"""
PBC Property Importer
Imports scraped PBC off-market sales data into the MLS database.
Includes duplicate checking (PCN + fuzzy date matching within 7 days).
"""

import sqlite3
import pandas as pd
import os
from datetime import datetime, timedelta
from property_type_utils import canonical_property_type
from geo_zone_utils import classify_palm_beach_zone_from_coords
from city_utils import canonical_city_name, normalize_city_values_in_db

# Configuration
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mls.db')

def get_existing_sales():
    """Load existing parcel_id + sold_date from database for duplicate checking."""
    existing = {}
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT parcel_id, DATE(sold_date) 
            FROM listing_details 
            WHERE parcel_id IS NOT NULL AND sold_date IS NOT NULL
        """)
        for row in cursor.fetchall():
            parcel_id = str(row[0]).replace("-", "").strip()
            sold_date = row[1]
            if parcel_id and sold_date:
                if parcel_id not in existing:
                    existing[parcel_id] = []
                existing[parcel_id].append(sold_date)
        conn.close()
    except Exception as e:
        print(f"Warning: Could not load existing sales: {e}")
    return existing


def is_duplicate(parcel_id, sale_date_str, existing_sales, days_threshold=7):
    """Check if this parcel + date is a duplicate (within days_threshold days)."""
    if parcel_id not in existing_sales:
        return False
    
    try:
        sale_date = datetime.strptime(sale_date_str, "%Y-%m-%d")
        for db_date_str in existing_sales[parcel_id]:
            db_date = datetime.strptime(db_date_str, "%Y-%m-%d")
            if abs((sale_date - db_date).days) <= days_threshold:
                return True
    except:
        pass
    return False


def normalize_sale_date(raw_date):
    """
    Normalize sale date to YYYY-MM-DD.
    Accepts common formats used by exports and recorder flows.
    """
    if raw_date is None:
        return None
    s = str(raw_date).strip()
    if not s or s.lower() == "nan":
        return None

    candidates = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y")
    for fmt in candidates:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue

    try:
        parsed = pd.to_datetime(s, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.strftime("%Y-%m-%d")
    except Exception:
        return None


def build_pbc_listing_number(parcel_number, sale_date_yyyy_mm_dd):
    """Build stable off-market identity key: PBC-<parcel>-<yyyymmdd>."""
    date_suffix = sale_date_yyyy_mm_dd.replace("-", "")
    return f"PBC-{parcel_number}-{date_suffix}"


def determine_geo_zone(lat, lon, city, short_address=None):
    """Determine Palm Beach geo zone for PBC imports using shared landmark bands."""
    try:
        lat = float(lat) if lat is not None else None
    except Exception:
        lat = None
    try:
        lon = float(lon) if lon is not None else None
    except Exception:
        lon = None
    return classify_palm_beach_zone_from_coords(lat, lon, city, short_address=short_address)


def clean_price(price_str):
    """Convert price string like '$1,234,567' to float."""
    if not price_str or price_str == 'N/A':
        return None
    try:
        return float(str(price_str).replace('$', '').replace(',', ''))
    except:
        return None


def clean_numeric(val):
    """Convert numeric string to float, handling N/A."""
    if not val or val == 'N/A':
        return None
    try:
        return float(str(val).replace(',', ''))
    except:
        return None


def clean_int(val):
    """Convert to integer, handling N/A."""
    if not val or val == 'N/A':
        return None
    try:
        return int(float(str(val).replace(',', '')))
    except:
        return None


def import_pbc_data(csv_path, dry_run=False):
    """
    Import PBC scraped data into the database.
    
    Args:
        csv_path: Path to the enhanced CSV file from PBC scraper
        dry_run: If True, just report what would be imported without actually inserting
    
    Returns:
        dict with counts of imported, skipped, errors
    """
    print(f"\n{'='*60}")
    print("PBC Off-Market Sales Importer")
    print(f"{'='*60}")
    print(f"CSV: {csv_path}")
    print(f"Database: {DB_FILE}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE IMPORT'}")
    print(f"{'='*60}\n")
    
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found: {csv_path}")
        return {'imported': 0, 'skipped': 0, 'errors': 0}
    
    # Load existing sales for duplicate checking
    existing_sales = get_existing_sales()
    print(f"✓ Loaded {sum(len(v) for v in existing_sales.values())} existing sales for duplicate check")
    
    # Read CSV
    df = pd.read_csv(csv_path)
    print(f"✓ Read {len(df)} records from CSV")

    # Fast pre-filter pass before expensive row mapping:
    # 1) missing parcel/date,
    # 2) duplicate parcel+date rows inside CSV,
    # 3) duplicates already present in DB (±7 day window).
    prefiltered_rows = []
    seen_row_keys = set()
    skipped_missing_key = 0
    skipped_csv_dupes = 0
    skipped_db_dupes = 0

    for idx, row in df.iterrows():
        parcel_number = str(row.get('Parcel Number', '')).replace('-', '').strip()
        sale_date_raw = row.get('Sale Date', '')
        sale_date = normalize_sale_date(sale_date_raw)
        if not parcel_number or not sale_date:
            skipped_missing_key += 1
            continue

        row_key = (parcel_number, sale_date)
        if row_key in seen_row_keys:
            skipped_csv_dupes += 1
            continue
        seen_row_keys.add(row_key)

        if is_duplicate(parcel_number, sale_date, existing_sales):
            skipped_db_dupes += 1
            continue

        prefiltered_rows.append((idx, row, parcel_number, sale_date))

    print(
        "✓ Pre-filter summary: "
        f"to_import={len(prefiltered_rows)} | "
        f"skipped_missing_key={skipped_missing_key} | "
        f"skipped_csv_dupes={skipped_csv_dupes} | "
        f"skipped_db_dupes={skipped_db_dupes}\n"
    )
    
    # Connect to database
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    imported = 0
    skipped = 0
    errors = 0
    
    for idx, row, parcel_number, sale_date in prefiltered_rows:
        try:
            # Get parcel ID (full PCN)
            address = row.get('Location', '')
            
            # Skip low-value transfer deeds (< $10,000)
            sale_price = clean_price(row.get('Sale Price'))
            if sale_price and sale_price < 10000:
                print(f"  Skipping {parcel_number} ({address}) - transfer deed (${sale_price:,.0f})")
                skipped += 1
                continue
            
            # Generate stable off-market listing identity (preserves repeat sales across time)
            listing_number = build_pbc_listing_number(parcel_number, sale_date)
            
            # Map fields
            record = {
                'listing_number': listing_number,
                'parcel_id': parcel_number,
                'pcn_10_digit': parcel_number[:10] if len(parcel_number) >= 10 else parcel_number,
                'pcn_validated': 1,  # PBC data has valid PCNs from county
                'status': 'C',  # Match MLS format
                'calculated_status': 'C',  # Match MLS format
                'sold_date': f"{sale_date}T00:00:00" if sale_date else None,  # Match MLS date format
                'listing_date': f"{sale_date}T00:00:00" if sale_date else None,  # Off-market: use sold_date
                'sold_price': sale_price,  # Already cleaned above
                'short_address': address,
                'city': canonical_city_name(row.get('Municipality')) or 'Palm Beach',
                'state_province': 'FL',
                'subdivision': row.get('Subdivision') if row.get('Subdivision') != 'N/A' else None,
                'final_subdivision': row.get('Subdivision') if row.get('Subdivision') != 'N/A' else None,
                'property_type': canonical_property_type(row.get('Property_Type')),
                'total_bedrooms': clean_int(row.get('Bed_Rooms')),
                'baths_full': clean_numeric(row.get('Full_Baths')),
                'baths_half': clean_numeric(row.get('Half_Baths')),
                'year_built': clean_int(row.get('Year_Built')),
                'sqft_living': clean_numeric(row.get('Living_Area_SqFt')),
                'sqft_total': clean_numeric(row.get('Total_SqFt')),
                'lot_sqft': clean_numeric(row.get('Lot_SqFt')),
                'total_floors_stories': clean_int(row.get('Stories')),
                'geo_lat': clean_numeric(row.get('Latitude')),
                'geo_lon': clean_numeric(row.get('Longitude')),
            }
            
            # Determine geo zone
            record['geo_zone'] = determine_geo_zone(
                record['geo_lat'], 
                record['geo_lon'], 
                record['city'],
                short_address=record.get('short_address'),
            )
            
            # Calculate baths_total
            full = record['baths_full'] or 0
            half = record['baths_half'] or 0
            record['baths_total'] = full + (half * 0.5) if (full or half) else None
            
            if dry_run:
                price_str = f"${record['sold_price']:,.0f}" if record['sold_price'] else "N/A"
                print(f"  Would import: {listing_number} | {address} | {price_str} | {sale_date}")
                imported += 1
            else:
                # Build INSERT OR REPLACE statement
                columns = ', '.join(record.keys())
                placeholders = ', '.join(['?' for _ in record])
                sql = f"INSERT OR REPLACE INTO listing_details ({columns}) VALUES ({placeholders})"
                
                cursor.execute(sql, list(record.values()))
                imported += 1
                # Update in-memory duplicate map so same-run duplicates are also blocked.
                existing_sales.setdefault(parcel_number, []).append(sale_date)
                
                if imported % 50 == 0:
                    print(f"  Imported {imported} records...")
                    conn.commit()
        
        except Exception as e:
            print(f"  Error on row {idx}: {e}")
            errors += 1
    
    if not dry_run:
        conn.commit()
        
        # Post-import: Populate subdivisions from PCN lookup
        print("\nPopulating subdivisions from PCN lookup...")
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE listing_details 
            SET final_subdivision = (
                SELECT DISTINCT ld2.final_subdivision 
                FROM listing_details ld2 
                WHERE ld2.pcn_10_digit = listing_details.pcn_10_digit 
                AND ld2.final_subdivision IS NOT NULL
                LIMIT 1
            )
            WHERE listing_number LIKE 'PBC-%' 
            AND final_subdivision IS NULL
            AND pcn_10_digit IN (
                SELECT DISTINCT pcn_10_digit FROM listing_details WHERE final_subdivision IS NOT NULL
            )
        """)
        print(f"  Updated {cursor.rowcount} records with subdivision from PCN lookup")
        conn.commit()

        normalized_cities = normalize_city_values_in_db(conn)
        if normalized_cities:
            print(f"  Normalized {normalized_cities} existing city labels")
    
    conn.close()
    
    print(f"\n{'='*60}")
    print("IMPORT COMPLETE")
    print(f"{'='*60}")
    print(f"  Imported: {imported}")
    print(f"  Skipped (duplicates/keys): {skipped + skipped_missing_key + skipped_csv_dupes + skipped_db_dupes}")
    print(
        f"    Details => in-loop skipped: {skipped}, "
        f"missing key: {skipped_missing_key}, csv dupes: {skipped_csv_dupes}, db dupes: {skipped_db_dupes}"
    )
    print(f"  Errors: {errors}")
    print(f"{'='*60}\n")
    
    return {'imported': imported, 'skipped': skipped, 'errors': errors}


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python pbc_importer.py <csv_path> [--dry-run]")
        print("\nExample:")
        print("  python pbc_importer.py ~/Downloads/ENHANCED_Palm_Beach_02-09-2024.csv --dry-run")
        print("  python pbc_importer.py ~/Downloads/ENHANCED_Palm_Beach_02-09-2024.csv")
        sys.exit(1)
    
    csv_path = sys.argv[1]
    dry_run = '--dry-run' in sys.argv
    
    import_pbc_data(csv_path, dry_run=dry_run)
