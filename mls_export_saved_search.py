import argparse
import getpass
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.ui import Select

LOGIN_URL = (
    "https://beachesmls.mysolidearth.com/authenticate?"
    "redirect_to=eyJwYXJhbXMiOnt9LCJuYW1lIjoib2F1dGguYXV0aG9yaXplIiwicXVlcnkiOnsi"
    "Y2xpZW50X2lkIjoiSUtLUmo1Y1JfNTgtdElSQ3VoalFBNG5qUVAtZEhhYTNlVUZiR0Q2eFRq"
    "OCIsIm5vbmNlIjoiODY2Mjc4YzY5ZGJhNDE3ZDYzZmRmZjgwNjk3M2Q1YzkiLCJyZWRpcmVj"
    "dF91cmkiOiJodHRwczovL2ZsLmZsZXhtbHMuY29tL29wZW5pZF9ycC9jYWxsYmFjayIsInJl"
    "c3BvbnNlX3R5cGUiOiJjb2RlIiwic2NvcGUiOiJlbWFpbCBwcm9maWxlIG9wZW5pZCJ9fQ%3D%3D"
)
START_URL = "https://fl.flexmls.com"
LOGIN_PAGE_URL_FRAGMENT = "beachesmls.mysolidearth.com"
SAVED_SEARCHES_URL = "https://apps.flexmls.com/search/saved_searches?_variant=flagship"


def _first_visible(wait, selectors):
    for by, selector in selectors:
        try:
            return wait.until(EC.visibility_of_element_located((by, selector)))
        except TimeoutException:
            continue
    raise TimeoutException(f"No visible element found for selectors: {selectors}")


def _first_clickable(wait, selectors):
    for by, selector in selectors:
        try:
            return wait.until(EC.element_to_be_clickable((by, selector)))
        except Exception:
            continue
    raise TimeoutException(f"No clickable element found for selectors: {selectors}")


def _first_present(wait, selectors):
    for by, selector in selectors:
        try:
            return wait.until(EC.presence_of_element_located((by, selector)))
        except TimeoutException:
            continue
    raise TimeoutException(f"No present element found for selectors: {selectors}")


def _build_logger(log_file):
    logger = logging.getLogger(f"mls_export.{int(time.time() * 1000)}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    return logger


def _capture_debug(driver, debug_dir, step):
    if not debug_dir:
        return
    Path(debug_dir).mkdir(parents=True, exist_ok=True)
    safe_step = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in step)[:80]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    screenshot = Path(debug_dir) / f"{timestamp}_{safe_step}.png"
    html = Path(debug_dir) / f"{timestamp}_{safe_step}.html"
    driver.save_screenshot(str(screenshot))
    html.write_text(driver.page_source, encoding="utf-8")


def _log_state(logger, driver, message):
    logger.info("%s | url=%s | title=%s", message, driver.current_url, driver.title)


def _mask_value(value):
    if not value:
        return ""
    return "*" * min(len(value), 8)


def _log_url_change(logger, previous_url, driver, context):
    current_url = driver.current_url
    if current_url != previous_url:
        logger.info("URL changed after %s: %s -> %s", context, previous_url, current_url)
    return current_url


def _click_logged(driver, element, step, logger=None, debug_dir=None):
    element.click()
    if logger:
        logger.info("Click: %s", step)
    _capture_debug(driver, debug_dir, step)


def _set_input_value(driver, by, selector, value):
    el = driver.find_element(by, selector)
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
    # Prefer flatpickr API when present to avoid "invalid date" UI errors.
    applied = driver.execute_script(
        """
        const el = arguments[0];
        const val = arguments[1];
        function fire() {
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(new Event('change', { bubbles: true }));
          el.dispatchEvent(new Event('blur', { bubbles: true }));
        }
        try {
          if (el._flatpickr) {
            el._flatpickr.setDate(val, true, "m/d/Y");
            el._flatpickr.setDate(val, true, "m/d/y");
            fire();
            return true;
          }
        } catch (e) {}
        try {
          el.focus();
          el.value = val;
          fire();
          return true;
        } catch (e) {}
        return false;
        """,
        el,
        value,
    )
    if applied:
        return
    el.clear()
    el.send_keys(value)
    el.send_keys(Keys.TAB)


def _click_saved_search_by_name(driver, search_name, logger=None, debug_dir=None):
    js = """
        const target = arguments[0].trim();
        const spans = Array.from(document.querySelectorAll("span.savedSearchName"));
        for (const span of spans) {
            const txt = (span.textContent || "").trim();
            if (txt === target || txt.includes(target)) {
                const clickable = span.closest("a, .savedSearchContainer, .savedSearchRow, li, div");
                const el = clickable || span;
                el.scrollIntoView({ block: "center" });
                el.click();
                return txt;
            }
        }
        return null;
    """
    matched = driver.execute_script(js, search_name)
    if matched:
        if logger:
            logger.info("Clicked saved search via JS match: %s", matched)
        _capture_debug(driver, debug_dir, "open_saved_search")
        return True
    return False


def _select_custom_text_export(driver, logger=None):
    js = """
        const input = document.querySelector("#type5") || document.querySelector("input[name='stype'][value='custom']");
        const label = document.querySelector("label[for='type5']");
        if (!input && !label) return false;
        if (label) label.click();
        if (input) {
            input.checked = true;
            input.click();
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }
        return true;
    """
    ok = bool(driver.execute_script(js))
    if logger:
        logger.info("Custom export JS select result: %s", ok)
    return ok


def _select_export_template(driver, template_name, logger=None):
    if not template_name:
        return False
    try:
        select_el = driver.find_element(By.CSS_SELECTOR, "select[name='template_id']")
        sel = Select(select_el)
        sel.select_by_visible_text(template_name)
        if logger:
            logger.info("Selected export template: %s", template_name)
        return True
    except Exception as e:
        if logger:
            logger.info("Template selection skipped/failed (%s): %s", template_name, e)
        return False


def _force_custom_export_mode(driver, logger=None):
    js = """
        const custom = document.querySelector("input[name='stype'][value='custom']") || document.querySelector("#type5");
        const exportId = document.querySelector("input[name='export_id']");
        if (custom) {
          custom.checked = true;
          custom.click();
          custom.dispatchEvent(new Event('input', { bubbles: true }));
          custom.dispatchEvent(new Event('change', { bubbles: true }));
        }
        if (exportId) exportId.value = "type5";
        const checked = Array.from(document.querySelectorAll("input[name='stype']")).find(el => el.checked);
        return {
          custom_exists: !!custom,
          custom_checked: !!(custom && custom.checked),
          checked_id: checked ? checked.id : null,
          export_id: exportId ? exportId.value : null
        };
    """
    state = driver.execute_script(js) or {}
    if logger:
        logger.info(
            "Export mode state: custom_exists=%s custom_checked=%s checked_id=%s export_id=%s",
            state.get("custom_exists"),
            state.get("custom_checked"),
            state.get("checked_id"),
            state.get("export_id"),
        )
    return bool(state.get("custom_checked")) and state.get("checked_id") == "type5"


def _dump_browser_logs(driver, log_dir, run_ts, logger=None):
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    out = []
    for log_type in ("browser", "performance"):
        try:
            entries = driver.get_log(log_type)
            path = Path(log_dir) / f"mls_export_{run_ts}_{log_type}.jsonl"
            with path.open("w", encoding="utf-8") as f:
                for entry in entries:
                    f.write(json.dumps(entry, ensure_ascii=True) + "\n")
            out.append(str(path))
            if logger:
                logger.info("Saved %s log entries: %s (%d rows)", log_type, path, len(entries))
        except Exception as e:
            if logger:
                logger.info("Log type not available (%s): %s", log_type, e)
    return out


def _set_value_via_js(driver, selectors, value):
    js = """
        const selectors = arguments[0];
        const value = arguments[1];
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (!el) continue;
            el.focus();
            el.value = value;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }
        return false;
    """
    return bool(driver.execute_script(js, selectors, value))


def _fill_identity_fields(driver, value, logger=None):
    js = """
        const value = arguments[0];
        const selectors = [
          "input[name='member_login_id']",
          "input[name='email']",
          "input[aria-label='MLS Username']",
          "input[aria-label='Email']"
        ];
        const filled = [];
        for (const sel of selectors) {
          const nodes = Array.from(document.querySelectorAll(sel));
          for (const el of nodes) {
            try {
              el.focus();
              el.value = value;
              el.dispatchEvent(new Event('input', { bubbles: true }));
              el.dispatchEvent(new Event('change', { bubbles: true }));
              filled.push(sel);
            } catch (e) {}
          }
        }
        return filled;
    """
    filled = driver.execute_script(js, value) or []
    if logger:
        logger.info("Filled identity selectors: %s", ", ".join(filled) if filled else "(none)")
    return filled


def _fill_password(driver, wait, password, logger=None, timeout_sec=40):
    selectors = [
        "input[name='password']",
        "input[type='password']",
        "input[aria-label='Password']",
    ]
    deadline = time.time() + timeout_sec
    last_error = None

    while time.time() < deadline:
        for selector in selectors:
            try:
                fields = driver.find_elements(By.CSS_SELECTOR, selector)
                for field in fields:
                    if field.is_displayed() and field.is_enabled():
                        field.clear()
                        field.send_keys(password)
                        return "send_keys"
            except Exception as e:
                last_error = e

        try:
            if _set_value_via_js(driver, selectors, password):
                return "js"
        except Exception as e:
            last_error = e

        time.sleep(0.5)

    if last_error:
        raise last_error
    # Final fallback to raise a meaningful timeout with selectors context.
    _first_present(
        wait,
        [
            (By.CSS_SELECTOR, "input[name='password']"),
            (By.CSS_SELECTOR, "input[type='password']"),
            (By.CSS_SELECTOR, "input[aria-label='Password']"),
        ],
    )
    raise TimeoutException("Password field found but could not be filled.")


def _switch_to_view_frame_if_present(driver, logger=None):
    driver.switch_to.default_content()
    frames = driver.find_elements(By.CSS_SELECTOR, "iframe,frame")
    if not frames:
        if logger:
            logger.info("No frame found; staying in default content")
        return

    preferred_names = {"view_frame", "view"}
    for frame in frames:
        name = (frame.get_attribute("name") or "").strip().lower()
        frame_id = (frame.get_attribute("id") or "").strip().lower()
        if name in preferred_names or frame_id in preferred_names:
            driver.switch_to.frame(frame)
            if logger:
                logger.info("Switched to frame name=%s id=%s", name or "-", frame_id or "-")
            return

    # Fall back to first frame if view frame is not obvious.
    driver.switch_to.frame(frames[0])
    if logger:
        logger.info("Switched to first frame (fallback)")


def _switch_to_context_with_selector(driver, selector, logger=None, timeout_sec=0, max_depth=4):
    deadline = time.time() + max(timeout_sec, 0)

    def _search(depth=0):
        if driver.find_elements(By.CSS_SELECTOR, selector):
            return True
        if depth >= max_depth:
            return False
        frames = driver.find_elements(By.CSS_SELECTOR, "iframe,frame")
        for idx, frame in enumerate(frames):
            try:
                driver.switch_to.frame(frame)
                if _search(depth + 1):
                    if logger:
                        logger.info("Selector found in nested frame depth=%d index=%d: %s", depth + 1, idx, selector)
                    return True
                driver.switch_to.parent_frame()
            except Exception:
                try:
                    driver.switch_to.parent_frame()
                except Exception:
                    pass
                continue
        return False

    while True:
        try:
            driver.switch_to.default_content()
            if _search(0):
                if logger:
                    logger.info("Selector context ready: %s", selector)
                return True
        except Exception:
            pass

        if timeout_sec <= 0 or time.time() >= deadline:
            driver.switch_to.default_content()
            if logger:
                logger.info("Selector not found in default/nested frames: %s", selector)
            return False
        time.sleep(0.4)


def _switch_to_latest_window(driver, logger=None):
    try:
        handles = driver.window_handles
        if handles:
            driver.switch_to.window(handles[-1])
            if logger:
                logger.info("Switched to latest window handle: %s", handles[-1])
    except Exception as e:
        if logger:
            logger.info("Window switch skipped: %s", e)


def _wait_for_top_frame(driver, timeout_sec=45):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame("top_frame")
            return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _wait_for_csv(download_dir, timeout_sec, logger=None):
    download_path = Path(download_dir)
    deadline = time.time() + timeout_sec
    before = {p.name for p in download_path.glob("*.csv")}

    while time.time() < deadline:
        partial = list(download_path.glob("*.crdownload"))
        csvs = sorted(download_path.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if csvs and not partial:
            newest = csvs[0]
            if newest.name not in before or newest.stat().st_mtime >= time.time() - timeout_sec:
                if logger:
                    logger.info("Detected CSV download: %s", newest)
                return newest
        time.sleep(1)
    raise TimeoutException(f"CSV did not appear in {download_dir} within {timeout_sec}s.")


def _handle_ticket_login_if_present(driver, wait, username, password, logger=None, debug_dir=None):
    if "apps.flexmls.com/ticket" not in driver.current_url:
        return False

    if logger:
        logger.info("Ticket login detected, attempting secondary auth flow")
    _capture_debug(driver, debug_dir, "ticket_login_page")

    try:
        user_input = _first_present(wait, [(By.CSS_SELECTOR, "#user"), (By.NAME, "user")])
        user_input.clear()
        user_input.send_keys(username)
        if logger:
            logger.info("Filled ticket username")
    except Exception:
        if not _set_value_via_js(driver, ["#user", "input[name='user']"], username):
            raise
        if logger:
            logger.info("Filled ticket username via JS")

    next_btn = _first_clickable(wait, [(By.CSS_SELECTOR, "#login-button"), (By.NAME, "login")])
    _click_logged(driver, next_btn, "ticket_next", logger=logger, debug_dir=debug_dir)

    # Some ticket flows ask password on step 2; others redirect immediately.
    try:
        wait.until(lambda d: "apps.flexmls.com/ticket" not in d.current_url)
        if logger:
            logger.info("Ticket flow redirected without password step")
        return True
    except Exception:
        pass

    # Optional password step.
    try:
        pass_input = _first_present(wait, [(By.CSS_SELECTOR, "#password"), (By.NAME, "password"), (By.CSS_SELECTOR, "input[type='password']")])
        pass_input.clear()
        pass_input.send_keys(password)
        if logger:
            logger.info("Filled ticket password")
    except Exception:
        if not _set_value_via_js(driver, ["#password", "input[name='password']", "input[type='password']"], password):
            raise
        if logger:
            logger.info("Filled ticket password via JS")

    login_btn = _first_clickable(wait, [(By.CSS_SELECTOR, "#login-button"), (By.NAME, "login"), (By.CSS_SELECTOR, "button[type='submit']")])
    _click_logged(driver, login_btn, "ticket_submit", logger=logger, debug_dir=debug_dir)

    wait.until(lambda d: "apps.flexmls.com/ticket" not in d.current_url)
    if logger:
        logger.info("Ticket login completed")
    return True


def _login(driver, wait, email, password, logger=None, debug_dir=None):
    previous_url = driver.current_url
    driver.get(START_URL)
    if logger:
        previous_url = _log_url_change(logger, previous_url, driver, "open start url")
        _log_state(logger, driver, "Opened start URL")
    try:
        wait.until(EC.url_contains(LOGIN_PAGE_URL_FRAGMENT))
    except Exception:
        # If already logged in, this redirect might not occur.
        pass
    if logger:
        _log_state(logger, driver, "On login/auth page")
    _capture_debug(driver, debug_dir, "login_page")

    # Fill both MLS Username and Email fields if they exist.
    _first_present(
        wait,
        [
            (By.CSS_SELECTOR, "input[name='member_login_id']"),
            (By.CSS_SELECTOR, "input[name='email']"),
            (By.CSS_SELECTOR, "input[aria-label='MLS Username']"),
            (By.CSS_SELECTOR, "input[aria-label='Email']"),
        ],
    )
    _fill_identity_fields(driver, email, logger=logger)
    try:
        first_identity = driver.find_element(By.CSS_SELECTOR, "input[name='member_login_id'], input[name='email'], input[aria-label='MLS Username'], input[aria-label='Email']")
        first_identity.send_keys(Keys.TAB)
    except Exception:
        pass
    if logger:
        logger.info("Filled login identity with value: %s", email)

    fill_method = _fill_password(driver, wait, password, logger=logger, timeout_sec=40)
    if logger:
        logger.info("password fill method: %s (%s)", fill_method, _mask_value(password))
    if logger:
        logger.info("Filled password field")

    login_button = _first_clickable(
        wait,
        [
            (By.CSS_SELECTOR, "button[type='submit']"),
            (
                By.XPATH,
                "//button[.//div[normalize-space()='LOG IN'] or "
                "contains(normalize-space(), 'LOG IN')]",
            ),
            (
                By.XPATH,
                "/html/body/div[2]/div/main/div/div/div[1]/div/div[2]/form/"
                "div[2]/button/div",
            ),
        ],
    )
    _click_logged(driver, login_button, "login_button", logger=logger, debug_dir=debug_dir)
    if logger:
        logger.info("Clicked LOG IN")

    wait.until(lambda d: "authenticate" not in d.current_url)
    _switch_to_latest_window(driver, logger=logger)
    _handle_ticket_login_if_present(
        driver,
        wait,
        username=email,
        password=password,
        logger=logger,
        debug_dir=debug_dir,
    )
    if not _wait_for_top_frame(driver, timeout_sec=45):
        raise TimeoutException("Login submitted but top_frame did not appear.")
    driver.switch_to.default_content()
    if logger:
        _log_url_change(logger, previous_url, driver, "log in submit")
    print(f"Login successful. URL: {driver.current_url}")
    if logger:
        _log_state(logger, driver, "Login completed")
    _capture_debug(driver, debug_dir, "after_login")


def export_saved_search(
    email,
    password,
    search_name,
    download_dir,
    headless=False,
    timeout=35,
    download_timeout=120,
    log_file=None,
    debug_dir=None,
    login_only=False,
    from_date=None,
    export_template="AI Full DataSet",
    run_generate_db=False,
    ingest_dir="input_csvs",
):
    os.makedirs(download_dir, exist_ok=True)
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_file or os.path.join("logs", f"mls_export_{run_ts}.log")
    logger = _build_logger(log_file)
    print(f"Run log: {log_file}")
    logger.info("Starting export run for search_name=%s", search_name)
    logger.info("Run parameters: from_date=%s export_template=%s run_generate_db=%s", from_date, export_template, run_generate_db)

    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1502,900")
    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(Path(download_dir).resolve()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        },
    )
    options.set_capability("goog:loggingPrefs", {"browser": "ALL", "performance": "ALL"})

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, timeout)

    try:
        _login(driver, wait, email=email, password=password, logger=logger, debug_dir=debug_dir)
        if login_only:
            print("Login-only mode complete.")
            logger.info("Login-only mode complete")
            return None
        _switch_to_latest_window(driver, logger=logger)

        previous_url = driver.current_url
        driver.get(SAVED_SEARCHES_URL)
        _handle_ticket_login_if_present(
            driver,
            wait,
            username=email,
            password=password,
            logger=logger,
            debug_dir=debug_dir,
        )
        if "apps.flexmls.com/ticket" in driver.current_url:
            driver.get(SAVED_SEARCHES_URL)
        previous_url = _log_url_change(logger, previous_url, driver, "open saved searches")
        _log_state(logger, driver, "Opened saved searches page")
        _capture_debug(driver, debug_dir, "saved_searches_page")
        _switch_to_context_with_selector(driver, "a[data-target='#favorites']", logger=logger, timeout_sec=15)

        favorites_tab = _first_clickable(
            wait,
            [
                (By.CSS_SELECTOR, "a[data-target='#favorites']"),
                (By.XPATH, "//a[contains(normalize-space(.), 'Favorites')]"),
            ],
        )
        _click_logged(driver, favorites_tab, "favorites_tab", logger=logger, debug_dir=debug_dir)

        _switch_to_context_with_selector(driver, "span.savedSearchName", logger=logger, timeout_sec=15)
        if not _click_saved_search_by_name(driver, search_name, logger=logger, debug_dir=debug_dir):
            search_item = _first_clickable(
                wait,
                [
                    (
                        By.XPATH,
                        f"//span[contains(@class,'savedSearchName') and normalize-space()='{search_name}']",
                    ),
                    (
                        By.XPATH,
                        f"//*[contains(@class,'savedSearchName') and contains(normalize-space(), '{search_name}')]",
                    ),
                ],
            )
            _click_logged(driver, search_item, "open_saved_search", logger=logger, debug_dir=debug_dir)
        logger.info("Opened saved search: %s", search_name)

        if from_date:
            edit_search_tab = _first_clickable(
                wait,
                [
                    (By.CSS_SELECTOR, "#tab_search"),
                    (By.XPATH, "//a[@id='tab_search' and contains(normalize-space(.), 'Edit Search')]"),
                ],
            )
            _click_logged(driver, edit_search_tab, "edit_search_tab", logger=logger, debug_dir=debug_dir)
            logger.info("Opened Edit Search tab")

            date_ids = ["from_4_2", "from_4_4", "from_4_5", "from_4_6", "from_4_7", "from_4_8"]
            for field_id in date_ids:
                _first_present(wait, [(By.ID, field_id)])
                _set_input_value(driver, By.ID, field_id, from_date)
                current_val = driver.find_element(By.ID, field_id).get_attribute("value")
                logger.info("Set %s = %s (actual=%s)", field_id, from_date, current_val)

            # Try to move back to results context after date edits.
            try:
                results_tab = _first_clickable(
                    wait,
                    [
                        (By.CSS_SELECTOR, "#tab_grid"),
                        (By.XPATH, "//a[contains(normalize-space(.), 'Results')]"),
                        (By.XPATH, "//a[contains(normalize-space(.), 'List')]"),
                    ],
                )
                _click_logged(driver, results_tab, "results_tab", logger=logger, debug_dir=debug_dir)
            except Exception:
                logger.info("Results tab not found after edit; continuing in current context")

            _capture_debug(driver, debug_dir, "after_date_updates")

        # After opening the saved search, content may refresh in another frame/state.
        time.sleep(2)
        _switch_to_context_with_selector(driver, "#more-ellipses", logger=logger, timeout_sec=20)

        more_button = _first_clickable(
            wait,
            [
                (By.CSS_SELECTOR, "#more-ellipses a.dropdown-trigger"),
                (By.CSS_SELECTOR, "#more-ellipses .filemenu"),
                (By.XPATH, "//div[@id='more-ellipses']//a[contains(@class,'dropdown-trigger')]"),
            ],
        )
        _click_logged(driver, more_button, "more_menu", logger=logger, debug_dir=debug_dir)
        logger.info("Opened More menu")

        export_listings = _first_clickable(
            wait,
            [
                (By.CSS_SELECTOR, "li#export-listings a"),
                (By.XPATH, "//li[@id='export-listings']//a[contains(normalize-space(.), 'Export')]"),
            ],
        )
        _click_logged(driver, export_listings, "export_listings", logger=logger, debug_dir=debug_dir)
        logger.info("Clicked Export Listings")

        _switch_to_context_with_selector(driver, "label[for='type5'], #type5", logger=logger, timeout_sec=30)

        try:
            custom_export = _first_clickable(
                wait,
                [
                    (By.ID, "type5"),
                    (By.CSS_SELECTOR, "label[for='type5']"),
                    (By.XPATH, "//label[@for='type5' and contains(normalize-space(.), 'Custom Text Export')]"),
                ],
            )
            _click_logged(driver, custom_export, "custom_text_export", logger=logger, debug_dir=debug_dir)
            logger.info("Selected Custom Text Export")
        except Exception:
            if not _select_custom_text_export(driver, logger=logger):
                raise
            _capture_debug(driver, debug_dir, "custom_text_export")
            logger.info("Selected Custom Text Export via JS")

        _select_export_template(driver, export_template, logger=logger)
        if not _force_custom_export_mode(driver, logger=logger):
            raise TimeoutException("Unable to force Custom Text Export mode (type5).")
        _capture_debug(driver, debug_dir, "custom_mode_verified")

        run_export = _first_clickable(
            wait,
            [
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.CSS_SELECTOR, "button.g-recaptcha.btn.btn-primary"),
                (By.XPATH, "//button[contains(normalize-space(.), 'Export')]"),
            ],
        )
        _click_logged(driver, run_export, "final_export_click", logger=logger, debug_dir=debug_dir)
        logger.info("Clicked final Export button")

        csv_path = _wait_for_csv(download_dir=download_dir, timeout_sec=download_timeout, logger=logger)
        print(f"Export completed. CSV downloaded to: {csv_path}")
        logger.info("Export completed successfully: %s", csv_path)

        if run_generate_db:
            before_count = None
            after_count = None
            try:
                import sqlite3
                conn = sqlite3.connect("mls.db")
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM listing_details")
                before_count = cur.fetchone()[0]
                conn.close()
            except Exception as e:
                logger.info("Could not read pre-run row count: %s", e)

            os.makedirs(ingest_dir, exist_ok=True)
            src_path = Path(csv_path)
            dest_path = Path(ingest_dir) / src_path.name
            if dest_path.exists():
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest_path = Path(ingest_dir) / f"{stamp}_{src_path.name}"
            shutil.copy2(src_path, dest_path)
            logger.info("Copied export into ingest dir: %s", dest_path)
            print(f"Copied export to ingest folder: {dest_path}")

            logger.info("Running generate_db.py")
            subprocess.run([sys.executable, "generate_db.py"], check=True)
            print("generate_db.py completed successfully.")
            logger.info("generate_db.py completed successfully")

            try:
                import sqlite3
                conn = sqlite3.connect("mls.db")
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM listing_details")
                after_count = cur.fetchone()[0]
                conn.close()
            except Exception as e:
                logger.info("Could not read post-run row count: %s", e)

            delta = (after_count - before_count) if (before_count is not None and after_count is not None) else None
            print(
                f"Run summary: start_date={from_date or 'saved-search default'} | "
                f"downloaded={csv_path} | rows_before={before_count} | rows_after={after_count} | delta={delta}"
            )
            logger.info(
                "Run summary: start_date=%s downloaded=%s rows_before=%s rows_after=%s delta=%s",
                from_date or "saved-search default",
                csv_path,
                before_count,
                after_count,
                delta,
            )

        return str(csv_path)
    except Exception:
        os.makedirs("tmp", exist_ok=True)
        screenshot_path = os.path.join("tmp", f"mls_export_error_{run_ts}.png")
        try:
            driver.save_screenshot(screenshot_path)
            print(f"Export failed. Screenshot saved to: {screenshot_path}")
        except Exception:
            print("Export failed. Screenshot unavailable because browser window was closed.")
        logger.exception("Export failed; screenshot=%s", screenshot_path)
        raise
    finally:
        _dump_browser_logs(driver, log_dir="logs", run_ts=run_ts, logger=logger)
        logger.info("Closing browser")
        driver.quit()


def _build_args():
    parser = argparse.ArgumentParser(description="Export a Flexmls saved search to CSV.")
    parser.add_argument("--email", default=os.getenv("MLS_EMAIL"), help="MLS account email")
    parser.add_argument("--password", default=os.getenv("MLS_PASSWORD"), help="MLS account password")
    parser.add_argument(
        "--search-name",
        default="PalmBeach_Wellington_NewData",
        help="Saved search name shown in Favorites tab",
    )
    parser.add_argument(
        "--download-dir",
        default="output/mls_exports",
        help="Directory where CSV export will be saved",
    )
    parser.add_argument("--headless", action="store_true", help="Run Chrome in headless mode")
    parser.add_argument("--timeout", type=int, default=35, help="Element wait timeout in seconds")
    parser.add_argument(
        "--download-timeout",
        type=int,
        default=120,
        help="CSV download wait timeout in seconds",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Optional log file path. Defaults to logs/mls_export_<timestamp>.log",
    )
    parser.add_argument(
        "--debug-dir",
        default=None,
        help="Optional directory for step screenshots and page HTML captures",
    )
    parser.add_argument(
        "--login-only",
        action="store_true",
        help="Only perform login and stop (for troubleshooting auth flow)",
    )
    parser.add_argument(
        "--from-date",
        default=None,
        help="Optional MM/DD/YYYY value to apply to status date filters (from_4_2,4,5,6,7,8)",
    )
    parser.add_argument(
        "--export-template",
        default="AI Full DataSet",
        help="Template visible text for Custom Text Export (select[name='template_id'])",
    )
    parser.add_argument(
        "--run-generate-db",
        action="store_true",
        help="After download, copy CSV to input_csvs and run generate_db.py",
    )
    parser.add_argument(
        "--ingest-dir",
        default="input_csvs",
        help="Folder where exported CSV is copied before running generate_db.py",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _build_args()

    email = args.email or input("MLS email: ").strip()
    password = args.password or getpass.getpass("MLS password: ").strip()

    if not email or not password:
        raise SystemExit("Email and password are required.")

    export_saved_search(
        email=email,
        password=password,
        search_name=args.search_name,
        download_dir=args.download_dir,
        headless=args.headless,
        timeout=args.timeout,
        download_timeout=args.download_timeout,
        log_file=args.log_file,
        debug_dir=args.debug_dir,
        login_only=args.login_only,
        from_date=args.from_date,
        export_template=args.export_template,
        run_generate_db=args.run_generate_db,
        ingest_dir=args.ingest_dir,
    )
