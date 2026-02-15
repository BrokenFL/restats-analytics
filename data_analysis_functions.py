import pandas as pd
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta

# ================================================================
# PERIOD INDEX HELPERS
# ================================================================

def get_period_range(start_date_str, end_date_str, freq):
    freq_map = {
        "monthly": "M",
        "quarterly": "Q",
        "annually": "A"
    }
    start = pd.Timestamp(start_date_str)
    end = pd.Timestamp(end_date_str)
    return pd.period_range(start=start, end=end, freq=freq_map[freq])

def label_period(period, freq):
    if freq == "monthly":
        return period.strftime("%b %Y")
    if freq == "quarterly":
        return f"Q{period.quarter} {period.year}"
    if freq == "annually":
        return str(period.year)
    return str(period)

# ================================================================
# UNIVERSAL GROUP AGGREGATOR
# ================================================================

def safe_group_aggregation(df, date_col, value_col, agg_func, freq, start, end, out_col_name):
    if df.empty:
        return _empty_stat_shell(freq, start, end, out_col_name)

    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df[df[date_col].notna()]

    # Filter by date range (Inclusive of start and end)
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    df = df[(df[date_col] >= start_ts) & (df[date_col] <= end_ts)]

    # Group by Period (Month/Quarter/Year)
    df["PeriodIndex"] = df[date_col].dt.to_period({"monthly": "M", "quarterly": "Q", "annually": "A"}[freq])

    grouped = (
        df.groupby("PeriodIndex")[value_col]
        .agg(agg_func)
        .reset_index()
        .rename(columns={value_col: out_col_name})
    )

    return grouped

def _empty_stat_shell(freq, start, end, col):
    idx = get_period_range(start, end, freq)
    return pd.DataFrame({
        "PeriodIndex": idx,
        col: pd.NA
    })


def _active_snapshot_mask(df, snapshot_date):
    """
    Active-at-snapshot mask with protection against bad NULL end-dates.
    - If effective_active_end_date > snapshot -> include.
    - If effective_active_end_date is NULL, include only if status is active-ish.
    """
    activeish = df.get("status", pd.Series(index=df.index, dtype="object")).astype(str).str.upper().isin(
        ["A", "ACTIVE", "ACT", "COMING SOON", "CS"]
    )
    return (df["listing_date"] <= snapshot_date) & (
        (df["effective_active_end_date"] > snapshot_date)
        | (df["effective_active_end_date"].isna() & activeish)
    )

# ================================================================
# CORE METRIC FUNCTIONS
# ================================================================

def median_sold_price(df, freq, start, end):
    # Only sold items
    df = df[df["sold_price"].notna() & df["sold_date"].notna()].copy()
    return safe_group_aggregation(df, "sold_date", "sold_price", "median", freq, start, end, "Median Sold Price")

def median_price_per_sqft(df, freq, start, end):
    df = df.copy()
    df["sold_price"] = pd.to_numeric(df["sold_price"], errors="coerce")
    df["sqft_living"] = pd.to_numeric(df["sqft_living"], errors="coerce")
    
    # Only valid sales with sqft
    df = df[
        (df["sold_price"].notna()) & 
        (df["sqft_living"].notna()) & 
        (df["sqft_living"] > 0) & 
        (df["sold_date"].notna())
    ]
    df["PPSF"] = df["sold_price"] / df["sqft_living"]

    grouped = safe_group_aggregation(df, "sold_date", "PPSF", "median", freq, start, end, "Median Price Per SqFt")
    
    # Round to whole number
    if not grouped.empty:
        grouped["Median Price Per SqFt"] = grouped["Median Price Per SqFt"].round(0).astype("Int64")
    return grouped

def median_list_price(df, freq, start, end):
    # Snapshot based on active inventory
    df = df.copy()
    df["listing_date"] = pd.to_datetime(df["listing_date"], errors="coerce")
    df["effective_active_end_date"] = pd.to_datetime(df["effective_active_end_date"], errors="coerce")
    df["list_price"] = pd.to_numeric(df["list_price"], errors="coerce")
    
    # Filter valid data
    df = df[df["listing_date"].notna() & df["list_price"].notna()]
    
    period_idx = get_period_range(start, end, freq)
    out = []
    
    for period in period_idx:
        snapshot_date = period.to_timestamp(how='end')
        
        # Identify Active Listings at snapshot date
        active_mask = _active_snapshot_mask(df, snapshot_date)
        
        # Calculate Median of those active listings
        active_prices = df.loc[active_mask, "list_price"]
        median_price = active_prices.median() if not active_prices.empty else pd.NA
        
        out.append([period, median_price])
        
    return pd.DataFrame(out, columns=["PeriodIndex", "Median List Price"])

def median_list_price_per_sqft(df, freq, start, end):
    df = df.copy()
    df["listing_date"] = pd.to_datetime(df["listing_date"], errors="coerce")
    df["effective_active_end_date"] = pd.to_datetime(df["effective_active_end_date"], errors="coerce")
    df["list_price"] = pd.to_numeric(df["list_price"], errors="coerce")
    df["sqft_living"] = pd.to_numeric(df["sqft_living"], errors="coerce")
    
    # Filter valid data
    df = df[df["listing_date"].notna() & df["list_price"].notna() & (df["sqft_living"] > 0)]
    
    # Calculate PPSF
    df["ListPPSF"] = df["list_price"] / df["sqft_living"]
    
    period_idx = get_period_range(start, end, freq)
    out = []
    
    for period in period_idx:
        snapshot_date = period.to_timestamp(how='end')
        
        # Identify Active Listings at snapshot date
        active_mask = _active_snapshot_mask(df, snapshot_date)
        
        # Calculate Median of those active listings
        active_ppsf = df.loc[active_mask, "ListPPSF"]
        median_ppsf = active_ppsf.median() if not active_ppsf.empty else pd.NA
        
        # Round to whole number
        if pd.notna(median_ppsf):
            median_ppsf = round(median_ppsf)
        
        out.append([period, median_ppsf])
        
    return pd.DataFrame(out, columns=["PeriodIndex", "Median List Price Per SqFt"])

# --- UPDATED: SALES COUNT (Cumulative) ---
def sales_count(df, freq, start, end):
    """
    Counts ALL sales with a sold_date within the period.
    Example: Q1 Sales = Jan Sales + Feb Sales + Mar Sales.
    """
    df = df[df["sold_date"].notna()].copy()
    # Count rows (listing_number)
    return safe_group_aggregation(df, "sold_date", "listing_number", "count", freq, start, end, "Sales Count")

# --- NEW: TOTAL SALES VOLUME (Cumulative) ---
def total_sales_volume(df, freq, start, end):
    """
    Sums sold_price for all sales within the period.
    Example: Q1 Volume = Sum of all sold prices in Jan, Feb, Mar.
    """
    df = df[df["sold_date"].notna() & df["sold_price"].notna()].copy()
    # Sum sold_price
    return safe_group_aggregation(df, "sold_date", "sold_price", "sum", freq, start, end, "Total Sales Volume")

# --- UPDATED: NEW LISTINGS (Cumulative) ---
def new_listings(df, freq, start, end):
    """
    Counts ANY listing that was created (listing_date) within the period.
    Current status does NOT matter (it could be Sold, Cancelled, Active now).
    As long as listing_date is in the period, it counts as a New Listing.
    """
    df = df[df["listing_date"].notna()].copy()
    return safe_group_aggregation(df, "listing_date", "listing_number", "count", freq, start, end, "New Listings")

# --- NEW: PENDING SALES (New Contracts in Period) ---
def pending_sales(df, freq, start, end):
    """
    Counts listings that went under contract (under_contract_date) within the period.
    This represents new pending sales / contracts signed.
    """
    df = df[df["under_contract_date"].notna()].copy()
    return safe_group_aggregation(df, "under_contract_date", "listing_number", "count", freq, start, end, "Pending Sales")

def active_inventory(df, freq, start, end):
    """
    Count Active listings at end of each period.
    A listing was active at a point in time if:
    1. listing_date <= snapshot AND
    2. effective_active_end_date is NULL (still active) OR > snapshot (went off-market later)
    
    Note: This correctly counts historical inventory - a listing that is now Closed
    but was Active in Dec 2025 will count for Dec 2025 if effective_active_end_date > Dec 31.
    """
    if df.empty: return _empty_stat_shell(freq, start, end, "Active Inventory")
    df = df.copy()
    df["listing_date"] = pd.to_datetime(df["listing_date"], errors="coerce")
    df["effective_active_end_date"] = pd.to_datetime(df["effective_active_end_date"], errors="coerce")
    df = df[df["listing_date"].notna()]
    
    period_idx = get_period_range(start, end, freq)
    out = []
    for period in period_idx:
        # Snapshot is END of period
        snapshot_date = period.to_timestamp(how='end')
        mask = _active_snapshot_mask(df, snapshot_date)
        out.append([period, mask.sum()])
    return pd.DataFrame(out, columns=["PeriodIndex", "Active Inventory"])

def pending_inventory(df, freq, start, end):
    if df.empty: return _empty_stat_shell(freq, start, end, "Pending Inventory")
    
    df = df.copy()
    # Ensure dates
    cols = ['under_contract_date', 'sold_date', 'fallthrough_date', 'cancel_date', 'withdrawn_date', 'status_change_date', 'effective_active_end_date', 'listing_date']
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
        else:
            df[c] = pd.NaT

    df = df[df["under_contract_date"].notna()]

    # Determine Pending End Date (Earliest of Sold/Fallthrough/Cancel/Withdraw)
    df["calc_pending_end"] = pd.NaT

    # 1. If Sold/Closed, it ended on Sold Date
    mask_sold = df["status"].astype(str).str.upper().isin(['S', 'C', 'CLOSED', 'SOLD'])
    df.loc[mask_sold, "calc_pending_end"] = df.loc[mask_sold, "sold_date"]

    # 2. If Dead Deal (Expired, Cancelled, Withdrawn, etc.), find the end date
    pending_codes = ['P', 'PENDING', 'U', 'UNDER CONTRACT', 'D', 'BACKUP']
    mask_dead = ~df["status"].astype(str).str.upper().isin(pending_codes + ['S', 'C', 'CLOSED', 'SOLD'])
    
    # Use multiple date columns to find when the pending period ended
    dead_dates = df.loc[mask_dead, ["fallthrough_date", "cancel_date", "withdrawn_date", "status_change_date", "effective_active_end_date"]]
    df.loc[mask_dead, "calc_pending_end"] = dead_dates.min(axis=1)
    
    # 3. For dead deals where we STILL don't have an end date, use under_contract_date as fallback
    # (they went pending and then died, so they're not currently pending)
    mask_dead_no_end = mask_dead & df["calc_pending_end"].isna()
    df.loc[mask_dead_no_end, "calc_pending_end"] = df.loc[mask_dead_no_end, "under_contract_date"]

    # 4. Data Cleanup - end date can't be before contract date
    bad_data_mask = df["calc_pending_end"] < df["under_contract_date"]
    df.loc[bad_data_mask, "calc_pending_end"] = df.loc[bad_data_mask, "under_contract_date"]
    
    # 5. PCN-based invalidation: If same parcel has a newer listing, the old pending is dead
    if 'parcel_id' in df.columns:
        df['parcel_id'] = df['parcel_id'].astype(str)
        # For each parcel_id, find the max listing_date
        pcn_max_listing = df.groupby('parcel_id')['listing_date'].transform('max')
        # If this listing's listing_date is not the max for its parcel_id, it's superseded
        mask_superseded = (df['listing_date'] < pcn_max_listing) & df["calc_pending_end"].isna()
        df.loc[mask_superseded, "calc_pending_end"] = df.loc[mask_superseded, "listing_date"]

    period_idx = get_period_range(start, end, freq)
    out = []
    
    # Max pending duration: 6 months (180 days) - anything older is likely stale/dead
    MAX_PENDING_DAYS = 180
    
    for period in period_idx:
        snapshot_date = period.to_timestamp(how='end')
        stale_cutoff = snapshot_date - pd.Timedelta(days=MAX_PENDING_DAYS)
        
        # Only count as pending if:
        # 1. Went under contract before snapshot
        # 2. Either ended after snapshot OR (no end date AND status is pending AND not stale)
        mask = (df["under_contract_date"] <= snapshot_date) & (
            (df["calc_pending_end"] > snapshot_date) |
            (
                (df["calc_pending_end"].isna()) & 
                df["status"].astype(str).str.upper().isin(pending_codes) &
                (df["under_contract_date"] > stale_cutoff)  # Not stale (< 6 months old)
            )
        )
        out.append([period, mask.sum()])
        
    return pd.DataFrame(out, columns=["PeriodIndex", "Pending Inventory"])


def new_pending_sales(df, freq, start, end):
    """
    Count of listings that went under contract (pending) during each period.
    This is a FLOW metric (activity during period), not a snapshot.
    """
    if df.empty: return _empty_stat_shell(freq, start, end, "New Pending Sales")
    
    df = df.copy()
    df["under_contract_date"] = pd.to_datetime(df["under_contract_date"], errors="coerce")
    df = df[df["under_contract_date"].notna()]
    
    # Filter to date range
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    df = df[(df["under_contract_date"] >= start_ts) & (df["under_contract_date"] <= end_ts)]
    
    # Group by period and count
    df["PeriodIndex"] = df["under_contract_date"].dt.to_period({"monthly": "M", "quarterly": "Q", "annually": "A"}[freq])
    
    grouped = df.groupby("PeriodIndex").size().reset_index(name="New Pending Sales")
    
    # Fill missing periods
    period_idx = get_period_range(start, end, freq)
    result = pd.DataFrame({"PeriodIndex": period_idx})
    result = result.merge(grouped, on="PeriodIndex", how="left")
    result["New Pending Sales"] = result["New Pending Sales"].fillna(0).astype("Int64")
    
    return result


def median_dom(df, freq, start, end):
    df = df.copy()
    df["listing_date"] = pd.to_datetime(df["listing_date"], errors="coerce")
    df["effective_active_end_date"] = pd.to_datetime(df["effective_active_end_date"], errors="coerce")
    df = df[df["listing_date"].notna() & df["effective_active_end_date"].notna()].copy()
    df["DOM"] = (df["effective_active_end_date"] - df["listing_date"]).dt.days
    # Group by when listing ended (sold/closed), not when it was listed
    return safe_group_aggregation(df, "effective_active_end_date", "DOM", "median", freq, start, end, "Median DOM")

def listing_discount(df, freq, start, end):
    df = df.copy()
    df["original_list_price"] = pd.to_numeric(df["original_list_price"], errors="coerce")
    df["sold_price"] = pd.to_numeric(df["sold_price"], errors="coerce")
    df["sold_date"] = pd.to_datetime(df["sold_date"], errors="coerce")
    
    df = df[(df["sold_price"].notna()) & (df["original_list_price"] > 0)]
    df["ListingDiscount"] = ((df["original_list_price"] - df["sold_price"]) / df["original_list_price"]) * 100
    
    return safe_group_aggregation(df, "sold_date", "ListingDiscount", "median", freq, start, end, "Listing Discount")

def subdivision_median_price(df, freq, start, end):
    df = df.copy()
    df["sold_date"] = pd.to_datetime(df["sold_date"], errors="coerce")
    df = df[df["sold_price"].notna() & df["final_subdivision"].notna()]
    df["PeriodIndex"] = df["sold_date"].dt.to_period({"monthly": "M", "quarterly": "Q", "annually": "A"}[freq])
    return df.groupby(["PeriodIndex", "final_subdivision"])["sold_price"].median().reset_index().rename(columns={"sold_price": "Median Sold Price"})

def cash_sales_percentage(df, freq, start, end):
    df = df.copy()
    df["sold_date"] = pd.to_datetime(df["sold_date"], errors="coerce")
    df = df[df["sold_date"].notna()]
    df["terms_of_sale"] = df["terms_of_sale"].astype(str).str.upper()
    df["IsCash"] = df["terms_of_sale"].str.contains("CASH", na=False)
    
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    df = df[(df["sold_date"] >= start_ts) & (df["sold_date"] <= end_ts)]
    
    df["PeriodIndex"] = df["sold_date"].dt.to_period({"monthly": "M", "quarterly": "Q", "annually": "A"}[freq])
    grouped = df.groupby("PeriodIndex").agg(
        total_sales=("listing_number", "count"),
        cash_sales=("IsCash", "sum")
    ).reset_index()
    
    grouped["Cash Sales %"] = (grouped["cash_sales"] / grouped["total_sales"]) * 100
    return grouped[["PeriodIndex", "Cash Sales %"]]

def months_supply(df, freq, start, end):
    df = df.copy()
    df["listing_date"] = pd.to_datetime(df["listing_date"], errors="coerce")
    df["sold_date"] = pd.to_datetime(df["sold_date"], errors="coerce")
    df["effective_active_end_date"] = pd.to_datetime(df["effective_active_end_date"], errors="coerce")
    
    # Determine the latest data point to avoid "future" windows
    max_sold_date = df["sold_date"].max()
    if pd.isna(max_sold_date): max_sold_date = pd.Timestamp.now()

    period_idx = get_period_range(start, end, freq)
    out = []

    for period in period_idx:
        snapshot_date = period.to_timestamp(how='end')
        
        # 1. Active Count (Snapshot at End of Period)
        # We use the end of the period for consistent "projected" inventory
        active_mask = _active_snapshot_mask(df, snapshot_date)
        active_count = active_mask.sum()
        
        # 2. Sales Rate (Last 12 Months of ACTUAL Data)
        # If snapshot_date is in the future relative to our data (e.g. end of current incomplete month),
        # we clamp the sales window end to the latest actual sold date.
        # This ensures we sum 12 months of REAL sales, and divide by 12.
        effective_sales_end_date = min(snapshot_date, max_sold_date)
        
        # Ensure we don't look back from a date BEFORE the period starts (rare edge case)
        if effective_sales_end_date < snapshot_date and effective_sales_end_date < period.to_timestamp(how='start'):
             # If no data exists for this period yet, use snapshot_date (will result in 0 sales, which is correct)
             effective_sales_end_date = snapshot_date

        twelve_months_ago = effective_sales_end_date - relativedelta(months=12)
        sales_mask = (df["sold_date"] > twelve_months_ago) & (df["sold_date"] <= effective_sales_end_date)
        sales_count_12mo = sales_mask.sum()
        
        sales_rate = sales_count_12mo / 12.0
        
        if sales_rate > 0:
            msi = active_count / sales_rate
        else:
            msi = 0 if active_count == 0 else 999 
            
        out.append([period, msi])
        
    return pd.DataFrame(out, columns=["PeriodIndex", "Months Supply"])

def _clamp_score(v):
    if pd.isna(v):
        return np.nan
    return float(max(0, min(100, v)))


def _score_dom(dom):
    if pd.isna(dom):
        return np.nan
    if dom <= 30:
        return 100
    if dom <= 45:
        return 85
    if dom <= 60:
        return 70
    if dom <= 90:
        return 50
    if dom <= 120:
        return 30
    return 15


def _score_pending_to_sold(p2s):
    if pd.isna(p2s):
        return np.nan
    if p2s >= 1.20:
        return 100
    if p2s >= 1.00:
        return 85
    if p2s >= 0.80:
        return 70
    if p2s >= 0.60:
        return 50
    if p2s >= 0.40:
        return 30
    return 15


def _score_msi(msi):
    if pd.isna(msi):
        return np.nan
    if msi <= 2.0:
        return 100
    if msi <= 3.0:
        return 90
    if msi <= 4.0:
        return 75
    if msi <= 5.5:
        return 60
    if msi <= 7.0:
        return 40
    if msi <= 9.0:
        return 25
    return 10


def _score_inventory_yoy(inv_yoy):
    if pd.isna(inv_yoy):
        return np.nan
    # Lower inventory growth is hotter market; negative is strongest.
    if inv_yoy <= -15:
        return 100
    if inv_yoy <= -5:
        return 85
    if inv_yoy <= 5:
        return 65
    if inv_yoy <= 15:
        return 45
    if inv_yoy <= 30:
        return 25
    return 10


def _score_discount(discount):
    if pd.isna(discount):
        return np.nan
    # Lower discount = stronger seller pricing power.
    if discount <= 0:
        return 100
    if discount <= 2:
        return 85
    if discount <= 4:
        return 70
    if discount <= 6:
        return 55
    if discount <= 8:
        return 40
    if discount <= 10:
        return 25
    return 10


def _score_cash(cash):
    if pd.isna(cash):
        return np.nan
    if cash >= 55:
        return 100
    if cash >= 45:
        return 85
    if cash >= 35:
        return 70
    if cash >= 25:
        return 55
    if cash >= 15:
        return 40
    return 25


def _grade_from_score(score):
    if pd.isna(score):
        return pd.NA
    if score >= 80:
        return "A (Strong Seller)"
    if score >= 65:
        return "B (Seller)"
    if score >= 45:
        return "C (Balanced)"
    if score >= 30:
        return "D (Buyer)"
    return "F (Strong Buyer)"


def _weighted_average(values_and_weights):
    num = 0.0
    den = 0.0
    for v, w in values_and_weights:
        if pd.notna(v):
            num += float(v) * float(w)
            den += float(w)
    if den == 0:
        return np.nan
    return num / den


# --- PROPRIETARY MARKET GRADE V2 ---
def market_grade_score(df, freq, start, end):
    """
    Weighted market barometer (0-100) with explainable components:
      - Pace (30%): DOM + Pending/Sold
      - Supply Pressure (30%): MSI + Active Inventory YoY
      - Pricing Power (25%): Median Listing Discount
      - Demand Quality (15%): Cash Sales %
    """
    period_idx = get_period_range(start, end, freq)

    msi_df = months_supply(df, freq, start, end)
    dom_df = median_dom(df, freq, start, end)
    pending_df = pending_sales(df, freq, start, end)
    sales_df = sales_count(df, freq, start, end)
    inventory_df = active_inventory(df, freq, start, end)
    discount_df = listing_discount(df, freq, start, end)
    cash_df = cash_sales_percentage(df, freq, start, end)

    merged = pd.DataFrame({"PeriodIndex": period_idx})
    for x in [msi_df, dom_df, pending_df, sales_df, inventory_df, discount_df, cash_df]:
        merged = merged.merge(x, on="PeriodIndex", how="left")

    prior_map = dict(zip(merged["PeriodIndex"], merged["Active Inventory"]))

    def _prior_period(p):
        if freq == "monthly":
            return p - 12
        if freq == "quarterly":
            return p - 4
        return p - 1

    # Core component inputs
    merged["Pending-to-Sold"] = merged["Pending Sales"] / merged["Sales Count"]
    merged.loc[merged["Sales Count"].fillna(0) <= 0, "Pending-to-Sold"] = np.nan

    merged["Active Inventory YoY %"] = merged["PeriodIndex"].apply(
        lambda p: np.nan
        if pd.isna(prior_map.get(_prior_period(p), np.nan)) or prior_map.get(_prior_period(p), 0) == 0
        else ((prior_map.get(p, np.nan) - prior_map.get(_prior_period(p), np.nan)) / prior_map.get(_prior_period(p), np.nan)) * 100
    )

    # Subscores
    merged["DOM Score"] = merged["Median DOM"].apply(_score_dom).apply(_clamp_score)
    merged["P2S Score"] = merged["Pending-to-Sold"].apply(_score_pending_to_sold).apply(_clamp_score)
    merged["MSI Score"] = merged["Months Supply"].apply(_score_msi).apply(_clamp_score)
    merged["Inventory YoY Score"] = merged["Active Inventory YoY %"].apply(_score_inventory_yoy).apply(_clamp_score)
    merged["Discount Score"] = merged["Listing Discount"].apply(_score_discount).apply(_clamp_score)
    merged["Cash Score"] = merged["Cash Sales %"].apply(_score_cash).apply(_clamp_score)

    # Pillars
    merged["Pace Score"] = merged.apply(
        lambda r: _clamp_score(_weighted_average([(r.get("DOM Score"), 0.70), (r.get("P2S Score"), 0.30)])),
        axis=1,
    )
    merged["Supply Pressure Score"] = merged.apply(
        lambda r: _clamp_score(_weighted_average([(r.get("MSI Score"), 0.70), (r.get("Inventory YoY Score"), 0.30)])),
        axis=1,
    )
    merged["Pricing Power Score"] = merged["Discount Score"].apply(_clamp_score)
    merged["Demand Quality Score"] = merged["Cash Score"].apply(_clamp_score)

    # Final weighted grade score
    merged["Market Grade Score"] = merged.apply(
        lambda r: _clamp_score(
            _weighted_average(
                [
                    (r.get("Pace Score"), 0.30),
                    (r.get("Supply Pressure Score"), 0.30),
                    (r.get("Pricing Power Score"), 0.25),
                    (r.get("Demand Quality Score"), 0.15),
                ]
            )
        ),
        axis=1,
    )

    merged["Market Grade"] = merged["Market Grade Score"].apply(_grade_from_score)
    merged["Market Grade Formula"] = (
        "Score = 0.30*Pace + 0.30*Supply + 0.25*Pricing + 0.15*Demand; "
        "Pace=0.70*DOM+0.30*Pending/Sold; Supply=0.70*MSI+0.30*InventoryYoY"
    )

    return merged[
        [
            "PeriodIndex",
            "Market Grade",
            "Market Grade Score",
            "Pace Score",
            "Supply Pressure Score",
            "Pricing Power Score",
            "Demand Quality Score",
            "Months Supply",
            "Median DOM",
            "Pending-to-Sold",
            "Active Inventory YoY %",
            "Listing Discount",
            "Cash Sales %",
            "Market Grade Formula",
        ]
    ]
