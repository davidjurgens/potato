"""
Unticking a checkbox re-evaluates display logic.

potato-skill, 2.12.0 pack notes (P1): the checkbox change handler returned
before calling displayLogicManager.evaluateForSchema when a box was
unticked, so a question gated by `count_gt 1` stayed on screen after both
boxes were cleared, and one gated by `count_equals 0` never came back.
"""

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.port_manager import find_free_port  # noqa: E402
from tests.helpers.test_utils import TestConfigManager  # noqa: E402

pytestmark = pytest.mark.playwright

SCHEMES = [
    {"annotation_type": "multiselect", "name": "picks", "description": "Pick any",
     "labels": ["a", "b", "c"]},
    {"annotation_type": "text", "name": "two_or_more", "description": "Two or more",
     "display_logic": {"show_when": [
         {"schema": "picks", "operator": "count_gt", "value": 1}]}},
    {"annotation_type": "text", "name": "some", "description": "At least one",
     "display_logic": {"show_when": [
         {"not": {"schema": "picks", "operator": "count_equals", "value": 0}}]}},
    {"annotation_type": "text", "name": "many_or_none", "description": "Many or none",
     "display_logic": {"show_when": [
         {"any": [{"schema": "picks", "operator": "count_gt", "value": 1},
                  {"schema": "picks", "operator": "count_equals", "value": 0}]}]}},
]


@pytest.fixture(scope="module")
def server():
    with TestConfigManager("display_logic_untick", SCHEMES, num_items=2) as cfg:
        srv = FlaskTestServer(port=find_free_port(), config_file=cfg.config_path)
        if not srv.start():
            pytest.fail("Failed to start server")
        yield srv
        srv.stop()


def _shown(page, name):
    return page.locator(f'[data-display-logic-target="true"][data-schema-name="{name}"]').is_visible()


def _settle(page):
    page.wait_for_timeout(500)          # display logic animates for 300 ms


def test_unticking_re_evaluates_count_gates(server, page):
    # The shared `page` fixture (conftest.py), not a second sync_playwright():
    # a test that starts its own fails once the session browser is running.
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"email": "untick", "pass": "pw"})
    req.post(f"{server.base_url}/auth", form={"email": "untick", "pass": "pw"})
    page.goto(f"{server.base_url}/annotate")
    page.wait_for_selector('input[type="checkbox"][label_name="a"]', state="attached")
    _settle(page)
    boxes = {n: page.locator(f'input[type="checkbox"][schema="picks"][label_name="{n}"]')
             for n in ("a", "b")}

    def shown():
        return (_shown(page, "two_or_more"), _shown(page, "some"), _shown(page, "many_or_none"))

    assert shown() == (False, False, True)         # nothing ticked
    boxes["a"].click(); boxes["b"].click(); _settle(page)
    assert shown() == (True, True, True)
    boxes["b"].click(); _settle(page)              # one left
    assert shown() == (False, True, False)
    boxes["a"].click(); _settle(page)              # back to none
    assert shown() == (False, False, True)
