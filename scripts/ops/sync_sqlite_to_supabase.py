#!/usr/bin/env python3
"""Sync local SQLite mls.db listing_details up to Supabase public.listing_details.

Default behavior keeps the cloud table aligned with local SQLite:
- upsert all valid local rows keyed by listing_number
- delete cloud rows with missing listing_number
- delete cloud rows whose listing_number is no longer present locally

Usage:
    python scripts/ops/sync_sqlite_to_supabase.py
    python scripts/ops/sync_sqlite_to_supabase.py --keep-cloud-only
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

import psycopg


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "mls.db"
ENV_CANDIDATE_FILES = (
    ".env",
    ".env.local",
    "~/.codex/mls.env",
    "~/.codex/mls.env.local",
    "~/.config/openclaw/secrets/mls.env",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync local SQLite listing_details to Supabase.")
    parser.add_argument(
        "--db-path",
        default=os.getenv("RESTATS_DB", str(DEFAULT_DB_PATH)),
        help="Path to the local SQLite database.",
    )
    parser.add_argument(
        "--keep-cloud-only",
        action="store_true",
        help="Do not delete cloud rows that are missing locally.",
    )
    parser.add_argument(
        "--delete-invalid-local",
        action="store_true",
        help="Delete local rows with blank listing_number before syncing.",
    )
    return parser.parse_args()


def _load_local_env_defaults() -> None:
    for rel_path in ENV_CANDIDATE_FILES:
        env_path = Path(rel_path).expanduser()
        if not env_path.exists():
            continue
        try:
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except Exception:
            continue


def _database_url() -> str:
    # Prefer the configured Supabase pooler over a direct database URL. The
    # direct endpoint can resolve to an unreachable IPv6 address from the
    # unattended refresh host, while the pooler is the connection path used
    # by the deployed API.
    pooler_host = (os.getenv("SUPABASE_DB_HOST") or "").strip()
    pooler_password = os.getenv("SUPABASE_DB_PASSWORD")
    if pooler_host and "pooler" in pooler_host.lower() and pooler_password:
        pooler_port = os.getenv("SUPABASE_DB_PORT", "5432")
        pooler_name = os.getenv("SUPABASE_DB_NAME", "postgres")
        pooler_user = os.getenv("SUPABASE_DB_USER", "postgres")
        return (
            f"postgresql://{quote(pooler_user, safe='')}:{quote(pooler_password, safe='')}"
            f"@{pooler_host}:{pooler_port}/{pooler_name}"
            "?sslmode=require&connect_timeout=20"
        )

    url = os.getenv("RESTATS_DATABASE_URL") or os.getenv("DATABASE_URL")
    if url:
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}connect_timeout=20"

    ref = os.getenv("SUPABASE_PROJECT_REF")
    password = os.getenv("SUPABASE_DB_PASSWORD")
    if ref and password:
        return (
            f"postgresql://postgres:{quote(password, safe='')}"
            f"@db.{ref}.supabase.co:5432/postgres?sslmode=require&connect_timeout=20"
        )

    host = os.getenv("SUPABASE_DB_HOST")
    port = os.getenv("SUPABASE_DB_PORT", "5432")
    dbname = os.getenv("SUPABASE_DB_NAME", "postgres")
    user = os.getenv("SUPABASE_DB_USER", "postgres")
    password = os.getenv("SUPABASE_DB_PASSWORD")
    if host and password:
        return (
            f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
            f"@{host}:{port}/{dbname}?sslmode=require&connect_timeout=20"
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


def _ensure_unique_index(pg_conn) -> None:
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_listing_details_listing_number_unique
            ON public.listing_details (listing_number)
            """
        )
    pg_conn.commit()


def _ensure_read_indexes(pg_conn) -> None:
    statements = [
        "CREATE INDEX IF NOT EXISTS idx_listing_details_sold_date ON public.listing_details (sold_date)",
        "CREATE INDEX IF NOT EXISTS idx_listing_details_listing_date ON public.listing_details (listing_date)",
        "CREATE INDEX IF NOT EXISTS idx_listing_details_under_contract_date ON public.listing_details (under_contract_date)",
        "CREATE INDEX IF NOT EXISTS idx_listing_details_effective_active_end_date ON public.listing_details (effective_active_end_date)",
        "CREATE INDEX IF NOT EXISTS idx_listing_details_city ON public.listing_details (city)",
        "CREATE INDEX IF NOT EXISTS idx_listing_details_geo_zone ON public.listing_details (geo_zone)",
        "CREATE INDEX IF NOT EXISTS idx_listing_details_final_subdivision ON public.listing_details (final_subdivision)",
        "CREATE INDEX IF NOT EXISTS idx_listing_details_status ON public.listing_details (status)",
        "CREATE INDEX IF NOT EXISTS idx_listing_details_parcel_sold_date ON public.listing_details (parcel_id, sold_date)",
        "CREATE INDEX IF NOT EXISTS idx_listing_details_pcn10_sold_date ON public.listing_details (pcn_10_digit, sold_date)",
    ]
    with pg_conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)
    pg_conn.commit()


def _pg_type_map(pg_conn) -> dict[str, str]:
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


def _delete_invalid_local_rows(sqlite_conn: sqlite3.Connection) -> int:
    cur = sqlite_conn.execute(
        "DELETE FROM listing_details WHERE listing_number IS NULL OR TRIM(listing_number) = ''"
    )
    sqlite_conn.commit()
    return cur.rowcount or 0


def _sqlite_stats(sqlite_conn: sqlite3.Connection) -> tuple[int, int]:
    total, invalid = sqlite_conn.execute(
        """
        SELECT
            COUNT(*),
            SUM(CASE WHEN listing_number IS NULL OR TRIM(listing_number) = '' THEN 1 ELSE 0 END)
        FROM listing_details
        """
    ).fetchone()
    return int(total or 0), int(invalid or 0)


def _pg_valid_count(pg_conn) -> int:
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM public.listing_details
            WHERE listing_number IS NOT NULL AND btrim(listing_number) <> ''
            """
        )
        return int(cur.fetchone()[0] or 0)


def _prune_cloud_rows(pg_conn, sqlite_conn: sqlite3.Connection) -> int:
    with pg_conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS temp_sync_listing_numbers")
        cur.execute(
            """
            CREATE TEMP TABLE temp_sync_listing_numbers (
                listing_number TEXT PRIMARY KEY
            ) ON COMMIT DROP
            """
        )

        batch = []
        inserted = 0
        key_cursor = sqlite_conn.execute(
            """
            SELECT listing_number
            FROM listing_details
            WHERE listing_number IS NOT NULL AND TRIM(listing_number) <> ''
            """
        )
        for (listing_number,) in key_cursor:
            batch.append((listing_number,))
            if len(batch) >= 5000:
                cur.executemany(
                    "INSERT INTO temp_sync_listing_numbers (listing_number) VALUES (%s)",
                    batch,
                )
                inserted += len(batch)
                batch = []
        if batch:
            cur.executemany(
                "INSERT INTO temp_sync_listing_numbers (listing_number) VALUES (%s)",
                batch,
            )
            inserted += len(batch)

        cur.execute(
            """
            DELETE FROM public.listing_details d
            WHERE d.listing_number IS NULL
               OR btrim(d.listing_number) = ''
               OR NOT EXISTS (
                    SELECT 1
                    FROM temp_sync_listing_numbers t
                    WHERE t.listing_number = d.listing_number
               )
            """
        )
        deleted = cur.rowcount or 0

    pg_conn.commit()
    print(f"Loaded {inserted} sync keys into temporary cloud staging table.")
    return deleted


def main() -> int:
    args = parse_args()
    _load_local_env_defaults()

    db_path = Path(args.db_path).expanduser().resolve()
    if not db_path.exists():
        print(f"ERROR: SQLite DB not found: {db_path}", file=sys.stderr)
        return 1

    pg_url = _database_url()

    with sqlite3.connect(db_path) as sqlite_conn:
        total_before, invalid_before = _sqlite_stats(sqlite_conn)
        print(f"Local rows before cleanup: {total_before} total, {invalid_before} invalid.")

        local_deleted = 0
        if args.delete_invalid_local and invalid_before:
            local_deleted = _delete_invalid_local_rows(sqlite_conn)
            total_after_local_cleanup, invalid_after_cleanup = _sqlite_stats(sqlite_conn)
            print(
                f"Deleted {local_deleted} invalid local rows."
                f" Local rows now: {total_after_local_cleanup} total, {invalid_after_cleanup} invalid."
            )

        cols = [
            row[1] for row in sqlite_conn.execute("PRAGMA table_info(listing_details)").fetchall()
        ]
        if not cols:
            print("ERROR: listing_details table has no columns.", file=sys.stderr)
            return 1

        with psycopg.connect(pg_url) as pg_conn:
            _ensure_column(pg_conn, "buyer_financing", "TEXT")
            _ensure_unique_index(pg_conn)
            _ensure_read_indexes(pg_conn)
            pg_types = _pg_type_map(pg_conn)

            quoted_cols = [f'"{c}"' for c in cols]
            placeholders = ", ".join(["%s"] * len(cols))
            updates = ", ".join([f'"{c}" = EXCLUDED."{c}"' for c in cols if c != "listing_number"])
            upsert_sql = f"""
            INSERT INTO public.listing_details ({', '.join(quoted_cols)})
            VALUES ({placeholders})
            ON CONFLICT (listing_number) DO UPDATE SET {updates}
            """

            total_upserted = 0
            batch_size = 2000
            batch = []
            cursor = sqlite_conn.execute(
                f"""
                SELECT {', '.join(cols)}
                FROM listing_details
                WHERE listing_number IS NOT NULL AND TRIM(listing_number) <> ''
                """
            )
            with pg_conn.cursor() as pg_cur:
                for row in cursor:
                    batch.append(_convert_row(row, cols, pg_types))
                    if len(batch) >= batch_size:
                        pg_cur.executemany(upsert_sql, batch)
                        pg_conn.commit()
                        total_upserted += len(batch)
                        print(f"Upserted {total_upserted} rows...")
                        batch = []

                if batch:
                    pg_cur.executemany(upsert_sql, batch)
                    pg_conn.commit()
                    total_upserted += len(batch)
                    print(f"Upserted {total_upserted} rows...")

            deleted_cloud_rows = 0
            if args.keep_cloud_only:
                with pg_conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM public.listing_details
                        WHERE listing_number IS NULL OR btrim(listing_number) = ''
                        """
                    )
                    deleted_cloud_rows = cur.rowcount or 0
                pg_conn.commit()
                if deleted_cloud_rows:
                    print(f"Deleted {deleted_cloud_rows} invalid cloud rows.")
            else:
                deleted_cloud_rows = _prune_cloud_rows(pg_conn, sqlite_conn)
                print(f"Deleted {deleted_cloud_rows} cloud rows not present locally.")

            local_valid_count = int(
                sqlite_conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM listing_details
                    WHERE listing_number IS NOT NULL AND TRIM(listing_number) <> ''
                    """
                ).fetchone()[0]
                or 0
            )
            cloud_valid_count = _pg_valid_count(pg_conn)

    print(
        "Sync complete."
        f" Upserted valid rows: {total_upserted}."
        f" Local invalid rows deleted: {local_deleted}."
        f" Cloud rows deleted: {deleted_cloud_rows}."
        f" Local valid rows: {local_valid_count}."
        f" Cloud valid rows: {cloud_valid_count}."
    )
    if local_valid_count != cloud_valid_count:
        print(
            "ERROR: valid row counts still differ after sync.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
