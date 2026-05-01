"""
Compare legacy analytics metrics vs new API report summary for parity checks.

Current parity focus:
- monthly
- quarterly
- annual
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
import data_analysis_functions as daf
from api.main import market_report_summary, _resolve_report_window

DB_FILE = str(PROJECT_ROOT / "mls.db")


def _to_float(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
        return float(v)
    except Exception:
        return None


def _last_value(df, col):
    if df is None or df.empty or col not in df.columns:
        return None
    return _to_float(df.iloc[-1][col])


def _apply_filters(df, city=None, subdivision=None, geo_zone=None, property_group="ALL"):
    out = df.copy()
    if city:
        out = out[out["city"] == city]
    if subdivision:
        out = out[out["final_subdivision"] == subdivision]
    if geo_zone:
        out = out[out["geo_zone"] == geo_zone]
    if property_group == "SINGLE_FAMILY":
        out = out[out["property_type"] == "Single Family Home"]
    elif property_group == "TOWNHOME_CONDO":
        out = out[out["property_type"] == "Condo/TH/Other"]
    return out


def _legacy_metrics(df, freq, start_iso, end_iso):
    metrics = {}
    metrics["sold_count"] = _last_value(daf.sales_count(df, freq, start_iso, end_iso), "Sales Count")
    metrics["total_sales_volume"] = _last_value(daf.total_sales_volume(df, freq, start_iso, end_iso), "Total Sales Volume")
    metrics["median_sold_price"] = _last_value(daf.median_sold_price(df, freq, start_iso, end_iso), "Median Sold Price")
    metrics["new_listings"] = _last_value(daf.new_listings(df, freq, start_iso, end_iso), "New Listings")
    metrics["pending_sales"] = _last_value(daf.pending_sales(df, freq, start_iso, end_iso), "Pending Sales")
    metrics["active_inventory"] = _last_value(daf.active_inventory(df, freq, start_iso, end_iso), "Active Inventory")
    metrics["months_supply"] = _last_value(daf.months_supply(df, freq, start_iso, end_iso), "Months Supply")
    metrics["median_dom"] = _last_value(daf.median_dom(df, freq, start_iso, end_iso), "Median DOM")
    metrics["median_listing_discount"] = _last_value(daf.listing_discount(df, freq, start_iso, end_iso), "Listing Discount")
    return metrics


def _pct_diff(new_v, old_v):
    if new_v is None or old_v is None or old_v == 0:
        return None
    return ((new_v - old_v) / old_v) * 100


def main():
    parser = argparse.ArgumentParser(description="Parity check: legacy analytics vs new API report summary.")
    parser.add_argument("--mode", choices=["monthly", "quarterly", "annual"], required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, default=None)
    parser.add_argument("--quarter", type=int, default=None)
    parser.add_argument("--city", default=None)
    parser.add_argument("--subdivision", default=None)
    parser.add_argument("--geo-zone", default=None)
    parser.add_argument("--property-group", choices=["ALL", "SINGLE_FAMILY", "TOWNHOME_CONDO"], default="ALL")
    parser.add_argument("--db-file", default=DB_FILE)
    args = parser.parse_args()

    if args.mode == "monthly" and not args.month:
        parser.error("--month is required for monthly mode")
    if args.mode == "quarterly" and not args.quarter:
        parser.error("--quarter is required for quarterly mode")

    conn = sqlite3.connect(args.db_file)
    df = pd.read_sql_query("SELECT * FROM listing_details", conn)
    conn.close()

    for c in ["listing_date", "effective_active_end_date", "under_contract_date", "sold_date", "cancel_date", "withdrawn_date", "status_change_date", "temp_off_market_date", "expiration_date", "fallthrough_date"]:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in ["sold_price", "list_price", "original_list_price", "sqft_living", "days_on_market", "cumulative_dom"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    filtered = _apply_filters(
        df,
        city=args.city,
        subdivision=args.subdivision,
        geo_zone=args.geo_zone,
        property_group=args.property_group,
    )

    report_mode = args.mode if args.mode != "annual" else "annual"
    start_iso, end_iso, _, _, label = _resolve_report_window(
        report_mode=report_mode,
        period_days=30,
        ref_year=args.year,
        ref_month=args.month,
        ref_quarter=args.quarter,
        start_date=None,
        end_date=None,
    )
    freq_map = {"monthly": "monthly", "quarterly": "quarterly", "annual": "annually"}
    legacy = _legacy_metrics(filtered, freq_map[args.mode], start_iso, end_iso)

    api_summary = market_report_summary(
        report_mode=report_mode,
        period_days=30,
        ref_year=args.year,
        ref_month=args.month,
        ref_quarter=args.quarter,
        start_date=None,
        end_date=None,
        city=args.city,
        final_subdivision=args.subdivision,
        property_type=None,
        geo_zone=args.geo_zone,
        property_group=args.property_group,
    )["current"]

    compare_keys = [
        "sold_count",
        "total_sales_volume",
        "median_sold_price",
        "new_listings",
        "pending_sales",
        "active_inventory",
        "months_supply",
        "median_dom",
        "median_listing_discount",
    ]

    print("\n=== Dashboard Parity Check ===")
    print(f"Period: {label} ({start_iso} to {end_iso})")
    print(f"Filters: city={args.city or 'ALL'}, subdivision={args.subdivision or 'ALL'}, geo_zone={args.geo_zone or 'ALL'}, property_group={args.property_group}")
    print("")
    print(f"{'Metric':30} {'Legacy':>14} {'New API':>14} {'Diff%':>10}")
    print("-" * 72)
    for k in compare_keys:
        old_v = _to_float(legacy.get(k))
        new_v = _to_float(api_summary.get(k))
        diff = _pct_diff(new_v, old_v)
        old_s = "N/A" if old_v is None else f"{old_v:,.2f}"
        new_s = "N/A" if new_v is None else f"{new_v:,.2f}"
        diff_s = "N/A" if diff is None else f"{diff:,.2f}%"
        print(f"{k:30} {old_s:>14} {new_s:>14} {diff_s:>10}")


if __name__ == "__main__":
    main()
