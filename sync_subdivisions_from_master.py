import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / "scripts/maintenance/sync_subdivisions_from_master.py"), run_name="__main__")
