"""
Server integration tests for the MACE Competence Estimation API.

Tests:
- GET /admin/api/mace/overview
- GET /admin/api/mace/predictions?schema=X
- POST /admin/api/mace/trigger
- Admin auth required for all endpoints
- MACE runs after annotations reach threshold
"""

import json
import pytest
import requests
import time
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    TestConfigManager,
    create_test_directory,
    create_test_data_file,
    create_test_config,
)


class TestMACEAPI:
    """Integration tests for MACE admin API endpoints."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up a Flask server with MACE enabled."""
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

        mace_config = {
            "enabled": True,
            "trigger_every_n": 4,
            "min_annotations_per_item": 2,
            "min_items": 2,
            "num_restarts": 3,
            "num_iters": 20,
        }

        # Create test data with enough items
        test_dir = create_test_directory("mace_api")
        test_data = [
            {"id": f"item_{i}", "text": f"Test item {i} for MACE testing."}
            for i in range(1, 6)
        ]
        data_file = create_test_data_file(test_dir, test_data)

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            mace=mace_config,
            admin_api_key="test-mace-key",
            debug=True,
            max_annotations_per_item=5,
        )

        server = FlaskTestServer(
            port=None,
            config_file=config_file,
        )
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        request.cls.server = server
        request.cls.base_url = server.base_url
        yield server
        server.stop()

    def _login(self, session, username="testuser"):
        """Register and login a user."""
        session.post(
            f"{self.base_url}/register",
            data={"email": username, "pass": "pass"},
        )
        session.post(
            f"{self.base_url}/auth",
            data={"email": username, "pass": "pass"},
        )

    def _annotate(self, session, instance_id, label_name):
        """Submit a radio annotation using backend 'label' type."""
        annotation_data = {
            "instance_id": instance_id,
            "type": "label",
            "schema": "sentiment",
            "state": [{"name": label_name, "value": label_name}],
        }
        resp = session.post(
            f"{self.base_url}/updateinstance",
            json=annotation_data,
            timeout=10,
        )
        return resp

    def _admin_get(self, path, params=None):
        """Make an admin API GET request with API key."""
        return requests.get(
            f"{self.base_url}{path}",
            headers={"X-API-Key": "test-mace-key"},
            params=params,
            timeout=10,
        )

    def _admin_post(self, path, json_data=None):
        """Make an admin API POST request with API key."""
        return requests.post(
            f"{self.base_url}{path}",
            headers={"X-API-Key": "test-mace-key"},
            json=json_data,
            timeout=10,
        )

    # ========================================================================
    # Auth Tests
    # ========================================================================

    def test_mace_overview_requires_admin(self):
        """Overview endpoint should require admin API key."""
        resp = requests.get(f"{self.base_url}/admin/api/mace/overview", timeout=10)
        assert resp.status_code == 403

    def test_mace_predictions_requires_admin(self):
        """Predictions endpoint should require admin API key."""
        resp = requests.get(
            f"{self.base_url}/admin/api/mace/predictions",
            params={"schema": "sentiment"},
            timeout=10,
        )
        assert resp.status_code == 403

    def test_mace_trigger_requires_admin(self):
        """Trigger endpoint should require admin API key."""
        resp = requests.post(f"{self.base_url}/admin/api/mace/trigger", timeout=10)
        assert resp.status_code == 403

    # ========================================================================
    # Overview Tests
    # ========================================================================

    def test_mace_overview_before_annotations(self):
        """Overview should show enabled but no results before any annotations."""
        resp = self._admin_get("/admin/api/mace/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        # May or may not have results depending on cached state
        # Just verify the response structure
        assert "has_results" in data

    # ========================================================================
    # Annotation + Trigger Tests
    # ========================================================================

    def test_submit_annotations_and_trigger(self):
        """Submit annotations from multiple users and manually trigger MACE."""
        # Create 3 annotators
        users = ["mace_user_1", "mace_user_2", "mace_user_3"]
        sessions = {}
        for username in users:
            s = requests.Session()
            self._login(s, username)
            sessions[username] = s

        # Have each user annotate the same items
        items_labels = {
            "item_1": "positive",
            "item_2": "negative",
            "item_3": "positive",
        }

        for username in users:
            for item_id, label in items_labels.items():
                resp = self._annotate(sessions[username], item_id, label)
                assert resp.status_code == 200, (
                    f"Annotation failed for {username}/{item_id}: {resp.text}"
                )
                resp_data = resp.json()
                assert resp_data.get("status") == "success", (
                    f"Annotation not stored for {username}/{item_id}: {resp_data}"
                )

        # Manually trigger MACE
        resp = self._admin_post("/admin/api/mace/trigger")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["schemas_processed"] >= 1
        assert "sentiment" in data["schemas"]

    def test_mace_overview_after_trigger(self):
        """After triggering, overview should have results."""
        resp = self._admin_get("/admin/api/mace/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["has_results"] is True
        assert len(data["schemas"]) >= 1

        # Check annotator competence is present
        assert len(data["annotator_competence"]) >= 1
        for uid, info in data["annotator_competence"].items():
            assert "average" in info
            assert 0.0 <= info["average"] <= 1.0

    def test_mace_predictions_for_schema(self):
        """Predictions endpoint should return predicted labels."""
        resp = self._admin_get(
            "/admin/api/mace/predictions",
            params={"schema": "sentiment"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "predicted_labels" in data
        assert "label_entropy" in data
        assert len(data["predicted_labels"]) >= 1

    def test_mace_predictions_for_instance(self):
        """Predictions endpoint with instance_id filter."""
        resp = self._admin_get(
            "/admin/api/mace/predictions",
            params={"schema": "sentiment", "instance_id": "item_1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "predicted_label" in data
        assert "entropy" in data
        assert data["predicted_label"] in ("positive", "negative")

    def test_mace_predictions_missing_schema(self):
        """Predictions endpoint should require schema parameter."""
        resp = self._admin_get("/admin/api/mace/predictions")
        assert resp.status_code == 400

    def test_mace_predictions_unknown_schema(self):
        """Predictions for unknown schema should return error."""
        resp = self._admin_get(
            "/admin/api/mace/predictions",
            params={"schema": "nonexistent"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data


class TestMACEDisabled:
    """Test that MACE endpoints work gracefully when disabled."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up a Flask server without MACE."""
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "Sentiment",
                "labels": [{"name": "positive"}, {"name": "negative"}],
            }
        ]

        with TestConfigManager(
            "mace_disabled",
            annotation_schemes,
            admin_api_key="test-key",
            debug=True,
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

    def test_overview_disabled(self):
        """Overview should indicate MACE is not configured."""
        resp = requests.get(
            f"{self.base_url}/admin/api/mace/overview",
            headers={"X-API-Key": "test-key"},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("enabled") is False or "not configured" in data.get("message", "").lower()

    def test_trigger_disabled(self):
        """Trigger should return error when MACE is not enabled."""
        resp = requests.post(
            f"{self.base_url}/admin/api/mace/trigger",
            headers={"X-API-Key": "test-key"},
            timeout=10,
        )
        assert resp.status_code == 400
