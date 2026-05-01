import argparse
import os
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def safe_move(src: Path, dst: Path, dry_run: bool) -> None:
    if not src.exists():
        return
    ensure_dir(dst.parent)
    if dry_run:
        print(f"DRY  move {src} -> {dst}")
        return
    shutil.move(str(src), str(dst))
    print(f"MOVE {src} -> {dst}")


def move_root_csvs(dry_run: bool) -> None:
    safe_move(ROOT / "customexport (93).csv", ROOT / "input_csvs" / "raw" / "customexport (93).csv", dry_run)
    safe_move(ROOT / "pbc_missing_details.csv", ROOT / "output" / "pbc" / "pbc_missing_details.csv", dry_run)


def archive_old_logs(days_old: int, dry_run: bool) -> None:
    logs_dir = ROOT / "logs"
    if not logs_dir.exists():
        return
    archive_dir = logs_dir / "archive" / datetime.now().strftime("%Y-%m")
    cutoff = datetime.now().timestamp() - (days_old * 86400)
    for path in logs_dir.glob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".log", ".jsonl"}:
            continue
        if path.stat().st_mtime < cutoff:
            safe_move(path, archive_dir / path.name, dry_run)


def archive_tmp(days_old: int, dry_run: bool) -> None:
    tmp_dir = ROOT / "tmp"
    if not tmp_dir.exists():
        return
    archive_dir = tmp_dir / "archive" / datetime.now().strftime("%Y-%m")
    cutoff = datetime.now().timestamp() - (days_old * 86400)

    for path in tmp_dir.glob("*"):
        if path.name == "archive":
            continue
        if path.is_file() and path.stat().st_mtime < cutoff:
            safe_move(path, archive_dir / path.name, dry_run)

    for name in ("mls_debug", "pb_board_filtered", "pdfs"):
        path = tmp_dir / name
        if path.exists():
            safe_move(path, archive_dir / name, dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(description="Organize generated artifacts in this project.")
    parser.add_argument("--days-old", type=int, default=3, help="Archive files older than this many days.")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without moving files.")
    args = parser.parse_args()

    move_root_csvs(args.dry_run)
    archive_old_logs(args.days_old, args.dry_run)
    archive_tmp(args.days_old, args.dry_run)


if __name__ == "__main__":
    main()
