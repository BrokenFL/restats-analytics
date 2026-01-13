from data_analysis_functions import (
    median_sold_price,
    median_list_price,
    sales_count,
    new_listings,
    pending_sales,
    active_inventory,
    pending_inventory,
    median_dom,
    listing_discount,
    subdivision_median_price,
    median_price_per_sqft,
    median_list_price_per_sqft,
    cash_sales_percentage,
    months_supply,
    total_sales_volume,
    market_grade_score
)

STATISTIC_FUNCTIONS = {
    "Market Grade": "market_grade_score",
    "Median Sold Price": "median_sold_price",
    "Median Price Per SqFt": "median_price_per_sqft",
    "Median List Price Per SqFt": "median_list_price_per_sqft",
    "Months Supply (MSI)": "months_supply",
    "Total Sales Volume": "total_sales_volume",
    "Cash Sales %": "cash_sales_percentage",
    "Median List Price": "median_list_price",
    "Sales Count": "sales_count",
    "New Listings": "new_listings",
    "Pending Sales": "pending_sales",
    "Active Inventory": "active_inventory",
    "Pending Inventory": "pending_inventory",
    "Median DOM": "median_dom",
    "Listing Discount": "listing_discount",
    "Subdivision Median Price": "subdivision_median_price",
}

STATS_METADATA = {
    "median_sold_price": {
        "func": median_sold_price,
        "date_col_for_filtering": "sold_date",
        "dtype": "Float64",
        "is_dist": False
    },
    "median_price_per_sqft": {
        "func": median_price_per_sqft,
        "date_col_for_filtering": "sold_date",
        "dtype": "Int64",
        "is_dist": False
    },
    "months_supply": {
        "func": months_supply,
        "date_col_for_filtering": "listing_date",
        "skip_start_date_filter": True,
        "dtype": "Float64",
        "is_dist": False
    },
    "total_sales_volume": { # <--- CONFIG THIS
        "func": total_sales_volume,
        "date_col_for_filtering": "sold_date",
        "dtype": "Float64",
        "is_dist": False
    },
    "cash_sales_percentage": {
        "func": cash_sales_percentage,
        "date_col_for_filtering": "sold_date",
        "dtype": "Float64",
        "is_dist": False
    },
    "median_list_price": {
        "func": median_list_price,
        "date_col_for_filtering": "listing_date",
        "skip_start_date_filter": True,
        "dtype": "Float64",
        "is_dist": False
    },
    "median_list_price_per_sqft": {
        "func": median_list_price_per_sqft,
        "date_col_for_filtering": "listing_date",
        "skip_start_date_filter": True,
        "dtype": "Int64",
        "is_dist": False
    },
    "sales_count": {
        "func": sales_count,
        "date_col_for_filtering": "sold_date",
        "dtype": "Int64",
        "is_dist": False
    },
    "new_listings": {
        "func": new_listings,
        "date_col_for_filtering": "listing_date",
        "dtype": "Int64",
        "is_dist": False
    },
    "pending_sales": {
        "func": pending_sales,
        "date_col_for_filtering": "under_contract_date",
        "dtype": "Int64",
        "is_dist": False
    },
    "active_inventory": {
        "func": active_inventory,
        "date_col_for_filtering": "listing_date",
        "skip_start_date_filter": True,
        "dtype": "Int64",
        "is_dist": False
    },
    "pending_inventory": {
        "func": pending_inventory,
        "date_col_for_filtering": "under_contract_date",
        "skip_start_date_filter": True,
        "dtype": "Int64",
        "is_dist": False
    },
    "median_dom": {
        "func": median_dom,
        "date_col_for_filtering": "listing_date",
        "dtype": "Float64",
        "is_dist": False
    },
    "listing_discount": {
        "func": listing_discount,
        "date_col_for_filtering": "sold_date",
        "dtype": "Float64",
        "is_dist": False
    },
    "subdivision_median_price": {
        "func": subdivision_median_price,
        "date_col_for_filtering": "sold_date",
        "dtype": "Float64",
        "grouped_output": True,
        "is_dist": False
    },
    "market_grade_score": {
        "func": market_grade_score,
        "date_col_for_filtering": "listing_date",
        "skip_start_date_filter": True,
        "dtype": "string",
        "is_dist": False
    },
}
