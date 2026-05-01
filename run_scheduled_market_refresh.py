import argparse
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path


DEFAULT_CITIES = "Palm Beach,Wellington,Boca Raton,Delray Beach,South Palm Beach"


def run_and_stream(cmd, cwd, log_path):
    print(f"running={cmd}")
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"$ {cmd}\n")
        log_file.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            log_file.write(line)
        code = proc.wait()
        log_file.write(f"[exit_code={code}]\n")
        log_file.flush()
    return code


def build_mls_cmd(run_ts, cities, max_export_records):
    return (
        "python3 -u CMA/mls_quicksearch_export_from_cma.py "
        "--search-mode city "
        f"--cities {shlex.quote(cities)} "
        "--derive-from-db "
        "--export-each-search "
        "--import-to-db "
        "--headless "
        f"--download-dir {shlex.quote(f'output/mls_exports/automation_{run_ts}')} "
        f"--debug-dir {shlex.quote(f'output/mls_debug/automation_{run_ts}')} "
        '--db-file "mls.db" '
        '--backup-dir "backups" '
        f"--max-export-records {int(max_export_records)}"
    )


def build_pbc_cmd(run_ts, cities):
    return (
        "python3 -u run_pbc_city_refresh.py "
        f"--cities {shlex.quote(cities)} "
        "--from-last-imported "
        "--headless "
        f"--download-dir {shlex.quote(f'output/pbc_exports/automation_{run_ts}')} "
        '--db-file "mls.db" '
        '--backup-dir "backups"'
    )


def parse_args():
    p = argparse.ArgumentParser(description="Run MLS + PBC scheduled market refresh.")
    p.add_argument("--cities", default=DEFAULT_CITIES, help="Comma-separated city list.")
    p.add_argument("--max-export-records", type=int, default=4000)
    p.add_argument("--skip-mls", action="store_true")
    p.add_argument("--skip-pbc", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_root = Path(__file__).resolve().parent
    log_dir = project_root / "output" / "automation_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"market_refresh_{run_ts}.log"

    print(f"RUN_TS={run_ts}")
    print(f"log_path={log_path.relative_to(project_root)}")

    failures = []

    if not args.skip_mls:
        mls_code = run_and_stream(
            build_mls_cmd(run_ts, args.cities, args.max_export_records),
            cwd=project_root,
            log_path=log_path,
        )
        print(f"mls_exit_code={mls_code}")
        if mls_code != 0:
            failures.append(f"mls_exit_code={mls_code}")

    if not args.skip_pbc and not failures:
        pbc_code = run_and_stream(
            build_pbc_cmd(run_ts, args.cities),
            cwd=project_root,
            log_path=log_path,
        )
        print(f"pbc_exit_code={pbc_code}")
        if pbc_code != 0:
            failures.append(f"pbc_exit_code={pbc_code}")

    if failures:
        print("market_refresh_status=error")
        print("market_refresh_failures=" + ",".join(failures))
        raise SystemExit(1)

    print("market_refresh_status=ok")


if __name__ == "__main__":
    main()
