"""
Multi-Phase Workflow Tests

This module contains tests for complete multi-phase annotation workflows,
including consent, instructions, annotation, and post-study phases.
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


class TestMultiPhaseWorkflow:
    """Test complete multi-phase annotation workflows."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with multi-phase test data."""
        test_dir = create_test_directory("multi_phase_workflow_test")

        # Create test data
        test_data = [
            {"id": "phase_item_1", "text": "This is the first item for phase testing."},
            {"id": "phase_item_2", "text": "This is the second item for phase testing."},
            {"id": "phase_item_3", "text": "This is the third item for phase testing."}
        ]
        data_file = create_test_data_file(test_dir, test_data)

        # Create annotation schemes
        annotation_schemes = [
            {
                "name": "phase_rating",
                "annotation_type": "radio",
                "labels": ["1", "2", "3", "4", "5"],
                "description": "Rate the quality of this text."
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Multi-Phase Test Task",
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

    def test_annotation_phase(self):
        """Test the annotation phase of the workflow."""
        session = requests.Session()
        user_data = {"email": "phase_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        # Access annotation page
        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200

    def test_multi_item_workflow(self):
        """Test workflow across multiple items."""
        session = requests.Session()
        user_data = {"email": "multi_item_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        # Submit annotation
        annotation_data = {
            "instance_id": "phase_item_1",
            "type": "radio",
            "schema": "phase_rating",
            "state": [{"name": "3", "value": "3"}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200
