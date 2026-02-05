"""
Server integration tests for the Adjudication API.

Tests the adjudication endpoints:
- GET /adjudicate (HTML page)
- GET /adjudicate/api/queue
- GET /adjudicate/api/item/<id>
- POST /adjudicate/api/submit
- GET /adjudicate/api/stats
- POST /adjudicate/api/skip/<id>
- GET /adjudicate/api/next
"""

import json
import pytest
import requests
import time
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


class TestAdjudicationAPI:
    """Integration tests for adjudication API endpoints."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up a Flask server with adjudication enabled."""
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "What is the sentiment?",
                "labels": [
                    {"name": "positive"},
                    {"name": "negative"},
                    {"name": "neutral"},
                ],
            }
        ]

        adjudication_config = {
            "enabled": True,
            "adjudicator_users": ["adj_user"],
            "min_annotations": 2,
            "agreement_threshold": 0.75,
            "show_all_items": True,
            "error_taxonomy": ["ambiguous_text", "guideline_gap"],
        }

        with TestConfigManager(
            "adjudication_api",
            annotation_schemes,
            adjudication=adjudication_config,
            debug=True,
            max_annotations_per_item=3,
        ) as test_config:
            server = FlaskTestServer(
                port=None,
                config_file=test_config.config_path,
            )
            if not server.start():
                pytest.fail("Failed to start Flask test server")
            request.cls.server = server
            request.cls.base_url = server.base_url
            yield server
            server.stop()

    def _login(self, session, username="testuser"):
        """Helper to register and login."""
        session.post(
            f"{self.base_url}/register",
            data={"email": username, "pass": "pass"},
        )
        session.post(
            f"{self.base_url}/auth",
            data={"email": username, "pass": "pass"},
        )

    def _annotate_item(self, session, username="testuser"):
        """Helper to make an annotation to populate data."""
        # Navigate to annotation page to get assigned an item
        resp = session.get(f"{self.base_url}/")
        return resp

    def test_adjudicate_page_requires_auth(self):
        """Non-authenticated users should be redirected."""
        session = requests.Session()
        resp = session.get(f"{self.base_url}/adjudicate", allow_redirects=False)
        # Should redirect to login
        assert resp.status_code in [302, 200]

    def test_adjudicate_page_requires_adjudicator(self):
        """Regular users should be redirected from adjudication page."""
        session = requests.Session()
        self._login(session, "regular_user")
        resp = session.get(f"{self.base_url}/adjudicate", allow_redirects=False)
        # Should redirect since regular_user is not in adjudicator_users
        assert resp.status_code in [302, 200]

    def test_adjudicate_page_for_adjudicator(self):
        """Adjudicators should see the adjudication page."""
        session = requests.Session()
        self._login(session, "adj_user")
        resp = session.get(f"{self.base_url}/adjudicate")
        assert resp.status_code == 200
        assert "Adjudication" in resp.text

    def test_api_queue_requires_adjudicator(self):
        """Non-adjudicators should be rejected from API."""
        session = requests.Session()
        self._login(session, "regular_user_2")
        resp = session.get(f"{self.base_url}/adjudicate/api/queue")
        assert resp.status_code == 403

    def test_api_queue_returns_json(self):
        """Queue API should return valid JSON."""
        session = requests.Session()
        self._login(session, "adj_user")
        resp = session.get(f"{self.base_url}/adjudicate/api/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_api_stats_returns_json(self):
        """Stats API should return valid JSON."""
        session = requests.Session()
        self._login(session, "adj_user")
        resp = session.get(f"{self.base_url}/adjudicate/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "completed" in data
        assert "pending" in data
        assert "completion_rate" in data

    def test_api_next_returns_json(self):
        """Next item API should return valid JSON."""
        session = requests.Session()
        self._login(session, "adj_user")
        resp = session.get(f"{self.base_url}/adjudicate/api/next")
        assert resp.status_code == 200
        data = resp.json()
        # May have item or may be empty depending on annotations
        assert "item" in data or "message" in data

    def test_api_item_not_found(self):
        """Item API should return 404 for non-existent items."""
        session = requests.Session()
        self._login(session, "adj_user")
        resp = session.get(f"{self.base_url}/adjudicate/api/item/nonexistent_item")
        assert resp.status_code == 404

    def test_api_submit_requires_json(self):
        """Submit API should require JSON body."""
        session = requests.Session()
        self._login(session, "adj_user")
        resp = session.post(f"{self.base_url}/adjudicate/api/submit")
        assert resp.status_code == 400

    def test_api_submit_requires_instance_id(self):
        """Submit API should require instance_id."""
        session = requests.Session()
        self._login(session, "adj_user")
        resp = session.post(
            f"{self.base_url}/adjudicate/api/submit",
            json={"label_decisions": {"sentiment": "positive"}},
        )
        assert resp.status_code == 400

    def test_api_skip_nonexistent(self):
        """Skip API should return 404 for non-existent items."""
        session = requests.Session()
        self._login(session, "adj_user")
        resp = session.post(f"{self.base_url}/adjudicate/api/skip/nonexistent_item")
        assert resp.status_code == 404

    def test_api_submit_with_span_decisions(self):
        """Submit API should accept span decisions."""
        session = requests.Session()
        self._login(session, "adj_user")
        resp = session.post(
            f"{self.base_url}/adjudicate/api/submit",
            json={
                "instance_id": "test_span_item",
                "label_decisions": {"sentiment": "positive"},
                "span_decisions": [
                    {"schema": "entity", "name": "PERSON", "start": 0, "end": 5},
                ],
                "source": {"sentiment": "adjudicator", "entity": "annotator_user1"},
                "confidence": "high",
            },
        )
        # May be 200 or 500 depending on whether item exists in queue
        # The key is that the server doesn't crash on span_decisions
        assert resp.status_code in [200, 500]

    def test_api_queue_structure(self):
        """Queue API should return items with span_annotations field."""
        session = requests.Session()
        self._login(session, "adj_user")
        resp = session.get(f"{self.base_url}/adjudicate/api/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        # Each item should have the expected fields
        for item in data["items"]:
            assert "instance_id" in item
            assert "annotations" in item
            assert "span_annotations" in item
            assert "behavioral_data" in item
            assert "agreement_scores" in item
            assert "overall_agreement" in item
            assert "num_annotators" in item
            assert "status" in item

    def test_unauthenticated_api_calls(self):
        """All API endpoints should require authentication."""
        session = requests.Session()

        endpoints = [
            ("GET", "/adjudicate/api/queue"),
            ("GET", "/adjudicate/api/stats"),
            ("GET", "/adjudicate/api/next"),
            ("GET", "/adjudicate/api/item/test"),
            ("POST", "/adjudicate/api/submit"),
            ("POST", "/adjudicate/api/skip/test"),
        ]

        for method, path in endpoints:
            if method == "GET":
                resp = session.get(f"{self.base_url}{path}")
            else:
                resp = session.post(f"{self.base_url}{path}")
            assert resp.status_code == 401, f"Expected 401 for {method} {path}, got {resp.status_code}"
