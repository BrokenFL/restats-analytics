import time
import os
import glob
import csv
import requests
import sys
import sqlite3
import argparse
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURATION ---
DOWNLOAD_FOLDER = os.path.join(os.path.expanduser('~'), 'Downloads')
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mls.db')


def parse_mmddyyyy(date_str):
    """Validate and normalize MM/DD/YYYY input."""
    if not date_str:
        return None
    dt = datetime.strptime(date_str.strip(), "%m/%d/%Y")
    return dt.strftime("%m/%d/%Y")


def get_last_imported_pbc_sale_date(target_city=None):
    """
    Returns latest sold_date for PBC-imported rows.
    If city is provided, filters by that city.
    """
    if not os.path.exists(DB_FILE):
        return None

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        city_filter = target_city.strip().title() if target_city else None
        if city_filter:
            cursor.execute(
                """
                SELECT MAX(DATE(sold_date))
                FROM listing_details
                WHERE listing_number LIKE 'PBC-%'
                  AND city = ?
                  AND sold_date IS NOT NULL
                """,
                (city_filter,)
            )
        else:
            cursor.execute(
                """
                SELECT MAX(DATE(sold_date))
                FROM listing_details
                WHERE listing_number LIKE 'PBC-%'
                  AND sold_date IS NOT NULL
                """
            )

        row = cursor.fetchone()
        conn.close()
        if not row or not row[0]:
            return None
        latest = datetime.strptime(row[0], "%Y-%m-%d")
        return latest
    except Exception as e:
        print(f"Warning: Could not read last imported PBC sold date: {e}")
        return None


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

def _switch_to_municipality_mode(driver):
    """
    Attempt to switch search type from subdivisions to municipalities.
    Works across minor DOM changes.
    """
    try:
        search_type_js = """
            var selects = document.querySelectorAll('select');
            for (var s of selects) {
                var hasMunicipality = false;
                var hasSubdivision = false;
                var municipalityIdx = -1;
                for (var i = 0; i < s.options.length; i++) {
                    var txt = (s.options[i].text || '').toLowerCase();
                    if (txt.includes('municipalit')) {
                        hasMunicipality = true;
                        municipalityIdx = i;
                    }
                    if (txt.includes('subdiv')) {
                        hasSubdivision = true;
                    }
                }
                if (hasMunicipality && (hasSubdivision || municipalityIdx >= 0)) {
                    s.selectedIndex = municipalityIdx;
                    s.dispatchEvent(new Event('change', { bubbles: true }));
                    return s.id || 'search-type-select';
                }
            }
            return null;
        """
        result = driver.execute_script(search_type_js)
        if result:
            print("✓ Switched to Municipalities search mode")
            time.sleep(2)
    except Exception as e:
        print(f"Note: Could not switch search mode automatically: {e}")


def _force_click_municipality_mode(driver):
    """
    Fallbacks for UIs where municipality mode is a tab/radio/button rather than select.
    """
    # Recorder-confirmed path: municipality radio is input[2] with value MUNI.
    try:
        muni_js = """
            var el = document.evaluate(
                "/html/body/main/div/div/div/form/div/div[2]/div/input[2]",
                document,
                null,
                XPathResult.FIRST_ORDERED_NODE_TYPE,
                null
            ).singleNodeValue;
            if (el) {
                el.click();
                el.checked = true;
                if (el.value !== 'MUNI') { el.value = 'MUNI'; }
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }
            return false;
        """
        if driver.execute_script(muni_js):
            time.sleep(0.6)
            return True
    except Exception:
        pass

    selector_candidates = [
        (By.CSS_SELECTOR, "input[type='radio'][value='MUNI']"),
        (By.ID, "Municipality"),
        (By.ID, "Municipalities"),
        (By.CSS_SELECTOR, "input[value*='Municip']"),
        (By.CSS_SELECTOR, "button[id*='Municip']"),
        (By.CSS_SELECTOR, "a[id*='Municip']"),
        (By.XPATH, "//*[contains(normalize-space(text()), 'Municipality')]"),
        (By.XPATH, "//*[contains(normalize-space(text()), 'Municipalities')]"),
    ]

    for by, sel in selector_candidates:
        try:
            elems = driver.find_elements(by, sel)
            for elem in elems:
                try:
                    driver.execute_script("arguments[0].click();", elem)
                    time.sleep(0.4)
                    return True
                except Exception:
                    continue
        except Exception:
            continue
    return False


def _wait_for_municipality_options(driver, timeout_sec=12):
    """Wait until Municipality select has real options."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            elem = driver.find_element(By.ID, "Municipality")
            options = Select(elem).options
            real = [o.text.strip() for o in options if o.text and o.text.strip()]
            if real:
                return real
        except Exception:
            pass
        time.sleep(0.5)
    return []


def _select_municipality(driver, wait, target_city):
    """Select municipality robustly with exact then contains matching."""
    wait.until(EC.presence_of_element_located((By.ID, "Municipality")))
    options = _wait_for_municipality_options(driver, timeout_sec=10)
    if not options:
        # Retry search mode switch once in case options populated late.
        _switch_to_municipality_mode(driver)
        if not _wait_for_municipality_options(driver, timeout_sec=3):
            _force_click_municipality_mode(driver)
        options = _wait_for_municipality_options(driver, timeout_sec=8)

    municipality_select = Select(driver.find_element(By.ID, "Municipality"))
    if not options:
        options = [opt.text.strip() for opt in municipality_select.options if opt.text and opt.text.strip()]
    def _norm(s):
        return " ".join(str(s).strip().lower().split())

    def _strip_prefixes(s):
        prefixes = ("town of ", "city of ", "village of ")
        out = _norm(s)
        for p in prefixes:
            if out.startswith(p):
                return out[len(p):]
        return out

    target_norm = _norm(target_city)
    exact = next((o for o in options if _norm(o) == target_norm), None)
    exact_prefixed = next((o for o in options if _strip_prefixes(o) == target_norm), None)

    contains_candidates = [o for o in options if target_norm in _norm(o)]
    contains_ranked = sorted(contains_candidates, key=lambda o: len(_norm(o)) - len(target_norm))
    contains = contains_ranked[0] if contains_ranked else None

    selected_text = exact or exact_prefixed or contains

    if not selected_text:
        sample = options[:20]
        raise ValueError(f"Municipality '{target_city}' not found. Available sample: {sample}")

    municipality_select.select_by_visible_text(selected_text)
    driver.execute_script(
        "arguments[0].dispatchEvent(new Event('change', { bubbles: true }));",
        driver.find_element(By.ID, "Municipality")
    )
    print(f"✓ Selected municipality: {selected_text}")


def run_scraper(target_city=None, start_date=None, end_date=None, use_last_imported=False, prompt_for_missing=True):
    # --- PHASE 0: USER INPUTS ---
    print("\n--- PBC Property Scraper Configuration ---")

    # 1. Get Municipality
    if not target_city:
        target_city = input("Enter Municipality (Press Enter for 'Palm Beach'): ").strip()
        if not target_city:
            target_city = "Palm Beach"

    # 2. Get Start Date (with optional last-imported mode)
    default_date = (datetime.now() - timedelta(days=180)).strftime("%m/%d/%Y")
    if use_last_imported and not start_date:
        latest = get_last_imported_pbc_sale_date(target_city)
        if latest:
            start_date = (latest + timedelta(days=1)).strftime("%m/%d/%Y")
            print(f"✓ Using last imported PBC date +1 day: {start_date}")
        else:
            print("Note: No prior PBC import date found; using default start date.")

    if not start_date:
        if prompt_for_missing:
            start_date_input = input(f"Enter Start Date MM/DD/YYYY (Press Enter for {default_date}): ").strip()
        else:
            start_date_input = ""
        if not start_date_input:
            formatted_date = default_date
        else:
            try:
                formatted_date = parse_mmddyyyy(start_date_input)
            except ValueError:
                print(f"Invalid date format! Defaulting to {default_date}")
                formatted_date = default_date
    else:
        try:
            formatted_date = parse_mmddyyyy(start_date)
        except ValueError:
            print(f"Invalid start date '{start_date}'. Falling back to {default_date}")
            formatted_date = default_date

    # 3. Optional End Date
    if end_date is None and prompt_for_missing:
        end_date_input = input("Enter End Date MM/DD/YYYY (optional, press Enter for no end date): ").strip()
        if end_date_input:
            try:
                formatted_end_date = parse_mmddyyyy(end_date_input)
            except ValueError:
                print("Invalid end date format. Ignoring end date.")
                formatted_end_date = None
        else:
            formatted_end_date = None
    else:
        try:
            formatted_end_date = parse_mmddyyyy(end_date) if end_date else None
        except ValueError:
            print(f"Invalid end date '{end_date}'. Ignoring end date.")
            formatted_end_date = None

    if formatted_end_date:
        print(f"\n-> Starting Search for '{target_city}' sales from {formatted_date} to {formatted_end_date}...\n")
    else:
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

        # FIRST: ensure we are in municipality search mode
        _switch_to_municipality_mode(driver)
        if not _wait_for_municipality_options(driver, timeout_sec=3):
            _force_click_municipality_mode(driver)

        # SECOND: select municipality robustly
        try:
            _select_municipality(driver, wait, target_city)
        except Exception as e:
            print(f"ERROR selecting municipality: {e}")
            driver.quit()
            return
        
        # Select "Qualified Sales" (QS)
        qs_radio = driver.find_element(By.CSS_SELECTOR, "input[value='QS']")
        driver.execute_script("arguments[0].click();", qs_radio)

        # Set Date based on USER INPUT
        date_from_input = driver.find_element(By.ID, "SaleDateFrom")
        date_from_input.clear()
        date_from_input.send_keys(formatted_date)
        if formatted_end_date:
            try:
                date_to_input = driver.find_element(By.ID, "SaleDateTo")
                date_to_input.clear()
                date_to_input.send_keys(formatted_end_date)
                print(f"✓ Applied date range: {formatted_date} to {formatted_end_date}")
            except Exception:
                print("Note: SaleDateTo field not found on page; using start date only.")

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
                if formatted_end_date:
                    print(f"No results found for {target_city} from {formatted_date} to {formatted_end_date}")
                else:
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
        safe_start = formatted_date.replace("/", "-")
        if formatted_end_date:
            safe_end = formatted_end_date.replace("/", "-")
            output_csv_path = os.path.join(DOWNLOAD_FOLDER, f"ENHANCED_{safe_city}_{safe_start}_to_{safe_end}.csv")
        else:
            output_csv_path = os.path.join(DOWNLOAD_FOLDER, f"ENHANCED_{safe_city}_{safe_start}.csv")

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

            def is_existing_duplicate(clean_pcn_val, sale_date):
                """Check if parcel+date already exists in DB (fuzzy ±7 days)."""
                if not clean_pcn_val or not sale_date:
                    return False
                if clean_pcn_val not in existing_sales:
                    return False
                try:
                    pbc_date = datetime.strptime(sale_date, "%Y-%m-%d")
                    for db_date_str in existing_sales[clean_pcn_val]:
                        db_date = datetime.strptime(db_date_str, "%Y-%m-%d")
                        if abs((pbc_date - db_date).days) <= 7:
                            return True
                except Exception:
                    return False
                return False

            # Pre-filter the downloaded CSV before expensive detail scraping/geocoding:
            # 1) remove rows without parcel,
            # 2) remove duplicate parcel+sale-date rows inside the same CSV,
            # 3) remove rows already in database.
            all_rows = list(reader)
            prefiltered_rows = []
            seen_row_keys = set()
            skipped_no_pcn = 0
            skipped_in_csv_dupes = 0
            skipped_in_db = 0

            for row in all_rows:
                pcn = row.get('Parcel Number')
                if not pcn:
                    keys = [k for k in row.keys() if 'Parcel' in k]
                    if keys:
                        pcn = row[keys[0]]
                if not pcn:
                    skipped_no_pcn += 1
                    continue

                sale_date = row.get('Sale Date', '').strip()
                clean_pcn_val = clean_pcn(pcn)
                row_key = (clean_pcn_val, sale_date)
                if row_key in seen_row_keys:
                    skipped_in_csv_dupes += 1
                    continue
                seen_row_keys.add(row_key)

                if is_existing_duplicate(clean_pcn_val, sale_date):
                    skipped_in_db += 1
                    continue

                row['_clean_pcn'] = clean_pcn_val
                prefiltered_rows.append(row)

            total_skipped_prefilter = skipped_no_pcn + skipped_in_csv_dupes + skipped_in_db
            print(
                f"✓ Pre-filtered CSV rows: total={len(all_rows)} | to_process={len(prefiltered_rows)} | "
                f"skipped_no_pcn={skipped_no_pcn} | skipped_csv_dupes={skipped_in_csv_dupes} | skipped_in_db={skipped_in_db}"
            )
            
            count = 0
            for row in prefiltered_rows:
                pcn = row.get('Parcel Number') or row.get('_clean_pcn')
                address = row.get('Location', '').strip()
                municipality = row.get('Municipality', '').strip()

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
                    row.pop('_clean_pcn', None)
                    full_row = {**row, **extra_data}
                    writer.writerow(full_row)
                    print(f" Done. (Lat: {lat}, Lon: {lon})")

                except Exception as e:
                    print(f" Error: {e}")
                    row.pop('_clean_pcn', None)
                    writer.writerow(row)

                count += 1
                time.sleep(1.1)

        print(
            f"\n✓ DONE! Processed {count} new properties, "
            f"pre-filter skipped {total_skipped_prefilter} "
            f"(no pcn: {skipped_no_pcn}, csv dupes: {skipped_in_csv_dupes}, in-db: {skipped_in_db})."
        )
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
    parser = argparse.ArgumentParser(description="PBC off-market scraper")
    parser.add_argument("--city", help="Municipality (example: Palm Beach)")
    parser.add_argument("--start-date", help="Start date MM/DD/YYYY")
    parser.add_argument("--end-date", help="End date MM/DD/YYYY")
    parser.add_argument(
        "--from-last-imported",
        action="store_true",
        help="Set start date to last imported PBC sold_date + 1 day (optionally filtered by city)."
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Do not prompt for missing inputs; use defaults."
    )
    args = parser.parse_args()

    run_scraper(
        target_city=args.city,
        start_date=args.start_date,
        end_date=args.end_date,
        use_last_imported=args.from_last_imported,
        prompt_for_missing=(not args.non_interactive)
    )
