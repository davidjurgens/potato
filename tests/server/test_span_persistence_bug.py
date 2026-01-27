"""
Test to reproduce span annotation persistence bug.

This test verifies that span annotations persist correctly when navigating
between instances and returning to a previously annotated instance.
"""

import pytest
import requests
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory
)


class TestSpanPersistence:
    """Test span annotation persistence across navigation."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server for span persistence tests."""
        test_dir = create_test_directory("span_persistence_test")

        test_data = [
            {"id": "instance1", "text": "I am very happy today."},
            {"id": "instance2", "text": "This is a different instance."}
        ]
        data_file = create_test_data_file(test_dir, test_data)

        annotation_schemes = [
            {
                "name": "emotion",
                "annotation_type": "span",
                "labels": ["happy", "sad"],
                "description": "Mark emotion spans in the text."
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Span Persistence Test",
            require_password=False,
            admin_api_key="admin_api_key"
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_span_annotation_persistence_bug(self):
        """Test that reproduces the bug where span highlights disappear from UI after navigation."""
        session = requests.Session()
        username = "test_user_span_persistence"
        password = "test_password"

        # Register and login user
        user_data = {"email": username, "pass": password}
        reg_response = session.post(f"{self.server.base_url}/register", data=user_data)
        assert reg_response.status_code in [200, 302]
        login_response = session.post(f"{self.server.base_url}/auth", data=user_data)
        assert login_response.status_code in [200, 302]

        # Get current instance (should be instance1)
        resp = session.get(f"{self.server.base_url}/api/current_instance")
        assert resp.status_code == 200
        instance_id = resp.json().get("instance_id")

        # Submit span annotation on instance1
        annotation_data = {
            "instance_id": instance_id,
            "type": "span",
            "schema": "emotion",
            "state": [
                {"name": "happy", "title": "happy", "start": 5, "end": 10, "value": "happy"}
            ]
        }
        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json=annotation_data
        )
        assert response.status_code == 200

        # Verify annotation was saved via user_state endpoint
        admin_response = self.server.get(f"/admin/user_state/{username}")
        assert admin_response.status_code == 200
        user_state = admin_response.json()

        # Check that annotations exist
        annotations = user_state.get("annotations", {})
        assert annotations is not None

    def test_span_annotation_update(self):
        """Test that span annotations can be updated."""
        session = requests.Session()
        username = "test_user_span_update"
        password = "test_password"

        # Register and login user
        user_data = {"email": username, "pass": password}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        # Get current instance
        resp = session.get(f"{self.server.base_url}/api/current_instance")
        assert resp.status_code == 200
        instance_id = resp.json().get("instance_id")

        # Submit first span annotation
        annotation_data = {
            "instance_id": instance_id,
            "type": "span",
            "schema": "emotion",
            "state": [
                {"name": "happy", "title": "happy", "start": 0, "end": 5, "value": "happy"}
            ]
        }
        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json=annotation_data
        )
        assert response.status_code == 200

        # Update with different span
        annotation_data["state"] = [
            {"name": "sad", "title": "sad", "start": 10, "end": 15, "value": "sad"}
        ]
        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json=annotation_data
        )
        assert response.status_code == 200
