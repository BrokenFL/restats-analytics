import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> int:
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return int(proc.returncode)


def _forwarded(args: list[str]) -> list[str]:
    if args and args[0] == "--":
        return args[1:]
    return args


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified ReStats CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Run the primary ingest pipeline.")
    ingest.add_argument("args", nargs=argparse.REMAINDER, help="Args forwarded to main.py")

    audit = sub.add_parser("audit", help="Run duplicate audit.")
    audit.add_argument("args", nargs=argparse.REMAINDER, help="Args forwarded to scripts/audits/audit_duplicates.py")

    report = sub.add_parser("report", help="Run parity report check.")
    report.add_argument("args", nargs=argparse.REMAINDER, help="Args forwarded to scripts/ops/parity_check_dashboard.py")

    guardrails = sub.add_parser("guardrails", help="Run post-ingest guardrail checks.")
    guardrails.add_argument("args", nargs=argparse.REMAINDER, help="Args forwarded to scripts/audits/audit_data_quality_guardrails.py")

    args = parser.parse_args()

    if args.command == "ingest":
        return _run([sys.executable, "main.py", *_forwarded(args.args)])
    if args.command == "audit":
        return _run([sys.executable, "scripts/audits/audit_duplicates.py", *_forwarded(args.args)])
    if args.command == "report":
        return _run([sys.executable, "scripts/ops/parity_check_dashboard.py", *_forwarded(args.args)])
    return _run([sys.executable, "scripts/audits/audit_data_quality_guardrails.py", *_forwarded(args.args)])


if __name__ == "__main__":
    raise SystemExit(main())
