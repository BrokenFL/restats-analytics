import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from property_type_utils import CONDO_TH_OTHER_VALUE, SINGLE_FAMILY_VALUE


def _canon_subdivision(value):
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text or text in {"NAN", "NONE", "NULL", "<NA>"}:
        return None
    return " ".join(text.split())


def _load_rows(db_file: str) -> pd.DataFrame:
    conn = sqlite3.connect(db_file)
    try:
        return pd.read_sql_query(
            """
            SELECT
                listing_number,
                pcn_10_digit,
                city,
                short_address,
                DATE(listing_date) AS listing_date,
                DATE(sold_date) AS sold_date,
                final_subdivision,
                property_type
            FROM listing_details
            WHERE listing_number NOT LIKE 'PBC-%'
            """,
            conn,
        )
    finally:
        conn.close()


def _summarize_subdivisions(
    historical_df: pd.DataFrame,
    min_rows: int,
    dominant_share_threshold: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    grouped = (
        historical_df.groupby(["final_subdivision", "property_type"], dropna=False)
        .size()
        .reset_index(name="row_count")
    )
    pivot = (
        grouped.pivot(index="final_subdivision", columns="property_type", values="row_count")
        .fillna(0)
        .reset_index()
    )
    for col in [SINGLE_FAMILY_VALUE, CONDO_TH_OTHER_VALUE]:
        if col not in pivot.columns:
            pivot[col] = 0

    pivot["historical_rows"] = pivot[SINGLE_FAMILY_VALUE] + pivot[CONDO_TH_OTHER_VALUE]
    pivot["historical_sf_rows"] = pivot[SINGLE_FAMILY_VALUE].astype(int)
    pivot["historical_condo_th_other_rows"] = pivot[CONDO_TH_OTHER_VALUE].astype(int)
    pivot["dominant_type"] = pivot.apply(
        lambda row: (
            SINGLE_FAMILY_VALUE
            if row["historical_sf_rows"] >= row["historical_condo_th_other_rows"]
            else CONDO_TH_OTHER_VALUE
        ),
        axis=1,
    )
    pivot["dominant_share"] = pivot.apply(
        lambda row: (
            max(row["historical_sf_rows"], row["historical_condo_th_other_rows"]) / row["historical_rows"]
            if row["historical_rows"]
            else 0.0
        ),
        axis=1,
    )
    pivot["distinct_historical_types"] = (
        (pivot["historical_sf_rows"] > 0).astype(int) + (pivot["historical_condo_th_other_rows"] > 0).astype(int)
    )

    defaults = pivot[
        (pivot["historical_rows"] >= min_rows) & (pivot["dominant_share"] >= dominant_share_threshold)
    ].copy()
    defaults["fallback_scope"] = "subdivision_default"

    mixed = pivot[
        (pivot["historical_rows"] >= min_rows) & (pivot["distinct_historical_types"] > 1)
    ].copy()
    mixed["needs_parcel_override_review"] = mixed["dominant_share"] < dominant_share_threshold

    sort_cols = ["historical_rows", "dominant_share", "final_subdivision"]
    defaults = defaults.sort_values(sort_cols, ascending=[False, False, True]).reset_index(drop=True)
    mixed = mixed.sort_values(sort_cols, ascending=[False, False, True]).reset_index(drop=True)
    return defaults, mixed


def _build_parcel_overrides(
    historical_df: pd.DataFrame,
    mixed_subdivisions_df: pd.DataFrame,
    min_rows: int,
    dominant_share_threshold: float,
) -> pd.DataFrame:
    if mixed_subdivisions_df.empty:
        return pd.DataFrame(
            columns=[
                "final_subdivision",
                "pcn_10_digit",
                "parcel_rows",
                "parcel_sf_rows",
                "parcel_condo_th_other_rows",
                "parcel_dominant_type",
                "parcel_dominant_share",
            ]
        )

    mixed_names = set(mixed_subdivisions_df["final_subdivision"].tolist())
    scoped = historical_df[
        historical_df["final_subdivision"].isin(mixed_names)
        & historical_df["pcn_10_digit"].notna()
        & (historical_df["pcn_10_digit"].astype(str).str.strip() != "")
    ].copy()
    if scoped.empty:
        return pd.DataFrame(
            columns=[
                "final_subdivision",
                "pcn_10_digit",
                "parcel_rows",
                "parcel_sf_rows",
                "parcel_condo_th_other_rows",
                "parcel_dominant_type",
                "parcel_dominant_share",
            ]
        )

    grouped = (
        scoped.groupby(["final_subdivision", "pcn_10_digit", "property_type"], dropna=False)
        .size()
        .reset_index(name="row_count")
    )
    pivot = (
        grouped.pivot(index=["final_subdivision", "pcn_10_digit"], columns="property_type", values="row_count")
        .fillna(0)
        .reset_index()
    )
    for col in [SINGLE_FAMILY_VALUE, CONDO_TH_OTHER_VALUE]:
        if col not in pivot.columns:
            pivot[col] = 0

    pivot["parcel_rows"] = pivot[SINGLE_FAMILY_VALUE] + pivot[CONDO_TH_OTHER_VALUE]
    pivot["parcel_sf_rows"] = pivot[SINGLE_FAMILY_VALUE].astype(int)
    pivot["parcel_condo_th_other_rows"] = pivot[CONDO_TH_OTHER_VALUE].astype(int)
    pivot["parcel_dominant_type"] = pivot.apply(
        lambda row: (
            SINGLE_FAMILY_VALUE
            if row["parcel_sf_rows"] >= row["parcel_condo_th_other_rows"]
            else CONDO_TH_OTHER_VALUE
        ),
        axis=1,
    )
    pivot["parcel_dominant_share"] = pivot.apply(
        lambda row: (
            max(row["parcel_sf_rows"], row["parcel_condo_th_other_rows"]) / row["parcel_rows"]
            if row["parcel_rows"]
            else 0.0
        ),
        axis=1,
    )
    overrides = pivot[
        (pivot["parcel_rows"] >= min_rows) & (pivot["parcel_dominant_share"] >= dominant_share_threshold)
    ].copy()
    return overrides.sort_values(
        ["parcel_rows", "parcel_dominant_share", "final_subdivision", "pcn_10_digit"],
        ascending=[False, False, True, True],
    ).reset_index(drop=True)


def _build_recent_candidates(
    recent_df: pd.DataFrame,
    subdivision_defaults_df: pd.DataFrame,
    parcel_overrides_df: pd.DataFrame,
) -> pd.DataFrame:
    recent = recent_df.copy()
    recent = recent[recent["property_type"] == CONDO_TH_OTHER_VALUE].copy()
    if recent.empty:
        return pd.DataFrame(
            columns=[
                "listing_number",
                "listing_date",
                "sold_date",
                "city",
                "short_address",
                "final_subdivision",
                "pcn_10_digit",
                "current_property_type",
                "parcel_override_type",
                "subdivision_default_type",
                "recommended_property_type",
                "recommendation_source",
            ]
        )

    subdivision_defaults = subdivision_defaults_df[
        ["final_subdivision", "dominant_type", "dominant_share", "historical_rows"]
    ].rename(
        columns={
            "dominant_type": "subdivision_default_type",
            "dominant_share": "subdivision_default_share",
            "historical_rows": "subdivision_default_rows",
        }
    )
    parcel_overrides = parcel_overrides_df[
        ["final_subdivision", "pcn_10_digit", "parcel_dominant_type", "parcel_dominant_share", "parcel_rows"]
    ].rename(columns={"parcel_dominant_type": "parcel_override_type"})

    recent = recent.merge(subdivision_defaults, how="left", on="final_subdivision")
    recent = recent.merge(parcel_overrides, how="left", on=["final_subdivision", "pcn_10_digit"])
    recent["current_property_type"] = recent["property_type"]
    recent["recommended_property_type"] = recent["parcel_override_type"].combine_first(
        recent["subdivision_default_type"]
    )
    recent["recommendation_source"] = recent.apply(
        lambda row: (
            "parcel_override"
            if pd.notna(row["parcel_override_type"])
            else "subdivision_default"
            if pd.notna(row["subdivision_default_type"])
            else "unresolved"
        ),
        axis=1,
    )
    return recent[
        [
            "listing_number",
            "listing_date",
            "sold_date",
            "city",
            "short_address",
            "final_subdivision",
            "pcn_10_digit",
            "current_property_type",
            "parcel_override_type",
            "subdivision_default_type",
            "recommended_property_type",
            "recommendation_source",
        ]
    ].sort_values(["recommendation_source", "listing_date", "listing_number"], ascending=[True, False, True])


def main():
    parser = argparse.ArgumentParser(description="Audit historical property types to derive subdivision defaults and parcel overrides.")
    parser.add_argument("--db-file", default=str(PROJECT_ROOT / "mls.db"))
    parser.add_argument("--cutover-date", default="2026-03-16")
    parser.add_argument("--min-subdivision-rows", type=int, default=5)
    parser.add_argument("--subdivision-threshold", type=float, default=0.85)
    parser.add_argument("--min-parcel-rows", type=int, default=2)
    parser.add_argument("--parcel-threshold", type=float, default=0.90)
    parser.add_argument(
        "--defaults-csv-path",
        default=str(PROJECT_ROOT / "output" / "audits" / "property_type_subdivision_defaults.csv"),
    )
    parser.add_argument(
        "--mixed-csv-path",
        default=str(PROJECT_ROOT / "output" / "audits" / "property_type_mixed_subdivisions.csv"),
    )
    parser.add_argument(
        "--parcel-csv-path",
        default=str(PROJECT_ROOT / "output" / "audits" / "property_type_parcel_override_candidates.csv"),
    )
    parser.add_argument(
        "--recent-csv-path",
        default=str(PROJECT_ROOT / "output" / "audits" / "property_type_recent_recommendations.csv"),
    )
    parser.add_argument(
        "--json-path",
        default=str(PROJECT_ROOT / "output" / "audits" / "property_type_fallback_audit_latest.json"),
    )
    args = parser.parse_args()

    for path in [
        args.defaults_csv_path,
        args.mixed_csv_path,
        args.parcel_csv_path,
        args.recent_csv_path,
        args.json_path,
    ]:
        os.makedirs(os.path.dirname(path), exist_ok=True)

    df = _load_rows(str(Path(args.db_file).expanduser().resolve()))
    df["final_subdivision"] = df["final_subdivision"].map(_canon_subdivision)
    df["pcn_10_digit"] = df["pcn_10_digit"].astype(str).str.strip()
    df.loc[df["pcn_10_digit"].isin(["", "nan", "None", "<NA>"]), "pcn_10_digit"] = pd.NA

    scoped = df[
        df["final_subdivision"].notna()
        & df["property_type"].isin([SINGLE_FAMILY_VALUE, CONDO_TH_OTHER_VALUE])
        & df["listing_date"].notna()
    ].copy()

    historical_df = scoped[scoped["listing_date"] < args.cutover_date].copy()
    recent_df = scoped[scoped["listing_date"] >= args.cutover_date].copy()

    defaults_df, mixed_df = _summarize_subdivisions(
        historical_df,
        min_rows=args.min_subdivision_rows,
        dominant_share_threshold=args.subdivision_threshold,
    )
    parcel_df = _build_parcel_overrides(
        historical_df,
        mixed_df,
        min_rows=args.min_parcel_rows,
        dominant_share_threshold=args.parcel_threshold,
    )
    recent_candidates_df = _build_recent_candidates(recent_df, defaults_df, parcel_df)

    defaults_df.to_csv(args.defaults_csv_path, index=False)
    mixed_df.to_csv(args.mixed_csv_path, index=False)
    parcel_df.to_csv(args.parcel_csv_path, index=False)
    recent_candidates_df.to_csv(args.recent_csv_path, index=False)

    summary = {
        "cutover_date": args.cutover_date,
        "historical_rows": int(len(historical_df)),
        "recent_rows": int(len(recent_df)),
        "subdivision_defaults": int(len(defaults_df)),
        "mixed_subdivisions": int(len(mixed_df)),
        "parcel_override_candidates": int(len(parcel_df)),
        "recent_condo_th_other_rows": int(len(recent_candidates_df)),
        "recent_recommendation_counts": {
            key: int(value)
            for key, value in recent_candidates_df["recommendation_source"].value_counts(dropna=False).to_dict().items()
        },
        "defaults_csv_path": args.defaults_csv_path,
        "mixed_csv_path": args.mixed_csv_path,
        "parcel_csv_path": args.parcel_csv_path,
        "recent_csv_path": args.recent_csv_path,
    }
    with open(args.json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
