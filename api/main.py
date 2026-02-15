import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from typing import Optional
import calendar
import json

import pandas as pd

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware


def _default_db_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(here)
    return os.path.join(project_root, "mls.db")


DB_PATH = os.getenv("RESTATS_DB_PATH", _default_db_path())

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


def get_connection() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=500, detail=f"Database not found: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _read_latest_audit_summary() -> dict:
    path = os.path.join(os.path.dirname(_default_db_path()), "output", "audits", "latest_audit_summary.json")
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


def _active_snapshot_mask(df: pd.DataFrame, snapshot_date: pd.Timestamp) -> pd.Series:
    activeish = df.get("status", pd.Series(index=df.index, dtype="object")).astype(str).str.upper().isin(
        ["A", "ACTIVE", "ACT", "COMING SOON", "CS"]
    )
    return (df["listing_date"].notna()) & (df["listing_date"] <= snapshot_date) & (
        (df["effective_active_end_date"] > snapshot_date)
        | (df["effective_active_end_date"].isna() & activeish)
    )


def _compute_period_metrics(df: pd.DataFrame, start_iso: str, end_iso: str) -> dict:
    start_ts = pd.Timestamp(start_iso).normalize()
    end_ts = pd.Timestamp(end_iso).normalize() + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)

    sold = df[(df["sold_date"].notna()) & (df["sold_date"] >= start_ts) & (df["sold_date"] <= end_ts)].copy()
    listed = df[(df["listing_date"].notna()) & (df["listing_date"] >= start_ts) & (df["listing_date"] <= end_ts)].copy()
    pending = df[
        (df["under_contract_date"].notna())
        & (df["under_contract_date"] >= start_ts)
        & (df["under_contract_date"] <= end_ts)
    ].copy()

    snapshot_date = end_ts
    active_mask = _active_snapshot_mask(df, snapshot_date)
    active_inventory = int(active_mask.sum())

    sales_count = int(len(sold))
    # Match legacy months-supply logic: active snapshot / (trailing 12mo sales / 12)
    twelve_months_ago = end_ts - pd.DateOffset(months=12)
    sales_12mo = int(((df["sold_date"].notna()) & (df["sold_date"] > twelve_months_ago) & (df["sold_date"] <= end_ts)).sum())
    sales_rate = sales_12mo / 12.0
    months_supply = (active_inventory / sales_rate) if sales_rate > 0 else (0 if active_inventory == 0 else 999)

    # Match legacy median_dom logic: listing_date/effective_active_end_date where end date falls in period.
    dom_df = df[df["listing_date"].notna() & df["effective_active_end_date"].notna()].copy()
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
    if "terms_of_sale" in sold.columns and sales_count > 0:
        terms = sold["terms_of_sale"].astype(str).str.upper()
        cash_count = terms.str.contains("CASH", na=False).sum()
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
        "active_inventory": active_inventory,
        "months_supply": _safe_number(months_supply),
        "median_dom": _safe_number(dom_series.median()) if dom_series is not None and not dom_series.empty else None,
        "median_listing_discount": _safe_number(discount_series.median()) if discount_series is not None and not discount_series.empty else None,
        "cash_sales_percent": cash_sales_percent,
    }


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
            where_clauses.append(
                "UPPER(COALESCE(property_type, '')) IN ('SF','SINGLE FAMILY','SINGLE-FAMILY','SINGLE FAMILY HOME')"
            )
        elif pg == "TOWNHOME_CONDO":
            where_clauses.append(
                "UPPER(COALESCE(property_type, '')) NOT IN ('SF','SINGLE FAMILY','SINGLE-FAMILY','SINGLE FAMILY HOME')"
            )
        elif pg == "ALL":
            pass
        else:
            # Unknown group values are ignored to keep endpoint robust.
            pass
    if sold_since:
        where_clauses.append("DATE(sold_date) >= DATE(?)")
        params.append(sold_since)


@app.get("/api/health")
def health() -> dict:
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS cnt FROM listing_details")
        count = cursor.fetchone()["cnt"]
    return {"ok": True, "database": DB_PATH, "listing_count": count}


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

        cur.execute(
            """
            SELECT property_type, COUNT(*) AS cnt
            FROM listing_details
            GROUP BY property_type
            ORDER BY cnt DESC
            """
        )
        property_type_distribution = [dict(r) for r in cur.fetchall()]

    return {
        "database": {
            "path": DB_PATH,
            "listing_count": listing_count,
            "last_mls_status_date": last_mls_status,
            "last_off_market_sold_date": last_off_market_sold,
            "property_type_distribution": property_type_distribution,
        },
        "duplicate_audit": _read_latest_audit_summary(),
    }


@app.get("/api/summary/kpis")
def summary_kpis(
    city: Optional[str] = Query(default=None),
    final_subdivision: Optional[str] = Query(default=None),
    property_type: Optional[str] = Query(default=None),
    geo_zone: Optional[str] = Query(default=None),
    property_group: Optional[str] = Query(default="ALL"),
    sold_since: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
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
        sold_since=sold_since,
    )

    where_sql = " AND ".join(where_clauses)

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT
                COUNT(*) AS total_records,
                SUM(CASE WHEN status IN ('C', 'Closed', 'Sold') THEN 1 ELSE 0 END) AS closed_count,
                SUM(CASE WHEN status IN ('A', 'Active', 'Coming Soon') THEN 1 ELSE 0 END) AS active_count,
                ROUND(AVG(CASE WHEN sold_price > 0 THEN sold_price END), 2) AS avg_sold_price,
                ROUND(AVG(CASE WHEN list_price > 0 THEN list_price END), 2) AS avg_list_price,
                ROUND(AVG(CASE
                    WHEN sold_price > 0 AND list_price > 0 THEN (sold_price / list_price) * 100
                END), 2) AS avg_sp_lp_ratio
            FROM listing_details
            WHERE {where_sql}
            """,
            params,
        )
        row = cursor.fetchone()

    return dict(row)


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
    if freq == "quarterly":
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
                ROUND(AVG(CASE WHEN sold_price > 0 THEN sold_price END), 2) AS avg_sold_price,
                ROUND(MIN(CASE WHEN sold_price > 0 THEN sold_price END), 2) AS min_sold_price,
                ROUND(MAX(CASE WHEN sold_price > 0 THEN sold_price END), 2) AS max_sold_price
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
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT
                CASE
                    WHEN status IN ('C', 'Closed', 'Sold') THEN 'Closed'
                    WHEN status IN ('A', 'Active') THEN 'Active'
                    WHEN status IN ('L') THEN 'Under Contract'
                    WHEN status IN ('P') THEN 'Pending'
                    WHEN status IN ('E') THEN 'Expired'
                    WHEN status IN ('W') THEN 'Withdrawn'
                    WHEN status IN ('O') THEN 'Temp Off Market'
                    WHEN status IN ('H') THEN 'Hold'
                    ELSE COALESCE(status, 'Unknown')
                END AS status,
                COUNT(*) AS count
            FROM listing_details
            WHERE {where_sql}
            GROUP BY
                CASE
                    WHEN status IN ('C', 'Closed', 'Sold') THEN 'Closed'
                    WHEN status IN ('A', 'Active') THEN 'Active'
                    WHEN status IN ('L') THEN 'Under Contract'
                    WHEN status IN ('P') THEN 'Pending'
                    WHEN status IN ('E') THEN 'Expired'
                    WHEN status IN ('W') THEN 'Withdrawn'
                    WHEN status IN ('O') THEN 'Temp Off Market'
                    WHEN status IN ('H') THEN 'Hold'
                    ELSE COALESCE(status, 'Unknown')
                END
            ORDER BY count DESC
            """,
            params,
        )
        rows = [dict(r) for r in cursor.fetchall()]

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
                list_price,
                sold_price,
                CASE
                    WHEN list_price > 0 AND sold_price > 0 THEN ROUND((sold_price / list_price) * 100, 2)
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


@app.get("/api/market/report-summary")
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
        df = pd.read_sql_query(
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
                terms_of_sale,
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
            where_clauses.append(
                "UPPER(COALESCE(property_type, '')) IN ('SF','SINGLE FAMILY','SINGLE-FAMILY','SINGLE FAMILY HOME')"
            )
        elif pg == "TOWNHOME_CONDO":
            where_clauses.append(
                "UPPER(COALESCE(property_type, '')) NOT IN ('SF','SINGLE FAMILY','SINGLE-FAMILY','SINGLE FAMILY HOME')"
            )
    where_sql = " AND ".join(where_clauses)

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT
                final_subdivision,
                city,
                COUNT(*) AS sold_count,
                ROUND(AVG(CASE WHEN sold_price > 0 THEN sold_price END), 2) AS avg_sold_price,
                ROUND(AVG(CASE WHEN list_price > 0 THEN list_price END), 2) AS avg_list_price,
                ROUND(AVG(CASE
                    WHEN sold_price > 0 AND list_price > 0 THEN (sold_price / list_price) * 100
                END), 2) AS avg_sp_lp,
                ROUND(AVG(CASE WHEN COALESCE(days_on_market, cumulative_dom) > 0 THEN COALESCE(days_on_market, cumulative_dom) END), 1) AS avg_dom
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


@app.get("/api/market/period-series")
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
        df = pd.read_sql_query(
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
                terms_of_sale,
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
