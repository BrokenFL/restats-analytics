import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / "scripts/maintenance/migrate_pbc_listing_numbers.py"), run_name="__main__")
