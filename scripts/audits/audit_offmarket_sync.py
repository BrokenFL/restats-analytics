import argparse
import csv
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.maintenance.sync_subdivisions_from_master import canon, canon_pcn10, load_master_map


def _default_since_date(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _fetch_recent_pbc_rows(conn: sqlite3.Connection, since_date: str):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            listing_number,
            parcel_id,
            pcn_10_digit,
            city,
            short_address,
            DATE(sold_date) AS sold_date,
            sold_price,
            final_subdivision,
            pcn_validated
        FROM listing_details
        WHERE listing_number LIKE 'PBC-%'
          AND sold_date IS NOT NULL
          AND DATE(sold_date) >= DATE(?)
        ORDER BY DATE(sold_date) DESC, listing_number DESC
        """,
        (since_date,),
    )
    return cur.fetchall()


def _find_recent_cross_source_matches(conn: sqlite3.Connection, since_date: str, window_days: int):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            p.listing_number AS pbc_listing,
            m.listing_number AS mls_listing,
            COALESCE(p.parcel_id, '') AS parcel_id,
            COALESCE(p.city, '') AS pbc_city,
            COALESCE(m.city, '') AS mls_city,
            UPPER(TRIM(COALESCE(p.short_address, ''))) AS pbc_addr,
            UPPER(TRIM(COALESCE(m.short_address, ''))) AS mls_addr,
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
         AND DATE(p.sold_date) >= DATE(?)
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
        ORDER BY p.sold_date DESC, day_diff ASC
        """,
        (since_date, window_days),
    )
    return cur.fetchall()


def _build_issue_rows(recent_rows, cross_source_rows, master_map):
    issues = []
    overlap_seen = set()

    for row in recent_rows:
        listing_number, parcel_id, pcn_10_digit, city, short_address, sold_date, sold_price, final_subdivision, pcn_validated = row
        pcn10 = canon_pcn10(pcn_10_digit or parcel_id)
        master_subdivision = master_map.get(pcn10)

        if not final_subdivision or not str(final_subdivision).strip():
            issues.append(
                {
                    "issue_type": "missing_final_subdivision",
                    "listing_number": listing_number,
                    "parcel_id": parcel_id,
                    "city": city,
                    "sold_date": sold_date,
                    "sold_price": sold_price,
                    "short_address": short_address,
                    "final_subdivision": final_subdivision,
                    "master_subdivision": master_subdivision,
                    "related_listing": "",
                    "related_city": "",
                    "related_sold_date": "",
                    "day_diff": "",
                }
            )

        if int(pcn_validated or 0) != 1:
            issues.append(
                {
                    "issue_type": "pcn_not_validated",
                    "listing_number": listing_number,
                    "parcel_id": parcel_id,
                    "city": city,
                    "sold_date": sold_date,
                    "sold_price": sold_price,
                    "short_address": short_address,
                    "final_subdivision": final_subdivision,
                    "master_subdivision": master_subdivision,
                    "related_listing": "",
                    "related_city": "",
                    "related_sold_date": "",
                    "day_diff": "",
                }
            )

        if master_subdivision and canon(final_subdivision) != canon(master_subdivision):
            issues.append(
                {
                    "issue_type": "master_subdivision_mismatch",
                    "listing_number": listing_number,
                    "parcel_id": parcel_id,
                    "city": city,
                    "sold_date": sold_date,
                    "sold_price": sold_price,
                    "short_address": short_address,
                    "final_subdivision": final_subdivision,
                    "master_subdivision": master_subdivision,
                    "related_listing": "",
                    "related_city": "",
                    "related_sold_date": "",
                    "day_diff": "",
                }
            )

    for row in cross_source_rows:
        pbc_listing, mls_listing, parcel_id, pbc_city, mls_city, pbc_addr, mls_addr, pbc_sold_dt, mls_sold_dt, pbc_price, mls_price, day_diff = row
        key = (pbc_listing, mls_listing)
        if key in overlap_seen:
            continue
        overlap_seen.add(key)
        issues.append(
            {
                "issue_type": "cross_source_overlap",
                "listing_number": pbc_listing,
                "parcel_id": parcel_id,
                "city": pbc_city,
                "sold_date": pbc_sold_dt,
                "sold_price": pbc_price,
                "short_address": pbc_addr,
                "final_subdivision": "",
                "master_subdivision": "",
                "related_listing": mls_listing,
                "related_city": mls_city,
                "related_sold_date": mls_sold_dt,
                "day_diff": day_diff,
            }
        )

    return issues


def main():
    parser = argparse.ArgumentParser(description="Audit recent off-market rows against MLS sync and naming rules.")
    parser.add_argument("--db-file", default=str(PROJECT_ROOT / "mls.db"))
    parser.add_argument("--since-date", default=None, help="YYYY-MM-DD. Defaults to last 75 days.")
    parser.add_argument("--recent-days", type=int, default=75)
    parser.add_argument("--window-days", type=int, default=60)
    parser.add_argument(
        "--csv-path",
        default=str(PROJECT_ROOT / "output" / "audits" / "offmarket_sync_audit.csv"),
    )
    parser.add_argument(
        "--json-path",
        default=str(PROJECT_ROOT / "output" / "audits" / "offmarket_sync_audit_latest.json"),
    )
    parser.add_argument(
        "--lookup-dir",
        default=str(PROJECT_ROOT / "lookups"),
    )
    args = parser.parse_args()

    since_date = args.since_date or _default_since_date(args.recent_days)
    os.makedirs(os.path.dirname(args.csv_path), exist_ok=True)

    db_file = str(Path(args.db_file).expanduser().resolve())
    conn = sqlite3.connect(db_file)
    try:
        recent_rows = _fetch_recent_pbc_rows(conn, since_date)
        cross_source_rows = _find_recent_cross_source_matches(conn, since_date, args.window_days)
    finally:
        conn.close()

    master_map = load_master_map(args.lookup_dir)
    issues = _build_issue_rows(recent_rows, cross_source_rows, master_map)
    counts = Counter(issue["issue_type"] for issue in issues)

    with open(args.csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "issue_type",
                "listing_number",
                "parcel_id",
                "city",
                "sold_date",
                "sold_price",
                "short_address",
                "final_subdivision",
                "master_subdivision",
                "related_listing",
                "related_city",
                "related_sold_date",
                "day_diff",
            ],
        )
        writer.writeheader()
        writer.writerows(issues)

    summary = {
        "since_date": since_date,
        "recent_pbc_rows": len(recent_rows),
        "issues_total": len(issues),
        "issue_counts": dict(sorted(counts.items())),
        "csv_path": args.csv_path,
    }
    with open(args.json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
