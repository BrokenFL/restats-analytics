import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from CMA.mls_quicksearch_export_from_cma import _stamp_authoritative_city
from data_cleaning import backfill_incoming_from_existing_mls, process_and_load_data
from data_loader import DataLoader


class MlsImportIntegrityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_download_count_mismatch_leaves_csv_unstamped(self):
        export = self.root / "export.csv"
        payload = b"Listing Number,Status\nB26000001,A\nB26000002,A\n"
        export.write_bytes(payload)
        with self.assertRaisesRegex(ValueError, "contains 2 rows but Quick Search reported 1"):
            _stamp_authoritative_city(str(export), "Delray Beach", expected_count=1)
        self.assertEqual(export.read_bytes(), payload)

    def test_preservation_batches_lookups_under_sqlite_parameter_limit(self):
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.execute("""
                CREATE TABLE listing_details (
                    listing_number TEXT, parcel_id TEXT, listing_date TEXT,
                    sold_date TEXT, status TEXT, remarks TEXT
                )
            """)
            conn.execute("""
                INSERT INTO listing_details VALUES
                ('RX-1', '12000000005', '2026-11-01', NULL, 'A', 'Preserve me')
            """)
            conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 2)
            incoming = pd.DataFrame([
                {"listing_number": f"B2600000{i}", "parcel_id": f"1200000000{i}",
                 "listing_date": "2026-11-01", "sold_date": None, "status": "A", "remarks": None}
                for i in range(6)
            ])
            cleaned, filled_rows, _ = backfill_incoming_from_existing_mls(conn, incoming)
        self.assertEqual(filled_rows, 1)
        self.assertEqual(cleaned.iloc[-1]["remarks"], "Preserve me")

    def test_failed_finalize_rolls_back_upsert_and_inventory_retirement(self):
        db = self.root / "mls.db"
        with DataLoader(db) as loader:
            loader.create_database()
            with loader.conn:
                loader.conn.execute("""
                    INSERT INTO listing_details (listing_number, city, status)
                    VALUES ('B26000001', 'Delray Beach', 'A')
                """)
        export = self.root / "export.csv"
        export.write_text("Listing Number,City,Status\nB26000002,Delray Beach,A\n")
        with patch("data_cleaning.backfill_missing_city_in_db", side_effect=RuntimeError("blocked")):
            with self.assertRaisesRegex(RuntimeError, "blocked"):
                process_and_load_data(
                    [export], db, reconcile_active_inventory=True, refresh_date="2026-11-17"
                )
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(
                conn.execute("SELECT listing_number, effective_active_end_date FROM listing_details").fetchall(),
                [("B26000001", None)],
            )

    def test_cli_returns_failure_for_missing_or_malformed_export(self):
        db = self.root / "mls.db"
        malformed = self.root / "malformed.csv"
        malformed.write_text("bad,columns\na,b\n")
        importer = Path(__file__).resolve().parents[1] / "generate_db.py"
        for export in [self.root / "missing.csv", malformed]:
            with self.subTest(export=export.name):
                result = subprocess.run(
                    [sys.executable, str(importer), "--db-name", str(db),
                     "--skip-archive", "--defer-rx-cleanup", str(export)],
                    cwd=self.root, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertNotIn("Data successfully merged", result.stdout)
