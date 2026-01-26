"""
Tests for annotation output persistence across different annotation types.

This module tests that annotations are properly saved to output files
for various annotation types.
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


class TestAnnotationOutputPersistence:
    """Test annotation output persistence for different annotation types."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with multiple annotation types."""
        test_dir = create_test_directory("annotation_output_persistence_test")

        test_data = [
            {"id": "persist_test_1", "text": "This is a test text for annotation persistence."},
            {"id": "persist_test_2", "text": "Another test text for annotation testing."}
        ]
        data_file = create_test_data_file(test_dir, test_data)

        # Create multiple annotation schemes
        annotation_schemes = [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative", "neutral"],
                "description": "Select sentiment"
            },
            {
                "name": "agreement",
                "annotation_type": "likert",
                "min_label": "1",
                "max_label": "5",
                "size": 5,
                "description": "Rate agreement"
            },
            {
                "name": "rating",
                "annotation_type": "slider",
                "min_value": 0,
                "max_value": 100,
                "starting_value": 50,
                "description": "Rate on slider"
            },
            {
                "name": "feedback",
                "annotation_type": "text",
                "description": "Enter feedback"
            },
            {
                "name": "topics",
                "annotation_type": "multiselect",
                "labels": ["technology", "science", "politics", "entertainment"],
                "description": "Select topics"
            },
            {
                "name": "entities",
                "annotation_type": "span",
                "labels": ["person", "location", "organization"],
                "description": "Mark entities"
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Output Persistence Test",
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

    def test_radio_annotation_persistence(self):
        """Test radio annotation persistence."""
        session = requests.Session()
        user_data = {"email": "radio_persist_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        annotation_data = {
            "instance_id": "persist_test_1",
            "type": "radio",
            "schema": "sentiment",
            "state": [{"name": "positive", "value": "positive"}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200

    def test_likert_annotation_persistence(self):
        """Test likert annotation persistence."""
        session = requests.Session()
        user_data = {"email": "likert_persist_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        annotation_data = {
            "instance_id": "persist_test_1",
            "type": "likert",
            "schema": "agreement",
            "state": [{"name": "agreement", "value": "3"}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200

    def test_slider_annotation_persistence(self):
        """Test slider annotation persistence."""
        session = requests.Session()
        user_data = {"email": "slider_persist_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        annotation_data = {
            "instance_id": "persist_test_1",
            "type": "slider",
            "schema": "rating",
            "state": [{"name": "rating", "value": "75"}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200

    def test_text_annotation_persistence(self):
        """Test text annotation persistence."""
        session = requests.Session()
        user_data = {"email": "text_persist_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        annotation_data = {
            "instance_id": "persist_test_1",
            "type": "text",
            "schema": "feedback",
            "state": [{"name": "feedback", "value": "This is test feedback."}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200

    def test_span_annotation_persistence(self):
        """Test span annotation persistence."""
        session = requests.Session()
        user_data = {"email": "span_persist_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        annotation_data = {
            "instance_id": "persist_test_1",
            "type": "span",
            "schema": "entities",
            "state": [{"name": "person", "start": 0, "end": 5, "value": "person"}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200
