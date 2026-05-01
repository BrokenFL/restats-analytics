import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).resolve().parent / "scripts/maintenance/apply_property_type_overrides.py"),
        run_name="__main__",
    )
