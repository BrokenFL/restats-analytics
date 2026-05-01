# CMA Module Architecture (Phase Plan)

## Goal

Build a dedicated `cma_module` that:

1. Accepts a subject parcel/listing.
2. Expands candidate universe via PCN10 + unified subdivision + geo fallback.
3. Pulls comps from both MLS + county records.
4. Scores comps with explainable similarity logic.
5. Produces valuation output + confidence + audit trail.

This should remain separate from core ingest pipeline at first, then integrate into `main.py`.

---

## Key Enhancements to Include

In addition to sold comp matching, include **market activity signals**:

1. **Recent closed velocity (last 60 days)**
   - count
   - median sold price
   - median PPSF
2. **Pending momentum (same market scope)**
   - new pending count in last 30/60 days
   - pending-to-sold ratio
3. **Status mix context**
   - active inventory
   - months supply

These should reuse existing stats logic where possible:
- `data_analysis_functions.py` (`sales_count`, `pending_sales`, `active_inventory`, `months_supply`, etc.)

---

## Module Layout

Suggested folder:

`/Users/brookesnader/Library/Mobile Documents/com~apple~CloudDocs/ReStatsProgram DEC 2025/cma_module/`

Files:

1. `models.py`
   - Pydantic/dataclass models:
   - `SubjectProfile`, `CompCandidate`, `CompScore`, `ValuationResult`, `CMAContext`

2. `intake.py`
   - Input handling:
   - parcel id, optional MLS listing id, valuation date
   - resolve subject from DB + optional fresh scrape paths

3. `expansion.py`
   - PCN10/unified subdivision expansion from lookup cheatsheets
   - development grouping
   - fallback radius expansion (geo-based)

4. `harvest.py`
   - Pull candidate records:
   - MLS statuses (Closed, Pending, Active, AUC, Withdrawn, Cancelled)
   - county records sold history

5. `canonicalize.py`
   - Subject merge policy:
   - county wins: lot size, year built, legal/parcel traits
   - MLS wins: interior, amenities, remarks, listing-side features
   - normalize units/flags

6. `scoring.py`
   - Tier logic (1/2/3) and similarity scoring (0-100)
   - recency multiplier
   - large-feature mismatch penalties

7. `valuation.py`
   - weighted PPSF (weight = score^2)
   - baseline value
   - v1 adjustments: waterfront, pool, impact glass, roof age, condo floor band
   - output point estimate + range

8. `context.py`
   - market-context calculation (60-day closed + pending + supply)
   - call shared metrics functions where practical

9. `reporting.py`
   - emit:
   - `output/cma/<subject_id>/valuation.json`
   - `output/cma/<subject_id>/top_comps.csv`
   - `output/cma/<subject_id>/context.json`

10. `runner.py`
    - orchestration for CLI/menu

---

## Candidate Pool Strategy (locked)

### Tier 1
- property type match
- same final_subdivision OR same development_name
- sold within 12 months
- sqft_living within +-25%

### Tier 2
- same geo_zone
- sold within 18 months
- sqft_living within +-35%

### Tier 3
- radius 0.5 to 1.0 miles
- sold within 24 months

Target: 30-150 candidates, score down to top 8-15.

---

## Similarity Scoring (v1)

Total score before recency modifier: 0-100

1. Base similarity (0-60)
- sqft match: 0-25
- bed match: 0-10
- bath match: 0-10
- year built match: 0-10
- lot match (SFH): 0-5

2. Location closeness (0-20)
- same final_subdivision/development: 20
- same geo_zone: 14
- within 0.5 mi: 8
- within 1.0 mi: 4

3. Feature match / penalties (0-20 net)
- waterfront match +6, mismatch -10
- pool match +3
- impact glass match +3
- garage match +2
- condo floor-band match +3
- amenity/security parity +3

4. Recency multiplier
- <=6 months: x1.00
- <=12 months: x0.95
- <=18 months: x0.90
- <=24 months: x0.85

---

## Valuation Output (v1)

1. `ppsf = sold_price / sqft_living` for each selected comp.
2. `weight = score^2`
3. `weighted_ppsf = sum(ppsf * weight) / sum(weight)`
4. `baseline_value = weighted_ppsf * subject_sqft`
5. Apply limited adjustments (v1):
   - waterfront
   - pool
   - impact glass
   - roof age
   - condo floor band

Return:
- point value
- low/high range
- confidence grade (`A/B/C`)
- comp table with per-feature score breakdown

---

## Confidence Rules (v1)

Base confidence from:

1. comp count:
- >=12 high support
- 8-11 medium
- <8 low

2. score quality:
- median top-10 score
- spread between top scores

3. recency quality:
- proportion sold in last 6 months

Output:
- `confidence_grade`: A/B/C
- `confidence_reason`: text explanation

---

## Data Contract (outputs)

### `valuation.json`
- subject summary
- valuation point/range
- confidence
- scoring formula version
- timestamp

### `top_comps.csv`
- comp id
- sold date / price / ppsf
- final score
- each component score
- key mismatch flags

### `context.json`
- last_60d_closed_count
- last_60d_median_price
- last_60d_median_ppsf
- pending_30d / pending_60d
- pending_to_sold_ratio
- active_inventory_snapshot
- months_supply

---

## Integration Plan

### Phase 1 (module only)
- Build module and CLI runner:
- `python3 -m cma_module.runner --parcel <PCN>`

### Phase 2 (menu integration)
- Add `main.py` option:
- `CMA Valuation (Parcel)`
- This runs module and writes report artifacts.

### Phase 3 (dashboard)
- Add CMA tab:
- subject input
- top comp table
- valuation range
- context panel (60-day closed + pending momentum)

---

## Immediate Next Build Steps

1. Create `cma_module/models.py`, `runner.py`, `scoring.py` skeletons.
2. Implement candidate pull from existing DB first (no extra scraping yet).
3. Add 60-day closed + pending context using shared stats functions.
4. Emit first `valuation.json` and `top_comps.csv`.
