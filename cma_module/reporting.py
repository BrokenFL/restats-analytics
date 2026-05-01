import csv
import json
import os
from dataclasses import asdict
from datetime import datetime
from typing import List, Optional

from .models import CompScore, SubjectProfile


def _output_dir(subject: SubjectProfile) -> str:
    key = subject.parcel_id or subject.listing_number
    key = str(key).replace("/", "_").replace(" ", "_")
    root = os.path.join("output", "cma", key)
    os.makedirs(root, exist_ok=True)
    return root


def write_outputs(
    subject: SubjectProfile,
    comps: List[CompScore],
    value: dict,
    context: dict,
    scope: dict,
    community_insights: Optional[dict] = None,
    pending_projection: Optional[dict] = None,
    closing_trends: Optional[dict] = None,
    surrounding_discount_metrics: Optional[dict] = None,
    pending_pressure_guardrail: Optional[dict] = None,
) -> dict:
    out_dir = _output_dir(subject)
    top_comps_csv = os.path.join(out_dir, "top_comps.csv")
    valuation_json = os.path.join(out_dir, "valuation.json")
    context_json = os.path.join(out_dir, "context.json")

    with open(top_comps_csv, "w", newline="", encoding="utf-8") as f:
        if comps:
            writer = csv.DictWriter(f, fieldnames=list(asdict(comps[0]).keys()))
            writer.writeheader()
            writer.writerows([asdict(c) for c in comps])
        else:
            writer = csv.writer(f)
            writer.writerow(["note"])
            writer.writerow(["No valid comps"])

    valuation_payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "subject": asdict(subject),
        "valuation": value,
        "comps_used": len(comps),
        "top_scores": [c.final_score for c in comps[:5]],
        "community_insights": community_insights or {},
        "pending_projection": pending_projection or {},
        "surrounding_discount_metrics": surrounding_discount_metrics or {},
        "pending_pressure_guardrail": pending_pressure_guardrail or {},
        "closing_trends": closing_trends or {},
    }
    with open(valuation_json, "w", encoding="utf-8") as f:
        json.dump(valuation_payload, f, indent=2)

    with open(context_json, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "surrounding_area_context": context,
                "pending_projection": pending_projection or {},
                "surrounding_discount_metrics": surrounding_discount_metrics or {},
                "pending_pressure_guardrail": pending_pressure_guardrail or {},
                "closing_trends": closing_trends or {},
                "trend_summaries": {
                    "community_trend_summary": (closing_trends or {}).get("community_trend_summary", {}),
                    "surrounding_trend_summary": (closing_trends or {}).get("surrounding_trend_summary", {}),
                    "trend_divergence_flags": (closing_trends or {}).get("trend_divergence_flags", []),
                },
                "scope": {
                    "pcn10_count": len(scope.get("pcn10_set", [])),
                    "final_subdivision_count": len(scope.get("final_subdivision_set", [])),
                    "unified_subdivision_count": len(scope.get("unified_subdivision_set", [])),
                },
            },
            f,
            indent=2,
        )

    return {
        "out_dir": out_dir,
        "top_comps_csv": top_comps_csv,
        "valuation_json": valuation_json,
        "context_json": context_json,
    }
