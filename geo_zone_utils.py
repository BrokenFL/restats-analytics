from typing import Optional


# Palm Beach zone boundaries (official landmark lines provided by user).
# Applies only for records where city == "Palm Beach".
PALM_BEACH_WELLS_RD_LAT = 26.725636
PALM_BEACH_WORTH_AVE_LAT = 26.700837
PALM_BEACH_SLOANS_CURVE_LAT = 26.647377
PALM_BEACH_OCEAN_AVE_LAT = 26.594029
# Small tolerance for GPS/rounding drift at strict boundary lines (~11 meters).
PALM_BEACH_LAT_EPSILON = 0.0001
PALM_BEACH_SOUTH_END_ADDRESS_PREFIXES = (
    "3475 S OCEAN BOULEVARD",
    "3575 S OCEAN BOULEVARD",
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

    Returns None for non-Palm Beach or points south of Ocean Ave.
    """
    if lat is None or city is None:
        return None
    try:
        city_norm = str(city).strip().upper()
        lat_f = float(lat)
    except Exception:
        return None

    if city_norm != "PALM BEACH":
        return None
    if short_address:
        addr = str(short_address).strip().upper()
        for prefix in PALM_BEACH_SOUTH_END_ADDRESS_PREFIXES:
            if addr.startswith(prefix):
                return "South End"
    if lat_f < (PALM_BEACH_OCEAN_AVE_LAT - PALM_BEACH_LAT_EPSILON):
        return None
    if lat_f < PALM_BEACH_SLOANS_CURVE_LAT:
        return "South End"
    if lat_f < PALM_BEACH_WORTH_AVE_LAT:
        return "Estate Section"
    if lat_f < PALM_BEACH_WELLS_RD_LAT:
        return "Mid-Town"
    return "North End"


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
