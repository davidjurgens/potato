"""Phase pages must not ask for an annotation instance they do not have.

Consent, instruction and survey pages asked ``/api/current_instance`` for the
current item twice on every load (span-core and the Firefox instance-id
fix). The endpoint answers 404 outside the annotation phase, and the browser
logs each one as a failed resource load, so every study's first screen
opened with two errors in the console.

Runs a copy of ``examples/advanced/all-phases-example``, whose first page is
a consent survey.
"""

import os
import shutil

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "advanced", "all-phases-example")


@pytest.fixture(scope="module")
def server():
    work = os.path.join(create_test_directory("phase_page_requests"), "all-phases-example")
    if os.path.exists(work):
        shutil.rmtree(work)
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns("annotation_output"))
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the example server")
    yield srv
    srv.stop()


def test_consent_page_makes_no_failing_instance_request(server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        context.request.post(f"{server.base_url}/register",
                             form={"email": "phase_user", "pass": "pw"})
        context.request.post(f"{server.base_url}/auth",
                             form={"email": "phase_user", "pass": "pw"})
        page = context.new_page()
        failed = []
        page.on("response",
                lambda r: failed.append(f"{r.status} {r.url}") if r.status >= 400 else None)
        page.goto(f"{server.base_url}/")
        page.wait_for_timeout(1500)
        is_annotation = page.evaluate("window.config && window.config.is_annotation_page")
        browser.close()

    assert is_annotation is False, "the fixture should land on a phase page"
    instance_failures = [f for f in failed if "/api/current_instance" in f]
    assert not instance_failures, instance_failures
