import pandas as pd


SINGLE_FAMILY_VALUE = "Single Family Home"
CONDO_TH_OTHER_VALUE = "Condo/TH/Other"
PROPERTY_TYPE_DETAIL_MAP = {
    "SF": SINGLE_FAMILY_VALUE,
    "SFH": SINGLE_FAMILY_VALUE,
    "SINGLE FAMILY": SINGLE_FAMILY_VALUE,
    "SINGLE-FAMILY": SINGLE_FAMILY_VALUE,
    "SINGLE FAMILY HOME": SINGLE_FAMILY_VALUE,
    "SINGLE FAMILY RESIDENCE": SINGLE_FAMILY_VALUE,
    "CN": "Condo",
    "CONDO": "Condo",
    "CONDOMINIUM": "Condo",
    "TH": "Townhouse",
    "TOWNHOUSE": "Townhouse",
    "TOWNHOME": "Townhouse",
    "VL": "Villa",
    "VILLA": "Villa",
    "CO": "Co-Op",
    "CO-OP": "Co-Op",
    "COOP": "Co-Op",
    "SC": "Stock Cooperative",
    "STOCK COOPERATIVE": "Stock Cooperative",
    "MH": "Manufactured Home",
    "MANUFACTURED HOME": "Manufactured Home",
    "MO": "Mobile Home",
    "MOBILE HOME": "Mobile Home",
}


def canonical_property_type(raw_value):
    """
    Canonicalize MLS property type/subtype values while preserving useful detail.
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
    if upper in PROPERTY_TYPE_DETAIL_MAP:
        return PROPERTY_TYPE_DETAIL_MAP[upper]
    if upper.startswith("SINGLE FAMILY"):
        return SINGLE_FAMILY_VALUE

    return s


def property_group_for_type(raw_value):
    normalized = canonical_property_type(raw_value)
    if normalized is None:
        return None
    upper = normalized.upper()
    if upper == SINGLE_FAMILY_VALUE.upper() or upper.startswith("SINGLE FAMILY"):
        return SINGLE_FAMILY_VALUE
    return CONDO_TH_OTHER_VALUE


def is_single_family_type(raw_value) -> bool:
    return property_group_for_type(raw_value) == SINGLE_FAMILY_VALUE


def canonical_property_type_series(series: pd.Series) -> pd.Series:
    return series.apply(canonical_property_type)
