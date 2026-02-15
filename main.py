import os
import sys
import subprocess
import time
import sqlite3
from datetime import datetime, timedelta

import shutil
import re
import glob
import pandas as pd

DOWNLOAD_FOLDER = os.path.join(os.path.expanduser("~"), "Downloads")

def get_last_mls_status_date_plus_one():
    """
    Return MM/DD/YYYY for one day after the latest MLS status-related date in DB.
    Excludes imported off-market rows (listing_number LIKE 'PBC-%').
    """
    db_file = "mls.db"
    if not os.path.exists(db_file):
        return None

    sql = """
    SELECT MAX(dt) FROM (
        SELECT MAX(DATE(under_contract_date)) AS dt FROM listing_details WHERE listing_number NOT LIKE 'PBC-%'
        UNION ALL
        SELECT MAX(DATE(sold_date)) AS dt FROM listing_details WHERE listing_number NOT LIKE 'PBC-%'
        UNION ALL
        SELECT MAX(DATE(expiration_date)) AS dt FROM listing_details WHERE listing_number NOT LIKE 'PBC-%'
        UNION ALL
        SELECT MAX(DATE(withdrawn_date)) AS dt FROM listing_details WHERE listing_number NOT LIKE 'PBC-%'
        UNION ALL
        SELECT MAX(DATE(temp_off_market_date)) AS dt FROM listing_details WHERE listing_number NOT LIKE 'PBC-%'
        UNION ALL
        SELECT MAX(DATE(cancel_date)) AS dt FROM listing_details WHERE listing_number NOT LIKE 'PBC-%'
    );
    """
    try:
        conn = sqlite3.connect(db_file)
        cur = conn.cursor()
        cur.execute(sql)
        row = cur.fetchone()
        conn.close()
        if not row or not row[0]:
            return None
        last_dt = datetime.strptime(row[0], "%Y-%m-%d")
        return (last_dt + timedelta(days=1)).strftime("%m/%d/%Y")
    except Exception:
        return None

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def reset_database():
    print("\n--- RESETTING DATABASE & RESTORING FILES ---")
    confirm = input("Are you sure you want to delete the database and restore all CSVs? (y/n): ").lower()
    if confirm != 'y':
        print("Reset cancelled.")
        time.sleep(1)
        return

    db_file = "mls.db"
    source_dir = "processed_archive"
    dest_dir = "input_csvs"

    # 1. Delete Database
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
            print(f"🗑️  Deleted {db_file}")
        except Exception as e:
            print(f"Error deleting DB: {e}")
    
    for ext in ['-shm', '-wal']:
        if os.path.exists(db_file + ext):
            try:
                os.remove(db_file + ext)
            except: pass

    # 2. Restore Files
    if not os.path.exists(source_dir):
        print(f"Archive directory {source_dir} not found.")
        input("Press Enter...")
        return

    os.makedirs(dest_dir, exist_ok=True)
    
    timestamp_pattern = re.compile(r"^\d{8}-\d{6}_(.+)")
    files = os.listdir(source_dir)
    count = 0
    
    for filename in files:
        if filename.startswith("."): continue
        
        src = os.path.join(source_dir, filename)
        match = timestamp_pattern.match(filename)
        original_name = match.group(1) if match else filename
        dest = os.path.join(dest_dir, original_name)
        
        try:
            shutil.move(src, dest)
            print(f"♻️  Restored: {original_name}")
            count += 1
        except Exception as e:
            print(f"Error moving {filename}: {e}")
            
    print(f"\n✅ Reset Complete. {count} files moved to {dest_dir}.")
    input("Press Enter to continue...")

def run_data_processing():
    print("\n--- Starting Data Processing ---")
    try:
        # Run generate_db.py using the current python interpreter
        subprocess.run([sys.executable, "generate_db.py"], check=True)
        input("\nPress Enter to continue...")
    except subprocess.CalledProcessError as e:
        print(f"\nError running data processing: {e}")
        input("\nPress Enter to continue...")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
        input("\nPress Enter to continue...")

def update_subdivisions():
    """Update subdivision names in database using lookup cheatsheets without re-importing data."""
    print("\n--- Updating Subdivisions from Lookup Sheets ---")
    
    db_file = "mls.db"
    lookup_folder = "lookups"
    
    if not os.path.exists(db_file):
        print(f"❌ Database '{db_file}' not found. Run data processing first.")
        input("\nPress Enter to continue...")
        return
    
    # Load lookup cheatsheets
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
                    print(f"✅ Loaded {len(temp_map)} mappings from {filename}")
                else:
                    print(f"⚠️  Skipping {filename}: Missing 'Master PCN' or unified subdivision column")
            except Exception as e:
                print(f"❌ Error loading {filename}: {e}")
        else:
            print(f"⚠️  Not found: {filename}")
    
    if not pcn_map:
        print("\n❌ No lookup mappings loaded. Check your cheatsheet files.")
        input("\nPress Enter to continue...")
        return
    
    print(f"\n📊 Total mappings loaded: {len(pcn_map)}")
    confirm = input("Apply these mappings to the database? (y/n): ").lower()
    if confirm != 'y':
        print("Update cancelled.")
        input("\nPress Enter to continue...")
        return
    
    # Update database
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        # Check if pcn_10_digit column exists
        cursor.execute("PRAGMA table_info(listing_details)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'pcn_10_digit' not in columns:
            print("❌ Column 'pcn_10_digit' not found. Re-run full data import.")
            conn.close()
            input("\nPress Enter to continue...")
            return
        
        # Add pcn_validated column if it doesn't exist
        if 'pcn_validated' not in columns:
            print("Adding pcn_validated column...")
            cursor.execute("ALTER TABLE listing_details ADD COLUMN pcn_validated INTEGER DEFAULT 0")
        
        # First, reset all pcn_validated to 0
        cursor.execute("UPDATE listing_details SET pcn_validated = 0")
        
        # Update subdivision names and set pcn_validated = 1 for matching PCNs
        update_count = 0
        for pcn, subdivision in pcn_map.items():
            cursor.execute(
                "UPDATE listing_details SET final_subdivision = ?, pcn_validated = 1 WHERE pcn_10_digit = ?",
                (subdivision, pcn)
            )
            update_count += cursor.rowcount
        
        conn.commit()
        
        # Count validated vs unvalidated
        cursor.execute("SELECT COUNT(*) FROM listing_details WHERE pcn_validated = 1")
        validated = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM listing_details WHERE pcn_validated = 0 OR pcn_validated IS NULL")
        unvalidated = cursor.fetchone()[0]
        
        print(f"\n✅ Updated {update_count} records with new subdivision names.")
        print(f"📊 Validated PCNs: {validated:,} | Unvalidated: {unvalidated:,}")
        
        # --- FUZZY MATCHING FOR UNVALIDATED RECORDS ---
        if unvalidated > 0:
            print("\n--- Attempting Fuzzy Match for Unvalidated Records ---")
            
            # Get unvalidated records with their PCN and current subdivision
            cursor.execute("""
                SELECT DISTINCT pcn_10_digit, final_subdivision 
                FROM listing_details 
                WHERE (pcn_validated = 0 OR pcn_validated IS NULL) 
                AND pcn_10_digit IS NOT NULL
            """)
            unvalidated_records = cursor.fetchall()
            
            # Build a map of 9-digit PCN prefix -> validated subdivision
            pcn9_to_subdivision = {}
            for pcn, subdivision in pcn_map.items():
                pcn9 = pcn[:9] if len(pcn) >= 9 else pcn
                if pcn9 not in pcn9_to_subdivision:
                    pcn9_to_subdivision[pcn9] = subdivision
            
            # Try to match unvalidated records
            fuzzy_matches = 0
            for pcn, current_sub in unvalidated_records:
                if not pcn or len(pcn) < 9:
                    continue
                pcn9 = pcn[:9]
                
                # Check if first 9 digits match a validated PCN
                if pcn9 in pcn9_to_subdivision:
                    matched_sub = pcn9_to_subdivision[pcn9]
                    
                    # Optional: fuzzy check on name similarity
                    current_upper = str(current_sub).upper() if current_sub else ""
                    matched_upper = str(matched_sub).upper()
                    
                    # Simple fuzzy: check if key words overlap
                    current_words = set(current_upper.replace(",", "").split())
                    matched_words = set(matched_upper.replace(",", "").split())
                    overlap = current_words & matched_words
                    
                    # If there's word overlap or it's a close PCN match, update it
                    if len(overlap) > 0 or abs(int(pcn) - int(pcn9 + "0")) < 100:
                        cursor.execute(
                            "UPDATE listing_details SET final_subdivision = ?, pcn_validated = 1 WHERE pcn_10_digit = ?",
                            (matched_sub, pcn)
                        )
                        if cursor.rowcount > 0:
                            fuzzy_matches += cursor.rowcount
                            print(f"  🔗 Matched PCN {pcn}: '{current_sub}' → '{matched_sub}'")
            
            conn.commit()
            print(f"\n✅ Fuzzy matched {fuzzy_matches} additional records.")
        
        conn.close()
        
    except Exception as e:
        print(f"\n❌ Database error: {e}")
    
    input("\nPress Enter to continue...")

def launch_dashboard():
    print("\n--- Launching Dashboard ---")
    print("Press Ctrl+C in the terminal to stop the dashboard.")
    time.sleep(1)
    try:
        # Run streamlit
        subprocess.run(["streamlit", "run", "app.py"], check=True)
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    except FileNotFoundError:
        print("\nError: 'streamlit' command not found. Please ensure it is installed.")
        input("\nPress Enter to continue...")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
        input("\nPress Enter to continue...")

def launch_react_dashboard():
    """
    Launch modern dashboard stack:
    - FastAPI backend on port 8000
    - React (Vite) frontend on port 5173
    Keeps existing Streamlit dashboard untouched.
    """
    print("\n--- Launching React Dashboard (API + Frontend) ---")
    print("Backend:  http://127.0.0.1:8000")
    print("Frontend: http://127.0.0.1:5173")
    print("Press Ctrl+C to stop both processes.")
    time.sleep(1)

    api_proc = None
    fe_proc = None
    try:
        api_cmd = [
            sys.executable, "-m", "uvicorn",
            "api.main:app",
            "--reload",
            "--port", "8000"
        ]
        fe_cmd = ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"]

        api_proc = subprocess.Popen(api_cmd)
        fe_proc = subprocess.Popen(fe_cmd, cwd="frontend")

        # Keep this launcher alive while children run.
        while True:
            if api_proc.poll() is not None:
                raise RuntimeError("FastAPI process exited unexpectedly.")
            if fe_proc.poll() is not None:
                raise RuntimeError("Frontend process exited unexpectedly.")
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping React dashboard...")
    except FileNotFoundError as e:
        print(f"\nMissing command: {e}. Make sure 'npm' and Python deps are installed.")
        input("\nPress Enter to continue...")
    except Exception as e:
        print(f"\nError launching React dashboard: {e}")
        input("\nPress Enter to continue...")
    finally:
        for proc in [fe_proc, api_proc]:
            if proc and proc.poll() is None:
                proc.terminate()
        # small grace period then force kill if needed
        time.sleep(0.5)
        for proc in [fe_proc, api_proc]:
            if proc and proc.poll() is None:
                proc.kill()

def find_latest_enhanced_csv(created_after=None):
    """
    Find the latest ENHANCED csv in Downloads.
    Prefer *_COMBINED.csv when available.
    """
    patterns = [
        os.path.join(DOWNLOAD_FOLDER, "ENHANCED_*_COMBINED.csv"),
        os.path.join(DOWNLOAD_FOLDER, "ENHANCED_*.csv"),
    ]
    candidates = []
    for pattern in patterns:
        for path in glob.glob(pattern):
            try:
                ctime = os.path.getctime(path)
            except Exception:
                continue
            if created_after is None or ctime >= created_after:
                candidates.append((ctime, path))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def run_duplicate_audit_summary():
    """Run duplicate audit summary after auto pipelines."""
    print("\n🔎 Running duplicate audit summary...")
    json_path = os.path.join("output", "audits", "latest_audit_summary.json")
    try:
        subprocess.run(
            [
                sys.executable,
                "audit_duplicates.py",
                "--window-days", "7",
                "--sample-size", "10",
                "--json-path", json_path,
            ],
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Duplicate audit failed: {e}")
    except Exception as e:
        print(f"⚠️  Duplicate audit error: {e}")

def run_property_type_normalization():
    """Normalize property_type into canonical categories."""
    print("\n🧩 Normalizing property types...")
    try:
        subprocess.run([sys.executable, "normalize_property_types.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Property type normalization failed: {e}")
    except Exception as e:
        print(f"⚠️  Property type normalization error: {e}")

def run_pbc_geo_zone_audit_and_fix():
    """Audit and correct Palm Beach geo-zone tagging (North/Mid/Estate/South)."""
    print("\n🧭 Auditing Palm Beach geo-zone assignments...")
    report_path = os.path.join("output", "audits", "pbc_geo_zone_audit_latest.csv")
    try:
        subprocess.run(
            [sys.executable, "audit_fix_pbc_geo_zones.py", "--apply", "--report-path", report_path],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"⚠️  PBC geo-zone audit failed: {e}")
    except Exception as e:
        print(f"⚠️  PBC geo-zone audit error: {e}")

def run_subdivision_master_sync():
    """Sync final_subdivision to master lookup sheet by PCN."""
    print("\n🗂️  Syncing subdivisions from master lookup...")
    report_path = os.path.join("output", "audits", "subdivision_master_sync_report.csv")
    try:
        subprocess.run(
            [sys.executable, "sync_subdivisions_from_master.py", "--apply", "--report-path", report_path],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Subdivision master sync failed: {e}")
    except Exception as e:
        print(f"⚠️  Subdivision master sync error: {e}")

def run_cross_source_duplicate_cleanup():
    """Remove PBC rows that duplicate MLS sales."""
    print("\n🧹 Cleaning cross-source duplicates (PBC vs MLS)...")
    report_path = os.path.join("output", "audits", "cross_source_duplicate_cleanup.csv")
    try:
        subprocess.run(
            [
                sys.executable,
                "clean_cross_source_duplicates.py",
                "--window-days", "30",
                "--apply",
                "--report-path", report_path,
            ],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Cross-source cleanup failed: {e}")
    except Exception as e:
        print(f"⚠️  Cross-source cleanup error: {e}")

def run_data_integrity_sweep():
    """Run all data-quality hardening checks/fixes in sequence."""
    print("\n--- Data Integrity Sweep ---")
    run_subdivision_master_sync()
    run_cross_source_duplicate_cleanup()
    run_pbc_geo_zone_audit_and_fix()
    run_property_type_normalization()
    run_duplicate_audit_summary()
    print("\n✅ Data integrity sweep complete.")
    input("\nPress Enter to continue...")

def run_off_market_scraper_automation():
    """
    Automated off-market full pipeline:
    - Default city: Palm Beach
    - Start date: last imported PBC sold_date + 1 day
    - Import ENHANCED CSV into DB
    - Run cabana merge in DB
    """
    print("\n--- Off-Market Full Pipeline (Automation Mode) ---")
    print("City: Palm Beach | Date mode: incremental from last imported PBC sale date (+1 day)")
    started_at = time.time()
    try:
        # Step 1: Scrape + normalize into ENHANCED csv
        subprocess.run(
            [
                sys.executable,
                "PalmBeachProrpertyScraper.py",
                "--city", "Palm Beach",
                "--from-last-imported",
                "--non-interactive"
            ],
            check=True
        )

        # Step 2: Import newest ENHANCED csv into listing_details
        enhanced_csv = find_latest_enhanced_csv(created_after=started_at - 120)
        if not enhanced_csv:
            print("\n❌ Could not find a newly generated ENHANCED CSV in Downloads.")
            input("\nPress Enter to continue...")
            return

        print(f"\n📥 Importing off-market CSV into database:\n{enhanced_csv}")
        subprocess.run(
            [sys.executable, "pbc_importer.py", enhanced_csv],
            check=True
        )

        # Step 3: Merge likely cabana records in DB
        print("\n🏷️  Running cabana merge on database...")
        subprocess.run(
            [sys.executable, "merge_cabanas.py", "--merge"],
            check=True
        )
        run_subdivision_master_sync()
        run_cross_source_duplicate_cleanup()
        run_pbc_geo_zone_audit_and_fix()
        run_property_type_normalization()
        run_duplicate_audit_summary()
        print("\n✅ Off-market automation pipeline complete.")
    except subprocess.CalledProcessError as e:
        print(f"\nError running off-market automation pipeline: {e}")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
    input("\nPress Enter to continue...")

def run_off_market_scraper_custom():
    """
    Manual off-market full pipeline:
    - User chooses city (Palm Beach default)
    - User can set start/end dates (optional)
    - Imports newest ENHANCED CSV
    - Runs cabana merge + geo-zone audit + type normalization + duplicate audit
    """
    print("\n--- Off-Market Full Pipeline (Custom) ---")
    city = input("Enter Municipality (Press Enter for 'Palm Beach'): ").strip() or "Palm Beach"
    start_date = input("Enter Start Date MM/DD/YYYY (optional): ").strip()
    end_date = input("Enter End Date MM/DD/YYYY (optional): ").strip()
    started_at = time.time()

    cmd = [sys.executable, "PalmBeachProrpertyScraper.py", "--city", city, "--non-interactive"]
    if start_date:
        cmd.extend(["--start-date", start_date])
    if end_date:
        cmd.extend(["--end-date", end_date])

    try:
        # Step 1: Scrape + normalize into ENHANCED csv
        subprocess.run(cmd, check=True)

        # Step 2: Import newest ENHANCED csv into listing_details
        enhanced_csv = find_latest_enhanced_csv(created_after=started_at - 120)
        if not enhanced_csv:
            print("\n❌ Could not find a newly generated ENHANCED CSV in Downloads.")
            input("\nPress Enter to continue...")
            return

        print(f"\n📥 Importing off-market CSV into database:\n{enhanced_csv}")
        subprocess.run([sys.executable, "pbc_importer.py", enhanced_csv], check=True)

        # Step 3: Merge likely cabana records in DB
        print("\n🏷️  Running cabana merge on database...")
        subprocess.run([sys.executable, "merge_cabanas.py", "--merge"], check=True)

        # Step 4+: Cleanup/consistency checks
        run_subdivision_master_sync()
        run_cross_source_duplicate_cleanup()
        run_pbc_geo_zone_audit_and_fix()
        run_property_type_normalization()
        run_duplicate_audit_summary()
        print("\n✅ Off-market custom pipeline complete.")
    except subprocess.CalledProcessError as e:
        print(f"\nError running off-market custom pipeline: {e}")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
    input("\nPress Enter to continue...")

def run_mls_update_automation():
    """
    Automated MLS update pipeline:
    - Runs Flexmls saved-search export
    - Optionally updates all relevant status start-date filters
    - Copies CSV into input_csvs
    - Runs generate_db.py to clean + upsert
    """
    print("\n--- MLS Update (Auto Incremental: export -> ingest -> generate_db) ---")
    print("Default saved search: PalmBeach_Wellington_NewData")
    template = "AI Full DataSet"
    from_date = get_last_mls_status_date_plus_one()
    if from_date:
        print(f"Date mode: incremental from last MLS status date (+1 day) => {from_date}")
    else:
        print("Date mode: no prior MLS status date found; using existing saved-search date defaults.")

    cmd = [
        sys.executable,
        "mls_export_saved_search.py",
        "--search-name", "PalmBeach_Wellington_NewData",
        "--export-template", template,
        "--run-generate-db",
    ]
    if from_date:
        cmd.extend(["--from-date", from_date])

    try:
        subprocess.run(cmd, check=True)
        run_subdivision_master_sync()
        run_cross_source_duplicate_cleanup()
        run_property_type_normalization()
        run_duplicate_audit_summary()
        print("\n✅ MLS update pipeline complete.")
    except subprocess.CalledProcessError as e:
        print(f"\nError running MLS update pipeline: {e}")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
    input("\nPress Enter to continue...")

def main():
    while True:
        clear_screen()
        print("========================================")
        print("   ReStats Program - Main Menu")
        print("========================================")
        print("1. 🔄 Run Data Processing (Import CSVs)")
        print("2. 📊 Launch Dashboard")
        print("3. 🏘️  Update Subdivisions (Lookup Sheets)")
        print("4. ⚠️  Reset Database & Restore Files")
        print("5. 📥 Update MLS (Auto incremental: export -> generate_db)")
        print("6. 🤖 Off-Market Full Run (Auto incremental: scrape -> import -> cabana merge)")
        print("7. 🧭 Off-Market Pull (Custom city/date range)")
        print("8. ⚛️  Launch React Dashboard (API + frontend)")
        print("9. 🧪 Run Data Integrity Sweep")
        print("10. ❌ Exit")
        print("========================================")
        
        choice = input("Enter your choice (1-10): ").strip()
        
        if choice == '1':
            run_data_processing()
        elif choice == '2':
            launch_dashboard()
        elif choice == '3':
            update_subdivisions()
        elif choice == '4':
            reset_database()
        elif choice == '5':
            run_mls_update_automation()
        elif choice == '6':
            run_off_market_scraper_automation()
        elif choice == '7':
            run_off_market_scraper_custom()
        elif choice == '8':
            launch_react_dashboard()
        elif choice == '9':
            run_data_integrity_sweep()
        elif choice == '10':
            print("Goodbye!")
            break
        else:
            print("Invalid choice. Please try again.")
            time.sleep(1)

if __name__ == "__main__":
    main()
