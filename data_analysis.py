# --- START OF FILE data_analysis.py ---

import pandas as pd
import numpy as np
from datetime import datetime
import os
import traceback

# App config + stat registry
from app_config import STATISTIC_FUNCTIONS, STATS_METADATA
from data_analysis_functions import get_period_range, label_period

# Centralized logging
from analytics_logger import (
    logger, log_analysis_params, log_stat_calculation, 
    log_dataframe_summary, log_data_filter, log_section,
    run_diagnostics, log_timing
)

DEFAULT_DATE_COL_FOR_FILTERING = "listing_date"


# =====================================================================
# MAIN ANALYSIS ENGINE
# =====================================================================

@log_timing
def analyze_real_estate_data(df_master_unfiltered, params):
    """
    Top-level analysis engine.
    Fully updated to work with cleaned fields:
        - calculated_status
        - effective_active_end_date
        - final_subdivision
        - is_zombie
        - pcn_10_digit
    Returns dict: { DisplayName: DataFrame }
    """
    log_section("ANALYSIS START")
    
    # ---------------------------------------
    # Validate params
    # ---------------------------------------
    required = ["start_date", "end_date", "timeframe", "stats_to_calculate"]
    if not isinstance(params, dict) or not all(k in params for k in required):
        missing = [k for k in required if k not in params]
        logger.error(f"Missing required parameters: {missing}")
        return {"error": f"Missing required analysis parameters: {missing}"}

    timeframe = params["timeframe"].lower()
    if timeframe not in ["monthly", "quarterly", "annually"]:
        logger.error(f"Invalid timeframe: {timeframe}")
        return {"error": f"Invalid timeframe: {timeframe}"}

    calc_yoy = params.get("calculate_yoy", False)
    start_str = params["start_date"]
    end_str = params["end_date"]
    
    # Log all parameters
    log_analysis_params(params)

    # ---------------------------------------
    # Validate Dates
    # ---------------------------------------
    try:
        start_ts = pd.Timestamp(start_str).normalize()
        end_ts = pd.Timestamp(end_str).normalize()
        if start_ts > end_ts:
            raise ValueError("Start date is after end date.")
    except Exception as e:
        logger.error(f"Invalid date formatting: {e}")
        return {"error": f"Invalid date formatting: {e}"}

    logger.info(
        f"Analysis range: {start_ts.date()} to {end_ts.date()} | timeframe={timeframe} | YoY={calc_yoy}"
    )

    df_base = df_master_unfiltered.copy() if isinstance(df_master_unfiltered, pd.DataFrame) else pd.DataFrame()
    if df_base.empty:
        logger.error("Master DataFrame is empty or invalid")
        return {"error": "Master DataFrame is empty or invalid."}
    
    # Run diagnostics on input data
    run_diagnostics(df_base)

    # ---------------------------------------
    # Build Period Index
    # ---------------------------------------
    all_periods = get_period_range(start_str, end_str, timeframe)
    all_labels = [label_period(p, timeframe) for p in all_periods]

    # ---------------------------------------
    # Final Output Container
    # ---------------------------------------
    results = {}

    # -----------------------------------------------------------------
    # PROCESS EACH STATISTIC REQUESTED BY USER
    # -----------------------------------------------------------------
    stats_requested = params.get("stats_to_calculate", [])
    if not isinstance(stats_requested, list):
        stats_requested = []

    for display_name in stats_requested:

        # Map UI Display → Internal Key
        internal_key = STATISTIC_FUNCTIONS.get(display_name)
        if not internal_key:
            logger.warning(f"Unknown statistic '{display_name}', skipping.")
            continue

        meta = STATS_METADATA.get(internal_key, {})
        func = meta.get("func")
        is_dist = meta.get("is_dist", False)
        date_col = meta.get("date_col_for_filtering", DEFAULT_DATE_COL_FOR_FILTERING)
        dtype = meta.get("dtype", "object")

        logger.info(f"Processing: {display_name} | key={internal_key}")

        if not callable(func):
            logger.error(f"No valid function for key '{internal_key}'")
            results[display_name] = _error_df_shell(display_name, all_periods, all_labels, calc_yoy, is_dist)
            continue

        # ---------------------------------------
        # Extend Start Date for YoY
        # ---------------------------------------
        actual_start = start_str
        if calc_yoy and not is_dist:
            actual_start = (start_ts - pd.DateOffset(years=1)).strftime("%Y-%m-%d")

        # ---------------------------------------
        # Filter df
        # ---------------------------------------
        df = df_base.copy()
        if date_col not in df.columns:
            logger.error(f"Date column '{date_col}' missing for statistic '{display_name}'")
            results[display_name] = _error_df_shell(display_name, all_periods, all_labels, calc_yoy, is_dist)
            continue

        try:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            before_filter = len(df)
            df = df[df[date_col].notna()]
            log_data_filter("date_notna", df, f"(was {before_filter}, now {len(df)})")
            
            start_filter = pd.Timestamp(actual_start)
            end_filter = pd.Timestamp(end_str)

            # Check for special skip flags (Used for Active/Pending Inventory)
            skip_start_filter = meta.get("skip_start_date_filter", False)
            skip_all_date_filter = meta.get("skip_all_date_filter", False)

            if skip_all_date_filter:
                # Don't filter by date at all - inventory metrics need ALL historical records
                log_data_filter("skip_all_date", df, "(no date filter applied)")
            elif skip_start_filter:
                # Only filter future dates. Keep history for "carry-over" inventory.
                before = len(df)
                df = df[df[date_col] <= end_filter]
                log_data_filter("skip_start", df, f"(<= {end_filter.date()}, was {before})")
            else:
                # Standard filtering (Start to End)
                before = len(df)
                df = df[(df[date_col] >= start_filter) & (df[date_col] <= end_filter)]
                log_data_filter("date_range", df, f"({start_filter.date()} to {end_filter.date()}, was {before})")

        except Exception as err:
            logger.error(f"Date filtering failed for '{display_name}': {err}", exc_info=True)
            results[display_name] = _error_df_shell(display_name, all_periods, all_labels, calc_yoy, is_dist)
            continue

        # ---------------------------------------
        # STAT FUNCTION EXECUTION
        # ---------------------------------------
        try:
            logger.debug(f"Calling {internal_key} with {len(df)} rows")
            raw_df = func(df, timeframe, actual_start, end_str)
            log_stat_calculation(display_name, df, raw_df)
        except Exception as err:
            logger.error(f"Stat function '{internal_key}' failed: {err}", exc_info=True)
            results[display_name] = _error_df_shell(display_name, all_periods, all_labels, calc_yoy, is_dist)
            continue

        if not isinstance(raw_df, pd.DataFrame) or raw_df.empty:
            logger.warning(f"Stat '{display_name}' returned empty DF.")
            results[display_name] = _error_df_shell(display_name, all_periods, all_labels, calc_yoy, is_dist)
            continue

        # ---------------------------------------
        # YOY CALC (must happen BEFORE reindex to user periods)
        # ---------------------------------------
        if calc_yoy and not is_dist:
            # Determine the actual column name in raw_df
            # Usually it matches display_name, but sometimes the function returns a specific name
            # We need to find the value column that is NOT "PeriodIndex"
            value_cols = [c for c in raw_df.columns if c != "PeriodIndex"]
            if value_cols:
                actual_col_name = value_cols[0] 
                
                yoy_name = f"{display_name} YoY %"
                raw_df[yoy_name] = _compute_yoy(raw_df, actual_col_name, timeframe)
                
                # If the column name doesn't match display_name, rename it so downstream logic works
                if actual_col_name != display_name:
                    raw_df.rename(columns={actual_col_name: display_name}, inplace=True)
                
                # Debug log to verify YoY was calculated
                yoy_valid = raw_df[yoy_name].notna().sum()
                logger.debug(f"YoY calculated for {display_name}: {yoy_valid} valid values out of {len(raw_df)}")
            else:
                 logger.warning(f"Could not find value column for {display_name}")

        # ---------------------------------------
        # REINDEX TO USER PERIODS
        # ---------------------------------------
        raw_df = raw_df.set_index("PeriodIndex")
        # Reindex ensures chronological order since all_periods is already sorted
        aligned = raw_df.reindex(all_periods).reset_index()
        aligned["Period"] = all_labels

        # Fix dtype
        if display_name in aligned.columns:
            aligned[display_name] = aligned[display_name].astype(dtype)

        if calc_yoy and not is_dist:
            yoy_name = f"{display_name} YoY %"
            aligned[yoy_name] = aligned[yoy_name].astype("Float64")

        results[display_name] = aligned

    # Final summary
    log_section("ANALYSIS COMPLETE")
    logger.info(f"Stats calculated: {len(results)}")
    for stat_name, df in results.items():
        if isinstance(df, pd.DataFrame) and not df.empty:
            valid_count = df[stat_name].notna().sum() if stat_name in df.columns else 0
            logger.info(f"  {stat_name}: {valid_count} valid periods")
    
    return results


# =====================================================================
# SUPPORTING HELPERS
# =====================================================================

def _compute_yoy(df, col, timeframe):
    """
    Compute Year-over-Year % by matching each period to its prior year period.
    Uses period arithmetic instead of row shifting to handle gaps in data.
    """
    if "PeriodIndex" not in df.columns:
        return pd.Series([np.nan] * len(df))

    # Build a lookup dict: PeriodIndex -> value
    value_lookup = {}
    for _, row in df.iterrows():
        period = row["PeriodIndex"]
        val = row[col]
        if pd.notna(val):
            value_lookup[period] = val
    
    # For each period, find the prior year period and calculate YoY
    yoy_values = []
    for _, row in df.iterrows():
        current_period = row["PeriodIndex"]
        current_val = row[col]
        
        if pd.isna(current_val):
            yoy_values.append(np.nan)
            continue
        
        # Calculate prior year period using period arithmetic
        try:
            # Subtract 1 year worth of periods
            if timeframe == "monthly":
                prior_period = current_period - 12
            elif timeframe == "quarterly":
                prior_period = current_period - 4
            else:  # annually
                prior_period = current_period - 1
            
            prior_val = value_lookup.get(prior_period)
            
            if prior_val is not None and prior_val != 0:
                yoy_pct = ((current_val - prior_val) / abs(prior_val)) * 100
                yoy_values.append(yoy_pct)
            else:
                yoy_values.append(np.nan)
        except Exception:
            yoy_values.append(np.nan)
    
    return pd.Series(yoy_values, dtype="Float64")


def _error_df_shell(display_name, periods, labels, calc_yoy, is_dist):
    """Return an empty but structurally correct dataframe when an error occurs."""
    df = pd.DataFrame({
        "PeriodIndex": periods,
        "Period": labels,
        display_name: pd.NA
    })

    if calc_yoy and not is_dist:
        df[f"{display_name} YoY %"] = pd.NA

    if is_dist:
        for col in ["Low", "Mid-Low", "Mid-High", "High"]:
            df[col] = pd.NA

    return df


# --- END OF FILE data_analysis.py ---
