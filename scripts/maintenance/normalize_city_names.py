#!/usr/bin/env python3
"""Normalize city labels in the local ReStats SQLite database."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from city_utils import normalize_city_values_in_db


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="mls.db")
    args = parser.parse_args()

    db_path = Path(args.db_path).expanduser().resolve()
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    with sqlite3.connect(db_path) as conn:
        updated = normalize_city_values_in_db(conn)
        rows = conn.execute(
            """
            SELECT city, COUNT(*) AS count
            FROM listing_details
            WHERE city IS NOT NULL AND TRIM(city) <> ''
            GROUP BY city
            ORDER BY city
            """
        ).fetchall()

    print(f"Updated city labels: {updated}")
    for city, count in rows:
        print(f"{city}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
