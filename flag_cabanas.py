#!/usr/bin/env python3

import argparse
import sqlite3

import pandas as pd

from cabana_utils import likely_cabana_mask


def ensure_column(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(listing_details)").fetchall()}
    if "cabana_flag" not in cols:
        conn.execute("ALTER TABLE listing_details ADD COLUMN cabana_flag INTEGER DEFAULT 0")


def main() -> int:
    parser = argparse.ArgumentParser(description="Flag likely cabana/storage/parking accessory records.")
    parser.add_argument("--db", default="mls.db")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        ensure_column(conn)
        df = pd.read_sql_query(
            """
            SELECT listing_number, short_address, unit_number, legal_desc, public_remarks,
                   total_bedrooms, sqft_living, sold_price, list_price
            FROM listing_details
            """,
            conn,
        )
        if df.empty:
            print("No rows found.")
            return 0

        df["cabana_flag"] = likely_cabana_mask(df).astype(int)
        flagged = int(df["cabana_flag"].sum())
        print(f"Likely cabana rows: {flagged}")

        if args.apply:
            payload = df[["listing_number", "cabana_flag"]].copy()
            payload.to_sql("temp_cabana_flags", conn, if_exists="replace", index=False)
            with conn:
                conn.execute(
                    """
                    UPDATE listing_details
                    SET cabana_flag = COALESCE(
                        (SELECT t.cabana_flag
                         FROM temp_cabana_flags t
                         WHERE t.listing_number = listing_details.listing_number),
                        0
                    )
                    """
                )
                conn.execute("DROP TABLE temp_cabana_flags")
            print("Applied cabana flags to listing_details.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
