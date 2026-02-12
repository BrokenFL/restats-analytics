#!/usr/bin/env python3
"""
Re-scrape missing beds/baths/sqft for PBC records that are missing these details.
"""

import sqlite3
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

DB_FILE = "mls.db"

def get_detail_value(driver, label):
    """
    Finds a cell in a table containing 'label' and returns the text of the NEXT cell.
    Works with the new PBC website table structure.
    """
    try:
        # New PBC structure: table rows with td[1]=label, td[2]=value
        # Use exact text match for the first td, then get the second td
        xpath = f"//table/tbody/tr/td[normalize-space(text())='{label}']/following-sibling::td[1]"
        element = driver.find_element(By.XPATH, xpath)
        value = element.text.strip()
        if value:
            return value
    except:
        pass
    
    try:
        # Try contains for partial matches
        xpath = f"//table/tbody/tr/td[contains(text(), '{label}')]/following-sibling::td[1]"
        element = driver.find_element(By.XPATH, xpath)
        value = element.text.strip()
        # Make sure we're not grabbing a huge block of text
        if value and len(value) < 100:
            return value
    except:
        pass
    
    return None

def scrape_property_details(driver, pcn):
    """Visits the detail page for a specific PCN and extracts structural info."""
    clean_id = pcn.replace("-", "").strip()
    url = f"https://pbcpao.gov/Property/Details?parcelId={clean_id}"
    driver.get(url)
    
    # Wait for page to fully load - the building details table takes time
    time.sleep(3)
    
    # Wait for the building info table to appear
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//table//tr/td[contains(text(), 'Year Built')]"))
        )
    except:
        # Table might not exist for this property
        pass
    
    details = {}
    
    # Try new PBC website labels - exact matches from the table
    details['Bed_Rooms'] = get_detail_value(driver, "No of Bedroom(s)")
    details['Full_Baths'] = get_detail_value(driver, "No of Bath(s)")
    details['Half_Baths'] = get_detail_value(driver, "No of Half Bath(s)")
    
    # For condos, "Area" is the sqft
    details['Living_Area_SqFt'] = get_detail_value(driver, "Area")
    details['Total_SqFt'] = details['Living_Area_SqFt']  # Same for condos
    
    # Also get subdivision name
    details['Subdivision'] = get_detail_value(driver, "Name")
    
    return details

def clean_numeric(value):
    """Convert string to numeric, return None if not valid."""
    if not value:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except:
        return None

def main():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Get PBC records missing beds/baths
    cursor.execute("""
        SELECT listing_number, parcel_id, short_address 
        FROM listing_details 
        WHERE listing_number LIKE 'PBC-%' 
        AND (total_bedrooms IS NULL OR baths_full IS NULL OR sqft_living IS NULL)
    """)
    records = cursor.fetchall()
    
    print(f"Found {len(records)} PBC records missing details")
    
    if not records:
        print("Nothing to update!")
        return
    
    # Start browser
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless")
    driver = webdriver.Chrome(options=options)
    
    updated = 0
    errors = 0
    
    try:
        for i, (listing_number, parcel_id, address) in enumerate(records):
            print(f"[{i+1}/{len(records)}] Scraping {address}...")
            
            try:
                details = scrape_property_details(driver, parcel_id)
                
                beds = clean_numeric(details.get('Bed_Rooms'))
                baths = clean_numeric(details.get('Full_Baths'))
                half_baths = clean_numeric(details.get('Half_Baths'))
                sqft = clean_numeric(details.get('Living_Area_SqFt'))
                total_sqft = clean_numeric(details.get('Total_SqFt'))
                
                subdivision = details.get('Subdivision')
                
                if beds or baths or sqft or subdivision:
                    cursor.execute("""
                        UPDATE listing_details 
                        SET total_bedrooms = COALESCE(?, total_bedrooms),
                            baths_full = COALESCE(?, baths_full),
                            baths_half = COALESCE(?, baths_half),
                            sqft_living = COALESCE(?, sqft_living),
                            sqft_total = COALESCE(?, sqft_total),
                            final_subdivision = COALESCE(?, final_subdivision)
                        WHERE listing_number = ?
                    """, (beds, baths, half_baths, sqft, total_sqft, subdivision, listing_number))
                    
                    print(f"   Updated: Beds={beds}, Baths={baths}, SqFt={sqft}, Sub={subdivision}")
                    updated += 1
                else:
                    print(f"   No data found")
                
                # Rate limit
                time.sleep(1)
                
                # Commit every 10 records
                if updated % 10 == 0:
                    conn.commit()
                    
            except Exception as e:
                print(f"   Error: {e}")
                errors += 1
    
    finally:
        driver.quit()
        conn.commit()
        conn.close()
    
    print(f"\nDone! Updated {updated} records, {errors} errors")

if __name__ == "__main__":
    main()
