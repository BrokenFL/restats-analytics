# --- START OF FILE data_analysis.py ---

import pandas as pd
import numpy as np
import logging
from datetime import datetime
import os
import traceback

# App config + stat registry
from app_config import STATISTIC_FUNCTIONS, STATS_METADATA
from data_analysis_functions import get_period_range, label_period

DEFAULT_DATE_COL_FOR_FILTERING = "listing_date"

# -------------------------------
# Logging Setup
# -------------------------------
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_filename = os.path.join(log_dir, "real_estate_analysis.log")

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(module)s - %(message)s",
        handlers=[logging.FileHandler(log_filename, mode="w"), logging.StreamHandler()],
    )
    logger.propagate = False


# =====================================================================
# MAIN ANALYSIS ENGINE
# =====================================================================

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

    # ---------------------------------------
    # Validate params
    # ---------------------------------------
    required = ["start_date", "end_date", "timeframe", "stats_to_calculate"]
    if not isinstance(params, dict) or not all(k in params for k in required):
        missing = [k for k in required if k not in params]
        return {"error": f"Missing required analysis parameters: {missing}"}

    timeframe = params["timeframe"].lower()
    if timeframe not in ["monthly", "quarterly", "annually"]:
        return {"error": f"Invalid timeframe: {timeframe}"}

    calc_yoy = params.get("calculate_yoy", False)
    start_str = params["start_date"]
    end_str = params["end_date"]

    # ---------------------------------------
    # Validate Dates
    # ---------------------------------------
    try:
        start_ts = pd.Timestamp(start_str).normalize()
        end_ts = pd.Timestamp(end_str).normalize()
        if start_ts > end_ts:
            raise ValueError("Start date is after end date.")
    except Exception as e:
        return {"error": f"Invalid date formatting: {e}"}

    logger.info(
        f"Begin analysis | timeframe={timeframe} | YoY={calc_yoy} | range={start_ts.date()} to {end_ts.date()}"
    )

    df_base = df_master_unfiltered.copy() if isinstance(df_master_unfiltered, pd.DataFrame) else pd.DataFrame()
    if df_base.empty:
        return {"error": "Master DataFrame is empty or invalid."}

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
            df = df[df[date_col].notna()]
            
            start_filter = pd.Timestamp(actual_start)
            end_filter = pd.Timestamp(end_str)

            # Check for special skip flags (Used for Active/Pending Inventory)
            skip_start_filter = meta.get("skip_start_date_filter", False)
            skip_all_date_filter = meta.get("skip_all_date_filter", False)

            if skip_all_date_filter:
                # Don't filter by date at all - inventory metrics need ALL historical records
                # to calculate current snapshot (a listing from 2020 could still be active)
                pass
            elif skip_start_filter:
                # Only filter future dates. Keep history for "carry-over" inventory.
                df = df[df[date_col] <= end_filter]
            else:
                # Standard filtering (Start to End)
                df = df[(df[date_col] >= start_filter) & (df[date_col] <= end_filter)]

        except Exception as err:
            logger.error(f"Date filtering failed for '{display_name}': {err}")
            results[display_name] = _error_df_shell(display_name, all_periods, all_labels, calc_yoy, is_dist)
            continue

        # ---------------------------------------
        # STAT FUNCTION EXECUTION
        # ---------------------------------------
        try:
            raw_df = func(df, timeframe, actual_start, end_str)
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
        aligned = raw_df.reindex(all_periods).reset_index()
        aligned["Period"] = all_labels

        # Fix dtype
        if display_name in aligned.columns:
            aligned[display_name] = aligned[display_name].astype(dtype)

        if calc_yoy and not is_dist:
            yoy_name = f"{display_name} YoY %"
            aligned[yoy_name] = aligned[yoy_name].astype("Float64")

        results[display_name] = aligned

    logger.info("Analysis complete.")
    return results


# =====================================================================
# SUPPORTING HELPERS
# =====================================================================

def _compute_yoy(df, col, timeframe):
    """Compute Year-over-Year % based on period index shifting."""
    if "PeriodIndex" not in df.columns:
        return pd.Series([np.nan] * len(df))

    # Sort by PeriodIndex to ensure shift works correctly
    df_sorted = df.sort_values("PeriodIndex").reset_index(drop=True)
    
    shifts = {"monthly": 12, "quarterly": 4, "annually": 1}
    shift_n = shifts.get(timeframe, 12)

    series = pd.to_numeric(df_sorted[col], errors="coerce")
    prev = series.shift(shift_n)

    denom = prev.replace(0, np.nan).abs()
    yoy = ((series - prev) / denom) * 100
    yoy_result = yoy.replace([np.inf, -np.inf], np.nan).astype("Float64")
    
    # Map back to original df order using PeriodIndex
    yoy_map = dict(zip(df_sorted["PeriodIndex"], yoy_result))
    return df["PeriodIndex"].map(yoy_map)


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
