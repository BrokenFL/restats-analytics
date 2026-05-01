import re
from typing import List, Optional

import numpy as np

from .models import CompScore, SubjectProfile


def _weighted_ppsf_for_bucket(comps: List[CompScore]):
    if not comps:
        return None
    scores = np.array([max(c.final_score, 1.0) for c in comps], dtype=float)
    ppsf = np.array([c.ppsf for c in comps], dtype=float)
    w = scores ** 2
    return float((ppsf * w).sum() / w.sum())


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _subject_premium_score(subject: SubjectProfile, community_insights: Optional[dict]) -> tuple[float, list[str]]:
    score = 8.0  # neutral base
    reasons = []

    if subject.waterfront == 1:
        score += 10
        reasons.append("waterfront")
    if subject.private_pool == 1:
        score += 4
        reasons.append("pool")
    if subject.storm_protection_impact_glass == 1:
        score += 4
        reasons.append("impact_glass")
    if subject.construction_cbs == 1:
        score += 2
        reasons.append("cbs_construction")

    if subject.year_roof_installed and subject.year_roof_installed >= 2015:
        score += 2
        reasons.append("newer_roof")

    if subject.unit_floor and subject.total_floors_stories and subject.total_floors_stories > 0:
        pct = float(subject.unit_floor) / float(subject.total_floors_stories)
        if pct >= 0.7:
            score += 2
            reasons.append("higher_floor_percentile")

    if subject.lot_sqft and subject.lot_sqft > 0:
        # Mild positive signal; detailed lot premium is captured in comp matching already.
        score += 1
        reasons.append("larger_lot_signal")

    remarks = (subject.public_remarks or "").lower()
    keyword_map = {
        "renovated_terms": r"\b(?:renovat|remodel|updated|designer|custom)\b",
        "luxury_terms": r"\b(?:luxury|turnkey|chef|premium)\b",
        "impact_terms": r"\b(?:impact|hurricane)\b",
    }
    for key, pat in keyword_map.items():
        if remarks and re.search(pat, remarks):
            score += 1.5
            reasons.append(key)

    # If local market evidence says certain features are lifting top-ppsf,
    # reward those features when subject has them.
    if community_insights:
        drv = community_insights.get("top_price_drivers", {}) or {}
        pool_lift = drv.get("top_vs_low_pool_pct")
        if pool_lift is not None and pool_lift > 10 and subject.private_pool == 1:
            score += 1.5
            reasons.append("pool_matches_top_quartile_lift")
        impact_lift = drv.get("top_vs_low_impact_glass_pct")
        if impact_lift is not None and impact_lift > 10 and subject.storm_protection_impact_glass == 1:
            score += 1.5
            reasons.append("impact_matches_top_quartile_lift")
        water_lift = drv.get("top_vs_low_waterfront_pct")
        if water_lift is not None and water_lift > 10 and subject.waterfront == 1:
            score += 2.0
            reasons.append("waterfront_matches_top_quartile_lift")

    return float(score), reasons


def _has_renovation_signal(text: Optional[str]) -> bool:
    s = str(text or "").lower()
    return bool(re.search(r"\b(?:renovat|remodel|updated|designer|custom|new kitchen|new bath)\b", s))


def _has_partial_impact_signal(text: Optional[str]) -> bool:
    s = str(text or "").lower()
    return bool(re.search(r"\b(?:partial impact|some impact|impact in part|partial hurricane)\b", s))


def _has_view_signal(text: Optional[str]) -> bool:
    s = str(text or "").lower()
    return bool(re.search(r"\b(?:ocean view|intracoastal|lake view|golf view|water view|canal view|preserve view)\b", s))


def _comp_feature_adjustment_pct(subject: SubjectProfile, comp: CompScore) -> tuple[float, list[str], dict]:
    """
    Convert subject-vs-comp feature deltas to a bounded adjustment percent.
    Positive means comp is adjusted up to reflect stronger subject traits.
    """
    score = 0.0
    reasons: list[str] = []
    components: dict[str, float] = {}

    # View / waterfront
    subj_view = (subject.waterfront == 1) or _has_view_signal(subject.public_remarks)
    comp_view = (comp.waterfront == 1) or _has_view_signal(comp.public_remarks)
    if subj_view and not comp_view:
        score += 2.0
        reasons.append("subject_superior_view")
        components["view"] = 2.0
    elif comp_view and not subj_view:
        score -= 2.0
        reasons.append("comp_superior_view")
        components["view"] = -2.0

    # Lot size signal (mainly relevant to SFH)
    if subject.lot_sqft and subject.lot_sqft > 0 and comp.lot_sqft and comp.lot_sqft > 0:
        ratio = (float(subject.lot_sqft) - float(comp.lot_sqft)) / float(subject.lot_sqft)
        if ratio >= 0.20:
            score += 1.0
            reasons.append("subject_larger_lot")
            components["lot"] = 1.0
        elif ratio <= -0.20:
            score -= 1.0
            reasons.append("comp_larger_lot")
            components["lot"] = -1.0

    # Roof year / roof age
    if subject.year_roof_installed and comp.year_roof_installed:
        d = int(subject.year_roof_installed) - int(comp.year_roof_installed)
        if d >= 5:
            score += 1.0
            reasons.append("subject_newer_roof")
            components["roof"] = 1.0
        elif d <= -5:
            score -= 1.0
            reasons.append("comp_newer_roof")
            components["roof"] = -1.0

    # Year built
    if subject.year_built and comp.year_built:
        d = int(subject.year_built) - int(comp.year_built)
        if d >= 10:
            score += 0.75
            reasons.append("subject_newer_year_built")
            components["year_built"] = 0.75
        elif d <= -10:
            score -= 0.75
            reasons.append("comp_newer_year_built")
            components["year_built"] = -0.75

    # Impact windows (full + partial signal via remarks)
    subj_impact = (subject.storm_protection_impact_glass == 1)
    comp_impact = (comp.storm_protection_impact_glass == 1)
    subj_partial = _has_partial_impact_signal(subject.public_remarks)
    comp_partial = _has_partial_impact_signal(comp.public_remarks)
    subj_impact_score = 2 if subj_impact else (1 if subj_partial else 0)
    comp_impact_score = 2 if comp_impact else (1 if comp_partial else 0)
    impact_delta = subj_impact_score - comp_impact_score
    if impact_delta > 0:
        score += 0.9
        reasons.append("subject_superior_impact_protection")
        components["impact"] = 0.9
    elif impact_delta < 0:
        score -= 0.9
        reasons.append("comp_superior_impact_protection")
        components["impact"] = -0.9

    # Renovation signal from remarks
    subj_reno = _has_renovation_signal(subject.public_remarks)
    comp_reno = _has_renovation_signal(comp.public_remarks)
    if subj_reno and not comp_reno:
        score += 1.5
        reasons.append("subject_renovation_signal")
        components["renovation"] = 1.5
    elif comp_reno and not subj_reno:
        score -= 1.5
        reasons.append("comp_renovation_signal")
        components["renovation"] = -1.5

    # Translate points to percent and clamp.
    adj_pct = _clamp(score * 0.8, -12.0, 12.0)
    return float(adj_pct), reasons, components


def value_from_comps(
    subject: SubjectProfile,
    comps: List[CompScore],
    community_insights: Optional[dict] = None,
    guardrail_context: Optional[dict] = None,
) -> dict:
    if not comps or not subject.sqft_living or subject.sqft_living <= 0:
        return {
            "weighted_ppsf": None,
            "baseline_value": None,
            "low_value": None,
            "high_value": None,
            "pre_guardrail_recommended_value": None,
            "guardrail_applied": False,
            "guardrail_adjusted_value": None,
            "guardrail_reason": "insufficient_inputs",
        }

    by_bucket = {
        "A": [c for c in comps if c.bucket == "A"],
        "B": [c for c in comps if c.bucket == "B"],
        "C": [c for c in comps if c.bucket == "C"],
    }
    comp_adjustments: list[dict] = []
    adjusted_ppsf_by_listing: dict[str, float] = {}
    for c in comps:
        adj_pct, adj_reasons, adj_components = _comp_feature_adjustment_pct(subject, c)
        adjusted_ppsf = float(c.ppsf * (1.0 + (adj_pct / 100.0)))
        adjusted_ppsf_by_listing[c.listing_number] = adjusted_ppsf
        comp_adjustments.append(
            {
                "listing_number": c.listing_number,
                "bucket": c.bucket,
                "raw_ppsf": round(float(c.ppsf), 2),
                "adjustment_pct": round(float(adj_pct), 2),
                "adjusted_ppsf": round(float(adjusted_ppsf), 2),
                "reasons": adj_reasons,
                "components": {k: round(float(v), 2) for k, v in adj_components.items()},
            }
        )

    def _weighted_ppsf_for_bucket_adjusted(bucket_comps: List[CompScore]):
        if not bucket_comps:
            return None
        scores = np.array([max(c.final_score, 1.0) for c in bucket_comps], dtype=float)
        ppsf = np.array([adjusted_ppsf_by_listing.get(c.listing_number, c.ppsf) for c in bucket_comps], dtype=float)
        w = scores ** 2
        return float((ppsf * w).sum() / w.sum())

    bucket_ppsf = {k: _weighted_ppsf_for_bucket_adjusted(v) for k, v in by_bucket.items()}

    # Make same-community recent sales dominate.
    target_weights = {"A": 0.85, "B": 0.10, "C": 0.05}
    present = [k for k, v in bucket_ppsf.items() if v is not None]
    if not present:
        return {
            "weighted_ppsf": None,
            "baseline_value": None,
            "low_value": None,
            "high_value": None,
            "bucket_weights_used": {},
            "bucket_counts": {k: len(v) for k, v in by_bucket.items()},
            "pre_guardrail_recommended_value": None,
            "guardrail_applied": False,
            "guardrail_adjusted_value": None,
            "guardrail_reason": "no_bucket_ppsf",
        }
    # If A unavailable, degrade confidence naturally and shift remaining weights.
    if "A" not in present:
        target_weights = {"B": 0.80, "C": 0.20}
    # Normalize weights over present buckets only.
    denom = sum(target_weights.get(k, 0.0) for k in present)
    if denom <= 0:
        norm_weights = {k: 1.0 / len(present) for k in present}
    else:
        norm_weights = {k: target_weights.get(k, 0.0) / denom for k in present}

    weighted_ppsf = float(sum((bucket_ppsf[k] * norm_weights[k]) for k in present))
    baseline = weighted_ppsf * float(subject.sqft_living)

    # Conservative v1 range bands by score dispersion.
    scores = np.array([max(c.final_score, 1.0) for c in comps], dtype=float)
    score_std = float(np.std(scores)) if len(scores) > 1 else 0.0
    spread = 0.08 if score_std <= 10 else 0.12
    low = baseline * (1 - spread)
    high = baseline * (1 + spread)

    # Premium adjustment layer:
    # move target PPSF within observed comp band according to subject premium score.
    ppsf_values = np.array(sorted([c.ppsf for c in comps if c.ppsf > 0]), dtype=float)
    if len(ppsf_values) >= 4:
        p25 = float(np.quantile(ppsf_values, 0.25))
        p50 = float(np.quantile(ppsf_values, 0.50))
        p75 = float(np.quantile(ppsf_values, 0.75))
        p90 = float(np.quantile(ppsf_values, 0.90))
    else:
        p25 = p50 = p75 = p90 = float(weighted_ppsf)

    premium_score, premium_reasons = _subject_premium_score(subject, community_insights)

    # 0-20 scale around neutral 8.
    push_up = _clamp((premium_score - 8.0) / 12.0, 0.0, 1.0)
    push_down = _clamp((8.0 - premium_score) / 8.0, 0.0, 1.0)

    if premium_score >= 8.0:
        target_ppsf = weighted_ppsf + (p90 - weighted_ppsf) * push_up
    else:
        target_ppsf = weighted_ppsf - (weighted_ppsf - p25) * push_down

    # Guard using community high ppsf when available.
    comm_high = (community_insights or {}).get("ppsf_high")
    if comm_high and comm_high > 0:
        target_ppsf = min(target_ppsf, float(comm_high))
    target_ppsf = max(target_ppsf, 1.0)

    premium_value = target_ppsf * float(subject.sqft_living)
    premium_adj_pct = ((premium_value - baseline) / baseline) * 100 if baseline > 0 else 0.0

    pre_guardrail_recommended_value = round(float(premium_value), 0)
    adjusted_value = pre_guardrail_recommended_value
    guardrail_applied = False
    guardrail_reason = "none"
    if guardrail_context and baseline > 0:
        cap = guardrail_context.get("recommended_value_cap_pct")
        floor = guardrail_context.get("recommended_value_floor_pct")
        if cap is not None and floor is not None:
            clamped_pct = _clamp(float(premium_adj_pct), float(floor), float(cap))
            adjusted_value = round(float(baseline * (1.0 + (clamped_pct / 100.0))), 0)
            guardrail_applied = adjusted_value != pre_guardrail_recommended_value
            state = guardrail_context.get("pending_pressure_state") or "unknown"
            guardrail_reason = f"pending_pressure_{state}"

    out = {
        "weighted_ppsf": round(weighted_ppsf, 2),
        "baseline_value": round(baseline, 0),
        "low_value": round(low, 0),
        "high_value": round(high, 0),
        "bucket_weights_used": {k: round(v, 3) for k, v in norm_weights.items()},
        "bucket_ppsf": {k: (None if bucket_ppsf[k] is None else round(bucket_ppsf[k], 2)) for k in ["A", "B", "C"]},
        "bucket_counts": {k: len(v) for k, v in by_bucket.items()},
        "premium_score": round(premium_score, 2),
        "premium_reasons": premium_reasons,
        "ppsf_band_selected_comps": {
            "p25": round(p25, 2),
            "p50": round(p50, 2),
            "p75": round(p75, 2),
            "p90": round(p90, 2),
        },
        "premium_adjusted_ppsf": round(float(target_ppsf), 2),
        "premium_adjusted_value": round(float(premium_value), 0),
        "premium_adjustment_pct_vs_baseline": round(float(premium_adj_pct), 1),
        "comp_adjustments": comp_adjustments,
        "pre_guardrail_recommended_value": pre_guardrail_recommended_value,
        "guardrail_applied": guardrail_applied,
        "guardrail_adjusted_value": adjusted_value,
        "guardrail_reason": guardrail_reason,
        # Suggested final estimate can be bounded by pending-pressure guardrails.
        "final_recommended_value": adjusted_value,
    }
    return out
