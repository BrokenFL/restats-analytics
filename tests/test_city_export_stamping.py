import tempfile
import unittest
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from CMA.mls_quicksearch_export_from_cma import _derive_from_date_from_db, _stamp_authoritative_city


class CityExportStampingTests(unittest.TestCase):
    def test_city_column_is_added_to_export(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "export.csv"
            pd.DataFrame([{"Listing Number": "R1", "Short Address": "1 Ocean Blvd"}]).to_csv(
                path, index=False
            )
            _stamp_authoritative_city(str(path), "South Palm Beach")
            result = pd.read_csv(path, dtype=str)
            self.assertEqual(result.loc[0, "City"], "South Palm Beach")

    def test_derived_start_date_ignores_future_source_dates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mls.db"
            today = date.today()
            with sqlite3.connect(path) as conn:
                conn.execute(
                    """CREATE TABLE listing_details (
                        city TEXT, listing_date TEXT, status_change_date TEXT,
                        under_contract_date TEXT, sold_date TEXT, withdrawn_date TEXT,
                        temp_off_market_date TEXT, cancel_date TEXT, expiration_date TEXT
                    )"""
                )
                conn.execute(
                    "INSERT INTO listing_details (city, sold_date, under_contract_date) VALUES (?, ?, ?)",
                    (
                        "Palm Beach",
                        (today - timedelta(days=1)).isoformat(),
                        (today + timedelta(days=30)).isoformat(),
                    ),
                )
            self.assertEqual(
                _derive_from_date_from_db(str(path), ["Palm Beach"]),
                (today - timedelta(days=1)).strftime("%m/%d/%Y"),
            )


if __name__ == "__main__":
    unittest.main()
