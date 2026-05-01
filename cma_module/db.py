import os
import sqlite3
from typing import Optional

import pandas as pd

from .models import SubjectProfile


def db_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    return os.path.join(root, "mls.db")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _to_subject(row: sqlite3.Row) -> SubjectProfile:
    d = dict(row)
    baths_total = d.get("baths_total")
    if baths_total is None:
        try:
            full = float(d.get("baths_full")) if d.get("baths_full") is not None else 0.0
            half = float(d.get("baths_half")) if d.get("baths_half") is not None else 0.0
            calc = full + (half * 0.5)
            baths_total = calc if calc > 0 else None
        except Exception:
            baths_total = None
    return SubjectProfile(
        listing_number=d.get("listing_number", ""),
        status=d.get("status"),
        calculated_status=d.get("calculated_status"),
        parcel_id=d.get("parcel_id", "") or "",
        pcn_10_digit=d.get("pcn_10_digit", "") or "",
        city=d.get("city"),
        geo_zone=d.get("geo_zone"),
        property_type=d.get("property_type"),
        final_subdivision=d.get("final_subdivision"),
        development_name=d.get("development_name"),
        short_address=d.get("short_address"),
        geo_lat=d.get("geo_lat"),
        geo_lon=d.get("geo_lon"),
        sqft_living=d.get("sqft_living"),
        lot_sqft=d.get("lot_sqft"),
        total_bedrooms=d.get("total_bedrooms"),
        baths_total=baths_total,
        year_built=d.get("year_built"),
        unit_floor=d.get("unit_floor"),
        total_floors_stories=d.get("total_floors_stories"),
        waterfront=d.get("waterfront"),
        private_pool=d.get("private_pool"),
        storm_protection_impact_glass=d.get("storm_protection_impact_glass"),
        construction_cbs=d.get("construction_cbs"),
        garage_spaces=d.get("garage_spaces"),
        year_roof_installed=d.get("year_roof_installed"),
        public_remarks=d.get("public_remarks"),
        sold_date=d.get("sold_date"),
        sold_price=d.get("sold_price"),
        list_price=d.get("list_price"),
        hoa_poa_coa_monthly=d.get("hoa_poa_coa_monthly"),
        membership_fee=d.get("membership_fee"),
    )


def get_subject_by_parcel(parcel: str, as_of_date: Optional[str] = None) -> SubjectProfile:
    p = str(parcel).replace("-", "").strip()
    if not p:
        raise ValueError("Parcel is required.")
    with connect() as conn:
        cur = conn.cursor()
        if as_of_date:
            cur.execute(
                """
                SELECT *
                FROM listing_details
                WHERE REPLACE(COALESCE(parcel_id,''), '-', '') = ?
                  AND (DATE(sold_date) <= DATE(?) OR sold_date IS NULL)
                ORDER BY DATE(COALESCE(sold_date, listing_date)) DESC, listing_number DESC
                LIMIT 1
                """,
                (p, as_of_date),
            )
        else:
            cur.execute(
                """
                SELECT *
                FROM listing_details
                WHERE REPLACE(COALESCE(parcel_id,''), '-', '') = ?
                ORDER BY DATE(COALESCE(sold_date, listing_date)) DESC, listing_number DESC
                LIMIT 1
                """,
                (p,),
            )
        row = cur.fetchone()
    if not row:
        raise ValueError(f"No subject found in DB for parcel: {parcel}")
    return _to_subject(row)


def pull_candidate_sales(as_of_date: str, months_back: int = 24) -> pd.DataFrame:
    with connect() as conn:
        df = pd.read_sql_query(
            """
            SELECT
                listing_number, parcel_id, pcn_10_digit, city, geo_zone, property_type,
                final_subdivision, development_name, short_address, geo_lat, geo_lon,
                sqft_living, lot_sqft, total_bedrooms, baths_total, year_built,
                unit_floor, total_floors_stories, waterfront, private_pool,
                storm_protection_impact_glass, construction_cbs, garage_spaces, year_roof_installed,
                public_remarks, sold_date, sold_price, list_price,
                CASE WHEN listing_number LIKE 'PBC-%' THEN 'OFF_MARKET' ELSE 'MLS' END AS source_type
            FROM listing_details
            WHERE sold_date IS NOT NULL
              AND sold_price IS NOT NULL
              AND sold_price > 0
              AND DATE(sold_date) >= DATE(?, ?)
              AND DATE(sold_date) <= DATE(?)
            """,
            conn,
            params=(as_of_date, f"-{months_back} months", as_of_date),
        )
    for c in ["sold_date"]:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in [
        "sold_price", "list_price", "sqft_living", "lot_sqft", "baths_total",
        "garage_spaces", "geo_lat", "geo_lon", "unit_floor"
    ]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ["total_bedrooms", "year_built", "total_floors_stories", "waterfront", "private_pool", "storm_protection_impact_glass"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def pull_market_activity(subject: SubjectProfile, as_of_date: str) -> dict:
    """Surrounding-area momentum: same city + (same geo_zone OR within ~1mi) + same broad property group."""
    def property_group_sql():
        p = (subject.property_type or "").upper()
        if "SINGLE" in p or p == "SF":
            return "UPPER(COALESCE(property_type,'')) IN ('SF','SINGLE FAMILY','SINGLE-FAMILY','SINGLE FAMILY HOME')"
        return "UPPER(COALESCE(property_type,'')) NOT IN ('SF','SINGLE FAMILY','SINGLE-FAMILY','SINGLE FAMILY HOME')"

    city = subject.city or ""
    zone = subject.geo_zone or ""
    lat = subject.geo_lat
    lon = subject.geo_lon
    with connect() as conn:
        cur = conn.cursor()
        geo_clause = "AND geo_zone = ?"
        params = [city, as_of_date, zone]
        if lat is not None and lon is not None:
            # rough 1-mile-ish box fallback around subject
            geo_clause = """
            AND (
                geo_zone = ?
                OR (
                    geo_lat BETWEEN ? AND ?
                    AND geo_lon BETWEEN ? AND ?
                )
            )
            """
            lat_d = 0.018
            lon_d = 0.018
            params = [city, as_of_date, zone, lat - lat_d, lat + lat_d, lon - lon_d, lon + lon_d]

        pg_sql = property_group_sql()
        cur.execute(
            f"""
            SELECT COUNT(*), AVG(sold_price), AVG(sold_price / NULLIF(sqft_living,0))
            FROM listing_details
            WHERE city = ?
              AND DATE(sold_date) >= DATE(?, '-60 days')
              AND DATE(sold_date) <= DATE(?)
              AND {pg_sql}
              {geo_clause}
            """,
            [params[0], params[1], as_of_date, *params[2:]],
        )
        sold_60_count, sold_60_avg_price, sold_60_avg_ppsf = cur.fetchone()

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM listing_details
            WHERE city = ?
              AND DATE(under_contract_date) >= DATE(?, '-60 days')
              AND DATE(under_contract_date) <= DATE(?)
              AND {pg_sql}
              {geo_clause}
            """,
            [params[0], params[1], as_of_date, *params[2:]],
        )
        pending_60 = cur.fetchone()[0]

    return {
        "sold_60_count": int(sold_60_count or 0),
        "sold_60_avg_price": float(sold_60_avg_price) if sold_60_avg_price else None,
        "sold_60_avg_ppsf": float(sold_60_avg_ppsf) if sold_60_avg_ppsf else None,
        "pending_60_count": int(pending_60 or 0),
    }


def pull_surrounding_discount_metrics(subject: SubjectProfile, as_of_date: str) -> dict:
    """
    Surrounding-area listing discount metric:
    - same city
    - same broad property group
    - same geo_zone OR ~1mi fallback
    Uses 180-day source if sample >=5 else 365-day fallback.
    """
    def property_group_sql():
        p = (subject.property_type or "").upper()
        if "SINGLE" in p or p == "SF":
            return "UPPER(COALESCE(property_type,'')) IN ('SF','SINGLE FAMILY','SINGLE-FAMILY','SINGLE FAMILY HOME')"
        return "UPPER(COALESCE(property_type,'')) NOT IN ('SF','SINGLE FAMILY','SINGLE-FAMILY','SINGLE FAMILY HOME')"

    city = subject.city or ""
    zone = subject.geo_zone or ""
    lat = subject.geo_lat
    lon = subject.geo_lon
    as_of = pd.Timestamp(as_of_date)
    with connect() as conn:
        cur = conn.cursor()
        geo_clause = "AND geo_zone = ?"
        params = [city, zone]
        if lat is not None and lon is not None:
            geo_clause = """
            AND (
                geo_zone = ?
                OR (
                    geo_lat BETWEEN ? AND ?
                    AND geo_lon BETWEEN ? AND ?
                )
            )
            """
            lat_d = 0.018
            lon_d = 0.018
            params = [city, zone, lat - lat_d, lat + lat_d, lon - lon_d, lon + lon_d]

        pg_sql = property_group_sql()
        sold_df = pd.read_sql_query(
            f"""
            SELECT sold_date, list_price, sold_price
            FROM listing_details
            WHERE city = ?
              AND sold_date IS NOT NULL
              AND list_price > 0
              AND sold_price > 0
              AND DATE(sold_date) <= DATE(?)
              AND {pg_sql}
              {geo_clause}
            """,
            conn,
            params=[params[0], as_of_date, *params[1:]],
        )

    if sold_df.empty:
        return {
            "surrounding_median_listing_discount_pct": None,
            "surrounding_discount_source_days": None,
            "surrounding_discount_source_comp_count": 0,
        }

    sold_df["sold_date"] = pd.to_datetime(sold_df["sold_date"], errors="coerce")
    sold_df["sold_price"] = pd.to_numeric(sold_df["sold_price"], errors="coerce")
    sold_df["list_price"] = pd.to_numeric(sold_df["list_price"], errors="coerce")
    sold_df = sold_df[
        sold_df["sold_date"].notna()
        & (sold_df["sold_date"] <= as_of)
        & (sold_df["sold_price"] > 0)
        & (sold_df["list_price"] > 0)
    ]
    if sold_df.empty:
        return {
            "surrounding_median_listing_discount_pct": None,
            "surrounding_discount_source_days": None,
            "surrounding_discount_source_comp_count": 0,
        }

    sold_180 = sold_df[sold_df["sold_date"] >= (as_of - pd.Timedelta(days=180))].copy()
    source_df = sold_180 if len(sold_180) >= 5 else sold_df.copy()
    source_days = 180 if len(sold_180) >= 5 else 365
    source_df["listing_discount_pct"] = (source_df["list_price"] - source_df["sold_price"]) / source_df["list_price"]
    source_df["listing_discount_pct"] = source_df["listing_discount_pct"].clip(lower=-0.10, upper=0.30)
    median_discount = float(source_df["listing_discount_pct"].median()) if not source_df.empty else None
    return {
        "surrounding_median_listing_discount_pct": None if median_discount is None else round(median_discount * 100, 2),
        "surrounding_discount_source_days": source_days,
        "surrounding_discount_source_comp_count": int(len(source_df)),
    }


def build_pending_pressure_guardrail(
    subject: SubjectProfile,
    scope: dict,
    as_of_date: str,
    pending_projection: Optional[dict] = None,
    surrounding_discount_metrics: Optional[dict] = None,
    surrounding_context: Optional[dict] = None,
) -> dict:
    """
    Pending-pressure guardrail:
    produces a cap/floor for recommended value adjustment percent vs baseline.
    Does not force adjustment, only bounds extreme outputs.
    """
    pending_projection = pending_projection or pull_pending_projection(subject, scope, as_of_date)
    surrounding_discount_metrics = surrounding_discount_metrics or pull_surrounding_discount_metrics(subject, as_of_date)
    surrounding_context = surrounding_context or pull_market_activity(subject, as_of_date)

    sold_60 = int((surrounding_context or {}).get("sold_60_count") or 0)
    pending_60 = int((surrounding_context or {}).get("pending_60_count") or 0)
    pending_to_sold_ratio = float(pending_60 / sold_60) if sold_60 > 0 else (float(pending_60) if pending_60 > 0 else 0.0)

    comm_discount = (pending_projection or {}).get("recent_median_listing_discount_pct")
    surr_discount = (surrounding_discount_metrics or {}).get("surrounding_median_listing_discount_pct")
    discount_delta_pct = None
    if comm_discount is not None and surr_discount is not None:
        discount_delta_pct = float(comm_discount) - float(surr_discount)

    # Conservative defaults. Cap/floor are adjustment-percent bounds vs baseline value.
    state = "neutral"
    cap_pct = 6.0
    floor_pct = -8.0
    notes = []

    if pending_to_sold_ratio >= 1.25 and (discount_delta_pct is None or discount_delta_pct <= -1.5):
        state = "tight"
        cap_pct = 8.0
        floor_pct = -5.0
    elif pending_to_sold_ratio <= 0.70 and (discount_delta_pct is None or discount_delta_pct >= 1.5):
        state = "soft"
        cap_pct = 4.0
        floor_pct = -12.0

    notes.append(f"pending_to_sold_ratio={pending_to_sold_ratio:.2f}")
    if discount_delta_pct is None:
        notes.append("discount_delta_pct=N/A")
    else:
        notes.append(f"discount_delta_pct={discount_delta_pct:.2f}")

    return {
        "pending_pressure_state": state,
        "recommended_value_cap_pct": round(cap_pct, 2),
        "recommended_value_floor_pct": round(floor_pct, 2),
        "guardrail_notes": " | ".join(notes),
        "inputs": {
            "pending_60_count": pending_60,
            "sold_60_count": sold_60,
            "pending_to_sold_ratio": round(pending_to_sold_ratio, 4),
            "community_discount_pct": comm_discount,
            "surrounding_discount_pct": surr_discount,
            "discount_delta_pct": None if discount_delta_pct is None else round(discount_delta_pct, 4),
        },
    }


def pull_pending_projection(subject: SubjectProfile, scope: dict, as_of_date: str) -> dict:
    """Estimate pending close prices from recent same-community listing discount."""

    def property_group_sql():
        p = (subject.property_type or "").upper()
        if "SINGLE" in p or p == "SF":
            return "UPPER(COALESCE(property_type,'')) IN ('SF','SINGLE FAMILY','SINGLE-FAMILY','SINGLE FAMILY HOME')"
        return "UPPER(COALESCE(property_type,'')) NOT IN ('SF','SINGLE FAMILY','SINGLE-FAMILY','SINGLE FAMILY HOME')"

    def same_community_mask(df: pd.DataFrame) -> pd.Series:
        sub_set = scope.get("final_subdivision_set", set()) or set()
        same_sub = df["final_subdivision"].isin(sub_set)
        same_dev = False
        if subject.development_name and str(subject.development_name).strip():
            same_dev = df["development_name"].astype(str) == str(subject.development_name)
        return same_sub | same_dev

    city = subject.city or ""
    pg_sql = property_group_sql()
    with connect() as conn:
        sold_df = pd.read_sql_query(
            f"""
            SELECT sold_price, list_price, sold_date, final_subdivision, development_name
            FROM listing_details
            WHERE city = ?
              AND sold_date IS NOT NULL
              AND sold_price > 0
              AND list_price > 0
              AND DATE(sold_date) >= DATE(?, '-365 days')
              AND DATE(sold_date) <= DATE(?)
              AND {pg_sql}
            """,
            conn,
            params=(city, as_of_date, as_of_date),
        )
        pending_df = pd.read_sql_query(
            f"""
            SELECT
                listing_number, short_address, list_price, status, calculated_status,
                final_subdivision, development_name, under_contract_date, listing_date, sold_date
            FROM listing_details
            WHERE city = ?
              AND list_price > 0
              AND DATE(listing_date) <= DATE(?)
              AND (sold_date IS NULL OR DATE(sold_date) > DATE(?))
              AND (
                    under_contract_date IS NOT NULL
                    OR UPPER(COALESCE(status,'')) LIKE '%PENDING%'
                    OR UPPER(COALESCE(status,'')) LIKE '%CONTRACT%'
                    OR UPPER(COALESCE(calculated_status,'')) LIKE '%PENDING%'
                    OR UPPER(COALESCE(calculated_status,'')) LIKE '%CONTRACT%'
                  )
              AND {pg_sql}
            """,
            conn,
            params=(city, as_of_date, as_of_date),
        )

    if sold_df.empty:
        return {
            "pending_count": 0 if pending_df.empty else int(len(pending_df)),
            "recent_median_listing_discount_pct": None,
            "discount_source_days": None,
            "discount_source_comp_count": 0,
            "projected_pending_close_total": None,
            "projected_pending_close_median": None,
            "projected_examples": [],
        }

    sold_df["sold_date"] = pd.to_datetime(sold_df["sold_date"], errors="coerce")
    sold_df["sold_price"] = pd.to_numeric(sold_df["sold_price"], errors="coerce")
    sold_df["list_price"] = pd.to_numeric(sold_df["list_price"], errors="coerce")
    sold_df = sold_df[sold_df["sold_date"].notna() & (sold_df["sold_price"] > 0) & (sold_df["list_price"] > 0)]
    sold_df = sold_df[same_community_mask(sold_df)]

    if sold_df.empty:
        return {
            "pending_count": 0 if pending_df.empty else int(len(pending_df)),
            "recent_median_listing_discount_pct": None,
            "discount_source_days": None,
            "discount_source_comp_count": 0,
            "projected_pending_close_total": None,
            "projected_pending_close_median": None,
            "projected_examples": [],
        }

    as_of = pd.Timestamp(as_of_date)
    sold_180 = sold_df[sold_df["sold_date"] >= (as_of - pd.Timedelta(days=180))].copy()
    sold_for_discount = sold_180 if len(sold_180) >= 5 else sold_df.copy()
    discount_source_days = 180 if len(sold_180) >= 5 else 365

    sold_for_discount["listing_discount_pct"] = (
        (sold_for_discount["list_price"] - sold_for_discount["sold_price"]) / sold_for_discount["list_price"]
    )
    # Keep realistic range and prevent one bad row from breaking projections.
    sold_for_discount["listing_discount_pct"] = sold_for_discount["listing_discount_pct"].clip(lower=-0.10, upper=0.30)
    median_discount = float(sold_for_discount["listing_discount_pct"].median())

    if pending_df.empty:
        return {
            "pending_count": 0,
            "recent_median_listing_discount_pct": round(median_discount * 100, 2),
            "discount_source_days": discount_source_days,
            "discount_source_comp_count": int(len(sold_for_discount)),
            "projected_pending_close_total": 0.0,
            "projected_pending_close_median": 0.0,
            "projected_examples": [],
        }

    pending_df["list_price"] = pd.to_numeric(pending_df["list_price"], errors="coerce")
    pending_df = pending_df[pending_df["list_price"].notna() & (pending_df["list_price"] > 0)]
    pending_df = pending_df[same_community_mask(pending_df)]
    if pending_df.empty:
        return {
            "pending_count": 0,
            "recent_median_listing_discount_pct": round(median_discount * 100, 2),
            "discount_source_days": discount_source_days,
            "discount_source_comp_count": int(len(sold_for_discount)),
            "projected_pending_close_total": 0.0,
            "projected_pending_close_median": 0.0,
            "projected_examples": [],
        }

    pending_df["projected_close_price"] = pending_df["list_price"] * (1.0 - median_discount)
    pending_df = pending_df.sort_values("projected_close_price", ascending=False)

    examples = []
    for _, row in pending_df.head(10).iterrows():
        examples.append(
            {
                "listing_number": str(row.get("listing_number", "")),
                "short_address": row.get("short_address"),
                "list_price": round(float(row["list_price"]), 0),
                "projected_close_price": round(float(row["projected_close_price"]), 0),
                "status": row.get("status"),
                "calculated_status": row.get("calculated_status"),
            }
        )

    return {
        "pending_count": int(len(pending_df)),
        "recent_median_listing_discount_pct": round(median_discount * 100, 2),
        "discount_source_days": discount_source_days,
        "discount_source_comp_count": int(len(sold_for_discount)),
        "projected_pending_close_total": round(float(pending_df["projected_close_price"].sum()), 0),
        "projected_pending_close_median": round(float(pending_df["projected_close_price"].median()), 0),
        "projected_examples": examples,
    }
