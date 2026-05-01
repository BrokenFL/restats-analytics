import argparse
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd


def _clean_text(value: str) -> str:
    if value is None:
        return ""
    s = str(value).upper().strip()
    s = s.replace("\u2014", "-")
    s = re.sub(r"\s+", " ", s)
    return s


def normalize_subdivision(name: str) -> str:
    """
    Normalize noisy PAPA subdivision names into a stable key.
    """
    s = _clean_text(name)
    if not s:
        return ""

    # Remove parenthetical content and known inactive tags.
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\bDEACTIVATED\b", " ", s)

    # Remove plat/book-page style references.
    s = re.sub(r"\bPB\s*\d+[A-Z0-9\-&,/ ]*", " ", s)
    s = re.sub(r"\bOR\s*\d+[A-Z0-9\-&,/ ]*", " ", s)
    s = re.sub(r"\bB\d+[A-Z0-9\-&,/ ]*", " ", s)

    # Remove filing/declaration tails that are legal metadata, not names.
    s = re.sub(r"\bDECL(?:ARATION)?\s+FILED\b.*$", " ", s)
    s = re.sub(r"\bFILED\b.*$", " ", s)
    s = re.sub(r"\bREPLAT OF PORTIONS OF\b", " REPLAT ", s)

    # Normalize punctuation to spaces but preserve alphanumerics.
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    # Common abbreviation normalization.
    s = re.sub(r"\bCTRY\b", "COUNTRY", s)

    # Token-level cleanup for common legal/plat suffixes.
    for pattern in [
        r"\bSUBDIVISION\b",
        r"\bSUB\b",
        r"\bREPLAT\b",
        r"\bRESUB\b",
        r"\bEXTENSION\b",
        r"\bADD(?:ITION)?\b",
        r"\bPLAT\b",
        r"\bPL\b",
        r"\bPHASE\b",
        r"\bPH\b",
        r"\bPAR(?:CEL)?\b",
        r"\bSEC(?:TION)?\b",
        r"\bPUD\b",
        r"\bUNIT\b",
        r"\bNO\b",
        r"\bIN\b",
    ]:
        s = re.sub(pattern, " ", s)

    # Remove orphan numeric/roman tokens left by plat/phase suffixes.
    s = re.sub(r"\b\d+(?:ST|ND|RD|TH)?\b", " ", s)
    s = re.sub(r"\b[IVX]+\b", " ", s)

    s = re.sub(r"\s+", " ", s).strip()
    return s


def _family_group_key(name: str) -> str:
    """
    Aggressive key for grouping likely same subdivision family.
    """
    s = _clean_text(name)
    if not s:
        return ""
    s = re.sub(r"\b(COND|CONDO|CONDOMINIUM|CONDOMINIUMS|CO OP|CO-OP|APTS?|TOWNHOMES?)\b", " ", s)
    s = re.sub(r"\b(DECL|FILED|AS)\b", " ", s)
    s = re.sub(r"\b(OF|AT|THE|IN|ON)\b", " ", s)
    s = re.sub(
        r"\b(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|"
        r"1ST|2ND|3RD|4TH|5TH|6TH|7TH|8TH|9TH|10TH|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN)\b",
        " ",
        s,
    )
    s = re.sub(
        r"\b(PART|UNIT|NO|NUMBER|PHASE|PH|PLAT|PL|SECTION|SEC|REPLAT|REPL|REV|REVISED|AMND|AMEND|ADD|ADDITION|PAR|PARCEL|PUD|TRS|FT|DEF|BLK)\b",
        " ",
        s,
    )
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(r"\b\d+[A-Z]?\b", " ", s)
    s = re.sub(r"\b[A-Z]\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _family_label(name: str) -> str:
    """
    Less aggressive canonical family label, preserving natural words like AT/OF/THE.
    """
    s = _clean_text(name)
    if not s:
        return ""
    s = re.sub(r"\b(COND|CONDO|CONDOMINIUM|CONDOMINIUMS|CO OP|CO-OP|APTS?)\b", " ", s)
    s = re.sub(r"\bDECL(?:ARATION)?\b.*$", " ", s)
    s = re.sub(
        r"\b(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|"
        r"1ST|2ND|3RD|4TH|5TH|6TH|7TH|8TH|9TH|10TH|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN)\b",
        " ",
        s,
    )
    s = re.sub(
        r"\b(PART|UNIT|NO|NUMBER|PHASE|PH|PLAT|PL|SECTION|SEC|REPLAT|REPL|REV|REVISED|AMND|AMEND|ADD|ADDITION|PAR|PARCEL|PUD|TRS|FT|DEF|BLK)\b",
        " ",
        s,
    )
    s = re.sub(r"\b\d+[A-Z]?\b", " ", s)
    s = re.sub(r"\b[A-Z]\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _core_token_set(name: str) -> frozenset:
    """
    Order-insensitive token set for matching near-identical family names.
    """
    s = _clean_text(name)
    if not s:
        return frozenset()
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    tokens = [t for t in s.split() if t]
    drop = {
        "THE", "OF", "AT", "IN", "ON", "AND", "TO", "AS",
        "COND", "CONDO", "CONDOMINIUM", "CONDOMINIUMS", "CO", "OP", "APTS", "APT",
        "DECL", "FILED", "REPL", "REPLAT", "REV", "REVISED", "AMND", "AMEND",
        "PART", "UNIT", "NO", "NUMBER", "PHASE", "PH", "PLAT", "PL",
        "SECTION", "SEC", "ADD", "ADDITION", "PAR", "PARCEL", "PUD",
        "TRS", "FT", "DEF", "BLK",
        "FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH", "SEVENTH",
        "EIGHTH", "NINTH", "TENTH", "ONE", "TWO", "THREE", "FOUR", "FIVE",
        "SIX", "SEVEN", "EIGHT", "NINE", "TEN",
    }
    out = []
    for t in tokens:
        if t in drop:
            continue
        if re.fullmatch(r"\d+[A-Z]?", t):
            continue
        if len(t) == 1:
            continue
        out.append(t)
    return frozenset(out)


def _core_tokens_in_order(name: str) -> Tuple[str, ...]:
    """
    Order-preserving core tokens used for consecutive-word matching.
    """
    s = _clean_text(name)
    if not s:
        return tuple()
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    tokens = [t for t in s.split() if t]
    drop = {
        "THE", "OF", "AT", "IN", "ON", "AND", "TO", "AS",
        "COND", "CONDO", "CONDOMINIUM", "CONDOMINIUMS", "CO", "OP", "APTS", "APT",
        "DECL", "FILED", "REPL", "REPLAT", "REV", "REVISED", "AMND", "AMEND",
        "PART", "UNIT", "NO", "NUMBER", "PHASE", "PH", "PLAT", "PL",
        "SECTION", "SEC", "ADD", "ADDITION", "PAR", "PARCEL", "PUD",
        "TRS", "FT", "DEF", "BLK",
        "FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH", "SEVENTH",
        "EIGHTH", "NINTH", "TENTH", "ONE", "TWO", "THREE", "FOUR", "FIVE",
        "SIX", "SEVEN", "EIGHT", "NINE", "TEN",
    }
    out = []
    for t in tokens:
        if t in drop:
            continue
        if re.fullmatch(r"\d+[A-Z]?", t):
            continue
        if len(t) == 1:
            continue
        out.append(t)
    return tuple(out)


def _ngrams(tokens: Tuple[str, ...], n: int) -> set:
    if len(tokens) < n:
        return set()
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def _community_anchor(name: str) -> str:
    """
    Strong community markers used to prevent cross-community over-grouping.
    """
    s = _clean_text(name)
    anchor_patterns = [
        "WOODFIELD",
        "BROKEN SOUND",
        "BOCA WEST",
        "BOCAIRE",
        "BOCA WOODS",
        "ROYAL PALM POLO",
        "ST ANDREWS",
    ]
    for anchor in anchor_patterns:
        if re.search(rf"\b{re.escape(anchor)}\b", s):
            return anchor
    return ""


def _major_community_rollup(name: str) -> str:
    """
    Umbrella community rollup for major planned communities.
    """
    s = _clean_text(name)
    if not s:
        return ""

    rules = [
        (r"\bWOODFIELD(?:\s+CTRY)?\s+COUNTRY\s+CLUB\b", "WOODFIELD COUNTRY CLUB"),
        (r"\bBROKEN\s+SOUND\b", "BROKEN SOUND"),
        (r"\bBOCA\s+WEST\b", "BOCA WEST"),
        (r"\bBOCAIRE\b", "BOCAIRE"),
        (r"\bBOCA\s+WOODS\b", "BOCA WOODS"),
    ]
    for pat, label in rules:
        if re.search(pat, s):
            return label
    return ""


def _group_anchor_ok(g: pd.DataFrame) -> bool:
    anchor_values = g["_anchor"].fillna("").astype(str).str.strip()
    non_empty = {a for a in anchor_values if a}
    if len(non_empty) > 1:
        return False
    # Do not mix anchored and unanchored names in one auto-group operation.
    if len(non_empty) == 1 and (anchor_values == "").any():
        return False
    return True


def _pcn_locality_ok(g: pd.DataFrame) -> bool:
    pcn = g["Master PCN"].fillna("").astype(str).str.strip()
    pcn = pcn[pcn != ""]
    if pcn.empty:
        return False
    pcn_clean = pcn.str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
    pref6_counts = pcn.str[:6].value_counts()
    dominant_pref6_share = pref6_counts.iloc[0] / len(pcn)
    pref6_unique = pcn.str[:6].nunique()
    pref10_counts = pcn_clean.str[:10].value_counts()
    dominant_pref10_share = pref10_counts.iloc[0] / len(pcn_clean)
    pref10_unique = pcn_clean.str[:10].nunique()
    return (
        dominant_pref6_share >= 0.60
        or pref6_unique <= 2
        or dominant_pref10_share >= 0.80
        or pref10_unique <= 2
    )


def _choose_suggested_label(g: pd.DataFrame, canonical_col: str) -> str:
    labels = g[canonical_col].fillna("").astype(str).str.strip().apply(_family_label)
    labels = labels[labels != ""]
    if labels.empty:
        return ""
    label_counts = labels.value_counts()
    top_count = label_counts.iloc[0]
    top_labels = sorted(label_counts[label_counts == top_count].index, key=len)
    suggested = top_labels[0]

    has_condo = g[canonical_col].fillna("").astype(str).str.contains(
        r"\b(?:COND|CONDO|CONDOMINIUM|CO OP|CO-OP|APTS?)\b",
        case=False,
        regex=True,
    ).mean() >= 0.5
    if has_condo and "CONDOMINIUM" not in suggested and "CO OP" not in suggested:
        suggested = f"{suggested} CONDOMINIUMS"
    return suggested


def _apply_auto_grouping(df: pd.DataFrame, canonical_col: str = "Canonical Subdivision") -> pd.DataFrame:
    """
    Optional grouping pass for municipalities without a curated cheatsheet.
    Uses both name-family and Master PCN prefix proximity to avoid over-grouping.
    """
    out = df.copy()
    out["_group_key"] = out[canonical_col].apply(_family_group_key)
    out["_family_label"] = out[canonical_col].apply(_family_label)
    out["_anchor"] = out[canonical_col].apply(_community_anchor)

    # Pass 0: major community umbrella rollup.
    out["_major_rollup"] = out[canonical_col].apply(_major_community_rollup)
    major_mask = out["_major_rollup"].fillna("").astype(str).str.strip() != ""
    out.loc[major_mask, canonical_col] = out.loc[major_mask, "_major_rollup"]

    block_keys = {"DELRAY", "PARK", "ESTATES", "AVENUE", "S D", ""}
    for key, g in out.groupby("_group_key", dropna=False):
        if key in block_keys:
            continue
        unique_finals = g[canonical_col].fillna("").astype(str).str.strip().nunique()
        if unique_finals < 2:
            continue

        token_count = len(str(key).split())
        if token_count < 2:
            continue

        if not _group_anchor_ok(g):
            continue
        if not _pcn_locality_ok(g):
            continue

        suggested = _choose_suggested_label(g, canonical_col=canonical_col) or key

        out.loc[g.index, canonical_col] = suggested

    # Pass 2: token-set + PCN proximity (captures order-variant names).
    out["_token_set"] = out[canonical_col].apply(_core_token_set)
    generic_token_sets = {frozenset(), frozenset({"DELRAY"}), frozenset({"PARK"}), frozenset({"ESTATES"})}
    for tset, g in out.groupby("_token_set", dropna=False):
        if tset in generic_token_sets:
            continue
        if not isinstance(tset, frozenset) or len(tset) < 2:
            continue

        unique_finals = g[canonical_col].fillna("").astype(str).str.strip().nunique()
        if unique_finals < 2:
            continue

        if not _group_anchor_ok(g):
            continue
        if not _pcn_locality_ok(g):
            continue

        suggested = _choose_suggested_label(g, canonical_col=canonical_col)
        if not suggested:
            continue

        out.loc[g.index, canonical_col] = suggested

    # Pass 3: consecutive-word clustering (3-word, then strict 2-word).
    out["_core_tokens"] = out[canonical_col].apply(_core_tokens_in_order)
    out["_trigrams"] = out["_core_tokens"].apply(lambda t: _ngrams(t, 3))
    out["_bigrams"] = out["_core_tokens"].apply(lambda t: _ngrams(t, 2))

    generic_tokens = {"BOCA", "RATON", "DELRAY", "BEACH", "COUNTRY", "CLUB", "PARK", "ESTATES", "VILLAGE"}

    for ngram_col, n in [("_trigrams", 3), ("_bigrams", 2)]:
        ngram_map = defaultdict(list)
        for idx, grams in out[ngram_col].items():
            for gram in grams:
                if all(tok in generic_tokens for tok in gram):
                    continue
                ngram_map[gram].append(idx)

        for _, idxs in ngram_map.items():
            idxs = list(set(idxs))
            if len(idxs) < 2:
                continue
            g = out.loc[idxs]
            unique_finals = g[canonical_col].fillna("").astype(str).str.strip().nunique()
            if unique_finals < 2:
                continue
            # N-gram pass is only for small variant sets, not broad community rollups.
            if unique_finals > 4:
                continue
            # Do not run consecutive-word grouping inside anchored master communities.
            if (g["_anchor"].fillna("").astype(str).str.strip() != "").any():
                continue
            if not _group_anchor_ok(g):
                continue
            if not _pcn_locality_ok(g):
                continue

            # Build similarity-connected components so one good pair does not
            # collapse unrelated names that share a common 2/3-gram.
            names = sorted(g[canonical_col].fillna("").astype(str).str.strip().unique())
            names = [nm for nm in names if nm]
            if len(names) < 2:
                continue
            token_map = {nm: _core_token_set(nm) for nm in names}
            required = 0.80 if n == 3 else 0.85
            adj = {nm: set() for nm in names}
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    a_name = names[i]
                    b_name = names[j]
                    a = token_map[a_name]
                    b = token_map[b_name]
                    if not a or not b:
                        continue
                    jacc = len(a & b) / len(a | b)
                    subset = min(len(a & b) / len(a), len(a & b) / len(b))
                    if jacc >= required and subset >= required:
                        adj[a_name].add(b_name)
                        adj[b_name].add(a_name)

            seen = set()
            for nm in names:
                if nm in seen:
                    continue
                stack = [nm]
                comp = []
                while stack:
                    cur = stack.pop()
                    if cur in seen:
                        continue
                    seen.add(cur)
                    comp.append(cur)
                    stack.extend(list(adj[cur] - seen))
                if len(comp) < 2:
                    continue
                comp_rows = g[g[canonical_col].isin(comp)]
                suggested = _choose_suggested_label(comp_rows, canonical_col=canonical_col)
                if not suggested:
                    continue
                out.loc[comp_rows.index, canonical_col] = suggested

    # Pass 4: first-10-PCN locality + naming overlap.
    out["_pcn10"] = (
        out["Master PCN"]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.replace(r"[^A-Z0-9]", "", regex=True)
        .str[:10]
    )
    for p10, g in out.groupby("_pcn10", dropna=False):
        if not p10:
            continue
        unique_finals = g[canonical_col].fillna("").astype(str).str.strip().nunique()
        if unique_finals < 2:
            continue
        if unique_finals > 8:
            continue
        if not _group_anchor_ok(g):
            continue

        names = sorted(g[canonical_col].fillna("").astype(str).str.strip().unique())
        names = [n for n in names if n]
        if len(names) < 2:
            continue

        token_map = {n: _core_token_set(n) for n in names}
        generic_overlap = {
            "GOLF", "TENNIS", "CLUB", "COUNTRY", "CENTER", "CENTRE", "VILLAGE",
            "PARK", "ESTATES", "LANDING", "SQUARE", "PLACE", "COURT", "COMMONS",
        }
        adj = {n: set() for n in names}
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a = names[i]
                b = names[j]
                ta = token_map[a]
                tb = token_map[b]
                if not ta or not tb:
                    continue
                inter = len(ta & tb)
                union = len(ta | tb)
                jacc = inter / union if union else 0.0
                subset = min(inter / len(ta), inter / len(tb))
                shared_distinct = (ta & tb) - generic_overlap
                if inter >= 2 and shared_distinct and (jacc >= 0.60 or subset >= 0.85):
                    adj[a].add(b)
                    adj[b].add(a)

        visited = set()
        for n0 in names:
            if n0 in visited:
                continue
            stack = [n0]
            comp = []
            while stack:
                cur = stack.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                comp.append(cur)
                stack.extend(list(adj[cur] - visited))

            if len(comp) < 2:
                continue
            comp_idx = g[g[canonical_col].isin(comp)].index
            comp_rows = out.loc[comp_idx]
            suggested = _choose_suggested_label(comp_rows, canonical_col=canonical_col)
            if not suggested:
                continue
            out.loc[comp_idx, canonical_col] = suggested

    # Pass 5: consecutive 3-word phrase rollup with locality guardrails.
    # This captures "X Y Z" community phrases across variants (e.g., WOODFIELD COUNTRY CLUB ...).
    out["_core_tokens"] = out[canonical_col].apply(_core_tokens_in_order)
    out["_trigrams"] = out["_core_tokens"].apply(lambda t: _ngrams(t, 3))
    trigram_rows = defaultdict(set)
    for idx, grams in out["_trigrams"].items():
        for gram in grams:
            trigram_rows[gram].add(idx)

    generic_tokens = {
        "COUNTRY", "CLUB", "PARK", "ESTATES", "VILLAGE", "CENTER", "CENTRE",
        "PLACE", "COURT", "COMMONS", "LANDING", "SQUARE",
    }
    for gram, idxs in sorted(trigram_rows.items(), key=lambda kv: -len(kv[1])):
        if len(idxs) < 2:
            continue
        # Keep phrases with at least one distinctive token.
        if all(tok in generic_tokens for tok in gram):
            continue
        g = out.loc[list(idxs)]
        unique_finals = g[canonical_col].fillna("").astype(str).str.strip().nunique()
        if unique_finals < 2:
            continue
        # Avoid massive broad rollups.
        if unique_finals > 16:
            continue
        if not _group_anchor_ok(g):
            continue
        if not _pcn_locality_ok(g):
            continue

        phrase = " ".join(gram).strip()
        if not phrase:
            continue

        # Prefer existing exact label if present, otherwise phrase.
        labels = g[canonical_col].fillna("").astype(str).str.strip()
        exact_phrase = labels[labels.str.upper() == phrase].head(1)
        suggested = exact_phrase.iloc[0] if not exact_phrase.empty else phrase
        out.loc[g.index, canonical_col] = suggested

    out = out.drop(
        columns=[
            "_group_key",
            "_family_label",
            "_token_set",
            "_anchor",
            "_core_tokens",
            "_trigrams",
            "_bigrams",
            "_pcn10",
            "_major_rollup",
        ],
        errors="ignore",
    )
    return out


def assign_neighborhood(normalized_name: str) -> str:
    n = _clean_text(normalized_name)

    if "EL CID" in n:
        return "El Cid Historic"
    if "PROSPECT PARK" in n:
        return "Prospect Park South"
    if "SOUTHLAND PARK" in n:
        return "Southland Park"
    if "CENTRAL PARK" in n:
        return "Central Park"
    if "WORTH COURT" in n:
        return "Worth Court"
    if "BELAIR" in n or "MIRAMAR" in n:
        return "SoSo / South End"
    if "FLAGLER PROMENADE" in n:
        return "Estates of South Palm Beach"
    if "EDMOR" in n:
        return "SoSo / South End"
    if "BURNUP" in n or "RUSSLYN" in n:
        return "South End Luxury"
    if "DEEP ROCK" in n:
        return "Deep Rock"
    if "FLAMINGO PARK" in n:
        return "Historic Neighborhoods"

    return "Other / Transitional"


def _build_cheatsheet_maps(cheatsheet_csv: Path) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Build lookup maps from the audit cheatsheet:
    - raw_map: exact raw name match (upper/trim)
    - norm_map: normalized-name match
    """
    cdf = pd.read_csv(cheatsheet_csv)
    required = {"Name", "Unified Subdivision"}
    missing = [c for c in required if c not in cdf.columns]
    if missing:
        raise ValueError(
            f"Cheatsheet missing required columns: {missing}. "
            f"Found: {list(cdf.columns)}"
        )

    cdf = cdf.copy()
    cdf["canonical"] = cdf["Unified Subdivision"].fillna("").astype(str).str.strip()
    cdf = cdf[cdf["canonical"] != ""]

    raw_map = {}
    norm_map = {}
    for _, row in cdf.iterrows():
        raw = _clean_text(row["Name"])
        canon = str(row["canonical"]).strip()
        if raw and raw not in raw_map:
            raw_map[raw] = canon

        norm = normalize_subdivision(row["Name"])
        if norm and norm not in norm_map:
            norm_map[norm] = canon
    return raw_map, norm_map


def build_lookup(
    input_csv: Path,
    output_csv: Path,
    name_col: str = "Name",
    cheatsheet_csv: Optional[Path] = None,
    auto_group: bool = False,
) -> Path:
    df = pd.read_csv(input_csv)
    if name_col not in df.columns:
        raise ValueError(f"Column '{name_col}' not found. Available columns: {list(df.columns)}")

    df["Normalized Name"] = df[name_col].apply(normalize_subdivision)
    df["Canonical Subdivision"] = df["Normalized Name"]
    df["Match Source"] = "rule_fallback"

    if cheatsheet_csv:
        raw_map, norm_map = _build_cheatsheet_maps(cheatsheet_csv)
        raw_keys = df[name_col].apply(_clean_text)

        exact_canonical = raw_keys.map(raw_map)
        norm_canonical = df["Normalized Name"].map(norm_map)
        chosen = exact_canonical.combine_first(norm_canonical)

        exact_hit = exact_canonical.notna()
        norm_hit = (~exact_hit) & norm_canonical.notna()

        df.loc[chosen.notna(), "Canonical Subdivision"] = chosen[chosen.notna()]
        df.loc[exact_hit, "Match Source"] = "cheatsheet_exact"
        df.loc[norm_hit, "Match Source"] = "cheatsheet_normalized"
    elif auto_group:
        df = _apply_auto_grouping(df, canonical_col="Canonical Subdivision")
        df["Match Source"] = "auto_grouped"

    # Output schema intentionally mirrors palmbeach_subdivision_audit_cheatsheet.csv
    # so downstream scripts can use one consistent contract.
    final = pd.DataFrame()
    for col in ["Master PCN", "Name", "Book", "Page", "Year"]:
        final[col] = df[col] if col in df.columns else ""

    # Keep Final as raw-normalized; Unified is the canonical/grouped target.
    final["Final Subdivision"] = df["Normalized Name"]
    final["Unified Subdivision"] = df["Canonical Subdivision"]
    final = final.sort_values(by=["Unified Subdivision", "Name"], na_position="last")

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    final.to_csv(output_csv, index=False)
    return output_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize PAPA subdivision names into a lookup CSV.")
    parser.add_argument(
        "--input",
        required=True,
        help="Path to source CSV (example: 'PAPA - Advanced Sales Search (2).csv').",
    )
    parser.add_argument(
        "--output",
        default="wpb_master_subdivision_lookup.csv",
        help="Path for normalized output CSV.",
    )
    parser.add_argument(
        "--name-column",
        default="Name",
        help="Subdivision source column name in the input CSV.",
    )
    parser.add_argument(
        "--audit-cheatsheet",
        help=(
            "Optional canonical mapping CSV with columns 'Name' and "
            "'Unified Subdivision' (example: palmbeach_subdivision_audit_cheatsheet.csv)."
        ),
    )
    parser.add_argument(
        "--auto-group",
        action="store_true",
        help=(
            "Apply heuristic grouping (name-family + Master PCN prefix checks) "
            "when no audit cheatsheet is provided."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_csv = Path(args.input).expanduser().resolve()
    output_csv_arg = Path(args.output).expanduser()
    output_csv = (Path.cwd() / output_csv_arg).resolve() if not output_csv_arg.is_absolute() else output_csv_arg.resolve()
    cheatsheet_csv = Path(args.audit_cheatsheet).expanduser().resolve() if args.audit_cheatsheet else None

    if not input_csv.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_csv}")
    if cheatsheet_csv and not cheatsheet_csv.exists():
        raise FileNotFoundError(f"Audit cheatsheet CSV not found: {cheatsheet_csv}")

    out = build_lookup(
        input_csv=input_csv,
        output_csv=output_csv,
        name_col=args.name_column,
        cheatsheet_csv=cheatsheet_csv,
        auto_group=args.auto_group,
    )
    print(f"Subdivision lookup generated successfully: {out}")


if __name__ == "__main__":
    main()
