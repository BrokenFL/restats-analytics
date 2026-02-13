# ReStats - Real Estate Market Intelligence Engine

Automated MLS + off-market data pipeline and analytics dashboard for Palm Beach-area market tracking.

## What this app does

- Ingests MLS CSV exports into a normalized SQLite dataset.
- Applies timeline and status logic (including zombie listing detection).
- Standardizes subdivision naming with PCN lookup-based mapping and fallback grouping.
- Calculates market stats across monthly/quarterly/annual periods.
- Serves an interactive Streamlit dashboard and PDF report workflow.
- Supports off-market county sales scraping/import with duplicate and transfer filtering.
- Supports cabana/auxiliary-unit merge logic to avoid double-counting sales.

## Core stack

- Python 3
- Pandas / NumPy
- SQLite (`mls.db`, WAL mode)
- Streamlit + Plotly
- Selenium + requests (off-market scraping/enrichment)
- FPDF-based report generation in `report_generator.py`

## Repository map

- `app.py`: Streamlit app (filters, KPI display, charting, export entry points).
- `main.py`: Console menu for common operations.
- `generate_db.py`: MLS batch entrypoint (`input_csvs/*.csv` -> cleaning -> DB upsert).
- `data_cleaning.py`: MLS normalization, derived logic, lookup application, dedupe.
- `data_loader.py`: DB schema + insert/upsert implementation.
- `data_analysis.py` + `data_analysis_functions.py`: metric calculation engine.
- `report_generator.py`: PDF market report generation utilities.
- `PalmBeachProrpertyScraper.py`: off-market sales scraper + enricher.
- `pbc_importer.py`: importer for enriched off-market CSV into `listing_details`.
- `merge_cabanas.py`: DB-level condo/cabana merge workflow.
- `rescrape_missing_details.py`: fills missing beds/baths/sqft for imported PBC records.

## Data architecture

### MLS flow

1. Drop raw MLS CSV files into `input_csvs/`.
2. Run `generate_db.py` (or menu option in `main.py`).
3. `data_cleaning.py`:
   - Renames raw columns to normalized schema names.
   - Casts types (dates, numerics, booleans).
   - Computes `effective_active_end_date`, `calculated_status`, `is_zombie`.
   - Applies subdivision normalization via lookup sheets and PCN grouping.
   - Applies geo-zone tagging.
4. `data_loader.py` upserts into `listing_details` in `mls.db`.
5. Streamlit dashboard (`app.py`) reads DB and runs analytics.

### Off-market flow

1. Run `PalmBeachProrpertyScraper.py` to pull county sales search results and enrich each row.
2. Scraper performs:
   - Municipality search mode selection.
   - Date filter support (start, optional end).
   - Duplicate avoidance using PCN + fuzzy sold-date match against existing DB sales.
   - Geocoding enrichment and property-detail scrape.
   - CSV-level cabana combine pass for same owner + same day pairs.
3. Run `pbc_importer.py` on `ENHANCED_*.csv`:
   - Maps fields into `listing_details` schema.
   - Creates `listing_number` as `PBC-<parcel_number>`.
   - Sets closed-sale status fields (`status='C'`, `calculated_status='C'`).
   - Filters likely transfer deeds (`sale_price < $10,000`).
   - Reconciles `final_subdivision` via matching `pcn_10_digit` where possible.

## Cabana handling

Two layers exist:

- CSV-level (`PalmBeachProrpertyScraper.py`): combines cabana rows with main property rows using same `Sale Date` + `Owner Name`.
- DB-level (`merge_cabanas.py`): merges likely condo+cabana pairs in `listing_details` when:
  - same building,
  - within 7 days,
  - and pricing pattern suggests shared transaction.

## Main menu operations (`main.py`)

Current menu options:

1. Run MLS data processing (`generate_db.py`)
2. Launch Streamlit dashboard (`streamlit run app.py`)
3. Update subdivisions from lookup sheets
4. Reset database and restore archived input files
5. Off-market pull (automation): `Palm Beach` + start from last imported PBC date
6. Off-market pull (custom): custom city + optional date range
7. Exit

## Getting started

1. Install dependencies:
   - `pip install -r requirements.txt`
   - Ensure Streamlit/Selenium/browser driver are available in your environment.
2. Prepare MLS inputs:
   - Add MLS CSV exports to `input_csvs/`.
3. Build/update database:
   - `python3 generate_db.py`
4. Launch dashboard:
   - `streamlit run app.py`
   - or `python3 main.py` and use menu options.

## Off-market quick commands

- Interactive scraper:
  - `python3 PalmBeachProrpertyScraper.py`
- Automation mode:
  - `python3 PalmBeachProrpertyScraper.py --city "Palm Beach" --from-last-imported`
- Custom date range:
  - `python3 PalmBeachProrpertyScraper.py --city "Palm Beach" --start-date 01/01/2024 --end-date 12/31/2024`
- Import scraped CSV:
  - `python3 pbc_importer.py /path/to/ENHANCED_file.csv --dry-run`
  - `python3 pbc_importer.py /path/to/ENHANCED_file.csv`

## Notes

- Lookup CSV files under `lookups/` are part of normalization quality.
- `mls.db` and raw CSV files are excluded by `.gitignore`.
- `requirements.txt` includes API-related packages, but this repo currently operates primarily through scripts + Streamlit UI.
