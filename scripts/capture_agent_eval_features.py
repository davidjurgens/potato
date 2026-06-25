#!/usr/bin/env python3
"""
Capture website-quality screenshots of the new agent-evaluation schemas (M-series).

For each example config it launches the server in --debug --debug-phase annotation,
goes to /annotate, performs a few representative annotations (so the feature is shown
*in use* — selected verdicts, a marked critical node, a computed IoU, etc.), then
saves a full-viewport PNG and a cropped element PNG.

Usage:
    python scripts/capture_agent_eval_features.py [--only schema1,schema2] [--no-headless]
"""

import os
import sys
import time
import socket
import argparse
import subprocess
from pathlib import Path

project_root = Path(__file__).parents[1]
sys.path.insert(0, str(project_root))

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests

# schema -> (config, wait_css, interaction_js, crop_css)
# interaction_js runs after load+settle to put the feature in an annotated state.
EX = "examples/agent-traces"
FEATURES = {
    "agent_interaction_graph": (
        f"{EX}/interaction-graph/config.yaml", ".aig-node",
        """
        var n = document.querySelector('.aig-node[data-node]'); if (n) n.dispatchEvent(new MouseEvent('click',{bubbles:true}));
        var e = document.querySelector('.aig-edge'); if (e) { e.dispatchEvent(new MouseEvent('click',{bubbles:true})); }
        """, ".agent-graph-container"),
    "failure_attribution": (
        f"{EX}/failure-attribution/config.yaml", ".failure-attribution-container",
        """
        var a=document.querySelector('.fa-agent'); if(a){a.selectedIndex=2;a.dispatchEvent(new Event('change',{bubbles:true}));}
        var s=document.querySelector('.fa-step'); if(s){s.selectedIndex=3;s.dispatchEvent(new Event('change',{bubbles:true}));}
        var r=document.querySelector('.fa-reason'); if(r){r.value='The Reviewer approved without running the failing test.';r.dispatchEvent(new Event('input',{bubbles:true}));}
        """, ".failure-attribution-container"),
    "handoff_review": (
        f"{EX}/handoff-review/config.yaml", ".hr-card",
        """
        var f=document.querySelector('.hr-card[data-idx="0"] .hr-flag[data-f="dropped_constraint"]'); if(f) f.click();
        var q=document.querySelector('.hr-card[data-idx="0"] .hr-qbtn[data-v="2"]'); if(q) q.click();
        """, ".handoff-review-container"),
    "agent_scorecard": (
        f"{EX}/agent-scorecard/config.yaml", ".asc-card",
        """
        document.querySelectorAll('.asc-card').forEach(function(c,ci){
          c.querySelectorAll('.asc-row').forEach(function(r,ri){
            var b=r.querySelector('.asc-sbtn[data-v="'+(3+((ci+ri)%3))+'"]'); if(b) b.click();
          });
        });
        var t=document.querySelector('.asc-team-grid .asc-sbtn[data-v="4"]'); if(t) t.click();
        var m=document.querySelector('.asc-ms-cb'); if(m){m.checked=true;m.dispatchEvent(new Event('change',{bubbles:true}));}
        """, ".agent-scorecard-container"),
    "tool_contention": (
        f"{EX}/tool-contention/config.yaml", ".tc-lane",
        """
        var b=document.querySelector('.tc-card[data-idx="0"] .tc-lbtn[data-l="race_condition"]'); if(b) b.click();
        """, ".tool-contention-container"),
    "emergent_behavior": (
        f"{EX}/emergent-behavior/config.yaml", ".eb-block",
        """
        ['0','1'].forEach(function(t){var cb=document.querySelector('.eb-cb[data-b="groupthink"][data-t="'+t+'"]'); if(cb){cb.checked=true;cb.dispatchEvent(new Event('change',{bubbles:true}));}});
        var nn=document.querySelector('.eb-note[data-b="groupthink"]'); if(nn){nn.value='All agents converged without independent checks.';nn.dispatchEvent(new Event('input',{bubbles:true}));}
        """, ".emergent-behavior-container"),
    "gui_trajectory": (
        f"{EX}/gui-trajectory/config.yaml", ".gt-card",
        """
        var ok=document.querySelector('.gt-card[data-idx="0"] .gt-vbtn[data-v="correct"]'); if(ok) ok.click();
        var bad=document.querySelector('.gt-card[data-idx="2"] .gt-vbtn[data-v="wrong_element"]'); if(bad) bad.click();
        """, ".gui-trajectory-container"),
    "tool_call_review": (
        f"{EX}/tool-call-review/config.yaml", ".tcr-card",
        """
        var ok=document.querySelector('.tcr-card[data-idx="0"] .tcr-vbtn[data-v="correct"]'); if(ok) ok.click();
        var bad=document.querySelector('.tcr-card[data-idx="1"] .tcr-vbtn[data-v="wrong_args"]'); if(bad) bad.click();
        """, ".tool-call-review-container"),
    "voice_interaction": (
        f"{EX}/voice-interaction/config.yaml", ".vi-timeline",
        """
        var l=document.querySelector('.vi-ocard[data-idx="0"] .vi-lbtn[data-l="agent_should_respond"]'); if(l) l.click();
        var r=document.querySelector('.vi-rbtn[data-v="4"]'); if(r) r.click();
        """, ".voice-interaction-container"),
    "temporal_grounding": (
        f"{EX}/temporal-grounding/config.yaml", ".tg-card",
        """
        var s=document.querySelector('.tg-start[data-idx="0"]'); var e=document.querySelector('.tg-end[data-idx="0"]');
        if(s&&e){s.value='3.2';e.value='6.8';s.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('input',{bubbles:true}));}
        """, ".temporal-grounding-container"),
    "speech_transcript": (
        f"{EX}/speech-transcript/config.yaml", ".st-card",
        """
        var b=document.querySelector('.st-card[data-idx="0"] .st-ebtn[data-e="asr_error"]'); if(b) b.click();
        var c=document.querySelector('.st-card[data-idx="0"] .st-correction'); if(c){c.value="what's the weather like today";c.dispatchEvent(new Event('input',{bubbles:true}));}
        var d=document.querySelector('.st-card[data-idx="2"] .st-ebtn[data-e="disfluency"]'); if(d) d.click();
        """, ".speech-transcript-container"),
    "multimodal_reasoning": (
        f"{EX}/multimodal-reasoning/config.yaml", ".mmr-card",
        """
        var ok=document.querySelector('.mmr-card[data-idx="0"] .mmr-vbtn[data-v="coherent"]'); if(ok) ok.click();
        var h=document.querySelector('.mmr-card[data-idx="2"] .mmr-vbtn[data-v="visual_hallucination"]'); if(h) h.click();
        """, ".mmr-container"),
    "table_grid": (
        f"{EX}/table-grid/config.yaml", ".tbg-cell",
        # Seed the hidden input + fire instanceChanged for a deterministic render
        # (clicking cycles, which races with the late rebuild on this schema).
        """
        var h=document.querySelector('.table-grid-input');
        if(h){h.value=JSON.stringify({rows:3,cols:3,cells:{'0,0':'col_header','0,1':'col_header','0,2':'col_header','1,0':'row_header','2,0':'row_header','2,2':'empty'}});
        h.setAttribute('data-modified','true'); document.dispatchEvent(new Event('instanceChanged'));}
        """, ".table-grid-container"),
}

BASE_PORT = 9140


def find_free_port(start=BASE_PORT):
    for port in range(start, start + 200):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port)); return port
            except OSError:
                continue
    raise RuntimeError("no free port")


def start_server(config_path, port):
    cmd = [sys.executable, str(project_root / "potato" / "flask_server.py"), "start",
           config_path, "-p", str(port), "--debug", "--debug-phase", "annotation"]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, cwd=str(project_root))
    for _ in range(120):
        if proc.poll() is not None:
            print("  server died:", proc.stderr.read().decode()[:500]); return None
        try:
            if requests.get(f"http://localhost:{port}/", timeout=2).status_code in (200, 302):
                return proc
        except requests.ConnectionError:
            pass
        time.sleep(0.5)
    proc.terminate(); return None


def capture(driver, port, name, wait_css, interaction_js, crop_css, out_dir):
    driver.get(f"http://localhost:{port}/annotate")
    try:
        WebDriverWait(driver, 20).until(EC.visibility_of_element_located((By.ID, "main-content")))
    except Exception:
        pass
    try:
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, wait_css)))
    except Exception:
        print(f"  WARN: wait selector {wait_css} not found")
    # Settle past any late `instanceChanged` rebuild (some schemas re-render ~1-2s
    # after load); interacting before that would have the rebuild wipe the click.
    time.sleep(3.0)
    if interaction_js:
        try:
            driver.execute_script(interaction_js); time.sleep(1.5)
        except Exception as e:
            print(f"  interaction error: {e}")
    driver.execute_script("window.scrollTo(0,0);"); time.sleep(0.3)

    full = os.path.join(out_dir, f"{name}_full.png")
    driver.save_screenshot(full); print(f"  {full}")
    try:
        el = driver.find_element(By.CSS_SELECTOR, crop_css)
        # Neutralize the sticky navbar / any fixed footer so they don't bleed into
        # the element crop, and give the container a little breathing room on top.
        driver.execute_script("""
            var target = arguments[0];
            var nb = document.querySelector('.potato-navbar'); if (nb) nb.style.display = 'none';
            document.querySelectorAll('*').forEach(function(e){
                var p = getComputedStyle(e).position;
                if ((p === 'fixed' || p === 'sticky') && e !== target && !target.contains(e)) e.style.position = 'static';
            });
            target.style.scrollMarginTop = '24px';
        """, el)
        time.sleep(0.3)
        driver.execute_script("arguments[0].scrollIntoView({block:'start'});", el); time.sleep(0.4)
        el.screenshot(os.path.join(out_dir, f"{name}_feature.png"))
        print(f"  {os.path.join(out_dir, name + '_feature.png')}")
    except Exception as e:
        print(f"  crop error: {e}")
    errs = [l for l in driver.get_log("browser") if l["level"] in ("SEVERE", "ERROR")]
    for e in errs[:4]:
        print(f"  console: {e['message'][:160]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--no-headless", action="store_true")
    ap.add_argument("--output-dir", default="screenshots/website")
    args = ap.parse_args()

    out_dir = str(project_root / args.output_dir)
    os.makedirs(out_dir, exist_ok=True)
    targets = {k: v for k, v in FEATURES.items()
               if not args.only or k in args.only.split(",")}

    opts = ChromeOptions()
    if not args.no_headless:
        opts.add_argument("--headless=new")
    for a in ("--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
              "--force-device-scale-factor=2", "--window-size=1500,1350"):
        opts.add_argument(a)
    opts.set_capability("goog:loggingPrefs", {"browser": "ALL"})

    for name, (cfg, wait_css, js, crop) in targets.items():
        print(f"== {name} ({cfg})")
        port = find_free_port()
        proc = start_server(cfg, port)
        if not proc:
            print("  SKIP (server failed)"); continue
        driver = webdriver.Chrome(options=opts)
        try:
            capture(driver, port, name, wait_css, js, crop, out_dir)
        finally:
            driver.quit()
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    print("done ->", out_dir)


if __name__ == "__main__":
    main()
