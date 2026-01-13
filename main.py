import os
import sys
import subprocess
import time
import sqlite3

import shutil
import re
import glob
import pandas as pd

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
        print("5. ❌ Exit")
        print("========================================")
        
        choice = input("Enter your choice (1-5): ").strip()
        
        if choice == '1':
            run_data_processing()
        elif choice == '2':
            launch_dashboard()
        elif choice == '3':
            update_subdivisions()
        elif choice == '4':
            reset_database()
        elif choice == '5':
            print("Goodbye!")
            break
        else:
            print("Invalid choice. Please try again.")
            time.sleep(1)

if __name__ == "__main__":
    main()
