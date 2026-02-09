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
    """Custom PDF class for market reports"""
    
    def __init__(self, logo_path=None, headshot_path=None):
        super().__init__()
        self.logo_path = logo_path
        self.headshot_path = headshot_path
        self.set_auto_page_break(auto=True, margin=15)
        
    def header(self):
        # Logo
        if self.logo_path and os.path.exists(self.logo_path):
            self.image(self.logo_path, 10, 8, 40)
        else:
            self.set_font('Helvetica', 'B', 16)
            self.set_text_color(30, 58, 95)
            self.cell(40, 10, 'Douglas Elliman', 0, 0)
        
        # Title
        self.set_font('Helvetica', 'B', 18)
        self.set_text_color(30, 58, 95)
        self.cell(0, 10, 'Market Analysis Report', 0, 1, 'R')
        self.ln(5)
        
        # Line
        self.set_draw_color(30, 58, 95)
        self.set_line_width(0.5)
        self.line(10, 25, 200, 25)
        self.ln(10)
    
    def footer(self):
        self.set_y(-30)
        
        # Line
        self.set_draw_color(30, 58, 95)
        self.set_line_width(0.3)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(3)
        
        # Agent info
        start_x = 10
        if self.headshot_path and os.path.exists(self.headshot_path):
            try:
                self.image(self.headshot_path, start_x, self.get_y(), 15)
                start_x = 28
            except:
                pass
        
        self.set_font('Helvetica', 'B', 9)
        self.set_text_color(30, 58, 95)
        self.set_xy(start_x, self.get_y())
        self.cell(0, 4, 'Brooke Snader', 0, 1)
        self.set_x(start_x)
        self.set_font('Helvetica', '', 8)
        self.set_text_color(100, 100, 100)
        self.cell(0, 3, 'Licensed Real Estate Salesperson | Douglas Elliman', 0, 1)
        
        # Generated date
        self.set_y(-10)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f'Generated: {datetime.now().strftime("%B %d, %Y")}', 0, 0, 'R')


def generate_pdf_report(results, metadata, output_path=None, icons_path="icons"):
    """
    Generate a PDF market report using FPDF2
    
    Args:
        results: dict of {stat_name: DataFrame} from analysis
        metadata: dict with filter/date info
        output_path: where to save PDF (if None, returns bytes)
        icons_path: path to icons folder
    
    Returns:
        PDF bytes if output_path is None, else saves to file
    """
    
    # Load image paths
    logo_path = os.path.join(icons_path, "Elliman Logo .png")
    headshot_path = os.path.join(icons_path, "Brooke Headhsot dec 2025.png")
    
    # Create PDF
    pdf = MarketReportPDF(logo_path=logo_path, headshot_path=headshot_path)
    pdf.add_page()
    
    # Filter summary
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
    
    # Analysis Parameters box
    pdf.set_fill_color(248, 249, 250)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(30, 58, 95)
    pdf.cell(0, 8, f'Analysis: {timeframe} | {date_range}', 0, 1, 'L', fill=True)
    pdf.set_font('Helvetica', '', 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, filter_summary, 0, 1, 'L', fill=True)
    pdf.ln(5)
    
    # Market Grade if available
    if "Market Grade" in results:
        grade_df = results["Market Grade"]
        if isinstance(grade_df, pd.DataFrame) and not grade_df.empty and 'Market Grade' in grade_df.columns:
            valid_grades = grade_df[grade_df['Market Grade'].notna()]
            if not valid_grades.empty:
                last_row = valid_grades.iloc[-1]
                current_grade = str(last_row['Market Grade'])
                period = last_row.get('Period', '')
                
                # Grade box
                pdf.set_fill_color(30, 58, 95)
                pdf.set_text_color(255, 255, 255)
                pdf.set_font('Helvetica', 'B', 12)
                pdf.cell(60, 10, f'Market Grade: {current_grade}', 0, 1, 'L', fill=True)
                pdf.set_text_color(100, 100, 100)
                pdf.set_font('Helvetica', 'I', 8)
                pdf.cell(0, 5, f'Based on DOM & MSI as of {period}', 0, 1)
                pdf.ln(5)
    
    # Build data table
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
    
    if spreadsheet_data and sorted_periods:
        # Section title
        pdf.set_font('Helvetica', 'B', 12)
        pdf.set_text_color(30, 58, 95)
        pdf.cell(0, 10, 'Market Statistics', 0, 1)
        
        # Calculate column widths
        num_periods = len(sorted_periods)
        metric_col_width = 50
        period_col_width = (190 - metric_col_width) / max(num_periods, 1)
        
        # Table header
        pdf.set_fill_color(30, 58, 95)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Helvetica', 'B', 8)
        
        pdf.cell(metric_col_width, 8, 'Metric', 1, 0, 'L', fill=True)
        for period in sorted_periods:
            pdf.cell(period_col_width, 8, period[:10], 1, 0, 'C', fill=True)
        pdf.ln()
        
        # Table rows
        pdf.set_text_color(50, 50, 50)
        row_num = 0
        for stat in spreadsheet_data.keys():
            # Alternate row colors
            if row_num % 2 == 0:
                pdf.set_fill_color(255, 255, 255)
            else:
                pdf.set_fill_color(250, 250, 250)
            
            # Metric name
            pdf.set_font('Helvetica', 'B', 7)
            pdf.cell(metric_col_width, 12, stat[:25], 1, 0, 'L', fill=True)
            
            # Values
            pdf.set_font('Helvetica', '', 7)
            for period in sorted_periods:
                val, yoy = spreadsheet_data[stat].get(period, (None, None))
                val_str = format_value(stat, val)
                
                # Add YoY if available
                if pd.notna(yoy):
                    yoy_str = f" ({yoy:+.0f}%)"
                    cell_text = val_str + yoy_str
                else:
                    cell_text = val_str
                
                pdf.cell(period_col_width, 12, cell_text[:15], 1, 0, 'C', fill=True)
            
            pdf.ln()
            row_num += 1
    
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
