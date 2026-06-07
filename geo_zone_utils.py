from typing import Optional


# Palm Beach zone boundaries (official landmark lines provided by user).
# Applies only for records where city == "Palm Beach".
PALM_BEACH_WELLS_RD_LAT = 26.725636
PALM_BEACH_WORTH_AVE_LAT = 26.700837
PALM_BEACH_SLOANS_CURVE_LAT = 26.647377
PALM_BEACH_OCEAN_AVE_LAT = 26.594029
# Small tolerance for GPS/rounding drift at strict boundary lines (~11 meters).
PALM_BEACH_LAT_EPSILON = 0.0001
PALM_BEACH_SOUTH_OCEAN_CORRIDOR_MIN_LAT = 26.58
PALM_BEACH_SOUTH_OCEAN_CORRIDOR_LON_MIN = -80.06
PALM_BEACH_SOUTH_OCEAN_CORRIDOR_LON_MAX = -80.02
PALM_BEACH_ADDRESS_ZONE_PREFIXES = {
    "100 SUNRISE AVENUE": "Mid-Town",
    "235 SUNRISE AVENUE": "Mid-Town",
    "235 SUNRISE AVE": "Mid-Town",
    "238 PHIPPS PLAZA": "Mid-Town",
    "330 S OCEAN BOULEVARD": "Mid-Town",
    "330 S OCEAN BLVD": "Mid-Town",
}
PALM_BEACH_SOUTH_END_ADDRESS_PREFIXES = (
    "2295 S OCEAN BOULEVARD",
    "3100 S OCEAN BOULEVARD",
    "3450 S OCEAN BOULEVARD",
    "3456 S OCEAN BOULEVARD",
    "3474 S OCEAN BLVD",
    "3475 S OCEAN BOULEVARD",
    "3525 S OCEAN BOULEVARD",
    "3540 S OCEAN BOULEVARD",
    "3540 S OCEAN BLVD",
    "3545 S OCEAN BOULEVARD",
    "3546 S OCEAN BOULEVARD",
    "3546 SOUTH OCEAN",
    "3550 S OCEAN BOULEVARD",
    "3560 S OCEAN BOULEVARD",
    "3575 S OCEAN BOULEVARD",
    "3580 S OCEAN",
    "3581 S OCEAN BOULEVARD",
    "3589 S OCEAN BOULEVARD",
    "3590 S OCEAN BOULEVARD",
    "3601 S OCEAN BOULEVARD",
    "3605 S OCEAN BOULEVARD",
    "3610 S OCEAN BOULEVARD",
    "4000 S OCEAN BOULEVARD",
    "4001 S OCEAN BOULEVARD",
    "4201 S OCEAN BOULEVARD",
    "4500 S OCEAN BOULEVARD",
    "4501 S OCEAN BOULEVARD",
)


def classify_palm_beach_zone(
    lat: Optional[float],
    city: Optional[str],
    short_address: Optional[str] = None,
) -> Optional[str]:
    """
    Classify Palm Beach geo zone by latitude landmark bands:
    - North End: Wells Rd and north
    - Mid-Town: Worth Ave north to Wells Rd
    - Estate Section: Sloan's Curve north to Worth Ave
    - South End: Ocean Ave north to Sloan's Curve

    South Ocean condo corridor records just below Ocean Ave are grouped with
    South End when the MLS city is Palm Beach and the coordinates stay on-island.
    Returns None for non-Palm Beach or points outside the Palm Beach island scope.
    """
    if city is None:
        return None
    try:
        city_norm = str(city).strip().upper()
    except Exception:
        return None

    if city_norm != "PALM BEACH":
        return None
    if short_address:
        addr = str(short_address).strip().upper()
        for prefix, zone in PALM_BEACH_ADDRESS_ZONE_PREFIXES.items():
            if addr.startswith(prefix):
                return zone
        for prefix in PALM_BEACH_SOUTH_END_ADDRESS_PREFIXES:
            if addr.startswith(prefix):
                return "South End"
    if lat is None:
        return None
    try:
        lat_f = float(lat)
    except Exception:
        return None
    if lat_f < (PALM_BEACH_OCEAN_AVE_LAT - PALM_BEACH_LAT_EPSILON):
        return None
    if lat_f < PALM_BEACH_SLOANS_CURVE_LAT:
        return "South End"
    if lat_f < PALM_BEACH_WORTH_AVE_LAT:
        return "Estate Section"
    if lat_f < PALM_BEACH_WELLS_RD_LAT:
        return "Mid-Town"
    return "North End"


def classify_palm_beach_zone_from_coords(
    lat: Optional[float],
    lon: Optional[float],
    city: Optional[str],
    short_address: Optional[str] = None,
) -> Optional[str]:
    """
    Coordinate-aware wrapper that keeps obvious off-island/bad geocodes out of
    Palm Beach zones while grouping the South Ocean condo corridor as South End.
    """
    zone = classify_palm_beach_zone(lat, city, short_address=short_address)
    if zone is not None:
        return zone
    if lat is None or lon is None or city is None:
        return None
    try:
        city_norm = str(city).strip().upper()
        lat_f = float(lat)
        lon_f = float(lon)
    except Exception:
        return None
    if city_norm != "PALM BEACH":
        return None
    if (
        PALM_BEACH_SOUTH_OCEAN_CORRIDOR_MIN_LAT <= lat_f < (PALM_BEACH_OCEAN_AVE_LAT - PALM_BEACH_LAT_EPSILON)
        and PALM_BEACH_SOUTH_OCEAN_CORRIDOR_LON_MIN <= lon_f <= PALM_BEACH_SOUTH_OCEAN_CORRIDOR_LON_MAX
    ):
        return "South End"
    return None


def classify_palm_beach_south_end(
    lat: Optional[float],
    city: Optional[str],
    short_address: Optional[str] = None,
) -> Optional[str]:
    """
    Backward-compatible helper used by existing callers.
    """
    zone = classify_palm_beach_zone(lat, city, short_address=short_address)
    return "South End" if zone == "South End" else None
