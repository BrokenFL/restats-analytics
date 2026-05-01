import argparse
import csv
import json
import os
import re
import time
from datetime import datetime
from typing import Dict, List

import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


SEARCH_URL = "https://pbcpao.gov/AdvSearch/SalesSearch"
DETAIL_URL_TMPL = "https://pbcpao.gov/Property/Details?parcelId={parcel_id}"


def to_mmddyyyy(value: str) -> str:
    s = str(value).strip()
    if not s:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return datetime.strptime(s, "%Y-%m-%d").strftime("%m/%d/%Y")
    return s


def pick_subdivision(driver, wait: WebDriverWait, subdivision_name: str) -> None:
    box = wait.until(EC.presence_of_element_located((By.ID, "autocomplete-subdivision")))
    box.clear()
    box.send_keys(subdivision_name)
    time.sleep(0.8)
    items = driver.find_elements(By.CSS_SELECTOR, "ul.ui-autocomplete li")
    target = subdivision_name.strip().upper()
    for li in items:
        txt = li.text.strip().upper()
        if txt == target:
            driver.execute_script("arguments[0].click();", li)
            return
    for li in items:
        txt = li.text.strip().upper()
        if target in txt:
            driver.execute_script("arguments[0].click();", li)
            return


def run_sales_search(
    driver,
    wait: WebDriverWait,
    subdivision_name: str,
    date_from: str,
    date_to: str,
    min_sale_price: int,
) -> List[Dict]:
    driver.get(SEARCH_URL)
    time.sleep(1.2)
    pick_subdivision(driver, wait, subdivision_name)

    # QS
    try:
        qs = driver.find_element(By.XPATH, "/html/body/main/div/div/div/form/div/div[3]/div[2]/div[2]/input[2]")
    except Exception:
        qs = driver.find_element(By.CSS_SELECTOR, "input[value='QS']")
    driver.execute_script("arguments[0].click();", qs)

    sp = wait.until(EC.presence_of_element_located((By.ID, "SalePriceFrom")))
    sp.clear()
    sp.send_keys(str(int(min_sale_price)))

    df = wait.until(EC.presence_of_element_located((By.ID, "SaleDateFrom")))
    df.clear()
    df.send_keys(to_mmddyyyy(date_from))

    if str(date_to).strip():
        dt = wait.until(EC.presence_of_element_located((By.ID, "SaleDateTo")))
        dt.clear()
        dt.send_keys(to_mmddyyyy(date_to))

    btn = wait.until(EC.element_to_be_clickable((By.ID, "btnFormSearch")))
    driver.execute_script("arguments[0].click();", btn)
    time.sleep(2.8)

    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    out = []
    for r in rows:
        tds = r.find_elements(By.CSS_SELECTOR, "td")
        if len(tds) < 12:
            continue
        qv_link = tds[10].find_element(By.CSS_SELECTOR, "a")
        onclick = qv_link.get_attribute("onclick") or ""
        m = re.search(r"ShowDetails\('([0-9A-Za-z]+)'\)", onclick)
        if not m:
            continue
        parcel_id = m.group(1)
        out.append(
            {
                "parcel_id": parcel_id,
                "sale_price": tds[1].text.strip(),
                "sale_date": tds[2].text.strip(),
                "owner_name": tds[3].text.strip(),
                "location": tds[4].text.strip(),
                "municipality": tds[5].text.strip(),
                "sq_ft": tds[6].text.strip(),
                "mail_address": tds[7].text.strip(),
                "mail_city_state_zip": tds[8].text.strip(),
                "homesteaded": tds[9].text.strip(),
                "detail_url": DETAIL_URL_TMPL.format(parcel_id=parcel_id),
                "source_subdivision_search": subdivision_name,
            }
        )
    return out


def _extract_table_kv(driver) -> Dict[str, str]:
    details = {}
    for tr in driver.find_elements(By.XPATH, "//table//tr"):
        tds = tr.find_elements(By.XPATH, "./th|./td")
        texts = [x.text.strip() for x in tds if x.text and x.text.strip()]
        if len(texts) == 2:
            k, v = texts
            if k and k.upper() not in {"CODE", "DESCRIPTION"} and k not in details:
                details[k] = v
    return details


def _extract_additional_structures(driver) -> List[Dict]:
    structures = []
    for tr in driver.find_elements(By.XPATH, "//table//tr"):
        tds = tr.find_elements(By.XPATH, "./td")
        vals = [x.text.strip() for x in tds]
        if len(vals) >= 3:
            desc = vals[0]
            yr = vals[1]
            units = vals[2]
            # Additional structure rows look like: "Pool - In-Ground | 1982 | 1"
            if desc and re.fullmatch(r"\d{4}", yr or "") and re.fullmatch(r"\d+", units or ""):
                # filter out obvious non-structure lines
                bad = {"BASE AREA", "AREA UNDER AIR", "TOTAL SQUARE FOOTAGE", "NUMBER OF UNITS"}
                if desc.upper() in bad:
                    continue
                structures.append(
                    {
                        "description": desc,
                        "year_built": yr,
                        "units": units,
                    }
                )
    # de-dup
    dedup = []
    seen = set()
    for s in structures:
        key = (s["description"], s["year_built"], s["units"])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(s)
    return dedup


def scrape_property_details(driver, wait: WebDriverWait, parcel_id: str) -> Dict:
    url = DETAIL_URL_TMPL.format(parcel_id=parcel_id)
    driver.get(url)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    time.sleep(1.0)

    kv = _extract_table_kv(driver)
    structures = _extract_additional_structures(driver)
    return {
        "parcel_id": parcel_id,
        "detail_url": url,
        "property_address_detail": kv.get("Location", kv.get("LOCATION", "")),
        "subdivision_name_county": kv.get("SUBDIVISION", ""),
        "municipality": kv.get("MUNICIPALITY", kv.get("Municipality", "")),
        "sale_date_detail": kv.get("SALE DATE", ""),
        "property_use_code": kv.get("Property Use Code", ""),
        "zoning": kv.get("Zoning", ""),
        "acres": kv.get("Acres", ""),
        "bed_rooms": kv.get("Bed Rooms", ""),
        "full_baths": kv.get("Full Baths", ""),
        "half_baths": kv.get("Half Baths", ""),
        "year_built": kv.get("Year Built", ""),
        "stories": kv.get("Stories", ""),
        "roof_cover": kv.get("Roof Cover", ""),
        "air_condition_desc": kv.get("Air Condition Desc.", kv.get("Air Conditioning", "")),
        "area_under_air": kv.get("Area Under Air", ""),
        "total_square_footage": kv.get("Total Square Footage", kv.get("Total Square Feet*", "")),
        "additional_structures_json": json.dumps(structures, ensure_ascii=True),
        "additional_structures_count": len(structures),
    }


def parse_args():
    p = argparse.ArgumentParser(
        description="Consolidate parcel IDs from CMA subdivision searches and scrape detailed property pages."
    )
    p.add_argument("--query-csv", required=True, help="CSV from cma.py --output-sales-queries")
    p.add_argument("--output-sales-csv", default="cma_consolidated_sales.csv")
    p.add_argument("--output-details-csv", default="cma_consolidated_property_details.csv")
    p.add_argument("--max-subdivisions", type=int, default=0, help="Limit subdivision searches (0=all)")
    p.add_argument("--max-parcels", type=int, default=0, help="Limit parcel detail scrapes (0=all)")
    p.add_argument("--headless", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    q = pd.read_csv(args.query_csv, dtype=str).fillna("")
    if args.max_subdivisions and args.max_subdivisions > 0:
        q = q.head(args.max_subdivisions)

    options = webdriver.ChromeOptions()
    if args.headless:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1400,900")
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 15)

    all_sales_rows: List[Dict] = []
    try:
        # Phase 1: run sales searches for each official subdivision name.
        for i, r in q.iterrows():
            nm = r.get("official_subdivision_name", "").strip()
            if not nm:
                continue
            print(f"[search {i+1}/{len(q)}] {nm}")
            rows = run_sales_search(
                driver=driver,
                wait=wait,
                subdivision_name=nm,
                date_from=r.get("date_from", ""),
                date_to=r.get("date_to", ""),
                min_sale_price=int(float(r.get("min_sale_price", "100000") or 100000)),
            )
            for row in rows:
                row["unified_subdivision"] = r.get("unified_subdivision", "")
                row["normalized_subdivision_name"] = r.get("normalized_subdivision_name", "")
            all_sales_rows.extend(rows)

        if not all_sales_rows:
            raise RuntimeError("No sales rows collected from subdivision searches.")

        sales_df = pd.DataFrame(all_sales_rows).drop_duplicates(subset=["parcel_id", "sale_date"])
        sales_df = sales_df.sort_values(by=["parcel_id", "sale_date"])
        os.makedirs(os.path.dirname(args.output_sales_csv) or ".", exist_ok=True)
        sales_df.to_csv(args.output_sales_csv, index=False)
        print(f"Consolidated sales rows: {len(sales_df)} -> {os.path.abspath(args.output_sales_csv)}")

        # Carry address context into details output using the consolidated sales rows.
        sales_for_join = sales_df.copy()
        for col in ["location", "mail_address", "mail_city_state_zip"]:
            if col not in sales_for_join.columns:
                sales_for_join[col] = ""
        sales_for_join = (
            sales_for_join.sort_values(by=["parcel_id", "sale_date"])
            .drop_duplicates(subset=["parcel_id"], keep="first")
            .set_index("parcel_id")
        )

        # Phase 2: scrape each unique parcel details page.
        parcel_ids = list(sales_df["parcel_id"].dropna().astype(str).unique())
        if args.max_parcels and args.max_parcels > 0:
            parcel_ids = parcel_ids[: args.max_parcels]

        detail_rows = []
        for idx, pid in enumerate(parcel_ids, 1):
            print(f"[detail {idx}/{len(parcel_ids)}] {pid}")
            try:
                d = scrape_property_details(driver, wait, pid)
                if pid in sales_for_join.index:
                    s = sales_for_join.loc[pid]
                    d["property_address"] = s.get("location", "")
                    d["mail_address"] = s.get("mail_address", "")
                    d["mail_city_state_zip"] = s.get("mail_city_state_zip", "")
                else:
                    d["property_address"] = ""
                    d["mail_address"] = ""
                    d["mail_city_state_zip"] = ""
                d["scraped_at"] = datetime.now().isoformat(timespec="seconds")
                detail_rows.append(d)
            except Exception as e:
                detail_rows.append(
                    {
                        "parcel_id": pid,
                        "detail_url": DETAIL_URL_TMPL.format(parcel_id=pid),
                        "property_address": "",
                        "mail_address": "",
                        "mail_city_state_zip": "",
                        "scrape_error": str(e),
                        "scraped_at": datetime.now().isoformat(timespec="seconds"),
                    }
                )

        details_df = pd.DataFrame(detail_rows)
        os.makedirs(os.path.dirname(args.output_details_csv) or ".", exist_ok=True)
        details_df.to_csv(args.output_details_csv, index=False)
        print(f"Consolidated details rows: {len(details_df)} -> {os.path.abspath(args.output_details_csv)}")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
