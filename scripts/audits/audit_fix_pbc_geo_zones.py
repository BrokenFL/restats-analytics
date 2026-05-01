"""
Audit and fix Palm Beach geo_zone assignments using official zone bands.

Default behavior: dry-run and report only.
Use --apply to update DB.
"""

import argparse
import csv
import os
import sqlite3
from datetime import datetime
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from geo_zone_utils import classify_palm_beach_zone

DB_FILE = str(PROJECT_ROOT / "mls.db")


def run_audit(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT listing_number, short_address, city, geo_lat, geo_lon, geo_zone
        FROM listing_details
        WHERE city = 'Palm Beach'
        """
    )
    rows = cur.fetchall()

    to_set = []
    to_clear = []
    unknown = 0

    for listing_number, short_address, city, geo_lat, geo_lon, geo_zone in rows:
        try:
            lat = float(geo_lat) if geo_lat is not None else None
        except Exception:
            lat = None
        expected = classify_palm_beach_zone(lat, city, short_address=short_address)
        actual = geo_zone.strip() if isinstance(geo_zone, str) else geo_zone

        if lat is None:
            unknown += 1
            continue

        if expected is None and actual:
            to_clear.append((listing_number, short_address, lat, actual))
        elif expected is not None and actual != expected:
            to_set.append((listing_number, short_address, lat, actual, expected))

    return {
        "total_rows": len(rows),
        "unknown_lat_rows": unknown,
        "set_zone": to_set,
        "clear_zone": to_clear,
    }


def apply_fixes(conn, audit_result):
    cur = conn.cursor()
    for listing_number, _short_address, _lat, _actual, expected in audit_result["set_zone"]:
        cur.execute("UPDATE listing_details SET geo_zone = ? WHERE listing_number = ?", (expected, listing_number))
    for listing_number, *_ in audit_result["clear_zone"]:
        cur.execute("UPDATE listing_details SET geo_zone = NULL WHERE listing_number = ?", (listing_number,))
    conn.commit()


def write_report(path, audit_result):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["action", "listing_number", "short_address", "lat", "current_geo_zone", "expected_geo_zone"])
        for listing_number, short_address, lat, current_geo, expected_geo in audit_result["set_zone"]:
            w.writerow(["set_zone", listing_number, short_address, lat, current_geo, expected_geo])
        for listing_number, short_address, lat, current_geo in audit_result["clear_zone"]:
            w.writerow(["clear_zone", listing_number, short_address, lat, current_geo, ""])


def main():
    parser = argparse.ArgumentParser(description="Audit/fix PBC Palm Beach geo_zone assignments (all official zones).")
    parser.add_argument("--db-file", default=DB_FILE)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report-path", default=None)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_file)
    audit_result = run_audit(conn)

    print("\n=== PBC Geo-Zone Audit (Palm Beach, all zones) ===")
    print(f"total Palm Beach rows: {audit_result['total_rows']}")
    print(f"unknown/missing lat rows: {audit_result['unknown_lat_rows']}")
    print(f"rows to set zone: {len(audit_result['set_zone'])}")
    print(f"rows to clear zone: {len(audit_result['clear_zone'])}")

    if args.apply:
        apply_fixes(conn, audit_result)
        print("applied fixes to database.")
    else:
        print("dry-run only (no DB changes).")

    if args.report_path:
        write_report(args.report_path, audit_result)
        print(f"report saved: {args.report_path}")
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = os.path.join("output", "audits", f"pbc_geo_zone_audit_{ts}.csv")
        write_report(default_path, audit_result)
        print(f"report saved: {default_path}")

    conn.close()


if __name__ == "__main__":
    main()
