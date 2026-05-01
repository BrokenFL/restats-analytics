import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / "scripts/maintenance/clean_rx_board_duplicates.py"), run_name="__main__")
