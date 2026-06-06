#!/usr/bin/env python3
"""Build the local SQLite runtime DB from Supabase/Postgres.

Render does not receive the ignored local mls.db file from git. This script
hydrates mls.db from the managed Supabase table before FastAPI starts, allowing
the current SQLite-based API to run unchanged in production.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import psycopg


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "mls.db"


def _database_url() -> str:
    url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DATABASE_URL")
    if url:
        return url

    ref = os.getenv("SUPABASE_PROJECT_REF")
    password = os.getenv("SUPABASE_DB_PASSWORD")
    if ref and password:
        return f"postgresql://postgres:{quote(password, safe='')}@db.{ref}.supabase.co:5432/postgres?sslmode=require"

    raise RuntimeError(
        "Set DATABASE_URL, SUPABASE_DATABASE_URL, or SUPABASE_PROJECT_REF + SUPABASE_DB_PASSWORD."
    )


def _sqlite_type(pg_type: str) -> str:
    t = pg_type.lower()
    if "int" in t or t in {"smallserial", "serial", "bigserial"}:
        return "INTEGER"
    if t in {"numeric", "decimal", "real", "double precision"}:
        return "REAL"
    if "timestamp" in t or t == "date":
        return "TIMESTAMP"
    return "TEXT"


def _sqlite_value(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return value


def main() -> None:
    db_path = Path(os.getenv("RESTATS_DB_PATH", str(DEFAULT_DB_PATH))).resolve()
    force = os.getenv("RESTATS_REFRESH_FROM_SUPABASE", "1").lower() not in {"0", "false", "no"}
    if db_path.exists() and not force:
        print(f"SQLite DB already exists; skipping hydrate: {db_path}")
        return

    tmp_path = db_path.with_suffix(db_path.suffix + ".tmp")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    if tmp_path.exists():
        tmp_path.unlink()

    with psycopg.connect(_database_url(), connect_timeout=30) as pg_conn:
        with pg_conn.cursor() as pg_cur:
            pg_cur.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'listing_details'
                ORDER BY ordinal_position
                """
            )
            columns = pg_cur.fetchall()
            if not columns:
                raise RuntimeError("Supabase table public.listing_details was not found.")

            names = [name for name, _ in columns]
            quoted_columns = ", ".join(f'"{name}" {_sqlite_type(data_type)}' for name, data_type in columns)
            select_columns = ", ".join(f'"{name}"' for name in names)
            placeholders = ", ".join(["?"] * len(names))

            with sqlite3.connect(tmp_path) as sqlite_conn:
                sqlite_conn.execute(f"CREATE TABLE listing_details ({quoted_columns})")

                pg_cur.execute(f"SELECT {select_columns} FROM public.listing_details")
                total = 0
                while True:
                    rows = pg_cur.fetchmany(1000)
                    if not rows:
                        break
                    sqlite_conn.executemany(
                        f"INSERT INTO listing_details VALUES ({placeholders})",
                        ([ _sqlite_value(value) for value in row ] for row in rows),
                    )
                    total += len(rows)

                sqlite_conn.executescript(
                    """
                    CREATE INDEX IF NOT EXISTS idx_listing_details_listing_number ON listing_details(listing_number);
                    CREATE INDEX IF NOT EXISTS idx_listing_details_parcel_sold_date ON listing_details(parcel_id, sold_date);
                    CREATE INDEX IF NOT EXISTS idx_listing_details_pcn10_sold_date ON listing_details(pcn_10_digit, sold_date);
                    CREATE INDEX IF NOT EXISTS idx_listing_details_city ON listing_details(city);
                    CREATE INDEX IF NOT EXISTS idx_listing_details_status ON listing_details(status);
                    CREATE INDEX IF NOT EXISTS idx_listing_details_sold_date ON listing_details(sold_date);
                    CREATE INDEX IF NOT EXISTS idx_listing_details_effective_active_end_date ON listing_details(effective_active_end_date);
                    """
                )
                sqlite_conn.commit()

    tmp_path.replace(db_path)
    print(f"Hydrated SQLite DB from Supabase: {db_path} rows={total}")


if __name__ == "__main__":
    main()
