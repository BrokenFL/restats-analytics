# PBC Downloader Script Spec (Parallel LLM Handoff)

This document explains how the off-market sales downloader works in this project so another LLM can extend it safely.

## Primary script

- Script: `PalmBeachProrpertyScraper.py`  
- Purpose: query Palm Beach County Property Appraiser sales search, export CSV, enrich each row with property details + geocoding, and output `ENHANCED_*.csv`.

## End-to-end flow

1. Open sales search page:
   - `https://pbcpao.gov/AdvSearch/SalesSearch`
2. Switch search mode to **Municipality** (multiple DOM fallback methods).
3. Select municipality (example: `Palm Beach`, `Wellington`).
4. Select sale type `QS` (Qualified Sales).
5. Set date(s):
   - from: `#SaleDateFrom`
   - to: `#SaleDateTo` (optional)
6. Submit search via `#btnFormSearch`.
7. Click CSV export (tries multiple selectors, including `.buttons-csv`).
8. Wait for downloaded CSV in `~/Downloads`.
9. Pre-filter rows before heavy enrichment:
   - missing parcel number
   - duplicate `(parcel, sale_date)` inside same CSV
   - already-in-database duplicates by `(parcel, sold_date)` within ±7 days
10. For each remaining row:
    - scrape detail page `https://pbcpao.gov/Property/Details?parcelId=<clean_pcn>`
    - extract structural fields (beds, baths, subdivision, etc.)
    - geocode (ArcGIS first, OSM fallback)
11. Write enhanced CSV:
    - `ENHANCED_<CITY>_<START>.csv`
    - or `ENHANCED_<CITY>_<START>_to_<END>.csv`
12. Run CSV-level cabana + condo same-day combine routine (`combine_cabana_sales`), producing `*_COMBINED.csv`.

## CLI interface (scraper)

- `--city` municipality name
- `--start-date MM/DD/YYYY`
- `--end-date MM/DD/YYYY`
- `--from-last-imported` (auto starts at last imported PBC sold date +1 day)
- `--non-interactive` (no prompts)

Example:

```bash
python3 PalmBeachProrpertyScraper.py --city "Palm Beach" --start-date 01/01/2025 --end-date 12/31/2025 --non-interactive
```

## How sales records are identified

- Key source columns from county CSV:
  - `Parcel Number`
  - `Sale Date`
  - `Sale Price`
  - `Location`
  - `Municipality`
- Existing DB sales are loaded from `listing_details(parcel_id, sold_date)`.
- Duplicate suppression uses fuzzy date matching (±7 days) for same parcel.

## How subdivision is identified

Subdivision comes from property detail page scrape:

- Field extracted as:
  - `details['Subdivision'] = get_detail_value(driver, "SUBDIVISION")`
- This value is written into enhanced CSV and then into DB via importer.
- In importer, it maps to:
  - `subdivision`
  - `final_subdivision` (initially same value)

Important: canonical subdivision standardization is later handled by master lookup sync (`sync_subdivisions_from_master.py`), not solely by raw scrape text.

## Importer contract (next script in pipeline)

- Script: `pbc_importer.py`
- Input: enhanced CSV from scraper.
- Builds stable listing identity:
  - `listing_number = PBC-<parcel>-<yyyymmdd>`
- Applies duplicate checks again before insert (same parcel/date ±7 days).
- Skips transfer-like deeds under `$10,000`.
- Applies property type canonicalization and geo-zone classification.

## Expected output artifacts

- Enhanced CSV(s): `~/Downloads/ENHANCED_*.csv`
- Combined CSV(s): `~/Downloads/ENHANCED_*_COMBINED.csv`
- DB inserts into `mls.db` table `listing_details` via `pbc_importer.py`

## Selectors and DOM resilience notes

- Municipality mode has fallbacks:
  - JS scanning of `<select>` options
  - radio/button fallback (including recorder-based XPath)
- CSV export has multiple fallback selectors.
- Detail page field extraction is label-driven (`get_detail_value`), with old/new layout support.

## Known assumptions and constraints

- Chrome + Selenium available locally.
- Downloads folder is writable and used as file handoff.
- Geocoding requires internet access.
- County site markup can change; selector fallback strategy is mandatory.

## Pipeline steps after scraper (recommended)

1. `pbc_importer.py <enhanced_csv>`
2. `merge_cabanas.py --merge`
3. `sync_subdivisions_from_master.py --apply`
4. `clean_cross_source_duplicates.py --apply`
5. `audit_fix_pbc_geo_zones.py --apply`
6. `normalize_property_types.py`
7. `audit_duplicates.py`
8. `audit_data_quality_guardrails.py`

## Recommendation for your parallel LLM handoff

Yes: use this file as the handoff source of truth, then attach the script files if needed:

- `PalmBeachProrpertyScraper.py`
- `pbc_importer.py`
- `merge_cabanas.py`
- `sync_subdivisions_from_master.py`

That is cleaner and more reliable than rewriting context in chat each time.
