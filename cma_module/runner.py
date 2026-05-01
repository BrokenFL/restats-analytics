import argparse
import json
from datetime import date

from .db import (
    build_pending_pressure_guardrail,
    get_subject_by_parcel,
    pull_candidate_sales,
    pull_market_activity,
    pull_pending_projection,
    pull_surrounding_discount_metrics,
)
from .expansion import resolve_market_scope
from .insights import build_closing_trends, build_community_insights
from .reporting import write_outputs
from .scoring import build_candidate_pool, confidence_grade, score_candidates
from .valuation import value_from_comps


def parse_args():
    p = argparse.ArgumentParser(description="Run CMA valuation from existing ReStats DB.")
    p.add_argument("--parcel", required=True, help="Subject parcel id (with or without dashes).")
    p.add_argument("--as-of-date", default=date.today().isoformat(), help="YYYY-MM-DD")
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--skip-offmarket-refresh", action="store_true", help="Skip pre-CMA off-market subdivision refresh.")
    p.add_argument("--refresh-months-back", type=int, default=12, help="Months back for off-market pre-refresh window.")
    p.add_argument("--print-json", action="store_true")
    return p.parse_args()


def _run_offmarket_refresh(parcel: str, as_of_date: str, months_back: int):
    """
    Reuse main.py CMA off-market refresh when runner is invoked directly.
    Returns dict summary, or None if integration unavailable.
    """
    try:
        import main as app_main  # ReStats entrypoint module
    except Exception as e:
        return {"status": "skipped", "reason": f"main_import_failed: {e}", "attempted": 0, "imported": 0}

    refresh_fn = getattr(app_main, "run_cma_off_market_refresh", None)
    if refresh_fn is None:
        return {"status": "skipped", "reason": "refresh_function_missing", "attempted": 0, "imported": 0}

    try:
        result = refresh_fn(parcel=parcel, as_of_date=as_of_date, months_back=months_back)
        if isinstance(result, dict):
            return result
        return {"status": "ok", "reason": None, "attempted": 0, "imported": 0}
    except Exception as e:
        return {"status": "failed", "reason": str(e), "attempted": 0, "imported": 0}


def main():
    args = parse_args()
    refresh_result = None
    if args.skip_offmarket_refresh:
        refresh_result = {"status": "skipped", "reason": "user_skip", "attempted": 0, "imported": 0}
        if not args.print_json:
            print("\n⏭️  CMA pre-refresh: SKIPPED by flag (--skip-offmarket-refresh)")
    else:
        if not args.print_json:
            print("\n🔄 CMA pre-refresh: OFF-MARKET ENABLED")
        refresh_result = _run_offmarket_refresh(
            parcel=args.parcel,
            as_of_date=args.as_of_date,
            months_back=max(1, int(args.refresh_months_back or 12)),
        )
        if not args.print_json:
            print(
                "CMA pre-refresh summary: "
                f"status={refresh_result.get('status')} | "
                f"attempted={refresh_result.get('attempted')} | "
                f"imported={refresh_result.get('imported')} | "
                f"reason={refresh_result.get('reason') or 'none'}"
            )

    subject = get_subject_by_parcel(args.parcel, as_of_date=args.as_of_date)
    scope = resolve_market_scope(subject.pcn_10_digit or subject.parcel_id, subject.final_subdivision or "")
    sales_df = pull_candidate_sales(as_of_date=args.as_of_date, months_back=12)

    # Community-first comp harvest stats before scoring.
    same_community = sales_df[sales_df["final_subdivision"].isin(scope.get("final_subdivision_set", set()))].copy()
    community_source_breakdown = (
        same_community.groupby("source_type").size().to_dict() if not same_community.empty else {}
    )

    candidates = build_candidate_pool(subject, sales_df, scope, as_of_date=args.as_of_date)
    scored = score_candidates(subject, candidates, as_of_date=args.as_of_date, top_n=args.top_n)
    conf_grade, conf_reason = confidence_grade(scored)
    value = value_from_comps(subject, scored, community_insights=None, guardrail_context=None)
    value["confidence_grade"] = conf_grade
    value["confidence_reason"] = conf_reason
    context = pull_market_activity(subject, as_of_date=args.as_of_date)
    pending_projection = pull_pending_projection(subject, scope, as_of_date=args.as_of_date)
    surrounding_discount_metrics = pull_surrounding_discount_metrics(subject, as_of_date=args.as_of_date)
    pending_pressure_guardrail = build_pending_pressure_guardrail(
        subject,
        scope,
        as_of_date=args.as_of_date,
        pending_projection=pending_projection,
        surrounding_discount_metrics=surrounding_discount_metrics,
        surrounding_context=context,
    )
    community_insights = build_community_insights(subject, sales_df, scope, as_of_date=args.as_of_date)
    closing_trends = build_closing_trends(subject, sales_df, scope, as_of_date=args.as_of_date)
    # Recompute value with premium layer informed by community insights.
    value = value_from_comps(
        subject,
        scored,
        community_insights=community_insights,
        guardrail_context=pending_pressure_guardrail,
    )
    value["confidence_grade"] = conf_grade
    value["confidence_reason"] = conf_reason
    paths = write_outputs(
        subject,
        scored,
        value,
        context,
        scope,
        community_insights=community_insights,
        pending_projection=pending_projection,
        closing_trends=closing_trends,
        surrounding_discount_metrics=surrounding_discount_metrics,
        pending_pressure_guardrail=pending_pressure_guardrail,
    )

    payload = {
        "subject_parcel": subject.parcel_id,
        "subject_listing_number": subject.listing_number,
        "as_of_date": args.as_of_date,
        "offmarket_refresh": refresh_result or {},
        "community_scope": {
            "final_subdivision_count": len(scope.get("final_subdivision_set", [])),
            "community_sales_pool_count": int(len(same_community)),
            "community_source_breakdown": community_source_breakdown,
        },
        "candidate_count": int(len(candidates)),
        "scored_count": int(len(scored)),
        "valuation": value,
        "community_insights": community_insights,
        "pending_projection": pending_projection,
        "surrounding_discount_metrics": surrounding_discount_metrics,
        "pending_pressure_guardrail": pending_pressure_guardrail,
        "closing_trends": closing_trends,
        "surrounding_area_context": context,
        "outputs": paths,
    }
    if args.print_json:
        print(json.dumps(payload, indent=2))
    else:
        print("\n=== CMA RUN COMPLETE ===")
        print(f"Subject: {subject.short_address or subject.parcel_id} ({subject.parcel_id})")
        print(f"As-of: {args.as_of_date}")
        print(
            f"Community pool (before scoring): {len(same_community)} "
            f"| MLS {community_source_breakdown.get('MLS', 0)} "
            f"| Off-market {community_source_breakdown.get('OFF_MARKET', 0)}"
        )
        print(f"Candidates: {len(candidates)} | Scored comps: {len(scored)}")
        print(f"Value (baseline): ${value.get('baseline_value'):,.0f}" if value.get("baseline_value") else "Value (baseline): N/A")
        if value.get("premium_adjusted_value"):
            print(
                f"Value (premium-adjusted): ${value.get('premium_adjusted_value'):,.0f} "
                f"({value.get('premium_adjustment_pct_vs_baseline')}% vs baseline)"
            )
        print(f"Range: ${value.get('low_value'):,.0f} - ${value.get('high_value'):,.0f}" if value.get("low_value") else "Range: N/A")
        print(f"Confidence: {conf_grade} ({conf_reason})")
        if community_insights.get("community_comp_count_12mo", 0) > 0:
            print(
                "Community PPSF (12mo) "
                f"low/med/high: ${community_insights.get('ppsf_low'):,.0f}/"
                f"${community_insights.get('ppsf_median'):,.0f}/"
                f"${community_insights.get('ppsf_high'):,.0f}"
            )
        print(
            "Pending projection (community): "
            f"{pending_projection.get('pending_count', 0)} pending | "
            f"median list discount {pending_projection.get('recent_median_listing_discount_pct')}% "
            f"({pending_projection.get('discount_source_days') or 'N/A'}d lookback)"
        )
        print(
            "Surrounding discount: "
            f"{surrounding_discount_metrics.get('surrounding_median_listing_discount_pct')}% "
            f"({surrounding_discount_metrics.get('surrounding_discount_source_days') or 'N/A'}d lookback, "
            f"n={surrounding_discount_metrics.get('surrounding_discount_source_comp_count', 0)})"
        )
        print(
            "Pending pressure guardrail: "
            f"{pending_pressure_guardrail.get('pending_pressure_state')} | "
            f"cap {pending_pressure_guardrail.get('recommended_value_cap_pct')}% | "
            f"floor {pending_pressure_guardrail.get('recommended_value_floor_pct')}%"
        )
        print(
            "Closing trend points (12mo): "
            f"community={len(closing_trends.get('community_monthly', []))}, "
            f"surrounding={len(closing_trends.get('surrounding_monthly', []))}"
        )
        print(f"60d sold (surrounding): {context.get('sold_60_count')} | 60d pending: {context.get('pending_60_count')}")
        print(f"Output folder: {paths['out_dir']}")


if __name__ == "__main__":
    main()
