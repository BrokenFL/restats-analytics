import argparse
import glob
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def canon(value):
    if value is None:
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    return " ".join(s.split())


def canon_pcn10(value):
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return None
    # Normalize all lookup/db PCNs to fixed 10-digit key.
    return digits.zfill(10)[:10]


def load_master_map(lookup_dir="lookups"):
    pcn_map = {}
    files = sorted(glob.glob(os.path.join(lookup_dir, "*subdivision*audit*cheatsheet*.csv")))
    for path in files:
        df = pd.read_csv(path, dtype=str)
        if "Master PCN" not in df.columns:
            continue
        preferred_cols = [
            "Unified_Group_Name",
            "Unified Subdivision",
            "Final_Subdivision_Name",
            "Final Subdivision",
            "Name",
        ]
        sub_col = next((c for c in preferred_cols if c in df.columns), None)
        if not sub_col:
            continue
        for _, row in df[["Master PCN", sub_col]].dropna().iterrows():
            pcn = canon_pcn10(row["Master PCN"])
            sub = canon(row[sub_col])
            if pcn and sub and pcn not in pcn_map:
                pcn_map[pcn] = sub
    return pcn_map


def main():
    parser = argparse.ArgumentParser(description="Sync listing_details.final_subdivision to master lookup by PCN.")
    parser.add_argument("--db", default=str(PROJECT_ROOT / "mls.db"), help="Path to SQLite DB.")
    parser.add_argument("--lookup-dir", default=str(PROJECT_ROOT / "lookups"), help="Lookup folder path.")
    parser.add_argument("--apply", action="store_true", help="Apply updates. Default is dry-run.")
    parser.add_argument(
        "--report-path",
        default=os.path.join("output", "audits", "subdivision_master_sync_report.csv"),
        help="CSV report path.",
    )
    args = parser.parse_args()

    pcn_map = load_master_map(args.lookup_dir)
    if not pcn_map:
        print("No PCN map loaded from lookup files. Nothing to do.")
        return

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT listing_number, pcn_10_digit, final_subdivision, city FROM listing_details")
    rows = [dict(r) for r in cur.fetchall()]

    df = pd.DataFrame(rows)
    df["pcn"] = df["pcn_10_digit"].map(canon_pcn10)
    df["db_sub"] = df["final_subdivision"].map(canon)
    df["master_sub"] = df["pcn"].map(pcn_map)

    scope = df[df["pcn"].notna() & df["master_sub"].notna()].copy()
    scope["needs_update"] = scope["db_sub"] != scope["master_sub"]
    updates = scope[scope["needs_update"]].copy()

    os.makedirs(os.path.dirname(args.report_path), exist_ok=True)
    summary_cols = ["listing_number", "pcn_10_digit", "city", "final_subdivision", "master_sub"]
    out = updates.copy()
    out = out.rename(columns={"master_sub": "master_final_subdivision"})
    out[summary_cols[:-1] + ["master_final_subdivision"]].to_csv(args.report_path, index=False)

    print(f"Master PCN mappings loaded: {len(pcn_map)}")
    print(f"Rows with master mapping in DB: {len(scope)}")
    print(f"Rows needing update: {len(updates)}")
    print(f"Distinct PCNs needing update: {updates['pcn'].nunique() if not updates.empty else 0}")
    print(f"Report: {args.report_path}")

    if args.apply and not updates.empty:
        to_update = [
            (row["master_sub"], row["listing_number"])
            for _, row in updates[["master_sub", "listing_number"]].iterrows()
        ]
        cur.executemany(
            "UPDATE listing_details SET final_subdivision = ?, pcn_validated = 1 WHERE listing_number = ?",
            to_update,
        )
        # Mark all rows that had a valid master mapping as validated, even if no name change was needed.
        mapped_rows = [(row["listing_number"],) for _, row in scope[["listing_number"]].iterrows()]
        cur.executemany(
            "UPDATE listing_details SET pcn_validated = 1 WHERE listing_number = ?",
            mapped_rows,
        )
        conn.commit()
        print(f"Applied updates: {len(to_update)}")
        print(f"Marked as validated (mapped rows): {len(mapped_rows)}")
    elif args.apply:
        print("No updates needed.")
    else:
        print("Dry run only. Re-run with --apply to commit.")

    conn.close()


if __name__ == "__main__":
    main()
