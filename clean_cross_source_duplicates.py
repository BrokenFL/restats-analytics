import argparse
import csv
import os
import sqlite3
from datetime import datetime


DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mls.db")


def find_cross_source_candidates(conn: sqlite3.Connection, window_days: int):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            p.listing_number AS pbc_listing,
            m.listing_number AS mls_listing,
            COALESCE(p.parcel_id, '') AS parcel_id,
            UPPER(TRIM(COALESCE(p.short_address, ''))) AS pbc_addr_norm,
            UPPER(TRIM(COALESCE(m.short_address, ''))) AS mls_addr_norm,
            COALESCE(p.city, '') AS pbc_city,
            COALESCE(m.city, '') AS mls_city,
            DATE(p.sold_date) AS pbc_sold_dt,
            DATE(m.sold_date) AS mls_sold_dt,
            p.sold_price AS pbc_sold_price,
            m.sold_price AS mls_sold_price,
            ABS(julianday(DATE(p.sold_date)) - julianday(DATE(m.sold_date))) AS day_diff
        FROM listing_details p
        JOIN listing_details m
          ON p.listing_number LIKE 'PBC-%'
         AND m.listing_number NOT LIKE 'PBC-%'
         AND p.sold_date IS NOT NULL
         AND m.sold_date IS NOT NULL
         AND ABS(julianday(DATE(p.sold_date)) - julianday(DATE(m.sold_date))) <= ?
         AND (
              (
                COALESCE(p.parcel_id, '') <> ''
                AND COALESCE(p.parcel_id, '') = COALESCE(m.parcel_id, '')
              )
              OR
              (
                UPPER(TRIM(COALESCE(p.short_address, ''))) <> ''
                AND UPPER(TRIM(COALESCE(p.short_address, ''))) = UPPER(TRIM(COALESCE(m.short_address, '')))
                AND UPPER(TRIM(COALESCE(p.city, ''))) = UPPER(TRIM(COALESCE(m.city, '')))
                AND p.sold_price IS NOT NULL AND m.sold_price IS NOT NULL
                AND ABS(p.sold_price - m.sold_price) <= 1
              )
         )
        """
        ,
        (window_days,),
    )
    return cur.fetchall()


def choose_pbc_rows_to_remove(rows):
    """
    One PBC row can match multiple MLS rows; keep the closest date match and remove the PBC row once.
    """
    best = {}
    for r in rows:
        pbc_listing = r[0]
        day_diff = float(r[11]) if r[11] is not None else 9999
        if pbc_listing not in best or day_diff < best[pbc_listing][11]:
            best[pbc_listing] = r
    return list(best.values())


def write_report(path, chosen_rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "pbc_listing",
                "mls_listing",
                "parcel_id",
                "pbc_city",
                "mls_city",
                "pbc_sold_dt",
                "mls_sold_dt",
                "pbc_sold_price",
                "mls_sold_price",
                "day_diff",
                "pbc_addr_norm",
                "mls_addr_norm",
            ]
        )
        for r in chosen_rows:
            w.writerow(r)


def main():
    parser = argparse.ArgumentParser(description="Clean cross-source duplicates (PBC vs MLS).")
    parser.add_argument("--db-file", default=DB_FILE)
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--report-path",
        default=os.path.join("output", "audits", "cross_source_duplicate_cleanup.csv"),
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_file)
    rows = find_cross_source_candidates(conn, args.window_days)
    chosen = choose_pbc_rows_to_remove(rows)
    write_report(args.report_path, chosen)

    print(f"Candidates found: {len(rows)}")
    print(f"Unique PBC rows to remove: {len(chosen)}")
    print(f"Report: {args.report_path}")

    if args.apply and chosen:
        pbc_listings = [(r[0],) for r in chosen]
        cur = conn.cursor()
        cur.executemany("DELETE FROM listing_details WHERE listing_number = ?", pbc_listings)
        conn.commit()
        print(f"Deleted PBC duplicate rows: {cur.rowcount}")
    elif args.apply:
        print("No rows to delete.")
    else:
        print("Dry run only. Re-run with --apply to commit.")

    conn.close()


if __name__ == "__main__":
    main()

