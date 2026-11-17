import argparse
import fcntl
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timedelta
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
        "--max-export-records",
        type=int,
        default=4000,
        help="Fail a city export before download when the Quick Search result exceeds this limit.",
    )
    parser.add_argument(
        "--from-date",
        default=None,
        help="Optional MLS status-date start, e.g. 02/01/2026. Uses an overlapped DB-derived date when omitted.",
    )
    parser.add_argument(
        "--mls-overlap-days",
        type=int,
        default=45,
        help="Days to overlap the DB-derived MLS status-date cutoff.",
    )
    parser.add_argument(
        "--closed-lookback-days",
        type=int,
        default=180,
        help="Rolling close-date history pulled by the closed-only safety pass.",
    )
    parser.add_argument(
        "--skip-closed-backfill",
        action="store_true",
        help="Skip the rolling closed-only MLS safety pass (for diagnostics only).",
    )
    parser.add_argument(
        "--skip-mls",
        action="store_true",
        help="Skip MLS pulls while still running the county/cleanup/sync stages.",
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
        "--pbc-overlap-days",
        type=int,
        default=90,
        help="Days to overlap the county sold-date watermark.",
    )
    parser.add_argument(
        "--pbc-idle-timeout-seconds",
        type=int,
        default=int(os.getenv("RESTATS_PBC_IDLE_TIMEOUT_SECONDS", "900")),
        help="Fail the county subprocess after this many seconds without output.",
    )
    parser.add_argument(
        "--pbc-heartbeat-seconds",
        type=int,
        default=int(os.getenv("RESTATS_PBC_HEARTBEAT_SECONDS", "60")),
        help="Emit county progress while waiting for child-process output.",
    )
    parser.add_argument(
        "--skip-snapshot-refresh",
        action="store_true",
        help="Skip rebuilding cached monthly report snapshots.",
    )
    parser.add_argument(
        "--skip-active-reconciliation",
        action="store_true",
        help="Do not retire active rows absent from the full-city MLS refresh.",
    )
    return parser.parse_args()


def _run_city_refresh(
    city: str,
    template: str,
    headless: bool,
    status_mode: str,
    from_date: str | None,
    reconcile_active_inventory: bool,
    output_prefix: str = "mls_exports",
    debug_prefix: str = "mls_debug",
    overlap_days: int | None = None,
    max_export_records: int | None = None,
) -> None:
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
        os.path.join("output", f"{output_prefix}_{city_slug}"),
        "--debug-dir",
        os.path.join("output", f"{debug_prefix}_{city_slug}"),
        "--import-to-db",
        "--defer-rx-cleanup",
        "--db-file",
        "mls.db",
        "--backup-dir",
        "tmp",
    ]
    if reconcile_active_inventory:
        cmd.append("--reconcile-active-inventory")
    if from_date:
        cmd.extend(["--from-date", from_date])
    else:
        cmd.append("--derive-from-db")
        if overlap_days is not None:
            cmd.extend(["--overlap-days", str(overlap_days)])
    if max_export_records is not None:
        cmd.extend(["--max-export-records", str(max_export_records)])
    if headless:
        cmd.append("--headless")
    try:
        subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
    except subprocess.CalledProcessError as exc:
        if exc.returncode != os.EX_TEMPFAIL:
            raise
        print(f"{city}: transient BeachesMLS login failure. Retrying in 30 seconds with a fresh browser.", flush=True)
        time.sleep(30)
        try:
            subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
        except subprocess.CalledProcessError as retry_error:
            if retry_error.returncode != os.EX_TEMPFAIL:
                raise
            raise MlsLoginRetryExhausted(retry_error.returncode, retry_error.cmd) from retry_error


class MlsLoginRetryExhausted(subprocess.CalledProcessError):
    def __str__(self) -> str:
        return "BeachesMLS login remained unavailable after a retry with a fresh browser."


def _lookback_start_date(days: int, today=None) -> str:
    if days < 0:
        raise ValueError("lookback days must be zero or greater")
    reference = today or datetime.now().date()
    return (reference - timedelta(days=days)).strftime("%m/%d/%Y")


def _run_closed_history_refresh(
    cities: list[str],
    template: str,
    headless: bool,
    lookback_days: int,
    max_export_records: int = 4000,
) -> dict:
    start_date = _lookback_start_date(lookback_days)
    city_results = []
    for city in cities:
        print(f"\nClosed-history update: {city} from {start_date}", flush=True)
        _run_city_refresh(
            city=city,
            template=template,
            headless=headless,
            status_mode="closed-only",
            from_date=start_date,
            reconcile_active_inventory=False,
            output_prefix="mls_closed_exports",
            debug_prefix="mls_closed_debug",
            max_export_records=max_export_records,
        )
        city_results.append({"city": city, "status": "success", "from_date": start_date})
    return {
        "enabled": True,
        "lookback_days": lookback_days,
        "from_date": start_date,
        "cities": city_results,
    }


def _run_mls_closed_parity(cities: list[str], from_date: str) -> dict:
    output_path = os.path.join("output", "audits", "mls_closed_reconciliation_latest.json")
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts/ops/reconcile_mls_closed_exports.py"),
            "--cities",
            ",".join(cities),
            "--export-root",
            "output",
            "--export-prefix",
            "mls_closed_exports",
            "--db-file",
            "mls.db",
            "--from-date",
            from_date,
            "--output-json",
            output_path,
        ],
        cwd=PROJECT_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n", flush=True)
    if completed.stderr:
        print(completed.stderr, end="" if completed.stderr.endswith("\n") else "\n", flush=True)
    return {"status": "passed", "from_date": from_date, "report": output_path}


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


class PbcRefreshError(RuntimeError):
    def __init__(self, message: str, result: dict):
        super().__init__(message)
        self.result = result


def _parse_pbc_output(output: str, cities: list[str]) -> dict:
    results = []
    manual_follow_up = ""
    for line in output.splitlines():
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

    result_counts = Counter(row["city"] for row in results)
    successful = {row["city"] for row in results if row.get("status") in {"ok", "no_results"}}
    return {
        "cities": cities,
        "results": results,
        "manual_follow_up": manual_follow_up or None,
        "failed_cities": [city for city in cities if result_counts[city] != 1 or city not in successful],
    }


def _stop_pbc_process(process: subprocess.Popen) -> None:
    """Stop the county child and its browser descendants after an idle timeout."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (AttributeError, ProcessLookupError, PermissionError):
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (AttributeError, ProcessLookupError, PermissionError):
            process.kill()
        process.wait()


def _run_pbc_refresh(
    cities: list[str],
    headless: bool,
    download_dir: str,
    backup_dir: str,
    overlap_days: int = 90,
    idle_timeout_seconds: int = 900,
    heartbeat_seconds: int = 60,
) -> dict:
    if idle_timeout_seconds <= 0:
        raise ValueError("PBC idle timeout must be greater than zero")
    if heartbeat_seconds <= 0:
        raise ValueError("PBC heartbeat interval must be greater than zero")

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
        "--overlap-days",
        str(overlap_days),
    ]
    if headless:
        cmd.append("--headless")

    process = subprocess.Popen(
        cmd,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    assert process.stdout is not None

    output_lines: list[str] = []
    output_queue: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        try:
            for line in process.stdout:
                output_queue.put(line)
        finally:
            output_queue.put(None)

    reader = threading.Thread(target=read_output, name="pbc-output-reader", daemon=True)
    reader.start()
    last_output_at = time.monotonic()
    last_heartbeat_at = last_output_at
    current_city = "starting"
    stream_closed = False

    while not (stream_closed and process.poll() is not None):
        try:
            line = output_queue.get(timeout=1)
        except queue.Empty:
            now = time.monotonic()
            idle_for = int(now - last_output_at)
            if now - last_heartbeat_at >= heartbeat_seconds:
                print(
                    f"County refresh heartbeat: city={current_city}, idle={idle_for}s "
                    f"(timeout={idle_timeout_seconds}s)",
                    flush=True,
                )
                last_heartbeat_at = now
            if idle_for >= idle_timeout_seconds:
                _stop_pbc_process(process)
                reader.join(timeout=2)
                result = _parse_pbc_output("".join(output_lines), cities)
                raise PbcRefreshError(
                    f"County refresh timed out after {idle_for}s without output while processing {current_city}.",
                    result,
                )
            continue

        if line is None:
            stream_closed = True
            continue

        output_lines.append(line)
        print(line, end="" if line.endswith("\n") else "\n", flush=True)
        last_output_at = time.monotonic()
        last_heartbeat_at = last_output_at
        if line.startswith("[") and "] PBC municipality refresh: " in line:
            current_city = line.rsplit(":", 1)[-1].strip() or current_city

    reader.join(timeout=2)
    returncode = process.wait()
    result = _parse_pbc_output("".join(output_lines), cities)
    failed_cities = result["failed_cities"]
    if returncode or failed_cities:
        failed_label = ", ".join(failed_cities) if failed_cities else "unknown city"
        raise PbcRefreshError(
            f"County refresh failed for {failed_label} (exit code {returncode}).",
            result,
        )
    return result


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
    closed_backfill_result = {"enabled": False, "cities": []}
    mls_parity_result = None
    current_phase = "initializing"

    if not cities:
        raise SystemExit("At least one city is required.")

    def run_details() -> dict:
        return {
            "mode": "fresh_city_quicksearch",
            "phase": current_phase,
            "cities": city_runs,
            "template": args.template,
            "headless": args.headless,
            "status_mode": args.status_mode,
            "from_date": args.from_date,
            "mls_enabled": not getattr(args, "skip_mls", False),
            "max_export_records": getattr(args, "max_export_records", 4000),
            "mls_overlap_days": getattr(args, "mls_overlap_days", 45),
            "closed_backfill": closed_backfill_result,
            "mls_closed_parity": mls_parity_result,
            "pbc_refresh": pbc_result,
            "pbc_overlap_days": getattr(args, "pbc_overlap_days", 90),
            "cloud_sync": {
                "enabled": not args.skip_cloud_sync,
                "keep_cloud_only": args.keep_cloud_only,
            },
            "snapshot_refresh": {
                "enabled": not args.skip_snapshot_refresh and not args.skip_cloud_sync,
                "forced": not args.skip_snapshot_refresh and not args.skip_cloud_sync,
            },
        }

    def write_run_state(status: str, error=None) -> None:
        write_last_run(
            pipeline_name="mls_auto_update",
            status=status,
            started_at=started_ts,
            details=run_details(),
            error=error,
        )

    try:
        write_run_state("running")
        if not getattr(args, "skip_mls", False):
            for city in cities:
                current_phase = f"mls_active:{city}"
                write_run_state("running")
                print(f"\nCity update: {city}", flush=True)
                _run_city_refresh(
                    city=city,
                    template=args.template,
                    headless=args.headless,
                    status_mode=args.status_mode,
                    from_date=args.from_date,
                    reconcile_active_inventory=not args.skip_active_reconciliation,
                    overlap_days=getattr(args, "mls_overlap_days", 45),
                    max_export_records=getattr(args, "max_export_records", 4000),
                )
                city_runs.append(
                    {
                        "city": city,
                        "status": "success",
                        "status_mode": args.status_mode,
                        "from_date": args.from_date,
                    }
                )

        if (
            not getattr(args, "skip_mls", False)
            and args.status_mode == "all"
            and not getattr(args, "skip_closed_backfill", False)
        ):
            current_phase = "mls_closed_history"
            write_run_state("running")
            closed_backfill_result = _run_closed_history_refresh(
                cities=cities,
                template=args.template,
                headless=args.headless,
                lookback_days=getattr(args, "closed_lookback_days", 180),
                max_export_records=getattr(args, "max_export_records", 4000),
            )

        if not args.skip_pbc:
            current_phase = "pbc_refresh"
            write_run_state("running")
            print("\nCounty refresh: municipality search -> import", flush=True)
            try:
                pbc_result = {
                    "enabled": True,
                    **_run_pbc_refresh(
                        cities=cities,
                        headless=args.headless,
                        download_dir=args.pbc_download_dir,
                        backup_dir=args.pbc_backup_dir,
                        overlap_days=getattr(args, "pbc_overlap_days", 90),
                        idle_timeout_seconds=getattr(args, "pbc_idle_timeout_seconds", 900),
                        heartbeat_seconds=getattr(args, "pbc_heartbeat_seconds", 60),
                    ),
                }
            except PbcRefreshError as exc:
                pbc_result = {"enabled": True, **exc.result}
                raise
        # Run every derived-field and dedupe pass after both MLS and county
        # imports so the cloud receives one fully normalized database.
        current_phase = "normalization_and_audits"
        write_run_state("running")
        run_subdivision_master_sync()
        run_cross_source_duplicate_cleanup()
        run_rx_board_duplicate_cleanup()
        run_pbc_geo_zone_audit_and_fix()
        run_property_type_normalization()
        run_property_type_override_sync()
        run_cabana_flag_sync()
        if closed_backfill_result.get("enabled"):
            mls_parity_result = _run_mls_closed_parity(
                cities,
                closed_backfill_result["from_date"],
            )
        run_data_quality_guardrails()
        run_duplicate_audit_summary()
        run_mls_gap_batch_audit(pause=False)
        if not args.skip_cloud_sync:
            current_phase = "cloud_sync"
            write_run_state("running")
            print("\nCloud sync: local SQLite -> Supabase", flush=True)
            _run_cloud_sync(keep_cloud_only=args.keep_cloud_only)
        if not args.skip_snapshot_refresh and not args.skip_cloud_sync:
            current_phase = "snapshot_refresh"
            write_run_state("running")
            print("\nSnapshot refresh: rebuilding all cached months", flush=True)
            _run_snapshot_refresh()
        current_phase = "complete"
        write_run_state("success")
        print("\nMLS auto-update pipeline complete.", flush=True)
        return 0
    except subprocess.CalledProcessError as exc:
        if current_phase.startswith("mls_active:"):
            city_runs.append({"city": cities[len(city_runs)], "status": "failed", "error": str(exc)})
        write_run_state("failed", exc)
        print(f"\nMLS auto-update pipeline failed: {exc}", flush=True)
        return int(exc.returncode or 1)
    except Exception as exc:
        write_run_state("failed", exc)
        print(f"\nMLS auto-update pipeline failed: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    # Both schedulers and manual invocations write the same DB and run metadata.
    lock_path = PROJECT_ROOT / "output/ops/mls_auto_update.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as run_lock:
        try:
            fcntl.flock(run_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("An MLS refresh is already running. Its run status was left intact.")
        raise SystemExit(main())
