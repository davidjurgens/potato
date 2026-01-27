"""
Test suite for robust span annotation refactoring.

This module tests the new boundary-based span annotation system that replaces
the complex overlay approach with a simpler, more robust rendering method.
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


class TestRobustSpanAnnotation:
    """Test suite for robust span annotation system."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create test configuration for robust span annotation testing."""
        test_dir = create_test_directory("robust_span_test")

        test_data = [
            {"id": "robust_1", "text": "I am very happy today but also a bit sad sometimes."},
            {"id": "robust_2", "text": "This is an angry statement that shows frustration."},
            {"id": "robust_3", "text": "Surprising news made everyone excited."}
        ]
        data_file = create_test_data_file(test_dir, test_data)

        annotation_schemes = [
            {
                "annotation_type": "span",
                "name": "emotion",
                "description": "Highlight which phrases express different emotions in the text",
                "labels": ["happy", "sad", "angry", "surprised", "neutral"],
                "sequential_key_binding": True
            },
            {
                "annotation_type": "radio",
                "name": "overall_sentiment",
                "labels": ["positive", "negative", "neutral"],
                "description": "Select the overall sentiment"
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Robust Span Annotation Test",
            require_password=False,
            max_annotations_per_user=5
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_annotation_page_loads(self):
        """Test that annotation page loads with span annotation config."""
        session = requests.Session()
        user_data = {"email": "robust_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        response = session.get(f"{self.server.base_url}/annotate")
        assert response.status_code == 200

    def test_span_annotation_submit(self):
        """Test submitting a span annotation."""
        session = requests.Session()
        user_data = {"email": "robust_annotator", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        annotation_data = {
            "instance_id": "robust_1",
            "type": "span",
            "schema": "emotion",
            "state": [
                {"name": "happy", "start": 10, "end": 15, "value": "happy"},
                {"name": "sad", "start": 36, "end": 39, "value": "sad"}
            ]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200

    def test_overlapping_spans(self):
        """Test handling of overlapping span annotations."""
        session = requests.Session()
        user_data = {"email": "overlap_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        # Submit overlapping spans
        annotation_data = {
            "instance_id": "robust_1",
            "type": "span",
            "schema": "emotion",
            "state": [
                {"name": "happy", "start": 0, "end": 20, "value": "happy"},
                {"name": "neutral", "start": 15, "end": 30, "value": "neutral"}
            ]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        # Should handle overlapping spans (either accept or reject gracefully)
        assert response.status_code in [200, 400]
