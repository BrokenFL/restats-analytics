#!/usr/bin/env python3
"""
Centralized logging utility for ReStats analytics.
Provides detailed logging with timestamps, data summaries, and troubleshooting info.
"""

import logging
import os
from datetime import datetime
from functools import wraps
import pandas as pd

# Log directory
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Create timestamped log file (keeps history)
LOG_FILE = os.path.join(LOG_DIR, f"analytics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

# Also keep a "latest" log for easy access
LATEST_LOG = os.path.join(LOG_DIR, "analytics_latest.log")

# Configure logger
logger = logging.getLogger("restats_analytics")
logger.setLevel(logging.DEBUG)

# Clear existing handlers
if logger.handlers:
    logger.handlers.clear()

# File handler - detailed logging
file_handler = logging.FileHandler(LOG_FILE, mode="w")
file_handler.setLevel(logging.DEBUG)
file_format = logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(funcName)-25s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
file_handler.setFormatter(file_format)
logger.addHandler(file_handler)

# Latest log handler
latest_handler = logging.FileHandler(LATEST_LOG, mode="w")
latest_handler.setLevel(logging.DEBUG)
latest_handler.setFormatter(file_format)
logger.addHandler(latest_handler)

# Console handler - info and above
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_format = logging.Formatter("%(levelname)s: %(message)s")
console_handler.setFormatter(console_format)
logger.addHandler(console_handler)


def log_dataframe_summary(df, name="DataFrame"):
    """Log a summary of a DataFrame for debugging."""
    if df is None:
        logger.debug(f"{name}: None")
        return
    
    if not isinstance(df, pd.DataFrame):
        logger.debug(f"{name}: Not a DataFrame (type={type(df)})")
        return
    
    logger.debug(f"{name}: {len(df)} rows x {len(df.columns)} cols")
    logger.debug(f"  Columns: {list(df.columns)}")
    
    # Log key column stats
    for col in ['calculated_status', 'sold_date', 'listing_date', 'sold_price', 'list_price']:
        if col in df.columns:
            non_null = df[col].notna().sum()
            logger.debug(f"  {col}: {non_null} non-null ({100*non_null/len(df):.1f}%)")


def log_analysis_params(params):
    """Log analysis parameters."""
    logger.info("=" * 60)
    logger.info("ANALYSIS PARAMETERS")
    logger.info("=" * 60)
    for key, value in params.items():
        if key == "stats_to_calculate":
            logger.info(f"  {key}: {len(value)} stats requested")
            for stat in value:
                logger.info(f"    - {stat}")
        else:
            logger.info(f"  {key}: {value}")


def log_stat_calculation(stat_name, df_input, df_output):
    """Log details about a statistic calculation."""
    logger.info(f"STAT: {stat_name}")
    logger.debug(f"  Input rows: {len(df_input) if df_input is not None else 0}")
    
    if df_output is not None and isinstance(df_output, pd.DataFrame):
        logger.debug(f"  Output rows: {len(df_output)}")
        if not df_output.empty:
            # Log first few values
            for col in df_output.columns:
                if col not in ['PeriodIndex', 'Period']:
                    valid = df_output[col].notna().sum()
                    logger.debug(f"  {col}: {valid} valid values")


def log_data_filter(stage, df, description=""):
    """Log data filtering stages."""
    count = len(df) if df is not None else 0
    logger.debug(f"FILTER [{stage}]: {count} rows {description}")


def log_error(message, exc_info=False):
    """Log an error with optional exception info."""
    logger.error(message, exc_info=exc_info)


def log_warning(message):
    """Log a warning."""
    logger.warning(message)


def log_info(message):
    """Log info."""
    logger.info(message)


def log_debug(message):
    """Log debug info."""
    logger.debug(message)


def log_section(title):
    """Log a section header."""
    logger.info("")
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)


def log_subsection(title):
    """Log a subsection header."""
    logger.info(f"--- {title} ---")


def get_log_path():
    """Return the path to the current log file."""
    return LOG_FILE


def get_latest_log_path():
    """Return the path to the latest log file."""
    return LATEST_LOG


# Decorator for timing function execution
def log_timing(func):
    """Decorator to log function execution time."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = datetime.now()
        logger.debug(f"START: {func.__name__}")
        try:
            result = func(*args, **kwargs)
            elapsed = (datetime.now() - start).total_seconds()
            logger.debug(f"END: {func.__name__} ({elapsed:.2f}s)")
            return result
        except Exception as e:
            elapsed = (datetime.now() - start).total_seconds()
            logger.error(f"FAILED: {func.__name__} ({elapsed:.2f}s) - {e}", exc_info=True)
            raise
    return wrapper


# Quick diagnostic function
def run_diagnostics(df):
    """Run diagnostics on the master DataFrame and log results."""
    log_section("DATA DIAGNOSTICS")
    
    if df is None or df.empty:
        logger.error("DataFrame is None or empty!")
        return
    
    logger.info(f"Total records: {len(df)}")
    
    # Status breakdown
    if 'calculated_status' in df.columns:
        status_counts = df['calculated_status'].value_counts()
        logger.info("Status breakdown:")
        for status, count in status_counts.items():
            logger.info(f"  {status}: {count}")
    
    # Date ranges
    for date_col in ['listing_date', 'sold_date']:
        if date_col in df.columns:
            dates = pd.to_datetime(df[date_col], errors='coerce')
            valid = dates.notna().sum()
            if valid > 0:
                min_date = dates.min()
                max_date = dates.max()
                logger.info(f"{date_col}: {valid} records, range {min_date} to {max_date}")
    
    # Price stats
    for price_col in ['sold_price', 'list_price']:
        if price_col in df.columns:
            prices = pd.to_numeric(df[price_col], errors='coerce')
            valid = prices.notna().sum()
            if valid > 0:
                logger.info(f"{price_col}: {valid} records, median ${prices.median():,.0f}")
    
    # Source breakdown (MLS vs PBC)
    if 'listing_number' in df.columns:
        pbc = df['listing_number'].str.startswith('PBC-').sum()
        mls = len(df) - pbc
        logger.info(f"Sources: MLS={mls}, PBC={pbc}")
    
    log_section("END DIAGNOSTICS")


if __name__ == "__main__":
    # Test the logger
    logger.info("Analytics logger initialized")
    logger.debug("Debug message test")
    logger.warning("Warning message test")
    print(f"\nLog file: {LOG_FILE}")
    print(f"Latest log: {LATEST_LOG}")
