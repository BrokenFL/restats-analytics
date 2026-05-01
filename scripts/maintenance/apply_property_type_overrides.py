import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_cleaning import load_property_type_overrides, normalize_subdivision_name


def main():
    parser = argparse.ArgumentParser(description="Apply curated property-type overrides to the current DB.")
    parser.add_argument("--db", default=str(PROJECT_ROOT / "mls.db"))
    parser.add_argument("--lookup-dir", default=str(PROJECT_ROOT / "lookups"))
    parser.add_argument("--apply", action="store_true", help="Persist the updates. Default is dry-run.")
    args = parser.parse_args()

    subdivision_defaults, parcel_overrides = load_property_type_overrides(args.lookup_dir)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT rowid, listing_number, pcn_10_digit, final_subdivision, property_type
        FROM listing_details
        WHERE listing_number NOT LIKE 'PBC-%'
        """
    )
    rows = cur.fetchall()

    updates = []
    for row in rows:
        current = row["property_type"]
        pcn = "".join(ch for ch in str(row["pcn_10_digit"] or "") if ch.isdigit())[:10]
        subdivision = normalize_subdivision_name(row["final_subdivision"])
        target = None
        if subdivision and subdivision in subdivision_defaults:
            target = subdivision_defaults[subdivision]
        if pcn and pcn in parcel_overrides:
            target = parcel_overrides[pcn]
        if target and target != current:
            updates.append((target, row["rowid"]))

    print(f"Rows scanned: {len(rows)}")
    print(f"Rows needing update: {len(updates)}")

    if args.apply and updates:
        cur.executemany("UPDATE listing_details SET property_type = ? WHERE rowid = ?", updates)
        conn.commit()
        print("Updates applied.")
    elif args.apply:
        print("No updates needed.")
    else:
        print("Dry run only. Re-run with --apply to commit.")

    conn.close()


if __name__ == "__main__":
    main()
