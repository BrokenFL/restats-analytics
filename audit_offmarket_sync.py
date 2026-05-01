import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / "scripts/audits/audit_offmarket_sync.py"), run_name="__main__")
