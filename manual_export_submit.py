import os
import time
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait

from mls_export_saved_search import (
    _click_saved_search_by_name,
    _first_clickable,
    _login,
    _switch_to_context_with_selector,
    _switch_to_latest_window,
)


SEARCH_NAME = os.getenv("MLS_SEARCH_NAME", "PalmBeach_Wellington_NewData")
EXPORT_TEMPLATE = os.getenv("MLS_EXPORT_TEMPLATE", "AIDataSet")
DOWNLOAD_DIR = os.getenv("MLS_DOWNLOAD_DIR", "output/mls_exports")


def _wait_for_export_controls(driver, timeout_sec=30):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        for selector in (
            "button.g-recaptcha.btn.btn-primary[type='submit']",
            "label[for='type5']",
            "#type5",
            "select",
        ):
            if _switch_to_context_with_selector(driver, selector, timeout_sec=1):
                label = driver.find_elements(By.CSS_SELECTOR, "label[for='type5']")
                radio = driver.find_elements(By.CSS_SELECTOR, "#type5")
                button = driver.find_elements(By.CSS_SELECTOR, "button.g-recaptcha.btn.btn-primary[type='submit']")
                if (label or radio) and button:
                    return True
                driver.switch_to.default_content()
        time.sleep(0.5)
    return False


def _force_custom_export(driver):
    driver.switch_to.default_content()
    if not _switch_to_context_with_selector(driver, "label[for='type5']", timeout_sec=2):
        _switch_to_context_with_selector(driver, "#type5", timeout_sec=2)
    return bool(
        driver.execute_script(
            """
            const label = document.querySelector("label[for='type5']");
            const radio = document.querySelector('#type5');
            if (label) { try { label.click(); } catch (e) {} }
            if (radio) {
              try { radio.click(); } catch (e) {}
              radio.checked = true;
              radio.dispatchEvent(new Event('input', { bubbles: true }));
              radio.dispatchEvent(new Event('change', { bubbles: true }));
            }
            return !!(radio && radio.checked);
            """
        )
    )


def _select_template(driver, template_name):
    driver.switch_to.default_content()
    _switch_to_context_with_selector(driver, "select", timeout_sec=2)
    for select_el in driver.find_elements(By.TAG_NAME, "select"):
        try:
            sel = Select(select_el)
            sel.select_by_visible_text(template_name)
            return True
        except Exception:
            continue
    return False


def _wait_for_download(download_dir, timeout_sec=180):
    download_path = Path(download_dir)
    download_path.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in download_path.glob("*.csv")}
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        csvs = sorted(download_path.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        partials = list(download_path.glob("*.crdownload"))
        if csvs and not partials:
            newest = csvs[0]
            if newest.name not in before:
                return newest
        time.sleep(1)
    raise TimeoutException(f"No CSV appeared in {download_dir} within {timeout_sec}s.")


def main():
    email = os.environ["MLS_EMAIL"]
    password = os.environ["MLS_PASSWORD"]

    Path("tmp").mkdir(exist_ok=True)
    options = webdriver.ChromeOptions()
    options.add_argument("--window-size=1600,1000")

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 90)

    try:
        _login(driver, wait, email=email, password=password)
        _switch_to_latest_window(driver)

        driver.get("https://apps.flexmls.com/search/saved_searches?_variant=flagship")
        _switch_to_context_with_selector(driver, "a[data-target='#favorites']", timeout_sec=20)
        _first_clickable(wait, [(By.CSS_SELECTOR, "a[data-target='#favorites']")]).click()

        _switch_to_context_with_selector(driver, "span.savedSearchName", timeout_sec=20)
        if not _click_saved_search_by_name(driver, SEARCH_NAME):
            raise SystemExit(f"Could not open saved search: {SEARCH_NAME}")

        time.sleep(2)
        _first_clickable(wait, [(By.CSS_SELECTOR, "#more-ellipses a.dropdown-trigger")]).click()
        time.sleep(1)

        export = _first_clickable(
            wait,
            [
                (By.CSS_SELECTOR, "a[title='Export Listings']"),
                (By.XPATH, "//a[@title='Export Listings' and normalize-space()='Export']"),
            ],
        )
        driver.execute_script("arguments[0].click();", export)

        if not _wait_for_export_controls(driver, timeout_sec=30):
            driver.save_screenshot("tmp/manual_export_submit_controls_missing.png")
            Path("tmp/manual_export_submit_controls_missing.html").write_text(driver.page_source, encoding="utf-8")
            raise TimeoutException("Export page controls did not appear.")

        driver.save_screenshot("tmp/manual_export_submit_before_type5.png")
        Path("tmp/manual_export_submit_before_type5.html").write_text(driver.page_source, encoding="utf-8")

        if not _force_custom_export(driver):
            driver.save_screenshot("tmp/manual_export_submit_type5_failed.png")
            Path("tmp/manual_export_submit_type5_failed.html").write_text(driver.page_source, encoding="utf-8")
            raise TimeoutException("Custom Text Export did not become selected.")

        _select_template(driver, EXPORT_TEMPLATE)
        driver.save_screenshot("tmp/manual_export_submit_after_type5.png")
        Path("tmp/manual_export_submit_after_type5.html").write_text(driver.page_source, encoding="utf-8")

        driver.switch_to.default_content()
        _switch_to_context_with_selector(driver, "button.g-recaptcha.btn.btn-primary[type='submit']", timeout_sec=2)
        submit = _first_clickable(wait, [(By.CSS_SELECTOR, "button.g-recaptcha.btn.btn-primary[type='submit']")])
        driver.execute_script("arguments[0].click();", submit)
        driver.save_screenshot("tmp/manual_export_submit_after_click.png")
        Path("tmp/manual_export_submit_after_click.html").write_text(driver.page_source, encoding="utf-8")

        csv_path = _wait_for_download(DOWNLOAD_DIR, timeout_sec=180)
        print(f"Export completed: {csv_path}")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
