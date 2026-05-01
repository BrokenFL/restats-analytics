import glob
import os
import re
from typing import Dict, Set

import pandas as pd

LOOKUP_PATTERN = "*_subdivision_audit_cheatsheet.csv"


def _clean_pcn(v: str) -> str:
    digits = re.sub(r"\D", "", str(v or ""))
    return digits.zfill(10)[:10] if digits else ""


def _lookups_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    return os.path.join(root, "lookups")


def load_lookup_table() -> pd.DataFrame:
    frames = []
    for path in sorted(glob.glob(os.path.join(_lookups_dir(), LOOKUP_PATTERN))):
        df = pd.read_csv(path, dtype=str).fillna("")
        req = {"Master PCN", "Final Subdivision", "Unified Subdivision"}
        if not req.issubset(set(df.columns)):
            continue
        df = df.copy()
        df["pcn10"] = df["Master PCN"].apply(_clean_pcn).str[:10]
        df["final_subdivision"] = df["Final Subdivision"].astype(str).str.strip()
        df["unified_subdivision"] = df["Unified Subdivision"].astype(str).str.strip()
        frames.append(df[["pcn10", "final_subdivision", "unified_subdivision"]])
    if not frames:
        return pd.DataFrame(columns=["pcn10", "final_subdivision", "unified_subdivision"])
    out = pd.concat(frames, ignore_index=True).drop_duplicates()
    return out


def resolve_market_scope(subject_pcn10: str, subject_final_subdivision: str = "") -> Dict[str, Set[str]]:
    """
    Given subject pcn10, return sibling pcn10 and subdivision sets from unified grouping.
    """
    lkp = load_lookup_table()
    pcn10 = _clean_pcn(subject_pcn10)[:10]
    if lkp.empty or not pcn10:
        return {
            "subject_pcn10": pcn10,
            "pcn10_set": {pcn10} if pcn10 else set(),
            "final_subdivision_set": {subject_final_subdivision} if subject_final_subdivision else set(),
            "unified_subdivision_set": set(),
        }

    direct = lkp[lkp["pcn10"] == pcn10]
    unified_set = set(direct["unified_subdivision"].dropna().astype(str).str.strip().tolist())
    final_set = set(direct["final_subdivision"].dropna().astype(str).str.strip().tolist())

    if subject_final_subdivision:
        final_set.add(subject_final_subdivision.strip())

    if unified_set:
        fam = lkp[lkp["unified_subdivision"].isin(unified_set)]
    else:
        fam = direct

    pcn10_set = set(fam["pcn10"].dropna().astype(str).str.strip().tolist())
    fam_final = set(fam["final_subdivision"].dropna().astype(str).str.strip().tolist())
    final_set.update(fam_final)

    return {
        "subject_pcn10": pcn10,
        "pcn10_set": {x for x in pcn10_set if x},
        "final_subdivision_set": {x for x in final_set if x},
        "unified_subdivision_set": {x for x in unified_set if x},
    }
