import csv
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.ops.reconcile_mls_closed_exports import reconcile_city


class MlsClosedParityTests(unittest.TestCase):
    def _create_db(self, path, rows):
        with sqlite3.connect(path) as conn:
            conn.execute(
                """CREATE TABLE listing_details (
                    listing_number TEXT, city TEXT, status TEXT, sold_date TEXT,
                    sold_price REAL, parcel_id TEXT, geo_zone TEXT, short_address TEXT
                )"""
            )
            conn.executemany(
                "INSERT INTO listing_details VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def _write_export(self, path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "Listing Number",
            "City",
            "Status",
            "Close Date",
            "Close Price",
            "Parcel Number",
            "Short Address",
        ]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_closed_export_parity_passes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "mls.db"
            self._create_db(
                db_path,
                [
                    ("R1", "Palm Beach", "C", "2026-07-02T00:00:00", 1000000, "P1", "South End", "1 Ocean"),
                    ("AX-2", "Palm Beach", "C", "2026-07-03T00:00:00", 2000000, "P2", "South End", "2 Ocean"),
                    ("R3", "Palm Beach", "C", "2026-07-04T00:00:00", 3000000, "P3", "South End", "3 Ocean"),
                ],
            )
            export_path = root / "mls_closed_exports_palm_beach" / "closed.csv"
            self._write_export(
                export_path,
                [
                    {
                        "Listing Number": "R1",
                        "City": "Palm Beach",
                        "Status": "C",
                        "Close Date": "07/02/2026",
                        "Close Price": "$1,000,000",
                        "Parcel Number": "P1",
                        "Short Address": "1 Ocean",
                    },
                    {
                        "Listing Number": "A2",
                        "City": "Palm Beach",
                        "Status": "C",
                        "Close Date": "07/03/2026",
                        "Close Price": "$2,000,000",
                        "Parcel Number": "P2",
                        "Short Address": "2 Ocean",
                    },
                    {
                        "Listing Number": "A3",
                        "City": "Palm Beach",
                        "Status": "C",
                        "Close Date": "07/04/2026",
                        "Close Price": "$3,000,000",
                        "Parcel Number": "P3",
                        "Short Address": "3 Ocean",
                    },
                ],
            )
            with sqlite3.connect(db_path) as conn:
                result = reconcile_city(
                    conn,
                    "Palm Beach",
                    root,
                    "mls_closed_exports",
                    start_date=date(2026, 7, 1),
                    end_date=None,
                )
            self.assertTrue(result["passed"])
            self.assertEqual(result["source_count"], 3)
            self.assertEqual(result["match_type_counts"]["listing_number_or_alias"], 2)
            self.assertEqual(result["match_type_counts"]["transaction_key"], 1)

    def test_closed_export_parity_flags_missing_and_stale_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "mls.db"
            self._create_db(
                db_path,
                [("R2", "Wellington", "A", None, 500000, "P2", "", "2 Lake")],
            )
            export_path = root / "mls_closed_exports_palm_beach" / "closed.csv"
            self._write_export(
                export_path,
                [
                    {
                        "Listing Number": "R2",
                        "City": "Palm Beach",
                        "Status": "C",
                        "Close Date": "07/03/2026",
                        "Close Price": "$500,000",
                        "Parcel Number": "P2",
                        "Short Address": "2 Lake",
                    },
                    {
                        "Listing Number": "R3",
                        "City": "Palm Beach",
                        "Status": "C",
                        "Close Date": "07/04/2026",
                        "Close Price": "$700,000",
                        "Parcel Number": "P3",
                        "Short Address": "3 Lake",
                    },
                ],
            )
            with sqlite3.connect(db_path) as conn:
                result = reconcile_city(
                    conn,
                    "Palm Beach",
                    root,
                    "mls_closed_exports",
                    start_date=date(2026, 7, 1),
                    end_date=None,
                )
            self.assertFalse(result["passed"])
            self.assertEqual(result["missing_in_db"], ["R3"])
            self.assertEqual(result["wrong_city"], [{"listing_number": "R2", "local_city": "Wellington", "source_city": "Palm Beach"}])
            self.assertEqual(result["local_not_closed"][0]["listing_number"], "R2")

    def test_empty_source_export_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "mls.db"
            self._create_db(db_path, [])
            export_path = root / "mls_closed_exports_palm_beach" / "closed.csv"
            self._write_export(export_path, [])
            with sqlite3.connect(db_path) as conn:
                result = reconcile_city(
                    conn,
                    "Palm Beach",
                    root,
                    "mls_closed_exports",
                    start_date=date(2026, 7, 1),
                    end_date=None,
                )
            self.assertFalse(result["passed"])
            self.assertTrue(result["empty_source"])


if __name__ == "__main__":
    unittest.main()
