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


def build_refresh_cmd(run_ts, cities, max_export_records, skip_mls=False, skip_pbc=False):
    """Build the single guarded runner command used by scheduled refreshes."""
    del run_ts  # retained in the function signature for log/CLI compatibility
    cmd = (
        "python3 -u scripts/ops/run_mls_auto_update.py "
        f"--cities {shlex.quote(cities)} "
        "--headless "
        f"--max-export-records {int(max_export_records)} "
        "--mls-overlap-days 45 "
        "--closed-lookback-days 180 "
        "--pbc-overlap-days 90"
    )
    if skip_mls:
        cmd += " --skip-mls"
    if skip_pbc:
        cmd += " --skip-pbc"
    return cmd


def build_mls_cmd(run_ts, cities, max_export_records):
    """Backward-compatible alias for callers that schedule the full refresh."""
    return (
        build_refresh_cmd(
            run_ts,
            cities,
            max_export_records,
            skip_pbc=True,
        )
    )


def build_pbc_cmd(run_ts, cities):
    return build_refresh_cmd(run_ts, cities, 4000, skip_mls=True)


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

    if not args.skip_mls or not args.skip_pbc:
        refresh_code = run_and_stream(
            build_refresh_cmd(
                run_ts,
                args.cities,
                args.max_export_records,
                skip_mls=args.skip_mls,
                skip_pbc=args.skip_pbc,
            ),
            cwd=project_root,
            log_path=log_path,
        )
        print(f"refresh_exit_code={refresh_code}")
        if refresh_code != 0:
            failures.append(f"refresh_exit_code={refresh_code}")

    if failures:
        print("market_refresh_status=error")
        print("market_refresh_failures=" + ",".join(failures))
        raise SystemExit(1)

    print("market_refresh_status=ok")


if __name__ == "__main__":
    main()
