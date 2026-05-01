import re

import pandas as pd


EXCLUDED_CABANA_BUILDINGS = {
    "235 SUNRISE AVENUE",
    "235 SUNRISE AVE",
}


def get_building(addr: str) -> str:
    addr = str(addr or "").upper()
    match = re.match(r"^(\d+)\s+([NSEW]?\s*\w+\s+(?:BLVD|AVE|RD|DR|WAY|PL|ROW|LN|CT|CIRCLE))", addr)
    if match:
        return f"{match.group(1)} {match.group(2).strip()}"
    parts = addr.split()
    if len(parts) >= 3:
        return " ".join(parts[:3])
    return addr


def is_excluded_building(building: str) -> bool:
    b = str(building or "").upper().strip()
    if b in EXCLUDED_CABANA_BUILDINGS:
        return True
    return b.startswith("235 SUNRISE AVE") or b.startswith("235 SUNRISE AVENUE")


def is_cabana_address(addr: str) -> bool:
    addr = str(addr or "").upper()
    has_c = bool(re.search(r"\bC(?:\s|-)?\d{1,3}[A-Z]?\b", addr))
    has_cs = bool(re.search(r"\bCS\d{1,3}\b", addr))
    has_zero_unit = bool(re.search(r" 0\d{2,3}[A-Z]?$", addr))
    has_stg = any(token in addr for token in (" STG", "STORAGE", " PARKING", " PK "))
    has_cabana_word = "CABANA" in addr
    return has_c or has_cs or has_zero_unit or has_stg or has_cabana_word


def likely_cabana_mask(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(False, index=df.index)

    short_address = df.get("short_address", pd.Series("", index=df.index)).fillna("").astype(str)
    legal_desc = df.get("legal_desc", pd.Series("", index=df.index)).fillna("").astype(str)
    public_remarks = df.get("public_remarks", pd.Series("", index=df.index)).fillna("").astype(str)
    unit_number = df.get("unit_number", pd.Series("", index=df.index)).fillna("").astype(str)

    addr_upper = short_address.str.upper()
    legal_upper = legal_desc.str.upper()
    remarks_upper = public_remarks.str.upper()
    unit_upper = unit_number.str.upper().str.strip()

    building = addr_upper.apply(get_building)
    excluded = building.apply(is_excluded_building)

    address_signal = addr_upper.apply(is_cabana_address)
    legal_signal = legal_upper.str.contains(r"\bCABANA\b|\bSTORAGE\b|\bPARKING\b|\bPK\b", regex=True, na=False)
    remarks_signal = remarks_upper.str.contains(r"\bCABANA\b|\bSTORAGE\b|\bPARKING\b|\bPK\b", regex=True, na=False)
    unit_signal = unit_upper.str.contains(r"^(?:C\d{1,3}[A-Z]?|CS\d{1,3}|0\d{2,3}[A-Z]?)$", regex=True, na=False)

    beds = pd.to_numeric(df.get("total_bedrooms", pd.Series(index=df.index)), errors="coerce")
    sqft = pd.to_numeric(df.get("sqft_living", pd.Series(index=df.index)), errors="coerce")
    sold_price = pd.to_numeric(df.get("sold_price", pd.Series(index=df.index)), errors="coerce")
    list_price = pd.to_numeric(df.get("list_price", pd.Series(index=df.index)), errors="coerce")
    low_price = sold_price.fillna(list_price).fillna(0)

    small_accessory_signal = (beds.fillna(0) <= 0) & (sqft.fillna(0) < 400) & (low_price > 0) & (low_price < 500000)

    return (~excluded) & (address_signal | legal_signal | remarks_signal | unit_signal | small_accessory_signal)
