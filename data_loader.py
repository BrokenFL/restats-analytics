import sqlite3
import pandas as pd
import numpy as np
import logging
import os

# --- Register SQLite adapters ---
sqlite3.register_adapter(pd.Timestamp, lambda val: val.isoformat() if pd.notna(val) else None)
sqlite3.register_converter("timestamp", lambda val: pd.to_datetime(val.decode(), errors='coerce'))

# --- Logging Setup ---
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
logger = logging.getLogger(__name__)

if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(module)s - %(message)s')
    
    file_handler = logging.FileHandler(os.path.join(log_dir, "data_loader.log"), mode='w')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    logger.propagate = False

class DataLoader:
    def __init__(self, db_file):
        self.db_file = db_file
        self.conn = None

    def __enter__(self):
        self.create_connection()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_connection()

    def create_connection(self):
        if self.conn:
            return True
        try:
            self.conn = sqlite3.connect(
                self.db_file,
                timeout=20, # Increased timeout for larger merges
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
            )
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.execute("PRAGMA synchronous=NORMAL;")
            return True
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return False

    def close_connection(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def create_database(self):
        """Creates the table if it doesn't exist."""
        if not self.conn:
            if not self.create_connection(): return

        # Schema must match your data_cleaning.py output exactly
        create_sql = """
        CREATE TABLE IF NOT EXISTS listing_details (
            listing_number TEXT PRIMARY KEY,
            parcel_id TEXT,
            pcn_10_digit TEXT,
            status TEXT,
            calculated_status TEXT,
            is_zombie INTEGER,
            listing_date TIMESTAMP,
            effective_active_end_date TIMESTAMP,
            under_contract_date TIMESTAMP,
            sold_date TIMESTAMP,
            cancel_date TIMESTAMP,
            withdrawn_date TIMESTAMP,
            expiration_date TIMESTAMP,
            status_change_date TIMESTAMP,
            temp_off_market_date TIMESTAMP,
            fallthrough_date TIMESTAMP,
            list_price REAL,
            sold_price REAL,
            original_list_price REAL,
            taxes REAL,
            tax_year INTEGER,
            hoa_poa_coa_monthly REAL,
            membership_fee REAL,
            short_address TEXT,
            city TEXT,
            zip_code TEXT,
            state_province TEXT,
            subdivision TEXT,
            final_subdivision TEXT,
            development_name TEXT,
            street_number INTEGER,
            unit_number TEXT,
            unit_floor REAL,
            total_floors_stories INTEGER,
            property_type TEXT,
            sqft_living REAL,
            sqft_total REAL,
            sqft_guest_house REAL,
            lot_sqft REAL,
            year_built INTEGER,
            year_roof_installed INTEGER,
            total_bedrooms INTEGER,
            baths_full REAL,
            baths_half REAL,
            baths_total REAL,
            garage_spaces REAL,
            waterfront INTEGER,
            private_pool INTEGER,
            spa INTEGER,
            guest_house INTEGER,
            furnished INTEGER,
            gated_community INTEGER,
            construction_cbs INTEGER,
            storm_protection_accordion_shutters INTEGER,
            storm_protection_impact_glass INTEGER,
            storm_protection_panel_shutters INTEGER,
            subdiv_amenities_tennis INTEGER,
            subdiv_amenities_pool INTEGER,
            subdiv_amenities_manager_on_site INTEGER,
            subdiv_amenities_fitness_center INTEGER,
            subdiv_amenities_elevator INTEGER,
            subdiv_amenities_golf_course INTEGER,
            subdiv_amenities_clubhouse INTEGER,
            security_gate_manned INTEGER,
            security_gate_unmanned INTEGER,
            security_doorman INTEGER,
            security_lobby INTEGER,
            parking_garage_building INTEGER,
            parking_garage_detached INTEGER,
            parking_open INTEGER,
            parking_covered INTEGER,
            public_remarks TEXT,
            legal_desc TEXT,
            terms_of_sale TEXT,
            homeowners_assoc TEXT,
            listing_agent TEXT,
            listing_office TEXT,
            buyer_agent TEXT,
            buyer_office TEXT,
            days_on_market INTEGER,
            cumulative_dom INTEGER,
            geo_lat REAL,
            geo_lon REAL,
            pcn_validated INTEGER,
            cabana_flag INTEGER,
            geo_zone TEXT
        );
        """
        try:
            self.conn.execute(create_sql)
            # Additive schema migrations for existing databases.
            existing_cols = {
                row[1]
                for row in self.conn.execute("PRAGMA table_info(listing_details)").fetchall()
            }
            if "membership_fee" not in existing_cols:
                self.conn.execute("ALTER TABLE listing_details ADD COLUMN membership_fee REAL")
            if "cabana_flag" not in existing_cols:
                self.conn.execute("ALTER TABLE listing_details ADD COLUMN cabana_flag INTEGER DEFAULT 0")
            # Guardrail/performance indexes for duplicate checks and forensic audits.
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_listing_details_parcel_sold_date "
                "ON listing_details(parcel_id, sold_date);"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_listing_details_listing_number "
                "ON listing_details(listing_number);"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_listing_details_pcn10_sold_date "
                "ON listing_details(pcn_10_digit, sold_date);"
            )
        except Exception as e:
            logger.error(f"Error creating schema: {e}")

    def batch_insert_data(self, df, table_name, batch_size=1000):
        """
        Standard insert (append) for initial loads.
        """
        if df.empty:
            return

        if not self.conn:
            self.create_connection()

        try:
            # 1. Pre-process dataframe (Boolean/Date conversion)
            df_clean = df.copy()
            for col in df_clean.columns:
                # Handle Booleans
                if self.auto_detect_boolean(df_clean[col]):
                    df_clean[col] = df_clean[col].map({True: 1, False: 0, np.nan: None})
                # Handle Dates
                elif pd.api.types.is_datetime64_any_dtype(df_clean[col]):
                    df_clean[col] = df_clean[col].apply(lambda x: x.isoformat() if pd.notna(x) else None)

            # 2. Direct Append
            df_clean.to_sql(table_name, self.conn, if_exists='append', index=False, chunksize=batch_size)
            logger.info(f"Successfully batch inserted {len(df_clean)} rows.")

        except Exception as e:
            logger.error(f"Batch insert failed: {e}", exc_info=True)
            raise

    # ------------------------------------------------------
    # THE NEW UPSERT LOGIC
    # ------------------------------------------------------
    def upsert_data(self, df, table_name="listing_details"):
        """
        Inserts new records and updates existing records (based on Primary Key).
        """
        if df.empty:
            return

        if not self.conn:
            self.create_connection()

        try:
            # 1. Pre-process dataframe (Boolean/Date conversion)
            df_clean = df.copy()
            for col in df_clean.columns:
                # Handle Booleans
                if self.auto_detect_boolean(df_clean[col]):
                    df_clean[col] = df_clean[col].map({True: 1, False: 0, np.nan: None})
                # Handle Dates
                elif pd.api.types.is_datetime64_any_dtype(df_clean[col]):
                    df_clean[col] = df_clean[col].apply(lambda x: x.isoformat() if pd.notna(x) else None)

            # 2. Use a Temporary Table for the incoming data
            temp_table = "temp_listings_load"
            df_clean.to_sql(temp_table, self.conn, if_exists='replace', index=False)

            # 3. Perform SQL UPSERT (Insert or Replace)
            # This relies on listing_number being the PRIMARY KEY
            columns = ", ".join([f'"{c}"' for c in df_clean.columns])
            
            sql = f"""
            INSERT OR REPLACE INTO {table_name} ({columns})
            SELECT {columns} FROM {temp_table};
            """
            
            with self.conn:
                self.conn.execute(sql)
                self.conn.execute(f"DROP TABLE {temp_table};")
            
            logger.info(f"Successfully upserted {len(df_clean)} rows.")

        except Exception as e:
            logger.error(f"Upsert failed: {e}", exc_info=True)
            raise

    @staticmethod
    def auto_detect_boolean(series: pd.Series) -> bool:
        if str(series.dtype) in ("bool", "boolean"): return True
        unique_vals = set(series.dropna().unique())
        return unique_vals.issubset({0, 1, True, False, np.nan, None})

    def execute_read_query(self, query, params=None):
        if not self.conn: self.create_connection()
        return pd.read_sql_query(query, self.conn, params=params)
