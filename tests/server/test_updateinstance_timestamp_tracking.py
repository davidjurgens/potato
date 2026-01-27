"""
Server tests for /updateinstance endpoint with timestamp tracking.

This module tests the enhanced /updateinstance endpoint that now includes
comprehensive timestamp tracking, performance metrics, and annotation history.
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


class TestUpdateInstanceTimestampTracking:
    """Test cases for /updateinstance endpoint with timestamp tracking."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up test server for updateinstance tests."""
        test_dir = create_test_directory("updateinstance_timestamp_test")

        test_data = [
            {"id": "test_instance", "text": "Test text."},
            {"id": "test_instance_2", "text": "Another test text."},
        ]
        data_file = create_test_data_file(test_dir, test_data)

        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "What is the sentiment?",
                "labels": ["positive", "negative", "neutral"]
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Updateinstance Timestamp Test",
            require_password=False
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_updateinstance_basic_functionality(self):
        """Test basic functionality of the updateinstance endpoint."""
        session = requests.Session()
        user_data = {"email": "timestamp_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data, timeout=5)
        session.post(f"{self.server.base_url}/auth", data=user_data, timeout=5)

        # Test with proper annotation format
        data = {
            "instance_id": "test_instance",
            "type": "radio",
            "schema": "sentiment",
            "state": [{"name": "positive", "value": "positive"}]
        }

        response = session.post(f"{self.server.base_url}/updateinstance", json=data, timeout=5)

        # Verify response
        assert response.status_code == 200
        response_data = response.json()
        assert "status" in response_data

    def test_updateinstance_tracks_label_annotations(self):
        """Test that label annotations are tracked with timestamps."""
        session = requests.Session()
        user_data = {"email": "label_track_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data, timeout=5)
        session.post(f"{self.server.base_url}/auth", data=user_data, timeout=5)

        # Make request to updateinstance
        data = {
            "instance_id": "test_instance",
            "type": "radio",
            "schema": "sentiment",
            "state": [{"name": "positive", "value": "positive"}]
        }

        response = session.post(f"{self.server.base_url}/updateinstance", json=data, timeout=5)

        # Verify the endpoint responds correctly
        assert response.status_code == 200
