import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
import calendar
from datetime import datetime
from data_analysis import analyze_real_estate_data

# --- CONFIGURATION ---
DB_FILE = "mls.db"

STATS_OPTIONS = [
    "Market Grade", 
    "Median Sold Price",
    "Median Price Per SqFt",
    "Months Supply (MSI)",
    "Total Sales Volume", 
    "Active Inventory", 
    "Pending Inventory",
    "Median DOM", 
    "Sales Count",
    "New Listings",
    "Listing Discount",
    "Cash Sales %"
]

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
        @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&family=Playfair+Display:ital,wght@0,400;1,400&display=swap');
        
        /* Page background */
        .stApp {{
            background-image: url("data:image/png;base64,{background_b64}");
            background-size: cover;
            background-position: center top;
            background-attachment: fixed;
        }}
        
        /* Semi-transparent overlay for readability */
        .stApp::before {{
            content: "";
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(255, 255, 255, 0.85);
            z-index: -1;
        }}
        
        /* Main container */
        .block-container {{
            padding-top: 0;
            padding-bottom: 1rem;
        }}
        
        /* Banner header */
        .banner-container {{
            width: 100vw;
            margin-left: calc(-50vw + 50%);
            margin-top: -1rem;
            margin-bottom: 2rem;
            height: 200px;
            background-image: url("data:image/png;base64,{banner_b64}");
            background-size: cover;
            background-position: center;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
        }}
        .banner-container::before {{
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, rgba(30,58,95,0.7) 0%, rgba(45,90,135,0.5) 100%);
        }}
        .banner-content {{
            position: relative;
            text-align: center;
        }}
        .banner-title {{
            display: block;
            color: white;
            font-family: 'Montserrat', sans-serif;
            font-size: 2.8rem;
            font-weight: 700;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.4);
            letter-spacing: 2px;
            margin-bottom: 8px;
        }}
        .banner-subtitle {{
            display: block;
            color: rgba(255,255,255,0.9);
            font-family: 'Playfair Display', serif;
            font-size: 1.1rem;
            font-weight: 400;
            font-style: italic;
            text-shadow: 1px 1px 2px rgba(0,0,0,0.3);
            letter-spacing: 1px;
        }}
        
        /* Header styling - remove gradient text since we have banner */
        h1 {{
            display: none;
        }}
        
        /* KPI Cards */
        div[data-testid="stMetricValue"] {{
            font-size: 32px; 
            font-weight: 700;
            color: #1e3a5f;
        }}
        div[data-testid="stMetricLabel"] {{
            font-weight: 600;
            color: #495057;
        }}
        div[data-testid="stMetric"] {{
            background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%);
            border: none;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }}
        div[data-testid="stMetric"]:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 16px rgba(0,0,0,0.12);
        }}
        
        /* Expander styling */
        div[data-testid="stExpander"] {{
            background-color: rgba(248, 250, 252, 0.95);
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            margin-bottom: 1rem;
        }}
        
        /* Buttons */
        .stButton > button[kind="primary"] {{
            background: linear-gradient(90deg, #1e3a5f 0%, #2d5a87 100%);
            border: none;
            border-radius: 8px;
            font-weight: 600;
            transition: all 0.2s ease;
        }}
        .stButton > button[kind="primary"]:hover {{
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(30, 58, 95, 0.3);
        }}
        .stButton > button:not([kind="primary"]) {{
            border-radius: 8px;
            border: 1px solid #e2e8f0;
            font-weight: 500;
        }}
        
        /* Tabs */
        .stTabs [data-baseweb="tab-list"] {{
            gap: 8px;
            background-color: rgba(241, 245, 249, 0.95);
            padding: 8px;
            border-radius: 12px;
        }}
        .stTabs [data-baseweb="tab"] {{
            border-radius: 8px;
            font-weight: 600;
            padding: 10px 20px;
        }}
        .stTabs [aria-selected="true"] {{
            background-color: white;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        
        /* Chart cards */
        .chart-card {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 1.5rem;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            border: 1px solid #e2e8f0;
        }}
        .chart-card h3 {{
            color: #1e3a5f;
            font-family: 'Montserrat', sans-serif;
            font-weight: 600;
            margin-bottom: 1rem;
            padding-bottom: 0.5rem;
            border-bottom: 2px solid #e2e8f0;
        }}
        .js-plotly-plot {{
            border-radius: 8px;
        }}
        
        /* Selectbox & Multiselect */
        div[data-baseweb="select"] {{
            border-radius: 8px;
        }}
        
        /* Divider */
        hr {{
            border: none;
            height: 2px;
            background: linear-gradient(90deg, #e2e8f0 0%, #f1f5f9 50%, #e2e8f0 100%);
            margin: 1.5rem 0;
        }}
        
        /* Dark mode support */
        @media (prefers-color-scheme: dark) {{
            div[data-testid="stMetric"] {{
                background: linear-gradient(135deg, #1e1e2e 0%, #262730 100%);
                box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            }}
            div[data-testid="stMetricValue"] {{
                color: #60a5fa;
            }}
            div[data-testid="stExpander"] {{
                background-color: #1e1e2e;
                border-color: #36393f;
            }}
            h1 {{
                background: linear-gradient(90deg, #60a5fa 0%, #93c5fd 100%);
                -webkit-background-clip: text;
            }}
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
        
        if 'pcn_validated' in columns:
            query = """
            SELECT 
                listing_number, status, listing_date, sold_date, 
                under_contract_date, effective_active_end_date, fallthrough_date,
                cancel_date, withdrawn_date, status_change_date,
                sold_price, list_price, original_list_price, sqft_living,
                city, zip_code, final_subdivision, property_type, terms_of_sale,
                pcn_validated
            FROM listing_details
            """
        else:
            query = """
            SELECT 
                listing_number, status, listing_date, sold_date, 
                under_contract_date, effective_active_end_date, fallthrough_date,
                cancel_date, withdrawn_date, status_change_date,
                sold_price, list_price, original_list_price, sqft_living,
                city, zip_code, final_subdivision, property_type, terms_of_sale
            FROM listing_details
            """
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
                <span class="banner-subtitle">Comprehensive Market Data for Palm Beach County</span>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    
    # === TOP FILTER BAR ===
    with st.expander("🎯 **Filters & Settings** (click to expand)", expanded=True):
        # Row 1: Property, City, Subdivision
        r1c1, r1c2, r1c3 = st.columns(3)
        
        with r1c1:
            prop_type_selection = st.selectbox("Property Type", ["Single Family", "Condo/TH/Other", "All Types"])
        
        with r1c2:
            cities = sorted(df_master['city'].dropna().unique())
            selected_cities = st.multiselect("Cities", cities)
        
        # Build context for subdivision dropdown
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
        if 'pcn_validated' in df_context.columns:
            df_validated = df_context[df_context['pcn_validated'] == True]
        else:
            df_validated = df_context
        
        with r1c3:
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
    df_filtered = df_master.copy()
    if prop_type_selection == "Single Family":
        mask = df_filtered['property_type'].astype(str).str.contains("Single", case=False, na=False) | \
               (df_filtered['property_type'].astype(str).str.upper() == "SF")
        df_filtered = df_filtered[mask]
    elif prop_type_selection == "Condo/TH/Other":
        mask = df_filtered['property_type'].astype(str).str.contains("Single", case=False, na=False) | \
               (df_filtered['property_type'].astype(str).str.upper() == "SF")
        df_filtered = df_filtered[~mask]
    if selected_cities:
        df_filtered = df_filtered[df_filtered['city'].isin(selected_cities)]
    if selected_subs:
        df_filtered = df_filtered[df_filtered['final_subdivision'].isin(selected_subs)]
    
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
    tab_analytics, tab_calculator, tab_raw = st.tabs(["📈 Market Trends", "🧮 Deal Simulator", "💾 Data Explorer"])

    with tab_analytics:
        render_analytics_tab()

    with tab_calculator:
        render_calculator_tab()

    with tab_raw:
        st.dataframe(df_filtered.head(100), use_container_width=True)

def render_analytics_tab():
    if st.session_state.report_data:
        results = st.session_state.report_data
        
        # Handle error case
        if "error" in results:
            st.error(results["error"])
        else:
            # Special Handling for Market Grade
            if "Market Grade" in results and isinstance(results["Market Grade"], pd.DataFrame):
                grade_df = results["Market Grade"]
                if not grade_df.empty and 'Market Grade' in grade_df.columns:
                    last_row = grade_df.tail(1).iloc[0]
                    current_grade = last_row.get('Market Grade', 'N/A')
                    period = last_row.get('Period', 'Unknown')
                    
                    # Skip if grade is NA or empty
                    if pd.notna(current_grade) and str(current_grade) not in ['<NA>', 'nan', '', 'None']:
                        st.markdown("""<div class="chart-card">""", unsafe_allow_html=True)
                        st.markdown("### 📊 Proprietary Market Grade")
                        color = "green" if "A" in str(current_grade) else "orange" if "C" in str(current_grade) else "red"
                        st.markdown(f"#### Current Grade: :{color}[{current_grade}]")
                        st.caption(f"Based on Velocity (DOM) & Absorption (MSI) as of {period}")
                        st.markdown("""</div>""", unsafe_allow_html=True)

            for stat, df_res in results.items():
                if stat == "Market Grade": continue
                if not isinstance(df_res, pd.DataFrame): continue
                if df_res.empty: continue
                
                # Skip if stat column doesn't exist
                if stat not in df_res.columns:
                    continue
                
                # Convert pd.NA to NaN for Plotly compatibility
                df_chart = df_res.copy()
                for col in df_chart.columns:
                    if df_chart[col].dtype == "object" or str(df_chart[col].dtype).startswith("Int") or str(df_chart[col].dtype).startswith("Float"):
                        df_chart[col] = df_chart[col].astype(object).where(df_chart[col].notna(), None)
                
                # Drop rows where the stat value is None/NA
                df_chart = df_chart.dropna(subset=[stat])
                if df_chart.empty:
                    continue
                
                # Check for missing data - if gaps exist, use bar chart instead of line
                has_gaps = len(df_chart) < len(df_res)
                
                # Get formatting
                tooltip_fmt, axis_fmt = get_format_settings(stat)
                chart_cls = get_chart_type(stat)
                
                # Switch to bar chart if data has gaps (avoids broken trend lines)
                if has_gaps and chart_cls == px.line:
                    chart_cls = px.bar

                # Start chart card
                st.markdown("""<div class="chart-card">""", unsafe_allow_html=True)
                st.markdown(f"### {stat}")
                
                # Custom color scheme
                chart_color = "#1e3a5f"  # Navy blue to match theme
                
                chart_args = {
                    "data_frame": df_chart,
                    "x": "Period",
                    "y": stat,
                    "template": "plotly_white",
                    "color_discrete_sequence": [chart_color]
                }
                
                if chart_cls == px.line:
                    chart_args["markers"] = True

                fig = chart_cls(**chart_args)
                
                if axis_fmt:
                    fig.update_layout(yaxis_tickformat=axis_fmt)
                fig.update_traces(hovertemplate='%{y:' + tooltip_fmt + '}')
                fig.update_layout(
                    hovermode="x unified", 
                    height=350,
                    title=None,
                    margin=dict(t=10, b=40, l=60, r=20),
                    xaxis=dict(showgrid=False, tickfont=dict(size=11), title=None),
                    yaxis=dict(gridcolor='#f0f0f0', tickfont=dict(size=11), title=None),
                    plot_bgcolor='white',
                    paper_bgcolor='white'
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
                # Show data table below chart
                with st.expander("View Data Table"):
                    display_df = df_res.copy()
                    
                    # Build column config for formatting
                    col_config = {"Period": st.column_config.TextColumn("Period")}
                    
                    # Format the stat column based on type
                    if stat in display_df.columns:
                        if "%" in stat or "Discount" in stat or "Cash" in stat:
                            col_config[stat] = st.column_config.NumberColumn(stat, format="%d%%")
                        elif "Supply" in stat or "MSI" in stat:
                            col_config[stat] = st.column_config.NumberColumn(stat, format="%.1f")
                        elif "Price" in stat or "Volume" in stat:
                            col_config[stat] = st.column_config.NumberColumn(stat, format="$%d")
                        elif "DOM" in stat or "Count" in stat or "Inventory" in stat or "Listings" in stat:
                            col_config[stat] = st.column_config.NumberColumn(stat, format="%d")
                    
                    # Format YoY column if present
                    yoy_col = f"{stat} YoY %"
                    if yoy_col in display_df.columns:
                        col_config[yoy_col] = st.column_config.NumberColumn("YoY %", format="%d%%")
                    
                    # Hide PeriodIndex
                    if "PeriodIndex" in display_df.columns:
                        col_config["PeriodIndex"] = None
                    
                    st.dataframe(display_df, hide_index=True, use_container_width=True, column_config=col_config)
                
                # Close chart card
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
        
        fig = px.bar(waterfall_data, x="Category", y="Amount", color="Type", text_auto=True, title="Monthly Cash Flow Waterfall")
        st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    main()
