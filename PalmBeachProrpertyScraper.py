import time
import os
import glob
import csv
import requests
import sys
import sqlite3
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURATION ---
DOWNLOAD_FOLDER = os.path.join(os.path.expanduser('~'), 'Downloads')
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mls.db')


def get_existing_sales_from_db():
    """
    Load existing PCN + Sale Date combinations from the database.
    Returns a dict: {parcel_id: [list of sold_dates], ...}
    Uses fuzzy date matching (within 7 days) since MLS and PBC dates may differ slightly.
    """
    existing = {}
    try:
        if not os.path.exists(DB_FILE):
            print(f"Note: Database not found at {DB_FILE}, will scrape all properties.")
            return existing
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Get all full PCN (parcel_id) + sold_date combinations
        cursor.execute("""
            SELECT parcel_id, DATE(sold_date) 
            FROM listing_details 
            WHERE parcel_id IS NOT NULL AND sold_date IS NOT NULL
        """)
        
        for row in cursor.fetchall():
            parcel_id = row[0]
            sold_date = row[1]
            if parcel_id and sold_date:
                # parcel_id is full 17-digit PCN, clean it
                clean_parcel = str(parcel_id).replace("-", "").strip()
                if clean_parcel not in existing:
                    existing[clean_parcel] = []
                existing[clean_parcel].append(sold_date)
        
        conn.close()
        total_sales = sum(len(dates) for dates in existing.values())
        print(f"✓ Loaded {total_sales} existing sales ({len(existing)} unique properties) from database")
        
    except Exception as e:
        print(f"Warning: Could not load existing sales from DB: {e}")
    
    return existing

def get_latest_csv():
    """Finds the most recently downloaded CSV file in the Downloads folder."""
    list_of_files = glob.glob(os.path.join(DOWNLOAD_FOLDER, '*.csv'))
    if not list_of_files:
        return None
    return max(list_of_files, key=os.path.getctime)

def clean_pcn(pcn_with_dashes):
    """Removes dashes from PCN to make it URL-ready."""
    return pcn_with_dashes.replace("-", "").strip()

def get_detail_value(driver, label):
    """
    Finds a cell in a table containing 'label' and returns the text of the NEXT cell.
    Works with both old and new PBC website structures.
    """
    try:
        # Try table cell format (old structure)
        xpath = f"//td[contains(., '{label}')]/following-sibling::td"
        element = driver.find_element(By.XPATH, xpath)
        value = element.text.strip()
        if value:
            return value
    except:
        pass
    
    try:
        # Try div/span format (new structure) - look for label in any element
        xpath = f"//*[contains(text(), '{label}')]/following-sibling::*"
        element = driver.find_element(By.XPATH, xpath)
        value = element.text.strip()
        if value:
            return value
    except:
        pass
    
    return ""  # Return empty string so 'or' logic works

def get_lat_long_arcgis(address, city):
    """
    Uses ArcGIS geocoder (no API key required, better rate limits than Nominatim).
    """
    try:
        base_url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
        full_address = f"{address}, {city}, FL"
        
        params = {
            'SingleLine': full_address,
            'f': 'json',
            'outFields': 'Match_addr',
            'maxLocations': 1
        }
        
        response = requests.get(base_url, params=params, timeout=10)
        data = response.json()
        
        if data.get('candidates') and len(data['candidates']) > 0:
            location = data['candidates'][0].get('location', {})
            lat = location.get('y', '')
            lon = location.get('x', '')
            return str(lat), str(lon)
        else:
            return "", "" 
    except Exception as e:
        print(f"   [Geo Error]: {e}")
        return "", ""


def get_lat_long_osm(address, city):
    """
    Fallback: Uses OpenStreetMap (Nominatim) to find Lat/Long.
    """
    try:
        base_url = "https://nominatim.openstreetmap.org/search"
        full_query = f"{address}, {city}, FL"
        
        params = {
            'q': full_query,
            'format': 'json',
            'limit': 1
        }
        
        headers = {
            'User-Agent': 'PBC_Property_Scraper_Script/1.0 (internal_tool)'
        }
        
        response = requests.get(base_url, params=params, headers=headers, timeout=5)
        data = response.json()
        
        if data and len(data) > 0:
            return data[0].get('lat'), data[0].get('lon')
        else:
            return "", "" 
    except Exception as e:
        print(f"   [Geo Error]: {e}")
        return "", ""

def scrape_property_details(driver, pcn):
    """Visits the detail page for a specific PCN and extracts structural info."""
    clean_id = clean_pcn(pcn)
    url = f"https://pbcpao.gov/Property/Details?parcelId={clean_id}"
    driver.get(url)
    
    # Wait for the main location label to ensure page loaded
    try:
        WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID, "MainContent_lblLocation")))
    except:
        print(f"   ! Timed out loading details for {pcn}")
        return {}

    details = {}
    
    # --- Structural Details ---
    details['Detail_Url'] = url
    details['Subdivision'] = get_detail_value(driver, "SUBDIVISION")
    # Try new PBC website labels first, fall back to old labels
    details['Bed_Rooms'] = get_detail_value(driver, "No of Bedroom") or get_detail_value(driver, "Bed Rooms")
    details['Full_Baths'] = get_detail_value(driver, "No of Bath(s)") or get_detail_value(driver, "Full Baths")
    details['Half_Baths'] = get_detail_value(driver, "No of Half Bath") or get_detail_value(driver, "Half Baths")
    details['Year_Built'] = get_detail_value(driver, "Year Built")
    # For condos, "Area" is the sqft; for single family, use "Area Under Air"
    area_value = get_detail_value(driver, "Area")
    if area_value and area_value != "N/A":
        details['Living_Area_SqFt'] = area_value
        details['Total_SqFt'] = area_value  # For condos, living = total
    else:
        details['Living_Area_SqFt'] = get_detail_value(driver, "Area Under Air")
        details['Total_SqFt'] = get_detail_value(driver, "Total Square Feet")
    details['Roof_Cover'] = get_detail_value(driver, "Roof Cover")
    details['AC_Desc'] = get_detail_value(driver, "Air Conditioning")
    details['Stories'] = get_detail_value(driver, "Stories")
    
    # --- Additional Fields ---
    # Property Use Code (e.g., "0100—SINGLE FAMILY")
    property_use_raw = get_detail_value(driver, "Property Use Code")
    details['Property_Use_Code'] = property_use_raw
    # Parse to get property type
    if "SINGLE FAMILY" in property_use_raw.upper():
        details['Property_Type'] = "Single Family"
    elif "CONDO" in property_use_raw.upper():
        details['Property_Type'] = "Condo"
    elif "TOWNHOUSE" in property_use_raw.upper():
        details['Property_Type'] = "Townhouse"
    elif "MULTI" in property_use_raw.upper() or "DUPLEX" in property_use_raw.upper():
        details['Property_Type'] = "Multi-Family"
    elif "VACANT" in property_use_raw.upper():
        details['Property_Type'] = "Vacant Land"
    else:
        details['Property_Type'] = property_use_raw
    
    # Acres (convert to sqft: 1 acre = 43560 sqft)
    acres_raw = get_detail_value(driver, "Acres")
    details['Acres'] = acres_raw
    try:
        acres_float = float(acres_raw.replace(",", ""))
        details['Lot_SqFt'] = int(acres_float * 43560)
    except:
        details['Lot_SqFt'] = "N/A"
    
    # Exterior Wall (construction type)
    details['Exterior_Wall'] = get_detail_value(driver, "Exterior Wall 1")
    
    return details

def run_scraper(target_city=None, start_date=None):
    # --- PHASE 0: USER INPUTS ---
    print("\n--- PBC Property Scraper Configuration ---")
    
    # Check for command line arguments first
    if len(sys.argv) >= 3:
        target_city = sys.argv[1]
        start_date = sys.argv[2]
    
    # 1. Get Municipality
    if not target_city:
        target_city = input("Enter Municipality (Press Enter for 'Palm Beach'): ").strip()
        if not target_city:
            target_city = "Palm Beach"
        
    # 2. Get Start Date
    default_date = (datetime.now() - timedelta(days=180)).strftime("%m/%d/%Y")
    if not start_date:
        start_date_input = input(f"Enter Start Date MM/DD/YYYY (Press Enter for {default_date}): ").strip()
        if not start_date_input:
            formatted_date = default_date
        else:
            try:
                datetime.strptime(start_date_input, "%m/%d/%Y")
                formatted_date = start_date_input
            except ValueError:
                print(f"Invalid date format! Defaulting to {default_date}")
                formatted_date = default_date
    else:
        formatted_date = start_date

    print(f"\n-> Starting Search for '{target_city}' sales since {formatted_date}...\n")

    # --- PHASE 1: SEARCH & DOWNLOAD ---
    
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless") 
    driver = webdriver.Chrome(options=options)
    
    try:
        # 1. Navigate and Search
        url = "https://pbcpao.gov/AdvSearch/SalesSearch"
        driver.get(url)
        driver.maximize_window()

        wait = WebDriverWait(driver, 15)
        
        # Wait for page to fully load
        time.sleep(2)
        
        # FIRST: Select "Municipalities" from the search type dropdown (defaults to Subdivisions)
        try:
            # Look for a dropdown that lets you choose between Subdivisions/Municipalities
            search_type_js = """
                var selects = document.querySelectorAll('select');
                for (var s of selects) {
                    for (var i = 0; i < s.options.length; i++) {
                        if (s.options[i].text.includes('Municipalit')) {
                            s.selectedIndex = i;
                            s.dispatchEvent(new Event('change'));
                            return s.id || 'found';
                        }
                    }
                }
                return null;
            """
            result = driver.execute_script(search_type_js)
            if result:
                print(f"✓ Switched to Municipalities search mode")
                time.sleep(2)  # Wait for Municipality dropdown to populate
        except Exception as e:
            print(f"Note: Could not find search type selector: {e}")
        
        wait.until(EC.presence_of_element_located((By.ID, "Municipality")))
        time.sleep(1)
        
        # SECOND: Select the specific Municipality
        try:
            # Use JavaScript to select the option
            js_select = f"""
                var select = document.getElementById('Municipality');
                for (var i = 0; i < select.options.length; i++) {{
                    if (select.options[i].text === '{target_city}') {{
                        select.selectedIndex = i;
                        select.dispatchEvent(new Event('change'));
                        return true;
                    }}
                }}
                return false;
            """
            result = driver.execute_script(js_select)
            if result:
                print(f"✓ Selected municipality: {target_city}")
            else:
                # Get available options via JS
                options_js = driver.execute_script("""
                    var select = document.getElementById('Municipality');
                    var opts = [];
                    for (var i = 0; i < select.options.length; i++) {
                        if (select.options[i].text.trim()) opts.push(select.options[i].text);
                    }
                    return opts;
                """)
                print(f"ERROR: Municipality '{target_city}' not found.")
                print(f"Available: {options_js[:20]}...")
                driver.quit()
                return
        except Exception as e:
            print(f"ERROR selecting municipality: {e}")
            driver.quit()
            return
        
        # Select "Qualified Sales" (QS)
        qs_radio = driver.find_element(By.CSS_SELECTOR, "input[value='QS']")
        driver.execute_script("arguments[0].click();", qs_radio)

        # Set Date based on USER INPUT
        date_input = driver.find_element(By.ID, "SaleDateFrom")
        date_input.clear()
        date_input.send_keys(formatted_date)

        # Click Search
        driver.execute_script("arguments[0].click();", driver.find_element(By.ID, "btnFormSearch"))
        print("✓ Search submitted...")
        
        # Wait for results to load (look for the results table or CSV button)
        time.sleep(5)  # Give search time to complete

        # Click CSV Export - try multiple selectors
        csv_button = None
        csv_selectors = [
            "//button[contains(., 'CSV')]",
            "//button[contains(text(), 'CSV')]",
            "//a[contains(., 'CSV')]",
            "//button[@title='CSV']",
            "//*[contains(@class, 'buttons-csv')]"
        ]
        
        for selector in csv_selectors:
            try:
                csv_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, selector))
                )
                if csv_button:
                    break
            except:
                continue
        
        if csv_button:
            driver.execute_script("arguments[0].click();", csv_button)
            print("✓ CSV Export clicked. Waiting for download...")
        else:
            # Check if there are any results at all
            try:
                no_results = driver.find_element(By.XPATH, "//*[contains(text(), 'No records')]")
                print(f"No results found for {target_city} since {formatted_date}")
            except:
                print("No CSV button found. The page structure may have changed.")
                # Take a screenshot for debugging
                driver.save_screenshot(os.path.join(DOWNLOAD_FOLDER, "debug_screenshot.png"))
                print(f"Screenshot saved to {DOWNLOAD_FOLDER}/debug_screenshot.png")
            driver.quit()
            return
        
        # Wait for file to appear (poll for up to 30 seconds)
        print("Waiting for CSV download to complete...")
        input_csv_path = None
        for _ in range(30):
            time.sleep(1)
            candidate = get_latest_csv()
            if candidate:
                # Check if file was modified in last 30 seconds (i.e., just downloaded)
                if time.time() - os.path.getctime(candidate) < 30:
                    input_csv_path = candidate
                    break
        
        if not input_csv_path:
            print("Error: Could not find the downloaded CSV file after 30 seconds.")
            return
        
        # --- PHASE 2: PROCESS CSV & ENHANCE ---

        print(f"✓ Found CSV: {input_csv_path}")
        print("--- 2. Extracting Property Details & Geocoding ---")
        
        # Output file name includes city and date for clarity
        safe_city = target_city.replace(" ", "_")
        safe_date = formatted_date.replace("/", "-")
        output_csv_path = os.path.join(DOWNLOAD_FOLDER, f"ENHANCED_{safe_city}_{safe_date}.csv")

        with open(input_csv_path, 'r', encoding='utf-8-sig') as f_in, \
             open(output_csv_path, 'w', newline='', encoding='utf-8') as f_out:
            
            reader = csv.DictReader(f_in)
            
            fieldnames = reader.fieldnames + [
                'Detail_Url', 'Subdivision', 'Bed_Rooms', 'Full_Baths', 
                'Half_Baths', 'Year_Built', 'Living_Area_SqFt', 
                'Total_SqFt', 'Roof_Cover', 'AC_Desc', 'Stories',
                'Property_Use_Code', 'Property_Type', 'Acres', 'Lot_SqFt',
                'Exterior_Wall', 'Latitude', 'Longitude'
            ]
            
            writer = csv.DictWriter(f_out, fieldnames=fieldnames)
            writer.writeheader()
            
            # Load existing sales from database to skip duplicates
            existing_sales = get_existing_sales_from_db()
            
            count = 0
            skipped = 0
            for row in reader:
                pcn = row.get('Parcel Number')
                if not pcn: 
                    keys = [k for k in row.keys() if 'Parcel' in k]
                    if keys: pcn = row[keys[0]]
                
                if pcn:
                    address = row.get('Location', '').strip()
                    municipality = row.get('Municipality', '').strip()
                    sale_date = row.get('Sale Date', '').strip()
                    
                    # Check if this PCN + Sale Date already exists in our database
                    # Use full PCN (parcel_id) for matching - remove dashes
                    clean_pcn_val = clean_pcn(pcn)  # Full PCN without dashes
                    
                    # Check for fuzzy date match (within 7 days)
                    is_duplicate = False
                    if clean_pcn_val in existing_sales and sale_date:
                        try:
                            pbc_date = datetime.strptime(sale_date, "%Y-%m-%d")
                            for db_date_str in existing_sales[clean_pcn_val]:
                                db_date = datetime.strptime(db_date_str, "%Y-%m-%d")
                                if abs((pbc_date - db_date).days) <= 7:
                                    is_duplicate = True
                                    break
                        except:
                            pass
                    
                    if is_duplicate:
                        print(f"Skipping {pcn} ({address}) - already in database")
                        skipped += 1
                        continue

                    print(f"Processing {pcn} ({address})...", end="", flush=True)
                    
                    try:
                        # 1. Scrape PBC Page
                        extra_data = scrape_property_details(driver, pcn)
                        
                        # 2. Geocode Address (ArcGIS primary, OSM fallback)
                        lat, lon = get_lat_long_arcgis(address, municipality)
                        if not lat or not lon:
                            lat, lon = get_lat_long_osm(address, municipality)
                        extra_data['Latitude'] = lat
                        extra_data['Longitude'] = lon

                        # 3. Combine All Data
                        full_row = {**row, **extra_data}
                        writer.writerow(full_row)
                        print(f" Done. (Lat: {lat}, Lon: {lon})")
                        
                    except Exception as e:
                        print(f" Error: {e}")
                        writer.writerow(row)
                    
                    count += 1
                    time.sleep(1.1) 
                else:
                    print("Skipping row (No PCN found)")

        print(f"\n✓ DONE! Processed {count} new properties, skipped {skipped} already in database.")
        print(f"  Enhanced spreadsheet saved to:\n  {output_csv_path}")
        
        # Post-process: Combine cabana + condo same-day sales
        print("\n--- 3. Checking for Cabana + Condo Same-Day Sales ---")
        final_path = combine_cabana_sales(output_csv_path)

    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        driver.quit()
        print("Browser closed.")

def combine_cabana_sales(csv_path):
    """
    Post-process CSV to combine cabana + condo sales that occurred on the same day.
    If a cabana and condo sold on the same date to the same owner, combine them:
    - Sum the sale prices
    - Keep the condo/main property as the primary record
    - Mark the cabana as combined
    """
    import pandas as pd
    
    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            return csv_path
        
        # Identify cabanas (usually have "CABANA" in property type or location)
        df['is_cabana'] = df.apply(lambda row: 
            'CABANA' in str(row.get('Property_Type', '')).upper() or
            'CABANA' in str(row.get('Location', '')).upper() or
            'CABANA' in str(row.get('Property_Use_Code', '')).upper(),
            axis=1
        )
        
        # Clean sale price for comparison
        df['Sale_Price_Clean'] = df['Sale Price'].apply(
            lambda x: float(str(x).replace('$', '').replace(',', '')) if pd.notna(x) else 0
        )
        
        # Group by Sale Date and Owner Name to find same-day sales
        combined_rows = []
        skip_indices = set()
        
        for idx, row in df.iterrows():
            if idx in skip_indices:
                continue
            
            if row['is_cabana']:
                # Look for a matching condo/main property on same date, same owner
                same_day = df[
                    (df['Sale Date'] == row['Sale Date']) &
                    (df['Owner Name'] == row['Owner Name']) &
                    (~df['is_cabana']) &
                    (df.index != idx)
                ]
                
                if not same_day.empty:
                    # Found a matching main property - skip this cabana row
                    # The main property will have the cabana price added to it
                    skip_indices.add(idx)
                    continue
            else:
                # This is a main property - check if there's a cabana to combine
                cabana_match = df[
                    (df['Sale Date'] == row['Sale Date']) &
                    (df['Owner Name'] == row['Owner Name']) &
                    (df['is_cabana']) &
                    (df.index != idx)
                ]
                
                if not cabana_match.empty:
                    # Combine cabana price into this property
                    cabana_price = cabana_match['Sale_Price_Clean'].sum()
                    combined_price = row['Sale_Price_Clean'] + cabana_price
                    row = row.copy()
                    row['Sale Price'] = f"${combined_price:,.0f}"
                    row['Combined_Cabana'] = 'Yes'
                    row['Cabana_Price'] = f"${cabana_price:,.0f}"
                    
                    # Mark cabana rows to skip
                    for cabana_idx in cabana_match.index:
                        skip_indices.add(cabana_idx)
            
            combined_rows.append(row)
        
        # Create new dataframe with combined sales
        if combined_rows:
            result_df = pd.DataFrame(combined_rows)
            # Drop helper columns
            result_df = result_df.drop(columns=['is_cabana', 'Sale_Price_Clean'], errors='ignore')
            
            # Save to new file
            combined_path = csv_path.replace('.csv', '_COMBINED.csv')
            result_df.to_csv(combined_path, index=False)
            
            cabanas_combined = len(skip_indices)
            if cabanas_combined > 0:
                print(f"✓ Combined {cabanas_combined} cabana sale(s) with main properties")
                print(f"  Saved to: {combined_path}")
            
            return combined_path
        
        return csv_path
        
    except Exception as e:
        print(f"Error combining cabana sales: {e}")
        return csv_path


if __name__ == "__main__":
    run_scraper()