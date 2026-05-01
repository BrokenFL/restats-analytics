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


def login(username, email, password, headless=False, timeout=30, stay_open_seconds=10):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1502,808")

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, timeout)

    try:
        driver.get(LOGIN_URL)

        identity_input = _first_visible(
            wait,
            [
                (By.NAME, "member_login_id"),
                (By.NAME, "email"),
                (By.CSS_SELECTOR, "input[name='member_login_id']"),
                (By.CSS_SELECTOR, "input[name='email']"),
            ],
        )
        identity_input.clear()
        identity_input.send_keys(username or email)

        password_input = _first_visible(
            wait,
            [
                (By.NAME, "password"),
                (By.CSS_SELECTOR, "input[type='password']"),
                (
                    By.XPATH,
                    "/html/body/div[2]/div/main/div/div/div[1]/div/div[2]/form/"
                    "div[1]/div[3]/div/div[1]/div[1]/input",
                ),
            ],
        )
        password_input.clear()
        password_input.send_keys(password)

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
