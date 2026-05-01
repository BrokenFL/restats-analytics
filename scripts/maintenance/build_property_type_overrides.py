import argparse
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description="Promote audited property-type recommendations into lookup CSVs.")
    parser.add_argument(
        "--audit-dir",
        default=str(PROJECT_ROOT / "output" / "audits"),
    )
    parser.add_argument(
        "--lookup-dir",
        default=str(PROJECT_ROOT / "lookups"),
    )
    parser.add_argument(
        "--subdivision-threshold",
        type=float,
        default=0.85,
        help="Minimum dominant share for subdivision defaults.",
    )
    parser.add_argument(
        "--parcel-threshold",
        type=float,
        default=0.90,
        help="Minimum dominant share for parcel overrides.",
    )
    args = parser.parse_args()

    audit_dir = Path(args.audit_dir)
    lookup_dir = Path(args.lookup_dir)
    lookup_dir.mkdir(parents=True, exist_ok=True)

    defaults_path = audit_dir / "property_type_subdivision_defaults.csv"
    parcel_path = audit_dir / "property_type_parcel_override_candidates.csv"

    defaults_df = pd.read_csv(defaults_path, dtype={"final_subdivision": str, "dominant_type": str})
    defaults_df = defaults_df[defaults_df["dominant_share"] >= args.subdivision_threshold].copy()
    defaults_df = defaults_df[
        ["final_subdivision", "dominant_type", "dominant_share", "historical_rows"]
    ].rename(columns={"dominant_type": "property_type"})
    defaults_df = defaults_df.sort_values(["historical_rows", "dominant_share", "final_subdivision"], ascending=[False, False, True])
    defaults_df.to_csv(lookup_dir / "property_type_subdivision_defaults.csv", index=False)

    parcel_df = pd.read_csv(parcel_path, dtype={"pcn_10_digit": str, "parcel_dominant_type": str, "final_subdivision": str})
    parcel_df = parcel_df[parcel_df["parcel_dominant_share"] >= args.parcel_threshold].copy()
    parcel_df["pcn_10_digit"] = parcel_df["pcn_10_digit"].astype(str).str.replace(r"\D", "", regex=True).str[:10]
    parcel_df = parcel_df[
        ["pcn_10_digit", "final_subdivision", "parcel_dominant_type", "parcel_dominant_share", "parcel_rows"]
    ].rename(columns={"parcel_dominant_type": "property_type"})
    parcel_df = parcel_df.sort_values(["parcel_rows", "parcel_dominant_share", "final_subdivision", "pcn_10_digit"], ascending=[False, False, True, True])
    parcel_df.to_csv(lookup_dir / "property_type_parcel_overrides.csv", index=False)

    print(f"Wrote {len(defaults_df)} subdivision defaults to {lookup_dir / 'property_type_subdivision_defaults.csv'}")
    print(f"Wrote {len(parcel_df)} parcel overrides to {lookup_dir / 'property_type_parcel_overrides.csv'}")


if __name__ == "__main__":
    main()
