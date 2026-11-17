import argparse
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from PalmBeachProrpertyScraper import run_scraper
from pbc_importer import import_pbc_data


DEFAULT_CITIES = [
    "Palm Beach",
    "Wellington",
    "Boca Raton",
    "Delray Beach",
    "South Palm Beach",
]


def slugify(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_") or "city"


def emit_city_result(row):
    """Emit a machine-readable city result as soon as it is known."""
    print(
        "pbc_city_result="
        f"{row['city']}|status={row['status']}|processed={row['processed_count']}|"
        f"imported={row['imported']}|skipped={row['skipped']}|errors={row['errors']}|csv={row['csv']}",
        flush=True,
    )


def backup_db(db_file, backup_dir):
    db_path = Path(db_file)
    backup_root = Path(backup_dir)
    backup_root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_root / f"mls_backup_before_pbc_import_{ts}.db"
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(backup_path)) as backup:
            source.backup(backup)
    return str(backup_path)


def parse_args():
    p = argparse.ArgumentParser(description="Run per-city Palm Beach County off-market refresh and import.")
    p.add_argument(
        "--cities",
        default=",".join(DEFAULT_CITIES),
        help="Comma-separated municipality list.",
    )
    p.add_argument(
        "--download-dir",
        default="output/pbc_exports",
        help="Base directory for per-city PBC exports.",
    )
    p.add_argument(
        "--db-file",
        default="mls.db",
        help="SQLite DB file to import into.",
    )
    p.add_argument(
        "--backup-dir",
        default="backups",
        help="Directory for DB backup before first PBC import.",
    )
    p.add_argument(
        "--from-last-imported",
        action="store_true",
        help="Use the last imported PBC sold_date minus the configured overlap per city.",
    )
    p.add_argument(
        "--overlap-days",
        type=int,
        default=90,
        help="Days to overlap the county sold-date watermark.",
    )
    p.add_argument("--start-date", help="Optional fixed start date MM/DD/YYYY for all cities.")
    p.add_argument("--end-date", help="Optional fixed end date MM/DD/YYYY for all cities.")
    p.add_argument("--headless", action="store_true", help="Run Chrome headlessly.")
    p.add_argument(
        "--chromedriver-port",
        type=int,
        default=9516,
        help="Starting ChromeDriver port; increments by city to avoid collisions.",
    )
    return p.parse_args()


def main():
    args = parse_args()
    cities = [c.strip() for c in str(args.cities or "").split(",") if c.strip()]
    if not cities:
        raise SystemExit("No cities provided.")

    backup_path = ""
    results = []
    failures = []

    for index, city in enumerate(cities, start=1):
        city_slug = slugify(city)
        city_download_dir = Path(args.download_dir) / city_slug
        city_download_dir.mkdir(parents=True, exist_ok=True)
        print(f"[{index}/{len(cities)}] PBC municipality refresh: {city}", flush=True)

        try:
            scrape_result = run_scraper(
                target_city=city,
                start_date=args.start_date,
                end_date=args.end_date,
                use_last_imported=args.from_last_imported,
                prompt_for_missing=False,
                search_mode="municipality",
                headless=args.headless,
                download_folder=str(city_download_dir),
                chromedriver_port=args.chromedriver_port + index - 1,
                last_imported_overlap_days=args.overlap_days,
                db_file=args.db_file,
            ) or {}

            status = scrape_result.get("status")
            if status == "ok":
                final_csv = scrape_result.get("final_csv") or scrape_result.get("enhanced_csv")
                print(f"  pbc_csv={final_csv}", flush=True)
                if not backup_path:
                    backup_path = backup_db(args.db_file, args.backup_dir)
                    print(f"pbc_db_backup={backup_path}", flush=True)
                import_result = import_pbc_data(final_csv, dry_run=False, db_file=args.db_file)
                import_errors = import_result.get("errors", 0)
                row = {
                    "city": city,
                    "status": "error" if import_errors else "ok",
                    "csv": final_csv,
                    "processed_count": scrape_result.get("processed_count", 0),
                    "imported": import_result.get("imported", 0),
                    "skipped": import_result.get("skipped", 0),
                    "errors": import_errors,
                }
                if import_errors:
                    failures.append({"city": city, "reason": f"import_errors={import_errors}"})
                print(
                    f"  pbc_processed={row['processed_count']} pbc_imported={row['imported']} "
                    f"pbc_skipped={row['skipped']} pbc_errors={row['errors']}",
                    flush=True,
                )
            elif status == "no_results":
                row = {
                    "city": city,
                    "status": status,
                    "csv": "",
                    "processed_count": 0,
                    "imported": 0,
                    "skipped": 0,
                    "errors": 0,
                }
                print("  no_results=true", flush=True)
            else:
                reason = scrape_result.get("reason", "unknown_error")
                failures.append({"city": city, "reason": reason})
                row = {
                    "city": city,
                    "status": "error",
                    "csv": "",
                    "processed_count": 0,
                    "imported": 0,
                    "skipped": 0,
                    "errors": 1,
                }
                print(f"  pbc_error={reason}", flush=True)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            failures.append({"city": city, "reason": reason})
            row = {
                "city": city,
                "status": "error",
                "csv": "",
                "processed_count": 0,
                "imported": 0,
                "skipped": 0,
                "errors": 1,
            }
            print(f"  pbc_error={reason}", flush=True)

        results.append(row)
        emit_city_result(row)

    print("PBC city refresh completed.")
    if backup_path:
        print(f"pbc_db_backup={backup_path}")
    if failures:
        print("pbc_manual_follow_up=" + ",".join(f"{row['city']}({row['reason']})" for row in failures), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
