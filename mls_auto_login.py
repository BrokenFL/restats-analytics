import argparse
import getpass
import os
import time

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

LOGIN_URL = (
    os.getenv("MLS_LOGIN_URL")
    or "https://beachesmls.mysolidearth.com/authenticate?"
    "redirect_to=eyJwYXJhbXMiOnt9LCJuYW1lIjoib2F1dGguYXV0aG9yaXplIiwicXVlcnkiOnsi"
    "Y2xpZW50X2lkIjoiVHdGMUQ1TVFxbGZDdnVJZzJSazdVTktLNHYzV0xtVy1lTjZ6ZUZicmhf"
    "YyIsIm5vbmNlIjoiYjVkODMwYmY1YjNiYjBkZmJlYzc1MjljYWIxMjVmMGEiLCJyZWRpcmVj"
    "dF91cmkiOiJodHRwczovL2Zsci5mbGV4bWxzLmNvbS9vcGVuaWRfcnAvY2FsbGJhY2siLCJy"
    "ZXNwb25zZV90eXBlIjoiY29kZSIsInNjb3BlIjoiZW1haWwgcHJvZmlsZSBvcGVuaWQifX0%3D"
)
LOGIN_HOST_HINTS = ("mysolidearth.com", "authenticate")
SUCCESS_HOST_HINTS = ("flexmls.com", "apps.flexmls.com")


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
        except TimeoutException:
            continue
    raise TimeoutException(f"No clickable element found for selectors: {selectors}")


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


def _select_email_mode(driver, timeout_sec: int = 45) -> None:
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
                    if driver.find_elements(By.CSS_SELECTOR, "input[name='email'][type='email'], input[type='email'], input[aria-label='Email']"):
                        return
        except Exception:
            continue

    js = """
        const visible = (el) => !!(el && el.offsetParent !== null);
        const clickish = (el) => { try { el.click(); return true; } catch (e) { return false; } };
        const emailInput = document.querySelector("input[name='email'][type='email'], input[type='email'], input[aria-label='Email']");
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
          emailVisible: visible(document.querySelector("input[name='email'][type='email'], input[type='email'], input[aria-label='Email']")),
          mlsVisible: visible(document.querySelector("input[name='member_login_id'], input[aria-label='MLS Username']")),
        };
    """
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        state = driver.execute_script(js) or {}
        if state.get("ready") or (state.get("emailVisible") and not state.get("mlsVisible")):
            return
        time.sleep(0.5)
    raise TimeoutException("Could not switch login page into Email mode.")


def _wait_for_email_login_fields(driver, timeout_sec: int = 20) -> None:
    deadline = time.time() + timeout_sec
    email_selectors = ["input[name='email'][type='email']", "input[type='email']", "input[aria-label='Email']"]
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


def _fill_identity_fields(driver, value: str) -> None:
    selectors = [
        "input[name='email'][type='email']",
        "input[type='email']",
        "input[aria-label='Email']",
    ]
    for sel in selectors:
        for field in driver.find_elements(By.CSS_SELECTOR, sel):
            try:
                if field.is_displayed() and field.is_enabled():
                    try:
                        field.clear()
                    except Exception:
                        pass
                    field.send_keys(value)
                    return
            except Exception:
                continue
    if not _set_value_via_js(driver, selectors, value):
        raise TimeoutException("Could not fill email field.")


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
            for field in fields:
                try:
                    if field.is_displayed() and field.is_enabled():
                        field.send_keys(password)
                        return
                except Exception:
                    continue
        if _set_value_via_js(driver, selectors, password):
            return
        time.sleep(0.5)
    raise TimeoutException("Could not fill password field.")


def login(username, email, password, headless=False, timeout=30, stay_open_seconds=10):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1502,808")

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, timeout)

    try:
        driver.get(LOGIN_URL)

        _wait_for_auth_form(driver, timeout_sec=timeout)
        _select_email_mode(driver, timeout_sec=timeout)
        _wait_for_email_login_fields(driver, timeout_sec=min(timeout, 20))
        _fill_identity_fields(driver, email)
        _fill_password(driver, password, timeout_sec=timeout)

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
        login_button.click()

        wait.until(
            lambda d: (
                any(host in d.current_url for host in SUCCESS_HOST_HINTS)
                and not any(host in d.current_url for host in LOGIN_HOST_HINTS)
            )
        )
        print(f"Login successful. Current URL: {driver.current_url}")

        if stay_open_seconds > 0:
            time.sleep(stay_open_seconds)
    except Exception:
        os.makedirs("tmp", exist_ok=True)
        screenshot_path = os.path.join("tmp", "mls_login_error.png")
        driver.save_screenshot(screenshot_path)
        print(f"Login failed. Screenshot saved to: {screenshot_path}")
        raise
    finally:
        driver.quit()


def _build_args():
    parser = argparse.ArgumentParser(description="Log into BeachesMLS/Flexmls.")
    parser.add_argument("--username", default=os.getenv("MLS_USERNAME"), help="MLS member login / username")
    parser.add_argument("--email", default=os.getenv("MLS_EMAIL"), help="MLS account email")
    parser.add_argument("--password", default=os.getenv("MLS_PASSWORD"), help="MLS account password")
    parser.add_argument("--headless", action="store_true", help="Run Chrome in headless mode")
    parser.add_argument("--timeout", type=int, default=30, help="Wait timeout in seconds")
    parser.add_argument(
        "--stay-open-seconds",
        type=int,
        default=10,
        help="Keep browser open briefly after login success",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _build_args()

    username = args.username or os.getenv("MLS_EMAIL") or input("MLS username/member id: ").strip()
    email = args.email or input("MLS email: ").strip()
    password = args.password or getpass.getpass("MLS password: ").strip()

    if not username or not email or not password:
        raise SystemExit("Username, email, and password are required.")

    login(
        username=username,
        email=email,
        password=password,
        headless=args.headless,
        timeout=args.timeout,
        stay_open_seconds=args.stay_open_seconds,
    )
