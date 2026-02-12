import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
import calendar
import os
import base64
from datetime import datetime
from data_analysis import analyze_real_estate_data
from report_generator import generate_pdf_report

# --- CONFIGURATION ---
DB_FILE = "mls.db"

STATS_OPTIONS = [
    "Market Grade", 
    "Median Sold Price",
    "Median Price Per SqFt",
    "Median List Price",
    "Median List Price Per SqFt",
    "Months Supply (MSI)",
    "Total Sales Volume", 
    "Active Inventory", 
    "Pending Inventory",
    "Median DOM", 
    "Sales Count",
    "New Listings",
    "Pending Sales",
    "New Pending Sales",
    "Listing Discount",
    "Cash Sales %"
]

# Map stats to icon files (empty box will be shown for stats without icons)
STAT_ICONS = {
    "Median Sold Price": "icons/Median Sold Price.png",
    "Median Price Per SqFt": "icons/Median Price Per Foot.png",
    "Months Supply (MSI)": "icons/MSI.png",
    "Total Sales Volume": "icons/Total Volume.png",
    "Active Inventory": "icons/Active Listings.png",
    "Pending Inventory": "icons/Pending Listings.png",
    "Median DOM": "icons/Avg Days on Market.png",
    "Sales Count": "icons/Closed Listings .png",
    "New Listings": "icons/New Listings.png",
}

# Stats available for Market Report (all stats from STATS_OPTIONS)
REPORT_STATS = STATS_OPTIONS

st.set_page_config(
    page_title="ReStats - Real Estate Intelligence", 
    layout="wide",
    page_icon="🏠"
)

# --- CUSTOM CSS ---
import base64

def get_base64_image(image_path):
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode()

# Load images
try:
    banner_b64 = get_base64_image("banner.png")
    background_b64 = get_base64_image("background.png")
except:
    banner_b64 = ""
    background_b64 = ""

st.markdown(f"""
    <style>
        /* Google Fonts */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Playfair+Display:ital,wght@0,400;0,700;1,400&display=swap');
        
        /* ============================================
           DEEP OCEAN COLOR SYSTEM
           Dominant (60%): #0B1021 - Midnight Abyss
           Secondary (30%): #1C2333 - Slate Glass
           Accent (10%): #CFB53B - Prestige Gold
           Functional: #2E5CFF Trust Blue
           Functional: #00D09C Growth Green
           Functional: #FF6B6B Alert Coral
           Typography: #FFFFFF Pure White
           Typography: #A0AEC0 Muted Silver
           ============================================ */
        
        /* Page background - Deep Ocean */
        .stApp {{
            background: #0B1021 !important;
        }}
        
        /* Remove any overlay */
        .stApp::before {{
            display: none;
        }}
        
        /* Main container */
        .block-container {{
            padding-top: 0;
            padding-bottom: 1rem;
        }}
        
        /* All text defaults to light */
        .stApp, .stApp p, .stApp span, .stApp label, .stApp div {{
            color: #E2E8F0;
        }}
        
        /* Banner header - Deep Ocean gradient */
        .banner-container {{
            width: 100vw;
            margin-left: calc(-50vw + 50%);
            margin-top: -1rem;
            margin-bottom: 2rem;
            height: 180px;
            background: linear-gradient(135deg, #0B1021 0%, #1C2333 40%, #0B1021 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
            border-bottom: 1px solid rgba(207, 181, 59, 0.3);
        }}
        .banner-container::before {{
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: radial-gradient(ellipse at 50% 50%, rgba(46, 92, 255, 0.08) 0%, transparent 70%);
        }}
        .banner-content {{
            position: relative;
            text-align: center;
        }}
        .banner-title {{
            display: block;
            color: #FFFFFF;
            font-family: 'Inter', sans-serif;
            font-size: 2.6rem;
            font-weight: 700;
            letter-spacing: 3px;
            margin-bottom: 6px;
            margin-top: 20px;
            text-transform: uppercase;
        }}
        .banner-gold-line {{
            width: 80px;
            height: 2px;
            background: #CFB53B;
            margin: 8px auto;
        }}
        .banner-subtitle {{
            display: block;
            color: #A0AEC0;
            font-family: 'Playfair Display', serif;
            font-size: 1.05rem;
            font-weight: 400;
            font-style: italic;
            letter-spacing: 1px;
        }}
        
        /* Header styling */
        h1 {{
            display: none;
        }}
        h2, h3, h4 {{
            color: #FFFFFF !important;
            font-family: 'Inter', sans-serif !important;
        }}
        
        /* ============================================
           GLASSMORPHISM KPI CARDS
           ============================================ */
        div[data-testid="stMetricValue"] {{
            font-size: 30px; 
            font-weight: 700;
            color: #CFB53B !important;
            font-family: 'Inter', sans-serif;
        }}
        div[data-testid="stMetricLabel"] {{
            font-weight: 600;
            color: #A0AEC0 !important;
            font-family: 'Inter', sans-serif;
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 1px;
        }}
        div[data-testid="stMetricDelta"] {{
            color: #00D09C !important;
        }}
        div[data-testid="stMetric"] {{
            background: rgba(28, 35, 51, 0.7) !important;
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            padding: 20px;
            border-radius: 16px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            transition: transform 0.3s ease, box-shadow 0.3s ease, border-color 0.3s ease;
        }}
        div[data-testid="stMetric"]:hover {{
            transform: translateY(-4px);
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.4);
            border-color: rgba(207, 181, 59, 0.3);
        }}
        
        /* ============================================
           GLASSMORPHISM EXPANDERS
           ============================================ */
        div[data-testid="stExpander"] {{
            background: rgba(28, 35, 51, 0.6) !important;
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            border-radius: 16px !important;
            margin-bottom: 1rem;
        }}
        div[data-testid="stExpander"] summary {{
            color: #E2E8F0 !important;
            font-weight: 600;
        }}
        div[data-testid="stExpander"] summary:hover {{
            color: #CFB53B !important;
        }}
        
        /* ============================================
           BUTTONS - Gold accent for primary
           ============================================ */
        .stButton > button[kind="primary"] {{
            background: linear-gradient(135deg, #CFB53B 0%, #B8960F 100%) !important;
            color: #0B1021 !important;
            border: none;
            border-radius: 10px;
            font-weight: 700;
            font-family: 'Inter', sans-serif;
            letter-spacing: 0.5px;
            transition: all 0.3s ease;
            text-transform: uppercase;
            font-size: 0.85rem;
        }}
        .stButton > button[kind="primary"]:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(207, 181, 59, 0.4);
        }}
        .stButton > button:not([kind="primary"]) {{
            background: rgba(28, 35, 51, 0.6) !important;
            color: #E2E8F0 !important;
            border-radius: 10px;
            border: 1px solid rgba(255, 255, 255, 0.12) !important;
            font-weight: 500;
            backdrop-filter: blur(10px);
            transition: all 0.3s ease;
        }}
        .stButton > button:not([kind="primary"]):hover {{
            border-color: rgba(207, 181, 59, 0.4) !important;
            color: #CFB53B !important;
        }}
        
        /* ============================================
           TABS - Dark glass style
           ============================================ */
        .stTabs [data-baseweb="tab-list"] {{
            gap: 4px;
            background: rgba(28, 35, 51, 0.5);
            padding: 6px;
            border-radius: 14px;
            border: 1px solid rgba(255, 255, 255, 0.06);
        }}
        .stTabs [data-baseweb="tab"] {{
            border-radius: 10px;
            font-weight: 600;
            padding: 10px 20px;
            color: #A0AEC0 !important;
            font-family: 'Inter', sans-serif;
            transition: all 0.3s ease;
        }}
        .stTabs [data-baseweb="tab"]:hover {{
            color: #CFB53B !important;
        }}
        .stTabs [aria-selected="true"] {{
            background: rgba(207, 181, 59, 0.15) !important;
            color: #CFB53B !important;
            box-shadow: 0 2px 8px rgba(207, 181, 59, 0.2);
            border: 1px solid rgba(207, 181, 59, 0.3);
        }}
        
        /* ============================================
           CHART CARDS - Glassmorphism
           ============================================ */
        .chart-card {{
            background: rgba(28, 35, 51, 0.6);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 1.5rem;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
            border: 1px solid rgba(255, 255, 255, 0.08);
            transition: border-color 0.3s ease;
        }}
        .chart-card:hover {{
            border-color: rgba(207, 181, 59, 0.2);
        }}
        .chart-card h3 {{
            color: #FFFFFF !important;
            font-family: 'Inter', sans-serif;
            font-weight: 600;
            margin-bottom: 1rem;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid rgba(207, 181, 59, 0.3);
        }}
        
        /* ============================================
           FORM INPUTS - Dark glass
           ============================================ */
        div[data-baseweb="select"] > div {{
            background: rgba(28, 35, 51, 0.8) !important;
            border-color: rgba(255, 255, 255, 0.1) !important;
            border-radius: 10px !important;
            color: #E2E8F0 !important;
        }}
        div[data-baseweb="select"] > div:hover {{
            border-color: rgba(207, 181, 59, 0.4) !important;
        }}
        /* Selected value text inside select box */
        div[data-baseweb="select"] span,
        div[data-baseweb="select"] div[data-baseweb="select-value"] *,
        div[data-baseweb="select"] input {{
            color: #E2E8F0 !important;
            -webkit-text-fill-color: #E2E8F0 !important;
        }}
        div[data-baseweb="select"] input::placeholder {{
            color: #718096 !important;
            -webkit-text-fill-color: #718096 !important;
        }}
        
        /* ============================================
           DROPDOWN / POPOVER - Force dark background
           Targets every possible Streamlit/BaseWeb 
           dropdown container and list item
           ============================================ */
        /* Popover container (the floating box) */
        div[data-baseweb="popover"],
        div[data-baseweb="popover"] > div,
        div[data-baseweb="popover"] > div > div {{
            background: #1C2333 !important;
            background-color: #1C2333 !important;
            border: 1px solid rgba(207, 181, 59, 0.25) !important;
            border-radius: 12px !important;
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.6) !important;
        }}
        /* Menu list */
        ul[data-baseweb="menu"],
        div[data-baseweb="popover"] ul,
        [role="listbox"] {{
            background: #1C2333 !important;
            background-color: #1C2333 !important;
        }}
        /* All list items inside any dropdown */
        li[role="option"],
        li[data-baseweb="menu-item"],
        ul[data-baseweb="menu"] li,
        [role="listbox"] li,
        div[data-baseweb="popover"] li {{
            color: #E2E8F0 !important;
            background: #1C2333 !important;
            background-color: #1C2333 !important;
        }}
        /* Hover state */
        li[role="option"]:hover,
        li[data-baseweb="menu-item"]:hover,
        div[data-baseweb="popover"] li:hover {{
            background: rgba(207, 181, 59, 0.18) !important;
            background-color: rgba(207, 181, 59, 0.18) !important;
            color: #CFB53B !important;
        }}
        /* Focused / highlighted item (keyboard nav) */
        li[role="option"][aria-selected="true"],
        li[role="option"]:focus,
        li[data-baseweb="menu-item"][aria-selected="true"],
        li[aria-selected="true"] {{
            background: rgba(207, 181, 59, 0.22) !important;
            background-color: rgba(207, 181, 59, 0.22) !important;
            color: #CFB53B !important;
        }}
        /* Checkbox inside multiselect dropdown */
        div[data-baseweb="checkbox"] span {{
            color: #E2E8F0 !important;
        }}
        
        /* Text inputs */
        div[data-baseweb="input"] > div {{
            background: rgba(28, 35, 51, 0.8) !important;
            border-color: rgba(255, 255, 255, 0.1) !important;
            border-radius: 10px !important;
        }}
        div[data-baseweb="input"] input {{
            color: #E2E8F0 !important;
            -webkit-text-fill-color: #E2E8F0 !important;
        }}
        
        /* Multiselect tags */
        span[data-baseweb="tag"] {{
            background: rgba(207, 181, 59, 0.2) !important;
            border: 1px solid rgba(207, 181, 59, 0.4) !important;
            color: #CFB53B !important;
            border-radius: 6px !important;
        }}
        span[data-baseweb="tag"] span {{
            color: #CFB53B !important;
        }}
        
        /* Date input / calendar */
        div[data-baseweb="calendar"],
        div[data-baseweb="calendar"] * {{
            background-color: #1C2333 !important;
            color: #E2E8F0 !important;
        }}
        
        /* Number input */
        input[type="number"] {{
            color: #E2E8F0 !important;
            -webkit-text-fill-color: #E2E8F0 !important;
        }}
        
        /* Number input */
        input[type="number"] {{
            background: rgba(28, 35, 51, 0.8) !important;
            color: #E2E8F0 !important;
            border-color: rgba(255, 255, 255, 0.1) !important;
            border-radius: 10px !important;
        }}
        
        /* Slider */
        div[data-baseweb="slider"] div[role="slider"] {{
            background: #CFB53B !important;
        }}
        
        /* ============================================
           DATAFRAME / TABLE
           ============================================ */
        .stDataFrame {{
            border-radius: 12px;
            overflow: hidden;
        }}
        
        /* ============================================
           DIVIDER
           ============================================ */
        hr {{
            border: none;
            height: 1px;
            background: linear-gradient(90deg, transparent 0%, rgba(207, 181, 59, 0.3) 50%, transparent 100%);
            margin: 1.5rem 0;
        }}
        
        /* ============================================
           CAPTIONS & SMALL TEXT
           ============================================ */
        .stCaption, small, .stCaption p {{
            color: #718096 !important;
        }}
        
        /* Sidebar (if used) */
        section[data-testid="stSidebar"] {{
            background: #0B1021 !important;
            border-right: 1px solid rgba(255, 255, 255, 0.06);
        }}
        
        /* Download button */
        .stDownloadButton > button {{
            background: rgba(0, 208, 156, 0.15) !important;
            color: #00D09C !important;
            border: 1px solid rgba(0, 208, 156, 0.3) !important;
            border-radius: 10px;
            font-weight: 600;
        }}
        .stDownloadButton > button:hover {{
            background: rgba(0, 208, 156, 0.25) !important;
            box-shadow: 0 4px 12px rgba(0, 208, 156, 0.2);
        }}
        
        /* Success/Error/Warning messages */
        div[data-baseweb="notification"] {{
            border-radius: 12px !important;
        }}
        
        /* Plotly charts - transparent bg */
        .js-plotly-plot {{
            border-radius: 12px;
        }}
    </style>
""", unsafe_allow_html=True)

# --- DATA LOADING ---
@st.cache_data
def load_data():
    try:
        conn = sqlite3.connect(DB_FILE)
        # Check if pcn_validated column exists
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(listing_details)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # Build query with available columns
        base_cols = """listing_number, status, listing_date, sold_date, 
                under_contract_date, effective_active_end_date, fallthrough_date,
                cancel_date, withdrawn_date, status_change_date,
                sold_price, list_price, original_list_price, sqft_living,
                city, zip_code, final_subdivision, property_type, terms_of_sale,
                total_bedrooms, baths_total, sqft_total, days_on_market, short_address,
                geo_lat, geo_lon"""
        
        extra_cols = []
        if 'pcn_validated' in columns:
            extra_cols.append('pcn_validated')
        if 'geo_zone' in columns:
            extra_cols.append('geo_zone')
        
        if extra_cols:
            query = f"SELECT {base_cols}, {', '.join(extra_cols)} FROM listing_details"
        else:
            query = f"SELECT {base_cols} FROM listing_details"
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        date_cols = [
            'listing_date', 'sold_date', 'under_contract_date', 
            'effective_active_end_date', 'fallthrough_date',
            'cancel_date', 'withdrawn_date', 'status_change_date'
        ]
        for col in date_cols:
            df[col] = pd.to_datetime(df[col], errors='coerce')
            
        return df
    except Exception as e:
        st.error(f"Error loading database: {e}")
        return pd.DataFrame()

# --- HELPER: FORMATTING & CHART TYPES ---
def get_format_settings(stat_name):
    """Returns (y_tooltip_format, axis_format)"""
    if "Discount" in stat_name or "Cash" in stat_name:
        return ".1f", ".1f%"
    elif "Supply" in stat_name:
        return ".1f", ".1f"
    elif any(x in stat_name for x in ["Price", "Volume"]):
        return "$,.0f", "$,.0f"
    else:
        return ",.0f", ",.0f"

def get_chart_type(stat_name):
    """Returns px.bar or px.line based on metric type"""
    if stat_name in ["Sales Count", "Total Sales Volume", "New Listings"]:
        return px.bar
    return px.line

# --- MAIN LOGIC ---
def main():
    if 'report_data' not in st.session_state:
        st.session_state.report_data = None
    if 'report_metadata' not in st.session_state:
        st.session_state.report_metadata = {}

    df_master = load_data()
    if df_master.empty:
        st.warning("No data found in MLS Database. Run `generate_db.py` first.")
        st.stop()

    # === BANNER HEADER ===
    st.markdown("""
        <div class="banner-container">
            <div class="banner-content">
                <span class="banner-title">ReStats Analytics</span>
                <div class="banner-gold-line"></div>
                <span class="banner-subtitle">Comprehensive Market Intelligence for Palm Beach County</span>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    
    # === TOP FILTER BAR ===
    with st.expander("🎯 **Filters & Settings** (click to expand)", expanded=True):
        # Row 1: Property, City, Subdivision
        r1c1, r1c2, r1c3 = st.columns(3)
        
        with r1c1:
            prop_type_selection = st.selectbox("Property Type", ["All Types", "Single Family", "Condo/TH/Other"])
        
        with r1c2:
            cities = sorted(df_master['city'].dropna().unique())
            selected_cities = st.multiselect("Cities", cities)
        
        with r1c3:
            # Geo Zone filter (e.g., South End Palm Beach)
            geo_zones_available = []
            if 'geo_zone' in df_master.columns:
                geo_zones_available = sorted(df_master['geo_zone'].dropna().unique().tolist())
            selected_geo_zone = st.selectbox("Geo Zone", ["All"] + geo_zones_available, key="geo_zone_filter")
        
        # Build context for subdivision dropdown (filtered by property type, cities, AND geo zone)
        df_context = df_master.copy()
        if prop_type_selection == "Single Family":
            prop_mask = df_context['property_type'].astype(str).str.contains("Single", case=False, na=False) | \
                       (df_context['property_type'].astype(str).str.upper() == "SF")
            df_context = df_context[prop_mask]
        elif prop_type_selection == "Condo/TH/Other":
            prop_mask = df_context['property_type'].astype(str).str.contains("Single", case=False, na=False) | \
                       (df_context['property_type'].astype(str).str.upper() == "SF")
            df_context = df_context[~prop_mask]
        if selected_cities:
            df_context = df_context[df_context['city'].isin(selected_cities)]
        if selected_geo_zone != "All" and 'geo_zone' in df_context.columns:
            df_context = df_context[df_context['geo_zone'] == selected_geo_zone]
        if 'pcn_validated' in df_context.columns:
            df_validated = df_context[df_context['pcn_validated'] == True]
        else:
            df_validated = df_context
        
        # Subdivision dropdown (now filtered by geo zone too)
        r1c4_col1, r1c4_col2 = st.columns(2)
        with r1c4_col1:
            subdivisions = sorted(df_validated['final_subdivision'].dropna().unique())
            selected_subs = st.multiselect("Subdivisions", subdivisions)
        
        # Row 2: Timeframe first (affects other selectors)
        st.markdown("**Date Range**")
        current_year = datetime.now().year
        current_month = datetime.now().month
        current_quarter = (current_month - 1) // 3 + 1
        
        # Timeframe selection first
        r2c0, r2c1, r2c2, r2c3, r2c4 = st.columns(5)
        with r2c0:
            timeframe = st.selectbox("Timeframe", ["Monthly", "Quarterly", "Annually"])
        
        # Dynamic date selectors based on timeframe
        if timeframe == "Monthly":
            with r2c1:
                start_month = st.selectbox("Start Month", range(1, 13), index=0, key="start_month",
                                           format_func=lambda x: datetime(2000, x, 1).strftime("%b"))
            with r2c2:
                start_year = st.selectbox("Start Year", range(2015, current_year + 1),
                                          index=max(0, current_year - 2015 - 2), key="start_year")
            with r2c3:
                end_month = st.selectbox("End Month", range(1, 13), index=current_month - 1, key="end_month",
                                         format_func=lambda x: datetime(2000, x, 1).strftime("%b"))
            with r2c4:
                end_year = st.selectbox("End Year", range(2015, current_year + 1),
                                        index=current_year - 2015, key="end_year")
        elif timeframe == "Quarterly":
            with r2c1:
                start_quarter = st.selectbox("Start Quarter", [1, 2, 3, 4], index=0, key="start_quarter",
                                             format_func=lambda x: f"Q{x}")
            with r2c2:
                start_year = st.selectbox("Start Year", range(2015, current_year + 1),
                                          index=max(0, current_year - 2015 - 2), key="start_year_q")
            with r2c3:
                end_quarter = st.selectbox("End Quarter", [1, 2, 3, 4], index=current_quarter - 1, key="end_quarter",
                                           format_func=lambda x: f"Q{x}")
            with r2c4:
                end_year = st.selectbox("End Year", range(2015, current_year + 1),
                                        index=current_year - 2015, key="end_year_q")
            # Convert quarters to months
            start_month = (start_quarter - 1) * 3 + 1
            end_month = end_quarter * 3
        else:  # Annually
            with r2c1:
                start_year = st.selectbox("Start Year", range(2015, current_year + 1),
                                          index=max(0, current_year - 2015 - 2), key="start_year_a")
            with r2c2:
                end_year = st.selectbox("End Year", range(2015, current_year + 1),
                                        index=current_year - 2015, key="end_year_a")
            with r2c3:
                st.empty()
            with r2c4:
                st.empty()
            # Full year range
            start_month = 1
            end_month = 12
        
        # Row 3: Metrics & Buttons
        r3c1, r3c2, r3c3 = st.columns([3, 1, 1])
        with r3c1:
            stats_to_run = st.multiselect("Metrics to Analyze", STATS_OPTIONS, 
                                          default=["Median Sold Price", "Market Grade", "Months Supply (MSI)"])
        with r3c2:
            st.markdown("<br>", unsafe_allow_html=True)
            run_analysis = st.button("📊 Run Analysis", type="primary", use_container_width=True)
        with r3c3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔄 Refresh Data", use_container_width=True, help="Reload from database"):
                st.cache_data.clear()
                st.rerun()
    
    # === APPLY FILTERS ===
    from analytics_logger import logger, log_section
    log_section("UI FILTERS APPLIED")
    logger.info(f"Starting with {len(df_master)} total records")
    
    df_filtered = df_master.copy()
    if prop_type_selection == "Single Family":
        mask = df_filtered['property_type'].astype(str).str.contains("Single", case=False, na=False) | \
               (df_filtered['property_type'].astype(str).str.upper() == "SF")
        df_filtered = df_filtered[mask]
        logger.info(f"Property Type filter (Single Family): {len(df_filtered)} records")
    elif prop_type_selection == "Condo/TH/Other":
        mask = df_filtered['property_type'].astype(str).str.contains("Single", case=False, na=False) | \
               (df_filtered['property_type'].astype(str).str.upper() == "SF")
        df_filtered = df_filtered[~mask]
        logger.info(f"Property Type filter (Condo/TH/Other): {len(df_filtered)} records")
    else:
        logger.info(f"Property Type filter (All): {len(df_filtered)} records")
    
    if selected_cities:
        df_filtered = df_filtered[df_filtered['city'].isin(selected_cities)]
        logger.info(f"City filter ({selected_cities}): {len(df_filtered)} records")
    if selected_subs:
        df_filtered = df_filtered[df_filtered['final_subdivision'].isin(selected_subs)]
        logger.info(f"Subdivision filter ({selected_subs}): {len(df_filtered)} records")
    if selected_geo_zone != "All" and 'geo_zone' in df_filtered.columns:
        df_filtered = df_filtered[df_filtered['geo_zone'] == selected_geo_zone]
        logger.info(f"Geo Zone filter ({selected_geo_zone}): {len(df_filtered)} records")
    
    logger.info(f"Final filtered dataset: {len(df_filtered)} records")
    
    # === BUILD DATE STRINGS ===
    start_date_str = f"{start_year}-{start_month:02d}-01"
    last_day = calendar.monthrange(end_year, end_month)[1]
    end_date_str = f"{end_year}-{end_month:02d}-{last_day}"
    
    # === RUN ANALYSIS ===
    if run_analysis or st.session_state.report_data is None:
        params = {
            "start_date": start_date_str,
            "end_date": end_date_str,
            "timeframe": timeframe.lower(),
            "calculate_yoy": True,
            "stats_to_calculate": stats_to_run
        }
        st.session_state.report_data = analyze_real_estate_data(df_filtered, params)
        st.session_state.report_metadata["timeframe"] = timeframe
        # Store filter values for PDF report
        st.session_state.report_start_date = start_date_str
        st.session_state.report_end_date = end_date_str
        st.session_state.report_cities = selected_cities if selected_cities else []
        st.session_state.report_subdivisions = selected_subs if selected_subs else []
        st.session_state.report_property_type = prop_type_selection
        st.session_state.report_geo_zone = selected_geo_zone
    
    # === KPI CARDS ===
    st.divider()
    latest_price = df_filtered[df_filtered['sold_date'] >= '2024-01-01']['sold_price'].median()
    active_now_mask = (df_filtered['listing_date'].notna()) & \
                      ((df_filtered['effective_active_end_date'].isna()) | (df_filtered['effective_active_end_date'] > datetime.now()))
    active_count = active_now_mask.sum()
    
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Median Price (2024+)", f"${latest_price:,.0f}" if pd.notna(latest_price) else "N/A")
    k2.metric("Active Listings", f"{active_count}")
    k3.metric("Records Analyzed", f"{len(df_filtered):,}")
    k4.metric("Date Range", f"{start_month}/{start_year} - {end_month}/{end_year}")
    
    st.divider()

    # === TABS ===
    tab_analytics, tab_report, tab_calculator, tab_raw = st.tabs(["📈 Market Trends", "📄 Market Report", "🧮 Deal Simulator", "💾 Data Explorer"])

    with tab_analytics:
        render_analytics_tab()

    with tab_report:
        render_market_report_tab(df_filtered, selected_cities, selected_subs, prop_type_selection, selected_geo_zone)

    with tab_calculator:
        render_calculator_tab()

    with tab_raw:
        st.subheader("🔍 Data Explorer")
        
        # All available columns for selection
        all_columns = [
            'listing_number', 'status', 'city', 'final_subdivision', 'property_type',
            'total_bedrooms', 'baths_full', 'baths_half', 'baths_total',
            'sqft_living', 'sqft_total', 'lot_sqft', 'year_built',
            'list_price', 'sold_price', 'original_list_price',
            'listing_date', 'sold_date', 'under_contract_date', 'effective_active_end_date',
            'days_on_market', 'short_address', 'waterfront', 'private_pool',
            'listing_agent', 'listing_office', 'buyer_agent', 'buyer_office',
            'geo_lat', 'geo_lon'
        ]
        
        # Filters for raw data
        raw_col1, raw_col2, raw_col3 = st.columns(3)
        with raw_col1:
            status_filter = st.multiselect(
                "Filter by Status",
                options=sorted(df_filtered['status'].dropna().unique().tolist()),
                default=[],
                key="raw_status_filter"
            )
        with raw_col2:
            show_cols = st.multiselect(
                "Columns to Display",
                options=[c for c in all_columns if c in df_filtered.columns],
                default=['listing_number', 'status', 'total_bedrooms', 'baths_total', 
                         'sqft_living', 'list_price', 'sold_price', 'sold_date'],
                key="raw_cols"
            )
        with raw_col3:
            max_rows = st.number_input("Max Rows", min_value=10, max_value=5000, value=100, key="raw_max_rows")
        
        # Apply status filter
        df_display = df_filtered.copy()
        if status_filter:
            df_display = df_display[df_display['status'].isin(status_filter)]
        
        # Show available columns that exist
        available_cols = [c for c in show_cols if c in df_display.columns]
        
        # Format price columns for display
        df_show = df_display[available_cols].head(max_rows).copy()
        for col in ['list_price', 'sold_price', 'original_list_price']:
            if col in df_show.columns:
                df_show[col] = df_show[col].apply(lambda x: f"${x:,.0f}" if pd.notna(x) else "")
        
        st.caption(f"Showing {min(len(df_display), max_rows)} of {len(df_display)} records")
        st.dataframe(df_show, use_container_width=True)
        
        # Quick stats
        st.markdown("**Status Breakdown:**")
        status_counts = df_filtered['status'].value_counts()
        st.write(status_counts.to_dict())

def render_market_report_tab(df_filtered, selected_cities, selected_subs, prop_type_selection, selected_geo_zone="All"):
    """Render a one-page market report with up to 9 stats"""
    st.subheader("📄 Market Report Generator")
    
    # Report settings
    rpt_col1, rpt_col2, rpt_col3 = st.columns(3)
    
    with rpt_col1:
        report_period_type = st.selectbox(
            "Report Period",
            ["Single Month", "Single Quarter", "Single Year"],
            key="report_period_type"
        )
    
    current_year = datetime.now().year
    current_month = datetime.now().month
    
    with rpt_col2:
        if report_period_type == "Single Month":
            rpt_month = st.selectbox("Month", range(1, 13), index=current_month - 1,
                                     format_func=lambda x: datetime(2000, x, 1).strftime("%B"),
                                     key="rpt_month")
            rpt_year = st.selectbox("Year", range(2020, current_year + 1), 
                                    index=current_year - 2020, key="rpt_year")
        elif report_period_type == "Single Quarter":
            rpt_quarter = st.selectbox("Quarter", [1, 2, 3, 4], 
                                       format_func=lambda x: f"Q{x}",
                                       key="rpt_quarter")
            rpt_year = st.selectbox("Year", range(2020, current_year + 1),
                                    index=current_year - 2020, key="rpt_year_q")
        else:
            rpt_year = st.selectbox("Year", range(2020, current_year + 1),
                                    index=current_year - 2020, key="rpt_year_a")
    
    with rpt_col3:
        report_stats = st.multiselect(
            "Stats to Include (max 12)",
            REPORT_STATS,
            default=REPORT_STATS[:6],
            max_selections=12,
            key="report_stats"
        )
    
    # Build period strings
    if report_period_type == "Single Month":
        start_date = f"{rpt_year}-{rpt_month:02d}-01"
        last_day = calendar.monthrange(rpt_year, rpt_month)[1]
        end_date = f"{rpt_year}-{rpt_month:02d}-{last_day}"
        period_label = datetime(rpt_year, rpt_month, 1).strftime("%B %Y")
        timeframe = "monthly"
    elif report_period_type == "Single Quarter":
        start_month = (rpt_quarter - 1) * 3 + 1
        end_month = rpt_quarter * 3
        start_date = f"{rpt_year}-{start_month:02d}-01"
        last_day = calendar.monthrange(rpt_year, end_month)[1]
        end_date = f"{rpt_year}-{end_month:02d}-{last_day}"
        period_label = f"Q{rpt_quarter} {rpt_year}"
        timeframe = "quarterly"
    else:
        start_date = f"{rpt_year}-01-01"
        end_date = f"{rpt_year}-12-31"
        period_label = str(rpt_year)
        timeframe = "annually"
    
    # Build location string
    if selected_subs:
        location_str = ", ".join(selected_subs[:2]) + (f" +{len(selected_subs)-2} more" if len(selected_subs) > 2 else "")
    elif selected_cities:
        location_str = ", ".join(selected_cities[:2]) + (f" +{len(selected_cities)-2} more" if len(selected_cities) > 2 else "")
    else:
        location_str = "Palm Beach County"
    
    # Add geo zone if selected
    if selected_geo_zone and selected_geo_zone != "All":
        location_str = f"{selected_geo_zone}, {location_str}"
    
    # Build property type string (friendly names)
    prop_type_display = {
        "Single Family": "Single Family Home",
        "Condo/TH/Other": "Condo/Townhouse", 
        "All Types": "All"
    }
    type_str = prop_type_display.get(prop_type_selection, "All")
    
    # Generate Report Button
    if st.button("🖨️ Generate Report", type="primary", key="gen_report"):
        with st.spinner("Generating report..."):
            params = {
                "start_date": start_date,
                "end_date": end_date,
                "timeframe": timeframe,
                "calculate_yoy": True,
                "stats_to_calculate": report_stats
            }
            report_data = analyze_real_estate_data(df_filtered, params)
            st.session_state.market_report_data = report_data
            st.session_state.market_report_meta = {
                "period": period_label,
                "location": location_str,
                "property_type": type_str
            }
    
    # Display Report
    if 'market_report_data' in st.session_state and st.session_state.market_report_data:
        report_data = st.session_state.market_report_data
        meta = st.session_state.get('market_report_meta', {})
        
        if "error" in report_data:
            st.error(report_data["error"])
            return
        
        # Report Header
        st.markdown(f"""
        <div style="background: rgba(28, 35, 51, 0.7); backdrop-filter: blur(20px);
                    border: 1px solid rgba(207, 181, 59, 0.3);
                    color: white; padding: 24px; border-radius: 16px; margin-bottom: 20px; text-align: center;">
            <h1 style="margin: 0; font-size: 2.5rem; color: #CFB53B; font-family: Inter, sans-serif; letter-spacing: 2px;">PALM BEACH</h1>
            <div style="width: 60px; height: 2px; background: #CFB53B; margin: 10px auto;"></div>
            <h2 style="margin: 8px 0; font-size: 1.2rem; color: #FFFFFF;">{meta.get('location', 'Palm Beach County')}</h2>
            <p style="margin: 8px 0; font-size: 1rem; color: #A0AEC0;">
                {meta.get('property_type', 'All')}
            </p>
            <p style="margin: 8px 0; font-size: 1rem; color: #A0AEC0;">
                {meta.get('period', '')}
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        # Stats Grid (3x3)
        stats_to_show = [s for s in report_stats if s in report_data and isinstance(report_data[s], pd.DataFrame)]
        
        # Create rows of 3
        for row_start in range(0, len(stats_to_show), 3):
            row_stats = stats_to_show[row_start:row_start + 3]
            cols = st.columns(len(row_stats))
            
            for idx, stat in enumerate(row_stats):
                df_stat = report_data[stat]
                if df_stat.empty:
                    continue
                
                # Get the last period's value
                last_row = df_stat.iloc[-1]
                value = last_row.get(stat, None)
                yoy_col = f"{stat} YoY %"
                yoy = last_row.get(yoy_col, None) if yoy_col in df_stat.columns else None
                
                # Format value - ensure it's numeric
                if pd.isna(value) or value is None:
                    formatted_value = "N/A"
                else:
                    # Convert to numeric if it's a string
                    try:
                        value = float(value) if isinstance(value, str) else value
                    except (ValueError, TypeError):
                        formatted_value = str(value)
                        value = None
                    
                    if value is not None:
                        if "Price" in stat or "Volume" in stat:
                            formatted_value = f"${value:,.0f}"
                        elif "%" in stat or "Discount" in stat:
                            formatted_value = f"{value:.1f}%"
                        elif "Supply" in stat or "MSI" in stat:
                            formatted_value = f"{value:.1f}"
                        else:
                            formatted_value = f"{value:,.0f}"
                
                # Format YoY
                if pd.notna(yoy):
                    yoy_color = "#00D09C" if yoy >= 0 else "#FF6B6B"
                    yoy_arrow = "▲" if yoy >= 0 else "▼"
                    yoy_str = f'<span style="color: {yoy_color}; font-size: 0.9rem;">{yoy_arrow} {abs(yoy):.1f}% YoY</span>'
                else:
                    yoy_str = '<span style="color: #718096; font-size: 0.9rem;">N/A</span>'
                
                # Get icon
                icon_path = STAT_ICONS.get(stat, "")
                if icon_path and os.path.exists(icon_path):
                    icon_b64 = get_base64_image(icon_path)
                    icon_html = f'<img src="data:image/png;base64,{icon_b64}" style="width: 60px; height: 60px; margin-bottom: 10px;">'
                else:
                    icon_html = '<div style="width: 60px; height: 60px; background: #ddd; border-radius: 50%; margin: 0 auto 10px;"></div>'
                
                with cols[idx]:
                    st.markdown(f"""
                    <div style="background: rgba(28, 35, 51, 0.6); backdrop-filter: blur(20px);
                                border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 16px; 
                                padding: 20px; text-align: center; box-shadow: 0 8px 32px rgba(0,0,0,0.25);
                                min-height: 200px; transition: border-color 0.3s ease;">
                        {icon_html}
                        <div style="font-size: 0.85rem; color: #A0AEC0; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 1px;">{stat}</div>
                        <div style="font-size: 1.8rem; font-weight: bold; color: #CFB53B;">{formatted_value}</div>
                        {yoy_str}
                    </div>
                    """, unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # --- TREND CHART (pick best available stat with multiple data points) ---
        chart_stat = None
        chart_df_report = None
        preferred = ["Median Sold Price", "Total Sales Volume", "Sales Count", "Active Inventory", "Months Supply (MSI)"]
        for pref in preferred:
            if pref in report_data and isinstance(report_data[pref], pd.DataFrame) and not report_data[pref].empty:
                if pref in report_data[pref].columns and len(report_data[pref]) >= 2:
                    chart_stat = pref
                    chart_df_report = report_data[pref]
                    break
        if chart_stat is None:
            for s, df_r in report_data.items():
                if s == "Market Grade":
                    continue
                if isinstance(df_r, pd.DataFrame) and len(df_r) >= 2 and s in df_r.columns:
                    chart_stat = s
                    chart_df_report = df_r
                    break
        
        if chart_stat is not None and chart_df_report is not None:
            df_chart_rpt = chart_df_report.dropna(subset=[chart_stat]).copy()
            if not df_chart_rpt.empty and 'Period' in df_chart_rpt.columns:
                tooltip_fmt = "$,.0f" if ("Price" in chart_stat or "Volume" in chart_stat) else ".1f" if ("%" in chart_stat or "Supply" in chart_stat) else ",.0f"
                
                fig_rpt = px.line(df_chart_rpt, x="Period", y=chart_stat, markers=True,
                                  template="plotly_dark",
                                  color_discrete_sequence=["#2E5CFF"])
                fig_rpt.update_traces(
                    line=dict(width=3),
                    marker=dict(size=8, line=dict(width=2, color='#0B1021')),
                    hovertemplate='%{y:' + tooltip_fmt + '}'
                )
                fig_rpt.update_layout(
                    title=dict(text=f"Trend: {chart_stat}", font=dict(color='#FFFFFF', size=16)),
                    hovermode="x unified",
                    height=350,
                    margin=dict(t=40, b=40, l=60, r=20),
                    xaxis=dict(showgrid=False, tickfont=dict(size=11, color='#A0AEC0'), title=None, linecolor='rgba(255,255,255,0.1)'),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.06)', tickfont=dict(size=11, color='#A0AEC0'), title=None, linecolor='rgba(255,255,255,0.1)'),
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#A0AEC0'),
                    hoverlabel=dict(bgcolor='#1C2333', bordercolor='rgba(207,181,59,0.3)', font_color='#E2E8F0')
                )
                st.plotly_chart(fig_rpt, key="market_report_trend_chart", use_container_width=True)
        
        # Footer
        st.markdown(f"""
        <div style="text-align: center; color: #718096; font-size: 0.8rem; margin-top: 20px;">
            Generated by ReStats Analytics | Data as of {datetime.now().strftime("%B %d, %Y")}
        </div>
        """, unsafe_allow_html=True)
        
        # Build printable HTML with all stats
        stat_boxes_html = ""
        for idx, stat in enumerate(stats_to_show):
            df_stat = report_data[stat]
            if df_stat.empty:
                continue
            last_row = df_stat.iloc[-1]
            value = last_row.get(stat, None)
            yoy_col = f"{stat} YoY %"
            yoy = last_row.get(yoy_col, None) if yoy_col in df_stat.columns else None
            
            if pd.isna(value):
                formatted_value = "N/A"
            elif "Price" in stat or "Volume" in stat:
                formatted_value = f"${value:,.0f}"
            elif "%" in stat or "Discount" in stat:
                formatted_value = f"{value:.1f}%"
            elif "Supply" in stat or "MSI" in stat:
                formatted_value = f"{value:.1f}"
            else:
                formatted_value = f"{value:,.0f}"
            
            if pd.notna(yoy):
                yoy_color = "#00D09C" if yoy >= 0 else "#FF6B6B"
                yoy_arrow = "&#9650;" if yoy >= 0 else "&#9660;"
                yoy_str = f'<span style="color: {yoy_color};">{yoy_arrow} {abs(yoy):.1f}% YoY</span>'
            else:
                yoy_str = '<span style="color: #718096;">N/A</span>'
            
            icon_path = STAT_ICONS.get(stat, "")
            if icon_path and os.path.exists(icon_path):
                icon_b64 = get_base64_image(icon_path)
                icon_img = f'<img src="data:image/png;base64,{icon_b64}" style="width:50px;height:50px;margin-bottom:8px;">'
            else:
                icon_img = ''
            
            stat_boxes_html += f'''
            <div style="background:#1C2333;border:1px solid rgba(207,181,59,0.2);border-radius:12px;padding:15px;text-align:center;width:30%;display:inline-block;margin:1%;vertical-align:top;box-sizing:border-box;">
                {icon_img}
                <div style="font-size:0.85rem;color:#A0AEC0;margin-bottom:5px;text-transform:uppercase;letter-spacing:1px;">{stat}</div>
                <div style="font-size:1.5rem;font-weight:bold;color:#CFB53B;">{formatted_value}</div>
                {yoy_str}
            </div>
            '''
        
        print_html = f'''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Market Report - {meta.get('location', '')} - {meta.get('period', '')}</title>
            <style>
                body {{ font-family: 'Inter', Arial, sans-serif; margin: 20px; background: #0B1021; color: #E2E8F0; }}
                .header {{ background: #1C2333; border: 1px solid rgba(207,181,59,0.3); color: white; padding: 24px; border-radius: 12px; text-align: center; margin-bottom: 20px; }}
                .header h1 {{ margin: 0; font-size: 1.8rem; color: #FFFFFF; letter-spacing: 2px; }}
                .header h2 {{ margin: 5px 0; font-size: 1.3rem; color: #CFB53B; }}
                .header h3 {{ margin: 5px 0; font-size: 1rem; color: #A0AEC0; font-style: italic; }}
                .stats-grid {{ text-align: center; }}
                .footer {{ text-align: center; color: #718096; font-size: 0.8rem; margin-top: 20px; }}
                @media print {{ body {{ margin: 0; }} }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Market Report</h1>
                <h2>{meta.get('location', 'Palm Beach County')}</h2>
                <h3>{meta.get('period', '')}</h3>
            </div>
            <div class="stats-grid">
                {stat_boxes_html}
            </div>
            <div class="footer">
                Generated by ReStats Analytics | Data as of {datetime.now().strftime("%B %d, %Y")}
            </div>
            <script>window.onload = function() {{ window.print(); }}</script>
        </body>
        </html>
        '''
        
        # Encode HTML for JavaScript
        import base64
        html_b64 = base64.b64encode(print_html.encode()).decode()
        
        # Print and PDF Buttons
        st.markdown("<br>", unsafe_allow_html=True)
        btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 1])
        
        with btn_col1:
            import streamlit.components.v1 as components
            components.html(f"""
            <button id="printBtn" style="
                background: linear-gradient(135deg, #CFB53B 0%, #B8960F 100%);
                color: #0B1021;
                border: none;
                padding: 12px 20px;
                font-size: 0.9rem;
                border-radius: 10px;
                cursor: pointer;
                width: 100%;
                font-weight: 700;
                letter-spacing: 0.5px;
                text-transform: uppercase;
            ">🖨️ Print Report</button>
            <script>
                document.getElementById('printBtn').addEventListener('click', function() {{
                    var html = atob('{html_b64}');
                    var printWindow = window.open('', '_blank');
                    printWindow.document.write(html);
                    printWindow.document.close();
                }});
            </script>
            """, height=50)
        
        with btn_col2:
            # PDF Download for Market Report
            if st.button("📄 Download PDF", type="primary", key="market_report_pdf_btn"):
                with st.spinner("Generating PDF..."):
                    try:
                        # Build metadata for market report PDF
                        pdf_metadata = {
                            'timeframe': timeframe,
                            'start_date': start_date,
                            'end_date': end_date,
                            'cities': selected_cities if selected_cities else [],
                            'subdivisions': selected_subs if selected_subs else [],
                            'property_type': type_str,  # Use formatted type string
                            'geo_zone': selected_geo_zone if selected_geo_zone != "All" else None,
                            'period_label': period_label  # Add formatted period label
                        }
                        
                        pdf_bytes = generate_pdf_report(report_data, pdf_metadata, icons_path="icons")
                        
                        st.download_button(
                            label="📥 Click to Download",
                            data=pdf_bytes,
                            file_name=f"market_report_{meta.get('period', '').replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf",
                            mime="application/pdf",
                            key="market_report_pdf_download"
                        )
                        st.success("PDF ready!")
                    except Exception as e:
                        st.error(f"PDF Error: {str(e)}")


def render_analytics_tab():
    if st.session_state.report_data:
        results = st.session_state.report_data
        
        # Handle error case
        if "error" in results:
            st.error(results["error"])
        else:
            # =============================================
            # BUILD SPREADSHEET DATA FOR PRINT (metrics on Y, periods on X)
            # =============================================
            spreadsheet_data = {}  # {metric: {period: (value, yoy%)}}
            period_to_index = {}  # {period_label: period_index} for chronological sorting
            
            for stat, df_res in results.items():
                if stat == "Market Grade": continue
                if not isinstance(df_res, pd.DataFrame) or df_res.empty: continue
                if stat not in df_res.columns: continue
                
                # Check if PeriodIndex column exists in the DataFrame
                has_period_index = 'PeriodIndex' in df_res.columns
                
                yoy_col = f"{stat} YoY %"
                
                if has_period_index:
                    # Build period mapping from this DataFrame
                    for idx in df_res.index:
                        try:
                            period_label = df_res.loc[idx, 'Period']
                            period_idx = df_res.loc[idx, 'PeriodIndex']
                            if period_label and period_label not in period_to_index:
                                # Ensure we store the actual Period object, not a string
                                if hasattr(period_idx, 'to_timestamp'):
                                    # It's a pandas Period - store it directly
                                    period_to_index[period_label] = period_idx
                                else:
                                    # It's something else - try to convert to Period
                                    period_to_index[period_label] = pd.Period(period_idx)
                        except:
                            # Skip if there's any issue accessing the data
                            continue
                
                for idx, row in df_res.iterrows():
                    period = row.get('Period', str(row.get('PeriodIndex', '')))
                    if not period: continue
                    
                    val = row.get(stat)
                    yoy = row.get(yoy_col) if yoy_col in df_res.columns else None
                    
                    if stat not in spreadsheet_data:
                        spreadsheet_data[stat] = {}
                    spreadsheet_data[stat][period] = (val, yoy)
            
            # Sort periods chronologically
            if period_to_index:
                # Sort by the actual Period object for chronological order
                sorted_periods = sorted(period_to_index.keys(), key=lambda p: period_to_index[p])
            else:
                # Fallback: collect all unique periods and parse dates for sorting
                all_periods_set = set()
                for stat_data in spreadsheet_data.values():
                    all_periods_set.update(stat_data.keys())
                
                # Parse period labels to sort chronologically
                def parse_period_for_sort(period_str):
                    """Convert 'Jan 2025' to sortable tuple (2025, 1)"""
                    try:
                        from datetime import datetime
                        # Try to parse "Jan 2025" format
                        dt = datetime.strptime(period_str, "%b %Y")
                        return (dt.year, dt.month)
                    except:
                        # Fallback to alphabetical
                        return (9999, 99, period_str)
                
                sorted_periods = sorted(all_periods_set, key=parse_period_for_sort)
            
            # =============================================
            # PRINT BUTTON AT TOP
            # =============================================
            if spreadsheet_data:
                # Build spreadsheet HTML table
                def format_value(stat, val):
                    if pd.isna(val) or val is None:
                        return "N/A"
                    if "%" in stat or "Discount" in stat or "Cash" in stat:
                        return f"{val:.0f}%"
                    elif "Supply" in stat or "MSI" in stat:
                        return f"{val:.1f}"
                    elif "Price" in stat or "Volume" in stat:
                        return f"${val:,.0f}"
                    elif "DOM" in stat or "Count" in stat or "Inventory" in stat or "Listings" in stat:
                        return f"{val:,.0f}"
                    else:
                        try:
                            return f"{val:,.0f}" if val == int(val) else f"{val:,.1f}"
                        except:
                            return str(val)
                
                def format_yoy(yoy):
                    if pd.isna(yoy) or yoy is None:
                        return ""
                    return f"{yoy:+.0f}%"
                
                # Build HTML table rows
                table_rows = ""
                for stat in spreadsheet_data.keys():
                    row_cells = f"<td class='metric-name'>{stat}</td>"
                    for period in sorted_periods:
                        val, yoy = spreadsheet_data[stat].get(period, (None, None))
                        val_str = format_value(stat, val)
                        yoy_str = format_yoy(yoy)
                        yoy_class = "yoy-positive" if pd.notna(yoy) and yoy > 0 else "yoy-negative" if pd.notna(yoy) and yoy < 0 else ""
                        cell_content = f"<span class='val'>{val_str}</span>"
                        if yoy_str:
                            cell_content += f"<span class='yoy {yoy_class}'>{yoy_str}</span>"
                        row_cells += f"<td>{cell_content}</td>"
                    table_rows += f"<tr>{row_cells}</tr>"
                
                # Build header row
                header_cells = "<th>Metric</th>"
                for period in sorted_periods:
                    header_cells += f"<th>{period}</th>"
                
                # Build header info from session state
                start_date = st.session_state.get('report_start_date', '')
                end_date = st.session_state.get('report_end_date', '')
                timeframe_str = st.session_state.report_metadata.get('timeframe', 'Monthly')
                
                # Build location string
                location_parts = []
                geo_zone = st.session_state.get('report_geo_zone', 'All')
                if geo_zone and geo_zone != 'All':
                    location_parts.append(geo_zone)
                
                subs = st.session_state.get('report_subdivisions', [])
                cities = st.session_state.get('report_cities', [])
                if subs:
                    if len(subs) <= 2:
                        location_parts.append(', '.join(subs))
                    else:
                        location_parts.append(f"{', '.join(subs[:2])} +{len(subs)-2} more")
                elif cities:
                    if len(cities) <= 2:
                        location_parts.append(', '.join(cities))
                    else:
                        location_parts.append(f"{', '.join(cities[:2])} +{len(cities)-2} more")
                
                location_str = ', '.join(location_parts) if location_parts else 'Palm Beach County'
                
                # Property type
                prop_type_raw = st.session_state.get('report_property_type', 'All Types')
                prop_type_display = {
                    "Single Family": "Single Family Home",
                    "Condo/TH/Other": "Condo/Townhouse", 
                    "All Types": "All"
                }
                prop_type_str = prop_type_display.get(prop_type_raw, "All")
                
                # Determine if we need landscape (more than 6 periods)
                num_periods = len(sorted_periods)
                landscape = num_periods > 6
                font_size = "10px" if num_periods <= 8 else "9px" if num_periods <= 12 else "8px"
                th_pad = "8px 6px" if num_periods <= 8 else "6px 4px"
                td_pad = "10px 6px" if num_periods <= 8 else "8px 4px"
                metric_width = "180px" if num_periods <= 6 else "140px" if num_periods <= 10 else "120px"
                
                print_html = f'''
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Market Analysis Report</title>
                    <style>
                        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
                        @page {{ 
                            size: {"landscape" if landscape else "portrait"}; 
                            margin: 15mm; 
                        }}
                        * {{ box-sizing: border-box; }}
                        body {{ 
                            font-family: 'Inter', Arial, sans-serif; 
                            margin: 0; 
                            padding: 24px; 
                            background: #FFFFFF; 
                            color: #1a1a2e; 
                        }}
                        .header {{ 
                            background: linear-gradient(135deg, #1C2333 0%, #0B1021 100%); 
                            padding: 20px 28px; 
                            border-radius: 10px; 
                            margin-bottom: 24px; 
                            border-left: 4px solid #CFB53B;
                        }}
                        .header h1 {{ 
                            color: #FFFFFF; 
                            margin: 0 0 4px 0; 
                            font-size: 1.5rem; 
                            letter-spacing: 2px; 
                            text-transform: uppercase; 
                            font-weight: 700;
                        }}
                        .gold-line {{ width: 50px; height: 2px; background: #CFB53B; margin: 8px 0; }}
                        .subtitle {{ color: #A0AEC0; margin: 0; font-size: 0.85rem; font-style: italic; }}
                        
                        /* Table */
                        .table-wrapper {{
                            width: 100%;
                            overflow-x: auto;
                        }}
                        table {{ 
                            border-collapse: collapse; 
                            width: 100%; 
                            font-size: {font_size}; 
                            table-layout: fixed;
                        }}
                        th {{ 
                            background-color: #1C2333; 
                            color: #CFB53B; 
                            padding: {th_pad}; 
                            text-align: center; 
                            font-weight: 700; 
                            letter-spacing: 0.5px; 
                            text-transform: uppercase; 
                            font-size: {font_size}; 
                            border-bottom: 2px solid #CFB53B;
                            white-space: nowrap;
                        }}
                        th:first-child {{
                            text-align: left;
                            width: {metric_width};
                            min-width: 120px;
                        }}
                        td {{ 
                            border-bottom: 1px solid #e8e8e8; 
                            padding: {td_pad}; 
                            text-align: center; 
                            vertical-align: middle; 
                            color: #2d3748;
                            line-height: 1.4;
                        }}
                        td.metric-name {{ 
                            text-align: left; 
                            font-weight: 700; 
                            color: #1C2333; 
                            background-color: #f7f8fc; 
                            white-space: nowrap;
                            padding-left: 12px;
                            width: {metric_width};
                            border-right: 2px solid #CFB53B;
                        }}
                        tr:nth-child(even) {{ background-color: #fafbfe; }}
                        tr:hover {{ background-color: #f0f4ff; }}
                        
                        /* Values */
                        .val {{ font-weight: 600; font-size: 1em; display: block; }}
                        .yoy {{ font-size: 0.8em; display: block; margin-top: 1px; font-weight: 500; }}
                        .yoy-positive {{ color: #0d9668; }}
                        .yoy-negative {{ color: #dc2626; }}
                        
                        .footer {{ 
                            text-align: center; 
                            color: #a0a0a0; 
                            font-size: 0.75rem; 
                            margin-top: 20px; 
                            padding-top: 12px;
                            border-top: 1px solid #e8e8e8;
                        }}
                        
                        @media print {{ 
                            body {{ padding: 0; margin: 0; }}
                            .header {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
                            th {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
                            td.metric-name {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
                            tr:nth-child(even) {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
                        }}
                    </style>
                </head>
                <body>
                    <div class="header">
                        <h1>Palm Beach</h1>
                        <div class="gold-line"></div>
                        <p class="subtitle" style="margin: 4px 0; font-size: 0.9rem; color: #E2E8F0;">{location_str}</p>
                        <p class="subtitle" style="margin: 2px 0;">{prop_type_str}</p>
                        <p class="subtitle" style="margin: 2px 0;">{start_date} to {end_date} ({timeframe_str})</p>
                    </div>
                    <div class="table-wrapper">
                        <table>
                            <thead><tr>{header_cells}</tr></thead>
                            <tbody>{table_rows}</tbody>
                        </table>
                    </div>
                    <div class="footer">ReStats Analytics &bull; Palm Beach County Market Intelligence</div>
                    <script>window.onload = function() {{ window.print(); }}</script>
                </body>
                </html>
                '''
                
                import base64
                html_b64 = base64.b64encode(print_html.encode()).decode()
                
                # Two buttons side by side: Print and PDF Download
                btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 3])
                
                with btn_col1:
                    import streamlit.components.v1 as components
                    components.html(f"""
                    <button id="printSpreadsheetBtn" style="
                        background: linear-gradient(135deg, #CFB53B 0%, #B8960F 100%);
                        color: #0B1021;
                        border: none;
                        padding: 12px 20px;
                        font-size: 0.9rem;
                        border-radius: 10px;
                        cursor: pointer;
                        font-weight: 700;
                        letter-spacing: 0.5px;
                        text-transform: uppercase;
                    ">🖨️ Print</button>
                    <script>
                        document.getElementById('printSpreadsheetBtn').addEventListener('click', function() {{
                            var html = atob('{html_b64}');
                            var printWindow = window.open('', '_blank');
                            printWindow.document.write(html);
                            printWindow.document.close();
                        }});
                    </script>
                    """, height=50)
                
                with btn_col2:
                    # PDF Download button
                    if st.button("📄 Download PDF Report", type="primary", key="pdf_download_btn"):
                        with st.spinner("Generating professional PDF report..."):
                            try:
                                # Build metadata for report
                                report_metadata = st.session_state.get('report_metadata', {})
                                report_metadata['start_date'] = st.session_state.get('report_start_date', '')
                                report_metadata['end_date'] = st.session_state.get('report_end_date', '')
                                report_metadata['cities'] = st.session_state.get('report_cities', [])
                                report_metadata['subdivisions'] = st.session_state.get('report_subdivisions', [])
                                report_metadata['property_type'] = st.session_state.get('report_property_type', 'All')
                                report_metadata['geo_zone'] = st.session_state.get('report_geo_zone', 'All')
                                
                                pdf_bytes = generate_pdf_report(results, report_metadata, icons_path="icons")
                                
                                # Create download
                                st.download_button(
                                    label="📥 Click to Download PDF",
                                    data=pdf_bytes,
                                    file_name=f"market_report_{datetime.now().strftime('%Y%m%d')}.pdf",
                                    mime="application/pdf",
                                    key="pdf_download_actual"
                                )
                                st.success("PDF generated! Click above to download.")
                            except Exception as e:
                                st.error(f"Error generating PDF: {str(e)}")
            
            # =============================================
            # MARKET GRADE (special display)
            # =============================================
            if "Market Grade" in results:
                grade_df = results["Market Grade"]
                if isinstance(grade_df, pd.DataFrame) and not grade_df.empty and 'Market Grade' in grade_df.columns:
                    valid_grades = grade_df[grade_df['Market Grade'].notna()]
                    if not valid_grades.empty:
                        last_row = valid_grades.iloc[-1]
                        current_grade = last_row['Market Grade']
                        period = last_row.get('Period', str(last_row.get('PeriodIndex', 'Unknown')))
                        
                        grade_str = str(current_grade)
                        st.markdown("""<div class="chart-card">""", unsafe_allow_html=True)
                        st.markdown("### 📊 Proprietary Market Grade")
                        if "A" in grade_str:
                            color = "green"
                        elif "B" in grade_str:
                            color = "blue"
                        elif "C" in grade_str:
                            color = "orange"
                        elif "D" in grade_str:
                            color = "orange"
                        else:  # F
                            color = "red"
                        st.markdown(f"#### Current Grade: :{color}[{current_grade}]")
                        st.caption(f"Based on Velocity (DOM) & Absorption (MSI) as of {period}")
                        st.markdown("""</div>""", unsafe_allow_html=True)
            
            # =============================================
            # EACH STAT: Chart first (expanded), Data Table minimized
            # =============================================
            for stat, df_res in results.items():
                if stat == "Market Grade": continue
                if not isinstance(df_res, pd.DataFrame): continue
                if df_res.empty: continue
                if stat not in df_res.columns: continue
                
                st.markdown("""<div class="chart-card">""", unsafe_allow_html=True)
                st.markdown(f"### {stat}")
                
                # --- CHART FIRST (shown by default) ---
                df_chart = df_res.copy()
                for col in df_chart.columns:
                    if df_chart[col].dtype == "object" or str(df_chart[col].dtype).startswith("Int") or str(df_chart[col].dtype).startswith("Float"):
                        df_chart[col] = df_chart[col].astype(object).where(df_chart[col].notna(), None)
                
                df_chart = df_chart.dropna(subset=[stat])
                if not df_chart.empty:
                    has_gaps = len(df_chart) < len(df_res)
                    tooltip_fmt, axis_fmt = get_format_settings(stat)
                    chart_cls = get_chart_type(stat)
                    
                    if has_gaps and chart_cls == px.line:
                        chart_cls = px.bar

                    # Deep Ocean chart colors
                    chart_color = "#2E5CFF"  # Trust Blue for lines
                    bar_color = "rgba(207, 181, 59, 0.7)"  # Prestige Gold for bars
                    
                    use_color = bar_color if chart_cls == px.bar else chart_color
                    chart_args = {
                        "data_frame": df_chart,
                        "x": "Period",
                        "y": stat,
                        "template": "plotly_dark",
                        "color_discrete_sequence": [use_color]
                    }
                    
                    if chart_cls == px.line:
                        chart_args["markers"] = True

                    fig = chart_cls(**chart_args)
                    
                    if axis_fmt:
                        fig.update_layout(yaxis_tickformat=axis_fmt)
                    fig.update_traces(hovertemplate='%{y:' + tooltip_fmt + '}')
                    
                    # Deep Ocean chart styling
                    fig.update_layout(
                        hovermode="x unified", 
                        height=350,
                        title=None,
                        margin=dict(t=10, b=40, l=60, r=20),
                        xaxis=dict(
                            showgrid=False, 
                            tickfont=dict(size=11, color='#A0AEC0'), 
                            title=None,
                            linecolor='rgba(255,255,255,0.1)'
                        ),
                        yaxis=dict(
                            gridcolor='rgba(255,255,255,0.06)', 
                            tickfont=dict(size=11, color='#A0AEC0'), 
                            title=None,
                            linecolor='rgba(255,255,255,0.1)'
                        ),
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        font=dict(color='#A0AEC0'),
                        hoverlabel=dict(
                            bgcolor='#1C2333',
                            bordercolor='rgba(207,181,59,0.3)',
                            font_color='#E2E8F0'
                        )
                    )
                    
                    # Style line traces
                    if chart_cls == px.line:
                        fig.update_traces(
                            line=dict(width=3),
                            marker=dict(size=8, line=dict(width=2, color='#0B1021'))
                        )
                    else:
                        fig.update_traces(
                            marker=dict(line=dict(width=0)),
                            opacity=0.85
                        )
                    
                    st.plotly_chart(fig, key=f"chart_{stat.replace(' ', '_')}", use_container_width=True)
                
                # --- DATA TABLE (minimized by default) ---
                display_df = df_res.copy()
                
                col_config = {"Period": st.column_config.TextColumn("Period")}
                
                if stat in display_df.columns:
                    if "%" in stat or "Discount" in stat or "Cash" in stat:
                        col_config[stat] = st.column_config.NumberColumn(stat, format="%d%%")
                    elif "Supply" in stat or "MSI" in stat:
                        col_config[stat] = st.column_config.NumberColumn(stat, format="%.1f")
                    elif "Price" in stat or "Volume" in stat:
                        col_config[stat] = st.column_config.NumberColumn(stat, format="$%d")
                    elif "DOM" in stat or "Count" in stat or "Inventory" in stat or "Listings" in stat:
                        col_config[stat] = st.column_config.NumberColumn(stat, format="%d")
                
                yoy_col = f"{stat} YoY %"
                if yoy_col in display_df.columns:
                    col_config[yoy_col] = st.column_config.NumberColumn("YoY %", format="%+d%%")
                
                if "PeriodIndex" in display_df.columns:
                    col_config["PeriodIndex"] = None
                
                with st.expander("� View Data Table", expanded=False):
                    st.dataframe(display_df, hide_index=True, use_container_width=True, column_config=col_config, key=f"table_{stat.replace(' ', '_')}")
                
                st.markdown("""</div>""", unsafe_allow_html=True)

def render_calculator_tab():
    st.markdown("## Interactive Deal Simulator")
    st.markdown("Use this tool to test sensitivity (Report 3.1.2). How does interest rate impact your cash flow?")
    
    col_input, col_output = st.columns([1, 1])
    
    with col_input:
        st.markdown("#### Assumptions")
        price = st.number_input("Purchase Price", value=750000, step=10000)
        down_pct = st.slider("Down Payment %", 0, 100, 20)
        rate = st.slider("Interest Rate %", 3.0, 10.0, 6.5, 0.1)
        term = st.selectbox("Term (Years)", [30, 15])
        
        st.markdown("#### Operations")
        rent = st.number_input("Projected Monthly Rent", value=4500, step=100)
        taxes_yr = st.number_input("Annual Taxes", value=price * 0.015)
        ins_yr = st.number_input("Annual Insurance", value=3000)
        vacancy = st.slider("Vacancy Rate %", 0, 15, 5)

    with col_output:
        st.markdown("#### Pro Forma Results")
        
        loan_amount = price * (1 - (down_pct/100))
        monthly_rate = (rate / 100) / 12
        num_payments = term * 12
        
        if monthly_rate > 0:
            mortgage_payment = loan_amount * (monthly_rate * (1 + monthly_rate)**num_payments) / ((1 + monthly_rate)**num_payments - 1)
        else:
            mortgage_payment = loan_amount / num_payments
            
        monthly_taxes = taxes_yr / 12
        monthly_ins = ins_yr / 12
        monthly_vacancy_loss = rent * (vacancy/100)
        
        total_piti = mortgage_payment + monthly_taxes + monthly_ins
        noi = (rent - monthly_vacancy_loss) - (monthly_taxes + monthly_ins)
        cash_flow = rent - monthly_vacancy_loss - total_piti
        
        st.metric("Estimated Monthly PITI", f"${total_piti:,.2f}", help="Principal, Interest, Taxes, Insurance")
        
        delta_color = "normal" if cash_flow > 0 else "inverse"
        st.metric("Net Monthly Cash Flow", f"${cash_flow:,.2f}", delta=f"{cash_flow/rent*100:.1f}% Margin", delta_color=delta_color)
        
        initial_investment = (price * (down_pct/100)) + (price * 0.03) 
        coc_roi = (cash_flow * 12) / initial_investment * 100
        
        st.metric("Cash-on-Cash ROI", f"{coc_roi:.2f}%")
        
        waterfall_data = pd.DataFrame([
            {"Category": "Gross Rent", "Amount": rent, "Type": "Income"},
            {"Category": "Vacancy", "Amount": -monthly_vacancy_loss, "Type": "Expense"},
            {"Category": "Taxes/Ins", "Amount": -(monthly_taxes + monthly_ins), "Type": "Expense"},
            {"Category": "Mortgage", "Amount": -mortgage_payment, "Type": "Debt"},
            {"Category": "Net Cash Flow", "Amount": cash_flow, "Type": "Profit"}
        ])
        
        fig = px.bar(waterfall_data, x="Category", y="Amount", color="Type", text_auto=True, title="Monthly Cash Flow Waterfall",
                     color_discrete_map={"Income": "#00D09C", "Expense": "#FF6B6B", "Debt": "#2E5CFF", "Profit": "#CFB53B"})
        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#A0AEC0'),
            title_font=dict(color='#FFFFFF'),
            xaxis=dict(tickfont=dict(color='#A0AEC0'), linecolor='rgba(255,255,255,0.1)'),
            yaxis=dict(tickfont=dict(color='#A0AEC0'), gridcolor='rgba(255,255,255,0.06)', linecolor='rgba(255,255,255,0.1)'),
            legend=dict(font=dict(color='#A0AEC0')),
            hoverlabel=dict(bgcolor='#1C2333', bordercolor='rgba(207,181,59,0.3)', font_color='#E2E8F0')
        )
        st.plotly_chart(fig, key="waterfall_chart", use_container_width=True)

if __name__ == "__main__":
    main()
