"""
Tests for stale autosave fix: verifying that update_instance() properly validates
instance_id and rejects None/empty/unassigned instances.
"""
import pytest
from unittest.mock import patch, MagicMock
import json

# We test at the Flask route level using a test client
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager
import requests


class TestStaleAutosave:
    """Test that update_instance rejects invalid instance_ids."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "labels": ["positive", "negative"],
                "description": "Select sentiment",
            }
        ]
        with TestConfigManager(
            "stale_autosave_test", annotation_schemes, num_items=3
        ) as test_config:
            server = FlaskTestServer(port=9042, config_file=test_config.config_path)
            if not server.start():
                pytest.fail("Failed to start server")
            request.cls.server = server
            yield server
            server.stop()

    _user_counter = 0

    def _login(self):
        """Helper to register and login a unique user, returning a session."""
        TestStaleAutosave._user_counter += 1
        username = f"stale_test_user_{TestStaleAutosave._user_counter}"
        s = requests.Session()
        s.post(
            f"{self.server.base_url}/register",
            data={"email": username, "pass": "pw"},
        )
        return s

    def test_none_instance_id_rejected(self):
        """instance_id=None is a 400, not a 200 with an error body.

        The status code is the half the page reads: `saveAnnotations` checks
        `response.ok` first, so a refusal at 200 was indistinguishable from a
        stored save.
        """
        s = self._login()
        r = s.post(
            f"{self.server.base_url}/updateinstance",
            json={"instance_id": None, "annotations": {}},
        )
        assert r.status_code == 400
        data = r.json()
        assert data["status"] == "error"
        assert "instance_id" in data["message"].lower() or "missing" in data["message"].lower()

    def test_empty_instance_id_rejected(self):
        """instance_id='' is a 400."""
        s = self._login()
        r = s.post(
            f"{self.server.base_url}/updateinstance",
            json={"instance_id": "", "annotations": {}},
        )
        assert r.status_code == 400
        data = r.json()
        assert data["status"] == "error"

    def test_valid_instance_id_accepted(self):
        """Sending a valid assigned instance_id should succeed."""
        s = self._login()
        # First get the annotation page to see what instance we're on
        r = s.get(f"{self.server.base_url}/annotate")
        assert r.status_code == 200

        # Send update with a valid instance ID (instance "1" should be assigned)
        r = s.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "1",
                # `schema:::label`, not the nested stored shape: nesting names
                # no label, so this test used to pass while storing nothing.
                "annotations": {"sentiment:::positive": "true"},
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") != "error", f"Expected success, got: {data}"

        # "Accepted" has to mean stored. With the nested payload this test used
        # to send, every key was skipped and the 200 said nothing.
        stored = s.get(f"{self.server.base_url}/get_annotations",
                       params={"instance_id": "1"}).json()
        assert "positive" in str(stored.get("label_annotations", {})), (
            f"the annotation was not stored: {stored}")
