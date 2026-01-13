# 🏠 Real Estate Market Intelligence Engine

**Automated ETL Pipeline & Analytics Dashboard for Palm Beach Luxury Real Estate**

> *"I built this tool to automate the manual analysis of 50,000+ MLS records, reducing weekly market research time by 90% while uncovering hidden inventory trends."* — Brooke Snader

---

## 🎯 Business Value

In high-stakes real estate, data is often messy, delayed, and fragmented. This application solves three critical business problems:

- **Data Normalization:** Converts raw, inconsistent MLS data into a clean "Golden Record" (e.g., mapping "PB Hampton" and "Palm Beach Hampton" to a single entity).
- **"Zombie" Listing Detection:** Identifies listings that appear active but have actually expired, preventing wasted sales outreach.
- **True Supply Calculation:** Calculates Months Supply of Inventory (MSI) dynamically, identifying which micro-markets are shifting from Seller's to Buyer's markets before the public reports do.

---

## 🛠️ Tech Stack

| Category | Technology |
|----------|------------|
| **Core Logic** | Python 3.10+ |
| **Data Manipulation** | Pandas & NumPy |
| **Database** | SQLite (with WAL journaling for concurrency) |
| **Visualization** | Streamlit & Plotly Express |
| **Automation** | Custom ETL (Extract, Transform, Load) scripts with Upsert logic |

---

## 📂 Key Modules

- **`data_cleaning.py`** — The "RevOps" engine. Handles type casting, timeline logic (calculating effective active dates), and fuzzy matching for subdivision names.
- **`data_analysis.py`** — Statistical engine that computes Median Price, Price Per SqFt, and Absorption Rates across dynamic timeframes.
- **`app.py`** — The interactive front-end dashboard used by agents to visualize trends in real-time.

---

## 🚀 How It Works

1. **Ingestion:** Raw CSV exports from the MLS are dropped into the `input_csvs` folder.
2. **Processing:** `generate_db.py` triggers the cleaning pipeline, standardizing columns and applying business logic.
3. **Storage:** Clean data is upserted into `mls.db` (SQLite), ensuring no duplicates.
4. **Analysis:** The Streamlit dashboard queries the DB to generate live charts for Sold Price, Volume, and Inventory.

---

## 📸 Usage

- **Dashboard:** Select a specific subdivision (e.g., "Olympia") and timeframe (Quarterly).
- **Report Generation:** One-click generation of PDF-ready market reports for client presentations.

---

## 👤 Author

**Brooke Snader**  
Technical Sales Executive & Workflow Automation Specialist

[LinkedIn Profile](https://linkedin.com) | [Portfolio](https://portfolio.com)
