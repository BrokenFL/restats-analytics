import argparse
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import run_pbc_city_refresh as pbc_refresh
from PalmBeachProrpertyScraper import page_has_no_results_message
from data_loader import DataLoader
from pbc_importer import import_pbc_data


class PbcRefreshStatusTests(unittest.TestCase):
    def test_county_import_targets_only_the_requested_database(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "test.db"
            with DataLoader(db) as loader:
                loader.create_database()
            export = Path(directory) / "county.csv"
            export.write_text(
                "Parcel Number,Sale Date,Sale Price,Location,City\n"
                "12-43-46-01-01-001-0010,11/17/2026,250000,100 Test Ave,Delray Beach\n"
            )
            with redirect_stdout(StringIO()):
                result = import_pbc_data(export, db_file=db)
            self.assertEqual(result["imported"], 1)
            self.assertEqual(result["errors"], 0)
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM listing_details").fetchone(), (1,))

    def test_current_no_results_message_is_recognized(self):
        self.assertTrue(page_has_no_results_message("No Results matched your search criteria. Please modify your search."))
        self.assertTrue(page_has_no_results_message("No records"))
        self.assertFalse(page_has_no_results_message("Search results are ready"))

    def test_city_scrape_error_returns_nonzero_and_emits_city_result(self):
        args = argparse.Namespace(
            cities="Palm Beach",
            download_dir="output/pbc_exports",
            db_file="mls.db",
            backup_dir="tmp",
            from_last_imported=True,
            overlap_days=90,
            start_date=None,
            end_date=None,
            headless=True,
            chromedriver_port=9516,
        )
        with (
            patch.object(pbc_refresh, "parse_args", return_value=args),
            patch.object(
                pbc_refresh,
                "run_scraper",
                return_value={"status": "error", "reason": "csv_export_unavailable"},
            ),
            patch("builtins.print") as print_mock,
        ):
            self.assertEqual(pbc_refresh.main(), 1)

        emitted = "\n".join(str(call.args[0]) for call in print_mock.call_args_list)
        self.assertIn("pbc_city_result=Palm Beach|status=error", emitted)
        self.assertIn("pbc_manual_follow_up=Palm Beach(csv_export_unavailable)", emitted)
