import re
from typing import Dict

import pandas as pd

from .models import SubjectProfile


KEYWORD_PATTERNS = {
    "renovated_updated": r"\b(?:renovat|remodel|updated|newly updated|designer)\b",
    "impact_windows": r"\b(?:impact|hurricane)\b",
    "new_roof": r"\b(?:new roof|roof replaced|roof 20)\b",
    "turnkey_luxury": r"\b(?:turnkey|luxury|custom|chef)\b",
}


def _same_community_mask(df: pd.DataFrame, subject: SubjectProfile, scope: Dict[str, set]) -> pd.Series:
    same_sub_scope = df["final_subdivision"].isin(scope.get("final_subdivision_set", set()))
    same_dev = False
    if subject.development_name and str(subject.development_name).strip():
        same_dev = df["development_name"].astype(str) == str(subject.development_name)
    return same_sub_scope | same_dev


def build_community_insights(subject: SubjectProfile, sales_df: pd.DataFrame, scope: Dict[str, set], as_of_date: str) -> dict:
    if sales_df.empty:
        return {
            "community_comp_count_12mo": 0,
            "ppsf_low": None,
            "ppsf_high": None,
            "ppsf_avg": None,
            "ppsf_median": None,
            "notes": "No sold comps available.",
            "top_price_drivers": {},
        }

    as_of = pd.Timestamp(as_of_date)
    df = sales_df.copy()
    df = df[_same_community_mask(df, subject, scope)]
    df = df[df["sold_date"].notna() & (df["sold_date"] <= as_of) & (df["sold_date"] >= (as_of - pd.DateOffset(months=12)))]
    df = df[df["sqft_living"].notna() & (df["sqft_living"] > 0) & df["sold_price"].notna() & (df["sold_price"] > 0)]
    if df.empty:
        return {
            "community_comp_count_12mo": 0,
            "ppsf_low": None,
            "ppsf_high": None,
            "ppsf_avg": None,
            "ppsf_median": None,
            "notes": "No same-community sold comps in last 12 months.",
            "top_price_drivers": {},
        }

    df["ppsf"] = df["sold_price"] / df["sqft_living"]
    # Clamp obvious data outliers so summary stats represent market reality.
    df = df[(df["ppsf"] >= 50) & (df["ppsf"] <= 2000)]
    if df.empty:
        return {
            "community_comp_count_12mo": 0,
            "ppsf_low": None,
            "ppsf_high": None,
            "ppsf_avg": None,
            "ppsf_median": None,
            "notes": "No same-community sold comps in last 12 months after PPSF quality filtering.",
            "top_price_drivers": {},
        }
    p25 = df["ppsf"].quantile(0.25)
    p75 = df["ppsf"].quantile(0.75)
    top = df[df["ppsf"] >= p75].copy()
    low = df[df["ppsf"] <= p25].copy()

    def pct_true(frame, col):
        if col not in frame.columns or frame.empty:
            return None
        vals = pd.to_numeric(frame[col], errors="coerce").fillna(0)
        return float((vals > 0).mean() * 100)

    drivers = {
        "top_vs_low_waterfront_pct": None,
        "top_vs_low_pool_pct": None,
        "top_vs_low_impact_glass_pct": None,
        "top_vs_low_large_lot_median_diff_pct": None,
        "remarks_keyword_lift_pct": {},
    }

    top_w = pct_true(top, "waterfront")
    low_w = pct_true(low, "waterfront")
    if top_w is not None and low_w is not None:
        drivers["top_vs_low_waterfront_pct"] = round(top_w - low_w, 1)

    top_p = pct_true(top, "private_pool")
    low_p = pct_true(low, "private_pool")
    if top_p is not None and low_p is not None:
        drivers["top_vs_low_pool_pct"] = round(top_p - low_p, 1)

    top_i = pct_true(top, "storm_protection_impact_glass")
    low_i = pct_true(low, "storm_protection_impact_glass")
    if top_i is not None and low_i is not None:
        drivers["top_vs_low_impact_glass_pct"] = round(top_i - low_i, 1)

    if "lot_sqft" in top.columns and "lot_sqft" in low.columns and not top.empty and not low.empty:
        t_series = pd.to_numeric(top["lot_sqft"], errors="coerce").dropna()
        l_series = pd.to_numeric(low["lot_sqft"], errors="coerce").dropna()
        t = t_series.median() if not t_series.empty else None
        l = l_series.median() if not l_series.empty else None
        if pd.notna(t) and pd.notna(l) and l > 0:
            drivers["top_vs_low_large_lot_median_diff_pct"] = round(((t - l) / l) * 100, 1)

    remarks_top = top.get("public_remarks", pd.Series(dtype=str)).fillna("").astype(str).str.lower()
    remarks_low = low.get("public_remarks", pd.Series(dtype=str)).fillna("").astype(str).str.lower()
    for key, pattern in KEYWORD_PATTERNS.items():
        top_pct = float(remarks_top.str.contains(pattern, regex=True, na=False).mean() * 100) if not remarks_top.empty else 0.0
        low_pct = float(remarks_low.str.contains(pattern, regex=True, na=False).mean() * 100) if not remarks_low.empty else 0.0
        drivers["remarks_keyword_lift_pct"][key] = round(top_pct - low_pct, 1)

    return {
        "community_comp_count_12mo": int(len(df)),
        "ppsf_low": round(float(df["ppsf"].min()), 2),
        "ppsf_high": round(float(df["ppsf"].max()), 2),
        "ppsf_avg": round(float(df["ppsf"].mean()), 2),
        "ppsf_median": round(float(df["ppsf"].median()), 2),
        "top_quartile_count": int(len(top)),
        "low_quartile_count": int(len(low)),
        "notes": "Same-community sales (last 12 months).",
        "top_price_drivers": drivers,
    }


def _same_property_group_mask(df: pd.DataFrame, subject: SubjectProfile) -> pd.Series:
    subject_type = (subject.property_type or "").upper()
    series = df["property_type"].fillna("").astype(str).str.upper()
    sf_types = {"SF", "SINGLE FAMILY", "SINGLE-FAMILY", "SINGLE FAMILY HOME"}
    if "SINGLE" in subject_type or subject_type == "SF":
        return series.isin(sf_types)
    return ~series.isin(sf_types)


def _monthly_series(df: pd.DataFrame, as_of_date: str, months: int = 12) -> list[dict]:
    if df.empty:
        return []
    as_of = pd.Timestamp(as_of_date)
    start = (as_of.replace(day=1) - pd.DateOffset(months=months - 1)).normalize()
    df = df.copy()
    df["sold_date"] = pd.to_datetime(df["sold_date"], errors="coerce")
    df = df[df["sold_date"].notna() & (df["sold_date"] >= start) & (df["sold_date"] <= as_of)]
    if df.empty:
        return []
    df["month"] = df["sold_date"].dt.to_period("M").dt.to_timestamp()
    df["ppsf"] = df["sold_price"] / df["sqft_living"]
    agg = (
        df.groupby("month")
        .agg(
            sold_count=("listing_number", "count"),
            median_sold_price=("sold_price", "median"),
            median_ppsf=("ppsf", "median"),
        )
        .reset_index()
    )

    month_index = pd.date_range(start=start, periods=months, freq="MS")
    agg = agg.set_index("month").reindex(month_index)
    agg["sold_count"] = agg["sold_count"].fillna(0).astype(int)
    out = []
    for idx, row in agg.iterrows():
        out.append(
            {
                "period": idx.strftime("%Y-%m"),
                "sold_count": int(row["sold_count"]),
                "median_sold_price": None if pd.isna(row["median_sold_price"]) else round(float(row["median_sold_price"]), 0),
                "median_ppsf": None if pd.isna(row["median_ppsf"]) else round(float(row["median_ppsf"]), 2),
            }
        )
    return out


def _direction_from_window(values, metric):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return "insufficient"
    first = float(vals[0])
    last = float(vals[-1])
    delta = last - first
    if metric == "sold_count":
        flat = abs(delta) <= 1.0
    else:
        denom = max(abs(first), 1.0)
        flat = abs(delta) / denom <= 0.02
    if flat:
        return "flat"
    return "up" if delta > 0 else "down"


def _volatility_flag(values, metric):
    vals = [v for v in values if v is not None]
    if len(vals) < 4:
        return False
    changes = []
    for i in range(1, len(vals)):
        prev = float(vals[i - 1])
        cur = float(vals[i])
        if metric == "sold_count":
            denom = max(prev, 1.0)
        else:
            denom = max(abs(prev), 1.0)
        changes.append(abs(cur - prev) / denom)
    if not changes:
        return False
    avg_change = sum(changes) / len(changes)
    threshold = 0.35 if metric == "sold_count" else 0.08
    return avg_change > threshold


def _trend_summary(monthly: list[dict]) -> dict:
    if not monthly:
        return {
            "window_months": 3,
            "sold_count_direction_3mo": "insufficient",
            "median_sold_price_direction_3mo": "insufficient",
            "median_ppsf_direction_3mo": "insufficient",
            "sold_count_volatile_6mo": False,
            "median_sold_price_volatile_6mo": False,
            "median_ppsf_volatile_6mo": False,
        }

    tail3 = monthly[-3:]
    tail6 = monthly[-6:]
    sold3 = [r.get("sold_count") for r in tail3]
    price3 = [r.get("median_sold_price") for r in tail3]
    ppsf3 = [r.get("median_ppsf") for r in tail3]
    sold6 = [r.get("sold_count") for r in tail6]
    price6 = [r.get("median_sold_price") for r in tail6]
    ppsf6 = [r.get("median_ppsf") for r in tail6]
    return {
        "window_months": 3,
        "sold_count_direction_3mo": _direction_from_window(sold3, "sold_count"),
        "median_sold_price_direction_3mo": _direction_from_window(price3, "median_sold_price"),
        "median_ppsf_direction_3mo": _direction_from_window(ppsf3, "median_ppsf"),
        "sold_count_volatile_6mo": _volatility_flag(sold6, "sold_count"),
        "median_sold_price_volatile_6mo": _volatility_flag(price6, "median_sold_price"),
        "median_ppsf_volatile_6mo": _volatility_flag(ppsf6, "median_ppsf"),
    }


def _trend_divergence_flags(community_summary: dict, surrounding_summary: dict) -> list[str]:
    flags = []
    checks = [
        ("sold_count_direction_3mo", "sold_count_direction"),
        ("median_sold_price_direction_3mo", "median_sold_price_direction"),
        ("median_ppsf_direction_3mo", "median_ppsf_direction"),
    ]
    for key, label in checks:
        c = community_summary.get(key)
        s = surrounding_summary.get(key)
        if c in ("up", "down") and s in ("up", "down") and c != s:
            flags.append(f"{label}_divergence")
    vol_checks = [
        ("sold_count_volatile_6mo", "sold_count_volatility_gap"),
        ("median_sold_price_volatile_6mo", "median_sold_price_volatility_gap"),
        ("median_ppsf_volatile_6mo", "median_ppsf_volatility_gap"),
    ]
    for key, label in vol_checks:
        c = bool(community_summary.get(key, False))
        s = bool(surrounding_summary.get(key, False))
        if c != s:
            flags.append(label)
    return flags


def build_closing_trends(subject: SubjectProfile, sales_df: pd.DataFrame, scope: Dict[str, set], as_of_date: str) -> dict:
    """Return monthly closings trend lines for community and surrounding context."""
    empty_summary = _trend_summary([])
    if sales_df.empty:
        return {
            "months": 12,
            "community_monthly": [],
            "surrounding_monthly": [],
            "community_trend_summary": empty_summary,
            "surrounding_trend_summary": empty_summary,
            "trend_divergence_flags": [],
            "notes": "No sales data available for trend lines.",
        }

    df = sales_df.copy()
    df = df[
        df["sold_date"].notna()
        & df["sold_price"].notna()
        & (df["sold_price"] > 0)
        & df["sqft_living"].notna()
        & (df["sqft_living"] > 0)
    ]
    if df.empty:
        return {
            "months": 12,
            "community_monthly": [],
            "surrounding_monthly": [],
            "community_trend_summary": empty_summary,
            "surrounding_trend_summary": empty_summary,
            "trend_divergence_flags": [],
            "notes": "No usable sold rows for trend lines.",
        }

    same_group = _same_property_group_mask(df, subject)
    same_community = _same_community_mask(df, subject, scope)
    same_city = True
    if subject.city and str(subject.city).strip():
        same_city = df["city"].astype(str) == str(subject.city)

    community_df = df[same_group & same_community].copy()
    surrounding_df = df[same_group & same_city & (~same_community)].copy()

    community_monthly = _monthly_series(community_df, as_of_date=as_of_date, months=12)
    surrounding_monthly = _monthly_series(surrounding_df, as_of_date=as_of_date, months=12)
    community_summary = _trend_summary(community_monthly)
    surrounding_summary = _trend_summary(surrounding_monthly)
    return {
        "months": 12,
        "community_monthly": community_monthly,
        "surrounding_monthly": surrounding_monthly,
        "community_trend_summary": community_summary,
        "surrounding_trend_summary": surrounding_summary,
        "trend_divergence_flags": _trend_divergence_flags(community_summary, surrounding_summary),
        "notes": "Community line is primary. Surrounding line is trend context only.",
    }
