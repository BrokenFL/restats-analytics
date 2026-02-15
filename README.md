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

## React Migration API (New)

A starter FastAPI service is now available at:

- `api/main.py`

Run locally:

```bash
uvicorn api.main:app --reload --port 8000
```

Starter endpoints:

- `GET /api/health`
- `GET /api/summary/kpis`
- `GET /api/market/trends`
- `GET /api/inventory/by-status`
- `GET /api/filters/options`
- `GET /api/listings/recent`
- `GET /api/market/report-summary`
- `GET /api/market/subdivision-rankings`
- `GET /api/market/period-series`
- `GET /api/ops/status`

Example:

```bash
curl "http://127.0.0.1:8000/api/summary/kpis?sold_since=2026-02-05"
```

Filterable query params (where supported):

- `city`
- `geo_zone`
- `final_subdivision`
- `property_type`
- `property_group` (`ALL`, `SINGLE_FAMILY`, `TOWNHOME_CONDO`)
- `sold_since` (`/api/summary/kpis`)
- `months` (`/api/market/trends`)
- `frequency` (`monthly|quarterly|annual` for `/api/market/trends`)
- `periods` (`/api/market/period-series`, e.g. 12 for trailing 12 months)
- `report_mode` (`rolling|monthly|quarterly|annual|custom`) for report endpoints
- `ref_year`, `ref_month`, `ref_quarter` for monthly/quarterly/annual report modes
- `start_date`, `end_date` (`YYYY-MM-DD`) for custom date-range mode

Note: `GET /api/filters/options` now accepts context filters (`city`, `geo_zone`, `property_type`, `property_group`) so subdivision dropdown options can be narrowed to the selected area/type.

## React Frontend Starter (New)

Starter app location:

- `frontend/`

Install and run:

```bash
cd frontend
npm install
npm run dev
```

The frontend reads the API base URL from:

- `VITE_API_BASE_URL` (default: `http://127.0.0.1:8000`)

Example:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

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

## MLS login automation (starter)

- Install deps:
  - `pip install -r requirements.txt`
- Run securely with env vars (recommended):
  - `export MLS_EMAIL='your_email_here'`
  - `export MLS_PASSWORD='your_password_here'`
  - `python3 mls_auto_login.py`
- Optional flags:
  - `python3 mls_auto_login.py --headless`
  - `python3 mls_auto_login.py --timeout 45 --stay-open-seconds 20`
- On login failure, screenshot is saved to:
  - `tmp/mls_login_error.png`

## MLS saved search export automation

- Script:
  - `python3 mls_export_saved_search.py --search-name "PalmBeach_Wellington_NewData"`
- Login-only debug:
  - `python3 mls_export_saved_search.py --login-only --debug-dir "tmp/mls_debug"`
- Update status date filters before export:
  - `python3 mls_export_saved_search.py --search-name "PalmBeach_Wellington_NewData" --from-date "02/01/2026"`
  - Applies value to: `from_4_2`, `from_4_4`, `from_4_5`, `from_4_6`, `from_4_7`, `from_4_8`
- End-to-end: export -> ingest -> DB merge:
  - `python3 mls_export_saved_search.py --search-name "PalmBeach_Wellington_NewData" --from-date "02/05/2026" --run-generate-db`
  - This copies the downloaded CSV into `input_csvs/` and runs `generate_db.py`
  - Prints run summary: `start_date`, downloaded file, DB row count before/after, and delta
- Default download output:
  - `output/mls_exports/`
- Full example:
  - `export MLS_EMAIL='your_email_here'`
  - `export MLS_PASSWORD='your_password_here'`
  - `python3 mls_export_saved_search.py --search-name "PalmBeach_Wellington_NewData" --download-dir "output/mls_exports"`
- Verbose debug run (action log + step captures):
  - `python3 mls_export_saved_search.py --search-name "PalmBeach_Wellington_NewData" --debug-dir "tmp/mls_debug"`
  - Run log defaults to `logs/mls_export_<timestamp>.log` (override with `--log-file`)
  - Browser console/network logs are also saved to:
    - `logs/mls_export_<timestamp>_browser.jsonl`
    - `logs/mls_export_<timestamp>_performance.jsonl`
- On export failure, screenshot is saved to:
  - `tmp/mls_export_error.png`

## Notes

- Lookup CSV files under `lookups/` are part of normalization quality.
- `mls.db` and raw CSV files are excluded by `.gitignore`.
- `requirements.txt` includes API-related packages, but this repo currently operates primarily through scripts + Streamlit UI.

## Duplicate tools

- Duplicate audit:
  - `python3 audit_duplicates.py --window-days 7 --sample-size 20`
  - Optional CSV report: `python3 audit_duplicates.py --export-report`
  - Save latest JSON summary (used by React Run Status panel):
    - `python3 audit_duplicates.py --window-days 7 --sample-size 20 --json-path output/audits/latest_audit_summary.json`
- Legacy PBC key migration (one-time):
  - Dry run: `python3 migrate_pbc_listing_numbers.py --dry-run`
  - Apply: `python3 migrate_pbc_listing_numbers.py --apply`

## Property Type Standardization

- Canonical DB values are now:
  - `Single Family Home`
  - `Condo/TH/Other`
- One-time backfill (safe to re-run):
  - `python3 normalize_property_types.py`

## PBC Geo-Zone Audit

- Audit/fix imported PBC Palm Beach geo zones (South End consistency):
  - Dry run: `python3 audit_fix_pbc_geo_zones.py`
  - Apply fixes: `python3 audit_fix_pbc_geo_zones.py --apply`
- Latest report can be written with:
  - `python3 audit_fix_pbc_geo_zones.py --apply --report-path output/audits/pbc_geo_zone_audit_latest.csv`

## Dashboard Parity Check

Compare legacy analytics metrics with new API summary for period/filter parity:

- Quarterly:
  - `python3 parity_check_dashboard.py --mode quarterly --year 2025 --quarter 4 --property-group ALL`
- Monthly:
  - `python3 parity_check_dashboard.py --mode monthly --year 2026 --month 1 --property-group SINGLE_FAMILY`
- Annual:
  - `python3 parity_check_dashboard.py --mode annual --year 2025 --property-group TOWNHOME_CONDO`
