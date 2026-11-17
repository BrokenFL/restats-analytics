import argparse
import unittest
from unittest.mock import patch

import run_pbc_city_refresh as pbc_refresh
from PalmBeachProrpertyScraper import page_has_no_results_message


class PbcRefreshStatusTests(unittest.TestCase):
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
