import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Optional, Literal
import calendar
import json
import socket
from dataclasses import asdict

import pandas as pd
import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import data_analysis_functions as daf
from cabana_utils import likely_cabana_mask
from cma_module.db import (
    build_pending_pressure_guardrail,
    get_subject_by_parcel,
    pull_candidate_sales,
    pull_market_activity,
    pull_pending_projection,
    pull_surrounding_discount_metrics,
)
from cma_module.expansion import resolve_market_scope
from cma_module.insights import build_closing_trends, build_community_insights
from cma_module.scoring import build_candidate_pool, confidence_grade, score_candidates
from cma_module.valuation import value_from_comps


def _single_family_property_type_clause(column_name: str = "property_type") -> str:
    normalized = f"UPPER(TRIM(COALESCE({column_name}, '')))"
    return (
        f"({normalized} IN ('SF','SFH','SINGLE FAMILY','SINGLE-FAMILY','SINGLE FAMILY HOME','SINGLE FAMILY RESIDENCE') "
        f"OR {normalized} LIKE 'SINGLE FAMILY%')"
    )


def _default_db_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(here)
    return os.path.join(project_root, "mls.db")


def _ops_project_root() -> str:
    env_root = os.getenv("RESTATS_OPS_ROOT")
    if env_root:
        return env_root
    return os.path.dirname(os.path.realpath(DB_PATH))


DB_PATH = os.getenv("RESTATS_DB_PATH", _default_db_path())
DATABASE_URL = os.getenv("RESTATS_DATABASE_URL") or os.getenv("DATABASE_URL")
SUPABASE_PROJECT_REF = os.getenv("SUPABASE_PROJECT_REF")
SUPABASE_DB_PASSWORD = os.getenv("SUPABASE_DB_PASSWORD")
SUPABASE_DB_HOST = os.getenv("SUPABASE_DB_HOST")
SUPABASE_DB_PORT = int(os.getenv("SUPABASE_DB_PORT", "5432"))
SUPABASE_DB_NAME = os.getenv("SUPABASE_DB_NAME", "postgres")
SUPABASE_DB_USER = os.getenv("SUPABASE_DB_USER")
USE_POSTGRES = bool(DATABASE_URL or (SUPABASE_DB_PASSWORD and (SUPABASE_DB_HOST or SUPABASE_PROJECT_REF)))

app = FastAPI(
    title="ReStats API",
    version="0.1.0",
    description="Read API for ReStats dashboard metrics.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class KpiSummaryResponse(BaseModel):
    total_records: Optional[int] = None
    closed_count: Optional[int] = None
    active_count: Optional[int] = None
    active_inventory_current: Optional[int] = None
    active_inventory_snapshot: Optional[int] = None
    active_inventory_snapshot_date: Optional[str] = None
    avg_sold_price: Optional[float] = None
    avg_list_price: Optional[float] = None
    avg_sp_lp_ratio: Optional[float] = None


class ReportPeriodMetricsResponse(BaseModel):
    sold_count: Optional[float] = None
    total_sales_volume: Optional[float] = None
    median_sold_price: Optional[float] = None
    avg_sold_price: Optional[float] = None
    median_price_per_sqft: Optional[float] = None
    avg_list_price: Optional[float] = None
    avg_sp_lp: Optional[float] = None
    new_listings: Optional[float] = None
    pending_sales: Optional[float] = None
    pending_inventory: Optional[float] = None
    active_inventory: Optional[float] = None
    months_supply: Optional[float] = None
    median_dom: Optional[float] = None
    median_listing_discount: Optional[float] = None
    cash_sales_percent: Optional[float] = None


class ReportSummaryResponse(BaseModel):
    report_mode: Literal["rolling", "monthly", "quarterly", "annual", "custom"]
    period_days: int
    period_label: str
    current_start: str
    current_end: str
    previous_start: str
    previous_end: str
    current: ReportPeriodMetricsResponse
    previous: ReportPeriodMetricsResponse
    delta_pct: ReportPeriodMetricsResponse


class PeriodSeriesRowResponse(BaseModel):
    period: str
    start_date: str
    end_date: str
    sold_count: Optional[float] = None
    total_sales_volume: Optional[float] = None
    median_sold_price: Optional[float] = None
    avg_sold_price: Optional[float] = None
    median_price_per_sqft: Optional[float] = None
    avg_list_price: Optional[float] = None
    avg_sp_lp: Optional[float] = None
    new_listings: Optional[float] = None
    pending_sales: Optional[float] = None
    pending_inventory: Optional[float] = None
    active_inventory: Optional[float] = None
    months_supply: Optional[float] = None
    median_dom: Optional[float] = None
    median_listing_discount: Optional[float] = None
    cash_sales_percent: Optional[float] = None


class PeriodSeriesResponse(BaseModel):
    frequency: Literal["monthly", "quarterly", "annual"]
    periods: int
    rows: list[PeriodSeriesRowResponse]


class ReportListingRowResponse(BaseModel):
    listing_number: Optional[str] = None
    parcel_id: Optional[str] = None
    short_address: Optional[str] = None
    city: Optional[str] = None
    geo_zone: Optional[str] = None
    final_subdivision: Optional[str] = None
    property_type: Optional[str] = None
    status: Optional[str] = None
    unit_number: Optional[str] = None
    listing_date: Optional[str] = None
    under_contract_date: Optional[str] = None
    sold_date: Optional[str] = None
    effective_active_end_date: Optional[str] = None
    list_price: Optional[float] = None
    original_list_price: Optional[float] = None
    sold_price: Optional[float] = None
    sold_ppsf: Optional[float] = None
    sp_lp_ratio: Optional[float] = None
    total_bedrooms: Optional[float] = None
    baths_total: Optional[float] = None
    sqft_living: Optional[float] = None
    geo_lat: Optional[float] = None
    geo_lon: Optional[float] = None
    terms_of_sale: Optional[str] = None
    buyer_financing: Optional[str] = None
    cabana_flag: bool = False
    new_listing_in_period: bool
    pending_in_period: bool
    sold_in_period: bool
    active_at_period_end: bool
    pending_at_period_end: bool


class ReportListingsResponse(BaseModel):
    report_mode: Literal["rolling", "monthly", "quarterly", "annual", "custom"]
    period_label: str
    current_start: str
    current_end: str
    row_count: int
    rows: list[ReportListingRowResponse]


class ParityMetricRowResponse(BaseModel):
    metric: str
    legacy_value: Optional[float] = None
    api_value: Optional[float] = None
    delta: Optional[float] = None
    delta_pct: Optional[float] = None
    in_tolerance: bool


class ParityResponse(BaseModel):
    mode: Literal["monthly", "quarterly", "annual"]
    current_start: str
    current_end: str
    tolerance_pct: float
    metrics: list[ParityMetricRowResponse]
    mismatch_count: int


class CmaRunRequest(BaseModel):
    parcel: str
    as_of_date: Optional[str] = None
    top_n: int = 10


class CmaCompRow(BaseModel):
    listing_number: str
    bucket: Optional[str] = None
    final_score: Optional[float] = None
    similarity_score: Optional[float] = None
    recency_multiplier: Optional[float] = None
    location_points: Optional[float] = None
    base_points: Optional[float] = None
    feature_points: Optional[float] = None
    recency_days: Optional[int] = None
    distance_miles: Optional[float] = None
    sold_date: Optional[str] = None
    sold_price: Optional[float] = None
    list_price: Optional[float] = None
    ppsf: Optional[float] = None
    short_address: Optional[str] = None
    city: Optional[str] = None
    final_subdivision: Optional[str] = None
    property_type: Optional[str] = None
    geo_lat: Optional[float] = None
    geo_lon: Optional[float] = None
    total_bedrooms: Optional[float] = None
    baths_total: Optional[float] = None
    sqft_living: Optional[float] = None
    year_built: Optional[float] = None


class CmaRunResponse(BaseModel):
    subject: dict
    as_of_date: str
    valuation: dict
    confidence_grade: str
    confidence_reason: str
    pending_projection: dict
    surrounding_discount_metrics: dict
    pending_pressure_guardrail: dict
    closing_trends: dict
    community_insights: dict
    surrounding_area_context: dict
    community_scope: dict
    comps: list[CmaCompRow]


def _postgres_sql(sql: str) -> str:
    """Translate the small SQLite SQL subset used by the read API."""
    translated = sql.replace("DATE('now', ?)", "(CURRENT_DATE + (?::interval))")
    translated = translated.replace("DATE(?)", "(?::date)")
    translated = translated.replace("%", "%%")
    return translated.replace("?", "%s")


class _PostgresCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def description(self):
        return self._cursor.description

    def execute(self, sql: str, params=None):
        self._cursor.execute(_postgres_sql(sql), params or [])
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def close(self):
        self._cursor.close()


class _PostgresConnection:
    def __init__(self):
        if DATABASE_URL:
            self._conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        else:
            host = SUPABASE_DB_HOST or f"db.{SUPABASE_PROJECT_REF}.supabase.co"
            hostaddr = _resolve_ipv4(host)
            kwargs = dict(
                host=host,
                port=SUPABASE_DB_PORT,
                dbname=SUPABASE_DB_NAME,
                user=SUPABASE_DB_USER or "postgres",
                password=SUPABASE_DB_PASSWORD,
                sslmode="require",
                row_factory=dict_row,
            )
            if hostaddr:
                kwargs["hostaddr"] = hostaddr
            self._conn = psycopg.connect(**kwargs)

    def cursor(self):
        return _PostgresCursor(self._conn.cursor())

    def execute(self, sql: str, params=None):
        cursor = self.cursor()
        return cursor.execute(sql, params)

    def close(self):
        self._conn.close()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()


def _resolve_ipv4(host: str) -> Optional[str]:
    try:
        for family, _, _, _, sockaddr in socket.getaddrinfo(host, 5432, type=socket.SOCK_STREAM):
            if family == socket.AF_INET:
                return sockaddr[0]
    except OSError:
        return None
    return None


def get_connection():
    if USE_POSTGRES:
        return _PostgresConnection()
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=500, detail=f"Database not found: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _read_sql_query(sql: str, conn, params=None) -> pd.DataFrame:
    if USE_POSTGRES:
        cursor = conn.cursor()
        cursor.execute(sql, params or [])
        return pd.DataFrame(cursor.fetchall())
    return pd.read_sql_query(sql, conn, params=params)


def _read_latest_audit_summary() -> dict:
    path = os.path.join(_ops_project_root(), "output", "audits", "latest_audit_summary.json")
    if not os.path.exists(path):
        return {"available": False, "path": path}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        payload["available"] = True
        payload["path"] = path
        return payload
    except Exception as e:
        return {"available": False, "path": path, "error": str(e)}


def _read_latest_guardrail_summary() -> dict:
    path = os.path.join(_ops_project_root(), "output", "audits", "latest_guardrail_summary.json")
    if not os.path.exists(path):
        return {"available": False, "path": path}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        payload["available"] = True
        payload["path"] = path
        return payload
    except Exception as e:
        return {"available": False, "path": path, "error": str(e)}


def _read_last_run_metadata() -> dict:
    path = os.path.join(_ops_project_root(), "output", "ops", "last_run.json")
    if not os.path.exists(path):
        return {"available": False, "path": path}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        payload["available"] = True
        payload["path"] = path
        return payload
    except Exception as e:
        return {"available": False, "path": path, "error": str(e)}


def _parse_iso_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _resolve_report_window(
    report_mode: str,
    period_days: int,
    ref_year: Optional[int],
    ref_month: Optional[int],
    ref_quarter: Optional[int],
    start_date: Optional[str],
    end_date: Optional[str],
) -> tuple[str, str, str, str, str]:
    """
    Returns (current_start, current_end, previous_start, previous_end, label) in YYYY-MM-DD.
    """
    today = date.today()
    mode = (report_mode or "rolling").lower()

    if mode == "monthly":
        y = ref_year or today.year
        m = ref_month or today.month
        last_day = calendar.monthrange(y, m)[1]
        current_start = date(y, m, 1)
        current_end = date(y, m, last_day)
        if m == 1:
            py, pm = y - 1, 12
        else:
            py, pm = y, m - 1
        prev_last_day = calendar.monthrange(py, pm)[1]
        previous_start = date(py, pm, 1)
        previous_end = date(py, pm, prev_last_day)
        label = f"{current_start.strftime('%B %Y')}"
    elif mode == "quarterly":
        y = ref_year or today.year
        q = ref_quarter or ((today.month - 1) // 3 + 1)
        q = min(max(q, 1), 4)
        start_month = (q - 1) * 3 + 1
        end_month = start_month + 2
        current_start = date(y, start_month, 1)
        current_end = date(y, end_month, calendar.monthrange(y, end_month)[1])
        if q == 1:
            py, pq = y - 1, 4
        else:
            py, pq = y, q - 1
        p_start_month = (pq - 1) * 3 + 1
        p_end_month = p_start_month + 2
        previous_start = date(py, p_start_month, 1)
        previous_end = date(py, p_end_month, calendar.monthrange(py, p_end_month)[1])
        label = f"Q{q} {y}"
    elif mode == "annual":
        y = ref_year or today.year
        current_start = date(y, 1, 1)
        current_end = date(y, 12, 31)
        previous_start = date(y - 1, 1, 1)
        previous_end = date(y - 1, 12, 31)
        label = f"{y}"
    elif mode == "custom":
        s = _parse_iso_date(start_date)
        e = _parse_iso_date(end_date)
        if s is None or e is None or s > e:
            raise HTTPException(
                status_code=400,
                detail="For custom mode, provide valid start_date and end_date in YYYY-MM-DD with start_date <= end_date.",
            )
        current_start, current_end = s, e
        span_days = (current_end - current_start).days + 1
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=span_days - 1)
        label = f"{current_start.isoformat()} to {current_end.isoformat()}"
    else:
        # rolling window default
        d = max(period_days, 1)
        current_end = today
        current_start = today - timedelta(days=d - 1)
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=d - 1)
        label = f"Last {d} Days"

    return (
        current_start.isoformat(),
        current_end.isoformat(),
        previous_start.isoformat(),
        previous_end.isoformat(),
        label,
    )


def _pct_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None or previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 2)


def _safe_number(value) -> Optional[float]:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


@lru_cache(maxsize=1)
def _listing_details_columns() -> set[str]:
    if USE_POSTGRES:
        with closing(get_connection()) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'listing_details'
                """
            )
            return {row["column_name"] for row in cur.fetchall()}
    if not os.path.exists(DB_PATH):
        return set()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute("PRAGMA table_info(listing_details)").fetchall()
    return {row[1] for row in rows}


def _listing_details_has_column(column_name: str) -> bool:
    return column_name in _listing_details_columns()


def _optional_listing_column(column_name: str) -> str:
    return column_name if _listing_details_has_column(column_name) else f"NULL AS {column_name}"


def _non_cabana_mask(df: pd.DataFrame) -> pd.Series:
    if "cabana_flag" in df.columns:
        return pd.to_numeric(df["cabana_flag"], errors="coerce").fillna(0).eq(0)
    return ~likely_cabana_mask(df)


STATUS_BUCKETS: dict[str, set[str]] = {
    "Active": {"A", "ACTIVE", "ACT", "COMING SOON", "CS"},
    "Pending": {"P", "PENDING", "U", "UNDER CONTRACT", "D", "BACKUP", "L"},
    "Closed": {"C", "CLOSED", "SOLD", "S"},
    "Expired": {"E", "EXPIRED"},
    "Withdrawn": {"W", "WITHDRAWN"},
    "Temp Off Market": {"O", "TEMP OFF MARKET", "TOM"},
    "Hold": {"H", "HOLD"},
    "Cancelled": {"X", "CANCELLED", "CANCELED"},
}
ACTIVE_BUCKET = "Active"


def _status_upper(df: pd.DataFrame) -> pd.Series:
    return df.get("status", pd.Series(index=df.index, dtype="object")).astype(str).str.upper().str.strip()


def _status_bucket(value: object) -> str:
    s = str(value).upper().strip()
    if not s or s == "NAN":
        return "Unknown"
    for bucket, values in STATUS_BUCKETS.items():
        if s in values:
            return bucket
    return s.title()


def _status_bucket_series(df: pd.DataFrame) -> pd.Series:
    return _status_upper(df).map(_status_bucket)


def _is_active_now_mask(df: pd.DataFrame, as_of_date: Optional[pd.Timestamp] = None) -> pd.Series:
    if "effective_active_end_date" not in df.columns:
        return pd.Series(False, index=df.index)
    as_of = pd.Timestamp(as_of_date) if as_of_date is not None else pd.Timestamp.now()
    status_active = _status_bucket_series(df).eq(ACTIVE_BUCKET)
    listing_numbers = df.get("listing_number", pd.Series(index=df.index, dtype="object")).astype(str).str.upper().str.strip()
    primary_inventory = ~listing_numbers.str.startswith(("B", "RX-", "AX-", "FX-"))
    return primary_inventory & _non_cabana_mask(df) & status_active & (
        df["effective_active_end_date"].isna() | (df["effective_active_end_date"] > as_of)
    )


def _is_active_as_of_mask(df: pd.DataFrame, snapshot_date: pd.Timestamp) -> pd.Series:
    if "listing_date" not in df.columns or "effective_active_end_date" not in df.columns:
        return pd.Series(False, index=df.index)
    status_active = _status_bucket_series(df).eq(ACTIVE_BUCKET)
    listing_numbers = df.get("listing_number", pd.Series(index=df.index, dtype="object")).astype(str).str.upper().str.strip()
    primary_inventory = ~listing_numbers.str.startswith(("B", "RX-", "AX-", "FX-"))
    return primary_inventory & _non_cabana_mask(df) & (df["listing_date"].notna()) & (df["listing_date"] <= snapshot_date) & (
        (df["effective_active_end_date"] > snapshot_date)
        | (df["effective_active_end_date"].isna() & status_active)
    )


def _compute_period_metrics(df: pd.DataFrame, start_iso: str, end_iso: str) -> dict:
    start_ts = pd.Timestamp(start_iso).normalize()
    end_ts = pd.Timestamp(end_iso).normalize() + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    non_cabana = _non_cabana_mask(df)

    sold = df[non_cabana & (df["sold_date"].notna()) & (df["sold_date"] >= start_ts) & (df["sold_date"] <= end_ts)].copy()
    listed = df[non_cabana & (df["listing_date"].notna()) & (df["listing_date"] >= start_ts) & (df["listing_date"] <= end_ts)].copy()
    pending = df[
        non_cabana
        &
        (df["under_contract_date"].notna())
        & (df["under_contract_date"] >= start_ts)
        & (df["under_contract_date"] <= end_ts)
    ].copy()

    snapshot_date = end_ts
    active_mask = _is_active_as_of_mask(df, snapshot_date)
    active_inventory = int(active_mask.sum())
    pending_bucket = _status_bucket_series(df).eq("Pending")
    listing_numbers = df.get("listing_number", pd.Series(index=df.index, dtype="object")).astype(str).str.upper().str.strip()
    primary_inventory = ~listing_numbers.str.startswith(("B", "RX-", "AX-", "FX-"))
    pending_inventory_mask = (
        primary_inventory
        & non_cabana
        &
        df["under_contract_date"].notna()
        & (df["under_contract_date"] <= snapshot_date)
        & (df["sold_date"].isna() | (df["sold_date"] > snapshot_date))
        & (
            df["effective_active_end_date"].isna()
            | (df["effective_active_end_date"] > snapshot_date)
            | pending_bucket
        )
    )
    pending_inventory = int(pending_inventory_mask.sum())

    sales_count = int(len(sold))
    # Match legacy months-supply logic including clamp to latest known sold_date.
    max_sold_date = df["sold_date"].max()
    if pd.isna(max_sold_date):
        max_sold_date = pd.Timestamp.now()
    period_start_ts = pd.Timestamp(start_iso).normalize()
    effective_sales_end = min(snapshot_date, max_sold_date)
    if effective_sales_end < snapshot_date and effective_sales_end < period_start_ts:
        effective_sales_end = snapshot_date

    twelve_months_ago = effective_sales_end - pd.DateOffset(months=12)
    sales_12mo = int(
        (non_cabana & (df["sold_date"].notna()) & (df["sold_date"] > twelve_months_ago) & (df["sold_date"] <= effective_sales_end)).sum()
    )
    sales_rate = sales_12mo / 12.0
    months_supply = (active_inventory / sales_rate) if sales_rate > 0 else (0 if active_inventory == 0 else 999)

    # Match legacy median_dom logic: listing_date/effective_active_end_date where end date falls in period.
    dom_df = df[non_cabana & df["listing_date"].notna() & df["effective_active_end_date"].notna()].copy()
    dom_df = dom_df[(dom_df["effective_active_end_date"] >= start_ts) & (dom_df["effective_active_end_date"] <= end_ts)]
    dom_series = (dom_df["effective_active_end_date"] - dom_df["listing_date"]).dt.days

    # Match legacy listing_discount logic: (original_list_price - sold_price) / original_list_price on sold rows.
    discount_series = None
    if "original_list_price" in sold.columns and "sold_price" in sold.columns:
        valid = sold[(sold["original_list_price"] > 0) & (sold["sold_price"].notna())].copy()
        if not valid.empty:
            discount_series = ((valid["original_list_price"] - valid["sold_price"]) / valid["original_list_price"]) * 100

    ppsf_series = None
    if "sqft_living" in sold.columns and "sold_price" in sold.columns:
        valid = sold[(sold["sqft_living"] > 0) & (sold["sold_price"] > 0)].copy()
        if not valid.empty:
            ppsf_series = valid["sold_price"] / valid["sqft_living"]

    cash_sales_percent = None
    if "buyer_financing" in sold.columns and sales_count > 0:
        financing = sold["buyer_financing"].fillna("").astype(str).str.upper().str.strip()
        if financing.ne("").any():
            cash_count = financing.str.contains("CASH", na=False).sum()
            cash_sales_percent = _safe_number((cash_count / sales_count) * 100)

    return {
        "sold_count": sales_count,
        "total_sales_volume": _safe_number(sold["sold_price"].sum()) if "sold_price" in sold.columns else None,
        "median_sold_price": _safe_number(sold["sold_price"].median()) if "sold_price" in sold.columns else None,
        "avg_sold_price": _safe_number(sold["sold_price"].mean()) if "sold_price" in sold.columns else None,
        "median_price_per_sqft": _safe_number(ppsf_series.median()) if ppsf_series is not None else None,
        "avg_list_price": _safe_number(sold["list_price"].mean()) if "list_price" in sold.columns else None,
        "avg_sp_lp": _safe_number(
            ((sold[(sold["sold_price"] > 0) & (sold["list_price"] > 0)]["sold_price"] /
              sold[(sold["sold_price"] > 0) & (sold["list_price"] > 0)]["list_price"]) * 100).mean()
        ) if "sold_price" in sold.columns and "list_price" in sold.columns else None,
        "new_listings": int(len(listed)),
        "pending_sales": int(len(pending)),
        "pending_inventory": pending_inventory,
        "active_inventory": active_inventory,
        "months_supply": _safe_number(months_supply),
        "median_dom": _safe_number(dom_series.median()) if dom_series is not None and not dom_series.empty else None,
        "median_listing_discount": _safe_number(discount_series.median()) if discount_series is not None and not discount_series.empty else None,
        "cash_sales_percent": cash_sales_percent,
    }


def _build_report_listing_rows(df: pd.DataFrame, start_iso: str, end_iso: str) -> list[dict]:
    start_ts = pd.Timestamp(start_iso).normalize()
    end_ts = pd.Timestamp(end_iso).normalize() + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)

    rows = df.copy()
    rows["cabana_flag"] = ~_non_cabana_mask(rows)
    rows["new_listing_in_period"] = (
        rows["listing_date"].notna() & (rows["listing_date"] >= start_ts) & (rows["listing_date"] <= end_ts)
    )
    rows["pending_in_period"] = (
        rows["under_contract_date"].notna()
        & (rows["under_contract_date"] >= start_ts)
        & (rows["under_contract_date"] <= end_ts)
    )
    rows["sold_in_period"] = (
        rows["sold_date"].notna() & (rows["sold_date"] >= start_ts) & (rows["sold_date"] <= end_ts)
    )
    rows["active_at_period_end"] = _is_active_as_of_mask(rows, end_ts)

    pending_bucket = _status_bucket_series(rows).eq("Pending")
    listing_numbers = rows.get("listing_number", pd.Series(index=rows.index, dtype="object")).astype(str).str.upper().str.strip()
    primary_inventory = ~listing_numbers.str.startswith(("B", "RX-", "AX-", "FX-"))
    rows["pending_at_period_end"] = (
        primary_inventory
        & rows["under_contract_date"].notna()
        & (rows["under_contract_date"] <= end_ts)
        & (rows["sold_date"].isna() | (rows["sold_date"] > end_ts))
        & (
            rows["effective_active_end_date"].isna()
            | (rows["effective_active_end_date"] > end_ts)
            | pending_bucket
        )
    )

    contributor_mask = (
        rows["new_listing_in_period"]
        | rows["pending_in_period"]
        | rows["sold_in_period"]
        | rows["active_at_period_end"]
        | rows["pending_at_period_end"]
    )
    rows = rows[contributor_mask].copy()

    def _date_col(series: pd.Series) -> pd.Series:
        return pd.to_datetime(series, errors="coerce").dt.date.astype("string")

    for col in ["listing_date", "under_contract_date", "sold_date", "effective_active_end_date"]:
        rows[col] = _date_col(rows[col])

    rows["sold_ppsf"] = None
    valid_ppsf = (rows["sqft_living"] > 0) & (rows["sold_price"] > 0)
    rows.loc[valid_ppsf, "sold_ppsf"] = (rows.loc[valid_ppsf, "sold_price"] / rows.loc[valid_ppsf, "sqft_living"]).round(2)

    rows["sp_lp_ratio"] = None
    valid_ratio = (rows["list_price"] > 0) & (rows["sold_price"] > 0)
    rows.loc[valid_ratio, "sp_lp_ratio"] = ((rows.loc[valid_ratio, "sold_price"] / rows.loc[valid_ratio, "list_price"]) * 100).round(2)

    rows = rows.sort_values(
        by=["sold_in_period", "sold_date", "pending_in_period", "under_contract_date", "new_listing_in_period", "listing_date", "sold_price"],
        ascending=[False, False, False, False, False, False, False],
        na_position="last",
    )

    cols = [
        "listing_number",
        "parcel_id",
        "short_address",
        "city",
        "geo_zone",
        "final_subdivision",
        "property_type",
        "status",
        "unit_number",
        "listing_date",
        "under_contract_date",
        "sold_date",
        "effective_active_end_date",
        "list_price",
        "original_list_price",
        "sold_price",
        "sold_ppsf",
        "sp_lp_ratio",
        "total_bedrooms",
        "baths_total",
        "sqft_living",
        "geo_lat",
        "geo_lon",
        "terms_of_sale",
        "buyer_financing",
        "cabana_flag",
        "new_listing_in_period",
        "pending_in_period",
        "sold_in_period",
        "active_at_period_end",
        "pending_at_period_end",
    ]
    return rows[cols].replace({pd.NA: None}).where(pd.notna(rows[cols]), None).to_dict(orient="records")


def _resolve_anchor_period(
    frequency: str,
    end_date: Optional[str],
    end_year: Optional[int],
    end_month: Optional[int],
    end_quarter: Optional[int],
) -> pd.Period:
    freq = frequency.lower()
    end_dt = _parse_iso_date(end_date) if end_date else None
    today = date.today()
    if freq == "monthly":
        y = end_year or (end_dt.year if end_dt else today.year)
        m = end_month or (end_dt.month if end_dt else today.month)
        return pd.Period(f"{y}-{m:02d}", freq="M")
    if freq == "quarterly":
        y = end_year or (end_dt.year if end_dt else today.year)
        q = end_quarter or (((end_dt.month if end_dt else today.month) - 1) // 3 + 1)
        return pd.Period(f"{y}Q{q}", freq="Q")
    y = end_year or (end_dt.year if end_dt else today.year)
    return pd.Period(str(y), freq="Y")


def _series_last_value(df: pd.DataFrame, col: str) -> Optional[float]:
    if df is None or df.empty or col not in df.columns:
        return None
    return _safe_number(df.iloc[-1][col])


def _compute_legacy_period_metrics(df: pd.DataFrame, mode: str, start_iso: str, end_iso: str) -> dict:
    freq = "annually" if mode == "annual" else mode
    sales_df = daf.sales_count(df, freq, start_iso, end_iso)
    volume_df = daf.total_sales_volume(df, freq, start_iso, end_iso)
    median_price_df = daf.median_sold_price(df, freq, start_iso, end_iso)
    ppsf_df = daf.median_price_per_sqft(df, freq, start_iso, end_iso)
    new_listings_df = daf.new_listings(df, freq, start_iso, end_iso)
    pending_df = daf.pending_sales(df, freq, start_iso, end_iso)
    active_df = daf.active_inventory(df, freq, start_iso, end_iso)
    msi_df = daf.months_supply(df, freq, start_iso, end_iso)
    dom_df = daf.median_dom(df, freq, start_iso, end_iso)
    discount_df = daf.listing_discount(df, freq, start_iso, end_iso)
    cash_df = daf.cash_sales_percentage(df, freq, start_iso, end_iso)

    sold_slice = df[
        (df["sold_date"].notna())
        & (df["sold_date"] >= pd.Timestamp(start_iso))
        & (df["sold_date"] <= pd.Timestamp(end_iso) + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1))
    ]

    sp_lp = None
    if {"sold_price", "list_price"}.issubset(sold_slice.columns):
        ratio = sold_slice[(sold_slice["sold_price"] > 0) & (sold_slice["list_price"] > 0)]
        if not ratio.empty:
            sp_lp = _safe_number(((ratio["sold_price"] / ratio["list_price"]) * 100).mean())

    return {
        "sold_count": _series_last_value(sales_df, "Sales Count"),
        "total_sales_volume": _series_last_value(volume_df, "Total Sales Volume"),
        "median_sold_price": _series_last_value(median_price_df, "Median Sold Price"),
        "avg_sold_price": _safe_number(sold_slice["sold_price"].mean()) if "sold_price" in sold_slice.columns else None,
        "median_price_per_sqft": _series_last_value(ppsf_df, "Median Price Per SqFt"),
        "avg_list_price": _safe_number(sold_slice["list_price"].mean()) if "list_price" in sold_slice.columns else None,
        "avg_sp_lp": sp_lp,
        "new_listings": _series_last_value(new_listings_df, "New Listings"),
        "pending_sales": _series_last_value(pending_df, "Pending Sales"),
        "pending_inventory": None,
        "active_inventory": _series_last_value(active_df, "Active Inventory"),
        "months_supply": _series_last_value(msi_df, "Months Supply"),
        "median_dom": _series_last_value(dom_df, "Median DOM"),
        "median_listing_discount": _series_last_value(discount_df, "Listing Discount"),
        "cash_sales_percent": _series_last_value(cash_df, "Cash Sales %"),
    }


def _append_common_filters(
    where_clauses: list[str],
    params: list[str],
    city: Optional[str],
    final_subdivision: Optional[str],
    property_type: Optional[str],
    geo_zone: Optional[str] = None,
    property_group: Optional[str] = None,
    sold_since: Optional[str] = None,
) -> None:
    if city:
        where_clauses.append("city = ?")
        params.append(city)
    if final_subdivision:
        where_clauses.append("final_subdivision = ?")
        params.append(final_subdivision)
    if property_type:
        where_clauses.append("property_type = ?")
        params.append(property_type)
    if geo_zone:
        where_clauses.append("geo_zone = ?")
        params.append(geo_zone)
    if property_group and property_group.upper() != "ALL":
        pg = property_group.upper()
        if pg == "SINGLE_FAMILY":
            where_clauses.append(_single_family_property_type_clause())
        elif pg == "TOWNHOME_CONDO":
            where_clauses.append(f"NOT {_single_family_property_type_clause()}")
        elif pg == "ALL":
            pass
        else:
            # Unknown group values are ignored to keep endpoint robust.
            pass
    if sold_since:
        where_clauses.append("DATE(sold_date) >= DATE(?)")
        params.append(sold_since)


def _coerce_iso_date(value: Optional[str]) -> str:
    if not value:
        return date.today().isoformat()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="as_of_date must be YYYY-MM-DD") from exc


def _load_comp_details_map(conn: sqlite3.Connection, listing_numbers: list[str]) -> dict[str, dict]:
    if not listing_numbers:
        return {}
    placeholders = ",".join(["?"] * len(listing_numbers))
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
          listing_number, sold_date, sold_price, list_price,
          short_address, city, final_subdivision, property_type,
          geo_lat, geo_lon, total_bedrooms, baths_total, baths_full, baths_half, sqft_living, year_built
        FROM listing_details
        WHERE listing_number IN ({placeholders})
        """,
        listing_numbers,
    )
    rows = [dict(r) for r in cur.fetchall()]
    out: dict[str, dict] = {}
    for r in rows:
        key = str(r.get("listing_number") or "")
        out[key] = r
    return out


@app.get("/api/health")
def health() -> dict:
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS cnt FROM listing_details")
        count = cursor.fetchone()["cnt"]
    database = "supabase-postgres" if USE_POSTGRES else DB_PATH
    return {"ok": True, "database": database, "listing_count": count}


@app.post("/api/cma/run", response_model=CmaRunResponse)
def cma_run(payload: CmaRunRequest) -> dict:
    as_of_date = _coerce_iso_date(payload.as_of_date)
    top_n = max(5, min(int(payload.top_n or 15), 50))

    try:
        subject = get_subject_by_parcel(payload.parcel, as_of_date=as_of_date)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    scope = resolve_market_scope(subject.pcn_10_digit or subject.parcel_id, subject.final_subdivision or "")
    sales_df = pull_candidate_sales(as_of_date=as_of_date, months_back=12)
    candidates = build_candidate_pool(subject, sales_df, scope, as_of_date=as_of_date)
    scored = score_candidates(subject, candidates, as_of_date=as_of_date, top_n=top_n)
    conf_grade, conf_reason = confidence_grade(scored)

    context = pull_market_activity(subject, as_of_date=as_of_date)
    pending_projection = pull_pending_projection(subject, scope, as_of_date=as_of_date)
    surrounding_discount_metrics = pull_surrounding_discount_metrics(subject, as_of_date=as_of_date)
    pending_pressure_guardrail = build_pending_pressure_guardrail(
        subject,
        scope,
        as_of_date=as_of_date,
        pending_projection=pending_projection,
        surrounding_discount_metrics=surrounding_discount_metrics,
        surrounding_context=context,
    )
    community_insights = build_community_insights(subject, sales_df, scope, as_of_date=as_of_date)
    closing_trends = build_closing_trends(subject, sales_df, scope, as_of_date=as_of_date)
    valuation = value_from_comps(
        subject,
        scored,
        community_insights=community_insights,
        guardrail_context=pending_pressure_guardrail,
    )
    valuation["confidence_grade"] = conf_grade
    valuation["confidence_reason"] = conf_reason

    listing_numbers = [c.listing_number for c in scored]
    with closing(get_connection()) as conn:
        detail_map = _load_comp_details_map(conn, listing_numbers)

    comps: list[dict] = []
    for comp in scored:
        d = asdict(comp)
        more = detail_map.get(comp.listing_number, {})
        baths_total = _safe_number(more.get("baths_total"))
        if baths_total is None:
            full = _safe_number(more.get("baths_full")) or 0.0
            half = _safe_number(more.get("baths_half")) or 0.0
            calc = full + (half * 0.5)
            baths_total = calc if calc > 0 else None
        merged = {
            **d,
            "short_address": more.get("short_address"),
            "city": more.get("city", d.get("city")),
            "final_subdivision": more.get("final_subdivision", d.get("final_subdivision")),
            "property_type": more.get("property_type"),
            "geo_lat": _safe_number(more.get("geo_lat")),
            "geo_lon": _safe_number(more.get("geo_lon")),
            "total_bedrooms": _safe_number(more.get("total_bedrooms")),
            "baths_total": baths_total,
            "sqft_living": _safe_number(more.get("sqft_living")),
            "year_built": _safe_number(more.get("year_built")),
            "sold_price": _safe_number(more.get("sold_price", d.get("sold_price"))),
            "list_price": _safe_number(more.get("list_price")),
            "sold_date": str(more.get("sold_date", d.get("sold_date") or ""))[:10] if (more.get("sold_date") or d.get("sold_date")) else None,
        }
        comps.append(merged)

    same_community = sales_df[sales_df["final_subdivision"].isin(scope.get("final_subdivision_set", set()))].copy()
    community_source_breakdown = (
        same_community.groupby("source_type").size().to_dict() if not same_community.empty else {}
    )

    return {
        "subject": asdict(subject),
        "as_of_date": as_of_date,
        "valuation": valuation,
        "confidence_grade": conf_grade,
        "confidence_reason": conf_reason,
        "pending_projection": pending_projection,
        "surrounding_discount_metrics": surrounding_discount_metrics,
        "pending_pressure_guardrail": pending_pressure_guardrail,
        "closing_trends": closing_trends,
        "community_insights": community_insights,
        "surrounding_area_context": context,
        "community_scope": {
            "final_subdivision_count": len(scope.get("final_subdivision_set", [])),
            "community_sales_pool_count": int(len(same_community)),
            "community_source_breakdown": community_source_breakdown,
        },
        "comps": comps,
    }


@app.get("/api/ops/status")
def ops_status() -> dict:
    with closing(get_connection()) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM listing_details")
        listing_count = cur.fetchone()["c"]

        cur.execute("SELECT MAX(DATE(sold_date)) AS dt FROM listing_details WHERE listing_number LIKE 'PBC-%'")
        last_off_market_sold = cur.fetchone()["dt"]

        cur.execute(
            """
            SELECT MAX(dt) AS last_dt FROM (
                SELECT MAX(DATE(under_contract_date)) AS dt FROM listing_details WHERE listing_number NOT LIKE 'PBC-%'
                UNION ALL
                SELECT MAX(DATE(sold_date)) AS dt FROM listing_details WHERE listing_number NOT LIKE 'PBC-%'
                UNION ALL
                SELECT MAX(DATE(expiration_date)) AS dt FROM listing_details WHERE listing_number NOT LIKE 'PBC-%'
                UNION ALL
                SELECT MAX(DATE(withdrawn_date)) AS dt FROM listing_details WHERE listing_number NOT LIKE 'PBC-%'
                UNION ALL
                SELECT MAX(DATE(temp_off_market_date)) AS dt FROM listing_details WHERE listing_number NOT LIKE 'PBC-%'
                UNION ALL
                SELECT MAX(DATE(cancel_date)) AS dt FROM listing_details WHERE listing_number NOT LIKE 'PBC-%'
            )
            """
        )
        last_mls_status = cur.fetchone()["last_dt"]

        cur.execute("SELECT MAX(DATE(sold_date)) AS dt FROM listing_details WHERE sold_date IS NOT NULL")
        last_sold = cur.fetchone()["dt"]

        cur.execute(
            """
            SELECT property_type, COUNT(*) AS cnt
            FROM listing_details
            GROUP BY property_type
            ORDER BY cnt DESC
            """
        )
        property_type_distribution = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT status FROM listing_details")
        status_df = pd.DataFrame([dict(r) for r in cur.fetchall()])
        if status_df.empty:
            status_distribution = []
            status_bucket_distribution = []
        else:
            raw = (
                _status_upper(status_df)
                .replace({"": "Unknown", "NAN": "Unknown"})
                .value_counts()
                .reset_index()
                .rename(columns={"index": "status", "count": "cnt"})
            )
            status_distribution = raw.to_dict(orient="records")
            buckets = (
                _status_bucket_series(status_df)
                .value_counts()
                .reset_index()
                .rename(columns={"index": "status", "count": "cnt"})
            )
            status_bucket_distribution = buckets.to_dict(orient="records")

    def _days_since(v: Optional[str]) -> Optional[int]:
        if not v:
            return None
        d = _parse_iso_date(v)
        if d is None:
            return None
        return (date.today() - d).days

    return {
        "database": {
            "path": "supabase-postgres" if USE_POSTGRES else DB_PATH,
            "listing_count": listing_count,
            "last_mls_status_date": last_mls_status,
            "last_off_market_sold_date": last_off_market_sold,
            "last_sold_date": last_sold,
            "mls_status_lag_days": _days_since(last_mls_status),
            "sold_lag_days": _days_since(last_sold),
            "property_type_distribution": property_type_distribution,
            "status_distribution": status_distribution,
            "status_bucket_distribution": status_bucket_distribution,
        },
        "duplicate_audit": _read_latest_audit_summary(),
        "guardrail_audit": _read_latest_guardrail_summary(),
        "last_run": _read_last_run_metadata(),
    }


@app.get("/api/ops/parity", response_model=ParityResponse)
def ops_parity(
    mode: Literal["monthly", "quarterly", "annual"] = Query(default="monthly"),
    year: int = Query(default_factory=lambda: date.today().year),
    month: Optional[int] = Query(default=None, ge=1, le=12),
    quarter: Optional[int] = Query(default=None, ge=1, le=4),
    city: Optional[str] = Query(default=None),
    final_subdivision: Optional[str] = Query(default=None),
    property_type: Optional[str] = Query(default=None),
    geo_zone: Optional[str] = Query(default=None),
    property_group: Optional[str] = Query(default="ALL"),
    tolerance_pct: float = Query(default=0.5, ge=0.0, le=100.0),
) -> dict:
    current_start, current_end, _, _, _ = _resolve_report_window(
        report_mode=mode,
        period_days=30,
        ref_year=year,
        ref_month=month,
        ref_quarter=quarter,
        start_date=None,
        end_date=None,
    )
    where_clauses = ["1=1"]
    params: list[str] = []
    _append_common_filters(
        where_clauses,
        params,
        city,
        final_subdivision,
        property_type,
        geo_zone=geo_zone,
        property_group=property_group,
    )
    where_sql = " AND ".join(where_clauses)

    with closing(get_connection()) as conn:
        buyer_financing_select = _optional_listing_column("buyer_financing")
        df = _read_sql_query(
            f"""
            SELECT
                listing_number, city, final_subdivision, geo_zone, property_type, status,
                listing_date, effective_active_end_date, under_contract_date, sold_date,
                list_price, original_list_price, sold_price, terms_of_sale, {buyer_financing_select}, cabana_flag,
                sqft_living, days_on_market, cumulative_dom
            FROM listing_details
            WHERE {where_sql}
            """,
            conn,
            params=params,
        )

    for col in ["listing_date", "effective_active_end_date", "under_contract_date", "sold_date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in ["list_price", "original_list_price", "sold_price", "sqft_living", "days_on_market", "cumulative_dom"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["days_on_market"] = df["days_on_market"].fillna(df["cumulative_dom"])

    api_metrics = _compute_period_metrics(df, current_start, current_end)
    legacy_metrics = _compute_legacy_period_metrics(df, mode, current_start, current_end)

    metrics: list[dict] = []
    mismatches = 0
    for metric in sorted(set(api_metrics.keys()) | set(legacy_metrics.keys())):
        legacy_v = _safe_number(legacy_metrics.get(metric))
        api_v = _safe_number(api_metrics.get(metric))
        delta = None if legacy_v is None or api_v is None else round(api_v - legacy_v, 6)
        delta_pct = _pct_change(api_v, legacy_v)
        in_tolerance = True if delta_pct is None else abs(delta_pct) <= tolerance_pct
        if not in_tolerance:
            mismatches += 1
        metrics.append(
            {
                "metric": metric,
                "legacy_value": legacy_v,
                "api_value": api_v,
                "delta": delta,
                "delta_pct": delta_pct,
                "in_tolerance": in_tolerance,
            }
        )

    return {
        "mode": mode,
        "current_start": current_start,
        "current_end": current_end,
        "tolerance_pct": tolerance_pct,
        "metrics": metrics,
        "mismatch_count": mismatches,
    }


@app.get("/api/summary/kpis", response_model=KpiSummaryResponse)
def summary_kpis(
    city: Optional[str] = Query(default=None),
    final_subdivision: Optional[str] = Query(default=None),
    property_type: Optional[str] = Query(default=None),
    geo_zone: Optional[str] = Query(default=None),
    property_group: Optional[str] = Query(default="ALL"),
    sold_since: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    snapshot_date: Optional[str] = Query(default=None, description="YYYY-MM-DD for as-of inventory snapshot"),
) -> dict:
    cabana_select = "cabana_flag" if _listing_details_has_column("cabana_flag") else "0 AS cabana_flag"
    where_clauses = ["1=1"]
    params: list[str] = []
    _append_common_filters(
        where_clauses,
        params,
        city,
        final_subdivision,
        property_type,
        geo_zone=geo_zone,
        property_group=property_group,
        sold_since=sold_since,
    )

    where_sql = " AND ".join(where_clauses)

    with closing(get_connection()) as conn:
        active_df = _read_sql_query(
            f"""
            SELECT listing_number, listing_date, effective_active_end_date, status, sold_price, list_price
                 , {cabana_select}
            FROM listing_details
            WHERE {where_sql}
            """,
            conn,
            params=params,
        )

    if active_df.empty:
        row = {
            "total_records": 0,
            "closed_count": 0,
            "avg_sold_price": None,
            "avg_list_price": None,
            "avg_sp_lp_ratio": None,
        }
    else:
        active_df = active_df[_non_cabana_mask(active_df)].copy()
        active_df["sold_price"] = pd.to_numeric(active_df["sold_price"], errors="coerce")
        active_df["list_price"] = pd.to_numeric(active_df["list_price"], errors="coerce")
        status_bucket = _status_bucket_series(active_df)
        ratio_df = active_df[(active_df["sold_price"] > 0) & (active_df["list_price"] > 0)]
        row = {
            "total_records": int(len(active_df)),
            "closed_count": int(status_bucket.eq("Closed").sum()),
            "avg_sold_price": _safe_number(active_df.loc[active_df["sold_price"] > 0, "sold_price"].mean()),
            "avg_list_price": _safe_number(active_df.loc[active_df["list_price"] > 0, "list_price"].mean()),
            "avg_sp_lp_ratio": _safe_number(((ratio_df["sold_price"] / ratio_df["list_price"]) * 100).mean()) if not ratio_df.empty else None,
        }

    if active_df.empty:
        active_current = 0
        active_snapshot = 0
    else:
        active_df["listing_date"] = pd.to_datetime(active_df["listing_date"], errors="coerce")
        active_df["effective_active_end_date"] = pd.to_datetime(active_df["effective_active_end_date"], errors="coerce")
        active_current = int(_is_active_now_mask(active_df).sum())
        if snapshot_date:
            parsed_snapshot = _parse_iso_date(snapshot_date)
            if parsed_snapshot is None:
                raise HTTPException(status_code=400, detail="snapshot_date must be YYYY-MM-DD")
            snapshot_ts = pd.Timestamp(parsed_snapshot)
        else:
            snapshot_ts = pd.Timestamp.now().normalize()
        active_snapshot = int(_is_active_as_of_mask(active_df, snapshot_ts).sum())

    row["active_inventory_current"] = active_current
    row["active_inventory_snapshot"] = active_snapshot
    row["active_inventory_snapshot_date"] = snapshot_date or date.today().isoformat()
    # Backward compatibility for older clients expecting active_count.
    row["active_count"] = active_current
    return row


@app.get("/api/market/trends")
def market_trends(
    months: int = Query(default=12, ge=1, le=120),
    frequency: str = Query(default="monthly", pattern="^(monthly|quarterly|annual)$"),
    start_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    city: Optional[str] = Query(default=None),
    final_subdivision: Optional[str] = Query(default=None),
    property_type: Optional[str] = Query(default=None),
    geo_zone: Optional[str] = Query(default=None),
    property_group: Optional[str] = Query(default="ALL"),
) -> dict:
    where_clauses = [
        "sold_date IS NOT NULL",
        "COALESCE(cabana_flag, 0) = 0",
    ]
    params: list[str] = []
    if start_date and end_date:
        where_clauses.append("DATE(sold_date) >= DATE(?)")
        where_clauses.append("DATE(sold_date) <= DATE(?)")
        params.extend([start_date, end_date])
    else:
        where_clauses.append("DATE(sold_date) >= DATE('now', ?)")
        params.append(f"-{months} months")
    _append_common_filters(
        where_clauses,
        params,
        city,
        final_subdivision,
        property_type,
        geo_zone=geo_zone,
        property_group=property_group,
    )

    where_sql = " AND ".join(where_clauses)
    freq = frequency.lower()
    if USE_POSTGRES and freq == "quarterly":
        group_expr = "'Q' || EXTRACT(QUARTER FROM sold_date)::int::text || ' ' || EXTRACT(YEAR FROM sold_date)::int::text"
    elif USE_POSTGRES and freq == "annual":
        group_expr = "TO_CHAR(sold_date, 'YYYY')"
    elif USE_POSTGRES:
        group_expr = "TO_CHAR(sold_date, 'YYYY-MM')"
    elif freq == "quarterly":
        group_expr = "'Q' || CAST(((CAST(STRFTIME('%m', DATE(sold_date)) AS INTEGER)-1)/3)+1 AS INTEGER) || ' ' || STRFTIME('%Y', DATE(sold_date))"
    elif freq == "annual":
        group_expr = "STRFTIME('%Y', DATE(sold_date))"
    else:
        group_expr = "STRFTIME('%Y-%m', DATE(sold_date))"

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT
                {group_expr} AS period,
                COUNT(*) AS sold_count,
                CAST(ROUND(CAST(AVG(CASE WHEN sold_price > 0 THEN sold_price END) AS NUMERIC), 2) AS DOUBLE PRECISION) AS avg_sold_price,
                CAST(ROUND(CAST(MIN(CASE WHEN sold_price > 0 THEN sold_price END) AS NUMERIC), 2) AS DOUBLE PRECISION) AS min_sold_price,
                CAST(ROUND(CAST(MAX(CASE WHEN sold_price > 0 THEN sold_price END) AS NUMERIC), 2) AS DOUBLE PRECISION) AS max_sold_price
            FROM listing_details
            WHERE {where_sql}
            GROUP BY {group_expr}
            ORDER BY MIN(DATE(sold_date))
            """,
            params,
        )
        rows = [dict(r) for r in cursor.fetchall()]

    return {"months": months, "frequency": freq, "rows": rows}


@app.get("/api/inventory/by-status")
def inventory_by_status(
    city: Optional[str] = Query(default=None),
    final_subdivision: Optional[str] = Query(default=None),
    property_type: Optional[str] = Query(default=None),
    geo_zone: Optional[str] = Query(default=None),
    property_group: Optional[str] = Query(default="ALL"),
) -> dict:
    where_clauses = ["COALESCE(cabana_flag, 0) = 0"]
    params: list[str] = []
    _append_common_filters(
        where_clauses,
        params,
        city,
        final_subdivision,
        property_type,
        geo_zone=geo_zone,
        property_group=property_group,
    )

    where_sql = " AND ".join(where_clauses)

    with closing(get_connection()) as conn:
        df = _read_sql_query(
            f"""
            SELECT status
            FROM listing_details
            WHERE {where_sql}
            """,
            conn,
            params=params,
        )
    if df.empty:
        rows = []
    else:
        counts = _status_bucket_series(df).value_counts()
        rows = [{"status": str(k), "count": int(v)} for k, v in counts.items()]

    return {"rows": rows}


@app.get("/api/filters/options")
def filter_options(
    city: Optional[str] = Query(default=None),
    geo_zone: Optional[str] = Query(default=None),
    property_type: Optional[str] = Query(default=None),
    property_group: Optional[str] = Query(default="ALL"),
) -> dict:
    where_clauses = ["1=1"]
    params: list[str] = []
    _append_common_filters(
        where_clauses,
        params,
        city=city,
        final_subdivision=None,
        property_type=property_type,
        geo_zone=geo_zone,
        property_group=property_group,
    )
    where_sql = " AND ".join(where_clauses)

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT city, COUNT(*) AS count
            FROM listing_details
            WHERE city IS NOT NULL AND TRIM(city) <> ''
            GROUP BY city
            ORDER BY count DESC, city ASC
            LIMIT 200
            """
        )
        cities = [dict(r) for r in cursor.fetchall()]

        cursor.execute(
            f"""
            SELECT final_subdivision, COUNT(*) AS count
            FROM listing_details
            WHERE final_subdivision IS NOT NULL AND TRIM(final_subdivision) <> ''
              AND {where_sql}
            GROUP BY final_subdivision
            ORDER BY count DESC, final_subdivision ASC
            LIMIT 500
            """,
            params,
        )
        subdivisions = [dict(r) for r in cursor.fetchall()]

        cursor.execute(
            f"""
            SELECT property_type, COUNT(*) AS count
            FROM listing_details
            WHERE property_type IS NOT NULL AND TRIM(property_type) <> ''
              AND {where_sql}
            GROUP BY property_type
            ORDER BY count DESC, property_type ASC
            """,
            params,
        )
        property_types = [dict(r) for r in cursor.fetchall()]

        cursor.execute(
            f"""
            SELECT geo_zone, COUNT(*) AS count
            FROM listing_details
            WHERE geo_zone IS NOT NULL AND TRIM(geo_zone) <> ''
              AND {where_sql}
            GROUP BY geo_zone
            ORDER BY count DESC, geo_zone ASC
            """,
            params,
        )
        geo_zones = [dict(r) for r in cursor.fetchall()]

    return {
        "cities": cities,
        "subdivisions": subdivisions,
        "property_types": property_types,
        "property_groups": [
            {"value": "ALL", "label": "All"},
            {"value": "SINGLE_FAMILY", "label": "Single Family Home"},
            {"value": "TOWNHOME_CONDO", "label": "Condo/TH/Other"},
        ],
        "geo_zones": geo_zones,
    }


@app.get("/api/listings/recent")
def recent_listings(
    limit: int = Query(default=25, ge=1, le=200),
    city: Optional[str] = Query(default=None),
    final_subdivision: Optional[str] = Query(default=None),
    property_type: Optional[str] = Query(default=None),
    geo_zone: Optional[str] = Query(default=None),
    property_group: Optional[str] = Query(default="ALL"),
    sold_since: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    start_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
) -> dict:
    cabana_select = "cabana_flag" if _listing_details_has_column("cabana_flag") else "0 AS cabana_flag"
    where_clauses = ["sold_date IS NOT NULL"]
    params: list[str] = []
    _append_common_filters(
        where_clauses,
        params,
        city,
        final_subdivision,
        property_type,
        geo_zone=geo_zone,
        property_group=property_group,
    )
    if start_date and end_date:
        where_clauses.append("DATE(sold_date) >= DATE(?)")
        where_clauses.append("DATE(sold_date) <= DATE(?)")
        params.extend([start_date, end_date])
    elif sold_since:
        where_clauses.append("DATE(sold_date) >= DATE(?)")
        params.append(sold_since)
    where_sql = " AND ".join(where_clauses)

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT
                listing_number,
                DATE(sold_date) AS sold_date,
                short_address,
                city,
                final_subdivision,
                geo_zone,
                property_type,
                status,
                total_bedrooms,
                baths_total,
                sqft_living,
                geo_lat,
                geo_lon,
                list_price,
                sold_price,
                {cabana_select},
                CASE
                    WHEN sqft_living > 0 AND sold_price > 0 THEN CAST(ROUND(CAST((sold_price / sqft_living) AS NUMERIC), 2) AS DOUBLE PRECISION)
                    ELSE NULL
                END AS sold_ppsf,
                CASE
                    WHEN list_price > 0 AND sold_price > 0 THEN CAST(ROUND(CAST((sold_price / list_price) * 100 AS NUMERIC), 2) AS DOUBLE PRECISION)
                    ELSE NULL
                END AS sp_lp_ratio
            FROM listing_details
            WHERE {where_sql}
            ORDER BY DATE(sold_date) DESC, sold_price DESC
            LIMIT ?
            """,
            params + [limit],
        )
        rows = [dict(r) for r in cursor.fetchall()]

    return {"rows": rows, "limit": limit}


@app.get("/api/market/report-summary", response_model=ReportSummaryResponse)
def market_report_summary(
    report_mode: str = Query(default="rolling", pattern="^(rolling|monthly|quarterly|annual|custom)$"),
    period_days: int = Query(default=30, ge=7, le=366),
    ref_year: Optional[int] = Query(default=None),
    ref_month: Optional[int] = Query(default=None, ge=1, le=12),
    ref_quarter: Optional[int] = Query(default=None, ge=1, le=4),
    start_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    city: Optional[str] = Query(default=None),
    final_subdivision: Optional[str] = Query(default=None),
    property_type: Optional[str] = Query(default=None),
    geo_zone: Optional[str] = Query(default=None),
    property_group: Optional[str] = Query(default="ALL"),
) -> dict:
    current_start, current_end, previous_start, previous_end, period_label = _resolve_report_window(
        report_mode=report_mode,
        period_days=period_days,
        ref_year=ref_year,
        ref_month=ref_month,
        ref_quarter=ref_quarter,
        start_date=start_date,
        end_date=end_date,
    )

    where_clauses = ["1=1"]
    params: list[str] = []
    _append_common_filters(
        where_clauses,
        params,
        city,
        final_subdivision,
        property_type,
        geo_zone=geo_zone,
        property_group=property_group,
    )
    where_sql = " AND ".join(where_clauses)

    with closing(get_connection()) as conn:
        buyer_financing_select = _optional_listing_column("buyer_financing")
        df = _read_sql_query(
            f"""
            SELECT
                listing_number,
                city,
                final_subdivision,
                geo_zone,
                property_type,
                status,
                listing_date,
                effective_active_end_date,
                under_contract_date,
                sold_date,
                list_price,
                original_list_price,
                sold_price,
                cabana_flag,
                terms_of_sale,
                {buyer_financing_select},
                sqft_living,
                days_on_market,
                cumulative_dom
            FROM listing_details
            WHERE {where_sql}
            """,
            conn,
            params=params,
        )

    for col in ["listing_date", "effective_active_end_date", "under_contract_date", "sold_date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in ["list_price", "original_list_price", "sold_price", "sqft_living", "days_on_market", "cumulative_dom"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # Use cumulative_dom fallback if days_on_market missing
    df["days_on_market"] = df["days_on_market"].fillna(df["cumulative_dom"])

    current = _compute_period_metrics(df, current_start, current_end)
    previous = _compute_period_metrics(df, previous_start, previous_end)

    keys = sorted(set(current.keys()) | set(previous.keys()))
    delta_pct = {k: _pct_change(current.get(k), previous.get(k)) for k in keys}

    return {
        "report_mode": report_mode,
        "period_days": period_days,
        "period_label": period_label,
        "current_start": current_start,
        "current_end": current_end,
        "previous_start": previous_start,
        "previous_end": previous_end,
        "current": current,
        "previous": previous,
        "delta_pct": delta_pct,
    }


@app.get("/api/market/report-listings", response_model=ReportListingsResponse)
def market_report_listings(
    report_mode: str = Query(default="rolling", pattern="^(rolling|monthly|quarterly|annual|custom)$"),
    period_days: int = Query(default=30, ge=7, le=366),
    ref_year: Optional[int] = Query(default=None),
    ref_month: Optional[int] = Query(default=None, ge=1, le=12),
    ref_quarter: Optional[int] = Query(default=None, ge=1, le=4),
    start_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    city: Optional[str] = Query(default=None),
    final_subdivision: Optional[str] = Query(default=None),
    property_type: Optional[str] = Query(default=None),
    geo_zone: Optional[str] = Query(default=None),
    property_group: Optional[str] = Query(default="ALL"),
) -> dict:
    current_start, current_end, _, _, period_label = _resolve_report_window(
        report_mode=report_mode,
        period_days=period_days,
        ref_year=ref_year,
        ref_month=ref_month,
        ref_quarter=ref_quarter,
        start_date=start_date,
        end_date=end_date,
    )

    where_clauses = ["1=1"]
    params: list[str] = []
    _append_common_filters(
        where_clauses,
        params,
        city,
        final_subdivision,
        property_type,
        geo_zone=geo_zone,
        property_group=property_group,
    )
    where_sql = " AND ".join(where_clauses)

    with closing(get_connection()) as conn:
        buyer_financing_select = _optional_listing_column("buyer_financing")
        df = _read_sql_query(
            f"""
            SELECT
                listing_number,
                parcel_id,
                short_address,
                city,
                geo_zone,
                final_subdivision,
                property_type,
                status,
                unit_number,
                listing_date,
                effective_active_end_date,
                under_contract_date,
                sold_date,
                list_price,
                original_list_price,
                sold_price,
                total_bedrooms,
                baths_total,
                sqft_living,
                geo_lat,
                geo_lon,
                cabana_flag,
                terms_of_sale,
                {buyer_financing_select}
            FROM listing_details
            WHERE {where_sql}
            """,
            conn,
            params=params,
        )

    for col in ["listing_date", "effective_active_end_date", "under_contract_date", "sold_date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in ["list_price", "original_list_price", "sold_price", "total_bedrooms", "baths_total", "sqft_living", "geo_lat", "geo_lon"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    rows = _build_report_listing_rows(df, current_start, current_end)
    return {
        "report_mode": report_mode,
        "period_label": period_label,
        "current_start": current_start,
        "current_end": current_end,
        "row_count": len(rows),
        "rows": rows,
    }


@app.get("/api/market/subdivision-rankings")
def subdivision_rankings(
    report_mode: str = Query(default="rolling", pattern="^(rolling|monthly|quarterly|annual|custom)$"),
    period_days: int = Query(default=30, ge=7, le=366),
    ref_year: Optional[int] = Query(default=None),
    ref_month: Optional[int] = Query(default=None, ge=1, le=12),
    ref_quarter: Optional[int] = Query(default=None, ge=1, le=4),
    start_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    min_sales: int = Query(default=2, ge=1, le=50),
    limit: int = Query(default=15, ge=1, le=100),
    city: Optional[str] = Query(default=None),
    property_type: Optional[str] = Query(default=None),
    geo_zone: Optional[str] = Query(default=None),
    property_group: Optional[str] = Query(default="ALL"),
) -> dict:
    current_start, current_end, _, _, period_label = _resolve_report_window(
        report_mode=report_mode,
        period_days=period_days,
        ref_year=ref_year,
        ref_month=ref_month,
        ref_quarter=ref_quarter,
        start_date=start_date,
        end_date=end_date,
    )

    where_clauses = [
        "sold_date IS NOT NULL",
        "COALESCE(cabana_flag, 0) = 0",
        "DATE(sold_date) >= DATE(?)",
        "DATE(sold_date) <= DATE(?)",
        "final_subdivision IS NOT NULL",
        "TRIM(final_subdivision) <> ''",
    ]
    params: list[str] = [current_start, current_end]
    if city:
        where_clauses.append("city = ?")
        params.append(city)
    if property_type:
        where_clauses.append("property_type = ?")
        params.append(property_type)
    if geo_zone:
        where_clauses.append("geo_zone = ?")
        params.append(geo_zone)
    if property_group and property_group.upper() != "ALL":
        pg = property_group.upper()
        if pg == "SINGLE_FAMILY":
            where_clauses.append(_single_family_property_type_clause())
        elif pg == "TOWNHOME_CONDO":
            where_clauses.append(f"NOT {_single_family_property_type_clause()}")
    where_sql = " AND ".join(where_clauses)

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT
                final_subdivision,
                city,
                COUNT(*) AS sold_count,
                CAST(ROUND(CAST(AVG(CASE WHEN sold_price > 0 THEN sold_price END) AS NUMERIC), 2) AS DOUBLE PRECISION) AS avg_sold_price,
                CAST(ROUND(CAST(AVG(CASE WHEN list_price > 0 THEN list_price END) AS NUMERIC), 2) AS DOUBLE PRECISION) AS avg_list_price,
                CAST(ROUND(CAST(AVG(CASE
                    WHEN sold_price > 0 AND list_price > 0 THEN (sold_price / list_price) * 100
                END) AS NUMERIC), 2) AS DOUBLE PRECISION) AS avg_sp_lp,
                CAST(ROUND(CAST(AVG(CASE WHEN COALESCE(days_on_market, cumulative_dom) > 0 THEN COALESCE(days_on_market, cumulative_dom) END) AS NUMERIC), 1) AS DOUBLE PRECISION) AS avg_dom
            FROM listing_details
            WHERE {where_sql}
            GROUP BY final_subdivision, city
            HAVING COUNT(*) >= ?
            ORDER BY sold_count DESC, avg_sold_price DESC
            LIMIT ?
            """,
            params + [min_sales, limit],
        )
        rows = [dict(r) for r in cursor.fetchall()]

    return {
        "report_mode": report_mode,
        "period_days": period_days,
        "period_label": period_label,
        "current_start": current_start,
        "current_end": current_end,
        "rows": rows,
    }


@app.get("/api/market/period-series", response_model=PeriodSeriesResponse)
def market_period_series(
    frequency: str = Query(default="monthly", pattern="^(monthly|quarterly|annual)$"),
    periods: int = Query(default=12, ge=2, le=60),
    end_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    end_year: Optional[int] = Query(default=None),
    end_month: Optional[int] = Query(default=None, ge=1, le=12),
    end_quarter: Optional[int] = Query(default=None, ge=1, le=4),
    city: Optional[str] = Query(default=None),
    final_subdivision: Optional[str] = Query(default=None),
    property_type: Optional[str] = Query(default=None),
    geo_zone: Optional[str] = Query(default=None),
    property_group: Optional[str] = Query(default="ALL"),
) -> dict:
    where_clauses = ["1=1"]
    params: list[str] = []
    _append_common_filters(
        where_clauses,
        params,
        city,
        final_subdivision,
        property_type,
        geo_zone=geo_zone,
        property_group=property_group,
    )
    where_sql = " AND ".join(where_clauses)

    with closing(get_connection()) as conn:
        buyer_financing_select = _optional_listing_column("buyer_financing")
        df = _read_sql_query(
            f"""
            SELECT
                listing_number,
                city,
                final_subdivision,
                geo_zone,
                property_type,
                status,
                listing_date,
                effective_active_end_date,
                under_contract_date,
                sold_date,
                list_price,
                original_list_price,
                sold_price,
                cabana_flag,
                terms_of_sale,
                {buyer_financing_select},
                sqft_living,
                days_on_market,
                cumulative_dom
            FROM listing_details
            WHERE {where_sql}
            """,
            conn,
            params=params,
        )

    for col in ["listing_date", "effective_active_end_date", "under_contract_date", "sold_date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in ["list_price", "original_list_price", "sold_price", "sqft_living", "days_on_market", "cumulative_dom"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["days_on_market"] = df["days_on_market"].fillna(df["cumulative_dom"])

    anchor = _resolve_anchor_period(frequency, end_date, end_year, end_month, end_quarter)
    rows = []
    for i in range(periods - 1, -1, -1):
        p = anchor - i
        start_iso = p.start_time.date().isoformat()
        end_iso = p.end_time.date().isoformat()
        metrics = _compute_period_metrics(df, start_iso, end_iso)
        if frequency == "monthly":
            label = p.strftime("%b %Y")
        elif frequency == "quarterly":
            label = f"Q{p.quarter} {p.year}"
        else:
            label = str(p.year)
        rows.append(
            {
                "period": label,
                "start_date": start_iso,
                "end_date": end_iso,
                **metrics,
            }
        )

    return {"frequency": frequency, "periods": periods, "rows": rows}
