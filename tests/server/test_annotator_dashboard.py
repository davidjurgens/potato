"""
Integration tests for the opt-in annotator progress dashboard.

Covers:
- Default-off behavior (feature absent => /progress acts like it doesn't exist).
- Enabled behavior: authenticated annotator gets the page + JSON summary.
- Read-only privacy contract: a user never sees another annotator's identity,
  and personal stats reflect only the requesting user.
- Auth: unauthenticated access to the summary API is rejected.
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


SCHEMES = [
    {
        "annotation_type": "radio",
        "name": "sentiment",
        "description": "Sentiment",
        "labels": ["positive", "neutral", "negative"],
    }
]


def _auth(base_url, email, password="pw"):
    s = requests.Session()
    s.post(f"{base_url}/register", data={"email": email, "pass": password})
    s.post(f"{base_url}/auth", data={"email": email, "pass": password})
    return s


class TestDashboardDisabledByDefault:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        with TestConfigManager("annot_dash_off", SCHEMES, num_items=4) as tc:
            server = FlaskTestServer(port=9163, config_file=tc.config_path)
            if not server.start():
                pytest.fail("Failed to start Flask server")
            yield server
            server.stop()

    def test_summary_api_404_when_disabled(self, flask_server):
        s = _auth(flask_server.base_url, "off_user")
        r = s.get(f"{flask_server.base_url}/progress/api/summary")
        assert r.status_code == 404

    def test_progress_page_does_not_render_dashboard_when_disabled(self, flask_server):
        s = _auth(flask_server.base_url, "off_user2")
        # /progress falls back to home() when disabled; it must NOT render the
        # dashboard template.
        r = s.get(f"{flask_server.base_url}/progress")
        assert "Your annotation progress" not in r.text


class TestDashboardEnabled:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        with TestConfigManager(
            "annot_dash_on",
            SCHEMES,
            num_items=4,
            additional_config={
                "annotator_dashboard": {
                    "enabled": True,
                    "show_project_progress": True,
                    "show_personal_progress": True,
                    "show_active_annotators": False,
                }
            },
        ) as tc:
            server = FlaskTestServer(port=9164, config_file=tc.config_path)
            if not server.start():
                pytest.fail("Failed to start Flask server")
            yield server
            server.stop()

    def test_summary_requires_auth(self, flask_server):
        r = requests.get(f"{flask_server.base_url}/progress/api/summary")
        assert r.status_code == 401

    def test_progress_page_renders_for_annotator(self, flask_server):
        s = _auth(flask_server.base_url, "alice")
        r = s.get(f"{flask_server.base_url}/progress")
        assert r.status_code == 200
        assert "Your annotation progress" in r.text

    def test_summary_returns_project_and_personal(self, flask_server):
        s = _auth(flask_server.base_url, "bob")
        # Touch the annotation page so the user has assignments.
        s.get(f"{flask_server.base_url}/annotate")
        r = s.get(f"{flask_server.base_url}/progress/api/summary")
        assert r.status_code == 200
        data = r.json()
        assert "project" in data
        assert "personal" in data
        # Project aggregate keys
        for key in (
            "total_items",
            "items_with_annotations",
            "completion_percentage",
            "total_annotations",
        ):
            assert key in data["project"]
        # active_annotators gated off -> absent
        assert "active_annotators" not in data["project"]
        # Personal keys
        for key in ("annotated", "assigned", "completion_percentage"):
            assert key in data["personal"]

    def test_summary_exposes_no_other_user_identity(self, flask_server):
        # Two distinct annotators exist; carol must not see dave's id anywhere.
        _auth(flask_server.base_url, "dave_unique_name")
        carol = _auth(flask_server.base_url, "carol")
        carol.get(f"{flask_server.base_url}/annotate")
        r = carol.get(f"{flask_server.base_url}/progress/api/summary")
        assert r.status_code == 200
        body = r.text
        assert "dave_unique_name" not in body
        # No action/mutation affordances leak through the read-only API.
        assert "set_instances" not in body
        assert "reclaim" not in body
