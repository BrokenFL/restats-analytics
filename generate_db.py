import argparse
import os
import glob
import shutil
import time
import subprocess
import sys
from data_cleaning import process_and_load_data

# --- CONFIGURATION ---
INPUT_DIR = "input_csvs"
RAW_INPUT_DIR = os.path.join(INPUT_DIR, "raw")
BOARD_INPUT_DIR = os.path.join(INPUT_DIR, "board")
ARCHIVE_DIR = "processed_archive"
DB_NAME = "mls.db"


def find_input_csvs(input_dir=INPUT_DIR, raw_input_dir=RAW_INPUT_DIR, board_input_dir=BOARD_INPUT_DIR):
    """Collect CSVs from raw, board, and top-level input folders."""
    raw_files = glob.glob(os.path.join(raw_input_dir, "*.csv"))
    board_files = glob.glob(os.path.join(board_input_dir, "*.csv"))
    root_files = glob.glob(os.path.join(input_dir, "*.csv"))
    # Process raw first, then board files, then top-level input_csvs files.
    return raw_files + board_files + root_files


def _is_board_file(path: str) -> bool:
    parent_folder = os.path.basename(os.path.dirname(path))
    return parent_folder == "board"


def parse_args():
    parser = argparse.ArgumentParser(description="Load MLS CSVs into the SQLite database.")
    parser.add_argument(
        "csv_files",
        nargs="*",
        help="Optional explicit CSV paths to load. Defaults to scanning input_csvs/ and input_csvs/raw/.",
    )
    parser.add_argument(
        "--db-name",
        default=DB_NAME,
        help="Target SQLite DB filename/path.",
    )
    parser.add_argument(
        "--skip-archive",
        action="store_true",
        help="Do not move processed CSVs into processed_archive after a successful load.",
    )
    parser.add_argument(
        "--reconcile-active-inventory",
        action="store_true",
        help="Treat incoming city exports as authoritative current inventory and retire absent active rows.",
    )
    return parser.parse_args()


def run_rx_board_cleanup():
    """Remove board-overlap sold duplicates by keeping RX listings."""
    script_path = os.path.join("scripts", "maintenance", "clean_rx_board_duplicates.py")
    if not os.path.exists(script_path):
        print(f"⚠️  Skipping RX board dedupe (missing script): {script_path}")
        return

    print("🧹 Running RX board-overlap dedupe (60-day window)...")
    try:
        subprocess.run(
            [sys.executable, script_path, "--window-days", "60", "--apply"],
            check=True,
        )
    except Exception as e:
        print(f"⚠️  RX board dedupe failed: {e}")

def main():
    args = parse_args()

    # 1. Ensure directories exist
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(RAW_INPUT_DIR, exist_ok=True)
    os.makedirs(BOARD_INPUT_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    # 2. Find CSVs in the Input Directory
    if args.csv_files:
        csv_files = [os.path.abspath(path) for path in args.csv_files]
        missing = [path for path in csv_files if not os.path.exists(path)]
        if missing:
            print("❌ Missing CSV file(s):")
            for path in missing:
                print(f"   - {path}")
            return
    else:
        csv_files = find_input_csvs()
    
    if not csv_files:
        print(f"❌ No CSV files found in '{INPUT_DIR}', '{RAW_INPUT_DIR}', or '{BOARD_INPUT_DIR}'.")
        print(f"   Please drop your new MLS export files in '{RAW_INPUT_DIR}' or board exports in '{BOARD_INPUT_DIR}'.")
        return

    print(f"✅ Found {len(csv_files)} new file(s) to process.")

    # 3. Process Data (Note: create_new=False is crucial here!)
    # We pass the list of files to the cleaner. 
    # It will clean them and call DataLoader.upsert_data internally.
    try:
        board_files = [path for path in csv_files if _is_board_file(path)]
        regular_files = [path for path in csv_files if not _is_board_file(path)]

        if regular_files:
            process_and_load_data(
                regular_files,
                args.db_name,
                create_new=False,
                reconcile_active_inventory=args.reconcile_active_inventory,
            )
        if board_files:
            print(f"🧹 Filtering board files to closed-only rows before import: {len(board_files)} file(s)")
            filtered_paths = []
            os.makedirs(os.path.join(INPUT_DIR, "_tmp_board_filtered"), exist_ok=True)
            for src in board_files:
                import csv
                filtered_name = f"closed_only_{os.path.basename(src)}"
                filtered_path = os.path.join(INPUT_DIR, "_tmp_board_filtered", filtered_name)
                with open(src, newline="", encoding="latin1") as infile, open(filtered_path, "w", newline="", encoding="utf-8") as outfile:
                    reader = csv.DictReader(infile)
                    writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames or [])
                    writer.writeheader()
                    kept = 0
                    for row in reader:
                        status = str(row.get("Status", "")).strip().upper()
                        sold_date = str(row.get("Sold Date", "")).strip()
                        sold_price = str(row.get("Sold Price", "")).strip()
                        if status == "C" or sold_date or sold_price:
                            writer.writerow(row)
                            kept += 1
                print(f"   - {os.path.basename(src)} -> {kept} closed rows")
                filtered_paths.append(filtered_path)
            if filtered_paths:
                process_and_load_data(filtered_paths, args.db_name, create_new=False)
        print("🚀 Data successfully merged into database.")
        run_rx_board_cleanup()
        
        # 4. Move processed files to Archive
        if args.skip_archive:
            print("📂 Archive step skipped.")
        else:
            for file_path in csv_files:
                filename = os.path.basename(file_path)
                parent_folder = os.path.basename(os.path.dirname(file_path))
                source_prefix = "raw_" if parent_folder == "raw" else ""
                if parent_folder == "board":
                    source_prefix = "board_"
                
                # Add timestamp to filename to prevent overwriting in archive
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                new_name = f"{timestamp}_{source_prefix}{filename}"
                dest_path = os.path.join(ARCHIVE_DIR, new_name)
                
                shutil.move(file_path, dest_path)
                print(f"📂 Archived: {filename} -> {dest_path}")

        print("✨ All done! You can restart the API/Dashboard.")

    except Exception as e:
        print(f"❌ Error during processing: {e}")

if __name__ == "__main__":
    main()
