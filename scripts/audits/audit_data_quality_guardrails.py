import argparse
import csv
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run_guardrails(db_path, sample_size):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    checks = {
        "sold_price_gt_2x_list_price": """
            SELECT listing_number, city, short_address, list_price, sold_price
            FROM listing_details
            WHERE sold_price IS NOT NULL
              AND list_price IS NOT NULL
              AND list_price > 0
              AND sold_price > (list_price * 2.0)
            ORDER BY sold_price DESC
        """,
        "sqft_living_nonpositive_with_sold_price": """
            SELECT listing_number, city, short_address, sqft_living, sold_price
            FROM listing_details
            WHERE sold_price IS NOT NULL
              AND sold_price > 0
              AND (sqft_living IS NULL OR sqft_living <= 0)
            ORDER BY sold_price DESC
        """,
        "effective_end_before_listing_date": """
            SELECT listing_number, city, short_address, listing_date, effective_active_end_date
            FROM listing_details
            WHERE listing_date IS NOT NULL
              AND effective_active_end_date IS NOT NULL
              AND DATE(effective_active_end_date) < DATE(listing_date)
            ORDER BY DATE(listing_date) DESC
        """,
    }

    summary = {}
    sample_rows = []

    for check_name, sql in checks.items():
        cur.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
        summary[check_name] = len(rows)
        for r in rows[:sample_size]:
            sample_rows.append({"check": check_name, **r})

    conn.close()

    total_failures = sum(summary.values())
    return summary, sample_rows, total_failures


def write_csv(path, sample_rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fields = [
        "check",
        "listing_number",
        "city",
        "short_address",
        "list_price",
        "sold_price",
        "sqft_living",
        "listing_date",
        "effective_active_end_date",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in sample_rows:
            writer.writerow(row)


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Run post-ingest data quality guardrail checks.")
    parser.add_argument("--db-file", default=str(PROJECT_ROOT / "mls.db"))
    parser.add_argument("--sample-size", type=int, default=25)
    parser.add_argument("--json-path", default="output/audits/latest_guardrail_summary.json")
    parser.add_argument("--csv-path", default="output/audits/latest_guardrail_samples.csv")
    args = parser.parse_args()

    if not os.path.exists(args.db_file):
        raise SystemExit(f"Database not found: {args.db_file}")

    summary, sample_rows, total_failures = run_guardrails(args.db_file, args.sample_size)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "db_file": os.path.abspath(args.db_file),
        "checks": summary,
        "total_failures": total_failures,
        "passed": total_failures == 0,
        "sample_size": args.sample_size,
        "sample_rows_count": len(sample_rows),
    }

    write_json(args.json_path, payload)
    write_csv(args.csv_path, sample_rows)

    print("\n=== Data Quality Guardrails ===")
    for k, v in summary.items():
        print(f"{k}: {v}")
    print(f"total_failures: {total_failures}")
    print(f"json: {args.json_path}")
    print(f"csv: {args.csv_path}")


if __name__ == "__main__":
    main()
