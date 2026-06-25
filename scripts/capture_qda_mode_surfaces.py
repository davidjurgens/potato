#!/usr/bin/env python3
"""Capture every main QDA-Mode UI surface from the composed example.

Drives examples/advanced/qda-mode-example against a real Flask server and
writes screenshots to screenshots/verify/ for visual review + impeccable audit:

  qda_01_annotation.png    — annotation page (span + themes codebook schemes)
  qda_02_codebook_tray.png — Codebook tray open (tree + add-a-code composer)
  qda_03_memos.png         — Notes (memos) sidebar open with composer
  qda_04_search.png        — Find (FTS5 search) panel open with results
  qda_05_invivo.png        — in-vivo composer minted from a text selection
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port

OUT = Path(__file__).parent.parent / "screenshots" / "verify"
OUT.mkdir(parents=True, exist_ok=True)

CONFIG = (Path(__file__).parent.parent / "examples" / "advanced" /
          "qda-mode-example" / "config.yaml")


def main():
    port = find_free_port()
    server = FlaskTestServer(port=port, debug=False, config_file=str(CONFIG))
    assert server.start_server(), "server failed to start"
    server._wait_for_server_ready(timeout=15)

    o = Options()
    for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
              "--disable-gpu", "--window-size=1500,950"):
        o.add_argument(a)
    d = webdriver.Chrome(options=o)
    try:
        w = WebDriverWait(d, 20)
        d.get(f"{server.base_url}/")
        w.until(EC.presence_of_element_located((By.ID, "login-email")))
        d.find_element(By.ID, "login-email").send_keys("coder1")
        d.find_element(By.CSS_SELECTOR, "#login-content form").submit()
        w.until(EC.presence_of_element_located((By.ID, "instance_id")))
        # let the universal JS finish self-gating (toggles un-hide on 200)
        time.sleep(2.5)

        d.save_screenshot(str(OUT / "qda_01_annotation.png"))
        print("saved qda_01_annotation.png")

        # --- Codebook tray ---
        try:
            w.until(EC.element_to_be_clickable((By.ID, "cb-panel-toggle")))
            d.find_element(By.ID, "cb-panel-toggle").click()
            time.sleep(1.0)
            d.save_screenshot(str(OUT / "qda_02_codebook_tray.png"))
            print("saved qda_02_codebook_tray.png")
            d.find_element(By.ID, "cb-panel-close").click()
            time.sleep(0.4)
        except Exception as e:
            print("codebook tray FAILED:", e)

        # --- Memos sidebar ---
        try:
            w.until(EC.element_to_be_clickable((By.ID, "memo-panel-toggle")))
            d.find_element(By.ID, "memo-panel-toggle").click()
            time.sleep(0.6)
            d.find_element(By.ID, "memo-new-body").send_keys(
                "Participant ties skipped follow-ups directly to copay rises.")
            time.sleep(0.4)
            d.save_screenshot(str(OUT / "qda_03_memos.png"))
            print("saved qda_03_memos.png")
            d.find_element(By.ID, "memo-panel-close").click()
            time.sleep(0.4)
        except Exception as e:
            print("memos sidebar FAILED:", e)

        # --- Search / Find panel ---
        try:
            w.until(EC.element_to_be_clickable((By.ID, "search-panel-toggle")))
            d.find_element(By.ID, "search-panel-toggle").click()
            time.sleep(0.5)
            q = d.find_element(By.ID, "search-q")
            q.send_keys("copay")
            d.find_element(By.ID, "search-go").click()
            time.sleep(1.0)
            d.save_screenshot(str(OUT / "qda_04_search.png"))
            print("saved qda_04_search.png")
            d.find_element(By.ID, "search-panel-close").click()
            time.sleep(0.4)
        except Exception as e:
            print("search panel FAILED:", e)

        # --- In-vivo composer ---
        try:
            w.until(lambda x: x.execute_script(
                "return !!(window.spanManager"
                " && window.spanManager.isInitialized);"))
            d.execute_script("""
                const host = document.getElementById('text-content')
                    || document.querySelector('[id^="text-content-"]');
                let tn=null;
                for (const n of host.childNodes)
                    if (n.nodeType===3 && n.textContent.trim()){tn=n;break;}
                const r=document.createRange();
                r.setStart(tn, 0); r.setEnd(tn, 18);
                const s=window.getSelection();
                s.removeAllRanges(); s.addRange(r);
                document.dispatchEvent(new KeyboardEvent(
                    'keydown',{key:'i',bubbles:true}));
            """)
            w.until(EC.visibility_of_element_located((By.ID, "cb-invivo")))
            time.sleep(0.6)
            d.save_screenshot(str(OUT / "qda_05_invivo.png"))
            print("saved qda_05_invivo.png")
        except Exception as e:
            print("invivo composer FAILED:", e)

    finally:
        d.quit()
        server.stop_server()


if __name__ == "__main__":
    main()
