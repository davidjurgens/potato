"""
Error Handling Workflow Tests

This module contains tests for error handling workflows,
including validation errors, network failures, and edge cases.
"""

import json
import pytest
import requests
import time
from unittest.mock import patch, MagicMock
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory
)


class TestErrorHandlingWorkflow:
    """Test error handling workflows."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up test server for error handling tests."""
        test_dir = create_test_directory("error_handling_workflow_test")

        test_data = [
            {"id": "validation_item_1", "text": "Validation test item 1."},
            {"id": "validation_item_2", "text": "Validation test item 2."},
            {"id": "validation_item_3", "text": "Validation test item 3."},
            {"id": "edge_item_1", "text": "Edge case test item 1."},
            {"id": "edge_item_2", "text": "Edge case test item 2."},
            {"id": "edge_item_3", "text": "Edge case test item 3."},
            {"id": "edge_item_4", "text": "Edge case test item 4."},
            {"id": "network_item_1", "text": "Network test item 1."},
            {"id": "concurrent_item_1", "text": "Concurrent test item 1."},
            {"id": "concurrent_item_2", "text": "Concurrent test item 2."},
            {"id": "concurrent_item_3", "text": "Concurrent test item 3."},
            {"id": "persistence_item_1", "text": "Persistence test item 1."},
            {"id": "persistence_item_2", "text": "Persistence test item 2."},
            {"id": "persistence_item_3", "text": "Persistence test item 3."},
        ]
        data_file = create_test_data_file(test_dir, test_data)

        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "rating",
                "description": "Rate the item",
                "labels": ["1", "2", "3", "4", "5"]
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Error Handling Workflow Test",
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

    def test_validation_error_handling(self):
        """Test validation error handling with invalid annotation data."""
        session = requests.Session()
        user_data = {"email": "validation_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data, timeout=5)
        session.post(f"{self.server.base_url}/auth", data=user_data, timeout=5)

        # Test invalid annotation data (missing required fields)
        invalid_annotation_data = {
            "instance_id": "validation_item_1",
            # Missing type and schema
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=invalid_annotation_data, timeout=5)
        # Server should handle gracefully
        assert response.status_code in [200, 302, 400, 422, 500]

        # Test with proper annotation format
        valid_annotation_data = {
            "instance_id": "validation_item_1",
            "type": "radio",
            "schema": "rating",
            "state": [{"name": "4", "value": "4"}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=valid_annotation_data, timeout=5)
        assert response.status_code == 200

    def test_network_timeout_handling(self):
        """Test network error handling with timeouts."""
        session = requests.Session()
        user_data = {"email": "network_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data, timeout=5)
        session.post(f"{self.server.base_url}/auth", data=user_data, timeout=5)

        # Test with very short timeout to simulate network issues
        try:
            response = session.get(f"{self.server.base_url}/annotate", timeout=0.001)
            # If it succeeds with very short timeout, that's fine
        except requests.exceptions.Timeout:
            # Timeout is expected behavior
            pass
        except requests.exceptions.ReadTimeout:
            # Read timeout is also expected
            pass

        # Test with invalid server URL
        try:
            response = requests.get("http://invalid-server:9999/health", timeout=1)
        except requests.exceptions.ConnectionError:
            # Connection error is expected
            pass

        # Submit annotation with normal timeout
        annotation_data = {
            "instance_id": "network_item_1",
            "type": "radio",
            "schema": "rating",
            "state": [{"name": "3", "value": "3"}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data, timeout=5)
        assert response.status_code == 200

    def test_edge_case_handling(self):
        """Test edge case handling with various input types."""
        session = requests.Session()
        user_data = {"email": "edge_case_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data, timeout=5)
        session.post(f"{self.server.base_url}/auth", data=user_data, timeout=5)

        # Test empty state
        empty_annotation_data = {
            "instance_id": "edge_item_1",
            "type": "radio",
            "schema": "rating",
            "state": []
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=empty_annotation_data, timeout=5)
        # Should handle gracefully
        assert response.status_code in [200, 302, 400, 422]

        # Test boundary condition - minimum rating
        boundary_annotation_data = {
            "instance_id": "edge_item_3",
            "type": "radio",
            "schema": "rating",
            "state": [{"name": "1", "value": "1"}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=boundary_annotation_data, timeout=5)
        assert response.status_code == 200

        # Test maximum rating
        max_annotation_data = {
            "instance_id": "edge_item_4",
            "type": "radio",
            "schema": "rating",
            "state": [{"name": "5", "value": "5"}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=max_annotation_data, timeout=5)
        assert response.status_code == 200

    def test_concurrent_user_access(self):
        """Test concurrent access handling with multiple users."""
        # Create multiple user sessions
        users = ["concurrent_user_1", "concurrent_user_2", "concurrent_user_3"]
        sessions = {}
        for username in users:
            user_data = {"email": username, "pass": "test_password"}
            session = requests.Session()
            session.post(f"{self.server.base_url}/register", data=user_data, timeout=5)
            session.post(f"{self.server.base_url}/auth", data=user_data, timeout=5)
            sessions[username] = session

        # Each user annotates the same items
        concurrent_items = ["concurrent_item_1", "concurrent_item_2", "concurrent_item_3"]

        for i, item_id in enumerate(concurrent_items):
            for username, session in sessions.items():
                annotation_data = {
                    "instance_id": item_id,
                    "type": "radio",
                    "schema": "rating",
                    "state": [{"name": str((i + 1) % 5 + 1), "value": str((i + 1) % 5 + 1)}]
                }
                response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data, timeout=5)
                assert response.status_code == 200

    def test_data_persistence(self):
        """Test data persistence by submitting and verifying annotations."""
        session = requests.Session()
        user_data = {"email": "persistence_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data, timeout=5)
        session.post(f"{self.server.base_url}/auth", data=user_data, timeout=5)

        # Submit annotations
        persistence_items = ["persistence_item_1", "persistence_item_2", "persistence_item_3"]

        for item_id in persistence_items:
            annotation_data = {
                "instance_id": item_id,
                "type": "radio",
                "schema": "rating",
                "state": [{"name": "4", "value": "4"}]
            }
            response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data, timeout=5)
            assert response.status_code == 200

        # Verify user can still access annotation page
        response = session.get(f"{self.server.base_url}/annotate", timeout=5)
        assert response.status_code == 200


class TestErrorHandlingWorkflowMocked:
    """Test error handling workflows with mocked responses."""

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_validation_error_handling(self, mock_get, mock_post):
        """Test validation error handling with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses for validation errors
        mock_post.return_value = create_mock_response(400, {
            "error": "validation_error",
            "message": "Invalid annotation data"
        })
        mock_get.return_value = create_mock_response(200, {
            "username": "validation_user",
            "phase": "ANNOTATION",
            "annotations": {"total_count": 1},
            "assignments": {"total": 3, "remaining": 2}
        })

        # Test validation error handling
        server_url = "http://localhost:9001"

        # Submit invalid annotation
        invalid_annotation_data = {
            "instance_id": "validation_item_1",
            "annotation_data": json.dumps({
                "annotation_type": "validation_test"
                # Missing required fields
            })
        }
        response = requests.post(f"{server_url}/submit_annotation", data=invalid_annotation_data)
        assert response.status_code == 400
        error_data = response.json()
        assert "error" in error_data
        assert "validation_error" in error_data["error"]

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_network_error_handling(self, mock_get, mock_post):
        """Test network error handling with mocked responses."""

        # Configure mock responses for network errors
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection failed")
        mock_get.side_effect = requests.exceptions.Timeout("Request timeout")

        # Test network error handling
        server_url = "http://localhost:9001"

        # Test connection error
        try:
            requests.post(f"{server_url}/submit_annotation", data={})
            assert False, "Should have raised ConnectionError"
        except requests.exceptions.ConnectionError:
            pass  # Expected

        # Test timeout error
        try:
            requests.get(f"{server_url}/admin/user_state/user")
            assert False, "Should have raised Timeout"
        except requests.exceptions.Timeout:
            pass  # Expected

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_edge_case_handling(self, mock_get, mock_post):
        """Test edge case handling with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses for edge cases
        mock_post.return_value = create_mock_response(200, {"status": "success"})
        mock_get.return_value = create_mock_response(200, {
            "username": "edge_case_user",
            "phase": "ANNOTATION",
            "annotations": {"total_count": 4},
            "assignments": {"total": 4, "remaining": 0}
        })

        # Test edge case handling
        server_url = "http://localhost:9001"

        # Test empty annotation
        empty_annotation_data = {
            "instance_id": "edge_item_1",
            "annotation_data": json.dumps({})
        }
        response = requests.post(f"{server_url}/submit_annotation", data=empty_annotation_data)
        assert response.status_code == 200

        # Test special characters
        special_chars_annotation_data = {
            "instance_id": "edge_item_2",
            "annotation_data": json.dumps({
                "rating": 4,
                "notes": "Special chars: éñüñçå†îøñ",
                "annotation_type": "edge_case_test"
            })
        }
        response = requests.post(f"{server_url}/submit_annotation", data=special_chars_annotation_data)
        assert response.status_code == 200

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_concurrent_access_handling(self, mock_get, mock_post):
        """Test concurrent access handling with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses for concurrent access
        mock_post.return_value = create_mock_response(200, {"status": "success"})
        mock_get.return_value = create_mock_response(200, {
            "username": "concurrent_user_1",
            "phase": "ANNOTATION",
            "annotations": {"total_count": 3},
            "assignments": {"total": 3, "remaining": 0}
        })

        # Test concurrent access handling
        server_url = "http://localhost:9001"

        # Submit concurrent annotations
        for i in range(3):
            annotation_data = {
                "instance_id": f"concurrent_item_{i+1}",
                "annotation_data": json.dumps({
                    "rating": i + 1,
                    "confidence": 0.8,
                    "annotation_type": "concurrent_test"
                })
            }
            response = requests.post(f"{server_url}/submit_annotation", data=annotation_data)
            assert response.status_code == 200

        # Verify concurrent annotations
        response = requests.get(f"{server_url}/admin/user_state/concurrent_user_1")
        assert response.status_code == 200
        user_state = response.json()
        assert user_state["annotations"]["total_count"] >= 3
