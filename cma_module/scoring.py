from datetime import date
from math import atan2, cos, radians, sin, sqrt
from typing import Dict, List, Tuple

import pandas as pd

from .models import CompScore, SubjectProfile

MAX_SQFT_DIFF = 0.30


def _is_single_family_type(value: object) -> bool:
    v = str(value or "").strip().upper()
    return v in {"SF", "SINGLE FAMILY", "SINGLE-FAMILY", "SINGLE FAMILY HOME"}


def _same_property_group(subject_type: object, comp_type: object) -> bool:
    # Hard guardrail: do not cross-comp Single Family with Condo/TH/Other.
    return _is_single_family_type(subject_type) == _is_single_family_type(comp_type)


def _distance_miles(lat1, lon1, lat2, lon2):
    if any(pd.isna(x) for x in [lat1, lon1, lat2, lon2]):
        return None
    r = 3958.8
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def _recency_multiplier(sold_date: pd.Timestamp, as_of: pd.Timestamp) -> float:
    days = max((as_of - sold_date).days, 0)
    if days <= 90:
        return 1.05
    if days <= 183:
        return 1.00
    if days <= 365:
        return 0.93
    if days <= 548:
        return 0.86
    return 0.78


def _is_same_community(subject: SubjectProfile, row: pd.Series) -> bool:
    same_sub = bool(subject.final_subdivision and row.get("final_subdivision") == subject.final_subdivision)
    same_dev = bool(
        subject.development_name
        and str(subject.development_name).strip()
        and row.get("development_name") == subject.development_name
    )
    return same_sub or same_dev


def _bucket(subject: SubjectProfile, row: pd.Series, as_of: pd.Timestamp) -> tuple[str, int]:
    sold_date = row.get("sold_date")
    days = 9999
    if pd.notna(sold_date):
        days = max((as_of - sold_date).days, 0)

    # Keep same-neighborhood/subdivision comps in A through 12 months.
    if _is_same_community(subject, row) and days <= 365:
        return "A", days
    # B is older same-community support when available.
    if _is_same_community(subject, row) and days <= 730:
        return "B", days
    return "C", days


def _base_points(subject: SubjectProfile, row: pd.Series) -> float:
    points = 0.0
    subj_sqft = subject.sqft_living or 0
    comp_sqft = row.get("sqft_living")
    if subj_sqft > 0 and pd.notna(comp_sqft):
        diff = abs(comp_sqft - subj_sqft) / subj_sqft
        points += 25 * max(0, 1 - (diff / 0.30))
        # Penalize large size mismatch that still passes the hard filter.
        if diff > 0.20:
            points -= 4
        elif diff > 0.10:
            points -= 2

    sb = subject.total_bedrooms
    cb = row.get("total_bedrooms")
    if sb is not None and pd.notna(cb):
        bd = abs(float(cb) - float(sb))
        points += 10 if bd == 0 else (6 if bd <= 1 else 0)
        if bd > 1:
            points -= 4

    sba = subject.baths_total
    cba = row.get("baths_total")
    if sba is not None and pd.notna(cba):
        bd = abs(float(cba) - float(sba))
        points += 10 if bd == 0 else (6 if bd <= 0.5 else 0)
        if bd > 1.0:
            points -= 4
        elif bd > 0.5:
            points -= 2

    sy = subject.year_built
    cy = row.get("year_built")
    if sy is not None and pd.notna(cy):
        yd = abs(float(cy) - float(sy))
        points += 10 * max(0, 1 - yd / 30.0)

    # lot for SFH-like only
    st = (subject.property_type or "").upper()
    if "SINGLE" in st or st == "SF":
        sl = subject.lot_sqft or 0
        cl = row.get("lot_sqft")
        if sl > 0 and pd.notna(cl):
            diff = abs(cl - sl) / sl
            points += 5 * max(0, 1 - (diff / 0.50))
    return float(points)


def _location_points(subject: SubjectProfile, row: pd.Series) -> Tuple[float, float]:
    if subject.final_subdivision and subject.final_subdivision == row.get("final_subdivision"):
        return 20.0, 0.0
    if subject.development_name and subject.development_name == row.get("development_name"):
        return 20.0, 0.0
    if subject.geo_zone and subject.geo_zone == row.get("geo_zone"):
        return 14.0, 0.0

    dist = _distance_miles(subject.geo_lat, subject.geo_lon, row.get("geo_lat"), row.get("geo_lon"))
    if dist is None:
        return 0.0, dist
    if dist <= 0.5:
        return 8.0, dist
    if dist <= 1.0:
        return 4.0, dist
    return 0.0, dist


def _feature_points(subject: SubjectProfile, row: pd.Series) -> float:
    points = 0.0
    sw = subject.waterfront
    cw = row.get("waterfront")
    if sw in (0, 1) and pd.notna(cw):
        if int(cw) == int(sw):
            points += 6
        else:
            points -= 10

    sp = subject.private_pool
    cp = row.get("private_pool")
    if sp in (0, 1) and pd.notna(cp) and int(cp) == int(sp):
        points += 3

    si = subject.storm_protection_impact_glass
    ci = row.get("storm_protection_impact_glass")
    if si in (0, 1) and pd.notna(ci) and int(ci) == int(si):
        points += 3

    sg = subject.garage_spaces
    cg = row.get("garage_spaces")
    if sg is not None and pd.notna(cg) and abs(float(cg) - float(sg)) <= 1:
        points += 2

    # condo floor percentile proxy
    sf = subject.unit_floor
    cf = row.get("unit_floor")
    stf = subject.total_floors_stories
    ctf = row.get("total_floors_stories")
    if all(x is not None and not pd.isna(x) and float(x) > 0 for x in [sf, cf, stf, ctf]):
        s_pct = float(sf) / float(stf)
        c_pct = float(cf) / float(ctf)
        if abs(s_pct - c_pct) <= 0.20:
            points += 3

    return float(points)


def build_candidate_pool(subject: SubjectProfile, sales_df: pd.DataFrame, scope: Dict[str, set], as_of_date: str) -> pd.DataFrame:
    if sales_df.empty:
        return sales_df

    df = sales_df.copy()
    df = df[df["listing_number"] != subject.listing_number]
    # Enforce same broad property group at the top so every tier respects it.
    df = df[df["property_type"].apply(lambda v: _same_property_group(subject.property_type, v))]

    as_of = pd.Timestamp(as_of_date)
    df["months_old"] = (as_of - df["sold_date"]).dt.days / 30.4375

    # Hard guardrail: keep comps within 0.5 miles of subject when geocodes are available.
    if subject.geo_lat is not None and subject.geo_lon is not None:
        df["distance_miles"] = df.apply(
            lambda r: _distance_miles(subject.geo_lat, subject.geo_lon, r.get("geo_lat"), r.get("geo_lon")),
            axis=1,
        )
        df = df[df["distance_miles"].notna() & (df["distance_miles"] <= 0.5)]

    subj_sqft = subject.sqft_living or 0
    if subj_sqft > 0:
        df["sqft_diff"] = (df["sqft_living"] - subj_sqft).abs() / subj_sqft
    else:
        df["sqft_diff"] = 999

    same_sub = df["final_subdivision"].isin(scope.get("final_subdivision_set", set()))
    same_dev = (
        subject.development_name is not None
        and str(subject.development_name).strip() != ""
        and (df["development_name"].astype(str) == str(subject.development_name))
    )
    same_zone = (subject.geo_zone is not None) & (df["geo_zone"].astype(str) == str(subject.geo_zone))

    # Use tighter time window and comp count targets for cleaner comp sets.
    t1 = df[(same_sub | same_dev) & (df["months_old"] <= 12) & (df["sqft_diff"] <= MAX_SQFT_DIFF)]
    if len(t1) >= 15:
        return t1

    t2 = df[same_zone & (df["months_old"] <= 12) & (df["sqft_diff"] <= MAX_SQFT_DIFF)]
    merged = pd.concat([t1, t2], ignore_index=True).drop_duplicates(subset=["listing_number"])
    if len(merged) >= 15:
        return merged

    # Tier 3 radius fallback (still restricted to 0.5 miles, 12 months, and sqft tolerance).
    def within_1mi(r):
        d = _distance_miles(subject.geo_lat, subject.geo_lon, r.get("geo_lat"), r.get("geo_lon"))
        return d is not None and d <= 0.5

    t3 = df[df.apply(within_1mi, axis=1) & (df["months_old"] <= 12) & (df["sqft_diff"] <= MAX_SQFT_DIFF)]
    merged = pd.concat([merged, t3], ignore_index=True).drop_duplicates(subset=["listing_number"])
    return merged


def score_candidates(subject: SubjectProfile, candidates: pd.DataFrame, as_of_date: str, top_n: int = 15) -> List[CompScore]:
    if candidates.empty:
        return []
    as_of = pd.Timestamp(as_of_date)
    out: List[CompScore] = []
    for _, row in candidates.iterrows():
        if pd.isna(row.get("sold_date")) or pd.isna(row.get("sold_price")) or pd.isna(row.get("sqft_living")) or row.get("sqft_living", 0) <= 0:
            continue
        base = _base_points(subject, row)
        loc, distance = _location_points(subject, row)
        feat = _feature_points(subject, row)
        bucket, recency_days = _bucket(subject, row, as_of)
        similarity = max(0.0, min(100.0, base + loc + feat))
        mult = _recency_multiplier(row["sold_date"], as_of)
        final = similarity * mult
        out.append(
            CompScore(
                listing_number=str(row["listing_number"]),
                sold_date=str(row["sold_date"].date()),
                sold_price=float(row["sold_price"]),
                sqft_living=float(row["sqft_living"]),
                ppsf=float(row["sold_price"] / row["sqft_living"]),
                similarity_score=round(similarity, 2),
                recency_multiplier=round(mult, 3),
                final_score=round(final, 2),
                location_points=round(loc, 2),
                base_points=round(base, 2),
                feature_points=round(feat, 2),
                bucket=bucket,
                recency_days=int(recency_days),
                distance_miles=None if distance is None else round(distance, 3),
                final_subdivision=row.get("final_subdivision"),
                city=row.get("city"),
                lot_sqft=(None if pd.isna(row.get("lot_sqft")) else float(row.get("lot_sqft"))),
                year_built=(None if pd.isna(row.get("year_built")) else int(float(row.get("year_built")))),
                year_roof_installed=(
                    None if pd.isna(row.get("year_roof_installed")) else int(float(row.get("year_roof_installed")))
                ),
                waterfront=(None if pd.isna(row.get("waterfront")) else int(float(row.get("waterfront")))),
                private_pool=(None if pd.isna(row.get("private_pool")) else int(float(row.get("private_pool")))),
                storm_protection_impact_glass=(
                    None
                    if pd.isna(row.get("storm_protection_impact_glass"))
                    else int(float(row.get("storm_protection_impact_glass")))
                ),
                public_remarks=(None if pd.isna(row.get("public_remarks")) else str(row.get("public_remarks"))),
            )
        )

    out.sort(key=lambda x: x.final_score, reverse=True)
    return out[:top_n]


def confidence_grade(scored: List[CompScore]) -> tuple[str, str]:
    n = len(scored)
    if n == 0:
        return "C", "No valid sold comps found."
    top = scored[:10]
    med = pd.Series([x.final_score for x in top]).median()
    recent_ratio = pd.Series([x.recency_multiplier >= 0.95 for x in top]).mean()
    a_count = sum(1 for x in top if x.bucket == "A")
    if n >= 12 and med >= 70 and recent_ratio >= 0.5 and a_count >= 4:
        return "A", f"High support: {n} comps, median score {med:.1f}, strong recency."
    if n >= 8 and med >= 55 and a_count >= 2:
        return "B", f"Moderate support: {n} comps, median score {med:.1f}, same-community recent comps {a_count}."
    return "C", f"Lower confidence: {n} comps, median score {med:.1f}, same-community recent comps {a_count}."
