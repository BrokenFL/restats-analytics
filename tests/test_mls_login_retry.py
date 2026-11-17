import os
import subprocess
import unittest
from unittest.mock import Mock, patch

from CMA import mls_quicksearch_export_from_cma as quicksearch
from scripts.ops import run_mls_auto_update as workflow


class MlsLoginRetryTests(unittest.TestCase):
    def refresh_city(self):
        workflow._run_city_refresh("Delray Beach", "AIDataSet", True, "all", None, True)

    @patch.object(workflow.time, "sleep")
    @patch.object(workflow.subprocess, "run")
    def test_transient_login_retries_same_city_once(self, run, sleep):
        run.side_effect = [subprocess.CalledProcessError(os.EX_TEMPFAIL, ["export"]), None]

        self.refresh_city()

        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0], run.call_args_list[1])
        sleep.assert_called_once_with(30)

    @patch.object(workflow.time, "sleep")
    @patch.object(workflow.subprocess, "run")
    def test_second_login_failure_surfaces_after_one_retry(self, run, sleep):
        run.side_effect = subprocess.CalledProcessError(os.EX_TEMPFAIL, ["export"])

        with self.assertRaisesRegex(workflow.MlsLoginRetryExhausted, "login remained unavailable"):
            self.refresh_city()

        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(30)

    @patch.object(workflow.time, "sleep")
    @patch.object(workflow.subprocess, "run")
    def test_general_export_or_import_failure_is_not_retried(self, run, sleep):
        run.side_effect = subprocess.CalledProcessError(1, ["export"])

        with self.assertRaises(subprocess.CalledProcessError):
            self.refresh_city()

        run.assert_called_once()
        sleep.assert_not_called()

    @patch.object(quicksearch, "_wait_for_top_frame", return_value=False)
    @patch.object(quicksearch, "_capture_debug")
    def test_provider_outage_is_classified_as_transient(self, capture_debug, top_frame):
        driver = Mock(
            window_handles=[],
            current_url="https://fl.flexmls.com",
            title="Flexmls",
            page_source="<p>Identity provider unavailable</p>",
        )
        with self.assertRaisesRegex(quicksearch.TransientLoginError, "identity provider reported unavailable"):
            quicksearch._wait_for_flex_shell(
                driver,
                Mock(),
                username="example",
                password="example",
                debug_dir="unused",
            )

        capture_debug.assert_called_once_with(driver, "unused", "identity_provider_unavailable")
