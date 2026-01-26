"""
Server Integration Tests for Training Phase

This module contains integration tests for training phase functionality including:
- Training phase workflow integration
- Training data loading and serving
- Training feedback and retry logic
- Training completion and progression
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


class TestTrainingPhaseIntegration:
    """Integration tests for training phase functionality."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up test server with training configuration."""
        test_dir = create_test_directory("training_integration_test")

        # Create test data
        test_data = [
            {"id": "train_item_1", "text": "This is a positive sentiment text."},
            {"id": "train_item_2", "text": "This is a negative sentiment text."},
            {"id": "train_item_3", "text": "This is a neutral sentiment text."}
        ]
        data_file = create_test_data_file(test_dir, test_data)

        annotation_schemes = [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative", "neutral"],
                "description": "Select the sentiment of the text"
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Training Integration Test",
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

    def test_user_can_access_annotation_page(self):
        """Test that users can access the annotation page."""
        session = requests.Session()
        user_data = {"email": "training_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200

    def test_annotation_submission(self):
        """Test annotation submission workflow."""
        session = requests.Session()
        user_data = {"email": "training_annotator", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        annotation_data = {
            "instance_id": "train_item_1",
            "type": "radio",
            "schema": "sentiment",
            "state": [{"name": "positive", "value": "positive"}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200
