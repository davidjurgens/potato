"""
The geometry agreement report as a page, not as JSON.

`tests/server/test_iaa_image_report.py` already proves the numbers are right.
What it cannot see is the page: `/admin/iaa` renders through
`iaa/presentation.py`, and that layer has its own failure mode — a report it
does not know how to unwrap renders as "n/a" beside a healthy JSON body, so the
statistic is computed, returned, and then thrown away on the way to the screen.
Nested reports did exactly that once already.

So these assert on rendered text and on a clean console, with two annotators
who agree and two who do not, because a page that prints the same thing either
way is not reporting anything.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

pytestmark = pytest.mark.playwright

SCHEMA = "objects"
ADMIN_KEY = "iaa-ui-test-key"
ITEM_IDS = [f"img_{i}" for i in range(4)]


def box(x, y, w=0.2, h=0.2, label="car"):
    return {"type": "bbox", "label": label, "color": "#f00",
            "coordinates": {"x": x, "y": y, "width": w, "height": h}}


def _start(name, port_hint):
    test_dir = create_test_directory(name)
    data_file = create_test_data_file(
        test_dir,
        [{"id": f"img_{i}", "text": f"image {i}",
          "image_url": f"http://example.invalid/{i}.jpg"} for i in range(4)])
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{
            "annotation_type": "image_annotation",
            "name": SCHEMA,
            "description": "Objects",
            "tools": ["bbox"],
            "labels": [{"name": "car", "color": "#f00"},
                       {"name": "sign", "color": "#0f0"}],
        }],
        data_files=[data_file],
        item_properties={"id_key": "id", "text_key": "text"},
        annotation_task_name="IAA Dashboard UI",
        require_password=False,
        admin_api_key=ADMIN_KEY,
        # Two annotators on every item, so every item is an overlap item.
        num_annotators_per_item={"default": 2},
    )
    srv = FlaskTestServer(port=find_free_port(preferred_port=port_hint),
                          debug=False, config_file=config_file)
    assert srv.start_server(), "Failed to start Flask server"
    srv._wait_for_server_ready(timeout=15)
    return srv, test_dir


def _annotate(server, user, objects_for_item):
    session = requests.Session()
    session.post(f"{server.base_url}/register",
                 data={"email": user, "pass": "pw", "action": "signup"})
    session.post(f"{server.base_url}/auth", data={"email": user, "pass": "pw"})
    session.get(f"{server.base_url}/annotate")
    for instance_id in ITEM_IDS:
        session.get(f"{server.base_url}/annotate",
                    params={"instance_id": instance_id})
        response = session.post(
            f"{server.base_url}/updateinstance",
            json={"instance_id": instance_id,
                  "annotations": {
                      f"{SCHEMA}:::_data":
                          json.dumps(objects_for_item(instance_id))}})
        assert response.status_code == 200, response.text


@contextmanager
def project(name, port_hint, annotate):
    """One server at a time.

    Both projects cannot be up together: the server runs in this process, so
    two instances share the item/user state and config singletons and the
    newer one answers for both. The first version of this file kept them both
    alive and got byte-identical reports for projects whose JSON differed —
    see tests/unit/test_flask_test_server_isolation.py.
    """
    srv, test_dir = _start(name, port_hint)
    try:
        annotate(srv)
        yield srv
    finally:
        srv.stop_server()
        cleanup_test_directory(test_dir)


def seed_agreeing(srv):
    same = lambda _id: [box(0.10, 0.10), box(0.60, 0.60, label="sign")]
    _annotate(srv, "ui_alice", same)
    _annotate(srv, "ui_bob", same)


def seed_disagreeing(srv):
    # Disjoint boxes AND a different label: nothing to match on.
    _annotate(srv, "ui_carol", lambda _id: [box(0.05, 0.05)])
    _annotate(srv, "ui_dave", lambda _id: [box(0.70, 0.70, label="sign")])


def open_report(page, server):
    """Load the HTML report, carrying the admin key the route wants."""
    errors = []
    page.on("console", lambda m: errors.append(m.text)
            if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    # Scoped to this origin deliberately: an X-API-Key on every request rides
    # along to the Google Font the page loads, and the preflight for a header
    # that host does not allow shows up as a console error that looks like the
    # page is broken.
    page.route(
        f"{server.base_url}/**",
        lambda route: route.continue_(
            headers={**route.request.headers, "x-api-key": ADMIN_KEY}))
    page.goto(f"{server.base_url}/admin/iaa?format=html")
    page.wait_for_load_state("networkidle")
    return errors


class TestAgreementDashboard:

    def test_the_page_renders_the_image_schema_rather_than_n_a(self, page):
        """
        The presentation layer's failure mode: a computed statistic that the
        renderer cannot unwrap prints as "n/a" next to a perfectly good JSON
        body. The number existing is not the same as the number arriving.
        """
        with project("iaa_ui_agree", 9481, seed_agreeing) as server:
            open_report(page, server)
            body = page.inner_text("body")

        assert SCHEMA in body, body[:500]
        assert any(ch.isdigit() for ch in body), body[:500]
        assert "unsupported" not in body.lower(), body[:800]

    def test_the_page_loads_without_console_errors(self, page):
        with project("iaa_ui_agree2", 9483, seed_agreeing) as server:
            errors = open_report(page, server)
        # Optional subsystems answer 503 by design; a failed fetch is not a
        # script error and does not belong here.
        real = [e for e in errors if "Failed to load resource" not in e]
        assert not real, real

    def test_agreement_and_disagreement_do_not_render_the_same(self, page):
        """
        The test that makes the others mean something. A page that prints
        identical text whether annotators drew the same box or disjoint ones is
        reporting a template, not a measurement.

        The two projects run one after the other, never together — see
        `project()`.
        """
        with project("iaa_ui_agree3", 9484, seed_agreeing) as server:
            open_report(page, server)
            agreeing = page.inner_text("body")

        with project("iaa_ui_disagree", 9485, seed_disagreeing) as server:
            open_report(page, server)
            disagreeing = page.inner_text("body")

        assert agreeing != disagreeing, (
            "identical output for annotators who agreed and annotators who "
            "drew disjoint boxes with different labels")

    def test_perfect_agreement_reads_as_agreement(self, page):
        """
        Not merely "different from the disagreeing case". Two annotators who
        drew the same boxes must produce a report that says so, and the
        measured value for this fixture is 1.0.
        """
        with project("iaa_ui_agree4", 9486, seed_agreeing) as server:
            payload = requests.get(f"{server.base_url}/admin/iaa",
                                   headers={"X-API-Key": ADMIN_KEY}).json()
            open_report(page, server)
            body = page.inner_text("body")

        metrics = payload["schemas"][SCHEMA]["metrics"]
        assert metrics["mean_agreement"] == pytest.approx(1.0)
        assert metrics["detection_f1"] == pytest.approx(1.0)
        assert "1.0" in body or "100" in body, body[:600]

    def test_the_json_and_the_page_tell_the_same_story(self, page):
        """
        `?format=html` and the default JSON come from one computation. If the
        page says nothing while the JSON holds a report, the renderer dropped
        it — which is the exact bug this file guards.
        """
        with project("iaa_ui_agree5", 9487, seed_agreeing) as server:
            payload = requests.get(f"{server.base_url}/admin/iaa",
                                   headers={"X-API-Key": ADMIN_KEY}).json()
            assert payload, "the JSON report is empty"
            open_report(page, server)
            body = page.inner_text("body").lower()

        for name in (payload.get("schemas") or {}):
            assert name.lower() in body, (
                f"the JSON reports on {name!r} and the page never mentions it")
