# Open-source positioning

ReStats is an open-source real estate data-quality and market-intelligence toolkit. It is designed for smaller real estate operators, analysts, and technically inclined agents who need repeatable workflows for messy MLS-style CSV exports, county-record imports, local market reporting, and CMA support.

## Why this project exists

Local property data is fragmented. Smaller teams often rely on spreadsheets, one-off scripts, manual cleanup, and brittle dashboards. ReStats turns those workflows into a maintainable pipeline:

- Ingest MLS-style CSV exports.
- Normalize dates, statuses, property types, subdivisions, and geo zones.
- Merge county/off-market sales into a common schema.
- Detect duplicate sales and auxiliary-unit/cabana records.
- Generate market metrics across monthly, quarterly, annual, rolling, and custom periods.
- Serve analytics through Streamlit, FastAPI, and an emerging React dashboard.
- Support CMA workflows through parcel lookup and comp analysis.

## What is intentionally excluded

The public repository should not include private MLS exports, client data, credentials, production SQLite databases, or personally identifying records.

Public examples should use synthetic or public-domain data. Real-data bugs should be reduced to anonymized fixtures before being committed.

## Good use cases for Codex/API credits

Codex would be useful for ongoing maintenance work such as:

- Regression-test generation for CSV ingestion and normalization.
- PR review for field-mapping, schema, and API changes.
- Refactoring importer code into reusable adapters.
- Security review around credentials, `.env` handling, and generated artifacts.
- Documentation updates and contributor onboarding.
- Parity checks between legacy dashboard logic and API responses.
- Safer synthetic test data generation for MLS-style edge cases.

## Maintainer notes

This is a practical working project built from real brokerage data problems, but the open-source goal is broader: make real estate data cleanup, reporting, and analytics workflows more transparent and reusable for small teams that do not have enterprise data infrastructure.
