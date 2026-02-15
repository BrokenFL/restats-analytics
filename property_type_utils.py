import pandas as pd


SINGLE_FAMILY_VALUE = "Single Family Home"
CONDO_TH_OTHER_VALUE = "Condo/TH/Other"


def canonical_property_type(raw_value):
    """
    Canonicalize property type to one of:
    - Single Family Home
    - Condo/TH/Other
    Returns None only for truly missing values.
    """
    if raw_value is None:
        return None
    s = str(raw_value).strip()
    if not s:
        return None
    if s.lower() in {"nan", "none", "null", "n/a", "na"}:
        return None

    upper = s.upper()
    single_family_tokens = {
        "SF",
        "SINGLE FAMILY",
        "SINGLE-FAMILY",
        "SINGLE FAMILY HOME",
        "SFH",
    }
    if upper in single_family_tokens or "SINGLE FAMILY" in upper:
        return SINGLE_FAMILY_VALUE

    return CONDO_TH_OTHER_VALUE


def canonical_property_type_series(series: pd.Series) -> pd.Series:
    return series.apply(canonical_property_type)
