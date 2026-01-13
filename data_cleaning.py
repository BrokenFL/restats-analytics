import pandas as pd
import numpy as np
import sqlite3
import logging
import os
import csv
import chardet
from datetime import datetime, timedelta

# --- 1. SETUP & CONFIGURATION ---

# Configure Logging
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    # File Handler
    file_handler = logging.FileHandler(os.path.join(log_dir, "cleaning.log"), mode='w')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(module)s - %(message)s'))
    logger.addHandler(file_handler)

    # Console Handler
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
    logger.addHandler(stream_handler)
    logger.propagate = False

# Fallback DataLoader
try:
    from data_loader import DataLoader
except ImportError:
    pass

# Data Dictionary for Normalization
data_dictionary = {
    "listing_number": {"original_name": "Listing Number", "data_type": "string"},
    "status": {"original_name": "Status", "data_type": "string"},
    "listing_date": {"original_name": "Listing Date", "data_type": "date"},
    "sold_date": {"original_name": "Sold Date", "data_type": "date"},
    "cancel_date": {"original_name": "Cancel Date", "data_type": "date"},
    "expiration_date": {"original_name": "Expiration Date", "data_type": "date"},
    "under_contract_date": {"original_name": "Under Contract Date", "data_type": "date"},
    "withdrawn_date": {"original_name": "Withdrawn Date", "data_type": "date"},
    "temp_off_market_date": {"original_name": "Temp Off Market Date", "data_type": "date"},
    "status_change_date": {"original_name": "Status Change Date", "data_type": "date"},
    "fallthrough_date": {"original_name": "Fallthrough Date", "data_type": "date"},
    "list_price": {"original_name": "List Price", "data_type": "float"},
    "sold_price": {"original_name": "Sold Price", "data_type": "float"},
    "original_list_price": {"original_name": "Original List Price", "data_type": "float"},
    "taxes": {"original_name": "Taxes", "data_type": "float"},
    "tax_year": {"original_name": "Tax Year", "data_type": "integer"},
    "hoa_poa_coa_monthly": {"original_name": "HOA/POA/COA (Monthly)", "data_type": "float"},
    "parcel_id": {"original_name": "Parcel ID", "data_type": "string"},
    "subdivision": {"original_name": "Subdivision", "data_type": "string"},
    "short_address": {"original_name": "Short Address", "data_type": "string"},
    "city": {"original_name": "City", "data_type": "string"},
    "zip_code": {"original_name": "Zip Code", "data_type": "string"},
    "sqft_living": {"original_name": "SqFt - Living", "data_type": "float"},
    "sqft_total": {"original_name": "SqFt - Total", "data_type": "float"},
    "year_built": {"original_name": "Year Built", "data_type": "integer"},
    "total_bedrooms": {"original_name": "Total Bedrooms", "data_type": "integer"},
    "baths_full": {"original_name": "Baths - Full", "data_type": "float"},
    "baths_half": {"original_name": "Baths - Half", "data_type": "float"},
    "waterfront": {"original_name": "Waterfront", "data_type": "boolean"},
    "private_pool": {"original_name": "Private Pool", "data_type": "boolean"},
    "garage_spaces": {"original_name": "Garage Spaces", "data_type": "float"},
    "unit_number": {"original_name": "Unit #", "data_type": "string"},
    "unit_floor": {"original_name": "Unit Floor #", "data_type": "float"},
    "total_floors_stories": {"original_name": "Total Floors/Stories", "data_type": "integer"},
    "property_type": {"original_name": "Type", "data_type": "string"},
    "terms_of_sale": {"original_name": "Terms of Sale", "data_type": "string"},
    # Derived Columns
    "effective_active_end_date": {"original_name": "effective_active_end_date", "data_type": "date"},
    "calculated_status": {"original_name": "calculated_status", "data_type": "string"},
    "is_zombie": {"original_name": "is_zombie", "data_type": "boolean"},
    "pcn_10_digit": {"original_name": "pcn_10_digit", "data_type": "string"},
    "final_subdivision": {"original_name": "final_subdivision", "data_type": "string"}
}

# --- 2. HELPER FUNCTIONS ---

def load_subdivision_lookups(lookup_folder="lookups"):
    """
    Loads specific cheatsheet CSVs to map PCN -> Unified_Group_Name.
    This creates a 'Golden Record' for subdivision names, correcting agent typos.
    """
    cheatsheets = [
        "boca_subdivision_audit_cheatsheet.csv",
        "wpb_subdivision_audit_cheatsheet.csv",
        "palmbeach_subdivision_audit_cheatsheet.csv",
        "delray_subdivision_audit_cheatsheet.csv",
        "wellington_subdivision_audit_cheatsheet.csv"
    ]
    pcn_map = {}
    for filename in cheatsheets:
        path = os.path.join(lookup_folder, filename)
        if not os.path.exists(path):
            path = filename 
        if os.path.exists(path):
            try:
                df = pd.read_csv(path, dtype=str)
                # Handle different column names across files
                unified_col = None
                if "Unified_Group_Name" in df.columns:
                    unified_col = "Unified_Group_Name"
                elif "Unified Subdivision" in df.columns:
                    unified_col = "Unified Subdivision"
                
                if "Master PCN" in df.columns and unified_col:
                    temp_map = pd.Series(
                        df[unified_col].str.strip().values, 
                        index=df["Master PCN"].str.strip()
                    ).to_dict()
                    pcn_map.update(temp_map)
                    logger.info(f"Loaded {len(temp_map)} mappings from {filename}")
                else:
                    logger.warning(f"Skipping {filename}: Missing required columns.")
            except Exception as e:
                logger.error(f"Error loading cheatsheet {filename}: {e}")
        else:
            logger.warning(f"Cheatsheet not found: {filename}")
    return pcn_map

def convert_boolean(val):
    """Safe conversion of various boolean string representations."""
    if pd.isna(val): return False
    val_str = str(val).strip().lower()
    return val_str in ['yes', 'y', 'true', '1', 't', 'complete', 'manned']

def normalize_subdivision_name(name):
    """Standardizes subdivision naming conventions (e.g., 'Ave' -> 'Avenue')."""
    if pd.isna(name): return None
    name = str(name).upper().strip().replace(".", "").replace(",", "")
    replacements = {
        "AVE": "AVENUE", "BLVD": "BOULEVARD", "ST": "STREET",
        "DR": "DRIVE", "LN": "LANE", "RD": "ROAD",
    }
    for key, val in replacements.items():
        if name.endswith(f" {key}"):
            name = name.replace(f" {key}", f" {val}")
    return name

def apply_global_pcn_grouping(df: pd.DataFrame) -> pd.DataFrame:
    """
    Business Logic: If a PCN is not in the cheatsheet, calculate the 'Mode' (most common)
    subdivision name for that PCN to ensure data consistency across records.
    """
    if 'pcn_10_digit' not in df.columns: return df
    
    if 'subdivision' in df.columns:
        df['temp_norm'] = df['subdivision'].apply(normalize_subdivision_name)
    else:
        df['temp_norm'] = pd.NA

    df['final_subdivision'] = df['final_subdivision'].fillna(df['temp_norm'])

    def _mode_or_first(series):
        m = series.mode()
        return m.iloc[0] if not m.empty else pd.NA

    pcn_modes = df.groupby('pcn_10_digit')['final_subdivision'].agg(_mode_or_first)
    df['final_subdivision'] = df['pcn_10_digit'].map(pcn_modes).fillna(df['final_subdivision'])
    
    if 'temp_norm' in df.columns:
        df.drop(columns=['temp_norm'], inplace=True)
    return df

# --- 3. TIMELINE LOGIC ---

def calculate_timeline_logic(row):
    """
    CRITICAL BUSINESS LOGIC:
    Calculates the 'Effective Active End Date' to determine true market supply.
    Identifies 'Zombie Listings' (Active status but expired date).
    """
    status = str(row.get('status', '')).upper().strip()
    dates = {
        'list': pd.to_datetime(row.get('listing_date'), errors='coerce'),
        'uc': pd.to_datetime(row.get('under_contract_date'), errors='coerce'),
        'sold': pd.to_datetime(row.get('sold_date'), errors='coerce'),
        'cancel': pd.to_datetime(row.get('cancel_date'), errors='coerce'),
        'withdraw': pd.to_datetime(row.get('withdrawn_date'), errors='coerce'),
        'expire': pd.to_datetime(row.get('expiration_date'), errors='coerce'),
        'change': pd.to_datetime(row.get('status_change_date'), errors='coerce'),
        'fallthrough': pd.to_datetime(row.get('fallthrough_date'), errors='coerce'),
        'temp_off': pd.to_datetime(row.get('temp_off_market_date'), errors='coerce')
    }

    # Impute UC date from fallthrough if missing
    if pd.isna(dates['uc']) and pd.notna(dates['fallthrough']):
        try:
            imputed_uc = dates['fallthrough'] - timedelta(days=7)
            if pd.notna(dates['list']) and imputed_uc < dates['list']:
                dates['uc'] = dates['list']
            else:
                dates['uc'] = imputed_uc
        except Exception: pass

    active_end_date = pd.NaT
    calc_status = status
    is_zombie = False

    # Logic tree for End Date determination
    if status in ['C', 'S', 'SOLD', 'CLOSED', 'P', 'PENDING', 'U', 'D', 'UNDER CONTRACT']:
        if pd.notna(dates['uc']): active_end_date = dates['uc']
        elif pd.notna(dates['sold']): active_end_date = dates['sold']
        elif pd.notna(dates['change']): active_end_date = dates['change']
    elif status in ['L', 'CANCELLED', 'CANCELED']:
        active_end_date = dates['cancel'] if pd.notna(dates['cancel']) else dates['change']
    elif status in ['W', 'WITHDRAWN']:
        active_end_date = dates['withdraw'] if pd.notna(dates['withdraw']) else dates['change']
    elif status in ['E', 'X', 'EXPIRED']:
        active_end_date = dates['expire'] if pd.notna(dates['expire']) else dates['change']
    elif status in ['T', 'O', 'TEMP OFF', 'TOM']:
        active_end_date = dates['temp_off'] if pd.notna(dates['temp_off']) else dates['change']
    elif status in ['A', 'ACTIVE', 'ACT']:
        # Zombie Check: Active but expired
        if pd.notna(dates['expire']) and dates['expire'] < pd.Timestamp.now():
            active_end_date = dates['expire']
            calc_status = 'X'
            is_zombie = True
        else:
            active_end_date = pd.NaT

    # Ensure end date is not before listing date
    if pd.notna(active_end_date) and pd.notna(dates['list']) and active_end_date < dates['list']:
        active_end_date = dates['list']

    return pd.Series([active_end_date, calc_status, is_zombie], 
                     index=['effective_active_end_date', 'calculated_status', 'is_zombie'])

# --- 4. CHUNK PROCESSING ---

def _process_chunk(df_chunk, lookup_dict):
    """Cleans a single chunk of data to optimize memory usage."""
    df = df_chunk.copy()

    # Rename & Type Casting
    rename_mapping = {info["original_name"]: norm_name for norm_name, info in data_dictionary.items() if info["original_name"] in df.columns}
    df.rename(columns=rename_mapping, inplace=True)

    for norm_name, info in data_dictionary.items():
        if norm_name not in df.columns: continue
        dtype = info["data_type"]
        if dtype == "float":
            df[norm_name] = pd.to_numeric(df[norm_name].astype(str).str.replace(r'[$,]', '', regex=True), errors='coerce')
        elif dtype == "integer":
            df[norm_name] = pd.to_numeric(df[norm_name].astype(str).str.replace(r'[$,]', '', regex=True), errors='coerce').round().astype('Int64')
        elif dtype == "date":
            df[norm_name] = pd.to_datetime(df[norm_name], errors='coerce')
        elif dtype == "boolean":
            df[norm_name] = df[norm_name].apply(convert_boolean)
        else:
            df[norm_name] = df[norm_name].astype(str).str.strip()

    # Apply Timeline Logic
    logic_results = df.apply(calculate_timeline_logic, axis=1)
    df = pd.concat([df, logic_results], axis=1)

    # Apply PCN Lookup (The Golden Record)
    if 'parcel_id' in df.columns:
        df['pcn_10_digit'] = df['parcel_id'].astype(str).str.replace(r'\D', '', regex=True).str.slice(0, 10)
        if lookup_dict:
            df['final_subdivision'] = df['pcn_10_digit'].map(lookup_dict)
            # Track if PCN was found in lookup (validated)
            df['pcn_validated'] = df['pcn_10_digit'].isin(lookup_dict.keys())
        else:
            df['final_subdivision'] = pd.NA
            df['pcn_validated'] = False
            
    # Fallback Normalization (for display only - pcn_validated stays False)
    if 'subdivision' in df.columns:
        df['normalized_subdivision'] = df['subdivision'].apply(normalize_subdivision_name)
        df['final_subdivision'] = df['final_subdivision'].fillna(df['normalized_subdivision'])

    # Clean Pricing Logic
    if 'sold_date' in df.columns and 'sold_price' in df.columns:
        df.loc[df['sold_date'].isna(), 'sold_price'] = np.nan

    # Penthouse Logic
    try:
        if 'unit_number' in df.columns and 'total_floors_stories' in df.columns:
            ph_mask = df['unit_number'].astype(str).str.upper().str.contains('PH', na=False)
            valid_ph_mask = ph_mask & df['total_floors_stories'].notna()
            if 'unit_floor' not in df.columns: df['unit_floor'] = pd.NA
            if valid_ph_mask.any():
                df.loc[valid_ph_mask, 'unit_floor'] = df.loc[valid_ph_mask, 'total_floors_stories'].astype('Float64')
    except Exception as e:
        logger.error(f"Error PH logic: {e}")

    return df

# --- 5. MAIN EXECUTION ---

def clean_csv(file_stream, lookup_dict):
    processed_chunks = []
    chunk_size = 50000
    try:
        reader = pd.read_csv(file_stream, dtype=str, low_memory=False, chunksize=chunk_size, on_bad_lines='warn')
        for chunk in reader:
            cleaned_chunk = _process_chunk(chunk, lookup_dict)
            if not cleaned_chunk.empty:
                processed_chunks.append(cleaned_chunk)
    except Exception as e:
        logger.error(f"Error reading CSV: {e}")
        return pd.DataFrame()
    
    if not processed_chunks: return pd.DataFrame()
    final_df = pd.concat(processed_chunks, ignore_index=True)
    for col in data_dictionary.keys():
        if col not in final_df.columns: final_df[col] = pd.NA
    return final_df

def process_and_load_data(csv_files, db_filename, create_new=False):
    """
    Orchestrates the Loading -> Cleaning -> Upserting workflow.
    """
    logger.info(f"Starting processing for DB: {db_filename}")
    lookup_map = load_subdivision_lookups()
    
    data_loader = DataLoader(db_filename)
    if not data_loader.create_connection(): return

    try:
        if create_new:
            data_loader.conn.execute("DROP TABLE IF EXISTS listing_details")
            data_loader.create_database()
        else:
            data_loader.create_database()
    except Exception as e:
        logger.error(f"Schema error: {e}")
        return

    if not isinstance(csv_files, list): csv_files = [csv_files]
    all_dfs = []

    for file_path in csv_files:
        if not os.path.exists(file_path): continue
        
        # Encoding detection
        enc = 'utf-8'
        try:
            with open(file_path, 'rb') as f:
                raw = f.read(50000)
                detected = chardet.detect(raw)
                if detected['confidence'] > 0.7: enc = detected['encoding']
        except: pass

        logger.info(f"Processing {os.path.basename(file_path)}...")
        try:
            with open(file_path, 'r', encoding=enc, errors='replace') as f:
                df_clean = clean_csv(f, lookup_map)
            if not df_clean.empty: all_dfs.append(df_clean)
        except Exception as e:
            logger.error(f"Failed {file_path}: {e}")

    if all_dfs:
        final_merged = pd.concat(all_dfs, ignore_index=True)
        # Deduplicate based on most recent update
        if 'listing_number' in final_merged.columns and 'status_change_date' in final_merged.columns:
            final_merged.sort_values(by=['listing_number', 'status_change_date'], ascending=[True, False], inplace=True)
            final_merged.drop_duplicates(subset=['listing_number'], keep='first', inplace=True)

        try:
            final_merged = apply_global_pcn_grouping(final_merged)
            logger.info("Applied global PCN grouping.")
        except Exception as e:
            logger.error(f"Grouping error: {e}")

        # Ensure schema alignment
        try:
            schema_df = pd.read_sql_query("PRAGMA table_info(listing_details);", data_loader.conn)
            db_columns = schema_df['name'].tolist()
        except:
            db_columns = list(final_merged.columns)

        for col in db_columns:
            if col not in final_merged.columns: final_merged[col] = pd.NA
        final_merged = final_merged[db_columns]

        logger.info(f"Inserting {len(final_merged)} records...")
        try:
            if create_new:
                data_loader.batch_insert_data(final_merged, 'listing_details')
            else:
                data_loader.upsert_data(final_merged, 'listing_details')
            logger.info("Complete.")
        except Exception as e:
            logger.error(f"Insert failed: {e}")

    data_loader.close_connection()

if __name__ == "__main__":
    pass
