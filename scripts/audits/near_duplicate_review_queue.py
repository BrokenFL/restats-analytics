import argparse
import csv
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
import sys
from typing import Optional, Tuple, List, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DB_FILE = str(PROJECT_ROOT / "mls.db")


def normalize_address(value: str) -> str:
    if value is None:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def source_bucket(listing_number: str) -> str:
    v = str(listing_number or "").upper()
    if v.startswith("RX-"):
        return "RX"
    if v.startswith("PBC-"):
        return "PBC"
    if v.startswith("AX-"):
        return "AX"
    if re.match(r"^\d{2}-", v):
        return "LOCALNUM"
    return "OTHER"


def is_price_close(a, b) -> Tuple[bool, Optional[float], Optional[float]]:
    if a is None or b is None:
        return False, None, None
    try:
        av = float(a)
        bv = float(b)
    except Exception:
        return False, None, None
    if av <= 0 or bv <= 0:
        return False, None, None
    diff = abs(av - bv)
    pct = (diff / max(abs(av), abs(bv))) * 100.0
    tol = max(5000.0, max(abs(av), abs(bv)) * 0.01)
    return diff <= tol, diff, pct


def choose_action(row: dict) -> tuple[str, int, str]:
    src_a = row["source_a"]
    src_b = row["source_b"]
    day_diff = float(row["day_diff"] or 9999)
    addr_match = row["address_match"] == "1"
    price_close = row["price_close"] == "1"
    has_price = row["price_diff_abs"] not in ("", None)

    # Cross-source priority: keep RX when duplicate candidate is strong.
    if (src_a == "RX" and src_b != "RX") or (src_b == "RX" and src_a != "RX"):
        loser = row["listing_b"] if src_a == "RX" else row["listing_a"]
        if price_close and (addr_match or day_diff <= 14):
            return ("DELETE_LOWER_CONFIDENCE_KEEP_RX", 98, f"RX overlap: delete {loser}")
        if price_close and has_price:
            return ("REVIEW_RX_OVERLAP", 85, f"Likely RX overlap: review {loser}")
        if day_diff <= 7 and addr_match:
            return ("REVIEW_RX_OVERLAP", 80, f"Date/address aligned to RX: review {loser}")
        return ("REVIEW_RX_OVERLAP", 65, "RX overlap but weaker price/address signal")

    # Cross-source: keep MLS/board over PBC where evidence is strong.
    if (src_a == "PBC" and src_b != "PBC") or (src_b == "PBC" and src_a != "PBC"):
        loser = row["listing_a"] if src_a == "PBC" else row["listing_b"]
        if price_close and (addr_match or day_diff <= 21):
            return ("DELETE_PBC_KEEP_MLS", 95, f"PBC lag duplicate: delete {loser}")
        if day_diff <= 14 and addr_match:
            return ("DELETE_PBC_KEEP_MLS", 90, f"PBC likely duplicate: delete {loser}")
        return ("REVIEW_PBC_OVERLAP", 70, "PBC overlap but weak price/address signal")

    # Same-source duplicates should be reviewed unless extremely strong.
    if src_a == src_b:
        if price_close and addr_match and day_diff <= 14:
            return ("REVIEW_SAME_SOURCE_STRONG", 78, "Same-source near duplicate with strong match")
        return ("REVIEW_SAME_SOURCE", 50, "Same-source near duplicate")

    # Other mixed cases.
    if price_close and addr_match and day_diff <= 14:
        return ("REVIEW_MIXED_STRONG", 72, "Mixed-source strong match")
    return ("REVIEW_MIXED", 45, "Mixed-source weak match")


def load_pairs(conn: sqlite3.Connection, window_days: int):
    cur = conn.cursor()
    cur.execute(
        """
        WITH sales AS (
            SELECT
                listing_number,
                REPLACE(COALESCE(parcel_id, ''), '-', '') AS parcel_id_norm,
                DATE(sold_date) AS sold_dt,
                sold_price,
                COALESCE(short_address, '') AS short_address,
                COALESCE(city, '') AS city
            FROM listing_details
            WHERE parcel_id IS NOT NULL
              AND TRIM(parcel_id) <> ''
              AND sold_date IS NOT NULL
        )
        SELECT
            a.listing_number AS listing_a,
            b.listing_number AS listing_b,
            a.parcel_id_norm AS parcel_id,
            a.sold_dt AS sold_date_a,
            b.sold_dt AS sold_date_b,
            a.sold_price AS sold_price_a,
            b.sold_price AS sold_price_b,
            a.short_address AS address_a,
            b.short_address AS address_b,
            a.city AS city_a,
            b.city AS city_b,
            ABS(julianday(a.sold_dt) - julianday(b.sold_dt)) AS day_diff
        FROM sales a
        JOIN sales b
          ON a.parcel_id_norm = b.parcel_id_norm
         AND a.listing_number < b.listing_number
         AND ABS(julianday(a.sold_dt) - julianday(b.sold_dt)) <= ?
        ORDER BY day_diff ASC
        """,
        (window_days,),
    )
    return cur.fetchall()


def build_rows(pairs):
    out = []
    for (
        listing_a,
        listing_b,
        parcel_id,
        sold_date_a,
        sold_date_b,
        sold_price_a,
        sold_price_b,
        address_a,
        address_b,
        city_a,
        city_b,
        day_diff,
    ) in pairs:
        src_a = source_bucket(listing_a)
        src_b = source_bucket(listing_b)
        addr_a = normalize_address(address_a)
        addr_b = normalize_address(address_b)
        addr_match = "1" if addr_a and addr_b and addr_a == addr_b else "0"
        price_close, price_diff_abs, price_diff_pct = is_price_close(sold_price_a, sold_price_b)
        row = {
            "listing_a": listing_a,
            "listing_b": listing_b,
            "source_a": src_a,
            "source_b": src_b,
            "parcel_id": parcel_id,
            "sold_date_a": sold_date_a,
            "sold_date_b": sold_date_b,
            "day_diff": f"{float(day_diff):.1f}",
            "sold_price_a": sold_price_a if sold_price_a is not None else "",
            "sold_price_b": sold_price_b if sold_price_b is not None else "",
            "price_diff_abs": f"{float(price_diff_abs):.0f}" if price_diff_abs is not None else "",
            "price_diff_pct": f"{float(price_diff_pct):.2f}" if price_diff_pct is not None else "",
            "price_close": "1" if price_close else "0",
            "address_a": address_a,
            "address_b": address_b,
            "address_match": addr_match,
            "city_a": city_a,
            "city_b": city_b,
        }
        action, confidence, rationale = choose_action(row)
        row["recommended_action"] = action
        row["confidence"] = confidence
        row["rationale"] = rationale
        out.append(row)
    out.sort(key=lambda r: (-r["confidence"], float(r["day_diff"])))
    return out


def write_csv(path: str, rows: List[Dict]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            f.write("no_rows\n")
        return
    fields = [
        "recommended_action",
        "confidence",
        "rationale",
        "listing_a",
        "listing_b",
        "source_a",
        "source_b",
        "parcel_id",
        "sold_date_a",
        "sold_date_b",
        "day_diff",
        "sold_price_a",
        "sold_price_b",
        "price_diff_abs",
        "price_diff_pct",
        "price_close",
        "address_match",
        "address_a",
        "address_b",
        "city_a",
        "city_b",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def print_summary(rows: List[Dict]):
    print(f"pairs_scored: {len(rows)}")
    if not rows:
        return
    counts = {}
    for r in rows:
        counts[r["recommended_action"]] = counts.get(r["recommended_action"], 0) + 1
    print("action_counts:")
    for k in sorted(counts, key=lambda x: (-counts[x], x)):
        print(f"  {k}: {counts[k]}")
    high = [r for r in rows if r["confidence"] >= 90]
    print(f"high_confidence_pairs (>=90): {len(high)}")


def main():
    parser = argparse.ArgumentParser(description="Build a scored review queue for near-duplicate sales.")
    parser.add_argument("--db-file", default=DB_FILE)
    parser.add_argument("--window-days", type=int, default=60)
    parser.add_argument(
        "--out-path",
        default=os.path.join("output", "audits", "near_duplicate_review_queue_latest.csv"),
    )
    parser.add_argument("--high-confidence-only", action="store_true")
    parser.add_argument("--min-confidence", type=int, default=0)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_file)
    pairs = load_pairs(conn, args.window_days)
    conn.close()
    rows = build_rows(pairs)

    if args.high_confidence_only:
        rows = [r for r in rows if r["confidence"] >= max(90, args.min_confidence)]
    elif args.min_confidence > 0:
        rows = [r for r in rows if r["confidence"] >= args.min_confidence]

    write_csv(args.out_path, rows)
    print_summary(rows)
    print(f"report: {args.out_path}")


if __name__ == "__main__":
    main()
