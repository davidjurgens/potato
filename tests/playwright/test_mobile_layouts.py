"""Phone-width layout of the pages people actually open on a phone.

Each test opens a page as a real device -- viewport, touch, User-Agent and
pixel density together, via Playwright's device descriptors (see
``tests/helpers/mobile.py``) -- and fails if the page scrolls sideways or a
control the user needs is off the side of the screen.

Runs against a copy of ``examples/advanced/machine-annotators``, which has
data for every page covered here: an annotation task, a populated adjudication
queue, a psychometrics fit and a scored agreement report.
"""

import os
import shutil
import subprocess
import sys

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import PHONES, layout_problems, mobile_page  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "advanced", "machine-annotators")


@pytest.fixture(scope="module")
def example_server():
    work = os.path.join(create_test_directory("mobile_layouts"), "machine-annotators")
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "project.sqlite*", "test_config_port_*"))
    subprocess.run([sys.executable, os.path.join(work, "setup_demo.py")],
                   check=True, capture_output=True)
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the example server")
    yield srv
    srv.stop()


def _login(page, base_url, user):
    page.context.request.post(f"{base_url}/auth", form={"email": user, "pass": ""})


def _assert_fits(page, reachable):
    problems = layout_problems(page, reachable)
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("device", PHONES)
class TestAdjudicationOnAPhone:
    def test_queue(self, example_server, device):
        with mobile_page(device, example_server.base_url) as page:
            _login(page, example_server.base_url, "lead_curator")
            page.goto("/adjudicate")
            page.wait_for_selector(".adj-queue-item")
            _assert_fits(page, [".logout-btn", ".adj-queue-item"])

    def test_an_open_item(self, example_server, device):
        with mobile_page(device, example_server.base_url) as page:
            _login(page, example_server.base_url, "lead_curator")
            page.goto("/adjudicate")
            page.tap(".adj-queue-item")
            page.wait_for_selector(".adj-annotator-card")
            _assert_fits(page, [".logout-btn", ".adj-radio-option",
                                ".adj-origin-badge"])
            # The action bar is pinned; Submit must be on screen without
            # scrolling sideways.
            submit = page.get_by_role("button", name="Submit and continue")
            box = submit.bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= page.viewport_size["width"] + 1


@pytest.mark.parametrize("device", PHONES)
class TestAnnotationOnAPhone:
    def test_the_annotate_page_fits(self, example_server, device):
        """This example leaves Pocket Mode off, so a phone gets /annotate."""
        with mobile_page(device, example_server.base_url) as page:
            _login(page, example_server.base_url, f"phone_{device.split()[0].lower()}")
            page.goto("/annotate")
            page.wait_for_selector("#next-btn")
            assert "/pocket" not in page.url
            _assert_fits(page, [".logout-btn", "#next-btn"])


@pytest.mark.parametrize("device", PHONES)
class TestAdminPagesOnAPhone:
    def _open(self, server, device, path):
        return mobile_page(device, server.base_url,
                           extra_headers={"X-API-Key": server.admin_api_key})

    def test_psychometrics_dashboard(self, example_server, device):
        with self._open(example_server, device, "/psychometrics/dashboard") as page:
            page.goto("/psychometrics/dashboard")
            page.wait_for_selector(".ab-row")
            _assert_fits(page, ["#machine-note", ".ab-row .origin"])

    def test_agreement_report(self, example_server, device):
        with self._open(example_server, device, "/admin/iaa?format=html") as page:
            page.goto("/admin/iaa?format=html")
            page.wait_for_load_state("networkidle")
            _assert_fits(page, [".iaa-machine-note"])


# ---------------------------------------------------------------------------
# Pocket Mode: the phone view proper. Its own server, after the one above has
# stopped -- FlaskTestServer instances share process-wide singletons.
# ---------------------------------------------------------------------------

POCKET_EXAMPLE = os.path.join(REPO, "examples", "advanced", "pocket-mode")


@pytest.fixture(scope="module")
def pocket_server(example_server):
    example_server.stop()
    work = os.path.join(create_test_directory("mobile_pocket"), "pocket-mode")
    shutil.copytree(POCKET_EXAMPLE, work, ignore=shutil.ignore_patterns(
        "annotation_output", "project.sqlite*", "test_config_port_*"))
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the pocket-mode example server")
    yield srv
    srv.stop()


@pytest.mark.parametrize("device", PHONES)
def test_a_phone_is_routed_to_pocket_and_it_fits(pocket_server, device):
    with mobile_page(device, pocket_server.base_url) as page:
        _login(page, pocket_server.base_url, f"pocket_{device.split()[0].lower()}")
        page.goto("/annotate")
        page.wait_for_load_state("networkidle")
        assert "/pocket" in page.url, (
            f"a {device} should be routed to the pocket view, landed on {page.url}")
        _assert_fits(page, [])
