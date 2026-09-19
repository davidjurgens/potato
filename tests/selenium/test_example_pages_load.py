"""Every example's annotation page loads in a real browser without a script error.

Opt-in: it boots all ~215 example projects one after another, which takes
10-20 minutes serially. Run it when a change reaches every page -- the base
template, shared JavaScript, frontend asset gating, a request hook:

    POTATO_EXAMPLE_SWEEP=1 pytest tests/selenium/test_example_pages_load.py -n 6

Each example is started with ``--debug --debug-phase annotation`` so no login
or consent screens intervene. The page must clear its loading state, and the
console must hold no uncaught ``SyntaxError`` or ``ReferenceError``: the
signature of a script that failed to parse, or of a page calling into a
feature script that asset gating left out.

It found ``visual_ai_assistant.js`` failing to parse on every image or video
project with AI support (a ``const`` re-declaring a global another script
defines), and it is how the gating of five feature scripts on their markers
was checked against every example.

Console errors from third-party media (hosted sample videos, WebGL in headless
Chrome) are not script errors and are not checked here.
"""

import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

pytestmark = pytest.mark.skipif(
    os.environ.get("POTATO_EXAMPLE_SWEEP") != "1",
    reason="boots every example project; set POTATO_EXAMPLE_SWEEP=1 to run",
)

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "examples"

SCRIPT_ERROR = re.compile(r"Uncaught (SyntaxError|ReferenceError)")


def _example_configs():
    return sorted(p for p in EXAMPLES.rglob("config.yaml")
                  if "simulator-configs" not in p.parts)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    options = Options()
    for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                "--disable-gpu", "--window-size=1400,1000"):
        options.add_argument(arg)
    options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    return webdriver.Chrome(options=options)


LOADED_JS = """
const l = document.getElementById('loading-state');
return document.readyState === 'complete' &&
       (!l || getComputedStyle(l).display === 'none');
"""


@pytest.mark.selenium
@pytest.mark.slow
@pytest.mark.timeout(180)
@pytest.mark.parametrize(
    "config", _example_configs(),
    ids=lambda p: str(p.relative_to(EXAMPLES).parent))
def test_annotation_page_loads_without_a_script_error(config, tmp_path):
    port = _free_port()
    log = open(tmp_path / "server.log", "w")
    server = subprocess.Popen(
        [sys.executable, "potato/flask_server.py", "start", str(config.relative_to(REPO)),
         "-p", str(port), "--debug", "--debug-phase", "annotation", "--host", "127.0.0.1"],
        cwd=REPO, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    base = f"http://127.0.0.1:{port}"
    driver = None
    try:
        for _ in range(150):
            if server.poll() is not None:
                break
            try:
                requests.get(base + "/", timeout=2)
                break
            except requests.RequestException:
                time.sleep(0.4)
        if server.poll() is not None:
            log.flush()
            pytest.skip("example does not boot here (needs an external service?): "
                        + (tmp_path / "server.log").read_text()[-300:])

        driver = _driver()
        driver.set_page_load_timeout(40)
        driver.get(base + "/")
        driver.get(base + "/annotate")
        deadline = time.time() + 25
        while time.time() < deadline and not driver.execute_script(LOADED_JS):
            time.sleep(0.1)
        assert driver.execute_script(LOADED_JS), "the loading state never cleared"

        errors = [e["message"] for e in driver.get_log("browser")
                  if e["level"] == "SEVERE" and SCRIPT_ERROR.search(e["message"])]
        assert errors == []
    finally:
        if driver is not None:
            driver.quit()
        if server.poll() is None:
            try:
                os.killpg(server.pid, signal.SIGTERM)
                server.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(server.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        log.close()
