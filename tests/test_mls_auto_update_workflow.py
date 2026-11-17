import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main as main_module
from scripts.ops import run_mls_auto_update as workflow


class MlsAutoUpdateWorkflowTests(unittest.TestCase):
    @patch.object(workflow.subprocess, "run")
    def test_snapshot_refresh_forces_every_cached_month(self, run):
        workflow._run_snapshot_refresh()
        command = run.call_args.args[0]
        self.assertIn("--force", command)
        self.assertIn("--all-existing", command)
        self.assertTrue(run.call_args.kwargs["check"])

    def test_county_and_cleanup_finish_before_sync_and_snapshot(self):
        calls = []
        args = argparse.Namespace(
            cities="South Palm Beach",
            headless=True,
            template="AIDataSet",
            status_mode="all",
            from_date=None,
            skip_cloud_sync=False,
            keep_cloud_only=False,
            skip_pbc=False,
            pbc_download_dir="output/pbc_exports",
            pbc_backup_dir="tmp",
            skip_snapshot_refresh=False,
            skip_active_reconciliation=False,
            mls_overlap_days=45,
            closed_lookback_days=180,
            skip_closed_backfill=True,
            pbc_overlap_days=90,
        )

        def record(name, result=None):
            def _call(*_args, **_kwargs):
                calls.append(name)
                return result

            return _call

        patches = [
            patch.object(workflow, "parse_args", return_value=args),
            patch.object(workflow, "_run_city_refresh", side_effect=record("city")),
            patch.object(
                workflow,
                "_run_pbc_refresh",
                side_effect=record(
                    "pbc",
                    {"cities": ["South Palm Beach"], "results": [], "manual_follow_up": None, "failed_cities": []},
                ),
            ),
            patch.object(workflow, "run_subdivision_master_sync", side_effect=record("cleanup")),
            patch.object(workflow, "run_cross_source_duplicate_cleanup"),
            patch.object(workflow, "run_rx_board_duplicate_cleanup"),
            patch.object(workflow, "run_pbc_geo_zone_audit_and_fix"),
            patch.object(workflow, "run_property_type_normalization"),
            patch.object(workflow, "run_property_type_override_sync"),
            patch.object(workflow, "run_cabana_flag_sync"),
            patch.object(workflow, "run_data_quality_guardrails"),
            patch.object(workflow, "run_duplicate_audit_summary"),
            patch.object(workflow, "run_mls_gap_batch_audit"),
            patch.object(workflow, "_run_cloud_sync", side_effect=record("sync")),
            patch.object(workflow, "_run_snapshot_refresh", side_effect=record("snapshot")),
            patch.object(workflow, "write_last_run"),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

        self.assertEqual(workflow.main(), 0)
        self.assertLess(calls.index("city"), calls.index("pbc"))
        self.assertLess(calls.index("pbc"), calls.index("cleanup"))
        self.assertLess(calls.index("cleanup"), calls.index("sync"))
        self.assertLess(calls.index("sync"), calls.index("snapshot"))

    @patch.object(workflow.subprocess, "run")
    def test_derived_city_refresh_passes_overlap(self, run):
        workflow._run_city_refresh(
            city="Palm Beach",
            template="AIDataSet",
            headless=True,
            status_mode="all",
            from_date=None,
            reconcile_active_inventory=False,
            overlap_days=45,
        )
        command = run.call_args.args[0]
        self.assertIn("--derive-from-db", command)
        self.assertIn("--overlap-days", command)
        self.assertIn("45", command)

    def test_pbc_result_parser_preserves_city_failure(self):
        result = workflow._parse_pbc_output(
            "\n".join(
                [
                    "pbc_city_result=Palm Beach|status=no_results|processed=0|imported=0|skipped=0|errors=0|csv=",
                    "pbc_city_result=Delray Beach|status=error|processed=0|imported=0|skipped=0|errors=1|csv=",
                    "pbc_manual_follow_up=Delray Beach(csv_export_unavailable)",
                ]
            ),
            ["Palm Beach", "Delray Beach"],
        )
        self.assertEqual(result["failed_cities"], ["Delray Beach"])
        self.assertEqual(result["manual_follow_up"], "Delray Beach(csv_export_unavailable)")

    def test_pbc_failure_marks_overall_run_failed(self):
        args = argparse.Namespace(
            cities="Palm Beach",
            headless=True,
            template="AIDataSet",
            status_mode="all",
            from_date=None,
            skip_cloud_sync=False,
            keep_cloud_only=False,
            skip_pbc=False,
            pbc_download_dir="output/pbc_exports",
            pbc_backup_dir="tmp",
            skip_snapshot_refresh=False,
            skip_active_reconciliation=False,
            mls_overlap_days=45,
            closed_lookback_days=180,
            skip_closed_backfill=True,
            pbc_overlap_days=90,
        )
        failure = workflow.PbcRefreshError(
            "County refresh failed for Palm Beach (exit code 1).",
            {
                "cities": ["Palm Beach"],
                "results": [{"city": "Palm Beach", "status": "error"}],
                "manual_follow_up": "Palm Beach(csv_export_unavailable)",
                "failed_cities": ["Palm Beach"],
            },
        )
        with (
            patch.object(workflow, "parse_args", return_value=args),
            patch.object(workflow, "_run_city_refresh"),
            patch.object(workflow, "_run_pbc_refresh", side_effect=failure),
            patch.object(workflow, "write_last_run") as write_last_run,
        ):
            self.assertEqual(workflow.main(), 1)

        final_payload = write_last_run.call_args.kwargs
        self.assertEqual(final_payload["status"], "failed")
        self.assertEqual(final_payload["details"]["phase"], "pbc_refresh")
        self.assertEqual(final_payload["details"]["pbc_refresh"]["failed_cities"], ["Palm Beach"])

    def test_pbc_idle_timeout_is_reported_as_a_county_failure(self):
        class SilentProcess:
            pid = 999999
            stdout = iter(())

            def __init__(self):
                self.stopped = False

            def poll(self):
                return -15 if self.stopped else None

            def terminate(self):
                self.stopped = True

            def wait(self, timeout=None):
                self.stopped = True
                return -15

            def kill(self):
                self.stopped = True

        with patch.object(workflow.subprocess, "Popen", return_value=SilentProcess()):
            with self.assertRaisesRegex(workflow.PbcRefreshError, "timed out"):
                workflow._run_pbc_refresh(
                    cities=["Palm Beach"],
                    headless=True,
                    download_dir="output/pbc_exports",
                    backup_dir="tmp",
                    idle_timeout_seconds=1,
                    heartbeat_seconds=1,
                )

    def test_running_last_run_has_no_finished_timestamp_and_is_atomic(self):
        original_ops_dir = main_module.OPS_DIR
        original_path = main_module.LAST_RUN_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            main_module.OPS_DIR = temp_dir
            main_module.LAST_RUN_PATH = str(Path(temp_dir) / "last_run.json")
            try:
                main_module.write_last_run("mls_auto_update", "running", details={"phase": "pbc_refresh"})
                with open(main_module.LAST_RUN_PATH, encoding="utf-8") as handle:
                    payload = json.load(handle)
                self.assertEqual(payload["status"], "running")
                self.assertIsNone(payload["finished_at"])
                self.assertEqual(list(Path(temp_dir).glob("*.tmp")), [])
            finally:
                main_module.OPS_DIR = original_ops_dir
                main_module.LAST_RUN_PATH = original_path


if __name__ == "__main__":
    unittest.main()
