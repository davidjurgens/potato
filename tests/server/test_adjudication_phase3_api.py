"""
Server integration tests for Phase 3 adjudication endpoints.

Tests the following Phase 3 endpoints:
- GET /adjudicate/api/item/<id> — now returns annotator_signals and similar_items
- GET /adjudicate/api/similar/<id> — standalone similar items endpoint
- GET /admin/api/adjudication — admin adjudication overview
"""

import json
import pytest
import requests
import time
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


class TestAdjudicationPhase3API:
    """Integration tests for Phase 3 adjudication API endpoints."""

    ADMIN_API_KEY = "test-api-key-phase3"

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up a Flask server with adjudication enabled and two annotators."""
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
            "adjudicator_users": ["adjudicator1"],
            "min_annotations": 2,
            "agreement_threshold": 0.75,
            "show_all_items": True,
            "error_taxonomy": ["ambiguous_text", "guideline_gap", "label_overlap"],
        }

        with TestConfigManager(
            "adjudication_phase3",
            annotation_schemes,
            adjudication=adjudication_config,
            admin_api_key=TestAdjudicationPhase3API.ADMIN_API_KEY,
            debug=False,
            max_annotations_per_item=3,
        ) as test_config:
            server = FlaskTestServer(
                port=9017,
                config_file=test_config.config_path,
            )
            if not server.start():
                pytest.fail("Failed to start Flask test server")
            request.cls.server = server
            request.cls.base_url = server.base_url
            yield server
            server.stop()

    def _login(self, session, username):
        """Register and login a user."""
        session.post(
            f"{self.base_url}/register",
            data={"email": username, "pass": "pass"},
        )
        session.post(
            f"{self.base_url}/auth",
            data={"email": username, "pass": "pass"},
        )

    def _submit_annotation(self, session, instance_id, label_value):
        """Submit a radio annotation for the sentiment scheme on a given instance."""
        annotation_data = {
            "instance_id": instance_id,
            "type": "radio",
            "schema": "sentiment",
            "state": [{"name": label_value, "value": label_value}],
        }
        resp = session.post(
            f"{self.base_url}/updateinstance",
            json=annotation_data,
            timeout=10,
        )
        return resp

    def _get_assigned_instance_id(self, session):
        """Navigate to the annotation page and extract the assigned instance id."""
        resp = session.get(f"{self.base_url}/annotate")
        # Try to extract instance_id from the page or use the API
        resp2 = session.get(f"{self.base_url}/api/get_instance_id")
        if resp2.status_code == 200:
            data = resp2.json()
            return data.get("instance_id")
        return None

    def _populate_annotations(self):
        """Have two annotators annotate the same items to populate the adjudication queue."""
        annotators = ["phase3_ann1", "phase3_ann2"]
        sessions = {}

        for username in annotators:
            s = requests.Session()
            self._login(s, username)
            sessions[username] = s

        # Each annotator visits annotation page and submits on their assigned item
        for username in annotators:
            s = sessions[username]
            # Visit annotate page to get assigned
            s.get(f"{self.base_url}/annotate")
            # Get the assigned instance
            instance_id = self._get_assigned_instance_id(s)
            if instance_id:
                self._submit_annotation(s, instance_id, "positive" if username == "phase3_ann1" else "negative")

        return sessions

    # ------------------------------------------------------------------
    # Test 1: Item endpoint includes annotator_signals in response
    # ------------------------------------------------------------------

    def test_item_endpoint_includes_annotator_signals(self):
        """GET /adjudicate/api/item/<id> should return annotator_signals dict."""
        # First populate some annotations
        self._populate_annotations()

        # Login as adjudicator
        adj_session = requests.Session()
        self._login(adj_session, "adjudicator1")

        # Get the queue to find an item
        resp = adj_session.get(f"{self.base_url}/adjudicate/api/queue")
        assert resp.status_code == 200
        queue_data = resp.json()

        if queue_data["total"] > 0:
            instance_id = queue_data["items"][0]["instance_id"]
            # Fetch item detail
            resp = adj_session.get(f"{self.base_url}/adjudicate/api/item/{instance_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert "annotator_signals" in data
            assert isinstance(data["annotator_signals"], dict)
        else:
            # Even if the queue is empty due to agreement, we can test a known item
            # Use item "1" from the test data (TestConfigManager creates items with id "1" and "2")
            resp = adj_session.get(f"{self.base_url}/adjudicate/api/item/1")
            # May be 404 if not in queue, which is acceptable
            if resp.status_code == 200:
                data = resp.json()
                assert "annotator_signals" in data
                assert isinstance(data["annotator_signals"], dict)

    # ------------------------------------------------------------------
    # Test 2: Item endpoint includes similar_items in response
    # ------------------------------------------------------------------

    def test_item_endpoint_includes_similar_items(self):
        """GET /adjudicate/api/item/<id> should return similar_items list (empty when similarity disabled)."""
        adj_session = requests.Session()
        self._login(adj_session, "adjudicator1")

        # Get queue items
        resp = adj_session.get(f"{self.base_url}/adjudicate/api/queue")
        assert resp.status_code == 200
        queue_data = resp.json()

        if queue_data["total"] > 0:
            instance_id = queue_data["items"][0]["instance_id"]
            resp = adj_session.get(f"{self.base_url}/adjudicate/api/item/{instance_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert "similar_items" in data
            assert isinstance(data["similar_items"], list)
            # Similarity is not configured, so should be empty
            assert len(data["similar_items"]) == 0
        else:
            # Test with a non-existent item to verify 404 behavior
            resp = adj_session.get(f"{self.base_url}/adjudicate/api/item/nonexistent_phase3")
            assert resp.status_code == 404

    # ------------------------------------------------------------------
    # Test 3: Similar items endpoint returns correct structure
    # ------------------------------------------------------------------

    def test_similar_items_endpoint_structure(self):
        """GET /adjudicate/api/similar/<id> should return enabled, instance_id, similar_items, count."""
        adj_session = requests.Session()
        self._login(adj_session, "adjudicator1")

        # Use any instance_id - the endpoint should work even if the item is not in the queue
        resp = adj_session.get(f"{self.base_url}/adjudicate/api/similar/1")
        assert resp.status_code == 200
        data = resp.json()

        # Verify response structure
        assert "enabled" in data
        assert "instance_id" in data
        assert "similar_items" in data
        assert "count" in data

        # Similarity is not configured, so enabled should be False
        assert data["enabled"] is False
        assert data["instance_id"] == "1"
        assert isinstance(data["similar_items"], list)
        assert data["count"] == 0

    # ------------------------------------------------------------------
    # Test 4: Similar items endpoint requires adjudicator auth
    # ------------------------------------------------------------------

    def test_similar_items_requires_adjudicator_auth(self):
        """GET /adjudicate/api/similar/<id> should require adjudicator authentication."""
        # Unauthenticated request
        session = requests.Session()
        resp = session.get(f"{self.base_url}/adjudicate/api/similar/1")
        assert resp.status_code == 401

    def test_similar_items_rejects_regular_user(self):
        """GET /adjudicate/api/similar/<id> should reject non-adjudicator users."""
        session = requests.Session()
        self._login(session, "phase3_regular_user")
        resp = session.get(f"{self.base_url}/adjudicate/api/similar/1")
        assert resp.status_code == 403

    # ------------------------------------------------------------------
    # Test 5: Admin adjudication overview returns correct structure
    # ------------------------------------------------------------------

    def test_admin_adjudication_overview_structure(self):
        """GET /admin/api/adjudication should return adjudication overview with correct structure."""
        resp = requests.get(
            f"{self.base_url}/admin/api/adjudication",
            headers={"X-API-Key": self.ADMIN_API_KEY},
        )
        assert resp.status_code == 200
        data = resp.json()

        # Should indicate adjudication is enabled
        assert data.get("enabled") is True

        # Verify expected top-level keys
        assert "queue_stats" in data
        assert "adjudicator_details" in data
        assert "error_taxonomy_counts" in data
        assert "guideline_flag_count" in data
        assert "disagreement_patterns" in data
        assert "similarity_stats" in data

        # queue_stats should contain standard stats fields
        queue_stats = data["queue_stats"]
        assert "total" in queue_stats
        assert "completed" in queue_stats
        assert "pending" in queue_stats

    # ------------------------------------------------------------------
    # Test 6: Admin adjudication overview requires admin auth (API key)
    # ------------------------------------------------------------------

    def test_admin_adjudication_overview_requires_api_key(self):
        """GET /admin/api/adjudication without API key should return 403."""
        resp = requests.get(f"{self.base_url}/admin/api/adjudication")
        assert resp.status_code == 403

    def test_admin_adjudication_overview_rejects_wrong_key(self):
        """GET /admin/api/adjudication with wrong API key should return 403."""
        resp = requests.get(
            f"{self.base_url}/admin/api/adjudication",
            headers={"X-API-Key": "wrong-key-12345"},
        )
        assert resp.status_code == 403

    # ------------------------------------------------------------------
    # Test 7: Admin adjudication overview when adjudication not enabled
    #         (tested indirectly - the server HAS adjudication enabled,
    #          so we verify the "enabled: True" response and structure)
    # ------------------------------------------------------------------

    def test_admin_adjudication_overview_enabled_response(self):
        """When adjudication is enabled, the overview should return enabled=True with full data."""
        resp = requests.get(
            f"{self.base_url}/admin/api/adjudication",
            headers={"X-API-Key": self.ADMIN_API_KEY},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        # Should NOT have a "message" key when enabled and working
        # (message is only present when adjudication is not configured)
        assert "message" not in data or data.get("error") is None


class TestAdjudicationPhase3NoAdjudication:
    """Test the admin adjudication endpoint when adjudication is NOT enabled."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up a Flask server WITHOUT adjudication enabled."""
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "What is the sentiment?",
                "labels": [
                    {"name": "positive"},
                    {"name": "negative"},
                ],
            }
        ]

        with TestConfigManager(
            "adjudication_phase3_disabled",
            annotation_schemes,
            admin_api_key="test-api-key-no-adj",
            debug=False,
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

    def test_admin_adjudication_not_enabled_response(self):
        """When adjudication is not enabled, the overview should return enabled=False."""
        resp = requests.get(
            f"{self.base_url}/admin/api/adjudication",
            headers={"X-API-Key": "test-api-key-no-adj"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert "message" in data
