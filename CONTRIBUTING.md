# Contributing to ReStats

Thanks for your interest in ReStats. This project is built around a real-world problem: turning messy real estate exports, county records, and local market data into reliable analytics workflows that smaller teams can actually use.

## Good first contributions

Useful contributions include:

- Synthetic MLS-style fixture data for tests.
- Parser and field-mapping improvements.
- Documentation fixes and setup notes.
- Regression tests for CSV ingestion and normalization.
- FastAPI endpoint cleanup and parity checks.
- Dashboard/reporting improvements that do not require private MLS data.

## Data and privacy rules

Do not commit private MLS exports, client information, credentials, production databases, or personally identifying records.

Use synthetic or public-domain sample data whenever possible. If you are reproducing a bug from a real export, reduce it to the smallest anonymized fixture that demonstrates the issue.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the Streamlit app:

```bash
streamlit run app.py
```

Run the FastAPI service:

```bash
uvicorn api.main:app --reload --port 8000
```

## Pull request checklist

Before opening a PR:

- Keep generated files, raw CSVs, databases, logs, and credentials out of git.
- Add or update tests when touching parsing, normalization, duplicate detection, or API behavior.
- Update README or docs when behavior changes.
- Prefer small, reviewable changes over giant mystery meat PRs.
- Explain whether your change affects MLS ingestion, county-record imports, dashboard metrics, CMA logic, or API responses.

## Issue reports

Useful bug reports include:

- The command or endpoint you ran.
- The expected behavior.
- The actual behavior.
- A small synthetic/anonymized fixture if the issue depends on input data.
- Environment details such as Python version, OS, and database target.

## Project direction

The goal is to keep ReStats practical, auditable, and reusable for local-market real estate analytics. Contributions should improve reliability, transparency, portability, or documentation without requiring access to private MLS systems.
