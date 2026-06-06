#!/usr/bin/env python3
"""Sync local SQLite mls.db listing_details up to Supabase public.listing_details.

Usage:
    python scripts/ops/sync_sqlite_to_supabase.py

Reads the same env credentials as api/main.py:
  - RESTATS_DATABASE_URL or DATABASE_URL (full connection string)
  - SUPABASE_PROJECT_REF + SUPABASE_DB_PASSWORD
  - SUPABASE_DB_HOST + SUPABASE_DB_PORT + SUPABASE_DB_NAME + SUPABASE_DB_USER + SUPABASE_DB_PASSWORD
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

import psycopg


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "mls.db"


def _database_url() -> str:
    url = os.getenv("RESTATS_DATABASE_URL") or os.getenv("DATABASE_URL")
    if url:
        return url

    ref = os.getenv("SUPABASE_PROJECT_REF")
    password = os.getenv("SUPABASE_DB_PASSWORD")
    if ref and password:
        return (
            f"postgresql://postgres:{quote(password, safe='')}"
            f"@db.{ref}.supabase.co:5432/postgres?sslmode=require"
        )

    host = os.getenv("SUPABASE_DB_HOST")
    port = os.getenv("SUPABASE_DB_PORT", "5432")
    dbname = os.getenv("SUPABASE_DB_NAME", "postgres")
    user = os.getenv("SUPABASE_DB_USER", "postgres")
    password = os.getenv("SUPABASE_DB_PASSWORD")
    if host and password:
        return (
            f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
            f"@{host}:{port}/{dbname}?sslmode=require"
        )

    raise RuntimeError(
        "No Postgres credentials found. Set one of:\n"
        "  RESTATS_DATABASE_URL\n"
        "  DATABASE_URL\n"
        "  SUPABASE_PROJECT_REF + SUPABASE_DB_PASSWORD\n"
        "  SUPABASE_DB_HOST + SUPABASE_DB_PASSWORD"
    )


def _ensure_column(pg_conn, column_name: str, data_type: str = "TEXT") -> None:
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'listing_details'
              AND column_name = %s
            """,
            (column_name,),
        )
        if not cur.fetchone():
            cur.execute(
                f'ALTER TABLE public.listing_details ADD COLUMN "{column_name}" {data_type}'
            )
            pg_conn.commit()
            print(f"Added column {column_name} ({data_type}) to public.listing_details.")


def _pg_type_map(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'listing_details'
            """
        )
        return {row[0]: row[1].lower() for row in cur.fetchall()}


def _convert_row(row, col_names, pg_types):
    out = []
    for val, col in zip(row, col_names):
        pg_type = pg_types.get(col, "")
        if val is None:
            out.append(None)
            continue
        if "boolean" in pg_type and isinstance(val, int):
            out.append(bool(val))
        else:
            out.append(val)
    return tuple(out)


def main() -> int:
    db_path = Path(os.getenv("RESTATS_DB", str(DEFAULT_DB_PATH))).resolve()
    if not db_path.exists():
        print(f"ERROR: SQLite DB not found: {db_path}", file=sys.stderr)
        return 1

    pg_url = _database_url()

    # Read SQLite columns dynamically
    with sqlite3.connect(db_path) as sqlite_conn:
        cols = [
            row[1] for row in sqlite_conn.execute("PRAGMA table_info(listing_details)").fetchall()
        ]
    if not cols:
        print("ERROR: listing_details table has no columns.", file=sys.stderr)
        return 1

    # Ensure buyer_financing exists in Postgres
    with psycopg.connect(pg_url) as pg_conn:
        _ensure_column(pg_conn, "buyer_financing", "TEXT")
        pg_types = _pg_type_map(pg_conn)

    quoted_cols = [f'"{c}"' for c in cols]
    placeholders = ", ".join(["%s"] * len(cols))
    updates = ", ".join([f'"{c}" = EXCLUDED."{c}"' for c in cols if c != "listing_number"])

    upsert_sql = f"""
    INSERT INTO public.listing_details ({', '.join(quoted_cols)})
    VALUES ({placeholders})
    ON CONFLICT (listing_number) DO UPDATE SET {updates}
    """

    total = 0
    batch_size = 2000

    with sqlite3.connect(db_path) as sqlite_conn:
        cursor = sqlite_conn.execute(f"SELECT {', '.join(cols)} FROM listing_details")

        with psycopg.connect(pg_url) as pg_conn:
            with pg_conn.cursor() as pg_cur:
                batch = []
                for row in cursor:
                    batch.append(_convert_row(row, cols, pg_types))
                    if len(batch) >= batch_size:
                        pg_cur.executemany(upsert_sql, batch)
                        pg_conn.commit()
                        total += len(batch)
                        print(f"Upserted {total} rows...")
                        batch = []

                if batch:
                    pg_cur.executemany(upsert_sql, batch)
                    pg_conn.commit()
                    total += len(batch)
                    print(f"Upserted {total} rows...")

    print(f"Sync complete. Total rows upserted: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
