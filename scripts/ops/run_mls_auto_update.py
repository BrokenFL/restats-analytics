import argparse
import os
import subprocess
import sys
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
    return parser.parse_args()


def _run_city_refresh(city: str, template: str, headless: bool) -> None:
    city_slug = slugify_label(city)
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "CMA/mls_quicksearch_export_from_cma.py"),
        "--search-mode",
        "city",
        "--cities",
        city,
        "--derive-from-db",
        "--status-mode",
        "all",
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
    if headless:
        cmd.append("--headless")
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)


def main() -> int:
    args = parse_args()
    started_ts = datetime.now().isoformat(timespec="seconds")
    cities = [city.strip() for city in args.cities.split(",") if city.strip()]
    city_runs = []

    if not cities:
        raise SystemExit("At least one city is required.")

    try:
        for city in cities:
            print(f"\nCity update: {city}", flush=True)
            _run_city_refresh(city=city, template=args.template, headless=args.headless)
            city_runs.append({"city": city, "status": "success"})

        run_subdivision_master_sync()
        run_cross_source_duplicate_cleanup()
        run_rx_board_duplicate_cleanup()
        run_property_type_normalization()
        run_property_type_override_sync()
        run_cabana_flag_sync()
        run_data_quality_guardrails()
        run_duplicate_audit_summary()
        run_mls_gap_batch_audit(pause=False)
        write_last_run(
            pipeline_name="mls_auto_update",
            status="success",
            started_at=started_ts,
            details={
                "mode": "fresh_city_quicksearch",
                "cities": city_runs,
                "template": args.template,
                "headless": args.headless,
            },
        )
        print("\nMLS auto-update pipeline complete.", flush=True)
        return 0
    except subprocess.CalledProcessError as exc:
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
            },
        )
        print(f"\nMLS auto-update pipeline failed: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
