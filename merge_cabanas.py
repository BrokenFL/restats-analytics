#!/usr/bin/env python3
"""
Merge cabana sales with their corresponding condo sales in the database.
Cabanas sold within 7 days of condos at same building should be combined.

Matching logic:
1. Same building (street number + street name)
2. Within 7 days of each other
3. Either same price (recorded twice) OR cabana price <= 20% of condo price
4. Cabana identified by: C prefix, CS prefix, 0### unit, STG, PK, no beds/sqft
"""

import sqlite3
import re
from datetime import datetime, timedelta

DB_FILE = "mls.db"
EXCLUDED_CABANA_BUILDINGS = {
    "235 SUNRISE AVENUE",  # Palm Beach Hotel
    "235 SUNRISE AVE",     # Palm Beach Hotel (abbrev)
}

def get_building(addr):
    """Extract building address (number + street name)."""
    addr = addr.upper()
    match = re.match(r'^(\d+)\s+([NSEW]?\s*\w+\s+(?:BLVD|AVE|RD|DR|WAY|PL|ROW|LN|CT|CIRCLE))', addr)
    if match:
        return f'{match.group(1)} {match.group(2).strip()}'
    parts = addr.split()
    if len(parts) >= 3:
        return ' '.join(parts[:3])
    return addr

def is_cabana_address(addr):
    """Check if address looks like a cabana/parking/storage."""
    addr = addr.upper()
    # Keep this strict so normal condo units like C3034 are not treated as cabanas.
    has_c = bool(re.search(r'\bC(?:\s|-)?\d{1,3}\b', addr))
    has_cs = bool(re.search(r'\bCS\d{1,3}\b', addr))  # CS4 = Cabana South 4
    has_zero_unit = re.search(r' 0\d{2,3}$', addr)  # Unit like 0120, 0050
    has_stg = 'STG' in addr or ' PK ' in addr or 'STORAGE' in addr or 'PARKING' in addr
    has_cabana_word = 'CABANA' in addr
    return has_c or has_cs or has_zero_unit or has_stg or has_cabana_word

def is_excluded_building(building):
    b = building.upper().strip()
    if b in EXCLUDED_CABANA_BUILDINGS:
        return True
    if b.startswith("235 SUNRISE AVE") or b.startswith("235 SUNRISE AVENUE"):
        return True
    return False

def is_likely_cabana(record):
    """Check if record is likely a cabana based on multiple signals."""
    addr = record.get('addr', '').upper()
    beds = record.get('beds')
    sqft = record.get('sqft')
    price = record.get('price', 0)
    
    # Strong signals
    if is_cabana_address(addr):
        return True
    
    # 0 bedrooms with small sqft is likely cabana
    if (beds == 0 or beds is None) and sqft and sqft < 400:
        return True
    
    # Very low price relative to Palm Beach (<$500k) with no beds
    if price < 500000 and (beds == 0 or beds is None):
        return True
    
    return False

def parse_date(d):
    """Parse date string to datetime."""
    if not d:
        return None
    try:
        return datetime.strptime(d[:10], '%Y-%m-%d')
    except:
        return None

def find_cabana_pairs():
    """Find condo+cabana pairs sold within 7 days in same building."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Get ALL records (PBC and MLS) not already merged
    cursor.execute("""
        SELECT listing_number, short_address, sold_date, sold_price, total_bedrooms, sqft_living
        FROM listing_details 
        WHERE sold_price IS NOT NULL
        AND sold_price > 10000
        AND short_address NOT LIKE '%& Cabana%'
        AND short_address NOT LIKE '%& 2 Cabana%'
        ORDER BY sold_date, short_address
    """)
    records = cursor.fetchall()
    
    # Group by building
    by_building = {}
    for ln, addr, sold_date, price, beds, sqft in records:
        bldg = get_building(addr)
        if bldg not in by_building:
            by_building[bldg] = []
        by_building[bldg].append({
            'ln': ln, 'addr': addr, 'date': sold_date, 'price': price or 0,
            'beds': beds, 'sqft': sqft
        })
    
    pairs = []
    for bldg, sales in by_building.items():
        if is_excluded_building(bldg):
            continue
        if len(sales) < 2:
            continue
        
        # Identify cabanas using improved detection
        cabanas = [s for s in sales if is_likely_cabana(s)]
        # Condos are records with beds OR significant sqft that aren't cabana addresses
        condos = [s for s in sales if (s['beds'] and s['beds'] > 0) or (s['sqft'] and s['sqft'] >= 500 and not is_cabana_address(s['addr']))]
        
        for cab in cabanas:
            cab_date = parse_date(cab['date'])
            if not cab_date:
                continue
            
            for condo in condos:
                condo_date = parse_date(condo['date'])
                if not condo_date:
                    continue
                
                # Within 7 days
                days_diff = abs((cab_date - condo_date).days)
                if days_diff > 7:
                    continue
                
                # Same price OR cabana is <= 20% of condo price
                price_match = cab['price'] == condo['price'] and cab['price'] > 0
                price_ratio = cab['price'] / condo['price'] if condo['price'] > 0 else 0
                
                if price_match or (price_ratio <= 0.20 and price_ratio > 0):
                    pairs.append({
                        'condo_ln': condo['ln'],
                        'condo_addr': condo['addr'],
                        'condo_price': condo['price'],
                        'cabana_ln': cab['ln'],
                        'cabana_addr': cab['addr'],
                        'cabana_price': cab['price'],
                        'sold_date': condo['date'],
                        'days_diff': days_diff,
                        'price_match': price_match
                    })
    
    conn.close()
    return pairs

def merge_cabana_pairs(pairs, dry_run=True):
    """Merge cabana sales into condo records."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    merged = 0
    for pair in pairs:
        condo_ln = pair['condo_ln']
        cabana_ln = pair['cabana_ln']
        condo_price = pair['condo_price'] or 0
        cabana_price = pair['cabana_price'] or 0
        days_diff = pair.get('days_diff', 0)
        price_match = pair.get('price_match', condo_price == cabana_price)
        
        # If prices are identical, they recorded the same total twice - just use one
        if price_match:
            combined_price = condo_price  # Don't double count
            price_note = f"SAME ${condo_price:,.0f}"
        else:
            combined_price = condo_price + cabana_price
            price_note = f"${condo_price:,.0f} + ${cabana_price:,.0f} = ${combined_price:,.0f}"
        
        # Update condo address to include cabana reference
        new_addr = f"{pair['condo_addr']} & Cabana"
        
        days_note = f"({days_diff}d apart)" if days_diff > 0 else "(same day)"
        print(f"  Merging: {pair['condo_addr']} + {pair['cabana_addr']} {days_note}")
        print(f"    Price: {price_note}")
        
        if not dry_run:
            # Update condo record with combined price and new address
            cursor.execute("""
                UPDATE listing_details 
                SET sold_price = ?, short_address = ?
                WHERE listing_number = ?
            """, (combined_price, new_addr, condo_ln))
            
            # Delete cabana record
            cursor.execute("DELETE FROM listing_details WHERE listing_number = ?", (cabana_ln,))
            
            merged += 1
    
    if not dry_run:
        conn.commit()
    conn.close()
    
    return merged

def check_beds_baths():
    """Check how many PBC records have beds/baths populated."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM listing_details WHERE listing_number LIKE 'PBC-%'")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM listing_details WHERE listing_number LIKE 'PBC-%' AND total_bedrooms IS NOT NULL")
    with_beds = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM listing_details WHERE listing_number LIKE 'PBC-%' AND baths_full IS NOT NULL")
    with_baths = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM listing_details WHERE listing_number LIKE 'PBC-%' AND sqft_living IS NOT NULL")
    with_sqft = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM listing_details WHERE listing_number LIKE 'PBC-%' AND year_built IS NOT NULL")
    with_year = cursor.fetchone()[0]
    
    print(f"\nPBC Record Details Coverage:")
    print(f"  Total records: {total}")
    print(f"  With bedrooms: {with_beds} ({100*with_beds/total:.1f}%)")
    print(f"  With baths: {with_baths} ({100*with_baths/total:.1f}%)")
    print(f"  With sqft: {with_sqft} ({100*with_sqft/total:.1f}%)")
    print(f"  With year_built: {with_year} ({100*with_year/total:.1f}%)")
    
    conn.close()

if __name__ == "__main__":
    import sys
    
    print("Finding cabana+condo pairs...")
    pairs = find_cabana_pairs()
    print(f"Found {len(pairs)} pairs to merge\n")
    
    if pairs:
        if "--merge" in sys.argv:
            print("MERGING cabana+condo pairs:")
            merged = merge_cabana_pairs(pairs, dry_run=False)
            print(f"\nMerged {merged} pairs!")
        else:
            print("DRY RUN - Preview of merges:")
            merge_cabana_pairs(pairs, dry_run=True)
            print("\nTo actually merge, run with --merge flag")
    
    check_beds_baths()
