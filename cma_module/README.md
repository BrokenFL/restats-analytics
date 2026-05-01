# CMA Module (Phase 1)

Run from project root:

```bash
python3 -m cma_module.runner --parcel "<PARCEL_ID>" --as-of-date "2026-02-16"
```

Outputs:

- `output/cma/<parcel>/top_comps.csv`
- `output/cma/<parcel>/valuation.json`
- `output/cma/<parcel>/context.json`

## What Phase 1 does

1. Loads subject from `mls.db` by parcel.
2. Expands market scope using lookup cheatsheets (PCN10 + unified subdivision).
3. Pulls sold candidates from last 24 months.
4. Applies tiered pool logic and similarity scoring.
5. Calculates value from weighted PPSF.
6. Computes **surrounding-area 60-day momentum**:
   - sold count / avg sold price / avg PPSF
   - pending count

Surrounding area currently means:
- same city
- same broad property group (single-family vs condo/th/other)
- and (`same geo_zone` or approx ~1 mile bounding box if subject has lat/lon)

