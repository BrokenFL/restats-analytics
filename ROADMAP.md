# ReStats Roadmap

ReStats is moving from a working local analytics engine toward a more reusable open-source toolkit for real estate data quality, MLS-style CSV ingestion, county-record enrichment, market reporting, and CMA support.

## Near term

- Add synthetic MLS-style fixture data for parser and import tests.
- Add CI checks for CSV ingestion, normalization, duplicate detection, and API startup.
- Refactor raw field mapping into reusable adapter modules.
- Improve documentation for first-time setup without private MLS exports.
- Add safer examples for `.env`, local SQLite, and Supabase sync configuration.
- Expand regression coverage for `buyer_financing`, cash-sale detection, and changed MLS export field names.

## Data quality and normalization

- Harden date parsing across sold, pending, active, withdrawn, expired, and cancelled statuses.
- Improve duplicate sale detection across MLS and county-record imports.
- Expand cabana/auxiliary-unit merge detection with clearer audit output.
- Add stronger validation around subdivision aliases, PCN matching, and geo-zone tagging.
- Build a repeatable import audit report that summarizes row counts, skipped records, warnings, and schema mismatches.

## API and dashboard

- Bring FastAPI endpoint behavior into parity with the legacy Streamlit dashboard.
- Add endpoint-level tests for KPI summaries, trends, inventory, filters, and CMA responses.
- Improve `/api/ops/status` and parity-check reporting for production monitoring.
- Continue React dashboard migration while preserving print/report workflows.
- Add safer fallbacks when optional datasets or lookup files are unavailable.

## CMA module

- Improve comp selection explainability.
- Add tests for parcel lookup, comp filtering, adjustment math, and edge cases.
- Document assumptions and limitations for market-facing CMA use.
- Add synthetic examples that demonstrate CMA behavior without exposing private or client data.

## Open-source readiness

- Create a small public sample dataset using synthetic MLS-style rows.
- Add issue templates for bugs, data-fixture requests, and field-mapping changes.
- Publish an initial `v0.1.0` release once docs, license, and sample data are stable.
- Improve contributor onboarding so outside users can run the core pipeline without private brokerage infrastructure.

## Long-term ideas

- Support multiple MLS/export schemas through adapter configuration.
- Add pluggable county-record importers.
- Add a lightweight package interface for teams that only need parsing/normalization.
- Add richer report templates for monthly, quarterly, and annual local-market reviews.
- Explore anonymized benchmark fixtures for regression testing across local-market edge cases.
