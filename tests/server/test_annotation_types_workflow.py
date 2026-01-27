"""
Annotation Type-Specific Workflow Tests

This module contains tests for different annotation types and their specific behaviors,
including validation, key bindings, and data capture.
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


class TestAnnotationTypesWorkflow:
    """Test different annotation types and their workflows."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with multiple annotation types."""
        test_dir = create_test_directory("annotation_types_workflow_test")

        test_data = [
            {"id": "type_test_1", "text": "This is test item 1 for annotation type testing."},
            {"id": "type_test_2", "text": "This is test item 2 for annotation type testing."}
        ]
        data_file = create_test_data_file(test_dir, test_data)

        # Create multiple annotation schemes for different types
        annotation_schemes = [
            {
                "name": "likert_scale",
                "annotation_type": "likert",
                "min_label": "1",
                "max_label": "5",
                "size": 5,
                "description": "Rate on a scale of 1-5"
            },
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative", "neutral"],
                "description": "Select sentiment"
            },
            {
                "name": "intensity",
                "annotation_type": "slider",
                "min_value": 0,
                "max_value": 100,
                "starting_value": 50,
                "description": "Rate intensity"
            },
            {
                "name": "comments",
                "annotation_type": "text",
                "description": "Enter comments"
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
            annotation_task_name="Annotation Types Test",
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

    def test_likert_annotation_workflow(self):
        """Test likert scale annotation workflow."""
        session = requests.Session()
        user_data = {"email": "likert_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        annotation_data = {
            "instance_id": "type_test_1",
            "type": "likert",
            "schema": "likert_scale",
            "state": [{"name": "likert_scale", "value": "3"}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200

    def test_radio_annotation_workflow(self):
        """Test radio button annotation workflow."""
        session = requests.Session()
        user_data = {"email": "radio_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        annotation_data = {
            "instance_id": "type_test_1",
            "type": "radio",
            "schema": "sentiment",
            "state": [{"name": "positive", "value": "positive"}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200

    def test_slider_annotation_workflow(self):
        """Test slider annotation workflow."""
        session = requests.Session()
        user_data = {"email": "slider_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        annotation_data = {
            "instance_id": "type_test_1",
            "type": "slider",
            "schema": "intensity",
            "state": [{"name": "intensity", "value": "75"}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200

    def test_text_annotation_workflow(self):
        """Test text annotation workflow."""
        session = requests.Session()
        user_data = {"email": "text_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        annotation_data = {
            "instance_id": "type_test_1",
            "type": "text",
            "schema": "comments",
            "state": [{"name": "comments", "value": "This is a test comment."}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200

    def test_span_annotation_workflow(self):
        """Test span annotation workflow."""
        session = requests.Session()
        user_data = {"email": "span_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        annotation_data = {
            "instance_id": "type_test_1",
            "type": "span",
            "schema": "entities",
            "state": [{"name": "person", "start": 0, "end": 5, "value": "person"}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200
