import pandas as pd
import numpy as np
import sqlite3
import logging
import os
import csv
import re
import chardet
import glob
from datetime import datetime, timedelta
from property_type_utils import canonical_property_type_series
from geo_zone_utils import classify_palm_beach_zone
from cabana_utils import likely_cabana_mask

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
    "membership_fee": {"original_name": "Membership Fee", "data_type": "float"},
    "parcel_id": {"original_name": "Parcel ID", "data_type": "string"},
    "subdivision": {"original_name": "Subdivision", "data_type": "string"},
    "short_address": {"original_name": "Short Address", "data_type": "string"},
    "city": {"original_name": "City", "data_type": "string"},
    "zip_code": {"original_name": "Zip Code", "data_type": "string"},
    "state_province": {"original_name": "State Or Province", "data_type": "string"},
    "development_name": {"original_name": "Development Name", "data_type": "string"},
    "street_number": {"original_name": "Street Number", "data_type": "integer"},
    "sqft_living": {"original_name": "SqFt - Living", "data_type": "float"},
    "sqft_total": {"original_name": "SqFt - Total", "data_type": "float"},
    "sqft_guest_house": {"original_name": "Guest House Area Details: Living Area Guest House", "data_type": "float"},
    "lot_sqft": {"original_name": "Lot Size (SqFt)", "data_type": "float"},
    "year_built": {"original_name": "Year Built", "data_type": "integer"},
    "year_roof_installed": {"original_name": "Year Roof Installed", "data_type": "integer"},
    "total_bedrooms": {"original_name": "Total Bedrooms", "data_type": "integer"},
    "baths_full": {"original_name": "Baths - Full", "data_type": "float"},
    "baths_half": {"original_name": "Baths - Half", "data_type": "float"},
    "baths_total": {"original_name": "Baths Total", "data_type": "float"},
    "waterfront": {"original_name": "Waterfront", "data_type": "boolean"},
    "private_pool": {"original_name": "Private Pool", "data_type": "boolean"},
    "spa": {"original_name": "Spa", "data_type": "boolean"},
    "guest_house": {"original_name": "Guest House YN", "data_type": "boolean"},
    "furnished": {"original_name": "Furnished", "data_type": "boolean"},
    "gated_community": {"original_name": "Association Amenities: Gated", "data_type": "boolean"},
    "garage_spaces": {"original_name": "Garage Spaces", "data_type": "float"},
    "construction_cbs": {"original_name": "Construction Materials: CBS", "data_type": "boolean"},
    "storm_protection_accordion_shutters": {"original_name": "Storm Protection: Accordian Shutters", "data_type": "boolean"},
    "storm_protection_impact_glass": {"original_name": "Storm Protection: Impact Glass", "data_type": "boolean"},
    "storm_protection_panel_shutters": {"original_name": "Storm Protection: Panel Shutters", "data_type": "boolean"},
    "subdiv_amenities_tennis": {"original_name": "Association Amenities: Tennis Court(s)", "data_type": "boolean"},
    "subdiv_amenities_pool": {"original_name": "Association Amenities: Pool", "data_type": "boolean"},
    "subdiv_amenities_manager_on_site": {"original_name": "Association Amenities: Manager On Site", "data_type": "boolean"},
    "subdiv_amenities_fitness_center": {"original_name": "Association Amenities: Fitness Center", "data_type": "boolean"},
    "subdiv_amenities_elevator": {"original_name": "Association Amenities: Elevator(s)", "data_type": "boolean"},
    "subdiv_amenities_golf_course": {"original_name": "Association Amenities: Golf Course", "data_type": "boolean"},
    "subdiv_amenities_clubhouse": {"original_name": "Association Amenities: Clubhouse", "data_type": "boolean"},
    "security_gate_manned": {"original_name": "Security Features: Gated with Guard", "data_type": "boolean"},
    "security_gate_unmanned": {"original_name": "Security Features: Gated - No Guard", "data_type": "boolean"},
    "security_doorman": {"original_name": "Security Features: Key Card Entry", "data_type": "boolean"},
    "security_lobby": {"original_name": "Security Features: Lobby - Attended", "data_type": "boolean"},
    "parking_garage_building": {"original_name": "Parking Features: Garage", "data_type": "boolean"},
    "parking_garage_detached": {"original_name": "Parking Features: Detached Garage", "data_type": "boolean"},
    "parking_open": {"original_name": "Parking Features: Open", "data_type": "boolean"},
    "parking_covered": {"original_name": "Parking Features: Attached Garage", "data_type": "boolean"},
    "unit_number": {"original_name": "Unit #", "data_type": "string"},
    "unit_floor": {"original_name": "Unit Floor #", "data_type": "float"},
    "total_floors_stories": {"original_name": "Total Floors/Stories", "data_type": "integer"},
    "property_type": {"original_name": "Type", "data_type": "string"},
    "terms_of_sale": {"original_name": "Terms of Sale", "data_type": "string"},
    "buyer_financing": {"original_name": "Buyer Financing", "data_type": "string"},
    "geo_lat": {"original_name": "Geo Lat", "data_type": "float"},
    "geo_lon": {"original_name": "Geo Lon", "data_type": "float"},
    "public_remarks": {"original_name": "Public Remarks", "data_type": "string"},
    "legal_desc": {"original_name": "Legal", "data_type": "string"},
    "homeowners_assoc": {"original_name": "Homeowners Association", "data_type": "string"},
    "listing_agent": {"original_name": "Listing Member", "data_type": "string"},
    "listing_office": {"original_name": "Listing Office", "data_type": "string"},
    "buyer_agent": {"original_name": "Selling Member", "data_type": "string"},
    "buyer_office": {"original_name": "Selling Office", "data_type": "string"},
    "days_on_market": {"original_name": "Days On Market", "data_type": "integer"},
    "cumulative_dom": {"original_name": "Cumulative DOM", "data_type": "integer"},
    "pcn_validated": {"original_name": "pcn_validated", "data_type": "boolean"},
    "cabana_flag": {"original_name": "cabana_flag", "data_type": "boolean"},
    # Derived Columns
    "effective_active_end_date": {"original_name": "effective_active_end_date", "data_type": "date"},
    "calculated_status": {"original_name": "calculated_status", "data_type": "string"},
    "is_zombie": {"original_name": "is_zombie", "data_type": "boolean"},
    "pcn_10_digit": {"original_name": "pcn_10_digit", "data_type": "string"},
    "final_subdivision": {"original_name": "final_subdivision", "data_type": "string"},
    "geo_zone": {"original_name": "geo_zone", "data_type": "string"}
}

# Alternate MLS export headers (RAPB/Flex variants) -> normalized schema columns.
HEADER_ALIASES = {
    "List Date": "listing_date",
    "Listing Date": "listing_date",
    "Listing Contract Date": "listing_date",
    "Close Date": "sold_date",
    "Sold Date": "sold_date",
    "Close Price": "sold_price",
    "Sold Price": "sold_price",
    "Cancellation Date": "cancel_date",
    "Cancel Date": "cancel_date",
    "Expire Date": "expiration_date",
    "Expiration Date": "expiration_date",
    "Withdrawal Date": "withdrawn_date",
    "Withdrawn Date": "withdrawn_date",
    "Back on Market Date": "fallthrough_date",
    "Sold Terms": "terms_of_sale",
    "Terms of Sale": "terms_of_sale",
    "Buyer Fin": "buyer_financing",
    "Buyer Financing": "buyer_financing",
    "Property Type": "property_type",
    "Property Sub Type": "property_type",
    "Sub Type": "property_type",
    "Sub Type:": "property_type",
    "Type": "property_type",
    "Status": "status",
    "Status Change Date": "status_change_date",
    "Parcel Control #": "parcel_id",
    "Parcel ID": "parcel_id",
    "PCN#": "parcel_id",
    "Parcel Number": "parcel_id",
    "Postal Zip": "zip_code",
    "Zip Code": "zip_code",
    "State Or Province": "state_province",
    "Subdivision Name": "subdivision",
    "Development Name": "development_name",
    "Street Number": "street_number",
    "Living Area": "sqft_living",
    "SqFt - Living": "sqft_living",
    "Living Area Main": "sqft_living",
    "Building Area Main": "sqft_total",
    "# of Bedrooms": "total_bedrooms",
    "Beds Ttl": "total_bedrooms",
    "Beds Total": "total_bedrooms",
    "Bedrooms Total": "total_bedrooms",
    "Total Bedrooms": "total_bedrooms",
    "# of Baths": "baths_full",
    "Baths - Full": "baths_full",
    "Bathrooms Full": "baths_full",
    "Half Baths": "baths_half",
    "Baths - Half": "baths_half",
    "Bathrooms Half": "baths_half",
    "Baths Total": "baths_total",
    "Bathrooms Total": "baths_total",
    "# Floors": "total_floors_stories",
    "Total Floors/Stories": "total_floors_stories",
    "Stories Total": "total_floors_stories",
    "Maintenance Amount": "hoa_poa_coa_monthly",
    "HOA/POA/COA (Monthly)": "hoa_poa_coa_monthly",
    "Association Fee": "hoa_poa_coa_monthly",
    "Membership Fee": "membership_fee",
    "Membership Required Fee": "membership_fee",
    "Country Club Membership Fee": "membership_fee",
    "Membership Fee Amount": "membership_fee",
    "Remarks": "public_remarks",
    "Public Remarks": "public_remarks",
    "Legal": "legal_desc",
    "Tax Legal Description": "legal_desc",
    "Listing Member": "listing_agent",
    "Listing Agent": "listing_agent",
    "Listing Office": "listing_office",
    "Selling Member": "buyer_agent",
    "Buyer Agent": "buyer_agent",
    "Selling Office": "buyer_office",
    "Buyer Office": "buyer_office",
    "Apt #": "unit_number",
    "Unit Number": "unit_number",
    "Latitude": "geo_lat",
    "Longitude": "geo_lon",
    "Pool Private YN": "private_pool",
    "Guest House YN": "guest_house",
    "How Paid": "terms_of_sale",
}

LOOKUP_FILE_CITY_MAP = {
    "palmbeach_subdivision_audit_cheatsheet.csv": "Palm Beach",
    "southpalmbeach_subdivision_audit_cheatsheet.csv": "South Palm Beach",
    "wpb_subdivision_audit_cheatsheet.csv": "West Palm Beach",
    "bocaraton_subdivision_audit_cheatsheet.csv": "Boca Raton",
    "boca_subdivision_audit_cheatsheet.csv": "Boca Raton",
    "wellington_subdivision_audit_cheatsheet.csv": "Wellington",
    "delray_subdivision_audit_cheatsheet.csv": "Delray Beach",
}

# Geo zoning is centralized in geo_zone_utils.classify_palm_beach_zone
# and applied only for Palm Beach records.

# --- 2. HELPER FUNCTIONS ---

def load_subdivision_lookups(lookup_folder="lookups"):
    """
    Loads specific cheatsheet CSVs to map PCN -> Unified_Group_Name.
    This creates a 'Golden Record' for subdivision names, correcting agent typos.
    """
    cheatsheets = [
        "boca_subdivision_audit_cheatsheet.csv",
        "bocaraton_subdivision_audit_cheatsheet.csv",
        "wpb_subdivision_audit_cheatsheet.csv",
        "palmbeach_subdivision_audit_cheatsheet.csv",
        "delray_subdivision_audit_cheatsheet.csv",
        "wellington_subdivision_audit_cheatsheet.csv",
        "unincorporated_subdivision_audit_cheatsheet.csv",
    ]
    pcn_map = {}
    # Load all available cheatsheets in lookups folder first (prevents missing new files).
    for path in sorted(glob.glob(os.path.join(lookup_folder, "*_subdivision_audit_cheatsheet.csv"))):
        filename = os.path.basename(path)
        if filename not in cheatsheets:
            cheatsheets.append(filename)

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


def load_city_lookup_by_pcn(lookup_folder="lookups") -> dict:
    """
    Build PCN->City mapping from city-specific subdivision cheatsheets.
    """
    pcn_city = {}
    for path in sorted(glob.glob(os.path.join(lookup_folder, "*_subdivision_audit_cheatsheet.csv"))):
        filename = os.path.basename(path)
        city = LOOKUP_FILE_CITY_MAP.get(filename)
        if not city:
            continue
        try:
            df = pd.read_csv(path, dtype=str)
            if "Master PCN" not in df.columns:
                continue
            p = df["Master PCN"].astype(str).str.replace(r"\D", "", regex=True).str[:10]
            p = p[p.str.len() == 10]
            for key in p.tolist():
                if key not in pcn_city:
                    pcn_city[key] = city
        except Exception:
            continue
    return pcn_city


def load_property_type_overrides(lookup_folder="lookups"):
    """
    Load optional curated property-type overrides.

    Files:
    - property_type_subdivision_defaults.csv
    - property_type_parcel_overrides.csv
    """
    subdivision_defaults = {}
    parcel_overrides = {}

    subdivision_path = os.path.join(lookup_folder, "property_type_subdivision_defaults.csv")
    parcel_path = os.path.join(lookup_folder, "property_type_parcel_overrides.csv")

    if os.path.exists(subdivision_path):
        try:
            df = pd.read_csv(subdivision_path, dtype=str)
            sub_col = next((c for c in ["final_subdivision", "subdivision"] if c in df.columns), None)
            type_col = next((c for c in ["property_type", "recommended_property_type", "dominant_type"] if c in df.columns), None)
            if sub_col and type_col:
                rows = df[[sub_col, type_col]].dropna()
                for _, row in rows.iterrows():
                    sub = normalize_subdivision_name(row[sub_col])
                    prop_type = str(row[type_col]).strip()
                    if sub and prop_type:
                        subdivision_defaults[sub] = prop_type
                logger.info(f"Loaded {len(subdivision_defaults)} property-type subdivision defaults")
        except Exception as e:
            logger.error(f"Error loading property-type subdivision defaults: {e}")

    if os.path.exists(parcel_path):
        try:
            df = pd.read_csv(parcel_path, dtype=str)
            pcn_col = next((c for c in ["pcn_10_digit", "Master PCN", "parcel_id"] if c in df.columns), None)
            type_col = next((c for c in ["property_type", "recommended_property_type", "parcel_dominant_type"] if c in df.columns), None)
            if pcn_col and type_col:
                rows = df[[pcn_col, type_col]].dropna()
                for _, row in rows.iterrows():
                    pcn = str(row[pcn_col]).strip()
                    pcn = re.sub(r"\D", "", pcn)[:10]
                    prop_type = str(row[type_col]).strip()
                    if pcn and prop_type:
                        parcel_overrides[pcn] = prop_type
                logger.info(f"Loaded {len(parcel_overrides)} property-type parcel overrides")
        except Exception as e:
            logger.error(f"Error loading property-type parcel overrides: {e}")

    return subdivision_defaults, parcel_overrides

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
    elif status in ['H', 'COMING SOON', 'COMINGSOON']:
        # Coming soon / pre-market inventory should be retained in history
        # but should not count as active supply until it goes fully active.
        active_end_date = pd.NaT
        calc_status = 'H'
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

def _process_chunk(df_chunk, lookup_dict, property_type_overrides=None):
    """Cleans a single chunk of data to optimize memory usage."""
    df = df_chunk.copy()
    raw_property_sub_type = (
        df["Property Sub Type"].copy()
        if "Property Sub Type" in df.columns
        else pd.Series(pd.NA, index=df.index, dtype="object")
    )

    # Bring alternate source headers onto normalized names (RAPB/Flex variants).
    for src_col, norm_col in HEADER_ALIASES.items():
        if src_col in df.columns and norm_col not in df.columns:
            df[norm_col] = df[src_col]

    # FlexMLS 2026 exports no longer provide some legacy normalized fields directly.
    if "lot_sqft" not in df.columns and "Lot Size Acres" in df.columns:
        lot_acres = pd.to_numeric(df["Lot Size Acres"], errors="coerce")
        df["lot_sqft"] = lot_acres * 43560.0

    if "homeowners_assoc" not in df.columns:
        hoa = df.get("Association Type: Homeowner Association", pd.Series(index=df.index, dtype="object"))
        condo = df.get("Association Type: Condominium", pd.Series(index=df.index, dtype="object"))
        assoc = pd.Series(pd.NA, index=df.index, dtype="object")
        hoa_mask = hoa.astype(str).str.strip().ne("") & (~hoa.isna())
        condo_mask = condo.astype(str).str.strip().ne("") & (~condo.isna())
        assoc.loc[hoa_mask] = "Homeowner Association"
        assoc.loc[condo_mask] = "Condominium"
        if assoc.notna().any():
            df["homeowners_assoc"] = assoc

    # Rename & Type Casting
    rename_mapping = {info["original_name"]: norm_name for norm_name, info in data_dictionary.items() if info["original_name"] in df.columns}
    df.rename(columns=rename_mapping, inplace=True)
    # Guard against alias+rename collisions (e.g., Unit # and Apt # -> unit_number).
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()]

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
            nullish_mask = df[norm_name].str.lower().isin({"", "nan", "none", "nat", "<na>"})
            df.loc[nullish_mask, norm_name] = pd.NA

    # Normalize ambiguous RAPB "Residential" values using available structure hints.
    if 'property_type' in df.columns:
        nullish_tokens = {'', 'nan', 'none', '<na>'}
        raw_type = df['property_type'].astype(str).str.upper().str.strip()
        units_complex = pd.to_numeric(df.get('# Units in Complex', pd.Series(index=df.index)), errors='coerce')
        units_building = pd.to_numeric(df.get('Total Units In Building', pd.Series(index=df.index)), errors='coerce')
        units_community = pd.to_numeric(df.get('Number Of Units In Community', pd.Series(index=df.index)), errors='coerce')
        garage_spaces = pd.to_numeric(df.get('garage_spaces', df.get('Garage Spaces', pd.Series(index=df.index))), errors='coerce')
        lot_sqft = pd.to_numeric(df.get('lot_sqft', df.get('Lot Size (SqFt)', pd.Series(index=df.index))), errors='coerce')
        lot_acres = pd.to_numeric(df.get('Lot Size Acres', pd.Series(index=df.index)), errors='coerce')
        lot_dims = df.get('Lot Size Dimensions', pd.Series(index=df.index)).astype(str).str.strip()
        total_floors = pd.to_numeric(df.get('total_floors_stories', df.get('Stories Total', pd.Series(index=df.index))), errors='coerce')
        unit_number = df.get('unit_number', pd.Series(index=df.index)).astype(str).str.strip()
        has_unit = unit_number.notna() & (~unit_number.str.lower().isin(nullish_tokens))
        condo_assoc = df.get('Association Type: Condominium', pd.Series(index=df.index)).astype(str).str.upper().str.strip()
        hoa_assoc = df.get('Association Type: Homeowner Association', pd.Series(index=df.index)).astype(str).str.upper().str.strip()
        attached_garage = df.get('Parking Features: Attached Garage', pd.Series(index=df.index)).astype(str).str.upper().str.strip()
        garage_flag = garage_spaces.fillna(0).gt(0) | attached_garage.eq('YES')
        lot_flag = lot_acres.fillna(0).gt(0) | lot_sqft.fillna(0).gt(0) | (
            lot_dims.notna() & (~lot_dims.str.lower().isin(nullish_tokens))
        )

        residential_mask = raw_type.eq('RESIDENTIAL')
        condo_hint = (
            has_unit
            | (units_complex > 1)
            | (units_building > 1)
            | (units_community > 1)
            | condo_assoc.eq('YES')
        )
        sf_hint = (
            (~has_unit)
            & (~condo_hint)
            & (
                garage_flag
                | lot_flag
                | hoa_assoc.eq('YES')
                | total_floors.fillna(0).le(2)
                | ((units_complex.isna()) | (units_complex <= 1))
            )
        )
        df.loc[residential_mask & sf_hint, 'property_type'] = 'Single Family'
        df.loc[residential_mask & condo_hint, 'property_type'] = 'Condo'

    # Ensure baths_total is present even when export only gives full/half bath fields.
    if 'baths_total' not in df.columns:
        full = pd.to_numeric(df.get('baths_full', pd.Series(index=df.index)), errors='coerce')
        half = pd.to_numeric(df.get('baths_half', pd.Series(index=df.index)), errors='coerce')
        df['baths_total'] = full.fillna(0) + (half.fillna(0) * 0.5)

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

    if 'property_type' in df.columns and property_type_overrides:
        subdivision_defaults, parcel_overrides = property_type_overrides
        if subdivision_defaults and 'final_subdivision' in df.columns:
            sub_key = df['final_subdivision'].apply(normalize_subdivision_name)
            sub_types = sub_key.map(subdivision_defaults)
            df['property_type'] = df['property_type'].where(sub_types.isna(), sub_types)
        if parcel_overrides and 'pcn_10_digit' in df.columns:
            parcel_types = df['pcn_10_digit'].astype(str).str.replace(r'\D', '', regex=True).str[:10].map(parcel_overrides)
            df['property_type'] = parcel_types.fillna(df['property_type'])

    # Prefer MLS property subtype from AIDataSet exports when available.
    if raw_property_sub_type.notna().any():
        subtype_series = canonical_property_type_series(raw_property_sub_type)
        if 'property_type' in df.columns:
            df['property_type'] = subtype_series.combine_first(df['property_type'])
        else:
            df['property_type'] = subtype_series

    # Canonicalize property_type while preserving subtype detail.
    if 'property_type' in df.columns:
        df['property_type'] = canonical_property_type_series(df['property_type'])

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

    # Derived flag: keep cabanas in the database but label them so reporting can exclude them.
    df['cabana_flag'] = likely_cabana_mask(df).astype("Int64")

    return df


def _addr_norm(v):
    if pd.isna(v):
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(v).upper())


def _mls_canonical_rank(listing_number: str) -> int:
    """
    Lower is better. New FlexMLS `R...` records outrank legacy `RX-...` records.
    """
    s = str(listing_number).upper().strip()
    if re.fullmatch(r"R\d+", s):
        return 0
    if s.startswith("RX-"):
        return 1
    if s.startswith("AX-"):
        return 2
    if s.startswith("TX-"):
        return 3
    return 4


def _is_primary_mls(v) -> bool:
    return _mls_canonical_rank(v) <= 1


def _value_missing(v) -> bool:
    if pd.isna(v):
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    return False


def _status_group_for_match(status_value):
    u = str(status_value).upper().strip()
    if u in {"A", "ACTIVE", "ACT"}:
        return "ACTIVE"
    if u in {"P", "PENDING", "U", "UNDER CONTRACT", "D", "BACKUP"}:
        return "PENDING"
    return None


def backfill_incoming_from_existing_mls(conn, incoming_df, day_window_open=7, day_window_sold=1):
    """
    Before replacing weaker existing MLS rows with stronger incoming rows, preserve
    richer old values by filling only missing fields on the incoming record.
    """
    if incoming_df.empty:
        return incoming_df, 0, 0
    required = {"listing_number", "parcel_id"}
    if not required.issubset(set(incoming_df.columns)):
        return incoming_df, 0, 0

    work = incoming_df.copy()
    work["listing_date"] = pd.to_datetime(work.get("listing_date"), errors="coerce")
    work["sold_date"] = pd.to_datetime(work.get("sold_date"), errors="coerce")
    work["parcel_norm"] = work["parcel_id"].astype(str).str.replace(r"\D", "", regex=True)
    work["addr_norm"] = work.get("short_address", pd.Series(index=work.index, dtype="object")).map(_addr_norm)
    work["status_group"] = work.get("status", pd.Series(index=work.index, dtype="object")).map(_status_group_for_match)
    work["canonical_rank"] = work["listing_number"].map(_mls_canonical_rank)

    parcel_norms = sorted(
        {
            p for p in work["parcel_norm"].astype(str).tolist()
            if p and p != "nan" and len(p) >= 10
        }
    )
    if not parcel_norms:
        work.drop(columns=["parcel_norm", "addr_norm", "status_group", "canonical_rank"], inplace=True, errors="ignore")
        return work, 0, 0

    placeholders = ",".join(["?"] * len(parcel_norms))
    existing = pd.read_sql_query(
        f"""
        SELECT *
        FROM listing_details
        WHERE listing_number NOT LIKE 'PBC-%'
          AND substr(replace(replace(replace(replace(replace(replace(COALESCE(parcel_id, ''), '-', ''), ' ', ''), '.', ''), '/', ''), '_', ''), '#', ''), 1, 20)
              IN ({placeholders})
        """,
        conn,
        params=parcel_norms,
    )
    if existing.empty:
        work.drop(columns=["parcel_norm", "addr_norm", "status_group", "canonical_rank"], inplace=True, errors="ignore")
        return work, 0, 0

    existing["listing_date"] = pd.to_datetime(existing.get("listing_date"), errors="coerce")
    existing["sold_date"] = pd.to_datetime(existing.get("sold_date"), errors="coerce")
    existing["parcel_norm"] = existing["parcel_id"].astype(str).str.replace(r"\D", "", regex=True)
    existing["addr_norm"] = existing.get("short_address", pd.Series(index=existing.index, dtype="object")).map(_addr_norm)
    existing["status_group"] = existing.get("status", pd.Series(index=existing.index, dtype="object")).map(_status_group_for_match)
    existing["canonical_rank"] = existing["listing_number"].map(_mls_canonical_rank)

    protected_cols = {"listing_number", "canonical_rank", "parcel_norm", "addr_norm", "status_group"}
    fillable_cols = [c for c in existing.columns if c in work.columns and c not in protected_cols]

    rows_filled = 0
    fields_filled = 0
    for idx, row in work.iterrows():
        if row["canonical_rank"] > 1:
            continue
        if len(str(row["parcel_norm"])) < 10:
            continue

        hits = existing[
            (existing["parcel_norm"] == row["parcel_norm"])
            & (existing["listing_number"].astype(str) != str(row["listing_number"]))
            & (existing["canonical_rank"] > row["canonical_rank"])
        ].copy()
        if hits.empty:
            continue

        row_addr = row.get("addr_norm", "")
        hits = hits[
            hits["addr_norm"].eq("")
            | (row_addr == "")
            | hits["addr_norm"].eq(row_addr)
        ]
        if hits.empty:
            continue

        if pd.notna(row.get("sold_date")):
            hits = hits[hits["sold_date"].notna()].copy()
            if hits.empty:
                continue
            hits["date_diff"] = (hits["sold_date"] - row["sold_date"]).abs().dt.days
            hits = hits[hits["date_diff"] <= day_window_sold]
            if hits.empty:
                continue
        else:
            if pd.isna(row.get("listing_date")) or not row.get("status_group"):
                continue
            hits = hits[hits["listing_date"].notna() & hits["status_group"].eq(row["status_group"])].copy()
            if hits.empty:
                continue
            hits["date_diff"] = (hits["listing_date"] - row["listing_date"]).abs().dt.days
            hits = hits[hits["date_diff"] <= day_window_open]
            if hits.empty:
                continue

        hits["row_richness"] = hits[fillable_cols].notna().sum(axis=1)
        best = hits.sort_values(["canonical_rank", "date_diff", "row_richness"], ascending=[True, True, False]).iloc[0]

        filled_this_row = 0
        for col in fillable_cols:
            if _value_missing(work.at[idx, col]) and not _value_missing(best[col]):
                work.at[idx, col] = best[col]
                filled_this_row += 1

        if filled_this_row:
            rows_filled += 1
            fields_filled += filled_this_row

    if rows_filled:
        logger.info(f"Backfilled {fields_filled} missing values across {rows_filled} incoming MLS rows from weaker existing MLS matches.")

    work.drop(columns=["parcel_norm", "addr_norm", "status_group", "canonical_rank"], inplace=True, errors="ignore")
    return work, rows_filled, fields_filled


def dedupe_against_existing_offmarket(conn, incoming_df, day_window=7):
    """
    Cross-source duplicate guard:
    If incoming MLS sold rows match existing off-market rows on parcel + sold_date (±window),
    remove the older PBC row so MLS detail becomes the canonical record.
    """
    if incoming_df.empty:
        return incoming_df, 0
    required = {"listing_number", "parcel_id", "sold_date"}
    if not required.issubset(set(incoming_df.columns)):
        return incoming_df, 0

    work = incoming_df.copy()
    work["sold_date"] = pd.to_datetime(work["sold_date"], errors="coerce")
    work["parcel_norm"] = work["parcel_id"].astype(str).str.replace(r"\D", "", regex=True)
    work = work[
        work["sold_date"].notna()
        & work["parcel_norm"].str.len().ge(10)
        & (~work["listing_number"].astype(str).str.startswith("PBC-"))
    ]
    if work.empty:
        return incoming_df, 0

    existing = pd.read_sql_query(
        """
        SELECT listing_number, parcel_id, sold_date
        FROM listing_details
        WHERE listing_number LIKE 'PBC-%'
          AND sold_date IS NOT NULL
          AND parcel_id IS NOT NULL
        """,
        conn
    )
    if existing.empty:
        return incoming_df, 0

    existing["sold_date"] = pd.to_datetime(existing["sold_date"], errors="coerce")
    existing["parcel_norm"] = existing["parcel_id"].astype(str).str.replace(r"\D", "", regex=True)
    existing = existing[existing["sold_date"].notna() & existing["parcel_norm"].str.len().ge(10)]
    if existing.empty:
        return incoming_df, 0

    to_delete = set()
    for _, row in work.iterrows():
        hits = existing[existing["parcel_norm"] == row["parcel_norm"]]
        if hits.empty:
            continue
        deltas = (hits["sold_date"] - row["sold_date"]).abs().dt.days
        dupes = hits[deltas <= day_window]
        if not dupes.empty:
            to_delete.update(dupes["listing_number"].astype(str).tolist())

    if not to_delete:
        return incoming_df, 0

    placeholders = ",".join(["?"] * len(to_delete))
    conn.execute(f"DELETE FROM listing_details WHERE listing_number IN ({placeholders})", tuple(to_delete))
    conn.commit()
    logger.info(f"Removed {len(to_delete)} off-market rows replaced by incoming MLS matches.")
    return incoming_df, len(to_delete)


def drop_incoming_duplicates_against_existing_mls(conn, incoming_df, day_window=1):
    """
    Prevent duplicate closed transactions across MLS systems:
    drop incoming sold rows when an existing non-PBC row already matches
    parcel + sold_date (±day_window), with optional sold_price sanity match.
    """
    if incoming_df.empty:
        return incoming_df, 0
    required = {"listing_number", "parcel_id", "sold_date"}
    if not required.issubset(set(incoming_df.columns)):
        return incoming_df, 0

    work = incoming_df.copy()
    work["sold_date"] = pd.to_datetime(work["sold_date"], errors="coerce")
    work["sold_price"] = pd.to_numeric(work.get("sold_price"), errors="coerce")
    work["parcel_norm"] = work["parcel_id"].astype(str).str.replace(r"\D", "", regex=True)
    work["addr_norm"] = work.get("short_address", pd.Series(index=work.index, dtype="object")).map(_addr_norm)
    sold_mask = (
        work["sold_date"].notna()
        & work["parcel_norm"].str.len().ge(10)
        & (~work["listing_number"].astype(str).str.startswith("PBC-"))
    )
    sold_rows = work[sold_mask]
    if sold_rows.empty:
        return incoming_df, 0

    existing = pd.read_sql_query(
        """
        SELECT listing_number, parcel_id, sold_date, sold_price, short_address
        FROM listing_details
        WHERE listing_number NOT LIKE 'PBC-%'
          AND sold_date IS NOT NULL
          AND parcel_id IS NOT NULL
        """,
        conn
    )
    if existing.empty:
        return incoming_df, 0

    existing["sold_date"] = pd.to_datetime(existing["sold_date"], errors="coerce")
    existing["sold_price"] = pd.to_numeric(existing["sold_price"], errors="coerce")
    existing["parcel_norm"] = existing["parcel_id"].astype(str).str.replace(r"\D", "", regex=True)
    existing["addr_norm"] = existing["short_address"].map(_addr_norm)
    existing = existing[existing["sold_date"].notna() & existing["parcel_norm"].str.len().ge(10)]
    if existing.empty:
        return incoming_df, 0

    drop_indexes = set()
    delete_existing = set()
    for idx, row in sold_rows.iterrows():
        hits = existing[existing["parcel_norm"] == row["parcel_norm"]]
        if hits.empty:
            continue
        # Keep incoming row if it's the same listing_number already in DB;
        # allow upsert to refresh fields (e.g., city backfill on re-import).
        hits = hits[hits["listing_number"].astype(str) != str(row["listing_number"])]
        if hits.empty:
            continue
        deltas = (hits["sold_date"] - row["sold_date"]).abs().dt.days
        close_date_hits = hits[deltas <= day_window]
        if close_date_hits.empty:
            continue

        # Guardrail: placeholder parcel IDs can map to multiple real units.
        # If both rows have non-empty addresses, require address match.
        row_addr = row.get("addr_norm", "")
        close_date_hits = close_date_hits[
            close_date_hits["addr_norm"].eq("")
            | (row_addr == "")
            | close_date_hits["addr_norm"].eq(row_addr)
        ]
        if close_date_hits.empty:
            continue

        # If both have sold price, require close pricing to avoid suppressing true repeat sales.
        if pd.notna(row["sold_price"]):
            price_tol = max(5000.0, float(row["sold_price"]) * 0.01)
            price_hits = close_date_hits[
                close_date_hits["sold_price"].isna()
                | ((close_date_hits["sold_price"] - row["sold_price"]).abs() <= price_tol)
            ]
            if price_hits.empty:
                continue
            close_date_hits = price_hits

        incoming_ln = str(row["listing_number"])
        incoming_is_primary = _is_primary_mls(incoming_ln)
        incoming_rank = _mls_canonical_rank(incoming_ln)
        close_date_hits["is_primary_mls"] = close_date_hits["listing_number"].astype(str).map(_is_primary_mls)
        close_date_hits["canonical_rank"] = close_date_hits["listing_number"].astype(str).map(_mls_canonical_rank)

        if incoming_is_primary:
            # Preferred source rule: keep primary MLS rows and remove weaker matching rows.
            weaker_hits = close_date_hits[close_date_hits["canonical_rank"] > incoming_rank]
            if not weaker_hits.empty:
                delete_existing.update(weaker_hits["listing_number"].astype(str).tolist())
                continue
        else:
            # If a matching primary or stronger row exists in DB, drop incoming secondary duplicate.
            if (close_date_hits["canonical_rank"] <= incoming_rank).any():
                drop_indexes.add(idx)
                continue

        # If incoming is an RX and an R already exists, or incoming is a secondary row and
        # an equal/better row already exists, do not keep both.
        if (close_date_hits["canonical_rank"] <= incoming_rank).any():
            drop_indexes.add(idx)
            continue

        drop_indexes.add(idx)

    if delete_existing:
        placeholders = ",".join(["?"] * len(delete_existing))
        conn.execute(
            f"DELETE FROM listing_details WHERE listing_number IN ({placeholders})",
            tuple(sorted(delete_existing)),
        )
        conn.commit()
        logger.info(f"Removed {len(delete_existing)} existing secondary-feed rows replaced by incoming primary MLS rows.")

    if not drop_indexes:
        return incoming_df, 0
    deduped = incoming_df.drop(index=list(drop_indexes), errors="ignore").copy()
    logger.info(f"Dropped {len(drop_indexes)} incoming rows that match existing MLS transactions.")
    return deduped, len(drop_indexes)


def drop_internal_mls_transaction_duplicates(incoming_df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Dedupe within the incoming batch itself for MLS-vs-MLS feed overlap.
    Key: parcel + sold_date + sold_price (rounded) for non-PBC sold rows.
    Keeps one row per transaction using listing prefix priority and field richness.
    """
    if incoming_df.empty:
        return incoming_df, 0
    need = {"listing_number", "parcel_id", "sold_date", "sold_price"}
    if not need.issubset(set(incoming_df.columns)):
        return incoming_df, 0

    df = incoming_df.copy()
    df["sold_date"] = pd.to_datetime(df["sold_date"], errors="coerce")
    df["sold_price"] = pd.to_numeric(df["sold_price"], errors="coerce")
    df["parcel_norm"] = df["parcel_id"].astype(str).str.replace(r"\D", "", regex=True).str[:20]
    tx_mask = (
        (~df["listing_number"].astype(str).str.startswith("PBC-"))
        & df["sold_date"].notna()
        & df["sold_price"].notna()
        & (df["sold_price"] > 0)
        & df["parcel_norm"].str.len().ge(10)
    )
    tx = df[tx_mask].copy()
    if tx.empty:
        return incoming_df, 0

    tx["sold_dt"] = tx["sold_date"].dt.strftime("%Y-%m-%d")
    tx["sold_price_r"] = tx["sold_price"].round(0)
    tx["tx_key"] = tx["parcel_norm"] + "|" + tx["sold_dt"] + "|" + tx["sold_price_r"].astype(str)

    tx["prefix_rank"] = tx["listing_number"].map(_mls_canonical_rank)
    # Prefer richer rows when prefix ties.
    richness_cols = ["public_remarks", "legal_desc", "under_contract_date", "list_price", "original_list_price"]
    present_cols = [c for c in richness_cols if c in tx.columns]
    if present_cols:
        tx["row_richness"] = tx[present_cols].notna().sum(axis=1)
    else:
        tx["row_richness"] = 0

    tx_sorted = tx.sort_values(
        by=["tx_key", "prefix_rank", "row_richness", "listing_number"],
        ascending=[True, True, False, True],
    )
    keep_idx = tx_sorted.drop_duplicates(subset=["tx_key"], keep="first").index
    drop_idx = set(tx.index) - set(keep_idx)
    if not drop_idx:
        return incoming_df, 0

    out = incoming_df.drop(index=list(drop_idx), errors="ignore").copy()
    logger.info(f"Dropped {len(drop_idx)} internal incoming MLS transaction duplicates.")
    return out, len(drop_idx)


def drop_incoming_open_duplicates_against_existing_mls(conn, incoming_df, day_window=7):
    """
    Prevent open inventory duplication across MLS feeds:
    drop incoming non-sold rows when an existing non-PBC row already matches
    parcel + open-status-group + listing_date proximity.
    """
    if incoming_df.empty:
        return incoming_df, 0
    required = {"listing_number", "parcel_id", "status", "listing_date", "sold_date"}
    if not required.issubset(set(incoming_df.columns)):
        return incoming_df, 0

    active_codes = {"A", "ACTIVE", "ACT"}
    pending_codes = {"P", "PENDING", "U", "UNDER CONTRACT", "D", "BACKUP"}

    def status_group(s):
        u = str(s).upper().strip()
        if u in active_codes:
            return "ACTIVE"
        if u in pending_codes:
            return "PENDING"
        return None

    work = incoming_df.copy()
    work["listing_date"] = pd.to_datetime(work["listing_date"], errors="coerce")
    work["sold_date"] = pd.to_datetime(work["sold_date"], errors="coerce")
    work["parcel_norm"] = work["parcel_id"].astype(str).str.replace(r"\D", "", regex=True)
    work["status_group"] = work["status"].map(status_group)
    work["addr_norm"] = work.get("short_address", pd.Series(index=work.index, dtype="object")).map(_addr_norm)
    work = work[
        (~work["listing_number"].astype(str).str.startswith("PBC-"))
        & work["sold_date"].isna()
        & work["listing_date"].notna()
        & work["parcel_norm"].str.len().ge(10)
        & work["status_group"].notna()
    ]
    if work.empty:
        return incoming_df, 0

    existing = pd.read_sql_query(
        """
        SELECT listing_number, parcel_id, status, listing_date, sold_date, short_address
        FROM listing_details
        WHERE listing_number NOT LIKE 'PBC-%'
          AND parcel_id IS NOT NULL
          AND listing_date IS NOT NULL
          AND sold_date IS NULL
        """,
        conn,
    )
    if existing.empty:
        return incoming_df, 0
    existing["listing_date"] = pd.to_datetime(existing["listing_date"], errors="coerce")
    existing["sold_date"] = pd.to_datetime(existing["sold_date"], errors="coerce")
    existing["parcel_norm"] = existing["parcel_id"].astype(str).str.replace(r"\D", "", regex=True)
    existing["status_group"] = existing["status"].map(status_group)
    existing["addr_norm"] = existing.get("short_address", pd.Series(index=existing.index, dtype="object")).map(_addr_norm)
    existing = existing[
        existing["listing_date"].notna()
        & existing["parcel_norm"].str.len().ge(10)
        & existing["status_group"].notna()
    ]
    if existing.empty:
        return incoming_df, 0

    drop_idx = set()
    delete_existing = set()
    for idx, row in work.iterrows():
        hits = existing[
            (existing["parcel_norm"] == row["parcel_norm"])
            & (existing["status_group"] == row["status_group"])
            & (existing["listing_number"].astype(str) != str(row["listing_number"]))
        ]
        if hits.empty:
            continue
        row_addr = row.get("addr_norm", "")
        hits = hits[
            hits["addr_norm"].eq("")
            | (row_addr == "")
            | hits["addr_norm"].eq(row_addr)
        ]
        if hits.empty:
            continue
        day_diff = (hits["listing_date"] - row["listing_date"]).abs().dt.days
        matched = hits[day_diff <= day_window].copy()
        if matched.empty:
            continue

        incoming_rank = _mls_canonical_rank(row["listing_number"])
        matched["canonical_rank"] = matched["listing_number"].astype(str).map(_mls_canonical_rank)

        weaker = matched[matched["canonical_rank"] > incoming_rank]
        if not weaker.empty:
            delete_existing.update(weaker["listing_number"].astype(str).tolist())
            continue

        if (matched["canonical_rank"] <= incoming_rank).any():
            drop_idx.add(idx)

    if delete_existing:
        placeholders = ",".join(["?"] * len(delete_existing))
        conn.execute(
            f"DELETE FROM listing_details WHERE listing_number IN ({placeholders})",
            tuple(sorted(delete_existing)),
        )
        conn.commit()
        logger.info(f"Removed {len(delete_existing)} existing open MLS rows replaced by stronger incoming matches.")

    if not drop_idx:
        return incoming_df, 0
    out = incoming_df.drop(index=list(drop_idx), errors="ignore").copy()
    logger.info(f"Dropped {len(drop_idx)} incoming open-listing duplicates vs existing MLS rows.")
    return out, len(drop_idx)


def backfill_missing_city_in_db(conn) -> int:
    """
    One-pass DB backfill for existing rows with missing city using infer_missing_city logic.
    Returns number of rows updated.
    """
    rows = pd.read_sql_query(
        """
        SELECT listing_number, city, pcn_10_digit, geo_lat, geo_lon
        FROM listing_details
        WHERE city IS NULL OR TRIM(city) = ''
        """,
        conn,
    )
    if rows.empty:
        return 0
    inferred, _stats = infer_missing_city(conn, rows)
    to_update = inferred[
        inferred["city"].notna() & (~inferred["city"].astype(str).str.strip().eq(""))
    ][["listing_number", "city"]].copy()
    if to_update.empty:
        return 0
    updates = list(to_update.itertuples(index=False, name=None))
    conn.executemany("UPDATE listing_details SET city = ? WHERE listing_number = ?", [(c, l) for l, c in updates])
    conn.commit()
    return len(updates)


def infer_missing_city(conn, incoming_df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Infer missing city values for incoming MLS rows using:
    1) Existing DB PCN->city mode
    2) Geo fallback by nearest city centroid with distance guardrail
    """
    if incoming_df.empty or "city" not in incoming_df.columns:
        return incoming_df, {"filled_by_pcn": 0, "filled_by_geo": 0}

    df = incoming_df.copy()
    city_blank = df["city"].isna() | df["city"].astype(str).str.strip().eq("")

    filled_by_lookup = 0
    filled_by_pcn = 0
    # Stage 0: authoritative PCN -> city from lookup files.
    if "pcn_10_digit" in df.columns:
        lookup_city = load_city_lookup_by_pcn("lookups")
        df["pcn_10_digit"] = df["pcn_10_digit"].astype(str).str.replace(r"\D", "", regex=True).str[:10]
        if lookup_city:
            lk_mask = df["pcn_10_digit"].isin(lookup_city.keys()) & city_blank
            if lk_mask.any():
                df.loc[lk_mask, "city"] = df.loc[lk_mask, "pcn_10_digit"].map(lookup_city)
                filled_by_lookup = int(lk_mask.sum())

    # Stage 1: PCN -> city mode from existing DB records for remaining blanks.
    city_blank = df["city"].isna() | df["city"].astype(str).str.strip().eq("")
    if "pcn_10_digit" in df.columns and city_blank.any():
        db_city = pd.read_sql_query(
            """
            SELECT pcn_10_digit, city
            FROM listing_details
            WHERE pcn_10_digit IS NOT NULL
              AND TRIM(pcn_10_digit) <> ''
              AND city IS NOT NULL
              AND TRIM(city) <> ''
            """,
            conn,
        )
        if not db_city.empty:
            db_city["pcn_10_digit"] = db_city["pcn_10_digit"].astype(str).str.replace(r"\D", "", regex=True).str[:10]
            db_city = db_city[db_city["pcn_10_digit"].str.len() == 10]
            pcn_city_mode = db_city.groupby("pcn_10_digit")["city"].agg(
                lambda s: s.mode().iat[0] if not s.mode().empty else s.iloc[0]
            )
            pcn_fill_mask = city_blank & df["pcn_10_digit"].isin(pcn_city_mode.index)
            if pcn_fill_mask.any():
                df.loc[pcn_fill_mask, "city"] = df.loc[pcn_fill_mask, "pcn_10_digit"].map(pcn_city_mode)
                filled_by_pcn = int(pcn_fill_mask.sum())

    # Stage 2: Geo fallback by nearest centroid of known cities.
    city_blank = df["city"].isna() | df["city"].astype(str).str.strip().eq("")
    filled_by_geo = 0
    if city_blank.any() and {"geo_lat", "geo_lon"}.issubset(df.columns):
        known_geo = pd.read_sql_query(
            """
            SELECT city, geo_lat, geo_lon
            FROM listing_details
            WHERE city IS NOT NULL
              AND TRIM(city) <> ''
              AND geo_lat IS NOT NULL
              AND geo_lon IS NOT NULL
            """,
            conn,
        )
        if not known_geo.empty:
            known_geo["geo_lat"] = pd.to_numeric(known_geo["geo_lat"], errors="coerce")
            known_geo["geo_lon"] = pd.to_numeric(known_geo["geo_lon"], errors="coerce")
            # Keep plausible South Florida coordinates only.
            known_geo = known_geo[
                known_geo["geo_lat"].between(25.0, 28.5)
                & known_geo["geo_lon"].between(-81.0, -79.0)
            ]
            # Remove tiny groups to avoid noisy centroids.
            city_counts = known_geo["city"].value_counts()
            valid_cities = city_counts[city_counts >= 25].index
            known_geo = known_geo[known_geo["city"].isin(valid_cities)]
            centroids = known_geo.groupby("city")[["geo_lat", "geo_lon"]].mean()

            if not centroids.empty:
                import numpy as _np

                def _haversine_miles(lat1, lon1, lat2, lon2):
                    r = 3958.8
                    lat1, lon1, lat2, lon2 = map(_np.radians, [lat1, lon1, lat2, lon2])
                    dlat = lat2 - lat1
                    dlon = lon2 - lon1
                    a = _np.sin(dlat / 2) ** 2 + _np.cos(lat1) * _np.cos(lat2) * _np.sin(dlon / 2) ** 2
                    return 2 * r * _np.arctan2(_np.sqrt(a), _np.sqrt(1 - a))

                target = df[city_blank].copy()
                target["geo_lat"] = pd.to_numeric(target["geo_lat"], errors="coerce")
                target["geo_lon"] = pd.to_numeric(target["geo_lon"], errors="coerce")
                geo_ok = target["geo_lat"].between(25.0, 28.5) & target["geo_lon"].between(-81.0, -79.0)
                target = target[geo_ok]

                if not target.empty:
                    cent_city = centroids.index.tolist()
                    cent_lat = centroids["geo_lat"].to_numpy()
                    cent_lon = centroids["geo_lon"].to_numpy()

                    assign = {}
                    for idx, row in target.iterrows():
                        d = _haversine_miles(row["geo_lat"], row["geo_lon"], cent_lat, cent_lon)
                        best_i = int(_np.argmin(d))
                        best_city = cent_city[best_i]
                        best_dist = float(d[best_i])
                        # Guardrail: only assign when reasonably close to nearest centroid.
                        if best_dist <= 12.0:
                            assign[idx] = best_city
                    if assign:
                        df.loc[list(assign.keys()), "city"] = pd.Series(assign)
                        filled_by_geo = len(assign)

    return df, {
        "filled_by_lookup": filled_by_lookup,
        "filled_by_pcn": filled_by_pcn,
        "filled_by_geo": filled_by_geo,
    }


def correct_rapb_city_from_lookup(conn, lookup_folder="lookups") -> dict:
    """
    Correct existing RAPB rows using authoritative lookup-based PCN city mapping.
    """
    pcn_city = load_city_lookup_by_pcn(lookup_folder)
    if not pcn_city:
        return {"updated": 0, "mismatches_fixed": 0}
    rows = pd.read_sql_query(
        """
        SELECT listing_number, city, pcn_10_digit
        FROM listing_details
        WHERE listing_number GLOB '[0-9][0-9]-*'
        """,
        conn,
    )
    if rows.empty:
        return {"updated": 0, "mismatches_fixed": 0}

    rows["pcn"] = rows["pcn_10_digit"].astype(str).str.replace(r"\D", "", regex=True).str[:10]
    rows["lookup_city"] = rows["pcn"].map(pcn_city)
    rows = rows[rows["lookup_city"].notna()]
    if rows.empty:
        return {"updated": 0, "mismatches_fixed": 0}
    cur_city = rows["city"].fillna("").astype(str).str.strip().str.upper()
    tgt_city = rows["lookup_city"].fillna("").astype(str).str.strip().str.upper()
    fix = rows[cur_city != tgt_city].copy()
    if fix.empty:
        return {"updated": 0, "mismatches_fixed": 0}

    updates = [(r.lookup_city, r.listing_number) for r in fix.itertuples(index=False)]
    conn.executemany("UPDATE listing_details SET city = ? WHERE listing_number = ?", updates)
    conn.commit()
    return {"updated": len(updates), "mismatches_fixed": len(updates)}

# --- 5. MAIN EXECUTION ---

def clean_csv(file_stream, lookup_dict, property_type_overrides=None):
    processed_chunks = []
    chunk_size = 50000
    try:
        reader = pd.read_csv(file_stream, dtype=str, low_memory=False, chunksize=chunk_size, on_bad_lines='warn')
        for chunk in reader:
            cleaned_chunk = _process_chunk(chunk, lookup_dict, property_type_overrides)
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
    property_type_overrides = load_property_type_overrides()
    
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
                df_clean = clean_csv(f, lookup_map, property_type_overrides)
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

        # Apply geo zones (Palm Beach landmark bands)
        try:
            if 'geo_lat' in final_merged.columns and 'city' in final_merged.columns:
                final_merged['geo_zone'] = final_merged.apply(
                    lambda r: classify_palm_beach_zone(
                        r.get('geo_lat'),
                        r.get('city'),
                        short_address=r.get('short_address'),
                    ),
                    axis=1
                )
            else:
                final_merged['geo_zone'] = None
            logger.info("Applied geo zones.")
        except Exception as e:
            logger.error(f"Geo zone error: {e}")

        # Ensure schema alignment
        try:
            schema_df = pd.read_sql_query("PRAGMA table_info(listing_details);", data_loader.conn)
            db_columns = schema_df['name'].tolist()
        except:
            db_columns = list(final_merged.columns)

        # Fill missing city values for RAPB-style exports using PCN and geo inferences.
        try:
            final_merged, city_fill_stats = infer_missing_city(data_loader.conn, final_merged)
            logger.info(
                "City inference filled missing values: "
                f"LOOKUP={city_fill_stats.get('filled_by_lookup', 0)}, "
                f"PCN={city_fill_stats.get('filled_by_pcn', 0)}, "
                f"GEO={city_fill_stats.get('filled_by_geo', 0)}"
            )
        except Exception as e:
            logger.error(f"City inference error: {e}")

        # Preserve richer values from weaker old MLS rows before an incoming R-record replaces them.
        try:
            final_merged, inherited_rows, inherited_fields = backfill_incoming_from_existing_mls(
                data_loader.conn, final_merged, day_window_open=7, day_window_sold=1
            )
            if inherited_rows:
                logger.info(
                    f"Incoming MLS preservation filled {inherited_fields} fields across "
                    f"{inherited_rows} rows from existing MLS matches."
                )
        except Exception as e:
            logger.error(f"Incoming MLS preservation error: {e}")

        # Cross-source dedupe: prefer incoming MLS row over old PBC duplicate by parcel+sold_date window.
        try:
            final_merged, dropped_internal = drop_internal_mls_transaction_duplicates(final_merged)
            if dropped_internal:
                logger.info(f"Internal incoming dedupe dropped {dropped_internal} MLS rows.")

            final_merged, dropped_existing_open = drop_incoming_open_duplicates_against_existing_mls(
                data_loader.conn, final_merged, day_window=7
            )
            if dropped_existing_open:
                logger.info(f"Open-listing dedupe dropped {dropped_existing_open} incoming rows.")

            final_merged, dropped_existing_mls = drop_incoming_duplicates_against_existing_mls(
                data_loader.conn, final_merged, day_window=1
            )
            if dropped_existing_mls:
                logger.info(f"Transaction dedupe dropped {dropped_existing_mls} incoming MLS rows already in DB.")

            final_merged, removed_pbc = dedupe_against_existing_offmarket(data_loader.conn, final_merged, day_window=7)
            if removed_pbc:
                logger.info(f"Cross-source dedupe removed {removed_pbc} existing PBC rows.")
        except Exception as e:
            logger.error(f"Cross-source dedupe error: {e}")

        for col in db_columns:
            if col not in final_merged.columns: final_merged[col] = pd.NA
        final_merged = final_merged[db_columns]

        logger.info(f"Inserting {len(final_merged)} records...")
        try:
            if create_new:
                data_loader.batch_insert_data(final_merged, 'listing_details')
            else:
                data_loader.upsert_data(final_merged, 'listing_details')
            rapb_city_fix = correct_rapb_city_from_lookup(data_loader.conn, "lookups")
            if rapb_city_fix.get("updated"):
                logger.info(f"RAPB city correction updated {rapb_city_fix['updated']} rows via lookup PCN mapping.")
            # Also backfill older rows still missing city after upsert.
            updated_city = backfill_missing_city_in_db(data_loader.conn)
            if updated_city:
                logger.info(f"City backfill updated {updated_city} existing rows.")
            logger.info("Complete.")
        except Exception as e:
            logger.error(f"Insert failed: {e}")

    data_loader.close_connection()

if __name__ == "__main__":
    pass
