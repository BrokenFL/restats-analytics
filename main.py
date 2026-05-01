import os
import sys
import subprocess
import time
import sqlite3
import json
from datetime import datetime, timedelta

import shutil
import re
import glob
import pandas as pd

DOWNLOAD_FOLDER = os.path.join(os.path.expanduser("~"), "Downloads")
OPS_DIR = os.path.join("output", "ops")
LAST_RUN_PATH = os.path.join(OPS_DIR, "last_run.json")
DEFAULT_MLS_MARKETS = ["Palm Beach", "Wellington", "Boca Raton", "Delray Beach", "South Palm Beach"]


def normalize_pcn10(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return digits.zfill(10)[:10] if digits else ""

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


def _latest_pbc_sold_date(city=None):
    """
    Return latest PBC sold_date (YYYY-MM-DD) for a city (case-insensitive) or all cities.
    """
    db_file = "mls.db"
    if not os.path.exists(db_file):
        return None
    try:
        conn = sqlite3.connect(db_file)
        cur = conn.cursor()
        if city:
            cur.execute(
                """
                SELECT MAX(DATE(sold_date))
                FROM listing_details
                WHERE listing_number LIKE 'PBC-%'
                  AND sold_date IS NOT NULL
                  AND LOWER(TRIM(city)) = LOWER(TRIM(?))
                """,
                (city,),
            )
        else:
            cur.execute(
                """
                SELECT MAX(DATE(sold_date))
                FROM listing_details
                WHERE listing_number LIKE 'PBC-%'
                  AND sold_date IS NOT NULL
                """
            )
        row = cur.fetchone()
        conn.close()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def get_last_pbc_date_plus_one(city=None, fallback_global=True):
    """
    Resolve incremental PBC start date MM/DD/YYYY from latest imported sold_date.
    Returns dict with city/global baselines for logging.
    """
    city_latest = _latest_pbc_sold_date(city) if city else None
    global_latest = _latest_pbc_sold_date(None)
    baseline = city_latest or (global_latest if fallback_global else None)
    if not baseline:
        return {
            "start_date": None,
            "city_latest": city_latest,
            "global_latest": global_latest,
            "baseline": None,
            "source": "none",
        }
    dt = datetime.strptime(baseline, "%Y-%m-%d") + timedelta(days=1)
    source = "city" if city_latest else "global_fallback"
    return {
        "start_date": dt.strftime("%m/%d/%Y"),
        "city_latest": city_latest,
        "global_latest": global_latest,
        "baseline": baseline,
        "source": source,
    }

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def slugify_label(value):
    value = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return value or "market"


def write_last_run(pipeline_name, status, started_at=None, finished_at=None, details=None, error=None):
    """Persist latest pipeline execution metadata for ops dashboard."""
    os.makedirs(OPS_DIR, exist_ok=True)
    payload = {
        "pipeline": pipeline_name,
        "status": status,
        "started_at": started_at or datetime.now().isoformat(timespec="seconds"),
        "finished_at": finished_at or datetime.now().isoformat(timespec="seconds"),
        "details": details or {},
        "error": str(error) if error else None,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        with open(LAST_RUN_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        print(f"⚠️  Could not write last run metadata: {e}")

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
    
    # Load all available lookup cheatsheets (supports newly added Boca/Unincorporated files)
    cheatsheets = sorted(glob.glob(os.path.join(lookup_folder, "*subdivision*audit*cheatsheet*.csv")))
    
    pcn_map = {}
    for path in cheatsheets:
        filename = os.path.basename(path)
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
                        index=df["Master PCN"].map(normalize_pcn10)
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

def _norm_text(value):
    return " ".join(str(value or "").strip().upper().split())


def _clean_pcn10(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return digits.zfill(10)[:10] if digits else ""


def _get_cma_subject_row(parcel: str, as_of_date: str = None):
    """Get latest subject-like row by parcel for CMA/off-market refresh context."""
    p = re.sub(r"\D", "", str(parcel or ""))
    if not p:
        return None
    if not os.path.exists("mls.db"):
        return None
    try:
        conn = sqlite3.connect("mls.db")
        cur = conn.cursor()
        if as_of_date:
            cur.execute(
                """
                SELECT parcel_id, pcn_10_digit, city, final_subdivision, short_address, listing_number
                FROM listing_details
                WHERE REPLACE(COALESCE(parcel_id,''), '-', '') = ?
                  AND (DATE(sold_date) <= DATE(?) OR sold_date IS NULL)
                ORDER BY DATE(COALESCE(sold_date, listing_date)) DESC, listing_number DESC
                LIMIT 1
                """,
                (p, as_of_date),
            )
        else:
            cur.execute(
                """
                SELECT parcel_id, pcn_10_digit, city, final_subdivision, short_address, listing_number
                FROM listing_details
                WHERE REPLACE(COALESCE(parcel_id,''), '-', '') = ?
                ORDER BY DATE(COALESCE(sold_date, listing_date)) DESC, listing_number DESC
                LIMIT 1
                """,
                (p,),
            )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "parcel_id": row[0] or "",
            "pcn_10_digit": _clean_pcn10(row[1]),
            "city": row[2] or "",
            "final_subdivision": row[3] or "",
            "short_address": row[4] or "",
            "listing_number": row[5] or "",
        }
    except Exception:
        return None


def _resolve_lookup_official_subdivision_names(subject_final_subdivision: str, subject_pcn10: str = "", subject_city: str = ""):
    """
    From lookup cheatsheets, resolve all official PAPA subdivision names ('Name')
    under the same Unified Subdivision umbrella as the subject.
    """
    lookup_files = sorted(glob.glob(os.path.join("lookups", "*_subdivision_audit_cheatsheet.csv")))
    city_norm = re.sub(r"[^a-z0-9]", "", str(subject_city or "").lower())
    if city_norm:
        scoped_files = []
        for p in lookup_files:
            base = re.sub(r"[^a-z0-9]", "", os.path.basename(p).lower())
            if city_norm in base:
                scoped_files.append(p)
        if scoped_files:
            lookup_files = scoped_files
    if not lookup_files:
        return {"unified_values": [], "official_names": []}

    frames = []
    for path in lookup_files:
        try:
            df = pd.read_csv(path, dtype=str).fillna("")
            required = {"Name", "Final Subdivision", "Unified Subdivision"}
            if not required.issubset(set(df.columns)):
                continue
            df = df.copy()
            df["Name_norm"] = df["Name"].map(_norm_text)
            df["Final_norm"] = df["Final Subdivision"].map(_norm_text)
            df["Unified_norm"] = df["Unified Subdivision"].map(_norm_text)
            if "Master PCN" in df.columns:
                df["pcn10"] = df["Master PCN"].map(_clean_pcn10)
            else:
                df["pcn10"] = ""
            frames.append(df)
        except Exception:
            continue

    if not frames:
        return {"unified_values": [], "official_names": []}

    lkp = pd.concat(frames, ignore_index=True)
    unified_targets = set()
    final_norm = _norm_text(subject_final_subdivision)
    pcn10 = _clean_pcn10(subject_pcn10)

    if pcn10:
        unified_targets.update(
            [u for u in lkp.loc[lkp["pcn10"] == pcn10, "Unified_norm"].tolist() if u]
        )
    if final_norm:
        unified_targets.update(
            [u for u in lkp.loc[lkp["Final_norm"] == final_norm, "Unified_norm"].tolist() if u]
        )
        if not unified_targets:
            # fallback in case caller passed a unified label
            unified_targets.update(
                [u for u in lkp.loc[lkp["Unified_norm"] == final_norm, "Unified_norm"].tolist() if u]
            )

    if not unified_targets:
        return {"unified_values": [], "official_names": []}

    scoped = lkp[lkp["Unified_norm"].isin(unified_targets)].copy()
    names = []
    seen = set()
    for n in scoped["Name"].astype(str).str.strip().tolist():
        nn = _norm_text(n)
        if not nn or nn in seen:
            continue
        seen.add(nn)
        names.append(n)

    return {
        "unified_values": sorted(unified_targets),
        "official_names": names,
    }


def _filter_enhanced_csv_to_city(csv_path: str, target_city: str):
    """
    Restrict scraped subdivision results to a municipality before import.
    Prevents county-wide subdivision matches (e.g., Pompano) from entering CMA refresh.
    Returns (path_to_import, kept_rows, total_rows).
    """
    if not csv_path or not os.path.exists(csv_path):
        return csv_path, 0, 0
    city_norm = _norm_text(target_city)
    if not city_norm:
        return csv_path, 0, 0
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return csv_path, 0, 0

    total_rows = len(df)
    if total_rows == 0 or "Municipality" not in df.columns:
        return csv_path, total_rows, total_rows

    muni_norm = df["Municipality"].astype(str).map(_norm_text)
    keep = df[muni_norm == city_norm].copy()
    kept_rows = len(keep)
    if kept_rows == total_rows:
        return csv_path, kept_rows, total_rows

    filtered_path = csv_path.replace(".csv", f"_CITYFILTER_{city_norm.replace(' ', '_')}.csv")
    keep.to_csv(filtered_path, index=False)
    return filtered_path, kept_rows, total_rows


def run_cma_off_market_refresh(parcel: str, as_of_date: str = None, months_back: int = 12):
    """
    Refresh off-market sales by unified subdivision umbrella for CMA:
    uses lookup 'Name' (official PAPA names) under the subject's unified group.
    """
    subject = _get_cma_subject_row(parcel, as_of_date=as_of_date)
    if not subject:
        print("⚠️  Could not resolve subject parcel in DB. Skipping off-market refresh.")
        return {"status": "skipped", "reason": "subject_not_found", "attempted": 0, "imported": 0}

    lookup = _resolve_lookup_official_subdivision_names(
        subject_final_subdivision=subject.get("final_subdivision", ""),
        subject_pcn10=subject.get("pcn_10_digit", ""),
        subject_city=subject.get("city", ""),
    )
    names = lookup.get("official_names", [])
    if not names:
        print("⚠️  No official subdivision names found in lookup for subject unified group.")
        return {"status": "skipped", "reason": "no_lookup_names", "attempted": 0, "imported": 0}

    end_dt = None
    if as_of_date:
        try:
            end_dt = datetime.strptime(as_of_date, "%Y-%m-%d")
        except Exception:
            end_dt = None
    if end_dt is None:
        end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=30 * months_back)
    start_date = start_dt.strftime("%m/%d/%Y")
    end_date = end_dt.strftime("%m/%d/%Y")

    print("\n--- CMA Off-Market Community Refresh ---")
    print(f"Subject: {subject.get('short_address') or subject.get('parcel_id')}")
    print(f"City: {subject.get('city') or 'N/A'}")
    print(f"Final Subdivision: {subject.get('final_subdivision') or 'N/A'}")
    print(f"Unified groups: {', '.join(lookup.get('unified_values', [])) or 'N/A'}")
    print(f"Official subdivision names to search: {len(names)}")
    print(f"Date range: {start_date} to {end_date}")

    imported_files = []
    for idx, sub_name in enumerate(names, start=1):
        print(f"\n[{idx}/{len(names)}] Subdivision search: {sub_name}")
        started_at = time.time()
        cmd = [
            sys.executable,
            "PalmBeachProrpertyScraper.py",
            "--search-mode", "subdivision",
            "--subdivision", sub_name,
            "--start-date", start_date,
            "--end-date", end_date,
            "--non-interactive",
        ]
        try:
            subprocess.run(cmd, check=True)
            enhanced_csv = find_latest_enhanced_csv(created_after=started_at - 120)
            if enhanced_csv and enhanced_csv not in imported_files:
                city_filtered_csv, kept_rows, total_rows = _filter_enhanced_csv_to_city(
                    enhanced_csv,
                    subject.get("city", ""),
                )
                print(
                    f"📥 Importing: {city_filtered_csv} "
                    f"(city filter: kept {kept_rows}/{total_rows} rows for {subject.get('city') or 'N/A'})"
                )
                if kept_rows > 0:
                    subprocess.run([sys.executable, "pbc_importer.py", city_filtered_csv], check=True)
                    imported_files.append(city_filtered_csv)
                else:
                    print("No rows left after city filter; skipping import for this subdivision result.")
            else:
                print("No new ENHANCED CSV detected for this subdivision.")
        except subprocess.CalledProcessError as e:
            print(f"⚠️  Subdivision pull failed for '{sub_name}': {e}")
        except Exception as e:
            print(f"⚠️  Subdivision pull error for '{sub_name}': {e}")

    if imported_files:
        print("\n🏷️  Running post-import cleanup...")
        try:
            subprocess.run([sys.executable, "merge_cabanas.py", "--merge"], check=True)
        except Exception as e:
            print(f"⚠️  Cabana merge failed: {e}")
        run_subdivision_master_sync()
        run_cross_source_duplicate_cleanup()
        run_rx_board_duplicate_cleanup()
        run_off_market_sync_audit()
        run_pbc_geo_zone_audit_and_fix()
        run_property_type_normalization()
        run_property_type_override_sync()
        run_cabana_flag_sync()
        run_data_quality_guardrails()
        run_duplicate_audit_summary()
        print(f"\n✅ CMA off-market refresh complete. Imported files: {len(imported_files)}")
        return {"status": "ok", "reason": None, "attempted": len(names), "imported": len(imported_files)}
    else:
        print("\nℹ️  No new subdivision files imported for CMA refresh.")
        return {"status": "ok", "reason": "no_new_files", "attempted": len(names), "imported": 0}


def run_duplicate_audit_summary():
    """Run duplicate audit summary after auto pipelines."""
    print("\n🔎 Running duplicate audit summary...")
    json_path = os.path.join("output", "audits", "latest_audit_summary.json")
    try:
        subprocess.run(
            [
                sys.executable,
                "audit_duplicates.py",
                "--window-days", "60",
                "--sample-size", "10",
                "--json-path", json_path,
            ],
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Duplicate audit failed: {e}")
    except Exception as e:
        print(f"⚠️  Duplicate audit error: {e}")


def run_off_market_sync_audit():
    """Audit recent off-market imports for unresolved overlaps and subdivision drift."""
    print("\n🔎 Running off-market sync audit...")
    csv_path = os.path.join("output", "audits", "offmarket_sync_audit.csv")
    json_path = os.path.join("output", "audits", "offmarket_sync_audit_latest.json")
    try:
        subprocess.run(
            [
                sys.executable,
                "audit_offmarket_sync.py",
                "--csv-path", csv_path,
                "--json-path", json_path,
            ],
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Off-market sync audit failed: {e}")
    except Exception as e:
        print(f"⚠️  Off-market sync audit error: {e}")


def run_data_quality_guardrails():
    """Run hard guardrail audit checks and publish latest summary artifacts."""
    print("\n🛡️  Running data quality guardrails...")
    json_path = os.path.join("output", "audits", "latest_guardrail_summary.json")
    csv_path = os.path.join("output", "audits", "latest_guardrail_samples.csv")
    try:
        subprocess.run(
            [
                sys.executable,
                "audit_data_quality_guardrails.py",
                "--json-path", json_path,
                "--csv-path", csv_path,
            ],
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Guardrail audit failed: {e}")
    except Exception as e:
        print(f"⚠️  Guardrail audit error: {e}")

def run_property_type_normalization():
    """Normalize property_type into canonical categories."""
    print("\n🧩 Normalizing property types...")
    try:
        subprocess.run([sys.executable, "normalize_property_types.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Property type normalization failed: {e}")
    except Exception as e:
        print(f"⚠️  Property type normalization error: {e}")


def run_property_type_override_sync():
    """Apply curated parcel/subdivision property-type overrides to the current DB."""
    print("\n🏷️  Applying property-type overrides...")
    try:
        subprocess.run([sys.executable, "apply_property_type_overrides.py", "--apply"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Property type override sync failed: {e}")
    except Exception as e:
        print(f"⚠️  Property type override sync error: {e}")


def run_cabana_flag_sync():
    """Flag likely cabana/storage/parking accessory records without deleting them."""
    print("\n🏷️  Flagging likely cabana records...")
    try:
        subprocess.run([sys.executable, "flag_cabanas.py", "--apply"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Cabana flag sync failed: {e}")
    except Exception as e:
        print(f"⚠️  Cabana flag sync error: {e}")

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
                "--window-days", "60",
                "--apply",
                "--report-path", report_path,
            ],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Cross-source cleanup failed: {e}")
    except Exception as e:
        print(f"⚠️  Cross-source cleanup error: {e}")

def run_rx_board_duplicate_cleanup():
    """Remove board-overlap sold duplicates (keep RX, remove non-RX)."""
    print("\n🧹 Cleaning board-overlap duplicates (keep RX)...")
    try:
        subprocess.run(
            [
                sys.executable,
                os.path.join("scripts", "maintenance", "clean_rx_board_duplicates.py"),
                "--window-days", "60",
                "--apply",
            ],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"⚠️  RX board cleanup failed: {e}")
    except Exception as e:
        print(f"⚠️  RX board cleanup error: {e}")

def run_data_integrity_sweep():
    """Run all data-quality hardening checks/fixes in sequence."""
    print("\n--- Data Integrity Sweep ---")
    run_subdivision_master_sync()
    run_cross_source_duplicate_cleanup()
    run_rx_board_duplicate_cleanup()
    run_pbc_geo_zone_audit_and_fix()
    run_property_type_normalization()
    run_property_type_override_sync()
    run_cabana_flag_sync()
    run_data_quality_guardrails()
    run_duplicate_audit_summary()
    run_mls_gap_batch_audit(pause=False)
    print("\n✅ Data integrity sweep complete.")
    input("\nPress Enter to continue...")


def run_mls_gap_batch_audit(pause=True):
    """Audit city/date coverage gaps and write proposed search batches."""
    print("\n--- MLS Coverage Gap Audit ---")
    cmd = [
        sys.executable,
        "audit_mls_gap_batches.py",
        "--cities", ",".join(DEFAULT_MLS_MARKETS),
    ]
    try:
        subprocess.run(cmd, check=True)
        print("✅ MLS gap batch audit complete.")
    except subprocess.CalledProcessError as e:
        print(f"⚠️  MLS gap batch audit failed: {e}")
    if pause:
        input("\nPress Enter to continue...")

def run_off_market_scraper_automation():
    """
    Automated off-market full pipeline:
    - Cities: Palm Beach + Wellington
    - Per-city start date: last imported PBC sold_date + 1 day
    - Import each newly generated ENHANCED CSV into DB
    - Run cabana merge in DB
    """
    print("\n--- Off-Market Full Pipeline (Automation Mode v2: Palm Beach + Wellington) ---")
    target_cities = ["Palm Beach", "Wellington"]
    print("Cities: Palm Beach + Wellington | Date mode: per-city incremental from last imported PBC sold date (+1 day)")
    started_ts = datetime.now().isoformat(timespec="seconds")
    city_runs = []
    try:
        # Step 1/2: Scrape + import per city
        for city in target_cities:
            city_started_at = time.time()
            date_meta = get_last_pbc_date_plus_one(city=city, fallback_global=True)
            if date_meta["start_date"]:
                print(
                    f"\nCity: {city} | incremental from {date_meta['source']} baseline "
                    f"{date_meta['baseline']} (+1 day => {date_meta['start_date']})"
                )
            else:
                print(f"\nCity: {city} | no prior PBC sold_date found; scraper default will be used")

            cmd = [
                sys.executable,
                "PalmBeachProrpertyScraper.py",
                "--city", city,
                "--non-interactive"
            ]
            if date_meta["start_date"]:
                cmd.extend(["--start-date", date_meta["start_date"]])
            else:
                cmd.append("--from-last-imported")
            try:
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError as city_err:
                print(f"\n⚠️  Scraper failed for {city}; continuing to next city. Error: {city_err}")
                city_runs.append(
                    {
                        "city": city,
                        "start_date_used": date_meta["start_date"],
                        "city_last_imported_sold_date": date_meta["city_latest"],
                        "global_last_imported_sold_date": date_meta["global_latest"],
                        "baseline_source": date_meta["source"],
                        "enhanced_csv": None,
                        "imported": False,
                        "scrape_error": str(city_err),
                    }
                )
                continue

            enhanced_csv = find_latest_enhanced_csv(created_after=city_started_at - 120)
            if not enhanced_csv:
                print(f"\n⚠️  No newly generated ENHANCED CSV found for {city}; skipping import.")
                city_runs.append(
                    {
                        "city": city,
                        "start_date_used": date_meta["start_date"],
                        "city_last_imported_sold_date": date_meta["city_latest"],
                        "global_last_imported_sold_date": date_meta["global_latest"],
                        "baseline_source": date_meta["source"],
                        "enhanced_csv": None,
                        "imported": False,
                    }
                )
                continue

            print(f"\n📥 Importing off-market CSV into database ({city}):\n{enhanced_csv}")
            subprocess.run([sys.executable, "pbc_importer.py", enhanced_csv], check=True)
            city_runs.append(
                {
                    "city": city,
                    "start_date_used": date_meta["start_date"],
                    "city_last_imported_sold_date": date_meta["city_latest"],
                    "global_last_imported_sold_date": date_meta["global_latest"],
                    "baseline_source": date_meta["source"],
                    "enhanced_csv": enhanced_csv,
                    "imported": True,
                }
            )

        # Step 3: Merge likely cabana records in DB
        print("\n🏷️  Running cabana merge on database...")
        subprocess.run(
            [sys.executable, "merge_cabanas.py", "--merge"],
            check=True
        )
        run_subdivision_master_sync()
        run_cross_source_duplicate_cleanup()
        run_rx_board_duplicate_cleanup()
        run_off_market_sync_audit()
        run_pbc_geo_zone_audit_and_fix()
        run_property_type_normalization()
        run_property_type_override_sync()
        run_cabana_flag_sync()
        run_data_quality_guardrails()
        run_duplicate_audit_summary()
        write_last_run(
            pipeline_name="off_market_auto",
            status="success",
            started_at=started_ts,
            details={
                "cities": target_cities,
                "mode": "incremental",
                "city_runs": city_runs,
            },
        )
        print("\n✅ Off-market automation pipeline complete.")
    except subprocess.CalledProcessError as e:
        write_last_run(
            pipeline_name="off_market_auto",
            status="failed",
            started_at=started_ts,
            error=e,
            details={
                "cities": target_cities,
                "mode": "incremental",
                "city_runs": city_runs,
            },
        )
        print(f"\nError running off-market automation pipeline: {e}")
    except Exception as e:
        write_last_run(
            pipeline_name="off_market_auto",
            status="failed",
            started_at=started_ts,
            error=e,
            details={
                "cities": target_cities,
                "mode": "incremental",
                "city_runs": city_runs,
            },
        )
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
    mode_choice = input("Search mode: 1) Municipality  2) Subdivision (official Name) [Enter=1]: ").strip() or "1"
    is_subdivision_mode = mode_choice == "2"
    city = ""
    subdivision_name = ""
    if is_subdivision_mode:
        subdivision_name = input("Enter Official Subdivision Name (lookup 'Name' column): ").strip()
        if not subdivision_name:
            print("Subdivision name is required for subdivision mode.")
            input("\nPress Enter to continue...")
            return
    else:
        city = input("Enter Municipality (Press Enter for 'Palm Beach'): ").strip() or "Palm Beach"
    start_date = input("Enter Start Date MM/DD/YYYY (optional): ").strip()
    end_date = input("Enter End Date MM/DD/YYYY (optional): ").strip()
    date_meta = get_last_pbc_date_plus_one(city=city if city else None, fallback_global=True)
    if not start_date and date_meta["start_date"] and not is_subdivision_mode:
        start_date = date_meta["start_date"]
        print(
            f"Using incremental start date for {city}: {start_date} "
            f"(baseline {date_meta['baseline']} from {date_meta['source']})"
        )
    started_ts = datetime.now().isoformat(timespec="seconds")
    started_at = time.time()

    if is_subdivision_mode:
        cmd = [
            sys.executable, "PalmBeachProrpertyScraper.py",
            "--search-mode", "subdivision",
            "--subdivision", subdivision_name,
            "--non-interactive",
        ]
    else:
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
        run_rx_board_duplicate_cleanup()
        run_pbc_geo_zone_audit_and_fix()
        run_property_type_normalization()
        run_property_type_override_sync()
        run_cabana_flag_sync()
        run_data_quality_guardrails()
        run_duplicate_audit_summary()
        write_last_run(
            pipeline_name="off_market_custom",
            status="success",
            started_at=started_ts,
            details={
                "mode": "subdivision" if is_subdivision_mode else "municipality",
                "city": city,
                "subdivision": subdivision_name or None,
                "start_date": start_date or None,
                "end_date": end_date or None,
                "city_last_imported_sold_date": date_meta["city_latest"],
                "global_last_imported_sold_date": date_meta["global_latest"],
                "baseline_source": date_meta["source"],
            },
        )
        print("\n✅ Off-market custom pipeline complete.")
    except subprocess.CalledProcessError as e:
        write_last_run(
            pipeline_name="off_market_custom",
            status="failed",
            started_at=started_ts,
            error=e,
            details={
                "mode": "subdivision" if is_subdivision_mode else "municipality",
                "city": city,
                "subdivision": subdivision_name or None,
                "start_date": start_date or None,
                "end_date": end_date or None,
                "city_last_imported_sold_date": date_meta["city_latest"],
                "global_last_imported_sold_date": date_meta["global_latest"],
                "baseline_source": date_meta["source"],
            },
        )
        print(f"\nError running off-market custom pipeline: {e}")
    except Exception as e:
        write_last_run(
            pipeline_name="off_market_custom",
            status="failed",
            started_at=started_ts,
            error=e,
            details={
                "mode": "subdivision" if is_subdivision_mode else "municipality",
                "city": city,
                "subdivision": subdivision_name or None,
                "start_date": start_date or None,
                "end_date": end_date or None,
                "city_last_imported_sold_date": date_meta["city_latest"],
                "global_last_imported_sold_date": date_meta["global_latest"],
                "baseline_source": date_meta["source"],
            },
        )
        print(f"\nAn unexpected error occurred: {e}")
    input("\nPress Enter to continue...")

def run_mls_update_automation():
    """
    Automated MLS update pipeline using fresh city Quick Search exports.
    """
    print("\n--- MLS Update (Fresh city search -> export -> import) ---")
    print("Markets: " + ", ".join(DEFAULT_MLS_MARKETS))
    started_ts = datetime.now().isoformat(timespec="seconds")
    template = "AIDataSet"
    city_runs = []

    try:
        for city in DEFAULT_MLS_MARKETS:
            city_slug = slugify_label(city)
            cmd = [
                sys.executable,
                "CMA/mls_quicksearch_export_from_cma.py",
                "--search-mode", "city",
                "--cities", city,
                "--derive-from-db",
                "--status-mode", "all",
                "--export-each-search",
                "--export-template", template,
                "--download-dir", os.path.join("output", f"mls_exports_{city_slug}"),
                "--debug-dir", os.path.join("output", f"mls_debug_{city_slug}"),
                "--import-to-db",
                "--db-file", "mls.db",
                "--backup-dir", "tmp",
            ]
            print(f"\nCity update: {city}")
            subprocess.run(cmd, check=True)
            city_runs.append({"city": city, "status": "success"})

        run_subdivision_master_sync()
        run_cross_source_duplicate_cleanup()
        run_rx_board_duplicate_cleanup()
        run_off_market_sync_audit()
        run_property_type_normalization()
        run_property_type_override_sync()
        run_cabana_flag_sync()
        run_data_quality_guardrails()
        run_duplicate_audit_summary()
        run_mls_gap_batch_audit(pause=False)
        write_last_run(
            pipeline_name="mls_auto_update",
            status="success",
            started_at=started_ts,
            details={"mode": "fresh_city_quicksearch", "cities": city_runs, "template": template},
        )
        print("\n✅ MLS update pipeline complete.")
    except subprocess.CalledProcessError as e:
        write_last_run(
            pipeline_name="mls_auto_update",
            status="failed",
            started_at=started_ts,
            error=e,
            details={"mode": "fresh_city_quicksearch", "cities": city_runs, "template": template},
        )
        print(f"\nError running MLS update pipeline: {e}")
    except Exception as e:
        write_last_run(
            pipeline_name="mls_auto_update",
            status="failed",
            started_at=started_ts,
            error=e,
            details={"mode": "fresh_city_quicksearch", "cities": city_runs, "template": template},
        )
        print(f"\nAn unexpected error occurred: {e}")
    input("\nPress Enter to continue...")


def run_cma_valuation():
    """Run CMA valuation module by subject parcel."""
    print("\n--- CMA Valuation (Parcel) ---")
    parcel = input("Enter subject parcel (with or without dashes): ").strip()
    if not parcel:
        print("Parcel is required.")
        input("\nPress Enter to continue...")
        return
    as_of = input("As-of date YYYY-MM-DD (Enter for today): ").strip()
    refresh_choice = input("Refresh off-market by unified subdivision before CMA? (Y/n): ").strip().lower()
    if refresh_choice in ("", "y", "yes"):
        print("\n🔄 CMA pre-refresh: OFF-MARKET ENABLED")
        try:
            refresh_result = run_cma_off_market_refresh(parcel=parcel, as_of_date=as_of or None, months_back=12)
            if isinstance(refresh_result, dict):
                print(
                    f"CMA pre-refresh summary: status={refresh_result.get('status')} "
                    f"| attempted={refresh_result.get('attempted')} | imported={refresh_result.get('imported')} "
                    f"| reason={refresh_result.get('reason') or 'none'}"
                )
        except Exception as e:
            print(f"⚠️  CMA off-market refresh error: {e}")
    else:
        print("\n⏭️  CMA pre-refresh: SKIPPED by user choice")
    cmd = [sys.executable, "-m", "cma_module.runner", "--parcel", parcel]
    if as_of:
        cmd.extend(["--as-of-date", as_of])
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"\nError running CMA valuation: {e}")
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
        print("5. 📥 Update MLS Markets (Fresh city search -> import)")
        print("6. 🤖 Off-Market Full Run (Auto incremental: scrape -> import -> cabana merge)")
        print("7. 🧭 Off-Market Pull (Custom city/date range)")
        print("8. ⚛️  Launch React Dashboard (API + frontend)")
        print("9. 🧪 Run Data Integrity + Coverage Sweep")
        print("10. 🧮 CMA Valuation (Parcel)")
        print("11. ❌ Exit")
        print("========================================")

        choice = input("Enter your choice (1-11): ").strip()
        
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
            run_cma_valuation()
        elif choice == '11':
            print("Goodbye!")
            break
        else:
            print("Invalid choice. Please try again.")
            time.sleep(1)

if __name__ == "__main__":
    main()
