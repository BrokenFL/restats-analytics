import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.chdir(PROJECT_ROOT)

from main import (  # noqa: E402
    DEFAULT_MLS_MARKETS,
    run_cross_source_duplicate_cleanup,
    run_data_quality_guardrails,
    run_duplicate_audit_summary,
    run_cabana_flag_sync,
    run_mls_gap_batch_audit,
    run_pbc_geo_zone_audit_and_fix,
    run_property_type_normalization,
    run_property_type_override_sync,
    run_rx_board_duplicate_cleanup,
    run_subdivision_master_sync,
    slugify_label,
    write_last_run,
)


def parse_args():
    parser = argparse.ArgumentParser(description="Non-interactive MLS auto-update runner.")
    parser.add_argument(
        "--cities",
        default=",".join(DEFAULT_MLS_MARKETS),
        help="Comma-separated city list.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Selenium/Chrome headlessly.",
    )
    parser.add_argument(
        "--template",
        default="AIDataSet",
        help="Export template name.",
    )
    parser.add_argument(
        "--status-mode",
        default="all",
        choices=["all", "closed-only", "active-only"],
        help="MLS status scope to export.",
    )
    parser.add_argument(
        "--from-date",
        default=None,
        help="Optional MLS status-date start, e.g. 02/01/2026. Uses DB-derived dates when omitted.",
    )
    parser.add_argument(
        "--skip-cloud-sync",
        action="store_true",
        help="Skip the follow-up SQLite to Supabase sync.",
    )
    parser.add_argument(
        "--keep-cloud-only",
        action="store_true",
        help="Do not prune cloud-only rows during the follow-up sync.",
    )
    parser.add_argument(
        "--skip-pbc",
        action="store_true",
        help="Skip the follow-up county off-market refresh/import step.",
    )
    parser.add_argument(
        "--pbc-download-dir",
        default=os.path.join("output", "pbc_exports"),
        help="Base directory for per-city county export files.",
    )
    parser.add_argument(
        "--pbc-backup-dir",
        default="tmp",
        help="Directory for county-import database backups.",
    )
    parser.add_argument(
        "--skip-snapshot-refresh",
        action="store_true",
        help="Skip rebuilding cached monthly report snapshots.",
    )
    return parser.parse_args()


def _run_city_refresh(city: str, template: str, headless: bool, status_mode: str, from_date: str | None) -> None:
    city_slug = slugify_label(city)
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "CMA/mls_quicksearch_export_from_cma.py"),
        "--search-mode",
        "city",
        "--cities",
        city,
        "--status-mode",
        status_mode,
        "--export-each-search",
        "--export-template",
        template,
        "--download-dir",
        os.path.join("output", f"mls_exports_{city_slug}"),
        "--debug-dir",
        os.path.join("output", f"mls_debug_{city_slug}"),
        "--import-to-db",
        "--db-file",
        "mls.db",
        "--backup-dir",
        "tmp",
    ]
    if from_date:
        cmd.extend(["--from-date", from_date])
    else:
        cmd.append("--derive-from-db")
    if headless:
        cmd.append("--headless")
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)


def _run_cloud_sync(keep_cloud_only: bool) -> None:
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts/ops/sync_sqlite_to_supabase.py"),
        "--delete-invalid-local",
    ]
    if keep_cloud_only:
        cmd.append("--keep-cloud-only")
    attempts = max(1, int(os.getenv("RESTATS_CLOUD_SYNC_ATTEMPTS", "3")))
    for attempt in range(1, attempts + 1):
        try:
            subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
            return
        except subprocess.CalledProcessError:
            if attempt >= attempts:
                raise
            delay = 5 * attempt
            print(
                f"Cloud sync attempt {attempt}/{attempts} failed; retrying in {delay}s.",
                flush=True,
            )
            time.sleep(delay)


def _run_snapshot_refresh() -> None:
    subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts/ops/generate_market_report_snapshots.py"),
            "--force",
            "--all-existing",
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )


def _run_pbc_refresh(cities: list[str], headless: bool, download_dir: str, backup_dir: str) -> dict:
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "run_pbc_city_refresh.py"),
        "--cities",
        ",".join(cities),
        "--download-dir",
        download_dir,
        "--db-file",
        "mls.db",
        "--backup-dir",
        backup_dir,
        "--from-last-imported",
    ]
    if headless:
        cmd.append("--headless")

    completed = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n", flush=True)
    if completed.stderr:
        print(completed.stderr, end="" if completed.stderr.endswith("\n") else "\n", flush=True)

    results = []
    manual_follow_up = ""
    for line in completed.stdout.splitlines():
        if line.startswith("pbc_city_result="):
            payload = line.split("=", 1)[1]
            parts = payload.split("|")
            row = {"city": parts[0]}
            for item in parts[1:]:
                if "=" not in item:
                    continue
                key, value = item.split("=", 1)
                row[key] = value
            results.append(row)
        elif line.startswith("pbc_manual_follow_up="):
            manual_follow_up = line.split("=", 1)[1].strip()

    failures = [row for row in results if row.get("status") == "error"]
    return {
        "cities": cities,
        "results": results,
        "manual_follow_up": manual_follow_up or None,
        "failed_cities": [row.get("city", "") for row in failures if row.get("city")],
    }


def main() -> int:
    args = parse_args()
    started_ts = datetime.now().isoformat(timespec="seconds")
    cities = [city.strip() for city in args.cities.split(",") if city.strip()]
    city_runs = []
    pbc_result = {
        "enabled": not args.skip_pbc,
        "cities": cities,
        "results": [],
        "manual_follow_up": None,
        "failed_cities": [],
    }

    if not cities:
        raise SystemExit("At least one city is required.")

    try:
        for city in cities:
            print(f"\nCity update: {city}", flush=True)
            _run_city_refresh(
                city=city,
                template=args.template,
                headless=args.headless,
                status_mode=args.status_mode,
                from_date=args.from_date,
            )
            city_runs.append({"city": city, "status": "success"})

        if not args.skip_pbc:
            print("\nCounty refresh: municipality search -> import", flush=True)
            pbc_result = {
                "enabled": True,
                **_run_pbc_refresh(
                    cities=cities,
                    headless=args.headless,
                    download_dir=args.pbc_download_dir,
                    backup_dir=args.pbc_backup_dir,
                ),
            }
        # Run every derived-field and dedupe pass after both MLS and county
        # imports so the cloud receives one fully normalized database.
        run_subdivision_master_sync()
        run_cross_source_duplicate_cleanup()
        run_rx_board_duplicate_cleanup()
        run_pbc_geo_zone_audit_and_fix()
        run_property_type_normalization()
        run_property_type_override_sync()
        run_cabana_flag_sync()
        run_data_quality_guardrails()
        run_duplicate_audit_summary()
        run_mls_gap_batch_audit(pause=False)
        if not args.skip_cloud_sync:
            print("\nCloud sync: local SQLite -> Supabase", flush=True)
            _run_cloud_sync(keep_cloud_only=args.keep_cloud_only)
        if not args.skip_snapshot_refresh and not args.skip_cloud_sync:
            print("\nSnapshot refresh: rebuilding all cached months", flush=True)
            _run_snapshot_refresh()
        write_last_run(
            pipeline_name="mls_auto_update",
            status="success",
            started_at=started_ts,
            details={
                "mode": "fresh_city_quicksearch",
                "cities": city_runs,
                "template": args.template,
                "headless": args.headless,
                "status_mode": args.status_mode,
                "from_date": args.from_date,
                "pbc_refresh": pbc_result,
                "cloud_sync": {
                    "enabled": not args.skip_cloud_sync,
                    "keep_cloud_only": args.keep_cloud_only,
                },
                "snapshot_refresh": {
                    "enabled": not args.skip_snapshot_refresh and not args.skip_cloud_sync,
                    "forced": not args.skip_snapshot_refresh and not args.skip_cloud_sync,
                },
            },
        )
        print("\nMLS auto-update pipeline complete.", flush=True)
        return 0
    except subprocess.CalledProcessError as exc:
        if len(city_runs) < len(cities):
            city_runs.append({"city": cities[len(city_runs)], "status": "failed", "error": str(exc)})
        write_last_run(
            pipeline_name="mls_auto_update",
            status="failed",
            started_at=started_ts,
            error=exc,
            details={
                "mode": "fresh_city_quicksearch",
                "cities": city_runs,
                "template": args.template,
                "headless": args.headless,
                "status_mode": args.status_mode,
                "from_date": args.from_date,
                "pbc_refresh": pbc_result,
                "cloud_sync": {
                    "enabled": not args.skip_cloud_sync,
                    "keep_cloud_only": args.keep_cloud_only,
                },
                "snapshot_refresh": {
                    "enabled": not args.skip_snapshot_refresh and not args.skip_cloud_sync,
                    "forced": not args.skip_snapshot_refresh and not args.skip_cloud_sync,
                },
            },
        )
        print(f"\nMLS auto-update pipeline failed: {exc}", flush=True)
        return int(exc.returncode or 1)
    except Exception as exc:
        write_last_run(
            pipeline_name="mls_auto_update",
            status="failed",
            started_at=started_ts,
            error=exc,
            details={
                "mode": "fresh_city_quicksearch",
                "cities": city_runs,
                "template": args.template,
                "headless": args.headless,
                "status_mode": args.status_mode,
                "from_date": args.from_date,
                "pbc_refresh": pbc_result,
                "cloud_sync": {
                    "enabled": not args.skip_cloud_sync,
                    "keep_cloud_only": args.keep_cloud_only,
                },
                "snapshot_refresh": {
                    "enabled": not args.skip_snapshot_refresh and not args.skip_cloud_sync,
                    "forced": not args.skip_snapshot_refresh and not args.skip_cloud_sync,
                },
            },
        )
        print(f"\nMLS auto-update pipeline failed: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
