from dataclasses import dataclass
from typing import Optional


@dataclass
class SubjectProfile:
    listing_number: str
    status: Optional[str]
    calculated_status: Optional[str]
    parcel_id: str
    pcn_10_digit: str
    city: Optional[str]
    geo_zone: Optional[str]
    property_type: Optional[str]
    final_subdivision: Optional[str]
    development_name: Optional[str]
    short_address: Optional[str]
    geo_lat: Optional[float]
    geo_lon: Optional[float]
    sqft_living: Optional[float]
    lot_sqft: Optional[float]
    total_bedrooms: Optional[int]
    baths_total: Optional[float]
    year_built: Optional[int]
    unit_floor: Optional[float]
    total_floors_stories: Optional[int]
    waterfront: Optional[int]
    private_pool: Optional[int]
    storm_protection_impact_glass: Optional[int]
    construction_cbs: Optional[int]
    garage_spaces: Optional[float]
    year_roof_installed: Optional[int]
    public_remarks: Optional[str]
    sold_date: Optional[str]
    sold_price: Optional[float]
    list_price: Optional[float]
    hoa_poa_coa_monthly: Optional[float] = None
    membership_fee: Optional[float] = None


@dataclass
class CompScore:
    listing_number: str
    sold_date: str
    sold_price: float
    sqft_living: float
    ppsf: float
    similarity_score: float
    recency_multiplier: float
    final_score: float
    location_points: float
    base_points: float
    feature_points: float
    bucket: str
    recency_days: int
    distance_miles: Optional[float]
    final_subdivision: Optional[str]
    city: Optional[str]
    lot_sqft: Optional[float] = None
    year_built: Optional[int] = None
    year_roof_installed: Optional[int] = None
    waterfront: Optional[int] = None
    private_pool: Optional[int] = None
    storm_protection_impact_glass: Optional[int] = None
    public_remarks: Optional[str] = None
