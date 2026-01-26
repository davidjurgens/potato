"""
Annotation Workflow Integration Tests

This module contains comprehensive tests that demonstrate complete annotation workflows
using the production endpoints. These tests verify the entire system from data creation
to annotation completion.
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


class TestAnnotationWorkflowIntegration:
    """Test complete annotation workflow integration."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server for workflow integration tests."""
        test_dir = create_test_directory("annotation_workflow_integration_test")

        test_data = [
            {"id": "item_1", "text": "This is a positive statement about the product."},
            {"id": "item_2", "text": "This is a negative statement about the product."},
            {"id": "item_3", "text": "This is a neutral statement about the product."}
        ]
        data_file = create_test_data_file(test_dir, test_data)

        annotation_schemes = [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative", "neutral"],
                "description": "Select the sentiment"
            },
            {
                "name": "confidence",
                "annotation_type": "likert",
                "min_label": "1",
                "max_label": "5",
                "size": 5,
                "description": "Rate your confidence"
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Annotation Integration Test Task",
            require_password=False,
            max_annotations_per_user=10
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_complete_annotation_workflow(self):
        """Test complete annotation workflow from registration to annotation."""
        session = requests.Session()
        user_data = {"email": "workflow_user", "pass": "test_password"}

        # Register user
        reg_response = session.post(f"{self.server.base_url}/register", data=user_data)
        assert reg_response.status_code in [200, 302]

        # Login user
        login_response = session.post(f"{self.server.base_url}/auth", data=user_data)
        assert login_response.status_code in [200, 302]

        # Access annotation page
        annotate_response = session.get(f"{self.server.base_url}/annotate")
        assert annotate_response.status_code == 200

        # Submit annotation
        annotation_data = {
            "instance_id": "item_1",
            "type": "radio",
            "schema": "sentiment",
            "state": [{"name": "positive", "value": "positive"}]
        }
        submit_response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert submit_response.status_code == 200

    def test_multi_annotation_workflow(self):
        """Test annotating multiple items in sequence."""
        session = requests.Session()
        user_data = {"email": "multi_workflow_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        # Submit annotations for multiple items
        for i in range(1, 4):
            annotation_data = {
                "instance_id": f"item_{i}",
                "type": "radio",
                "schema": "sentiment",
                "state": [{"name": "neutral", "value": "neutral"}]
            }
            response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
            assert response.status_code == 200
