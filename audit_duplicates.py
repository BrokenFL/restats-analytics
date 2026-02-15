import argparse
import csv
import os
import sqlite3
from datetime import datetime
import json


DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mls.db")


def run_audit(db_file, window_days=7, sample_size=20):
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()

    # Should be impossible due PK, but report defensively.
    cur.execute(
        """
        SELECT listing_number, COUNT(*) AS c
        FROM listing_details
        GROUP BY listing_number
        HAVING c > 1
        ORDER BY c DESC
        """
    )
    dup_listing_numbers = cur.fetchall()

    cur.execute(
        """
        WITH sales AS (
            SELECT listing_number, parcel_id, DATE(sold_date) AS sold_dt
            FROM listing_details
            WHERE parcel_id IS NOT NULL AND sold_date IS NOT NULL
        )
        SELECT a.listing_number, b.listing_number, a.parcel_id, a.sold_dt, b.sold_dt
        FROM sales a
        JOIN sales b
          ON a.parcel_id = b.parcel_id
         AND a.listing_number < b.listing_number
         AND ABS(julianday(a.sold_dt) - julianday(b.sold_dt)) <= ?
        ORDER BY a.parcel_id, a.sold_dt
        """,
        (window_days,),
    )
    near_duplicates = cur.fetchall()

    cur.execute(
        """
        WITH sales AS (
            SELECT listing_number, parcel_id, DATE(sold_date) AS sold_dt
            FROM listing_details
            WHERE parcel_id IS NOT NULL AND sold_date IS NOT NULL
        )
        SELECT a.listing_number, b.listing_number, a.parcel_id, a.sold_dt, b.sold_dt
        FROM sales a
        JOIN sales b
          ON a.parcel_id = b.parcel_id
         AND a.listing_number < b.listing_number
         AND ABS(julianday(a.sold_dt) - julianday(b.sold_dt)) <= ?
         AND (
             (a.listing_number LIKE 'PBC-%' AND b.listing_number NOT LIKE 'PBC-%') OR
             (b.listing_number LIKE 'PBC-%' AND a.listing_number NOT LIKE 'PBC-%')
         )
        ORDER BY a.parcel_id, a.sold_dt
        """,
        (window_days,),
    )
    cross_source = cur.fetchall()
    conn.close()

    report = {
        "duplicate_listing_number_count": len(dup_listing_numbers),
        "near_duplicate_count": len(near_duplicates),
        "cross_source_count": len(cross_source),
        "duplicate_listing_number_samples": dup_listing_numbers[:sample_size],
        "near_duplicate_samples": near_duplicates[:sample_size],
        "cross_source_samples": cross_source[:sample_size],
    }
    return report


def write_report_csv(report, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["section", "listing_number_a", "listing_number_b", "parcel_id", "sold_date_a", "sold_date_b", "count"])
        for listing_number, count in report["duplicate_listing_number_samples"]:
            w.writerow(["duplicate_listing_number", listing_number, "", "", "", "", count])
        for a, b, parcel, da, db in report["near_duplicate_samples"]:
            w.writerow(["near_duplicate", a, b, parcel, da, db, ""])
        for a, b, parcel, da, db in report["cross_source_samples"]:
            w.writerow(["cross_source", a, b, parcel, da, db, ""])


def print_report(report):
    print("\n=== Duplicate Audit ===")
    print(f"duplicate listing_number rows: {report['duplicate_listing_number_count']}")
    print(f"near-duplicates (same parcel within window): {report['near_duplicate_count']}")
    print(f"cross-source near-duplicates (PBC vs MLS): {report['cross_source_count']}")


def write_report_json(report, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        **report,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Audit duplicate patterns in listing_details.")
    parser.add_argument("--db-file", default=DB_FILE)
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--export-report", action="store_true")
    parser.add_argument("--json-path", default=None)
    args = parser.parse_args()

    report = run_audit(args.db_file, window_days=args.window_days, sample_size=args.sample_size)
    print_report(report)

    if args.export_report:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join("output", "audits", f"duplicate_audit_{ts}.csv")
        write_report_csv(report, out_path)
        print(f"report saved: {out_path}")
    if args.json_path:
        write_report_json(report, args.json_path)
        print(f"json saved: {args.json_path}")


if __name__ == "__main__":
    main()
