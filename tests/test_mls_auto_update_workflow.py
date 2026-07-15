import argparse
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
