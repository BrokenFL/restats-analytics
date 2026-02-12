"""
PBC Property Importer
Imports scraped PBC off-market sales data into the MLS database.
Includes duplicate checking (PCN + fuzzy date matching within 7 days).
"""

import sqlite3
import pandas as pd
import os
from datetime import datetime, timedelta

# Configuration
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mls.db')

# Geo Zone definitions (same as in data_cleaning.py)
GEO_ZONES = {
    'Palm Beach - South End': {
        'city': 'Palm Beach',
        'lat_max': 26.705  # South of Worth Ave area
    },
    'Palm Beach - North End': {
        'city': 'Palm Beach',
        'lat_min': 26.705
    }
}


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


def determine_geo_zone(lat, lon, city):
    """Determine geo zone based on lat/lon coordinates. Only tags South End."""
    if not lat or not lon:
        return None
    
    try:
        lat = float(lat)
        lon = float(lon)
    except:
        return None
    
    # Only tag South End (lat < 26.705), leave North End as NULL
    if city.upper() == 'PALM BEACH':
        if lat < 26.705:
            return 'South End'
    
    return None


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
    print(f"✓ Read {len(df)} records from CSV\n")
    
    # Connect to database
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    imported = 0
    skipped = 0
    errors = 0
    
    for idx, row in df.iterrows():
        try:
            # Get parcel ID (full PCN)
            parcel_number = str(row.get('Parcel Number', '')).replace('-', '').strip()
            sale_date = str(row.get('Sale Date', '')).strip()
            address = row.get('Location', '')
            
            if not parcel_number:
                print(f"  Skipping row {idx}: No parcel number")
                skipped += 1
                continue
            
            # Check for duplicate
            if is_duplicate(parcel_number, sale_date, existing_sales):
                print(f"  Skipping {parcel_number} ({address}) - duplicate in database")
                skipped += 1
                continue
            
            # Skip low-value transfer deeds (< $10,000)
            sale_price = clean_price(row.get('Sale Price'))
            if sale_price and sale_price < 10000:
                print(f"  Skipping {parcel_number} ({address}) - transfer deed (${sale_price:,.0f})")
                skipped += 1
                continue
            
            # Generate unique listing number for off-market sales
            listing_number = f"PBC-{parcel_number}"
            
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
                'city': row.get('Municipality', 'Palm Beach').title(),  # Normalize to title case
                'state_province': 'FL',
                'subdivision': row.get('Subdivision') if row.get('Subdivision') != 'N/A' else None,
                'final_subdivision': row.get('Subdivision') if row.get('Subdivision') != 'N/A' else None,
                'property_type': row.get('Property_Type') if row.get('Property_Type') != 'N/A' else None,
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
                record['city']
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
    
    conn.close()
    
    print(f"\n{'='*60}")
    print("IMPORT COMPLETE")
    print(f"{'='*60}")
    print(f"  Imported: {imported}")
    print(f"  Skipped (duplicates): {skipped}")
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
