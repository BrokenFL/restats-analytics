import argparse
import getpass
import os
import re
import shutil
import sqlite3
import socket
import subprocess
import sys
import time
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

START_URL = "https://fl.flexmls.com"
LOGIN_URL = "https://beachesmls.mysolidearth.com/authenticate"
QUICK_SEARCH_URL = "https://fl.flexmls.com/cgi-bin/mainmenu.cgi?cmd=url+search/template/index.html"
LOGIN_PAGE_URL_FRAGMENT = "beachesmls.mysolidearth.com"
RESOURCE_PANELS_URL_FRAGMENT = "/resources/panels/"
FLEXMLS_RESOURCE_CARD_HREF = "https://flr.flexmls.com/openid_rp?provider_id=71"
ALL_STATUS_CODES = ["A", "H", "P", "PWC_U", "C", "E", "W", "O", "L"]
FULL_CITY_REFRESH_CITIES = {"SOUTH PALM BEACH"}
MAX_EXPORT_RECORDS = 4000
RESIDENTIAL_QUICK_SEARCH_TEMPLATE_ID = "20231129214456095779000000"
RESIDENTIAL_QUICK_SEARCH_VIEW_ID = "20231129213900299116000000"
ENV_CANDIDATE_FILES = (
    ".env",
    ".env.local",
    "~/.codex/mls.env",
    "~/.codex/mls.env.local",
    "~/.config/openclaw/secrets/mls.env",
)
KEYCHAIN_PASSWORD_SERVICES = (
    "MLS_PASSWORD",
    "MLS Refresh",
    "BeachesMLS",
    "FlexMLS",
    "MLS",
)
KEYCHAIN_EMAIL_SERVICES = (
    "MLS_EMAIL",
    "MLS Refresh",
    "BeachesMLS",
    "FlexMLS",
    "MLS",
)


def _load_local_env_defaults() -> None:
    for rel_path in ENV_CANDIDATE_FILES:
        env_path = Path(rel_path).expanduser()
        if not env_path.exists():
            continue
        try:
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except Exception:
            continue


def _read_keychain_password(service: str, account: str) -> str:
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _bootstrap_mls_env() -> None:
    _load_local_env_defaults()

    if not os.getenv("MLS_EMAIL"):
        for service in KEYCHAIN_EMAIL_SERVICES:
            for account in ("MLS_EMAIL", "brooke.snader@gmail.com"):
                value = _read_keychain_password(service, account)
                if value and "@" in value:
                    os.environ["MLS_EMAIL"] = value
                    break
            if os.getenv("MLS_EMAIL"):
                break

    email = os.getenv("MLS_EMAIL", "").strip()
    if not os.getenv("MLS_PASSWORD"):
        accounts = [a for a in (email, "MLS_PASSWORD", "mls-refresh") if a]
        for service in KEYCHAIN_PASSWORD_SERVICES:
            for account in accounts:
                value = _read_keychain_password(service, account)
                if value:
                    os.environ["MLS_PASSWORD"] = value
                    break
            if os.getenv("MLS_PASSWORD"):
                break


def _capture_debug(driver, debug_dir: str, step: str) -> None:
    if not debug_dir:
        return
    Path(debug_dir).mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", step)[:80]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    png = Path(debug_dir) / f"{ts}_{safe}.png"
    html = Path(debug_dir) / f"{ts}_{safe}.html"
    try:
        driver.save_screenshot(str(png))
    except Exception:
        pass
    try:
        html.write_text(driver.page_source, encoding="utf-8")
    except Exception:
        pass


def _switch_to_latest_window(driver) -> None:
    handles = driver.window_handles
    if handles:
        driver.switch_to.window(handles[-1])


def _wait_for_top_frame(driver, timeout_sec: int = 45) -> bool:
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


def _switch_to_context_with_selector(driver, selector: str, timeout_sec: int = 20, max_depth: int = 5) -> bool:
    deadline = time.time() + timeout_sec

    def _search(depth: int) -> bool:
        if driver.find_elements(By.CSS_SELECTOR, selector):
            return True
        if depth >= max_depth:
            return False
        frames = driver.find_elements(By.CSS_SELECTOR, "iframe,frame")
        for fr in frames:
            try:
                driver.switch_to.frame(fr)
                if _search(depth + 1):
                    return True
                driver.switch_to.parent_frame()
            except Exception:
                try:
                    driver.switch_to.parent_frame()
                except Exception:
                    pass
        return False

    while time.time() < deadline:
        driver.switch_to.default_content()
        if _search(0):
            return True
        time.sleep(0.4)
    driver.switch_to.default_content()
    return False


def _click_if_present(driver, wait: WebDriverWait, selectors) -> bool:
    for by, selector in selectors:
        try:
            elems = driver.find_elements(by, selector)
            for el in elems:
                if not el.is_displayed():
                    continue
                try:
                    el.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", el)
                return True
        except Exception:
            continue
    return False


def _set_value_via_js(driver, selectors, value) -> bool:
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


def _fill_identity_fields(driver, value: str) -> None:
    selectors = [
        "input[name='email'][type='email']",
        "input[type='email'][aria-label='Email']",
        "input[name='member_login_id']",
        "input[aria-label='MLS Username']",
    ]
    for sel in selectors:
        for field in driver.find_elements(By.CSS_SELECTOR, sel):
            try:
                if field.is_displayed() and field.is_enabled():
                    field.clear()
                    field.send_keys(value)
                    return
            except Exception:
                continue
    if not _set_value_via_js(driver, selectors, value):
        raise TimeoutException("Could not fill identity field.")


def _select_email_mode(driver, timeout_sec: int = 45) -> None:
    # Prefer a real Selenium click on the visible "Email" control before JS fallbacks.
    for by, sel in [
        (By.XPATH, "//label[normalize-space()='Email']"),
        (By.XPATH, "//*[self::label or self::div or self::span][normalize-space()='Email']"),
        (By.CSS_SELECTOR, "input[type='radio'][value='email']"),
    ]:
        try:
            for el in driver.find_elements(by, sel):
                if el.is_displayed() and el.is_enabled():
                    try:
                        el.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", el)
                    time.sleep(0.6)
                    if driver.find_elements(By.CSS_SELECTOR, "input[name='email'][type='email'], input[type='email'][aria-label='Email']"):
                        return
        except Exception:
            continue

    js = """
        const visible = (el) => !!(el && el.offsetParent !== null);
        const clickish = (el) => { try { el.click(); return true; } catch (e) { return false; } };
        const emailInput = document.querySelector("input[name='email'][type='email'], input[type='email'][aria-label='Email']");
        const mlsInput = document.querySelector("input[name='member_login_id'], input[aria-label='MLS Username']");
        if (visible(emailInput) && !visible(mlsInput)) {
          return {ready:true, emailVisible:true, mlsVisible:false};
        }

        const emailRadio = document.querySelector("input[type='radio'][value='email']");
        if (emailRadio) {
          try {
            emailRadio.checked = true;
            emailRadio.dispatchEvent(new MouseEvent('click', { bubbles: true }));
            emailRadio.dispatchEvent(new Event('input', { bubbles: true }));
            emailRadio.dispatchEvent(new Event('change', { bubbles: true }));
          } catch (e) {}
          const radioWrap = emailRadio.closest('.v-radio, .v-input--selection-controls__input');
          if (radioWrap) clickish(radioWrap);
          const label = radioWrap ? radioWrap.parentElement && radioWrap.parentElement.querySelector('label') : null;
          if (label) clickish(label);
        }

        return {
          ready:false,
          emailVisible: visible(document.querySelector("input[name='email'][type='email'], input[type='email'][aria-label='Email']")),
          mlsVisible: visible(document.querySelector("input[name='member_login_id'], input[aria-label='MLS Username']")),
          title: document.title || '',
        };
    """
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        state = driver.execute_script(js) or {}
        if state.get("ready") or (state.get("emailVisible") and not state.get("mlsVisible")):
            return
        time.sleep(0.5)
    raise TimeoutException("Could not switch login page into Email mode.")


def _fill_password(driver, password: str, timeout_sec: int = 40) -> None:
    selectors = [
        "input[name='password'][type='password']",
        "input[type='password'][aria-label='Password']",
        "input[type='password']",
    ]
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        for sel in selectors:
            fields = driver.find_elements(By.CSS_SELECTOR, sel)
            for f in fields:
                if f.is_displayed() and f.is_enabled():
                    f.clear()
                    f.send_keys(password)
                    return
        if _set_value_via_js(driver, selectors, password):
            return
        time.sleep(0.5)
    raise TimeoutException("Could not fill password field.")


def _wait_for_auth_form(driver, timeout_sec: int = 45) -> None:
    deadline = time.time() + timeout_sec
    js = """
        const hasRadio = !!document.querySelector("input[type='radio'][value='email'], input[type='radio'][value='member_login_id']");
        const hasMls = !!document.querySelector("input[name='member_login_id'], input[aria-label='MLS Username']");
        const hasPassword = !!document.querySelector("input[type='password'][aria-label='Password'], input[type='password']");
        return {hasRadio, hasMls, hasPassword, title: document.title || ''};
    """
    while time.time() < deadline:
        state = driver.execute_script(js) or {}
        if state.get("hasRadio") or state.get("hasMls") or state.get("hasPassword"):
            return
        time.sleep(0.5)
    raise TimeoutException("Auth form did not hydrate on the login page.")


def _wait_for_email_login_fields(driver, timeout_sec: int = 20) -> None:
    deadline = time.time() + timeout_sec
    email_selectors = ["input[name='email'][type='email']", "input[type='email'][aria-label='Email']"]
    password_selectors = ["input[name='password'][type='password']", "input[type='password'][aria-label='Password']", "input[type='password']"]

    while time.time() < deadline:
        email_ready = False
        password_ready = False
        for sel in email_selectors:
            for field in driver.find_elements(By.CSS_SELECTOR, sel):
                try:
                    if field.is_displayed() and field.is_enabled():
                        email_ready = True
                        break
                except Exception:
                    continue
            if email_ready:
                break
        for sel in password_selectors:
            for field in driver.find_elements(By.CSS_SELECTOR, sel):
                try:
                    if field.is_displayed() and field.is_enabled():
                        password_ready = True
                        break
                except Exception:
                    continue
            if password_ready:
                break
        if email_ready and password_ready:
            return
        time.sleep(0.4)
    raise TimeoutException("Email/password fields did not become ready after selecting Email mode.")


def _handle_ticket_login_if_present(driver, wait: WebDriverWait, username: str, password: str) -> bool:
    if "apps.flexmls.com/ticket" not in driver.current_url:
        return False
    # Username step
    for by, sel in [(By.CSS_SELECTOR, "#user"), (By.NAME, "user")]:
        try:
            el = wait.until(EC.presence_of_element_located((by, sel)))
            el.clear()
            el.send_keys(username)
            break
        except Exception:
            continue
    else:
        _set_value_via_js(driver, ["#user", "input[name='user']"], username)

    for by, sel in [(By.CSS_SELECTOR, "#login-button"), (By.NAME, "login"), (By.CSS_SELECTOR, "button[type='submit']")]:
        try:
            wait.until(EC.element_to_be_clickable((by, sel))).click()
            break
        except Exception:
            continue

    # Might redirect immediately
    try:
        wait.until(lambda d: "apps.flexmls.com/ticket" not in d.current_url)
        return True
    except Exception:
        pass

    # Password step (optional)
    for by, sel in [
        (By.CSS_SELECTOR, "#password"),
        (By.NAME, "password"),
        (By.CSS_SELECTOR, "input[type='password']"),
    ]:
        try:
            pel = wait.until(EC.presence_of_element_located((by, sel)))
            pel.clear()
            pel.send_keys(password)
            break
        except Exception:
            continue
    else:
        _set_value_via_js(driver, ["#password", "input[name='password']", "input[type='password']"], password)

    for by, sel in [(By.CSS_SELECTOR, "#login-button"), (By.NAME, "login"), (By.CSS_SELECTOR, "button[type='submit']")]:
        try:
            wait.until(EC.element_to_be_clickable((by, sel))).click()
            break
        except Exception:
            continue

    wait.until(lambda d: "apps.flexmls.com/ticket" not in d.current_url)
    return True


def _wait_for_flex_shell(
    driver,
    wait: WebDriverWait,
    username: str,
    password: str,
    debug_dir: str,
    timeout_sec: int = 90,
) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            _switch_to_latest_window(driver)
        except Exception:
            pass

        # Success condition on legacy Flex shell.
        if _wait_for_top_frame(driver, timeout_sec=2):
            driver.switch_to.default_content()
            return

        state = None
        try:
            handles = list(driver.window_handles)
        except Exception:
            handles = []
        for handle in reversed(handles):
            try:
                driver.switch_to.window(handle)
                url_probe = driver.current_url
                title_probe = (driver.title or "").lower()
                if "flexmls" in url_probe or "flexmls" in title_probe:
                    state = "flexmls"
                    break
                if RESOURCE_PANELS_URL_FRAGMENT in url_probe or "resource panels" in title_probe:
                    state = "resource_panels"
                    break
            except Exception:
                continue

        if state == "resource_panels":
            try:
                driver.execute_script("window.open(arguments[0], '_blank');", FLEXMLS_RESOURCE_CARD_HREF)
                _switch_to_latest_window(driver)
                _capture_debug(driver, debug_dir, "resource_panels_launch_flex")
            except Exception:
                try:
                    driver.get(FLEXMLS_RESOURCE_CARD_HREF)
                except Exception:
                    pass
            time.sleep(1.0)
            continue

        try:
            url = driver.current_url
            title = (driver.title or "").strip()
        except Exception:
            time.sleep(1.0)
            continue

        # Flex occasionally returns a transient 500 on callback; retry entrypoint.
        if "Internal Server Error (500)" in title or "openid_rp/assets/flexmls_rails_http_status/error" in driver.page_source:
            driver.get(START_URL)
            time.sleep(1.0)
            continue

        # Sometimes auth lands on myTRIBUS authorize page and needs a nudge.
        if "beachesmls.mysolidearth.com" in url:
            clicked = _click_if_present(
                driver,
                wait,
                [
                    (By.XPATH, "//a[contains(@href, 'flr.flexmls.com/openid_rp?provider_id=71')]"),
                    (By.XPATH, "//button[contains(., 'Authorize')]"),
                    (By.XPATH, "//button[contains(., 'Continue')]"),
                    (By.XPATH, "//button[contains(., 'Allow')]"),
                    (By.XPATH, "//a[contains(., 'Continue')]"),
                    (By.XPATH, "//a[contains(., 'Launch')]"),
                    (By.XPATH, "//a[contains(@href, 'fl.flexmls.com')]"),
                    (By.XPATH, "//a[contains(@href, '/resources/enter')]"),
                ],
            )
            if clicked:
                _capture_debug(driver, debug_dir, "authorize_click")
            else:
                # Force callback path again when page stays on spinner.
                if "oauth/authorize" in url or "Authorize" in title:
                    driver.get(START_URL)

        if "apps.flexmls.com/ticket" in url:
            _handle_ticket_login_if_present(driver, wait, username=username, password=password)

        time.sleep(1.0)

    _capture_debug(driver, debug_dir, "flex_shell_timeout")
    raise TimeoutException("Login completed but Flex shell (top_frame) did not load.")


def login(driver, wait: WebDriverWait, email: str, password: str, debug_dir: str) -> None:
    driver.get(LOGIN_URL)
    _capture_debug(driver, debug_dir, "start_url")
    try:
        wait.until(EC.url_contains(LOGIN_PAGE_URL_FRAGMENT))
    except Exception:
        pass

    _wait_for_auth_form(driver)
    _capture_debug(driver, debug_dir, "auth_form_ready")
    _select_email_mode(driver)
    _capture_debug(driver, debug_dir, "email_mode_selected")
    _wait_for_email_login_fields(driver)
    _capture_debug(driver, debug_dir, "email_fields_ready")
    _fill_identity_fields(driver, email)
    _fill_password(driver, password)

    login_btn = None
    for by, selector in [
        (By.CSS_SELECTOR, "button[type='submit']"),
        (By.XPATH, "//button[contains(normalize-space(), 'LOG IN')]"),
    ]:
        try:
            login_btn = wait.until(EC.element_to_be_clickable((by, selector)))
            break
        except Exception:
            continue
    if not login_btn:
        raise TimeoutException("Could not find login button.")
    try:
        login_btn.click()
    except Exception:
        driver.execute_script("arguments[0].click();", login_btn)

    # Auth can pause on the same URL briefly (spinner/challenge), so do not hard-fail here.
    try:
        WebDriverWait(driver, 20).until(
            lambda d: "authenticate" not in d.current_url or "fl.flexmls.com" in d.current_url
        )
    except TimeoutException:
        pass
    _switch_to_latest_window(driver)
    _handle_ticket_login_if_present(driver, wait, username=email, password=password)
    _wait_for_flex_shell(
        driver,
        wait,
        username=email,
        password=password,
        debug_dir=debug_dir,
        timeout_sec=90,
    )
    driver.switch_to.default_content()
    _capture_debug(driver, debug_dir, "after_login")


def _open_quick_search(driver, wait: WebDriverWait, debug_dir: str) -> None:
    _set_residential_quick_search_preferences(driver)
    driver.get(QUICK_SEARCH_URL)
    _switch_to_latest_window(driver)
    found = _switch_to_context_with_selector(driver, "#enabled_7, #t_7, input[name='t_7']", timeout_sec=30)
    if not found:
        # Try opening quick search from menu link inside app shell.
        driver.switch_to.default_content()
        _switch_to_context_with_selector(driver, "a[data-id='QuickSearch']", timeout_sec=10)
        try:
            wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "a[data-id='QuickSearch']"))).click()
        except Exception:
            pass
        found = _switch_to_context_with_selector(driver, "#enabled_7, #t_7, input[name='t_7']", timeout_sec=20)
    if not found:
        raise TimeoutException("Quick Search subdivision controls not found (enabled_7/t_7).")
    _capture_debug(driver, debug_dir, "quick_search_opened")


def _set_residential_quick_search_preferences(driver) -> None:
    try:
        driver.execute_async_script(
            """
            const done = arguments[arguments.length - 1];
            const params = [
              ['cmd', 'srv srch_rs/updatePref.html'],
              ['p_id', window.js_tech_id || '20250221102138345360000000'],
              ['template_id', arguments[0]],
              ['command_line_mode', 'true'],
            ];
            const updates = [
              ['last_quick_srch', arguments[0]],
              ['lastview', arguments[1]],
            ].map(([name, value]) => {
              const body = new URLSearchParams(params);
              body.set('pn', name);
              body.set('pv', value);
              return fetch('/cgi-bin/mainmenu-compress.cgi', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'},
                body: body.toString(),
                credentials: 'same-origin',
              }).then(resp => ({ok: resp.ok, status: resp.status, name}));
            });
            Promise.allSettled(updates).then(results => done(results)).catch(err => done(String(err)));
            """,
            RESIDENTIAL_QUICK_SEARCH_TEMPLATE_ID,
            RESIDENTIAL_QUICK_SEARCH_VIEW_ID,
        )
    except Exception:
        # Preference reset is best-effort; field-level checks below verify the actual loaded schema.
        return


def _ensure_residential_view(driver, wait: WebDriverWait, debug_dir: str) -> None:
    js = """
        const select = document.querySelector('#new_sd_tech_id');
        if (!select) return {ok:false, reason:'view_select_not_found'};

        const options = Array.from(select.options || []);
        const current = options.find(opt => !!opt.selected);
        const currentText = String(current ? current.textContent || '' : '').trim();
        const target = options.find(opt => {
          const text = String(opt.textContent || '').trim().toUpperCase();
          return text.startsWith('[1-RESIDENTIAL') || text === '[1-RESIDENTIAL *]';
        });
        if (!target) {
          return {
            ok:false,
            reason:'residential_view_not_found',
            options: options.map(opt => String(opt.textContent || '').trim())
          };
        }
        const hasCity = !!document.querySelector("select[data-locationfieldid='city']");
        if (current && current.value === target.value && hasCity) {
          return {ok:true, currentText, targetText:String(target.textContent || '').trim(), hasCity};
        }
        return {
          ok:false,
          reason:'residential_schema_not_loaded',
          currentText,
          targetText:String(target.textContent || '').trim(),
          hasCity
        };
    """
    result = driver.execute_script(js) or {}
    if result.get("ok"):
        _capture_debug(driver, debug_dir, "quick_search_residential_view")
        return

    # The view selector controls result columns, not the search template. If Flex
    # remembered the rental Quick Search, rebuild the Quick Search template through
    # the page's own loader so the Residential field list, including City, renders.
    loaded = driver.execute_script(
        """
        if (typeof loadNewQuickSearch !== 'function') {
          return {ok:false, reason:'loadNewQuickSearch_missing'};
        }
        const link = document.createElement('a');
        link.setAttribute('value', arguments[0] + "|'A'");
        link.textContent = '1-Residential';
        document.body.appendChild(link);
        try {
          loadNewQuickSearch(link);
          return {ok:true};
        } catch (e) {
          return {ok:false, reason:String(e && e.message ? e.message : e)};
        } finally {
          try { link.remove(); } catch (e) {}
        }
        """,
        RESIDENTIAL_QUICK_SEARCH_TEMPLATE_ID,
    ) or {}
    if not loaded.get("ok"):
        _capture_debug(driver, debug_dir, "quick_search_wrong_schema")
        raise TimeoutException(
            "Residential Quick Search schema did not load. "
            f"reason={result.get('reason')} current={result.get('currentText')} target={result.get('targetText')} "
            f"template_loader_reason={loaded.get('reason')}"
        )

    try:
        wait.until(lambda d: d.execute_script("return !!document.querySelector(\"select[data-locationfieldid='city']\")"))
    except TimeoutException:
        _capture_debug(driver, debug_dir, "quick_search_wrong_schema")
        raise TimeoutException("Residential Quick Search template loaded, but City field did not render.")
    _capture_debug(driver, debug_dir, "quick_search_residential_view")


def _set_status_values(driver, status_codes, debug_dir: str) -> None:
    # Explicitly set status multi-select so searches include all requested buckets.
    js = """
        const requested = (arguments[0] || []).map(x => String(x).toUpperCase().trim());
        if (!requested.length) return {ok:false, reason:'empty_requested'};

        let sel =
          document.querySelector("select[data-locationfieldid='status']") ||
          document.querySelector('#s_4') ||
          document.querySelector("select[name='s_4']") ||
          document.querySelector('#s_3') ||
          document.querySelector("select[name='s_3']");
        if (!sel) return {ok:false, reason:'status_select_not_found'};

        const statusItem = sel.closest('li.item, li.itemDisabled');
        if (statusItem) {
          const statusEnabled = statusItem.querySelector("input[id^='enabled_']");
          if (statusEnabled && !statusEnabled.checked) statusEnabled.click();
        }

        const options = Array.from(sel.options || []);
        const available = options.map(o => String(o.value || '').toUpperCase());
        for (const opt of options) opt.selected = false;

        let selectedCount = 0;
        for (const code of requested) {
          const opt = options.find(o => String(o.value || '').toUpperCase() === code);
          if (opt) {
            opt.selected = true;
            selectedCount += 1;
          }
        }
        sel.dispatchEvent(new Event('input', { bubbles: true }));
        sel.dispatchEvent(new Event('change', { bubbles: true }));
        const selectedValues = options
          .filter(o => !!o.selected)
          .map(o => String(o.value || '').toUpperCase());
        const requestedPresent = requested.filter(code => available.includes(code));
        const selectedRequestedCount = requestedPresent.filter(code => selectedValues.includes(code)).length;
        return {
          ok: selectedRequestedCount > 0,
          selectedCount,
          available,
          selectedValues,
          requestedPresentCount: requestedPresent.length,
          selectedRequestedCount
        };
    """
    result = driver.execute_script(js, status_codes) or {}
    step = "status_all_ok" if result.get("ok") else "status_all_failed"
    _capture_debug(driver, debug_dir, step)
    requested_present = int(result.get("requestedPresentCount") or 0)
    selected_requested = int(result.get("selectedRequestedCount") or 0)
    if requested_present and selected_requested < requested_present:
        raise TimeoutException(
            "Unable to set all requested MLS statuses. "
            f"selected={result.get('selectedValues')} available={result.get('available')}"
        )
    if not result.get("ok"):
        raise TimeoutException(f"Unable to set MLS status filter. reason={result.get('reason')}")


def _set_subdivision_value(driver, subdivision_name: str, debug_dir: str) -> None:
    # Per your note: enter *subdivision*.
    search_value = f"*{subdivision_name}*"
    js = """
        const enabled = document.querySelector('#enabled_7');
        if (enabled && !enabled.checked) enabled.click();
        const el = document.querySelector('#t_7');
        if (!el) return false;
        el.focus();
        el.value = arguments[0];
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
    """
    ok = driver.execute_script(js, search_value)
    if not ok:
        field = driver.find_element(By.ID, "t_7")
        field.clear()
        field.send_keys(search_value)
    _capture_debug(driver, debug_dir, "subdivision_set")


def _set_city_values(driver, city_names, debug_dir: str) -> None:
    requested = [str(c).strip() for c in city_names if str(c).strip()]
    if not requested:
        raise TimeoutException("No city names provided.")
    js = """
        const requested = (arguments[0] || []).map(x => String(x).trim()).filter(Boolean);
        if (!requested.length) return {ok:false, reason:'empty_requested'};

        let sel =
          document.querySelector("select[data-locationfieldid='city']") ||
          Array.from(document.querySelectorAll('select')).find(el =>
            String(el.getAttribute('aria-label') || '').trim().toUpperCase() === 'CITY'
          );
        if (!sel) return {ok:false, reason:'city_select_not_found'};

        const cityItem = sel.closest('li.item, li.itemDisabled');
        if (cityItem) {
          const cityEnabled = cityItem.querySelector("input[id^='enabled_']");
          if (cityEnabled && !cityEnabled.checked) cityEnabled.click();
        }

        const options = Array.from(sel.options || []);
        const byLabel = new Map(options.map(o => [String(o.textContent || o.value || '').trim().toUpperCase(), o]));
        for (const opt of options) opt.selected = false;

        let selected = [];
        let missing = [];
        for (const city of requested) {
          const opt = byLabel.get(city.toUpperCase());
          if (opt) {
            opt.selected = true;
            selected.push(city);
          } else {
            missing.push(city);
          }
        }
        sel.dispatchEvent(new Event('input', { bubbles: true }));
        sel.dispatchEvent(new Event('change', { bubbles: true }));
        return {ok:selected.length > 0, selected, missing};
    """
    result = driver.execute_script(js, requested) or {}
    _capture_debug(driver, debug_dir, "city_set")
    if not result.get("ok"):
        raise TimeoutException(f"Unable to set city filter. reason={result.get('reason')} missing={result.get('missing')}")
    missing = result.get("missing") or []
    if missing:
        raise TimeoutException(f"Some city filters were not found: {missing}")


def _set_status_from_date(driver, from_date: str, debug_dir: str, status_codes=None) -> None:
    js = """
        const fromDate = String(arguments[0] || '').trim();
        const requestedStatuses = (arguments[1] || []).map(x => String(x).toUpperCase().trim());
        if (!fromDate) return {ok:false, reason:'empty_from_date'};

        let sel =
          document.querySelector("select[data-locationfieldid='status']") ||
          document.querySelector('#s_4') ||
          document.querySelector("select[name='s_4']") ||
          document.querySelector('#s_3') ||
          document.querySelector("select[name='s_3']");
        if (!sel) return {ok:false, reason:'status_select_not_found'};

        const match = String(sel.id || sel.name || '').match(/s_(\\d+)/);
        if (!match) return {ok:false, reason:'status_group_not_found'};
        const groupId = match[1];
        const seeAll = document.getElementById(`${groupId}_see_all_link`);
        if (seeAll) {
          try { seeAll.click(); } catch (e) {}
        }

        const statusDateSuffixes = {
          P: ['2'],
          PWC_U: ['2'],
          C: ['4'],
          E: ['5'],
          W: ['6'],
          O: ['7'],
          L: ['8']
        };
        let suffixes = [];
        for (const status of requestedStatuses) {
          suffixes.push(...(statusDateSuffixes[status] || []));
        }
        suffixes = Array.from(new Set(suffixes));
        if (!suffixes.length) {
          return {ok:true, touched:[], skipped:true, reason:'no_date_fields_for_requested_statuses', groupId};
        }

        for (const suffix of ['2','4','5','6','7','8']) {
          const checkbox = document.getElementById(`c_${groupId}_${suffix}_date`);
          if (checkbox && checkbox.checked && !suffixes.includes(suffix)) {
            try { checkbox.click(); } catch (e) {}
          }
        }

        const ids = suffixes.map(suffix => `from_${groupId}_${suffix}`);
        const touched = [];
        for (const id of ids) {
          const el = document.getElementById(id);
          if (!el) continue;
          const dateCheckbox = document.getElementById(`c_${groupId}_${id.split('_').pop()}_date`);
          try {
            if (dateCheckbox && !dateCheckbox.checked) {
              dateCheckbox.click();
            }
            el.focus();
            el.value = fromDate;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
            touched.push(id);
          } catch (e) {}
        }
        return {ok:touched.length > 0, touched, groupId};
    """
    result = driver.execute_script(js, from_date, status_codes or []) or {}
    _capture_debug(driver, debug_dir, "status_from_date_set")
    if not result.get("ok"):
        raise TimeoutException(f"Unable to set status date ranges from {from_date}. reason={result.get('reason')}")


def _parse_match_count(text: str):
    match = re.search(r"([\d,]+)", str(text or ""))
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _slugify_filename(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return slug or "search"


def _get_visible_match_count(driver):
    try:
        text = driver.execute_script(
            """
            const sels = ['#top_matchesdiv', '#matchesdiv', '#results_totaldiv'];
            for (const sel of sels) {
              const el = document.querySelector(sel);
              if (!el) continue;
              const txt = (el.textContent || '').trim();
              if (txt && txt !== ': 0' && !/Update Count/i.test(txt) && !/loading/i.test(txt)) return txt;
            }
            return '';
            """
        )
        return _parse_match_count(text)
    except Exception:
        return None


def _run_search(driver, wait: WebDriverWait, debug_dir: str):
    # Quick Search in the new Flex shell commonly uses Update Count + View Results
    # rather than a normal submit button.
    initial_count = _get_visible_match_count(driver)

    update_started = False
    try:
        update_started = bool(
            driver.execute_script(
                """
                if (typeof updateMatchCount === 'function') {
                  try { updateMatchCount(); return true; } catch (e) {}
                }
                const sels = ['#topgridlink_updatematches', '#gridlink_updatematches'];
                for (const sel of sels) {
                  const el = document.querySelector(sel);
                  if (!el) continue;
                  try { el.click(); return true; } catch (e) {}
                }
                return false;
                """
            )
        )
    except Exception:
        update_started = False

    update_selectors = [
        (By.ID, "topgridlink_updatematches"),
        (By.ID, "gridlink_updatematches"),
        (By.XPATH, "//a[contains(@onclick,'updateMatchCount')]"),
    ]
    if not update_started:
        for by, sel in update_selectors:
            try:
                btn = WebDriverWait(driver, 5).until(EC.presence_of_element_located((by, sel)))
                try:
                    btn.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", btn)
                update_started = True
                break
            except Exception:
                continue

    # Wait for the match count link to populate before opening results.
    populated = False
    match_count = None
    deadline = time.time() + 45
    while time.time() < deadline:
        match_count = _get_visible_match_count(driver)
        if match_count is not None:
            if initial_count is None or match_count != initial_count or not update_started:
                populated = True
                break
        time.sleep(0.5)
    _capture_debug(driver, debug_dir, "after_update_count")

    def _force_show_results(tag: str) -> bool:
        try:
            jumped = driver.execute_script(
                """
                const countEls = ['#top_matchesdiv', '#matchesdiv']
                  .map(sel => document.querySelector(sel))
                  .filter(Boolean);
                const hasCount = countEls.some(el => {
                  const txt = (el.textContent || '').trim();
                  return txt && txt !== ': 0';
                });
                if (!hasCount || typeof showResults !== 'function') return false;
                try { showResults(); return true; } catch (e) { return false; }
                """
            )
            if jumped:
                return _switch_to_context_with_selector(
                    driver,
                    "#more-ellipses, li#export-listings a, #gridlink_results, #results_totaldiv",
                    timeout_sec=12,
                )
        except Exception:
            pass
        return False

    if _force_show_results("initial"):
        _capture_debug(driver, debug_dir, "after_show_results_js")
        return match_count or _get_visible_match_count(driver)

    result_selectors = [
        (By.ID, "topgridlink_outermatch"),
        (By.ID, "gridlink_outermatch"),
        (By.XPATH, "//a[contains(@onclick,'showResults')]"),
    ]
    for by, sel in result_selectors:
        try:
            btn = wait.until(EC.element_to_be_clickable((by, sel)))
            try:
                btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", btn)
            _capture_debug(driver, debug_dir, "after_view_results_click")
            if _switch_to_context_with_selector(
                driver,
                "#more-ellipses, li#export-listings a, #gridlink_results, #results_totaldiv",
                timeout_sec=12,
            ):
                return match_count or _get_visible_match_count(driver)
            break
        except Exception:
            continue
    else:
        # Legacy fallback: Enter in subdivision field if present.
        field = driver.find_element(By.ID, "t_7")
        field.send_keys(Keys.ENTER)
        _capture_debug(driver, debug_dir, "after_search_enter")
        if _switch_to_context_with_selector(
            driver,
            "#more-ellipses, li#export-listings a, #gridlink_results, #results_totaldiv",
            timeout_sec=12,
        ):
            return match_count or _get_visible_match_count(driver)

    if _force_show_results("retry"):
        _capture_debug(driver, debug_dir, "after_show_results_retry")
        return match_count or _get_visible_match_count(driver)

    wait.until(
        lambda d: _switch_to_context_with_selector(
            d,
            "#more-ellipses, #results_totaldiv, #gridlink_results, li#export-listings a",
            timeout_sec=2,
        )
        or "Search Results" in d.title
    )
    if not populated:
        _capture_debug(driver, debug_dir, "search_results_without_count")
    return match_count or _get_visible_match_count(driver)


def _wait_for_csv(download_dir: str, timeout_sec: int = 180):
    d = Path(download_dir)
    d.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in d.glob("*.csv")}
    before_partial = {p.name: p.stat().st_mtime for p in d.glob("*.crdownload")}
    start_time = time.time()
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        partial = [
            p
            for p in d.glob("*.crdownload")
            if p.name not in before_partial or p.stat().st_mtime >= start_time - 2
        ]
        csvs = sorted(
            [
                p
                for p in d.glob("*.csv")
                if p.name not in before and p.stat().st_mtime >= start_time - 2
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if csvs and not partial:
            return str(csvs[0])
        time.sleep(1.0)
    raise TimeoutException(f"CSV did not download in {download_dir} within {timeout_sec}s")


def _derive_from_date_from_db(db_file: str, cities) -> str:
    city_vals = [str(c).strip().upper() for c in cities if str(c).strip()]
    if not city_vals:
        raise SystemExit("No cities supplied for DB-derived start date.")
    placeholders = ",".join("?" for _ in city_vals)
    q = f"""
        SELECT
          MAX(CASE WHEN DATE(listing_date) <= DATE('now', 'localtime') THEN listing_date END),
          MAX(CASE WHEN DATE(status_change_date) <= DATE('now', 'localtime') THEN status_change_date END),
          MAX(CASE WHEN DATE(under_contract_date) <= DATE('now', 'localtime') THEN under_contract_date END),
          MAX(CASE WHEN DATE(sold_date) <= DATE('now', 'localtime') THEN sold_date END),
          MAX(CASE WHEN DATE(withdrawn_date) <= DATE('now', 'localtime') THEN withdrawn_date END),
          MAX(CASE WHEN DATE(temp_off_market_date) <= DATE('now', 'localtime') THEN temp_off_market_date END),
          MAX(CASE WHEN DATE(cancel_date) <= DATE('now', 'localtime') THEN cancel_date END),
          MAX(CASE WHEN DATE(expiration_date) <= DATE('now', 'localtime') THEN expiration_date END)
        FROM listing_details
        WHERE UPPER(COALESCE(city, '')) IN ({placeholders})
    """
    conn = sqlite3.connect(db_file)
    try:
        row = conn.execute(q, city_vals).fetchone()
    finally:
        conn.close()
    candidates = [v for v in (row or []) if v]
    if not candidates:
        raise SystemExit(f"No existing DB rows found for cities: {', '.join(cities)}")
    max_dt = max(pd.to_datetime(v, errors="coerce") for v in candidates)
    if pd.isna(max_dt):
        raise SystemExit(f"Could not derive a valid start date for cities: {', '.join(cities)}")
    return max_dt.strftime("%m/%d/%Y")


def _should_skip_from_date(cities) -> bool:
    normalized = {str(c).strip().upper() for c in cities if str(c).strip()}
    return bool(normalized) and normalized.issubset(FULL_CITY_REFRESH_CITIES)


def _backup_and_import(csv_files, db_file: str, backup_dir: str) -> Path:
    db_path = Path(db_file)
    if not db_path.exists():
        raise SystemExit(f"DB file not found: {db_file}")
    backup_root = Path(backup_dir)
    backup_root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_root / f"{db_path.stem}_backup_before_quicksearch_import_{ts}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "generate_db.py"),
        "--db-name",
        str(db_path),
        "--skip-archive",
        *[str(Path(path).resolve()) for path in csv_files],
    ]
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False)
    if proc.returncode != 0:
        raise SystemExit(f"CSV import failed with exit code {proc.returncode}")
    return backup_path


def _stamp_authoritative_city(csv_path: str, city: str) -> None:
    """Stamp the city selected in FlexMLS when the export omits that field."""
    path = Path(csv_path)
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except UnicodeDecodeError:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="latin1")
    frame["City"] = str(city).strip()
    frame.to_csv(path, index=False, encoding="utf-8")


def _select_custom_text_export(driver) -> bool:
    """Find and click the Custom Text Export radio button, searching all frames."""
    selectors = [
        (By.CSS_SELECTOR, "input[name='stype'][value='custom']"),
        (By.CSS_SELECTOR, "input[value='type5']"),
        (By.CSS_SELECTOR, "input[name='stype'][value='type5']"),
        (By.CSS_SELECTOR, "#type5"),
        (By.XPATH, "//label[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'custom text export')]"),
        (By.XPATH, "//label[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'type5')]"),
    ]

    def _try_click_in_frame():
        for by, sel in selectors:
            elems = driver.find_elements(by, sel)
            for el in elems:
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                    from selenium.webdriver.common.action_chains import ActionChains
                    ActionChains(driver).move_to_element(el).click().perform()
                except Exception:
                    try:
                        el.click()
                    except Exception:
                        try:
                            driver.execute_script("arguments[0].click();", el)
                        except Exception:
                            continue
                return True
        return False

    # Try current context first.
    if _try_click_in_frame():
        return True

    # Search recursively through iframes.
    def _search_frames(depth=0, max_depth=5):
        if depth >= max_depth:
            return False
        frames = driver.find_elements(By.CSS_SELECTOR, "iframe,frame")
        for fr in frames:
            try:
                driver.switch_to.frame(fr)
                if _try_click_in_frame():
                    return True
                if _search_frames(depth + 1, max_depth):
                    return True
                driver.switch_to.parent_frame()
            except Exception:
                try:
                    driver.switch_to.parent_frame()
                except Exception:
                    pass
        return False

    original = driver.current_window_handle
    driver.switch_to.default_content()
    if _search_frames():
        return True
    driver.switch_to.window(original)

    # Aggressive fallback: find ANY label containing "custom text" or "type5" and click it via JS.
    js = """
        const labels = Array.from(document.querySelectorAll('label, div, span, li'));
        const target = labels.find(l => {
            const text = (l.textContent || '').toLowerCase();
            return text.includes('custom text export') || text.includes('custom text') && text.includes('type5');
        });
        if (target) {
            target.click();
            return true;
        }
        const inputs = Array.from(document.querySelectorAll('input[type=\"radio\"]'));
        const input5 = inputs.find(i => {
            const val = (i.value || '').toLowerCase();
            const id = (i.id || '').toLowerCase();
            return val === 'type5' || val === 'custom' || id === 'type5';
        });
        if (input5) {
            input5.checked = true;
            input5.click();
            input5.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }
        return false;
    """
    return bool(driver.execute_script(js))


def _select_export_template(driver, template_name: str) -> None:
    if not template_name:
        return
    select_el = driver.find_element(By.CSS_SELECTOR, "select[name='template_id']")
    select = Select(select_el)
    try:
        select.select_by_visible_text(template_name)
        return
    except NoSuchElementException:
        pass

    def normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    requested = normalize(template_name)
    options = [(opt, (opt.text or "").strip(), normalize(opt.text or "")) for opt in select.options]
    for opt, _label, normalized in options:
        if normalized == requested:
            opt.click()
            return

    ai_data_options = [(opt, label) for opt, label, normalized in options if "ai" in normalized and "data" in normalized]
    if ai_data_options and "ai" in requested and "data" in requested:
        ai_data_options[0][0].click()
        print(f"Selected export template '{ai_data_options[0][1]}' as fallback for '{template_name}'", flush=True)
        return

    data_options = [(opt, label) for opt, label, normalized in options if "data" in normalized]
    if data_options and "data" in requested:
        data_options[0][0].click()
        print(f"Selected export template '{data_options[0][1]}' as fallback for '{template_name}'", flush=True)
        return

    available = [label for _opt, label, _normalized in options]
    raise NoSuchElementException(
        f"Could not locate export template '{template_name}'. Available templates: {available}"
    )


def _force_custom_export_mode(driver) -> bool:
    """Verify Custom Text Export is selected, searching all frames."""
    def _check_frame():
        js = """
            const custom = document.querySelector("input[name='stype'][value='custom']") 
                || document.querySelector("input[value='type5']")
                || document.querySelector("input[name='stype'][value='type5']")
                || document.querySelector("#type5");
            const exportId = document.querySelector("input[name='export_id']");
            if (custom) {
              custom.checked = true;
              custom.click();
              custom.dispatchEvent(new Event('input', { bubbles: true }));
              custom.dispatchEvent(new Event('change', { bubbles: true }));
            }
            if (exportId) exportId.value = "type5";
            const checked = Array.from(document.querySelectorAll("input[name='stype']")).find(el => el.checked)
                || Array.from(document.querySelectorAll("input[type='radio']")).find(el => el.checked);
            const isCustom = !!(custom && custom.checked) || !!(checked && (
                checked.value === 'custom' || checked.value === 'type5' || checked.id === 'type5'
            ));
            return isCustom;
        """
        return bool(driver.execute_script(js))

    if _check_frame():
        return True

    # Search through iframes.
    def _search_frames(depth=0, max_depth=5):
        if depth >= max_depth:
            return False
        frames = driver.find_elements(By.CSS_SELECTOR, "iframe,frame")
        for fr in frames:
            try:
                driver.switch_to.frame(fr)
                if _check_frame():
                    return True
                if _search_frames(depth + 1, max_depth):
                    return True
                driver.switch_to.parent_frame()
            except Exception:
                try:
                    driver.switch_to.parent_frame()
                except Exception:
                    pass
        return False

    driver.switch_to.default_content()
    return _search_frames()


def _wait_for_export_dialog(driver, timeout_sec=90) -> bool:
    selectors = [
        "label[for='type5']",
        "#type5",
        "input[name='stype'][value='custom']",
        "select[name='template_id']",
        "button[type='submit']",
        "button.g-recaptcha.btn.btn-primary",
    ]
    if _switch_to_context_with_selector(driver, selectors[0], timeout_sec=0):
        return True

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        driver.switch_to.default_content()
        for selector in selectors:
            if _switch_to_context_with_selector(driver, selector, timeout_sec=1):
                return True
        time.sleep(1)
    return False


def _wait_for_export_page(driver, timeout_sec=12) -> bool:
    deadline = time.time() + timeout_sec
    heading_xpath = "//*[contains(normalize-space(.), 'Export Flexmls Data to Other Software')]"

    while time.time() < deadline:
        try:
            if driver.find_elements(By.XPATH, heading_xpath):
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _run_new_export_page(driver, wait: WebDriverWait, export_template: str | None = None, debug_dir: str = "", timeout_sec: int = 30) -> bool:
    deadline = time.time() + timeout_sec
    heading_xpath = "//*[contains(normalize-space(.), 'Export Flexmls Data to Other Software')]"

    while time.time() < deadline:
        try:
            if driver.find_elements(By.XPATH, heading_xpath):
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        return False

    _capture_debug(driver, debug_dir, "new_export_page")

    custom_selected = False
    try:
        for by, sel in [
            (By.CSS_SELECTOR, "label[for='type5']"),
            (By.ID, "type5"),
            (By.XPATH, "//label[contains(normalize-space(.), 'Custom Text Export')]"),
        ]:
            try:
                wait.until(EC.element_to_be_clickable((by, sel))).click()
                break
            except Exception:
                continue
    except Exception:
        pass

    try:
        custom_selected = bool(
            driver.execute_script(
                """
                const radio = document.querySelector('#type5');
                const label = document.querySelector("label[for='type5']");
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
    except Exception:
        custom_selected = False

    _capture_debug(driver, debug_dir, "custom_text_export_new_page")
    if not custom_selected:
        raise TimeoutException("Custom Text Export (type5) did not become selected on the export page.")

    if export_template:
        try:
            select_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "select")))
            try:
                Select(select_el).select_by_visible_text(export_template)
            except Exception:
                pass
        except Exception:
            pass

    for by, sel in [
        (By.CSS_SELECTOR, "button.g-recaptcha.btn.btn-primary[type='submit']"),
        (By.XPATH, "//button[normalize-space()='EXPORT' or contains(normalize-space(.), 'EXPORT')]"),
        (By.XPATH, "//input[@type='submit' and (@value='EXPORT' or @value='Export')]"),
    ]:
        try:
            wait.until(EC.element_to_be_clickable((by, sel))).click()
            _capture_debug(driver, debug_dir, "new_export_page_submit")
            return True
        except Exception:
            continue
    raise TimeoutException("Could not submit new export page.")


def _submit_export_form_fallback(driver, export_template: str | None = None, debug_dir: str = "") -> bool:
    js = """
        const exportTemplate = arguments[0];
        const resultsNode = document.querySelector('#results_totaldiv');
        const selectedNode = document.querySelector('#cart_totaldiv');
        const exportForm = document.forms['exportform'];
        if (!exportForm) {
          return {ok: false, reason: 'missing_exportform'};
        }

        const resultsText = resultsNode ? (resultsNode.textContent || '') : '';
        const selectedText = selectedNode ? (selectedNode.textContent || '') : '';
        const countAll = parseInt(resultsText.replace(/[^0-9]/g, ''), 10) || 0;
        const countSelected = parseInt(selectedText.replace(/[^0-9]/g, ''), 10) || 0;
        const whereValue =
          (typeof results_allwherestr !== 'undefined' && results_allwherestr) ||
          (typeof allwherestr !== 'undefined' && allwherestr) ||
          '';
        const additional =
          (typeof additionalcond !== 'undefined' && additionalcond) ||
          '';

        if (!whereValue) {
          return {
            ok: false,
            reason: 'missing_results_context',
            count_all: countAll,
            count_selected: countSelected,
            where_present: !!whereValue
          };
        }

        const ensure = (name, value) => {
          let el = exportForm.querySelector(`[name="${name}"]`);
          if (!el) {
            el = document.createElement('input');
            el.type = 'hidden';
            el.name = name;
            exportForm.appendChild(el);
          }
          el.value = value;
        };

        ensure('where', whereValue);
        ensure('additionalcond', additional);
        ensure('countall', String(Math.max(countAll, countSelected, 0)));
        ensure('countselected', String(Math.max(countSelected, 0)));
        ensure('showonlyselectedoption', 'false');

        if (exportTemplate) {
          const templateSelect =
            document.querySelector("select[name='template_id']") ||
            exportForm.querySelector("[name='template_id']");
          if (templateSelect && templateSelect.options) {
            const options = Array.from(templateSelect.options);
            const match = options.find(opt => (opt.textContent || '').trim() === exportTemplate);
            if (match) {
              templateSelect.value = match.value;
              ensure('template_id', match.value);
            }
          }
        }

        exportForm.submit();
        return { ok: true, count_all: countAll, count_selected: countSelected, where_present: true };
    """
    state = driver.execute_script(js, export_template) or {}
    _capture_debug(driver, debug_dir, "export_form_fallback")
    return bool(state.get("ok"))


def _prepare_export_form_fallback(driver, export_template: str | None = None) -> dict:
    js = """
        const exportTemplate = arguments[0];
        const resultsNode = document.querySelector('#results_totaldiv');
        const selectedNode = document.querySelector('#cart_totaldiv');
        const exportForm = document.forms['exportform'];
        if (!exportForm) {
          return {ok: false, reason: 'missing_exportform'};
        }

        const resultsText = resultsNode ? (resultsNode.textContent || '') : '';
        const selectedText = selectedNode ? (selectedNode.textContent || '') : '';
        const countAll = parseInt(resultsText.replace(/[^0-9]/g, ''), 10) || 0;
        const countSelected = parseInt(selectedText.replace(/[^0-9]/g, ''), 10) || 0;
        const whereValue =
          (typeof results_allwherestr !== 'undefined' && results_allwherestr) ||
          (typeof allwherestr !== 'undefined' && allwherestr) ||
          '';
        const additional =
          (typeof additionalcond !== 'undefined' && additionalcond) ||
          '';

        if (!whereValue) {
          return {
            ok: false,
            reason: 'missing_results_context',
            count_all: countAll,
            count_selected: countSelected,
            where_present: false
          };
        }

        const ensure = (name, value) => {
          let el = exportForm.querySelector(`[name="${name}"]`);
          if (!el) {
            el = document.createElement('input');
            el.type = 'hidden';
            el.name = name;
            exportForm.appendChild(el);
          }
          el.value = value;
        };

        ensure('where', whereValue);
        ensure('additionalcond', additional);
        ensure('countall', String(Math.max(countAll, countSelected, 0)));
        ensure('countselected', String(Math.max(countSelected, 0)));
        ensure('showonlyselectedoption', 'false');

        if (exportTemplate) {
          const templateSelect =
            document.querySelector("select[name='template_id']") ||
            exportForm.querySelector("[name='template_id']");
          if (templateSelect && templateSelect.options) {
            const options = Array.from(templateSelect.options);
            const match = options.find(opt => (opt.textContent || '').trim() === exportTemplate);
            if (match) {
              templateSelect.value = match.value;
              ensure('template_id', match.value);
            }
          }
        }

        const fields = [];
        for (const el of Array.from(exportForm.querySelectorAll('input, select, textarea'))) {
          if (!el.name || el.disabled) continue;
          const tag = (el.tagName || '').toLowerCase();
          const type = (el.type || '').toLowerCase();
          if ((type === 'checkbox' || type === 'radio') && !el.checked) continue;
          if (tag === 'select' && el.multiple) {
            for (const opt of Array.from(el.selectedOptions || [])) {
              fields.push([el.name, opt.value]);
            }
            continue;
          }
          fields.push([el.name, el.value || '']);
        }

        return {
          ok: true,
          action: exportForm.getAttribute('action') || exportForm.action || '',
          method: (exportForm.getAttribute('method') || exportForm.method || 'POST').toUpperCase(),
          count_all: countAll,
          count_selected: countSelected,
          where_present: true,
          fields
        };
    """
    return driver.execute_script(js, export_template) or {}


def _write_debug_response(debug_dir: str, step: str, content: bytes) -> Path | None:
    if not debug_dir:
        return None
    Path(debug_dir).mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", step)[:80]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = Path(debug_dir) / f"{ts}_{safe}.html"
    path.write_bytes(content)
    return path


def _filename_from_content_disposition(value: str) -> str:
    if not value:
        return ""
    match = re.search(r"filename\\*?=(?:UTF-8''|\"?)([^\";]+)", value, flags=re.I)
    if not match:
        return ""
    return Path(match.group(1).strip()).name


class _ExportOptionsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.form_action = ""
        self.in_export_form = False
        self.current_select = ""
        self.options: dict[str, list[tuple[str, str]]] = {}
        self.fields: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = {name.lower(): (value or "") for name, value in attrs}
        tag = tag.lower()
        if tag == "form":
            form_id = attrs_dict.get("id", "")
            form_name = attrs_dict.get("name", "")
            if form_id == "my_export_form" or form_name in {"export_form", "exp_form"}:
                self.in_export_form = True
                self.form_action = attrs_dict.get("action", "")
        if not self.in_export_form:
            return

        if tag == "input":
            name = attrs_dict.get("name", "")
            if not name:
                return
            input_type = attrs_dict.get("type", "").lower()
            if input_type in {"radio", "checkbox"} and "checked" not in attrs_dict:
                return
            self.fields.append((name, attrs_dict.get("value", "")))
        elif tag == "select":
            self.current_select = attrs_dict.get("name", "")
            if self.current_select:
                self.options.setdefault(self.current_select, [])
        elif tag == "option" and self.current_select:
            self.options.setdefault(self.current_select, []).append((attrs_dict.get("value", ""), ""))

    def handle_data(self, data):
        if self.in_export_form and self.current_select and self.options.get(self.current_select):
            value, label = self.options[self.current_select][-1]
            self.options[self.current_select][-1] = (value, f"{label}{data}")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "select":
            self.current_select = ""
        elif tag == "form" and self.in_export_form:
            self.in_export_form = False


def _set_form_field(fields: list[tuple[str, str]], name: str, value: str) -> list[tuple[str, str]]:
    cleaned = [(key, existing) for key, existing in fields if key != name]
    cleaned.append((name, value))
    return cleaned


def _post_form(
    url: str,
    fields: list[tuple[str, str]],
    headers: dict[str, str],
    timeout_sec: int,
) -> tuple[int, str, str, str, bytes]:
    request = Request(url, data=urlencode(fields).encode("utf-8"), headers=headers, method="POST")
    with urlopen(request, timeout=timeout_sec) as response:
        content = response.read()
        return (
            getattr(response, "status", 200),
            response.headers.get("Content-Type", ""),
            response.headers.get("Content-Disposition", ""),
            response.geturl(),
            content,
        )


def _build_export_headers(driver, url: str) -> dict[str, str]:
    cookies = "; ".join(
        f"{cookie.get('name')}={cookie.get('value')}"
        for cookie in driver.get_cookies()
        if cookie.get("name") and cookie.get("value") is not None
    )
    try:
        user_agent = driver.execute_script("return navigator.userAgent") or "Mozilla/5.0"
    except Exception:
        user_agent = "Mozilla/5.0"

    headers = {
        "User-Agent": user_agent,
        "Referer": driver.current_url,
        "Origin": urljoin(url, "/").rstrip("/"),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/csv,application/octet-stream,text/plain,*/*",
    }
    if cookies:
        headers["Cookie"] = cookies
    return headers


def _write_export_content(download_dir: str, disposition: str, content: bytes) -> str:
    filename = _filename_from_content_disposition(disposition)
    if not filename or not filename.lower().endswith(".csv"):
        filename = f"flexmls_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    output_path = Path(download_dir) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path = output_path.with_name(
            f"{output_path.stem}_{datetime.now().strftime('%H%M%S')}{output_path.suffix}"
        )
    output_path.write_bytes(content)
    return str(output_path)


def _download_export_form_fallback(
    driver,
    download_dir: str,
    export_template: str | None = None,
    debug_dir: str = "",
    timeout_sec: int = 180,
) -> str:
    state = _prepare_export_form_fallback(driver, export_template=export_template)
    _capture_debug(driver, debug_dir, "export_form_direct_post_prepared")
    if not state.get("ok"):
        raise TimeoutException(f"Export form direct post was not prepared: {state}")

    raw_fields = state.get("fields") or []
    fields = [
        (str(field[0]), "" if field[1] is None else str(field[1]))
        for field in raw_fields
        if isinstance(field, (list, tuple)) and len(field) == 2 and field[0]
    ]
    if not fields:
        raise TimeoutException(f"Export form direct post had no fields: {state}")

    action = state.get("action") or "/flexmls-servlets/sservlet/TextExport"
    url = urljoin(driver.current_url, action)
    headers = _build_export_headers(driver, url)
    try:
        status, content_type, disposition, response_url, content = _post_form(url, fields, headers, timeout_sec)
    except HTTPError as exc:
        content = exc.read()
        debug_path = _write_debug_response(debug_dir, "export_direct_post_http_error", content)
        raise TimeoutException(
            f"Export direct POST failed with HTTP {exc.code}; debug_response={debug_path}"
        ) from exc
    except URLError as exc:
        raise TimeoutException(f"Export direct POST failed: {exc}") from exc

    preview = content[:2048].lower()
    looks_html = b"<html" in preview or b"<!doctype html" in preview
    if status >= 400 or looks_html:
        text = content.decode("utf-8", errors="replace")
        parser = _ExportOptionsParser()
        parser.feed(text)
        if status < 400 and parser.form_action:
            final_fields = parser.fields
            final_fields = _set_form_field(final_fields, "stype", "custom")
            final_fields = _set_form_field(final_fields, "export_id", "type5")
            final_fields = _set_form_field(final_fields, "export_count", "all")

            template_value = ""
            if export_template:
                requested = re.sub(r"[^a-z0-9]+", "", export_template.lower())
                for value, label in parser.options.get("template_id", []):
                    normalized = re.sub(r"[^a-z0-9]+", "", label.lower())
                    if normalized == requested:
                        template_value = value
                        break
            if not template_value and parser.options.get("template_id"):
                template_value = parser.options["template_id"][0][0]
            if template_value:
                final_fields = _set_form_field(final_fields, "template_id", template_value)

            summary_url = urljoin(response_url, parser.form_action)
            summary_headers = dict(headers)
            summary_headers["Referer"] = response_url
            summary_headers["Origin"] = urljoin(summary_url, "/").rstrip("/")
            try:
                summary_status, summary_type, summary_disposition, summary_url_final, summary_content = _post_form(
                    summary_url,
                    final_fields,
                    summary_headers,
                    timeout_sec,
                )
            except HTTPError as exc:
                error_content = exc.read()
                debug_path = _write_debug_response(debug_dir, "export_summary_post_http_error", error_content)
                raise TimeoutException(
                    f"Export Summary POST failed with HTTP {exc.code}; debug_response={debug_path}"
                ) from exc
            except URLError as exc:
                raise TimeoutException(f"Export Summary POST failed: {exc}") from exc

            summary_preview = summary_content[:2048].lower()
            summary_looks_html = b"<html" in summary_preview or b"<!doctype html" in summary_preview
            if summary_status < 400 and not summary_looks_html:
                return _write_export_content(download_dir, summary_disposition, summary_content)

            download_parser = _ExportOptionsParser()
            download_parser.feed(summary_content.decode("utf-8", errors="replace"))
            if summary_status < 400 and download_parser.form_action and download_parser.fields:
                custom_url = urljoin(summary_url_final, download_parser.form_action)
                custom_headers = dict(headers)
                custom_headers["Referer"] = summary_url_final
                custom_headers["Origin"] = urljoin(custom_url, "/").rstrip("/")
                try:
                    custom_status, custom_type, custom_disposition, _custom_url, custom_content = _post_form(
                        custom_url,
                        download_parser.fields,
                        custom_headers,
                        timeout_sec,
                    )
                except HTTPError as exc:
                    error_content = exc.read()
                    debug_path = _write_debug_response(debug_dir, "export_custom_post_http_error", error_content)
                    raise TimeoutException(
                        f"Export CustomExport POST failed with HTTP {exc.code}; debug_response={debug_path}"
                    ) from exc
                except URLError as exc:
                    raise TimeoutException(f"Export CustomExport POST failed: {exc}") from exc

                custom_preview = custom_content[:2048].lower()
                custom_looks_html = b"<html" in custom_preview or b"<!doctype html" in custom_preview
                if custom_status < 400 and not custom_looks_html:
                    return _write_export_content(download_dir, custom_disposition, custom_content)

                debug_path = _write_debug_response(debug_dir, "export_custom_post_html_response", custom_content)
                custom_text = custom_content[:500].decode("utf-8", errors="replace").replace("\n", " ")
                raise TimeoutException(
                    f"Export CustomExport POST returned non-CSV response status={custom_status} "
                    f"content_type={custom_type!r}; debug_response={debug_path}; preview={custom_text!r}"
                )

            debug_path = _write_debug_response(debug_dir, "export_summary_post_html_response", summary_content)
            summary_text = summary_content[:500].decode("utf-8", errors="replace").replace("\n", " ")
            raise TimeoutException(
                f"Export Summary POST returned non-CSV response status={summary_status} "
                f"content_type={summary_type!r}; debug_response={debug_path}; preview={summary_text!r}"
            )

        debug_path = _write_debug_response(debug_dir, "export_direct_post_html_response", content)
        text = content[:500].decode("utf-8", errors="replace").replace("\n", " ")
        raise TimeoutException(
            f"Export direct POST returned non-CSV response status={status} "
            f"content_type={content_type!r}; debug_response={debug_path}; preview={text!r}"
        )

    return _write_export_content(download_dir, disposition, content)


def _export_current_results(
    driver,
    wait: WebDriverWait,
    debug_dir: str,
    download_dir: str,
    export_template: str,
    download_timeout: int,
) -> str:
    # Full export flow: open export menu, prefer export page/direct form submit, then fall back to legacy modal.
    if not _switch_to_context_with_selector(driver, "#more-ellipses", timeout_sec=15):
        _capture_debug(driver, debug_dir, "export_menu_not_found")
        raise TimeoutException("More menu not found for export")

    for by, sel in [
        (By.CSS_SELECTOR, "#more-ellipses a.filemenu[title='More']"),
        (By.CSS_SELECTOR, "#more-ellipses a.dropdown-trigger"),
        (By.CSS_SELECTOR, "#more-ellipses .filemenu"),
    ]:
        try:
            wait.until(EC.element_to_be_clickable((by, sel))).click()
            break
        except Exception:
            continue

    for by, sel in [
        (By.CSS_SELECTOR, "li#export-listings a[title='Export Listings']"),
        (By.CSS_SELECTOR, "li#export-listings a"),
        (By.XPATH, "//li[@id='export-listings']//a[contains(normalize-space(.), 'Export')]"),
    ]:
        try:
            wait.until(EC.element_to_be_clickable((by, sel))).click()
            time.sleep(1.5)
            _capture_debug(driver, debug_dir, "export_opened")
            break
        except Exception:
            continue
    else:
        _capture_debug(driver, debug_dir, "export_click_failed")
        raise TimeoutException("Could not open Export Listings dialog")

    if _wait_for_export_page(driver, timeout_sec=8):
        if _run_new_export_page(
            driver,
            wait,
            export_template=export_template,
            debug_dir=debug_dir,
            timeout_sec=10,
        ):
            return _wait_for_csv(download_dir=download_dir, timeout_sec=download_timeout)

    try:
        return _download_export_form_fallback(
            driver,
            download_dir=download_dir,
            export_template=export_template,
            debug_dir=debug_dir,
            timeout_sec=download_timeout,
        )
    except TimeoutException as exc:
        print(f"  export_direct_post_fallback_failed={exc}", flush=True)

    if _submit_export_form_fallback(driver, export_template=export_template, debug_dir=debug_dir):
        return _wait_for_csv(download_dir=download_dir, timeout_sec=download_timeout)

    if not _wait_for_export_dialog(driver, timeout_sec=30):
        raise TimeoutException("Export dialog did not finish loading known controls.")

    if not _select_custom_text_export(driver):
        _capture_debug(driver, debug_dir, "custom_text_export_failed")
        raise TimeoutException("Could not select Custom Text Export (type5)")
    _capture_debug(driver, debug_dir, "custom_text_export")

    _select_export_template(driver, export_template)
    if not _force_custom_export_mode(driver):
        raise TimeoutException("Unable to force Custom Text Export mode")
    _capture_debug(driver, debug_dir, "custom_mode_verified")

    for by, sel in [
        (By.CSS_SELECTOR, "button[type='submit']"),
        (By.CSS_SELECTOR, "button.g-recaptcha.btn.btn-primary"),
        (By.XPATH, "//button[contains(normalize-space(.), 'Export')]"),
    ]:
        try:
            wait.until(EC.element_to_be_clickable((by, sel))).click()
            _capture_debug(driver, debug_dir, "final_export_click")
            return _wait_for_csv(download_dir=download_dir, timeout_sec=download_timeout)
        except Exception:
            continue
    raise TimeoutException("Final Export button click failed")


def parse_args():
    p = argparse.ArgumentParser(description="Run Flexmls Quick Search from CMA subdivision list.")
    p.add_argument("--query-csv", help="cma_sales_queries_*.csv from cma.py")
    p.add_argument("--email", default=os.getenv("MLS_EMAIL"))
    p.add_argument("--password", default=os.getenv("MLS_PASSWORD"))
    p.add_argument("--download-dir", default="output/mls_exports")
    p.add_argument("--download-timeout", type=int, default=180)
    p.add_argument("--debug-dir", default="output/mls_debug")
    p.add_argument("--headless", action="store_true")
    p.add_argument(
        "--chromedriver-port",
        type=int,
        default=9515,
        help="Preferred local port for the ChromeDriver service; falls back to nearby ports if needed.",
    )
    p.add_argument("--max-subdivisions", type=int, default=1, help="How many subdivision searches to run")
    p.add_argument(
        "--search-name-mode",
        choices=["unified-first", "official-only", "unified-only"],
        default="unified-first",
        help="How to build subdivision search terms from query CSV.",
    )
    p.add_argument(
        "--status-mode",
        choices=["all", "closed-only", "active-only"],
        default="all",
        help="MLS status selection for Quick Search.",
    )
    p.add_argument(
        "--export-each-search",
        action="store_true",
        help="Run full export (Custom Text Export + template + CSV download) after each search.",
    )
    p.add_argument(
        "--export-template",
        default="AI Full DataSet",
        help="Template visible text for Custom Text Export (select[name='template_id'])",
    )
    p.add_argument(
        "--max-export-records",
        type=int,
        default=MAX_EXPORT_RECORDS,
        help="Fail before export if a Quick Search count is above this many records.",
    )
    p.add_argument(
        "--cities",
        default="",
        help="Comma-separated city list for Quick Search city mode, e.g. 'Palm Beach,Wellington'.",
    )
    p.add_argument(
        "--search-mode",
        choices=["subdivision", "city"],
        default="subdivision",
        help="Whether to drive Quick Search by subdivision terms or direct city selection.",
    )
    p.add_argument(
        "--from-date",
        default="",
        help="Apply this start date to the status date filters, e.g. 03/03/2026.",
    )
    p.add_argument(
        "--derive-from-db",
        action="store_true",
        help="Derive --from-date from the latest date already present in the DB for the selected city/cities.",
    )
    p.add_argument(
        "--db-file",
        default="mls.db",
        help="SQLite DB used for deriving city cutoff dates and optional imports.",
    )
    p.add_argument(
        "--import-to-db",
        action="store_true",
        help="Import downloaded CSVs into --db-file after export completes.",
    )
    p.add_argument(
        "--backup-dir",
        default="tmp",
        help="Directory for DB backups before --import-to-db runs.",
    )
    return p.parse_args()


def _pick_chromedriver_port(preferred_port: int, attempts: int = 10) -> int:
    for offset in range(max(attempts, 1)):
        port = preferred_port + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _build_search_terms(df: pd.DataFrame, mode: str):
    def _clean(vals):
        out = []
        seen = set()
        for v in vals:
            s = str(v or "").strip()
            if not s:
                continue
            key = s.upper()
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
        return out

    unified = _clean(df.get("unified_subdivision", pd.Series(dtype=str)).tolist())
    official = _clean(df.get("official_subdivision_name", pd.Series(dtype=str)).tolist())

    terms = []
    if mode == "unified-only":
        terms = [{"name": s, "source": "unified_subdivision"} for s in unified]
    elif mode == "official-only":
        terms = [{"name": s, "source": "official_subdivision_name"} for s in official]
    else:
        terms = [{"name": s, "source": "unified_subdivision"} for s in unified]
        used = {t["name"].upper() for t in terms}
        for s in official:
            if s.upper() not in used:
                terms.append({"name": s, "source": "official_subdivision_name"})
                used.add(s.upper())
    return terms


def main():
    _bootstrap_mls_env()
    args = parse_args()
    email = args.email or input("MLS email: ").strip()
    password = args.password or getpass.getpass("MLS password: ").strip()
    if not email or not password:
        raise SystemExit("Email/password required.")

    if args.search_mode == "city":
        city_terms = [c.strip() for c in args.cities.split(",") if c.strip()]
        if not city_terms:
            raise SystemExit("--cities is required when --search-mode city.")
        search_terms = [{"name": city, "source": "city", "cities": [city]} for city in city_terms]
    else:
        if not args.query_csv:
            raise SystemExit("--query-csv is required when --search-mode subdivision.")
        q = pd.read_csv(args.query_csv, dtype=str).fillna("")
        search_terms = _build_search_terms(q, args.search_name_mode)
        if args.max_subdivisions > 0:
            search_terms = search_terms[: args.max_subdivisions]
        if not search_terms:
            raise SystemExit("No subdivision rows found in query CSV.")

    if args.derive_from_db:
        if args.search_mode != "city":
            raise SystemExit("--derive-from-db currently supports --search-mode city only.")
        if args.from_date:
            raise SystemExit("Use either --from-date or --derive-from-db, not both.")
        for row in search_terms:
            if _should_skip_from_date(row["cities"]):
                row["from_date"] = ""
                print(f"derived_from_date[{row['name']}]=SKIPPED_FULL_CITY_REFRESH")
            else:
                row["from_date"] = _derive_from_date_from_db(args.db_file, row["cities"])
                print(f"derived_from_date[{row['name']}]={row['from_date']}")
    elif args.from_date:
        for row in search_terms:
            row["from_date"] = args.from_date

    status_map = {
        "all": ALL_STATUS_CODES,
        "closed-only": ["C"],
        "active-only": ["A"],
    }
    status_codes = status_map[args.status_mode]

    Path(args.download_dir).mkdir(parents=True, exist_ok=True)
    Path(args.debug_dir).mkdir(parents=True, exist_ok=True)

    options = webdriver.ChromeOptions()
    if args.headless:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1502,900")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(Path(args.download_dir).resolve()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        },
    )

    service_port = _pick_chromedriver_port(args.chromedriver_port)
    print(f"chromedriver_port={service_port}")
    driver = webdriver.Chrome(service=Service(port=service_port), options=options)
    try:
        driver.execute_cdp_cmd(
            "Page.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": str(Path(args.download_dir).resolve())},
        )
    except Exception:
        pass
    wait = WebDriverWait(driver, 30)
    exported_csvs = []
    try:
        login(driver, wait, email=email, password=password, debug_dir=args.debug_dir)
        for i, row in enumerate(search_terms, start=1):
            source = row["source"]
            print(f"[{i}/{len(search_terms)}] Quick Search ({source}): {row['name']}")
            _open_quick_search(driver, wait, args.debug_dir)
            _ensure_residential_view(driver, wait, args.debug_dir)
            _set_status_values(driver, status_codes, args.debug_dir)
            from_date = row.get("from_date", args.from_date)
            if from_date:
                _set_status_from_date(driver, from_date, args.debug_dir, status_codes=status_codes)
            if args.search_mode == "city":
                _set_city_values(driver, row["cities"], args.debug_dir)
            else:
                subdivision = row["name"].strip()
                _set_subdivision_value(driver, subdivision, args.debug_dir)
            match_count = _run_search(driver, wait, args.debug_dir)
            if match_count is not None:
                print(f"  match_count={match_count}")
            time.sleep(2.0)
            if args.export_each_search:
                if match_count is not None and match_count > args.max_export_records:
                    raise TimeoutException(
                        f"Search '{row['name']}' returned {match_count:,} records, above export limit "
                        f"{args.max_export_records:,}. Split this search before exporting."
                    )
                csv_path = _export_current_results(
                    driver=driver,
                    wait=wait,
                    debug_dir=args.debug_dir,
                    download_dir=args.download_dir,
                    export_template=args.export_template,
                    download_timeout=args.download_timeout,
                )
                downloaded = Path(csv_path)
                unique_csv = downloaded.with_name(f"{i:02d}_{_slugify_filename(row['name'])}_{downloaded.name}")
                if downloaded != unique_csv:
                    if unique_csv.exists():
                        unique_csv.unlink()
                    shutil.move(str(downloaded), str(unique_csv))
                    csv_path = str(unique_csv)
                print(f"  export_csv={csv_path}")
                if args.search_mode == "city":
                    _stamp_authoritative_city(csv_path, row["cities"][0])
                exported_csvs.append(csv_path)

        print("Quick Search run completed.")
    finally:
        driver.quit()

    if args.import_to_db:
        if not exported_csvs:
            raise SystemExit("--import-to-db requires at least one exported CSV. Add --export-each-search.")
        backup_path = _backup_and_import(exported_csvs, args.db_file, args.backup_dir)
        print(f"db_backup={backup_path}")


if __name__ == "__main__":
    main()
