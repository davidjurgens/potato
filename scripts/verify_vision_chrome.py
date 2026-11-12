#!/usr/bin/env python3
"""
Drive a vision annotation surface in a real browser and assert on the DOM.

This is the scripted form of the manual Chrome loop used to verify each vision
wave. It exists because the automated suites and a live browser catch different
things: Jest proves the serializer's logic, Playwright proves the canvas
responds to a mouse, and this proves the *assembled page* — the real config, the
real template, the real asset versions — actually works.

WHAT IT ASSERTS, AND WHY IT DOES NOT SCREENSHOT
-----------------------------------------------
Assertions read the DOM and the stored annotation blob, never pixels. When a
browser tab is backgrounded or headless, `getComputedStyle` can return stale
paint values and canvas frames freeze — which has produced false findings here
before ("the focus indicator is missing", "the active-tool style is broken")
that a synthetic control element disproved. Screenshots are for a human to look
at, not for a machine to assert on.

USAGE
    python scripts/verify_vision_chrome.py examples/image/coco-import/config.yaml
    python scripts/verify_vision_chrome.py <config> --schema object_detection
    python scripts/verify_vision_chrome.py <config> --screenshot out.png

Exits non-zero if any check fails, so it can gate a wave.
"""

import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
except ImportError:
    print("selenium is required: pip install selenium")
    sys.exit(1)


def free_port(start=8300):
    for port in range(start, start + 200):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("no free port")


def start_server(config: str, port: int):
    """Start Potato in debug mode, skipping straight to the annotation phase."""
    proc = subprocess.Popen(
        [sys.executable, "potato/flask_server.py", "start", config,
         "-p", str(port), "--debug", "--debug-phase", "annotation"],
        cwd=str(REPO_ROOT),
        # Verbose configs fill the 64KB pipe buffer and hang the server if the
        # output is never drained.
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    import urllib.request
    import urllib.error

    for _ in range(60):
        if proc.poll() is not None:
            raise RuntimeError("server exited during startup")
        try:
            urllib.request.urlopen(f"http://localhost:{port}/annotate", timeout=2)
            return proc
        except urllib.error.HTTPError:
            return proc  # a 302 to the annotation page is healthy
        except Exception:
            time.sleep(1)
    proc.kill()
    raise RuntimeError("server did not become ready")


#: Each probe returns {name: value}; `check` decides pass/fail.
PROBE_JS = r"""
const schema = arguments[0];
const container = schema
    ? document.querySelector(`.image-annotation-container[data-schema="${schema}"]`)
    : document.querySelector('.image-annotation-container');
if (!container) return {error: 'no .image-annotation-container on the page'};

const m = container.annotationManager;
if (!m) return {error: 'container has no annotationManager'};

const input = document.getElementById(m.inputId);
let stored = [];
try { stored = JSON.parse(input.value || '[]'); } catch (e) {}

const externalScripts = [...document.querySelectorAll('script[src]')]
    .map(s => s.src).filter(s => !s.startsWith(location.origin));

return {
    schema: m.config.schemaName,
    fabricLoaded: typeof fabric !== 'undefined',
    fabricIsLocal: [...document.querySelectorAll('script[src]')]
        .some(s => s.src.includes('fabric') && s.src.startsWith(location.origin)),
    imageLoaded: !!m.image,
    tools: m.config.tools,
    toolButtons: [...container.querySelectorAll('.tool-btn')].map(b => b.dataset.tool),
    labelButtons: [...container.querySelectorAll('.label-btn')].map(b => b.dataset.label),
    keybindingProfile: m.config.keybindingProfile,
    toolKeys: m.config.toolKeys,
    visibilityWired: !!m.labelVisibility,
    eyeToggles: container.querySelectorAll('.label-visibility-toggle').length,
    carryOver: m.config.carryOver,
    carryOverButton: !!container.querySelector('.carry-over-btn'),
    annotationCount: m.getAnnotationCount(),
    storedTypes: stored.map(a => a.type),
    externalScripts: externalScripts,
    consoleReady: true,
};
"""


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", help="Path to a Potato config with an image_annotation schema")
    ap.add_argument("--schema", default=None, help="Schema name (default: first found)")
    ap.add_argument("--screenshot", default=None, help="Save a PNG for human review")
    ap.add_argument("--keep-open", action="store_true", help="Leave the server running")
    args = ap.parse_args()

    port = free_port()
    print(f"Starting {args.config} on :{port}")
    proc = start_server(args.config, port)

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1600,1200")
    opts.set_capability("goog:loggingPrefs", {"browser": "ALL"})

    driver = webdriver.Chrome(options=opts)
    failures = 0
    try:
        driver.get(f"http://localhost:{port}/annotate")
        time.sleep(4)

        probe = driver.execute_script(PROBE_JS, args.schema)
        if probe.get("error"):
            print(f"  FAIL  page probe — {probe['error']}")
            return 1

        print(f"\nSchema: {probe['schema']}")
        print(json.dumps(probe, indent=1))
        print("\nChecks:")

        results = [
            check("fabric is loaded", probe["fabricLoaded"]),
            check("fabric is served locally, not from a CDN", probe["fabricIsLocal"]),
            check("image loaded into the canvas", probe["imageLoaded"]),
            check("a tool button exists for every configured tool",
                  set(probe["tools"]) <= set(probe["toolButtons"]),
                  f"configured={probe['tools']} rendered={probe['toolButtons']}"),
            check("at least one label is available", bool(probe["labelButtons"])),
            check("keybinding profile is set", bool(probe["keybindingProfile"]),
                  str(probe["keybindingProfile"])),
            check("per-class visibility is wired", probe["visibilityWired"]),
            check("an eye toggle exists for every label",
                  probe["eyeToggles"] == len(probe["labelButtons"]),
                  f"{probe['eyeToggles']} toggles / {len(probe['labelButtons'])} labels"),
        ]

        if probe["carryOver"] in ("prompt", "auto"):
            results.append(check("carry-over button is rendered", probe["carryOverButton"]))

        # Exercise the programmatic entry point every producer routes through.
        added = driver.execute_script(
            """const c = document.querySelector('.image-annotation-container');
               return c.annotationManager.addAnnotation({
                   type: 'bbox', label: arguments[0], color: '#ff0000',
                   coordinates: {x: 0.25, y: 0.25, width: 0.3, height: 0.3}});""",
            probe["labelButtons"][0] if probe["labelButtons"] else "test",
        )
        results.append(check("addAnnotation accepts a contract-shaped bbox", bool(added)))

        after = driver.execute_script(
            """const c = document.querySelector('.image-annotation-container');
               const m = c.annotationManager;
               return JSON.parse(document.getElementById(m.inputId).value || '[]').length;""")
        results.append(check("the drawn annotation reached the saved blob",
                             after == len(probe["storedTypes"]) + 1,
                             f"{len(probe['storedTypes'])} -> {after}"))

        # Optional subsystems (memos, codebook, search) answer 503 when they are
        # not enabled for a project, and the client probes them unconditionally.
        # That is expected noise, so it is filtered by exact endpoint rather
        # than by ignoring resource errors wholesale — a 404 on a static asset
        # is exactly what this check exists to catch.
        # /favicon.ico is requested by the browser itself, unprompted; its 404
        # says nothing about the page under test.
        OPTIONAL_ENDPOINTS = ("/api/memos", "/api/codebook", "/api/search",
                              "/api/quotations", "/favicon.ico")
        severe = [
            e for e in driver.get_log("browser")
            if e["level"] == "SEVERE"
            and not any(ep in e["message"] for ep in OPTIONAL_ENDPOINTS)
        ]
        results.append(check("no severe console errors", not severe,
                             "; ".join(e["message"][:110] for e in severe[:3])))

        if probe["externalScripts"]:
            print(f"\n  note: {len(probe['externalScripts'])} script(s) still load "
                  f"from a CDN (see docs/deployment/air_gap.md):")
            for src in probe["externalScripts"]:
                print(f"        {src}")

        if args.screenshot:
            driver.save_screenshot(args.screenshot)
            print(f"\nScreenshot saved to {args.screenshot} — for human review only; "
                  f"do not assert on pixels.")

        failures = sum(1 for r in results if not r)
        print(f"\n{len(results) - failures}/{len(results)} checks passed")
    finally:
        driver.quit()
        if not args.keep_open:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
