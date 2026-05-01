import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / "scripts/audits/audit_fix_pbc_geo_zones.py"), run_name="__main__")
