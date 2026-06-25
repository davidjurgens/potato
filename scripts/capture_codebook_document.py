#!/usr/bin/env python3
"""Capture the living-codebook UI after the Impeccable audit fixes.

Seeds a couple of codes with typed-block content, then screenshots:
  - cbd_read.png       full-page read view (desktop)
  - cbd_editor.png     typed-block editor open (desktop)
  - cbd_read_mobile.png read view at a phone width (TOC collapses)
  - cbd_panel.png      in-annotation tray with an inline edit open

Run: python scripts/capture_codebook_document.py
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import create_test_data_file, create_test_config

OUT = Path(__file__).parent.parent / "screenshots" / "verify"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    td = os.path.join(Path(__file__).parent.parent, "tests", "output",
                      f"cbd_shot_{int(time.time())}")
    os.makedirs(td, exist_ok=True)
    data = create_test_data_file(td, [{
        "id": "i1",
        "text": "I couldn't get an appointment for three weeks, and even "
                "then the clinic was far from a bus line."}])
    cfg = create_test_config(
        td, [{"name": "themes", "description": "Themes",
              "annotation_type": "multiselect", "codebook": True,
              "labels": ["access barriers", "cost concerns"]}],
        data_files=[data], annotation_task_name="Codebook Document Example",
        require_password=False,
        additional_config={"codebook_mode": "open"})
    port = find_free_port()
    server = FlaskTestServer(port=port, debug=False, config_file=cfg)
    assert server.start_server()
    server._wait_for_server_ready(timeout=10)
    base = server.base_url

    s = requests.Session()
    s.post(f"{base}/register", data={"email": "shot", "pass": "pw"})
    s.post(f"{base}/auth", data={"email": "shot", "pass": "pw"})
    cb = s.get(f"{base}/api/codebook").json()
    ids = {}

    def walk(ns):
        for n in ns:
            ids[n["name"]] = n["id"]
            walk(n.get("children") or [])
    walk(cb["tree"])

    # doc-level instruction
    s.put(f"{base}/api/codebook/blocks", json={
        "section": "general_instructions", "base_version": 0,
        "blocks": [{"block_type": "custom", "custom_label": "How to code",
                    "body_md": "Read each excerpt **twice**. Apply *all* "
                    "themes clearly present."}]})
    s.put(f"{base}/api/codebook/blocks", json={
        "code_id": ids["access barriers"], "base_version": 0,
        "blocks": [
            {"block_type": "definition",
             "body_md": "Logistical obstacles to reaching care: distance, "
                        "transport, scheduling, availability."},
            {"block_type": "use_when",
             "body_md": "mentions travel, distance, transit, or clinic hours"},
        ]})
    s.put(f"{base}/api/codebook/blocks", json={
        "code_id": ids["cost concerns"], "base_version": 0,
        "blocks": [
            {"block_type": "short_def", "body_md": "Money as a barrier."},
            {"block_type": "definition",
             "body_md": "The speaker names **cost, price, copay, or "
                        "affordability** as shaping whether they seek care."},
            {"block_type": "use_when",
             "body_md": "- mentions copays, premiums, bills\n"
                        "- skips or delays care for financial reasons"},
            {"block_type": "example",
             "body_md": "> My copay went up again, so I've been skipping "
                        "the follow-up visits."},
        ]})

    o = Options()
    for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
              "--disable-gpu"):
        o.add_argument(a)
    o.add_argument("--window-size=1400,1300")
    d = webdriver.Chrome(options=o)
    d.set_script_timeout(15)

    # carry the session cookie into the browser
    d.get(base + "/login")
    time.sleep(0.4)
    d.execute_async_script(
        "const done=arguments[arguments.length-1];"
        "fetch('/register',{method:'POST',headers:{'Content-Type':"
        "'application/x-www-form-urlencoded'},body:'email=shot&pass=pw'})"
        ".then(()=>fetch('/auth',{method:'POST',headers:{'Content-Type':"
        "'application/x-www-form-urlencoded'},body:'email=shot&pass=pw'}))"
        ".then(()=>done('ok')).catch(e=>done(''+e));")

    # ---- read view (desktop) ----
    d.get(base + "/codebook")
    WebDriverWait(d, 10).until(
        EC.presence_of_element_located((By.ID, "cbd-doc")))
    time.sleep(1.0)
    d.save_screenshot(str(OUT / "cbd_read.png"))
    print("wrote cbd_read.png")

    # ---- editor open (desktop) ----
    d.find_element(By.ID, "cbd-edit-toggle").click()
    time.sleep(0.4)
    d.execute_script(
        "const secs=[...document.querySelectorAll('.cbd-section')];"
        "const t=secs.find(s=>{const n=s.querySelector('.cbd-section-name');"
        "return n && n.textContent==='cost concerns';});"
        "const b=[...t.querySelectorAll('.cbd-section-tools .cbd-btn')]"
        ".find(x=>x.textContent.trim()==='Edit'); b.click();")
    time.sleep(0.6)
    d.save_screenshot(str(OUT / "cbd_editor.png"))
    print("wrote cbd_editor.png")

    # ---- read view (mobile) ----
    d.set_window_size(420, 900)
    d.get(base + "/codebook")
    WebDriverWait(d, 10).until(
        EC.presence_of_element_located((By.ID, "cbd-doc")))
    time.sleep(0.8)
    d.save_screenshot(str(OUT / "cbd_read_mobile.png"))
    print("wrote cbd_read_mobile.png")

    # ---- panel inline edit ----
    d.set_window_size(1300, 1000)
    d.get(base + "/annotate")
    time.sleep(2.0)
    d.execute_script(
        "var t=document.getElementById('cb-panel-toggle');"
        "if(t){t.hidden=false;t.click();}")
    WebDriverWait(d, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".cb-node-edit")))
    time.sleep(0.5)
    d.execute_script(
        "const rows=[...document.querySelectorAll('.cb-node-row')];"
        "const r=rows.find(x=>{const n=x.querySelector('.cb-name');"
        "return n && n.textContent==='cost concerns';});"
        "if(r){const b=r.querySelector('.cb-node-edit'); if(b) b.click();}")
    time.sleep(0.9)
    d.save_screenshot(str(OUT / "cbd_panel.png"))
    print("wrote cbd_panel.png")

    d.quit()
    server.stop_server()


if __name__ == "__main__":
    main()
