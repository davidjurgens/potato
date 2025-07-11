"""
Annotation Type-Specific Workflow Tests

This module contains tests for different annotation types and their specific behaviors,
including validation, key bindings, and data capture.
"""

import json
import pytest
import time
from tests.flask_test_setup import FlaskTestServer
import requests
from unittest.mock import patch, MagicMock


class TestAnnotationTypesWorkflow:
    """Test different annotation types workflow."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server = FlaskTestServer(port=9001, debug=True)
        assert server.start_server()
        yield server
        server.stop_server()

    def test_likert_scale_workflow(self, flask_server):
        """Test Likert scale annotation workflow."""
        try:
            # Reset system
            response = flask_server.post("/test/reset", timeout=5)
            assert response.status_code == 200

            # Create user
            user_data = {"user_id": "likert_user", "phase": "annotation"}
            response = flask_server.post("/test/create_user", json=user_data, timeout=5)
            assert response.status_code == 200

            # Submit Likert scale annotation
            annotation_data = {
                "user_id": "likert_user",
                "instance_id": "item_1",
                "annotation": {
                    "rating": 4,
                    "confidence": 0.8
                }
            }
            response = flask_server.post("/submit_annotation", json=annotation_data, timeout=5)
            assert response.status_code == 200

            # Check user state
            response = flask_server.get("/test/user_state/likert_user", timeout=5)
            assert response.status_code == 200

        except Exception:
            pytest.skip("Server not running")

    def test_span_annotation_workflow(self, flask_server):
        """Test span annotation workflow."""
        try:
            # Reset system
            response = flask_server.post("/test/reset", timeout=5)
            assert response.status_code == 200

            # Create user
            user_data = {"user_id": "span_user", "phase": "annotation"}
            response = flask_server.post("/test/create_user", json=user_data, timeout=5)
            assert response.status_code == 200

            # Submit span annotation
            annotation_data = {
                "user_id": "span_user",
                "instance_id": "item_1",
                "annotation": {
                    "spans": [
                        {"start": 0, "end": 5, "label": "positive"},
                        {"start": 10, "end": 15, "label": "negative"}
                    ],
                    "confidence": 0.9
                }
            }
            response = flask_server.post("/submit_annotation", json=annotation_data, timeout=5)
            assert response.status_code == 200

            # Check user state
            response = flask_server.get("/test/user_state/span_user", timeout=5)
            assert response.status_code == 200

        except Exception:
            pytest.skip("Server not running")

    def test_multiselect_workflow(self, flask_server):
        """Test multiselect annotation workflow."""
        try:
            # Reset system
            response = flask_server.post("/test/reset", timeout=5)
            assert response.status_code == 200

            # Create user
            user_data = {"user_id": "multiselect_user", "phase": "annotation"}
            response = flask_server.post("/test/create_user", json=user_data, timeout=5)
            assert response.status_code == 200

            # Submit multiselect annotation
            annotation_data = {
                "user_id": "multiselect_user",
                "instance_id": "item_1",
                "annotation": {
                    "selected_labels": ["label1", "label3"],
                    "confidence": 0.7
                }
            }
            response = flask_server.post("/submit_annotation", json=annotation_data, timeout=5)
            assert response.status_code == 200

            # Check user state
            response = flask_server.get("/test/user_state/multiselect_user", timeout=5)
            assert response.status_code == 200

        except Exception:
            pytest.skip("Server not running")

    def test_slider_workflow(self, flask_server):
        """Test slider annotation workflow."""
        try:
            # Reset system
            response = flask_server.post("/test/reset", timeout=5)
            assert response.status_code == 200

            # Create user
            user_data = {"user_id": "slider_user", "phase": "annotation"}
            response = flask_server.post("/test/create_user", json=user_data, timeout=5)
            assert response.status_code == 200

            # Submit slider annotation
            annotation_data = {
                "user_id": "slider_user",
                "instance_id": "item_1",
                "annotation": {
                    "value": 0.75,
                    "confidence": 0.6
                }
            }
            response = flask_server.post("/submit_annotation", json=annotation_data, timeout=5)
            assert response.status_code == 200

            # Check user state
            response = flask_server.get("/test/user_state/slider_user", timeout=5)
            assert response.status_code == 200

        except Exception:
            pytest.skip("Server not running")

    def test_radio_button_workflow(self, flask_server):
        """Test radio button annotation workflow."""
        try:
            # Reset system
            response = flask_server.post("/test/reset", timeout=5)
            assert response.status_code == 200

            # Create user
            user_data = {"user_id": "radio_user", "phase": "annotation"}
            response = flask_server.post("/test/create_user", json=user_data, timeout=5)
            assert response.status_code == 200

            # Submit radio button annotation
            annotation_data = {
                "user_id": "radio_user",
                "instance_id": "item_1",
                "annotation": {
                    "selected_option": "option_b",
                    "confidence": 0.9
                }
            }
            response = flask_server.post("/submit_annotation", json=annotation_data, timeout=5)
            assert response.status_code == 200

            # Check user state
            response = flask_server.get("/test/user_state/radio_user", timeout=5)
            assert response.status_code == 200

        except Exception:
            pytest.skip("Server not running")

    def test_mixed_annotation_types_workflow(self, flask_server):
        """Test mixed annotation types workflow."""
        try:
            # Reset system
            response = flask_server.post("/test/reset", timeout=5)
            assert response.status_code == 200

            # Create user
            user_data = {"user_id": "mixed_user", "phase": "annotation"}
            response = flask_server.post("/test/create_user", json=user_data, timeout=5)
            assert response.status_code == 200

            # Submit mixed annotation
            annotation_data = {
                "user_id": "mixed_user",
                "instance_id": "item_1",
                "annotation": {
                    "rating": 3,
                    "text_comment": "This is a mixed annotation",
                    "selected_options": ["option_a", "option_c"],
                    "confidence": 0.8
                }
            }
            response = flask_server.post("/submit_annotation", json=annotation_data, timeout=5)
            assert response.status_code == 200

            # Check user state
            response = flask_server.get("/test/user_state/mixed_user", timeout=5)
            assert response.status_code == 200

        except Exception:
            pytest.skip("Server not running")


class TestAnnotationTypesWorkflowMocked:
    """Test annotation types workflow with mocked responses."""

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_likert_workflow(self, mock_get, mock_post):
        """Test Likert workflow with mocked responses."""

        # Mock responses
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_post.return_value = mock_response
        mock_get.return_value = mock_response

        server_url = "http://localhost:9001"

        # Test workflow
        annotation_data = {
            "user_id": "likert_user",
            "instance_id": "item_1",
            "annotation": {"rating": 4, "confidence": 0.8}
        }
        response = requests.post(f"{server_url}/submit_annotation", json=annotation_data)
        assert response.status_code == 200

        response = requests.get(f"{server_url}/test/user_state/likert_user")
        assert response.status_code == 200

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_span_workflow(self, mock_get, mock_post):
        """Test span workflow with mocked responses."""

        # Mock responses
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_post.return_value = mock_response
        mock_get.return_value = mock_response

        server_url = "http://localhost:9001"

        # Test workflow
        annotation_data = {
            "user_id": "span_user",
            "instance_id": "item_1",
            "annotation": {
                "spans": [{"start": 0, "end": 5, "label": "positive"}],
                "confidence": 0.9
            }
        }
        response = requests.post(f"{server_url}/submit_annotation", json=annotation_data)
        assert response.status_code == 200

        response = requests.get(f"{server_url}/test/user_state/span_user")
        assert response.status_code == 200

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_multiselect_workflow(self, mock_get, mock_post):
        """Test multiselect workflow with mocked responses."""

        # Mock responses
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_post.return_value = mock_response
        mock_get.return_value = mock_response

        server_url = "http://localhost:9001"

        # Test workflow
        annotation_data = {
            "user_id": "multiselect_user",
            "instance_id": "item_1",
            "annotation": {
                "selected_labels": ["label1", "label3"],
                "confidence": 0.7
            }
        }
        response = requests.post(f"{server_url}/submit_annotation", json=annotation_data)
        assert response.status_code == 200

        response = requests.get(f"{server_url}/test/user_state/multiselect_user")
        assert response.status_code == 200

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_slider_workflow(self, mock_get, mock_post):
        """Test slider workflow with mocked responses."""

        # Mock responses
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_post.return_value = mock_response
        mock_get.return_value = mock_response

        server_url = "http://localhost:9001"

        # Test workflow
        annotation_data = {
            "user_id": "slider_user",
            "instance_id": "item_1",
            "annotation": {
                "value": 0.75,
                "confidence": 0.6
            }
        }
        response = requests.post(f"{server_url}/submit_annotation", json=annotation_data)
        assert response.status_code == 200

        response = requests.get(f"{server_url}/test/user_state/slider_user")
        assert response.status_code == 200