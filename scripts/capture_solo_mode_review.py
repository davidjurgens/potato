#!/usr/bin/env python3
"""Capture solo-mode UI screenshots for impeccable review.

Outputs PNGs to screenshots/solo-review/ for status, annotate, and setup screens
in both desktop (1440px) and narrow (768px) viewports.
"""
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "screenshots" / "solo-review-after"
OUT.mkdir(parents=True, exist_ok=True)

BASE = "http://localhost:8000"
USER = "shot"
PASSWORD = "shot1234"

DESKTOP = (1440, 900)
NARROW = (768, 900)


def login(driver, base, user, password):
    driver.get(base + "/")
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "login-email"))
    )
    driver.find_element(By.ID, "login-email").send_keys(user)
    driver.find_element(By.ID, "login-pass").send_keys(password)
    driver.find_element(By.CSS_SELECTOR, "form[action='/auth'] button[type='submit']").click()
    WebDriverWait(driver, 10).until(
        lambda d: urlparse(d.current_url).path != "/" or "annotate" in d.current_url
    )


def full_height_screenshot(driver, out_path):
    """Resize window to full page height and screenshot."""
    width = driver.execute_script("return window.innerWidth")
    height = driver.execute_script(
        "return Math.max("
        "document.body.scrollHeight, document.documentElement.scrollHeight,"
        "document.body.offsetHeight, document.documentElement.offsetHeight)"
    )
    driver.set_window_size(width, max(height + 100, 900))
    time.sleep(0.4)
    driver.save_screenshot(str(out_path))


def capture(driver, path, name, viewport):
    driver.set_window_size(*viewport)
    driver.get(BASE + path)
    time.sleep(1.5)  # let JS render
    label = f"{name}_{viewport[0]}w"
    out = OUT / f"{label}.png"
    full_height_screenshot(driver, out)
    print(f"  wrote {out.name} ({viewport[0]}x{viewport[1]})")


def main():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--hide-scrollbars")
    driver = webdriver.Chrome(options=opts)
    try:
        print("Logging in...")
        driver.set_window_size(*DESKTOP)
        login(driver, BASE, USER, PASSWORD)

        for viewport in (DESKTOP, NARROW):
            print(f"\n=== {viewport[0]}px wide ===")
            for path, name in (
                ("/solo/status", "status_overview"),
                ("/solo/annotate", "annotate"),
                ("/solo/setup", "setup"),
            ):
                capture(driver, path, name, viewport)

            # Capture each status tab individually at desktop only
            if viewport == DESKTOP:
                driver.set_window_size(*viewport)
                driver.get(BASE + "/solo/status")
                time.sleep(1.5)
                tabs = driver.find_elements(By.CSS_SELECTOR, ".solo-tab")
                for tab in tabs:
                    name = (tab.get_attribute("data-tab") or "tab").replace("-", "_")
                    if name == "overview":
                        continue  # already captured
                    driver.execute_script("arguments[0].click();", tab)
                    time.sleep(1.5)
                    out = OUT / f"status_{name}_{viewport[0]}w.png"
                    full_height_screenshot(driver, out)
                    print(f"  wrote {out.name} (tab={name})")
        print("\nDone. Screenshots in:", OUT)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
