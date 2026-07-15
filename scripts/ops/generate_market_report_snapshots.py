#!/usr/bin/env python3
"""Generate durable monthly market-report snapshots in Supabase.

The job is intentionally idempotent.  By default it targets the most recently
completed month and exits quickly when every city/market snapshot already
exists.  Use --force to rebuild the target month after a corrected data load.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _previous_month(today: date | None = None) -> tuple[int, int]:
    current = today or date.today()
    first_of_current = current.replace(day=1)
    previous_day = first_of_current - timedelta(days=1)
    return previous_day.year, previous_day.month


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def parse_args() -> argparse.Namespace:
    default_year, default_month = _previous_month()
    parser = argparse.ArgumentParser(description="Generate monthly ReStats market snapshots in Supabase.")
    parser.add_argument("--year", type=int, default=default_year)
    parser.add_argument("--month", type=int, choices=range(1, 13), default=default_month)
    parser.add_argument("--force", action="store_true", help="Rebuild snapshots even when they already exist.")
    parser.add_argument("--if-missing", action="store_true", help="Exit without work when the target month is already complete.")
    parser.add_argument(
        "--all-existing",
        action="store_true",
        help="Rebuild every month already present in the snapshot table, plus the target month.",
    )
    return parser.parse_args()


def _load_database_url() -> str:
    from scripts.ops.sync_sqlite_to_supabase import _database_url, _load_local_env_defaults

    _load_local_env_defaults()
    return _database_url()


def _ensure_snapshot_table(pg_conn) -> None:
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.market_report_snapshots (
                snapshot_key TEXT PRIMARY KEY,
                report_mode TEXT NOT NULL,
                period_start DATE NOT NULL,
                period_end DATE NOT NULL,
                scope_key TEXT NOT NULL,
                city TEXT,
                property_group TEXT NOT NULL,
                payload JSONB NOT NULL,
                source_record_count INTEGER NOT NULL DEFAULT 0,
                generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_market_report_snapshots_identity
            ON public.market_report_snapshots (
                report_mode, period_start, period_end, scope_key, property_group
            )
            """
        )
    pg_conn.commit()


def _snapshot_key(period_start: str, period_end: str, scope_key: str, property_group: str) -> str:
    return "|".join(("monthly", period_start, period_end, scope_key, property_group))


def _existing_keys(pg_conn, period_start: str, period_end: str) -> set[tuple[str, str]]:
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT scope_key, property_group
            FROM public.market_report_snapshots
            WHERE report_mode = 'monthly'
              AND period_start = %s
              AND period_end = %s
            """,
            (period_start, period_end),
        )
        return {
            (
                str(row["scope_key"] if isinstance(row, dict) else row[0]),
                str(row["property_group"] if isinstance(row, dict) else row[1]),
            )
            for row in cur.fetchall()
        }


def _source_record_count(pg_conn) -> int:
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM public.listing_details
            WHERE listing_number IS NOT NULL AND btrim(listing_number) <> ''
            """
        )
        row = cur.fetchone()
        value = row["count"] if isinstance(row, dict) else row[0]
        return int(value or 0)


def _existing_months(pg_conn) -> set[tuple[int, int]]:
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT period_start
            FROM public.market_report_snapshots
            WHERE report_mode = 'monthly'
            ORDER BY period_start
            """
        )
        months = set()
        for row in cur.fetchall():
            value = row["period_start"] if isinstance(row, dict) else row[0]
            if isinstance(value, str):
                value = date.fromisoformat(value)
            months.add((value.year, value.month))
        return months


def _cities(api_module) -> list[str]:
    with api_module.closing(api_module.get_connection()) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT DISTINCT city
                FROM listing_details
                WHERE city IS NOT NULL AND TRIM(city) <> ''
                ORDER BY city
                """
            )
            values = [api_module.canonical_city_name(row.get("city")) for row in cursor.fetchall()]
        finally:
            cursor.close()
    return sorted({value for value in values if value})


def _build_payload(api_module, city: str | None, property_group: str, year: int, month: int, start_iso: str, end_iso: str) -> dict:
    report_summary = api_module.market_report_summary(
        "monthly", 30, year, month, None, None, None, city, None, None, None, property_group
    )
    period_series = api_module.market_period_series(
        "monthly", 12, None, None, None, None, city, None, None, None, property_group
    )
    rankings = api_module.subdivision_rankings(
        "monthly", 30, year, month, None, None, None, 2, 10, city, None, None, property_group
    )
    recent_listings = api_module.recent_listings(
        25, city, None, None, None, property_group, None, start_iso, end_iso
    )
    return {
        "report_summary": report_summary,
        "period_series": period_series,
        "rankings": rankings,
        "recent_listings": recent_listings,
    }


class _ReusableApiConnection:
    """Keep the snapshot batch on one read connection instead of opening 80."""

    def __init__(self, api_module) -> None:
        self._inner = api_module._PostgresConnection()

    def cursor(self):
        return self._inner.cursor()

    def execute(self, sql, params=None):
        return self._inner.execute(sql, params)

    def commit(self):
        return self._inner.commit()

    def rollback(self):
        return self._inner.rollback()

    @property
    def raw_connection(self):
        return self._inner._conn

    def close(self):
        # API helpers use contextlib.closing; reset the read transaction while
        # keeping the underlying connection available for the next helper.
        self._inner.rollback()

    def shutdown(self) -> None:
        self._inner.close()


def main() -> int:
    args = parse_args()
    database_url = _load_database_url()
    os.environ["RESTATS_DATABASE_URL"] = database_url

    # Force the generator to calculate fresh values rather than reading the
    # row it is about to replace from the API snapshot table.
    os.environ["RESTATS_DISABLE_SNAPSHOT_READ"] = "1"
    import api.main as api_module  # noqa: E402

    api_connection = _ReusableApiConnection(api_module)
    api_module.get_connection = lambda: api_connection
    try:
        pg_conn = api_connection.raw_connection
        _ensure_snapshot_table(pg_conn)
        source_count = _source_record_count(pg_conn)
        cities = _cities(api_module)
        scopes = [(None, "__ALL_MARKETS__")] + [(city, city) for city in cities]
        groups = ["ALL", "SINGLE_FAMILY", "TOWNHOME_CONDO"]
        required = {(scope_key, group) for _, scope_key in scopes for group in groups}
        months = {(args.year, args.month)}
        if args.all_existing:
            months.update(_existing_months(pg_conn))

        generated = 0
        for year, month in sorted(months):
            period_start, period_end = _month_bounds(year, month)
            existing = _existing_keys(pg_conn, period_start, period_end)
            if args.if_missing and not args.force and required.issubset(existing):
                print(f"Monthly snapshots already complete for {period_start} to {period_end}; nothing to do.")
                continue

            pending_writes = []
            for city, scope_key in scopes:
                for property_group in groups:
                    identity = (scope_key, property_group)
                    if identity in existing and not args.force:
                        continue
                    print(
                        f"Generating snapshot: {scope_key} | {property_group} | {period_start} to {period_end}",
                        flush=True,
                    )
                    payload = _build_payload(
                        api_module,
                        city,
                        property_group,
                        year,
                        month,
                        period_start,
                        period_end,
                    )
                    pending_writes.append(
                        (
                            _snapshot_key(period_start, period_end, scope_key, property_group),
                            scope_key,
                            city,
                            property_group,
                            Jsonb(json.loads(json.dumps(payload, default=str, allow_nan=False))),
                        )
                    )
            for key, scope_key, city, property_group, payload in pending_writes:
                with pg_conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO public.market_report_snapshots (
                            snapshot_key, report_mode, period_start, period_end,
                            scope_key, city, property_group, payload, source_record_count, generated_at
                        )
                        VALUES (%s, 'monthly', %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (snapshot_key) DO UPDATE SET
                            payload = EXCLUDED.payload,
                            source_record_count = EXCLUDED.source_record_count,
                            generated_at = EXCLUDED.generated_at,
                            period_start = EXCLUDED.period_start,
                            period_end = EXCLUDED.period_end,
                            scope_key = EXCLUDED.scope_key,
                            city = EXCLUDED.city,
                            property_group = EXCLUDED.property_group
                        """,
                        (
                            key,
                            period_start,
                            period_end,
                            scope_key,
                            city,
                            property_group,
                            payload,
                            source_count,
                        ),
                    )
                generated += 1
            pg_conn.commit()
    finally:
        api_connection.shutdown()

    print(f"Generated monthly snapshots: {generated}; source listing rows: {source_count}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
