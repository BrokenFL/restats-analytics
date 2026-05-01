# Scripts Layout

Operational scripts are organized by purpose:

- `scripts/audits/`: read-only quality/duplicate audits and reports
- `scripts/maintenance/`: cleanup, migrations, and one-time fixups
- `scripts/ops/`: operational diagnostics and parity checks

Root-level script filenames are kept as thin wrappers for backward compatibility.
Prefer using the `scripts/...` paths for new automation.
