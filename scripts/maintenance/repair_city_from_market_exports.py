#!/usr/bin/env python3
"""Repair missing city values from authoritative city-scoped MLS exports."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MARKET_EXPORT_DIRS = {
    "Palm Beach": "mls_exports_palm_beach",
    "Wellington": "mls_exports_wellington",
    "Boca Raton": "mls_exports_boca_raton",
    "Delray Beach": "mls_exports_delray_beach",
    "South Palm Beach": "mls_exports_south_palm_beach",
}
MISSING_SQL = "LOWER(TRIM(COALESCE(city, ''))) IN ('', '<na>', '<nan>', 'n/a', 'na', 'nan', 'none', 'null')"


def _listing_numbers(csv_path: Path) -> set[str]:
    try:
        frame = pd.read_csv(csv_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except UnicodeDecodeError:
        frame = pd.read_csv(csv_path, dtype=str, keep_default_na=False, encoding="latin1")
    column = next((name for name in ("Listing Number", "Listing #", "listing_number") if name in frame), None)
    if column is None:
        return set()
    return {str(value).strip() for value in frame[column] if str(value).strip()}


def _market_listing_map(export_root: Path) -> tuple[dict[str, str], dict[str, set[str]]]:
    listing_city: dict[str, str] = {}
    conflicts: dict[str, set[str]] = {}
    for city, directory in MARKET_EXPORT_DIRS.items():
        for csv_path in sorted((export_root / directory).glob("*.csv")):
            for listing_number in _listing_numbers(csv_path):
                previous = listing_city.get(listing_number)
                if previous and previous != city:
                    conflicts.setdefault(listing_number, {previous}).add(city)
                    continue
                listing_city[listing_number] = city
    for listing_number in conflicts:
        listing_city.pop(listing_number, None)
    return listing_city, conflicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(PROJECT_ROOT / "mls.db"))
    parser.add_argument("--export-root", default=str(PROJECT_ROOT / "output"))
    parser.add_argument("--backup-dir", default=str(PROJECT_ROOT / "tmp"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    listing_city, conflicts = _market_listing_map(Path(args.export_root))
    if conflicts:
        print(f"Conflicting market exports skipped: {len(conflicts)}")

    with sqlite3.connect(db_path) as conn:
        missing_before = int(conn.execute(f"SELECT COUNT(*) FROM listing_details WHERE {MISSING_SQL}").fetchone()[0])
        candidates = [
            (city, listing_number)
            for listing_number, city in listing_city.items()
            if conn.execute(
                f"SELECT 1 FROM listing_details WHERE listing_number = ? AND {MISSING_SQL}",
                (listing_number,),
            ).fetchone()
        ]
        print(f"Missing city rows: {missing_before}; repair candidates: {len(candidates)}")
        if not args.apply:
            return 0

        backup_dir = Path(args.backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{db_path.stem}_backup_before_city_repair_{timestamp}{db_path.suffix}"
        shutil.copy2(db_path, backup_path)
        conn.executemany("UPDATE listing_details SET city = ? WHERE listing_number = ?", candidates)
        conn.commit()
        missing_after = int(conn.execute(f"SELECT COUNT(*) FROM listing_details WHERE {MISSING_SQL}").fetchone()[0])

    print(f"Applied city repairs: {len(candidates)}; remaining missing: {missing_after}")
    print(f"db_backup={backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
