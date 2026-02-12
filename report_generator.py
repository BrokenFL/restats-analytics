"""
Professional PDF Market Report Generator
Uses FPDF2 to create branded Douglas Elliman market reports
"""

import pandas as pd
import numpy as np
from datetime import datetime
import base64
import os
import io
import tempfile

from fpdf import FPDF

def get_base64_image(image_path):
    """Convert image file to base64 string for embedding in HTML"""
    if not os.path.exists(image_path):
        return None
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def format_value(stat, val):
    """Format values based on metric type"""
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
    """Format YoY percentage with sign"""
    if pd.isna(yoy) or yoy is None:
        return ""
    return f"{yoy:+.0f}%"

def create_chart_image(df, stat, chart_type="line"):
    """Create a chart and return as base64 PNG"""
    if df.empty or stat not in df.columns:
        return None
    
    df_chart = df.dropna(subset=[stat]).copy()
    if df_chart.empty:
        return None
    
    # Douglas Elliman navy blue
    color = "#1e3a5f"
    
    if chart_type == "line":
        fig = px.line(df_chart, x="Period", y=stat, markers=True,
                      color_discrete_sequence=[color])
    else:
        fig = px.bar(df_chart, x="Period", y=stat,
                     color_discrete_sequence=[color])
    
    # Format y-axis based on stat type
    if "Price" in stat or "Volume" in stat:
        fig.update_layout(yaxis_tickformat="$,.0f")
    elif "%" in stat:
        fig.update_layout(yaxis_tickformat=".0%")
    
    fig.update_layout(
        template="plotly_white",
        height=300,
        width=700,
        margin=dict(t=30, b=50, l=70, r=30),
        title=None,
        xaxis_title=None,
        yaxis_title=None,
        font=dict(family="Arial", size=11),
        plot_bgcolor='white',
        paper_bgcolor='white'
    )
    
    # Convert to PNG bytes
    img_bytes = pio.to_image(fig, format="png", scale=2)
    return base64.b64encode(img_bytes).decode()

def generate_market_report_html(results, metadata, icons_path="icons"):
    """
    Generate HTML for a professional market report
    
    Args:
        results: dict of {stat_name: DataFrame} from analysis
        metadata: dict with keys like 'timeframe', 'start_date', 'end_date', 
                  'cities', 'subdivisions', 'property_type', 'geo_zone'
        icons_path: path to icons folder
    
    Returns:
        HTML string ready for PDF conversion
    """
    
    # Load images
    logo_path = os.path.join(icons_path, "Elliman Logo .png")
    headshot_path = os.path.join(icons_path, "Brooke Headhsot dec 2025.png")
    
    logo_b64 = get_base64_image(logo_path)
    headshot_b64 = get_base64_image(headshot_path)
    
    # Build filter summary
    filter_parts = []
    if metadata.get('cities'):
        filter_parts.append(f"Cities: {', '.join(metadata['cities'])}")
    if metadata.get('subdivisions'):
        filter_parts.append(f"Subdivisions: {', '.join(metadata['subdivisions'])}")
    if metadata.get('geo_zone') and metadata['geo_zone'] != 'All':
        filter_parts.append(f"Geo Zone: {metadata['geo_zone']}")
    if metadata.get('property_type') and metadata['property_type'] != 'All':
        filter_parts.append(f"Property Type: {metadata['property_type']}")
    
    filter_summary = " | ".join(filter_parts) if filter_parts else "All Areas"
    
    date_range = f"{metadata.get('start_date', '')} to {metadata.get('end_date', '')}"
    timeframe = metadata.get('timeframe', 'Monthly').title()
    
    # Build spreadsheet data
    spreadsheet_data = {}
    all_periods = set()
    
    for stat, df_res in results.items():
        if stat == "Market Grade":
            continue
        if not isinstance(df_res, pd.DataFrame) or df_res.empty:
            continue
        if stat not in df_res.columns:
            continue
        
        yoy_col = f"{stat} YoY %"
        for _, row in df_res.iterrows():
            period = row.get('Period', str(row.get('PeriodIndex', '')))
            if not period:
                continue
            all_periods.add(period)
            
            val = row.get(stat)
            yoy = row.get(yoy_col) if yoy_col in df_res.columns else None
            
            if stat not in spreadsheet_data:
                spreadsheet_data[stat] = {}
            spreadsheet_data[stat][period] = (val, yoy)
    
    sorted_periods = sorted(all_periods)
    
    # Build data table HTML
    table_rows = ""
    for stat in spreadsheet_data.keys():
        row_cells = f"<td class='metric-name'>{stat}</td>"
        for period in sorted_periods:
            val, yoy = spreadsheet_data[stat].get(period, (None, None))
            val_str = format_value(stat, val)
            yoy_str = format_yoy(yoy)
            yoy_class = "yoy-positive" if pd.notna(yoy) and yoy > 0 else "yoy-negative" if pd.notna(yoy) and yoy < 0 else ""
            cell_content = f"<span class='value'>{val_str}</span>"
            if yoy_str:
                cell_content += f"<br><span class='yoy {yoy_class}'>{yoy_str}</span>"
            row_cells += f"<td>{cell_content}</td>"
        table_rows += f"<tr>{row_cells}</tr>"
    
    # Build header row
    header_cells = "<th>Metric</th>"
    for period in sorted_periods:
        header_cells += f"<th>{period}</th>"
    
    # Get Market Grade if available
    market_grade_html = ""
    if "Market Grade" in results:
        grade_df = results["Market Grade"]
        if isinstance(grade_df, pd.DataFrame) and not grade_df.empty and 'Market Grade' in grade_df.columns:
            valid_grades = grade_df[grade_df['Market Grade'].notna()]
            if not valid_grades.empty:
                last_row = valid_grades.iloc[-1]
                current_grade = str(last_row['Market Grade'])
                period = last_row.get('Period', '')
                
                if "A" in current_grade:
                    grade_color = "#28a745"
                elif "B" in current_grade:
                    grade_color = "#17a2b8"
                elif "C" in current_grade:
                    grade_color = "#ffc107"
                elif "D" in current_grade:
                    grade_color = "#fd7e14"
                else:
                    grade_color = "#dc3545"
                
                market_grade_html = f"""
                <div class="grade-box">
                    <div class="grade-label">Market Grade</div>
                    <div class="grade-value" style="color: {grade_color};">{current_grade}</div>
                    <div class="grade-period">as of {period}</div>
                </div>
                """
    
    # Generate charts for key metrics
    charts_html = ""
    chart_metrics = ["Median Sold Price", "Sales Count", "Months Supply (MSI)", "Median DOM"]
    charts_generated = 0
    
    for metric in chart_metrics:
        if metric in results and charts_generated < 2:
            df = results[metric]
            if isinstance(df, pd.DataFrame) and not df.empty and metric in df.columns:
                chart_type = "line" if "Price" in metric or "DOM" in metric else "bar"
                try:
                    chart_b64 = create_chart_image(df, metric, chart_type)
                    if chart_b64:
                        charts_html += f"""
                        <div class="chart-container">
                            <div class="chart-title">{metric} Trend</div>
                            <img src="data:image/png;base64,{chart_b64}" class="chart-img"/>
                        </div>
                        """
                        charts_generated += 1
                except Exception as e:
                    pass  # Skip chart if generation fails
    
    # Logo and headshot HTML
    logo_html = f'<img src="data:image/png;base64,{logo_b64}" class="logo"/>' if logo_b64 else '<div class="logo-text">Douglas Elliman</div>'
    headshot_html = f'<img src="data:image/png;base64,{headshot_b64}" class="headshot"/>' if headshot_b64 else ''
    
    # Build complete HTML
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Market Analysis Report</title>
        <style>
            @page {{
                size: letter;
                margin: 0.5in;
            }}
            
            * {{
                box-sizing: border-box;
            }}
            
            body {{
                font-family: 'Helvetica Neue', Arial, sans-serif;
                color: #333;
                line-height: 1.4;
                margin: 0;
                padding: 0;
            }}
            
            .header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 3px solid #1e3a5f;
                padding-bottom: 15px;
                margin-bottom: 20px;
            }}
            
            .logo {{
                height: 50px;
                width: auto;
            }}
            
            .logo-text {{
                font-size: 24px;
                font-weight: bold;
                color: #1e3a5f;
            }}
            
            .header-right {{
                text-align: right;
            }}
            
            .report-title {{
                font-size: 22px;
                font-weight: bold;
                color: #1e3a5f;
                margin: 0;
            }}
            
            .report-subtitle {{
                font-size: 12px;
                color: #666;
                margin-top: 5px;
            }}
            
            .filter-summary {{
                background: #f8f9fa;
                padding: 12px 15px;
                border-radius: 6px;
                margin-bottom: 20px;
                font-size: 11px;
            }}
            
            .filter-summary strong {{
                color: #1e3a5f;
            }}
            
            .grade-box {{
                background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
                border: 2px solid #1e3a5f;
                border-radius: 10px;
                padding: 15px 25px;
                text-align: center;
                display: inline-block;
                margin-bottom: 20px;
            }}
            
            .grade-label {{
                font-size: 11px;
                color: #666;
                text-transform: uppercase;
                letter-spacing: 1px;
            }}
            
            .grade-value {{
                font-size: 28px;
                font-weight: bold;
                margin: 5px 0;
            }}
            
            .grade-period {{
                font-size: 10px;
                color: #888;
            }}
            
            .section-title {{
                font-size: 14px;
                font-weight: bold;
                color: #1e3a5f;
                margin: 20px 0 10px 0;
                padding-bottom: 5px;
                border-bottom: 1px solid #ddd;
            }}
            
            table {{
                width: 100%;
                border-collapse: collapse;
                font-size: 10px;
                margin-bottom: 20px;
            }}
            
            th {{
                background: #1e3a5f;
                color: white;
                padding: 10px 8px;
                text-align: center;
                font-weight: 600;
                font-size: 9px;
            }}
            
            td {{
                border: 1px solid #ddd;
                padding: 8px 6px;
                text-align: center;
                vertical-align: top;
            }}
            
            td.metric-name {{
                text-align: left;
                font-weight: 600;
                background: #f5f5f5;
                white-space: nowrap;
                width: 140px;
            }}
            
            tr:nth-child(even) {{
                background: #fafafa;
            }}
            
            .value {{
                font-weight: 500;
            }}
            
            .yoy {{
                font-size: 8px;
                display: block;
                margin-top: 2px;
            }}
            
            .yoy-positive {{
                color: #28a745;
            }}
            
            .yoy-negative {{
                color: #dc3545;
            }}
            
            .charts-section {{
                display: flex;
                flex-wrap: wrap;
                gap: 20px;
                margin-top: 20px;
            }}
            
            .chart-container {{
                flex: 1;
                min-width: 300px;
                max-width: 48%;
            }}
            
            .chart-title {{
                font-size: 12px;
                font-weight: bold;
                color: #1e3a5f;
                margin-bottom: 8px;
            }}
            
            .chart-img {{
                width: 100%;
                height: auto;
            }}
            
            .footer {{
                margin-top: 30px;
                padding-top: 15px;
                border-top: 2px solid #1e3a5f;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }}
            
            .agent-info {{
                display: flex;
                align-items: center;
                gap: 15px;
            }}
            
            .headshot {{
                width: 60px;
                height: 60px;
                border-radius: 50%;
                object-fit: cover;
                border: 2px solid #1e3a5f;
            }}
            
            .agent-details {{
                font-size: 11px;
            }}
            
            .agent-name {{
                font-weight: bold;
                color: #1e3a5f;
                font-size: 13px;
            }}
            
            .disclaimer {{
                font-size: 8px;
                color: #888;
                max-width: 300px;
                text-align: right;
            }}
            
            .generated-date {{
                font-size: 9px;
                color: #888;
                text-align: right;
                margin-top: 10px;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            {logo_html}
            <div class="header-right">
                <div class="report-title">Market Analysis Report</div>
                <div class="report-subtitle">{timeframe} Analysis | {date_range}</div>
            </div>
        </div>
        
        <div class="filter-summary">
            <strong>Analysis Parameters:</strong> {filter_summary}
        </div>
        
        {market_grade_html}
        
        <div class="section-title">Market Statistics</div>
        <table>
            <thead><tr>{header_cells}</tr></thead>
            <tbody>{table_rows}</tbody>
        </table>
        
        {f'<div class="section-title">Market Trends</div><div class="charts-section">{charts_html}</div>' if charts_html else ''}
        
        <div class="footer">
            <div class="agent-info">
                {headshot_html}
                <div class="agent-details">
                    <div class="agent-name">Brooke Snader</div>
                    <div>Licensed Real Estate Salesperson</div>
                    <div>Douglas Elliman Real Estate</div>
                    <div>Palm Beach, Florida</div>
                </div>
            </div>
            <div class="disclaimer">
                Data sourced from MLS. Information deemed reliable but not guaranteed. 
                This report is for informational purposes only.
            </div>
        </div>
        
        <div class="generated-date">
            Report generated: {datetime.now().strftime("%B %d, %Y at %I:%M %p")}
        </div>
    </body>
    </html>
    """
    
    return html


class MarketReportPDF(FPDF):
    """Custom PDF class with Deep Ocean / magazine-style layout"""
    
    # Deep Ocean colors (RGB tuples)
    MIDNIGHT = (11, 16, 33)
    SLATE = (28, 35, 51)
    GOLD = (207, 181, 59)
    TRUST_BLUE = (46, 92, 255)
    GROWTH_GREEN = (0, 208, 156)
    ALERT_CORAL = (255, 107, 107)
    WHITE = (255, 255, 255)
    SILVER = (160, 174, 192)
    LIGHT_TEXT = (226, 232, 240)
    
    def __init__(self, logo_path=None, headshot_path=None):
        super().__init__()
        self.logo_path = logo_path
        self.headshot_path = headshot_path
        self.set_auto_page_break(auto=False, margin=15)
        
    def header(self):
        # Dark header bar
        self.set_fill_color(*self.SLATE)
        self.rect(0, 0, 210, 30, 'F')
        
        # Gold accent line
        self.set_fill_color(*self.GOLD)
        self.rect(0, 30, 210, 0.8, 'F')
        
        # Logo
        if self.logo_path and os.path.exists(self.logo_path):
            try:
                self.image(self.logo_path, 10, 5, 35)
            except:
                self.set_font('Helvetica', 'B', 14)
                self.set_text_color(*self.GOLD)
                self.set_xy(10, 10)
                self.cell(40, 10, 'Douglas Elliman', 0, 0)
        
        # Title
        self.set_font('Helvetica', 'B', 16)
        self.set_text_color(*self.WHITE)
        self.set_xy(0, 8)
        self.cell(200, 6, 'MARKET ANALYSIS REPORT', 0, 1, 'R')
        self.set_font('Helvetica', '', 8)
        self.set_text_color(*self.SILVER)
        self.cell(200, 5, 'ReStats Analytics  |  Palm Beach County', 0, 1, 'R')
        
        self.set_y(35)
    
    def footer(self):
        self.set_y(-12)
        
        # Compact footer - single line
        self.set_font('Helvetica', '', 6)
        self.set_text_color(*self.SILVER)
        self.cell(0, 4, f'Brooke Snader | Douglas Elliman | Generated: {datetime.now().strftime("%B %d, %Y")}', 0, 0, 'C')
    
    def section_title(self, title):
        """Draw a styled section title with gold underline (compact)"""
        self.set_font('Helvetica', 'B', 9)
        self.set_text_color(*self.SLATE)
        self.cell(0, 5, title.upper(), 0, 1)
        # Gold underline
        self.set_fill_color(*self.GOLD)
        self.rect(self.get_x(), self.get_y(), 30, 0.4, 'F')
        self.ln(2)


def generate_pdf_report(results, metadata, output_path=None, icons_path="icons"):
    """
    Generate a magazine-style PDF market report with icon cards, 
    Market Grade badge, and professional layout using FPDF2.
    """
    
    # Icon mapping: stat name -> icon filename
    ICON_MAP = {
        "Median Sold Price": "Median Sold Price.png",
        "Median Price Per SqFt": "Median Price Per Foot.png",
        "Months Supply (MSI)": "MSI.png",
        "Total Sales Volume": "Total Volume.png",
        "Active Inventory": "Active Listings.png",
        "Pending Inventory": "Pending Listings.png",
        "New Listings": "New Listings.png",
        "Sales Count": "Closed Listings .png",
        "Median DOM": "Avg Days on Market.png",
    }
    
    logo_path = os.path.join(icons_path, "Elliman Logo .png")
    headshot_path = os.path.join(icons_path, "Brooke Headhsot dec 2025.png")
    
    pdf = MarketReportPDF(logo_path=logo_path, headshot_path=headshot_path)
    pdf.add_page()
    
    # --- LOCATION & PERIOD HERO SECTION ---
    # Build location string (City/Subdivision or GeoZone)
    location_parts = []
    
    # Add geo zone first if present
    if metadata.get('geo_zone'):
        location_parts.append(metadata['geo_zone'])
    
    # Add subdivisions or cities
    if metadata.get('subdivisions'):
        subs = metadata['subdivisions']
        if len(subs) <= 2:
            location_parts.append(', '.join(subs))
        else:
            location_parts.append(f"{', '.join(subs[:2])} +{len(subs)-2} more")
    elif metadata.get('cities'):
        cities = metadata['cities']
        if len(cities) <= 2:
            location_parts.append(', '.join(cities))
        else:
            location_parts.append(f"{', '.join(cities[:2])} +{len(cities)-2} more")
    
    location = ', '.join(location_parts) if location_parts else 'Palm Beach County'
    
    # Property type (already formatted: "Single Family Home", "Condo/Townhouse", or "All")
    prop_type = metadata.get('property_type', 'All')
    
    # Period label (already formatted: "January 2025", "Q1 2025", or "2025")
    period_label = metadata.get('period_label', '')
    if not period_label:
        # Fallback to date range if period_label not provided
        period_label = f"{metadata.get('start_date', '')} to {metadata.get('end_date', '')}"
    
    # Hero box with dark background (taller for multi-line layout)
    hero_y = pdf.get_y()
    pdf.set_fill_color(*MarketReportPDF.SLATE)
    pdf.rect(10, hero_y, 190, 22, 'F')
    # Gold left accent
    pdf.set_fill_color(*MarketReportPDF.GOLD)
    pdf.rect(10, hero_y, 3, 22, 'F')
    
    # Line 1: PALM BEACH (centered, bigger, gold)
    pdf.set_font('Helvetica', 'B', 14)
    pdf.set_text_color(*MarketReportPDF.GOLD)
    pdf.set_xy(10, hero_y + 2)
    pdf.cell(190, 5, 'PALM BEACH', 0, 1, 'C')
    
    # Line 2: Location/Subdivision/GeoZone (centered, white)
    pdf.set_font('Helvetica', '', 9)
    pdf.set_text_color(*MarketReportPDF.WHITE)
    pdf.set_xy(10, hero_y + 8)
    pdf.cell(190, 4, location, 0, 1, 'C')
    
    # Line 3: Property Type (centered, silver)
    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(*MarketReportPDF.SILVER)
    pdf.set_xy(10, hero_y + 13)
    pdf.cell(190, 3, prop_type, 0, 1, 'C')
    
    # Line 4: Period (centered, silver)
    pdf.set_xy(10, hero_y + 17)
    pdf.cell(190, 3, period_label, 0, 0, 'C')
    
    # Market Grade badge on the right side of hero
    grade_str = None
    if "Market Grade" in results:
        grade_df = results["Market Grade"]
        if isinstance(grade_df, pd.DataFrame) and not grade_df.empty and 'Market Grade' in grade_df.columns:
            valid_grades = grade_df[grade_df['Market Grade'].notna()]
            if not valid_grades.empty:
                grade_str = str(valid_grades.iloc[-1]['Market Grade'])
    
    if grade_str:
        # Grade circle on right side (centered vertically in hero box)
        badge_x = 175
        badge_y = hero_y + 6
        pdf.set_fill_color(*MarketReportPDF.GOLD)
        pdf.ellipse(badge_x, badge_y, 10, 10, 'F')
        pdf.set_font('Helvetica', 'B', 10)
        pdf.set_text_color(*MarketReportPDF.MIDNIGHT)
        pdf.set_xy(badge_x, badge_y + 1.5)
        pdf.cell(10, 6, grade_str, 0, 0, 'C')
    
    pdf.set_y(hero_y + 26)
    
    # --- STAT CARDS GRID (3 columns, compact to fit one page) ---
    card_data = []
    for stat, df_res in results.items():
        if stat == "Market Grade":
            continue
        if not isinstance(df_res, pd.DataFrame) or df_res.empty:
            continue
        if stat not in df_res.columns:
            continue
        
        last_row = df_res.iloc[-1]
        val = last_row.get(stat)
        yoy_col = f"{stat} YoY %"
        yoy = last_row.get(yoy_col) if yoy_col in df_res.columns else None
        values = df_res[stat].dropna().tolist()
        
        card_data.append({
            'stat': stat, 'value': val, 'yoy': yoy,
            'values': values, 'icon': ICON_MAP.get(stat, None)
        })
    
    if card_data:
        pdf.section_title('Key Market Indicators')
        
        # Compact sizing: fit all cards + chart on one page
        num_cards = len(card_data)
        cards_per_row = 3
        total_rows = (num_cards + cards_per_row - 1) // cards_per_row
        
        card_w = 60
        card_gap = 3
        # Fixed compact card height
        card_h = 22
        
        start_x = 10
        grid_start_y = pdf.get_y()
        
        for i, card in enumerate(card_data):
            col = i % cards_per_row
            row = i // cards_per_row
            
            x = start_x + col * (card_w + card_gap)
            y = grid_start_y + row * (card_h + card_gap)
            
            # Card background
            pdf.set_fill_color(248, 249, 252)
            pdf.set_draw_color(230, 232, 238)
            pdf.set_line_width(0.3)
            pdf.rect(x, y, card_w, card_h, 'FD')
            
            # Gold top accent
            pdf.set_fill_color(*MarketReportPDF.GOLD)
            pdf.rect(x, y, card_w, 1, 'F')
            
            # Icon
            icon_file = card.get('icon')
            has_icon = False
            if icon_file:
                icon_path = os.path.join(icons_path, icon_file)
                if os.path.exists(icon_path):
                    try:
                        pdf.image(icon_path, x + 2, y + 4, 9, 9)
                        has_icon = True
                    except:
                        pass
            
            text_x = (x + 13) if has_icon else (x + 3)
            
            # Label
            label = card['stat']
            if len(label) > 22:
                label = label[:20] + '..'
            pdf.set_font('Helvetica', '', 6)
            pdf.set_text_color(*MarketReportPDF.SILVER)
            pdf.set_xy(text_x, y + 3)
            pdf.cell(card_w - 15, 3, label.upper(), 0, 0)
            
            # Value
            val_str = format_value(card['stat'], card['value'])
            pdf.set_font('Helvetica', 'B', 12)
            pdf.set_text_color(*MarketReportPDF.SLATE)
            pdf.set_xy(text_x, y + 8)
            pdf.cell(card_w - 15, 6, val_str, 0, 0)
            
            # YoY badge
            yoy = card['yoy']
            if pd.notna(yoy):
                if yoy >= 0:
                    pdf.set_fill_color(230, 252, 245)
                    pdf.set_text_color(*MarketReportPDF.GROWTH_GREEN)
                    arrow = '+'
                else:
                    pdf.set_fill_color(255, 235, 235)
                    pdf.set_text_color(*MarketReportPDF.ALERT_CORAL)
                    arrow = '-'
                yoy_text = f'{arrow}{abs(yoy):.1f}% YoY'
                pdf.set_font('Helvetica', 'B', 6)
                badge_w = pdf.get_string_width(yoy_text) + 3
                pdf.set_xy(text_x, y + 16)
                pdf.cell(badge_w, 4, yoy_text, 0, 0, 'L', fill=True)
            
            # Mini sparkline (if card is tall enough and has data)
            values = card.get('values', [])
            if len(values) >= 3 and card_h >= 25:
                spark_x = x + 2
                spark_y = y + card_h - 5
                spark_w = card_w - 4
                spark_h = 4
                
                v_min, v_max = min(values), max(values)
                v_range = v_max - v_min if v_max != v_min else 1
                
                pdf.set_draw_color(*MarketReportPDF.TRUST_BLUE)
                pdf.set_line_width(0.3)
                
                points = []
                for j, v in enumerate(values):
                    px = spark_x + (j / max(len(values) - 1, 1)) * spark_w
                    py = spark_y + spark_h - ((v - v_min) / v_range) * spark_h
                    points.append((px, py))
                
                for j in range(len(points) - 1):
                    pdf.line(points[j][0], points[j][1], points[j+1][0], points[j+1][1])
                
                if points:
                    last_pt = points[-1]
                    pdf.set_fill_color(*MarketReportPDF.GOLD)
                    pdf.ellipse(last_pt[0] - 0.8, last_pt[1] - 0.8, 1.6, 1.6, 'F')
        
        # Move Y past all card rows
        pdf.set_y(grid_start_y + total_rows * (card_h + card_gap) + 4)
    
    # --- YoY COMPARISON BAR CHART ---
    # Shows YoY % change for each stat as horizontal bars
    # Works for single-period reports (most common use case for Market Report)
    
    yoy_chart_data = []
    for stat, df_res in results.items():
        if stat == "Market Grade":
            continue
        if not isinstance(df_res, pd.DataFrame) or df_res.empty:
            continue
        if stat not in df_res.columns:
            continue
        
        yoy_col = f"{stat} YoY %"
        if yoy_col in df_res.columns:
            last_row = df_res.iloc[-1]
            yoy_val = last_row.get(yoy_col)
            if pd.notna(yoy_val):
                # Shorten stat names for chart
                short_name = stat.replace("Median ", "").replace("Total ", "").replace(" (MSI)", "")
                if len(short_name) > 18:
                    short_name = short_name[:16] + ".."
                yoy_chart_data.append({'stat': short_name, 'yoy': float(yoy_val)})
    
    # Draw YoY comparison chart if we have at least 2 stats with YoY
    if yoy_chart_data and len(yoy_chart_data) >= 2:
        if pdf.get_y() > 210:
            pdf.add_page()
        
        pdf.section_title('Year-over-Year Change')
        
        chart_x = 10
        chart_y = pdf.get_y()
        num_bars = len(yoy_chart_data)
        bar_h = 6
        bar_gap = 2
        chart_h = num_bars * (bar_h + bar_gap) + 6
        chart_w = 190
        
        # Chart background
        pdf.set_fill_color(248, 249, 252)
        pdf.set_draw_color(230, 232, 238)
        pdf.set_line_width(0.2)
        pdf.rect(chart_x, chart_y, chart_w, chart_h, 'FD')
        
        # Find max absolute YoY for scaling
        max_abs_yoy = max(abs(d['yoy']) for d in yoy_chart_data)
        if max_abs_yoy == 0:
            max_abs_yoy = 1
        
        # Bar area
        label_w = 45  # space for stat labels
        bar_area_x = chart_x + label_w
        bar_area_w = chart_w - label_w - 10
        center_x = bar_area_x + bar_area_w / 2  # 0% line
        
        # Draw center line (0%)
        pdf.set_draw_color(180, 180, 185)
        pdf.set_line_width(0.3)
        pdf.line(center_x, chart_y + 4, center_x, chart_y + chart_h - 4)
        
        # Draw bars
        for i, item in enumerate(yoy_chart_data):
            bar_y = chart_y + 4 + i * (bar_h + bar_gap)
            yoy = item['yoy']
            
            # Stat label
            pdf.set_font('Helvetica', '', 5)
            pdf.set_text_color(*MarketReportPDF.SLATE)
            pdf.set_xy(chart_x + 2, bar_y)
            pdf.cell(label_w - 4, bar_h, item['stat'], 0, 0, 'R')
            
            # Bar width proportional to YoY (max bar = half of bar_area_w)
            bar_w = (abs(yoy) / max_abs_yoy) * (bar_area_w / 2 - 5)
            bar_w = max(bar_w, 2)  # minimum visible bar
            
            # Bar position and color
            if yoy >= 0:
                bar_start_x = center_x
                pdf.set_fill_color(*MarketReportPDF.GROWTH_GREEN)
            else:
                bar_start_x = center_x - bar_w
                pdf.set_fill_color(*MarketReportPDF.ALERT_CORAL)
            
            # Draw bar
            pdf.rect(bar_start_x, bar_y, bar_w, bar_h - 1, 'F')
            
            # YoY value label
            pdf.set_font('Helvetica', 'B', 5)
            if yoy >= 0:
                pdf.set_text_color(*MarketReportPDF.GROWTH_GREEN)
                pdf.set_xy(bar_start_x + bar_w + 1, bar_y)
                pdf.cell(12, bar_h, f'+{yoy:.0f}%', 0, 0, 'L')
            else:
                pdf.set_text_color(*MarketReportPDF.ALERT_CORAL)
                pdf.set_xy(bar_start_x - 13, bar_y)
                pdf.cell(12, bar_h, f'{yoy:.0f}%', 0, 0, 'R')
        
        pdf.set_y(chart_y + chart_h + 4)
    
    # --- DISCLAIMER (compact) ---
    pdf.ln(2)
    pdf.set_font('Helvetica', 'I', 5)
    pdf.set_text_color(160, 160, 160)
    pdf.multi_cell(0, 2.5, 'This report is generated from MLS data for informational purposes only. Past performance does not guarantee future results. Contact Brooke Snader for a personalized market analysis.')
    
    # Output
    if output_path:
        pdf.output(output_path)
        return output_path
    else:
        return bytes(pdf.output())


def get_pdf_download_link(pdf_bytes, filename="market_report.pdf"):
    """Generate a download link for Streamlit"""
    b64 = base64.b64encode(pdf_bytes).decode()
    return f'<a href="data:application/pdf;base64,{b64}" download="{filename}">📥 Download PDF Report</a>'
