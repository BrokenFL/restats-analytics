# FlexMLS 2026 Schema Mapping

Source sample reviewed:

- `/Users/brookesnader/Downloads/customexport - 2026-03-18T202429.646.csv`

This export has 88 source columns. The import path in `data_cleaning.py` now maps the high-value renamed FlexMLS fields onto the existing `listing_details` schema.

## Direct or renamed mappings

| FlexMLS 2026 header | Normalized column |
| --- | --- |
| `Listing Number` | `listing_number` |
| `Status` | `status` |
| `Status Change Date` | `status_change_date` |
| `Listing Contract Date` | `listing_date` |
| `Close Date` | `sold_date` |
| `Cancellation Date` | `cancel_date` |
| `Expiration Date` | `expiration_date` |
| `Under Contract Date` | `under_contract_date` |
| `Withdrawn Date` | `withdrawn_date` |
| `Temp Off Market Date` | `temp_off_market_date` |
| `Back on Market Date` | `fallthrough_date` |
| `List Price` | `list_price` |
| `Close Price` | `sold_price` |
| `Original List Price` | `original_list_price` |
| `Tax Year` | `tax_year` |
| `Association Fee` | `hoa_poa_coa_monthly` |
| `Membership Fee Amount` | `membership_fee` |
| `Parcel Number` | `parcel_id` |
| `Short Address` | `short_address` |
| `Postal Zip` | `zip_code` |
| `State Or Province` | `state_province` |
| `Subdivision Name` | `subdivision` |
| `Development Name` | `development_name` |
| `Street Number` | `street_number` |
| `Living Area Main` | `sqft_living` |
| `Building Area Main` | `sqft_total` |
| `Guest House Area Details: Living Area Guest House` | `sqft_guest_house` |
| `Year Built` | `year_built` |
| `Year Roof Installed` | `year_roof_installed` |
| `Bathrooms Full` | `baths_full` |
| `Bathrooms Half` | `baths_half` |
| `Bathrooms Total` | `baths_total` |
| `Garage Spaces` | `garage_spaces` |
| `Pool Private YN` | `private_pool` |
| `Guest House YN` | `guest_house` |
| `Furnished` | `furnished` |
| `Construction Materials: CBS` | `construction_cbs` |
| `Storm Protection: Accordian Shutters` | `storm_protection_accordion_shutters` |
| `Storm Protection: Impact Glass` | `storm_protection_impact_glass` |
| `Storm Protection: Panel Shutters` | `storm_protection_panel_shutters` |
| `Association Amenities: Tennis Court(s)` | `subdiv_amenities_tennis` |
| `Association Amenities: Pool` | `subdiv_amenities_pool` |
| `Association Amenities: Manager On Site` | `subdiv_amenities_manager_on_site` |
| `Association Amenities: Fitness Center` | `subdiv_amenities_fitness_center` |
| `Association Amenities: Elevator(s)` | `subdiv_amenities_elevator` |
| `Association Amenities: Golf Course` | `subdiv_amenities_golf_course` |
| `Association Amenities: Clubhouse` | `subdiv_amenities_clubhouse` |
| `Association Amenities: Gated` | `gated_community` |
| `Security Features: Gated with Guard` | `security_gate_manned` |
| `Security Features: Gated - No Guard` | `security_gate_unmanned` |
| `Security Features: Lobby - Attended` | `security_lobby` |
| `Security Features: Key Card Entry` | `security_doorman` |
| `Parking Features: Garage` | `parking_garage_building` |
| `Parking Features: Detached Garage` | `parking_garage_detached` |
| `Parking Features: Attached Garage` | `parking_covered` |
| `Parking Features: Open` | `parking_open` |
| `Unit Number` | `unit_number` |
| `Unit Floor #` | `unit_floor` |
| `Stories Total` | `total_floors_stories` |
| `Property Type` | `property_type` |
| `How Paid` | `terms_of_sale` |
| `Latitude` | `geo_lat` |
| `Longitude` | `geo_lon` |
| `Public Remarks` | `public_remarks` |
| `Tax Legal Description` | `legal_desc` |
| `Listing Agent` | `listing_agent` |
| `Listing Office` | `listing_office` |
| `Buyer Agent` | `buyer_agent` |
| `Buyer Office` | `buyer_office` |
| `Days On Market` | `days_on_market` |
| `Cumulative DOM` | `cumulative_dom` |

## Derived mappings

| Source | Normalized column | Rule |
| --- | --- | --- |
| `Lot Size Acres` | `lot_sqft` | Multiply by `43,560` |
| `Association Type: Homeowner Association` / `Association Type: Condominium` | `homeowners_assoc` | Store a simple text classification when either flag is present |

## PDF-confirmed conversion notes

Source:

- `/Users/brookesnader/Downloads/Field Name Changes.pdf`

This PDF confirms that several old Beaches MLS fields were not renamed 1:1. They were split into newer RESO-style fields, which explains why some legacy columns do not have a single direct replacement in the new export.

### Confirmed direct renames

| Old field | New field | Current handling |
| --- | --- | --- |
| `Sold Date` | `Close Date` | mapped |
| `Sold Price` | `Close Price` | mapped |
| `Fallthrough Date` | `Back on Market Date` | mapped |
| `SqFt - Total` | `Building Area Main` | mapped |
| `SqFt - Living` | `Living Area Main` | mapped |
| `Listing Date` | `Listing Contract Date` | mapped |
| `Parcel ID` | `Parcel Number` | mapped |
| `Terms of Sale` | `Buyer Financing` | partially mapped to `terms_of_sale` |
| `Legal Desc` | `Tax Legal Description` | mapped |
| `Ttl Units in Complex` | `Number Of Units In Community` | export field recognized; not yet normalized into a dedicated analytical rule |
| `Parking` | `Parking Features` | partial mapping for garage/open coverage |
| `Taxes` | `Tax Annual Amount` / `Tax Information` | `tax_year` handled; tax amount still needs explicit mapping when present in export |

### Confirmed field splits

These older fields were split into multiple new fields in FlexMLS/RESO. For these, a single alias is not enough:

| Old field | New RESO target(s) | Current status |
| --- | --- | --- |
| `Homeowners Assoc` | multiple association-related fields | partially handled via `homeowners_assoc`, `hoa_poa_coa_monthly`, `association_fee`, `association_type` inputs |
| `Subdiv. Amenities` | `Association Amenities` | partially handled for current amenity booleans |
| `Maintenance Fee Incl` | `Association Fee Includes` | only elevator-related case appears in sample export; not fully mapped |
| `Exterior Features` / `Improvements` / `Miscellaneous 1` / `Security` | `Fencing` / `Interior Features` / other feature fields | not broadly mapped; only sampled security/feature booleans currently covered |
| `Lot Description` / `Acreage Description` / `Lot SqFt` | `Lot Features` / `Lot Size Area` / road-related fields | partially handled through `lot_sqft` derivation and acreage flags still unresolved |
| `Waterfront Details` | `Water Access` and `Waterfront Features` | not yet mapped |
| `Porch/Patio/Balcony` and `Exterior Features` | `Outdoor Living Spaces YN` plus balcony/courtyard/patio/porch detail fields | not yet mapped |
| `Utilities` | `Sewer` / `Water Source` | not yet mapped |
| `Pet Restrictions` | `Pets Allowed` | not yet mapped |

### Notable renamed fields we have not implemented yet

These are PDF-confirmed, but they are either absent from the sampled export or currently not used by the pipeline:

- `Go Active Date` -> `Start Showing Date`
- `List Type` -> `Listing Agreement`
- `Type` -> `Property Sub Type`
- `View` -> `Water View`
- `Window Treatments` -> `Window Features`
- `Special Info` -> `Zoning Information`
- `Road Frontage Type` / `Road Surface Type`
- `Land Lease YN` / `Lease Info` -> `Land Lease Information` / `Recreation Lease Info`

## Still unmapped or low-confidence

These columns exist in the new export but do not have a confident normalized target yet:

- `Direction Faces`
- `Area`
- `High School`
- `Association Reserves YN`
- `Association Fee Includes: Elevator`
- `Total Units In Building`
- `Number Of Units In Community`
- `Lot Size Dimensions`
- `Acreage Description: *`
- `Buyer Financing`
- `Lot Size Area`
- `Outdoor Living Spaces YN`
- `Water Access`
- `Waterfront Features`
- `Water View`
- `Start Showing Date`

These should be handled in a second pass after we verify where the old pipeline actually used them, if at all.
