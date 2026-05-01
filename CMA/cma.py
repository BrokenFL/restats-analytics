import argparse
import csv
import glob
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Set

import pandas as pd


CHEATSHEET_PATTERN = "*_subdivision_audit_cheatsheet.csv"


@dataclass
class LookupHit:
    lookup_file: str
    master_pcn: str
    county_subdivision_name: str
    final_subdivision: str
    unified_subdivision: str
    pcn10: str


def clean_pcn(raw: str) -> str:
    if not raw:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", str(raw)).upper()


def subid_from_pcn(raw_pcn: str) -> str:
    p = clean_pcn(raw_pcn)
    return p[:10] if len(p) >= 10 else p


def find_lookup_files(lookups_dir: str) -> List[str]:
    paths = sorted(glob.glob(os.path.join(lookups_dir, CHEATSHEET_PATTERN)))
    return [p for p in paths if os.path.isfile(p)]


def load_lookup(path: str) -> pd.DataFrame:
    # Read strings to preserve leading zeros in PCN.
    df = pd.read_csv(path, dtype=str).fillna("")
    required = {"Master PCN", "Name", "Final Subdivision", "Unified Subdivision"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path} missing columns: {sorted(missing)}")

    df = df.copy()
    df["Master PCN"] = df["Master PCN"].apply(clean_pcn)
    df["PCN10"] = df["Master PCN"].str[:10]
    df["Name"] = df["Name"].astype(str).str.strip()
    df["Final Subdivision"] = df["Final Subdivision"].astype(str).str.strip()
    df["Unified Subdivision"] = df["Unified Subdivision"].astype(str).str.strip()
    return df


def lookup_hits_for_subid(lookup_path: str, df: pd.DataFrame, subid: str) -> List[LookupHit]:
    hits = []
    match_rows = df[df["PCN10"] == subid]
    for _, row in match_rows.iterrows():
        hits.append(
            LookupHit(
                lookup_file=os.path.basename(lookup_path),
                master_pcn=row["Master PCN"],
                county_subdivision_name=row["Name"],
                final_subdivision=row["Final Subdivision"],
                unified_subdivision=row["Unified Subdivision"],
                pcn10=row["PCN10"],
            )
        )
    return hits


def resolve_subdivision_context(subid: str, lookup_files: List[str]) -> Dict:
    all_hits: List[LookupHit] = []
    loaded: Dict[str, pd.DataFrame] = {}
    for path in lookup_files:
        df = load_lookup(path)
        loaded[path] = df
        all_hits.extend(lookup_hits_for_subid(path, df, subid))

    unified_set: Set[str] = set()
    final_set: Set[str] = set()
    for h in all_hits:
        if h.unified_subdivision:
            unified_set.add(h.unified_subdivision)
        if h.final_subdivision:
            final_set.add(h.final_subdivision)

    # If no direct PCN10 hit, fall back to PCN8/PCN9 proximity hints.
    proximity_rows = []
    if not all_hits and len(subid) >= 8:
        prefixes = [subid[:9], subid[:8]]
        for path, df in loaded.items():
            for pref in prefixes:
                prox = df[df["PCN10"].str.startswith(pref)]
                if prox.empty:
                    continue
                sample = prox[["PCN10", "Final Subdivision", "Unified Subdivision"]].drop_duplicates().head(30)
                for _, r in sample.iterrows():
                    proximity_rows.append(
                        {
                            "lookup_file": os.path.basename(path),
                            "pcn10": r["PCN10"],
                            "final_subdivision": r["Final Subdivision"],
                            "unified_subdivision": r["Unified Subdivision"],
                            "match_prefix": pref,
                        }
                    )

    # Build cross-community search list from all lookups.
    search_rows = []
    search_rows_detailed = []
    if unified_set:
        for path, df in loaded.items():
            in_unified = df[df["Unified Subdivision"].isin(unified_set)]
            in_unified = in_unified[["PCN10", "Name", "Final Subdivision", "Unified Subdivision"]].drop_duplicates()
            for _, r in in_unified.iterrows():
                search_rows.append(
                    {
                        "lookup_file": os.path.basename(path),
                        "official_subdivision_name": r["Name"],
                        "normalized_subdivision_name": r["Final Subdivision"],
                        "unified_subdivision": r["Unified Subdivision"],
                        "reason": "shared_unified_subdivision",
                    }
                )
                search_rows_detailed.append(
                    {
                        "lookup_file": os.path.basename(path),
                        "subid": r["PCN10"],
                        "official_subdivision_name": r["Name"],
                        "normalized_subdivision_name": r["Final Subdivision"],
                        "unified_subdivision": r["Unified Subdivision"],
                        "reason": "shared_unified_subdivision",
                    }
                )

    # Guarantee direct finals are included.
    for h in all_hits:
        search_rows.append(
            {
                "lookup_file": h.lookup_file,
                "official_subdivision_name": h.county_subdivision_name,
                "normalized_subdivision_name": h.final_subdivision,
                "unified_subdivision": h.unified_subdivision,
                "reason": "direct_pcn10_match",
            }
        )
        search_rows_detailed.append(
            {
                "lookup_file": h.lookup_file,
                "subid": h.pcn10,
                "official_subdivision_name": h.county_subdivision_name,
                "normalized_subdivision_name": h.final_subdivision,
                "unified_subdivision": h.unified_subdivision,
                "reason": "direct_pcn10_match",
            }
        )

    # De-duplicate stable sort.
    if search_rows:
        s_df = pd.DataFrame(search_rows).fillna("")
        s_df = s_df.sort_values(
            by=[
                "unified_subdivision",
                "official_subdivision_name",
                "normalized_subdivision_name",
                "lookup_file",
                "reason",
            ]
        ).drop_duplicates(
            subset=["official_subdivision_name", "unified_subdivision", "lookup_file"]
        )
        search_rows = s_df.to_dict(orient="records")
    if search_rows_detailed:
        sd_df = pd.DataFrame(search_rows_detailed).fillna("")
        sd_df = sd_df.sort_values(
            by=[
                "unified_subdivision",
                "subid",
                "official_subdivision_name",
                "normalized_subdivision_name",
                "lookup_file",
                "reason",
            ]
        ).drop_duplicates(
            subset=["lookup_file", "subid", "official_subdivision_name", "unified_subdivision"]
        )
        search_rows_detailed = sd_df.to_dict(orient="records")

    return {
        "subid": subid,
        "direct_hits": all_hits,
        "unified_subdivisions": sorted(unified_set),
        "final_subdivisions": sorted(final_set),
        "proximity_candidates": proximity_rows,
        "search_subdivision_rows": search_rows,
        "search_subdivision_rows_detailed": search_rows_detailed,
    }


def write_search_plan_csv(rows: List[Dict], output_csv: str) -> None:
    os.makedirs(os.path.dirname(output_csv) or ".", exist_ok=True)
    fieldnames = [
        "lookup_file",
        "official_subdivision_name",
        "normalized_subdivision_name",
        "unified_subdivision",
        "reason",
    ]
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def write_search_plan_detailed_csv(rows: List[Dict], output_csv: str) -> None:
    os.makedirs(os.path.dirname(output_csv) or ".", exist_ok=True)
    fieldnames = [
        "lookup_file",
        "subid",
        "official_subdivision_name",
        "normalized_subdivision_name",
        "unified_subdivision",
        "reason",
    ]
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def write_sales_query_csv(
    rows: List[Dict],
    output_csv: str,
    date_from: str,
    date_to: str,
    min_sale: int,
) -> None:
    """
    Emit exact subdivision-name search requests for the property records sales pull step.
    """
    os.makedirs(os.path.dirname(output_csv) or ".", exist_ok=True)
    if rows:
        df = pd.DataFrame(rows).fillna("")
    else:
        df = pd.DataFrame(columns=["lookup_file", "subid", "official_subdivision_name", "normalized_subdivision_name", "unified_subdivision", "reason"])

    # One row per unique official county subdivision search string.
    if not df.empty:
        keep_cols = ["lookup_file", "subid", "official_subdivision_name", "normalized_subdivision_name", "unified_subdivision", "reason"]
        df = df[keep_cols]
        df = df[df["official_subdivision_name"].astype(str).str.strip() != ""]
        df = df.sort_values(by=["official_subdivision_name", "unified_subdivision", "lookup_file", "subid"])
        df = df.drop_duplicates(subset=["official_subdivision_name", "unified_subdivision", "lookup_file"])

    df["sale_type"] = "QS"
    df["date_from"] = date_from
    df["date_to"] = date_to
    df["min_sale_price"] = int(min_sale)
    df["search_mode"] = "Subdivision"

    fieldnames = [
        "lookup_file",
        "subid",
        "official_subdivision_name",
        "normalized_subdivision_name",
        "unified_subdivision",
        "sale_type",
        "date_from",
        "date_to",
        "min_sale_price",
        "search_mode",
        "reason",
    ]
    df.to_csv(output_csv, index=False, columns=fieldnames)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Initial CMA resolver: PCN -> subdivision search plan.")
    p.add_argument("--pcn", required=True, help="Target parcel control number.")
    p.add_argument("--city", help="Optional city hint (used for display only in initial version).")
    p.add_argument("--lookups-dir", default=".", help="Directory with *_subdivision_audit_cheatsheet.csv files.")
    p.add_argument("--months", type=int, default=12, help="Sale lookback months (for plan metadata).")
    p.add_argument("--min-sale", type=int, default=100000, help="Minimum sale price filter (for plan metadata).")
    p.add_argument(
        "--output-plan",
        default="cma_search_plan.csv",
        help="Output CSV containing official subdivision names to search.",
    )
    p.add_argument(
        "--output-plan-detailed",
        default="cma_search_plan_detailed.csv",
        help="Output CSV containing SUBID -> official subdivision names within unified group.",
    )
    p.add_argument(
        "--output-sales-queries",
        default="cma_sales_queries.csv",
        help="Output CSV for sales-search automation (exact official subdivision names + filters).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    pcn_clean = clean_pcn(args.pcn)
    subid = subid_from_pcn(pcn_clean)
    if len(subid) < 8:
        raise ValueError(f"PCN '{args.pcn}' is too short after cleaning: '{pcn_clean}'")

    lookup_files = find_lookup_files(args.lookups_dir)
    if not lookup_files:
        raise FileNotFoundError(
            f"No lookup files found in {args.lookups_dir} matching {CHEATSHEET_PATTERN}"
        )

    resolved = resolve_subdivision_context(subid=subid, lookup_files=lookup_files)
    write_search_plan_csv(resolved["search_subdivision_rows"], args.output_plan)
    write_search_plan_detailed_csv(
        resolved["search_subdivision_rows_detailed"], args.output_plan_detailed
    )
    date_to = date.today()
    date_from = date_to - timedelta(days=args.months * 30)
    write_sales_query_csv(
        rows=resolved["search_subdivision_rows_detailed"],
        output_csv=args.output_sales_queries,
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        min_sale=args.min_sale,
    )

    print("\n--- CMA Resolver Output ---")
    print(f"Input PCN: {args.pcn}")
    print(f"Clean PCN: {pcn_clean}")
    print(f"SUBID (first 10): {subid}")
    if args.city:
        print(f"City Hint: {args.city}")
    print(f"Lookup files scanned: {len(lookup_files)}")
    print(f"Direct SUBID hits: {len(resolved['direct_hits'])}")
    print(f"Unified subdivisions found: {len(resolved['unified_subdivisions'])}")
    print(f"Official subdivisions to search: {len(resolved['search_subdivision_rows'])}")
    print(f"Sales filters planned: QS only, sale_price >= {args.min_sale:,}")
    print(f"Sales date window planned: {date_from.isoformat()} to {date_to.isoformat()}")
    print(f"Search plan CSV: {os.path.abspath(args.output_plan)}")
    print(f"Detailed plan CSV: {os.path.abspath(args.output_plan_detailed)}")
    print(f"Sales query CSV: {os.path.abspath(args.output_sales_queries)}")

    if resolved["direct_hits"]:
        print("\nDirect Hits:")
        for h in resolved["direct_hits"][:20]:
            print(
                f"- [{h.lookup_file}] PCN={h.master_pcn} "
                f"| CountyName='{h.county_subdivision_name}' "
                f"| Final='{h.final_subdivision}' | Unified='{h.unified_subdivision}'"
            )
    elif resolved["proximity_candidates"]:
        print("\nNo exact SUBID hit. Nearby prefix candidates:")
        for r in resolved["proximity_candidates"][:20]:
            print(
                f"- [{r['lookup_file']}] prefix={r['match_prefix']} pcn10={r['pcn10']} "
                f"| Final='{r['final_subdivision']}' | Unified='{r['unified_subdivision']}'"
            )
    else:
        print("\nNo direct or proximity subdivision matches found in lookup files.")


if __name__ == "__main__":
    main()
