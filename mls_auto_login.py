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
    "https://beachesmls.mysolidearth.com/authenticate?"
    "redirect_to=eyJwYXJhbXMiOnt9LCJuYW1lIjoib2F1dGguYXV0aG9yaXplIiwicXVlcnkiOnsi"
    "Y2xpZW50X2lkIjoiSUtLUmo1Y1JfNTgtdElSQ3VoalFBNG5qUVAtZEhhYTNlVUZiR0Q2eFRq"
    "OCIsIm5vbmNlIjoiODY2Mjc4YzY5ZGJhNDE3ZDYzZmRmZjgwNjk3M2Q1YzkiLCJyZWRpcmVj"
    "dF91cmkiOiJodHRwczovL2ZsLmZsZXhtbHMuY29tL29wZW5pZF9ycC9jYWxsYmFjayIsInJl"
    "c3BvbnNlX3R5cGUiOiJjb2RlIiwic2NvcGUiOiJlbWFpbCBwcm9maWxlIG9wZW5pZCJ9fQ%3D%3D"
)


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


def login(email, password, headless=False, timeout=30, stay_open_seconds=10):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1502,808")

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, timeout)

    try:
        driver.get(LOGIN_URL)

        email_input = _first_visible(
            wait,
            [
                (By.NAME, "email"),
                (By.CSS_SELECTOR, "input[name='email']"),
            ],
        )
        email_input.clear()
        email_input.send_keys(email)

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

        wait.until(lambda d: "flexmls.com" in d.current_url and "authenticate" not in d.current_url)
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

    email = args.email or input("MLS email: ").strip()
    password = args.password or getpass.getpass("MLS password: ").strip()

    if not email or not password:
        raise SystemExit("Email and password are required.")

    login(
        email=email,
        password=password,
        headless=args.headless,
        timeout=args.timeout,
        stay_open_seconds=args.stay_open_seconds,
    )
