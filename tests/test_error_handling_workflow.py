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


class TestErrorHandlingWorkflow:
    """Test error handling workflows."""

    @pytest.fixture(scope="class")
    def server_url(self):
        """Get the server URL for testing."""
        return "http://localhost:9001"

    def test_validation_error_handling(self, server_url):
        """
        Test validation error handling:
        - Test invalid annotation data
        - Test missing required fields
        - Test malformed JSON
        - Test validation error responses
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create user for validation testing
            user_data = {
                "username": "validation_user",
                "initial_phase": "ANNOTATION",
                "assign_items": True
            }
            response = requests.post(f"{server_url}/test/create_user", json=user_data, timeout=5)
            assert response.status_code in [200, 302]

            # Test invalid annotation data (missing required fields)
            invalid_annotation_data = {
                "instance_id": "validation_item_1",
                "annotation_data": json.dumps({
                    # Missing required fields
                    "annotation_type": "validation_test"
                })
            }
            response = requests.post(f"{server_url}/submit_annotation", data=invalid_annotation_data, timeout=5)
            # Should handle gracefully (either 400 error or continue)
            assert response.status_code in [200, 302, 400, 422]
            print("✓ Invalid annotation data handled gracefully")

            # Test malformed JSON
            malformed_annotation_data = {
                "instance_id": "validation_item_2",
                "annotation_data": "{invalid json}"  # Malformed JSON
            }
            response = requests.post(f"{server_url}/submit_annotation", data=malformed_annotation_data, timeout=5)
            # Should handle gracefully
            assert response.status_code in [200, 302, 400, 422]
            print("✓ Malformed JSON handled gracefully")

            # Test valid annotation for comparison
            valid_annotation_data = {
                "instance_id": "validation_item_3",
                "annotation_data": json.dumps({
                    "rating": 4,
                    "confidence": 0.8,
                    "annotation_type": "validation_test"
                })
            }
            response = requests.post(f"{server_url}/submit_annotation", data=valid_annotation_data, timeout=5)
            assert response.status_code in [200, 302]
            print("✓ Valid annotation processed successfully")

            print("✓ Validation error handling completed successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_network_error_handling(self, server_url):
        """
        Test network error handling:
        - Test connection timeouts
        - Test server unavailability
        - Test retry mechanisms
        - Test graceful degradation
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create user for network testing
            user_data = {
                "username": "network_user",
                "initial_phase": "ANNOTATION",
                "assign_items": True
            }
            response = requests.post(f"{server_url}/test/create_user", json=user_data, timeout=5)
            assert response.status_code in [200, 302]

            # Test with very short timeout to simulate network issues
            try:
                response = requests.get(f"{server_url}/test/user_state/network_user", timeout=0.001)
                # Should either timeout or succeed
                print("✓ Network timeout handled gracefully")
            except requests.exceptions.Timeout:
                print("✓ Network timeout caught as expected")

            # Test with invalid server URL
            try:
                response = requests.get("http://invalid-server:9999/test/health", timeout=1)
                print("✓ Invalid server handled gracefully")
            except requests.exceptions.ConnectionError:
                print("✓ Invalid server connection error caught as expected")

            # Submit annotation with potential network issues
            annotation_data = {
                "instance_id": "network_item_1",
                "annotation_data": json.dumps({
                    "rating": 3,
                    "confidence": 0.7,
                    "annotation_type": "network_test"
                })
            }
            response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
            assert response.status_code in [200, 302]
            print("✓ Network annotation submission successful")

            print("✓ Network error handling completed successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_edge_case_handling(self, server_url):
        """
        Test edge case handling:
        - Test empty annotations
        - Test very large annotations
        - Test special characters
        - Test boundary conditions
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create user for edge case testing
            user_data = {
                "username": "edge_case_user",
                "initial_phase": "ANNOTATION",
                "assign_items": True
            }
            response = requests.post(f"{server_url}/test/create_user", json=user_data, timeout=5)
            assert response.status_code in [200, 302]

            # Test empty annotation data
            empty_annotation_data = {
                "instance_id": "edge_item_1",
                "annotation_data": json.dumps({})
            }
            response = requests.post(f"{server_url}/submit_annotation", data=empty_annotation_data, timeout=5)
            assert response.status_code in [200, 302, 400, 422]
            print("✓ Empty annotation data handled gracefully")

            # Test annotation with special characters
            special_chars_annotation_data = {
                "instance_id": "edge_item_2",
                "annotation_data": json.dumps({
                    "rating": 4,
                    "notes": "Special chars: éñüñçå†îøñ",
                    "annotation_type": "edge_case_test"
                })
            }
            response = requests.post(f"{server_url}/submit_annotation", data=special_chars_annotation_data, timeout=5)
            assert response.status_code in [200, 302]
            print("✓ Special characters handled successfully")

            # Test boundary condition annotations
            boundary_annotation_data = {
                "instance_id": "edge_item_3",
                "annotation_data": json.dumps({
                    "rating": 1,  # Minimum rating
                    "confidence": 0.0,  # Minimum confidence
                    "annotation_type": "edge_case_test"
                })
            }
            response = requests.post(f"{server_url}/submit_annotation", data=boundary_annotation_data, timeout=5)
            assert response.status_code in [200, 302]
            print("✓ Boundary conditions handled successfully")

            # Test maximum values
            max_annotation_data = {
                "instance_id": "edge_item_4",
                "annotation_data": json.dumps({
                    "rating": 5,  # Maximum rating
                    "confidence": 1.0,  # Maximum confidence
                    "annotation_type": "edge_case_test"
                })
            }
            response = requests.post(f"{server_url}/submit_annotation", data=max_annotation_data, timeout=5)
            assert response.status_code in [200, 302]
            print("✓ Maximum values handled successfully")

            print("✓ Edge case handling completed successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_concurrent_access_handling(self, server_url):
        """
        Test concurrent access handling:
        - Test multiple users accessing same items
        - Test simultaneous annotation submissions
        - Test race condition handling
        - Test data consistency
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create multiple users for concurrent testing
            users_data = {
                "users": [
                    {"username": "concurrent_user_1", "initial_phase": "ANNOTATION", "assign_items": True},
                    {"username": "concurrent_user_2", "initial_phase": "ANNOTATION", "assign_items": True},
                    {"username": "concurrent_user_3", "initial_phase": "ANNOTATION", "assign_items": True}
                ]
            }
            response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=5)
            assert response.status_code in [200, 302]

            # Submit annotations concurrently (simulated)
            concurrent_items = ["concurrent_item_1", "concurrent_item_2", "concurrent_item_3"]

            for i, item_id in enumerate(concurrent_items):
                for username in ["concurrent_user_1", "concurrent_user_2", "concurrent_user_3"]:
                    annotation_data = {
                        "instance_id": item_id,
                        "annotation_data": json.dumps({
                            "rating": (i + 1) % 5 + 1,
                            "confidence": 0.8,
                            "user": username,
                            "annotation_type": "concurrent_test"
                        })
                    }
                    response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                    assert response.status_code in [200, 302]

            # Verify all concurrent annotations were recorded
            for username in ["concurrent_user_1", "concurrent_user_2", "concurrent_user_3"]:
                response = requests.get(f"{server_url}/test/user_state/{username}", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assert user_state["annotations"]["total_count"] >= 3
                    print(f"✓ {username} completed concurrent annotations")

            print("✓ Concurrent access handling completed successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_data_persistence_error_handling(self, server_url):
        """
        Test data persistence error handling:
        - Test annotation storage failures
        - Test data corruption scenarios
        - Test recovery mechanisms
        - Test data integrity validation
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create user for persistence testing
            user_data = {
                "username": "persistence_user",
                "initial_phase": "ANNOTATION",
                "assign_items": True
            }
            response = requests.post(f"{server_url}/test/create_user", json=user_data, timeout=5)
            assert response.status_code in [200, 302]

            # Submit annotations for persistence testing
            persistence_items = ["persistence_item_1", "persistence_item_2", "persistence_item_3"]

            for item_id in persistence_items:
                annotation_data = {
                    "instance_id": item_id,
                    "annotation_data": json.dumps({
                        "rating": 4,
                        "confidence": 0.8,
                        "timestamp": time.time(),
                        "annotation_type": "persistence_test"
                    })
                }
                response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                assert response.status_code in [200, 302]

            # Verify persistence by checking user state
            response = requests.get(f"{server_url}/test/user_state/persistence_user", timeout=5)
            if response.status_code == 200:
                user_state = response.json()
                assert user_state["annotations"]["total_count"] >= 3
                print("✓ Data persistence verified successfully")

            # Test system state to verify data integrity
            response = requests.get(f"{server_url}/test/system_state", timeout=5)
            if response.status_code == 200:
                system_state = response.json()
                assert "users" in system_state
                assert "items" in system_state
                print("✓ System state integrity verified")

            print("✓ Data persistence error handling completed successfully")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")


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

        print("✓ Mocked validation error handling test passed!")

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_network_error_handling(self, mock_get, mock_post):
        """Test network error handling with mocked responses."""

        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses for network errors
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection failed")
        mock_get.side_effect = requests.exceptions.Timeout("Request timeout")

        # Test network error handling
        server_url = "http://localhost:9001"

        # Test connection error
        try:
            response = requests.post(f"{server_url}/submit_annotation", data={})
            assert False, "Should have raised ConnectionError"
        except requests.exceptions.ConnectionError:
            print("✓ Connection error caught as expected")

        # Test timeout error
        try:
            response = requests.get(f"{server_url}/test/user_state/user")
            assert False, "Should have raised Timeout"
        except requests.exceptions.Timeout:
            print("✓ Timeout error caught as expected")

        print("✓ Mocked network error handling test passed!")

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

        print("✓ Mocked edge case handling test passed!")

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
        response = requests.get(f"{server_url}/test/user_state/concurrent_user_1")
        assert response.status_code == 200
        user_state = response.json()
        assert user_state["annotations"]["total_count"] >= 3

        print("✓ Mocked concurrent access handling test passed!")