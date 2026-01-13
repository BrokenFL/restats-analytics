import sqlite3
import pandas as pd
from dateutil.relativedelta import relativedelta

DB_FILE = "mls.db"
TARGET_SUB = "PALM BEACH HAMPTON"

def debug_msi():
    conn = sqlite3.connect(DB_FILE)
    
    # Load minimal data for MSI
    query = f"""
    SELECT 
        listing_number, status, listing_date, sold_date, 
        effective_active_end_date, final_subdivision
    FROM listing_details
    WHERE final_subdivision = '{TARGET_SUB}'
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    # Convert dates
    for col in ['listing_date', 'sold_date', 'effective_active_end_date']:
        df[col] = pd.to_datetime(df[col], errors='coerce')
        
    print(f"Total rows for {TARGET_SUB}: {len(df)}")
    
    # Define periods to check (All 2025 months)
    periods = pd.date_range(start="2025-01-31", end="2025-12-31", freq="M")
    
    max_sold_date = df["sold_date"].max()
    if pd.isna(max_sold_date):
        max_sold_date = pd.Timestamp.now()
        
    print(f"Max Sold Date in DB: {max_sold_date.date()}")
    
    print(f"\n--- MSI DEBUG ({TARGET_SUB}) ---")
    print(f"{'Period':<12} | {'Active':<8} | {'Sales(12mo)':<12} | {'Rate/Mo':<8} | {'MSI':<6}")
    print("-" * 60)
    
    for snapshot_date in periods:
        # 1. Active Count
        active_mask = (df["listing_date"] <= snapshot_date) & (
            (df["effective_active_end_date"].isna()) | 
            (df["effective_active_end_date"] > snapshot_date)
        )
        active_count = active_mask.sum()
        
        # 2. Sales Rate
        effective_sales_end = min(snapshot_date, max_sold_date)
        # Ensure we don't look back from before the period
        if effective_sales_end < snapshot_date:
            effective_sales_end = snapshot_date

        twelve_months_ago = effective_sales_end - relativedelta(months=12)
        
        sales_mask = (df["sold_date"] > twelve_months_ago) & (df["sold_date"] <= effective_sales_end)
        sales_12mo = sales_mask.sum()
        sales_rate = sales_12mo / 12.0
        
        msi = active_count / sales_rate if sales_rate > 0 else 0
        if sales_rate == 0 and active_count > 0:
            msi = 999
        
        print(f"{snapshot_date.date()} | {active_count:<8} | {sales_12mo:<12} | {sales_rate:<8.1f} | {msi:.1f}")

if __name__ == "__main__":
    debug_msi()
