import os
import glob
import shutil
import time
from data_cleaning import process_and_load_data

# --- CONFIGURATION ---
INPUT_DIR = "input_csvs"
ARCHIVE_DIR = "processed_archive"
DB_NAME = "mls.db"

def main():
    # 1. Ensure directories exist
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    # 2. Find CSVs in the Input Directory
    csv_files = glob.glob(os.path.join(INPUT_DIR, "*.csv"))
    
    if not csv_files:
        print(f"❌ No CSV files found in '{INPUT_DIR}'.")
        print(f"   Please drop your new MLS export files there.")
        return

    print(f"✅ Found {len(csv_files)} new file(s) to process.")

    # 3. Process Data (Note: create_new=False is crucial here!)
    # We pass the list of files to the cleaner. 
    # It will clean them and call DataLoader.upsert_data internally.
    try:
        process_and_load_data(csv_files, DB_NAME, create_new=False)
        print("🚀 Data successfully merged into database.")
        
        # 4. Move processed files to Archive
        for file_path in csv_files:
            filename = os.path.basename(file_path)
            
            # Add timestamp to filename to prevent overwriting in archive
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            new_name = f"{timestamp}_{filename}"
            dest_path = os.path.join(ARCHIVE_DIR, new_name)
            
            shutil.move(file_path, dest_path)
            print(f"📂 Archived: {filename} -> {dest_path}")

        print("✨ All done! You can restart the API/Dashboard.")

    except Exception as e:
        print(f"❌ Error during processing: {e}")

if __name__ == "__main__":
    main()
