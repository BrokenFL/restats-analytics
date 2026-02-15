import argparse
import csv
import os
import re
import sqlite3
from datetime import datetime


DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mls.db")
LEGACY_RE = re.compile(r"^PBC-\d+$")


def score_row(row):
    """
    Deterministic richness scoring to resolve same-key collisions.
    row: sqlite row tuple from SELECT below.
    """
    # listing_number, parcel_id, sold_date, sold_price, total_bedrooms, baths_total, sqft_living,
    # year_built, geo_lat, geo_lon, final_subdivision
    score = 0
    for val in row[3:]:
        if val is not None and str(val) != "":
            score += 1
    return score


def build_new_key(parcel_id, sold_date):
    sold_dt = str(sold_date)[:10]
    ymd = sold_dt.replace("-", "")
    return f"PBC-{parcel_id}-{ymd}"


def migrate(db_file, apply=False):
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT listing_number, parcel_id, DATE(sold_date) AS sold_dt, sold_price, total_bedrooms,
               baths_total, sqft_living, year_built, geo_lat, geo_lon, final_subdivision
        FROM listing_details
        WHERE listing_number LIKE 'PBC-%'
          AND parcel_id IS NOT NULL
        """
    )
    rows = cur.fetchall()

    to_update = []
    skipped = []
    collisions = []

    grouped = {}
    for row in rows:
        listing_number = row[0]
        parcel_id = str(row[1]).replace("-", "").strip()
        sold_dt = row[2]

        if not LEGACY_RE.match(str(listing_number)):
            continue  # already migrated/date-suffixed

        if not sold_dt:
            skipped.append((listing_number, parcel_id, "missing sold_date"))
            continue

        new_key = build_new_key(parcel_id, sold_dt)
        grouped.setdefault(new_key, []).append(row)

    for new_key, group_rows in grouped.items():
        if len(group_rows) == 1:
            to_update.append((group_rows[0][0], new_key))
            continue

        # Collision: keep richest row, archive the rest.
        ranked = sorted(group_rows, key=score_row, reverse=True)
        keep = ranked[0]
        to_update.append((keep[0], new_key))
        for loser in ranked[1:]:
            collisions.append((new_key, keep[0], loser[0]))

    report = {
        "to_update_count": len(to_update),
        "collision_count": len(collisions),
        "skipped_count": len(skipped),
        "to_update": to_update,
        "collisions": collisions,
        "skipped": skipped,
    }

    if apply:
        cur.execute("BEGIN")
        try:
            for old_key, new_key in to_update:
                cur.execute(
                    "UPDATE listing_details SET listing_number = ? WHERE listing_number = ?",
                    (new_key, old_key),
                )
            # Delete collision losers after winner update.
            for _, _, loser in collisions:
                cur.execute("DELETE FROM listing_details WHERE listing_number = ?", (loser,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    conn.close()
    return report


def write_report(report, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["section", "a", "b", "c"])
        for old_key, new_key in report["to_update"]:
            w.writerow(["update", old_key, new_key, ""])
        for new_key, keep_key, drop_key in report["collisions"]:
            w.writerow(["collision", new_key, keep_key, drop_key])
        for old_key, parcel_id, reason in report["skipped"]:
            w.writerow(["skipped", old_key, parcel_id, reason])


def main():
    parser = argparse.ArgumentParser(description="Migrate legacy PBC listing numbers to date-suffixed keys.")
    parser.add_argument("--db-file", default=DB_FILE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report-path", default=None)
    args = parser.parse_args()

    if args.apply and args.dry_run:
        raise SystemExit("Choose only one: --dry-run or --apply")
    if not args.apply and not args.dry_run:
        args.dry_run = True

    report = migrate(args.db_file, apply=args.apply)
    print(f"to_update: {report['to_update_count']}")
    print(f"collisions: {report['collision_count']}")
    print(f"skipped: {report['skipped_count']}")
    print(f"mode: {'APPLY' if args.apply else 'DRY RUN'}")

    if args.report_path:
        out = args.report_path
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = os.path.join("output", "audits", f"migrate_pbc_listing_numbers_{ts}.csv")
    write_report(report, out)
    print(f"report saved: {out}")


if __name__ == "__main__":
    main()
