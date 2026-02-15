import argparse
import glob
import os
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(PROJECT_ROOT, "mls.db")
DOWNLOADS = os.path.expanduser("~/Downloads")


def run(cmd, label):
    print(f"\n=== {label} ===")
    print(" ".join(cmd))
    started = time.time()
    subprocess.run(cmd, check=True)
    elapsed = time.time() - started
    print(f"✓ {label} complete in {elapsed/60:.1f} min")


def latest_enhanced_csv(created_after=None):
    patterns = [
        os.path.join(DOWNLOADS, "ENHANCED_*_COMBINED.csv"),
        os.path.join(DOWNLOADS, "ENHANCED_*.csv"),
    ]
    candidates = []
    for pattern in patterns:
        for p in glob.glob(pattern):
            try:
                ctime = os.path.getctime(p)
            except Exception:
                continue
            if created_after is None or ctime >= created_after:
                candidates.append((ctime, p))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def get_missing_years(city, since_year=2021):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT CAST(strftime('%Y', DATE(sold_date)) AS INTEGER) y
        FROM listing_details
        WHERE listing_number LIKE 'PBC-%'
          AND city = ?
          AND sold_date IS NOT NULL
          AND DATE(sold_date) >= DATE(?)
        ORDER BY y
        """,
        (city, f"{since_year}-01-01"),
    )
    have = {r[0] for r in cur.fetchall() if r[0] is not None}
    conn.close()
    current_year = date.today().year
    return [y for y in range(since_year, current_year + 1) if y not in have]


def year_range(year):
    if year == date.today().year:
        return f"01/01/{year}", date.today().strftime("%m/%d/%Y")
    return f"01/01/{year}", f"12/31/{year}"


def run_cleanup():
    run([sys.executable, "merge_cabanas.py", "--merge"], "Cabana Merge")
    run([sys.executable, "sync_subdivisions_from_master.py", "--apply", "--report-path", "output/audits/subdivision_master_sync_report.csv"], "Subdivision Master Sync")
    run([sys.executable, "clean_cross_source_duplicates.py", "--window-days", "30", "--apply", "--report-path", "output/audits/cross_source_duplicate_cleanup.csv"], "Cross-Source Dedup Cleanup")
    run([sys.executable, "audit_fix_pbc_geo_zones.py", "--apply", "--report-path", "output/audits/pbc_geo_zone_audit_latest.csv"], "Geo-Zone Audit/Fix")
    run([sys.executable, "normalize_property_types.py"], "Property Type Normalization")
    run([sys.executable, "audit_duplicates.py", "--window-days", "7", "--sample-size", "20", "--json-path", "output/audits/latest_audit_summary.json"], "Duplicate Audit Summary")


def summary_counts():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    rows = []
    for city in ["Palm Beach", "Wellington"]:
        cur.execute(
            """
            SELECT strftime('%Y', DATE(sold_date)) AS yr, COUNT(*)
            FROM listing_details
            WHERE listing_number LIKE 'PBC-%'
              AND city = ?
              AND sold_date IS NOT NULL
              AND DATE(sold_date) >= DATE('2021-01-01')
            GROUP BY yr
            ORDER BY yr
            """,
            (city,),
        )
        rows.append((city, cur.fetchall()))
    conn.close()
    return rows


def main():
    parser = argparse.ArgumentParser(description="Backfill off-market PBC data since 2021 for Palm Beach and Wellington.")
    parser.add_argument("--since-year", type=int, default=2021)
    parser.add_argument("--cities", nargs="+", default=["Palm Beach", "Wellington"])
    args = parser.parse_args()

    os.makedirs(os.path.join(PROJECT_ROOT, "output", "audits"), exist_ok=True)
    log_path = os.path.join(PROJECT_ROOT, "output", "audits", f"backfill_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")

    all_missing = {}
    for city in args.cities:
        missing = get_missing_years(city, args.since_year)
        all_missing[city] = missing
        print(f"{city} missing years: {missing}")

    with open(log_path, "w", encoding="utf-8") as log:
        log.write("Backfill Off-Market Report\n")
        log.write(f"Started: {datetime.now().isoformat(timespec='seconds')}\n\n")
        for city, years in all_missing.items():
            log.write(f"{city} missing years: {years}\n")

    for city in args.cities:
        for year in all_missing[city]:
            start_date, end_date = year_range(year)
            started = time.time()
            run(
                [
                    sys.executable,
                    "PalmBeachProrpertyScraper.py",
                    "--city", city,
                    "--start-date", start_date,
                    "--end-date", end_date,
                    "--non-interactive",
                ],
                f"Scrape {city} {year}",
            )
            enhanced = latest_enhanced_csv(created_after=started - 120)
            if not enhanced:
                raise RuntimeError(f"Could not locate ENHANCED CSV for {city} {year}")
            run([sys.executable, "pbc_importer.py", enhanced], f"Import {city} {year}")
            run_cleanup()

            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"\nCompleted {city} {year}\n")
                log.write(f"CSV: {enhanced}\n")

    counts = summary_counts()
    with open(log_path, "a", encoding="utf-8") as log:
        log.write("\nFinal counts since 2021:\n")
        for city, rows in counts:
            log.write(f"{city}: {rows}\n")
        log.write(f"\nFinished: {datetime.now().isoformat(timespec='seconds')}\n")

    print(f"\n✅ Backfill complete. Report: {log_path}")


if __name__ == "__main__":
    main()

