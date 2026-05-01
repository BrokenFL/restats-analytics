import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).resolve().parent / "scripts/audits/near_duplicate_review_queue.py"),
        run_name="__main__",
    )
