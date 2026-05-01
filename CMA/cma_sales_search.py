import argparse
import csv
import os
import re
import time
from datetime import datetime

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


SEARCH_URL = "https://pbcpao.gov/AdvSearch/SalesSearch"


def to_mmddyyyy(value: str) -> str:
    s = str(value).strip()
    if not s:
        return ""
    # Supports YYYY-MM-DD (from cma.py output) and MM/DD/YYYY.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return datetime.strptime(s, "%Y-%m-%d").strftime("%m/%d/%Y")
    return s


def pick_autocomplete_subdivision(driver, wait: WebDriverWait, subdivision_name: str) -> bool:
    box = wait.until(EC.presence_of_element_located((By.ID, "autocomplete-subdivision")))
    box.clear()
    box.send_keys(subdivision_name)
    time.sleep(0.8)

    # Try exact match in autocomplete list first.
    try:
        items = wait.until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "ul.ui-autocomplete li"))
        )
        target = subdivision_name.strip().upper()
        exact = None
        fallback = None
        for li in items:
            txt = li.text.strip()
            if not txt:
                continue
            if txt.upper() == target:
                exact = li
                break
            if target in txt.upper() and fallback is None:
                fallback = li
        choice = exact or fallback
        if choice:
            driver.execute_script("arguments[0].click();", choice)
            return True
    except TimeoutException:
        pass

    # Fallback: keep typed value.
    box.send_keys(Keys.TAB)
    return True


def run_search(driver, wait: WebDriverWait, subdivision_name: str, date_from: str, date_to: str, min_sale_price: int) -> dict:
    driver.get(SEARCH_URL)
    time.sleep(1.2)

    selected = pick_autocomplete_subdivision(driver, wait, subdivision_name)

    # QS radio from recorder; fallback to value selector.
    try:
        qs = driver.find_element(By.XPATH, "/html/body/main/div/div/div/form/div/div[3]/div[2]/div[2]/input[2]")
    except Exception:
        qs = driver.find_element(By.CSS_SELECTOR, "input[value='QS']")
    driver.execute_script("arguments[0].click();", qs)

    sale_price = wait.until(EC.presence_of_element_located((By.ID, "SalePriceFrom")))
    sale_price.clear()
    sale_price.send_keys(str(int(min_sale_price)))

    date_from_input = wait.until(EC.presence_of_element_located((By.ID, "SaleDateFrom")))
    date_from_input.clear()
    date_from_input.send_keys(to_mmddyyyy(date_from))

    if str(date_to).strip():
        date_to_input = wait.until(EC.presence_of_element_located((By.ID, "SaleDateTo")))
        date_to_input.clear()
        date_to_input.send_keys(to_mmddyyyy(date_to))

    search_btn = wait.until(EC.element_to_be_clickable((By.ID, "btnFormSearch")))
    driver.execute_script("arguments[0].click();", search_btn)

    time.sleep(2.5)
    page_text = driver.page_source

    # Best-effort result parsing.
    count = ""
    m = re.search(r"of\s+([0-9,]+)\s+entries", page_text, flags=re.IGNORECASE)
    if m:
        count = m.group(1).replace(",", "")

    no_records = bool(
        re.search(r"No\s+records|No\s+matching\s+records", page_text, flags=re.IGNORECASE)
    )
    return {
        "selected_subdivision": selected,
        "result_count": count,
        "no_records": no_records,
        "status": "ok",
    }


def parse_args():
    p = argparse.ArgumentParser(description="Run PBC subdivision sales searches from cma_sales_queries.csv")
    p.add_argument("--query-csv", required=True, help="CSV from cma.py --output-sales-queries")
    p.add_argument("--output-csv", default="cma_sales_search_results.csv", help="Result log CSV")
    p.add_argument("--max-searches", type=int, default=0, help="Limit number of rows (0 = all)")
    p.add_argument("--headless", action="store_true", help="Run Chrome headless")
    return p.parse_args()


def main():
    args = parse_args()
    df = pd.read_csv(args.query_csv, dtype=str).fillna("")
    if df.empty:
        raise ValueError(f"No rows in query CSV: {args.query_csv}")

    if args.max_searches and args.max_searches > 0:
        df = df.head(args.max_searches)

    options = webdriver.ChromeOptions()
    if args.headless:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1400,900")

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 15)

    rows = []
    try:
        for i, r in df.iterrows():
            subdivision = r.get("official_subdivision_name", "").strip()
            if not subdivision:
                continue
            date_from = r.get("date_from", "")
            date_to = r.get("date_to", "")
            min_sale = int(float(r.get("min_sale_price", "100000") or 100000))

            print(f"[{i+1}/{len(df)}] Searching: {subdivision}")
            result = run_search(
                driver=driver,
                wait=wait,
                subdivision_name=subdivision,
                date_from=date_from,
                date_to=date_to,
                min_sale_price=min_sale,
            )
            rows.append(
                {
                    "official_subdivision_name": subdivision,
                    "normalized_subdivision_name": r.get("normalized_subdivision_name", ""),
                    "unified_subdivision": r.get("unified_subdivision", ""),
                    "subid": r.get("subid", ""),
                    "sale_type": r.get("sale_type", "QS"),
                    "date_from": date_from,
                    "date_to": date_to,
                    "min_sale_price": min_sale,
                    "selected_subdivision": result["selected_subdivision"],
                    "result_count": result["result_count"],
                    "no_records": result["no_records"],
                    "status": result["status"],
                    "searched_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
    finally:
        driver.quit()

    os.makedirs(os.path.dirname(args.output_csv) or ".", exist_ok=True)
    fieldnames = [
        "official_subdivision_name",
        "normalized_subdivision_name",
        "unified_subdivision",
        "subid",
        "sale_type",
        "date_from",
        "date_to",
        "min_sale_price",
        "selected_subdivision",
        "result_count",
        "no_records",
        "status",
        "searched_at",
    ]
    with open(args.output_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"\nWrote results: {os.path.abspath(args.output_csv)}")
    print(f"Rows searched: {len(rows)}")


if __name__ == "__main__":
    main()
