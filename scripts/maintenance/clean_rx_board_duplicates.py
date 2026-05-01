import argparse
import csv
import os
import re
import sqlite3
from datetime import datetime
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DB_FILE = str(PROJECT_ROOT / "mls.db")


def normalize_address(value: str) -> str:
    if value is None:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def extract_unit_token(address: str) -> str:
    """
    Best-effort unit/apartment extractor.
    Returns normalized unit token (e.g., 306N, PH3, 3B) or "" when no clear unit is found.
    """
    if not address:
        return ""
    s = str(address).upper().strip()

    # Explicit unit markers.
    explicit_patterns = [
        r"\b(?:APT|APARTMENT|UNIT|STE|SUITE|#)\s*([A-Z0-9-]+)\b",
        r"\bPH\s*([A-Z0-9-]+)\b",
    ]
    for pat in explicit_patterns:
        m = re.search(pat, s)
        if m:
            return re.sub(r"[^A-Z0-9]", "", m.group(1))

    # Suffix forms often seen in condo records:
    # "... BLVD 307", "... AVE W 3 B", "... ROAD PH 3"
    two_token_suffix = re.search(
        r"\b(?:BLVD|BOULEVARD|AVE|AVENUE|RD|ROAD|DR|DRIVE|ST|STREET|PL|PLACE|LN|LANE|CT|COURT|WAY|CIR|CIRCLE|TER|TERRACE|PKWY|PARKWAY|HWY|HIGHWAY|TRL|TRAIL|ISLE|ISLAND)\s+(\d+)\s+([A-Z])\b$",
        s,
    )
    if two_token_suffix:
        return f"{two_token_suffix.group(1)}{two_token_suffix.group(2)}"

    ph_suffix = re.search(
        r"\b(?:BLVD|BOULEVARD|AVE|AVENUE|RD|ROAD|DR|DRIVE|ST|STREET|PL|PLACE|LN|LANE|CT|COURT|WAY|CIR|CIRCLE|TER|TERRACE|PKWY|PARKWAY|HWY|HIGHWAY|TRL|TRAIL|ISLE|ISLAND)\s+PH\s+([A-Z0-9]+)\b$",
        s,
    )
    if ph_suffix:
        return f"PH{ph_suffix.group(1)}"

    one_token_suffix = re.search(
        r"\b(?:BLVD|BOULEVARD|AVE|AVENUE|RD|ROAD|DR|DRIVE|ST|STREET|PL|PLACE|LN|LANE|CT|COURT|WAY|CIR|CIRCLE|TER|TERRACE|PKWY|PARKWAY|HWY|HIGHWAY|TRL|TRAIL|ISLE|ISLAND)\s+([A-Z0-9]+)\b$",
        s,
    )
    if one_token_suffix:
        token = re.sub(r"[^A-Z0-9]", "", one_token_suffix.group(1))
        # Require a numeric component so street words aren't misread as units.
        if re.search(r"\d", token):
            return token

    return ""


def is_primary_mls_listing(listing_number: str) -> bool:
    s = str(listing_number).upper().strip()
    return s.startswith("RX-") or re.fullmatch(r"R\d+", s) is not None


def find_candidates(conn: sqlite3.Connection, window_days: int):
    cur = conn.cursor()
    cur.execute(
        """
        WITH sales AS (
            SELECT
                listing_number,
                COALESCE(parcel_id, '') AS parcel_id,
                DATE(sold_date) AS sold_dt,
                sold_price,
                COALESCE(short_address, '') AS short_address,
                COALESCE(city, '') AS city
            FROM listing_details
            WHERE sold_date IS NOT NULL
              AND parcel_id IS NOT NULL
              AND TRIM(parcel_id) <> ''
        )
        SELECT
            a.listing_number AS listing_a,
            b.listing_number AS listing_b,
            a.parcel_id,
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
          ON a.parcel_id = b.parcel_id
         AND a.listing_number < b.listing_number
         AND ABS(julianday(a.sold_dt) - julianday(b.sold_dt)) <= ?
        """,
        (window_days,),
    )
    return cur.fetchall()


def choose_primary_mls_winners(rows):
    # loser_listing -> best matching row where winner is a primary MLS row.
    best = {}

    for row in rows:
        (
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
        ) = row

        a_is_primary = is_primary_mls_listing(listing_a)
        b_is_primary = is_primary_mls_listing(listing_b)
        if a_is_primary == b_is_primary:
            continue

        winner = listing_a if a_is_primary else listing_b
        loser = listing_b if a_is_primary else listing_a

        # Parcel is primary key for match, with price/date confirmation below.
        # Guardrail for master-parcel new-construction cases:
        # if both rows clearly indicate different unit identifiers, keep both.
        unit_a = extract_unit_token(address_a)
        unit_b = extract_unit_token(address_b)
        if unit_a and unit_b and unit_a != unit_b:
            continue

        # Hard rule: same parcel + close sold date (window filter) + price match => duplicate.
        # Keep the primary MLS listing, remove the secondary listing.
        if sold_price_a is None or sold_price_b is None:
            continue

        high = max(float(sold_price_a), float(sold_price_b))
        price_tol = max(5000.0, high * 0.01)
        price_diff = abs(float(sold_price_a) - float(sold_price_b))
        if price_diff > price_tol:
            continue

        score = (float(day_diff or 9999), float(price_diff), loser)
        if loser not in best or score < best[loser]["score"]:
            best[loser] = {
                "winner": winner,
                "loser": loser,
                "parcel_id": parcel_id,
                "sold_date_a": sold_date_a,
                "sold_date_b": sold_date_b,
                "sold_price_a": sold_price_a,
                "sold_price_b": sold_price_b,
                "address_a": address_a,
                "address_b": address_b,
                "city_a": city_a,
                "city_b": city_b,
                "day_diff": day_diff,
                "price_diff": price_diff,
                "score": score,
            }

    out = list(best.values())
    out.sort(key=lambda r: (r["day_diff"], r["price_diff"], r["loser"]))
    return out


def write_report(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "winner_primary_mls_listing",
                "loser_listing_to_delete",
                "parcel_id",
                "sold_date_a",
                "sold_date_b",
                "sold_price_a",
                "sold_price_b",
                "day_diff",
                "price_diff",
                "address_a",
                "address_b",
                "city_a",
                "city_b",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    r["winner"],
                    r["loser"],
                    r["parcel_id"],
                    r["sold_date_a"],
                    r["sold_date_b"],
                    r["sold_price_a"],
                    r["sold_price_b"],
                    r["day_diff"],
                    r["price_diff"],
                    r["address_a"],
                    r["address_b"],
                    r["city_a"],
                    r["city_b"],
                ]
            )


def main():
    parser = argparse.ArgumentParser(
        description="Clean board-overlap sold duplicates by keeping the primary MLS listing and deleting secondary duplicate rows."
    )
    parser.add_argument("--db-file", default=DB_FILE)
    parser.add_argument("--window-days", type=int, default=60)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report-path", default=None)
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = args.report_path or os.path.join("output", "audits", f"rx_board_duplicate_cleanup_{ts}.csv")

    conn = sqlite3.connect(args.db_file)
    rows = find_candidates(conn, args.window_days)
    chosen = choose_primary_mls_winners(rows)
    write_report(report_path, chosen)

    print(f"pairs examined: {len(rows)}")
    print(f"secondary duplicate rows flagged: {len(chosen)}")
    print(f"report: {report_path}")

    if args.apply and chosen:
        losers = [(r["loser"],) for r in chosen]
        cur = conn.cursor()
        cur.executemany("DELETE FROM listing_details WHERE listing_number = ?", losers)
        conn.commit()
        print(f"deleted rows: {cur.rowcount}")
    elif args.apply:
        print("no rows deleted")
    else:
        print("dry run only. re-run with --apply to commit.")

    conn.close()


if __name__ == "__main__":
    main()
