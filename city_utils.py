"""Shared city-name normalization for MLS and county imports."""

from __future__ import annotations

import re


_ZIP_SUFFIX_RE = re.compile(r"\s+\d{5}(?:-\d{4})?$")
_CANONICAL_CITY_NAMES = {
    "boca raton": "Boca Raton",
    "delray beach": "Delray Beach",
    "palm beach": "Palm Beach",
    "south palm beach": "South Palm Beach",
    "west palm beach": "West Palm Beach",
    "wellington": "Wellington",
}


def canonical_city_name(value: object) -> str | None:
    """Return one stable city label, removing ZIP suffixes from municipality exports."""
    if value is None:
        return None
    text = " ".join(str(value).strip().split())
    if not text or text.casefold() in {"nan", "none", "null"}:
        return None
    text = _ZIP_SUFFIX_RE.sub("", text).strip()
    if not text:
        return None
    return _CANONICAL_CITY_NAMES.get(text.casefold(), text.title())


def normalize_city_values_in_db(conn) -> int:
    """Normalize existing SQLite city values and return the number of updates."""
    rows = conn.execute(
        "SELECT listing_number, city FROM listing_details WHERE city IS NOT NULL"
    ).fetchall()
    updates = []
    for listing_number, city in rows:
        canonical = canonical_city_name(city)
        if canonical and canonical != str(city).strip():
            updates.append((canonical, listing_number))
    if updates:
        conn.executemany(
            "UPDATE listing_details SET city = ? WHERE listing_number = ?",
            updates,
        )
        conn.commit()
    return len(updates)
