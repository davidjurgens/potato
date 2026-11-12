"""What an annotator types must not reach the browser console.

``base_template_v2.html`` carried a "Global keyboard debug (temporary)" block
that logged ``e.key`` for every keydown on every annotation page, so a
free-text answer was echoed to the console one character at a time --
on the same pages where keystroke logging is advertised as content-blind.
It only showed with console logging on (debug mode, or ``enableUIDebug()``),
which is how the test turns it on.
"""

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.test_utils import TestConfigManager  # noqa: E402

pytestmark = pytest.mark.playwright

SECRET = "zqxv"


@pytest.fixture(scope="module")
def server():
    schemes = [{
        "annotation_type": "text",
        "name": "notes",
        "description": "Anything to add?",
    }]
    with TestConfigManager("console_keystrokes", schemes) as cfg:
        srv = FlaskTestServer(config_file=cfg.config_path)
        if not srv.start():
            pytest.fail("could not start server")
        yield srv
        srv.stop()


def test_typed_text_is_not_logged(server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        context.request.post(f"{server.base_url}/register",
                             form={"email": "kb_user", "pass": "pw"})
        context.request.post(f"{server.base_url}/auth",
                             form={"email": "kb_user", "pass": "pw"})
        page = context.new_page()
        messages = []
        page.on("console", lambda m: messages.append(m.text))
        page.goto(f"{server.base_url}/annotate")
        # Outside debug mode the template mutes console.log altogether, which
        # hid the leak; turn logging back on the way a researcher would.
        page.evaluate("window.enableUIDebug && window.enableUIDebug()")
        page.locator("[id^='notes'][id$='text']").first.click()
        page.keyboard.type(SECRET, delay=20)
        page.wait_for_timeout(300)
        browser.close()

    leaked = [m for m in messages
              if any(f" {ch} " in f" {m} " or f"keydown: {ch}" in m for ch in SECRET)]
    assert not leaked, f"typed keys reached the console: {leaked[:4]}"
