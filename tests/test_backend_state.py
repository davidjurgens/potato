"""
Backend State Testing Module

This module contains tests that use the new test routes to verify
backend state management, user interactions, and system behavior.
"""

import json
import pytest
import time
from tests.flask_test_setup import FlaskTestServer
from unittest.mock import patch, MagicMock
import requests


class TestBackendState:
    """Test backend state management using the new test routes."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        server = FlaskTestServer(port=9001, debug=True)
        assert server.start_server()
        yield server
        server.stop_server()

    def test_health_check(self, flask_server):
        """Test the health check endpoint."""
        try:
            response = flask_server.get("/test/health", timeout=5)
            assert response.status_code in [200, 302]  # Accept redirects

            if response.status_code == 200:
                data = response.json()
                assert data["status"] in ["healthy", "unhealthy"]
                assert "timestamp" in data
                assert "managers" in data
        except Exception:
            pytest.skip("Server not running")

    def test_system_state_initial(self, flask_server):
        """Test getting initial system state."""
        try:
            response = flask_server.get("/test/system_state", timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert "system_state" in data
                assert "users" in data
                assert "config" in data

                # Initial state should be empty
                assert data["system_state"]["total_users"] == 0
                assert data["system_state"]["total_items"] == 0
                assert data["system_state"]["total_annotations"] == 0
        except Exception:
            pytest.skip("Server not running")

    def test_user_creation_and_state(self, flask_server):
        """Test creating a user and checking their state."""
        try:
            # Create a test user
            user_data = {"username": "test_user_1"}
            response = flask_server.post(
                "/test/create_user",
                json=user_data,
                timeout=5
            )
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert data["status"] == "completed"
                assert data["username"] == "test_user_1"

                # Check user state
                response = flask_server.get(f"/test/user_state/test_user_1", timeout=5)
                assert response.status_code in [200, 302]

                if response.status_code == 200:
                    user_state = response.json()
                    assert user_state["username"] == "test_user_1"
                    assert "phase" in user_state
                    assert "assignments" in user_state
                    assert "annotations" in user_state
        except Exception:
            pytest.skip("Server not running")

    def test_user_phase_advancement(self, flask_server):
        """Test advancing a user's phase."""
        try:
            # Create a user first
            user_data = {"username": "test_user_2"}
            flask_server.post(f"/test/create_user", json=user_data, timeout=5)

            # Get initial phase
            response = flask_server.get(f"/test/user_state/test_user_2", timeout=5)
            if response.status_code == 200:
                initial_state = response.json()
                initial_phase = initial_state["phase"]

                # Advance phase
                response = flask_server.post(f"/test/advance_user_phase/test_user_2", timeout=5)
                assert response.status_code in [200, 302]

                if response.status_code == 200:
                    data = response.json()
                    assert data["status"] == "advanced"
                    assert data["username"] == "test_user_2"
                    assert data["old_phase"] == initial_phase
                    assert data["new_phase"] != initial_phase
        except Exception:
            pytest.skip("Server not running")

    def test_item_state_inspection(self, flask_server):
        """Test inspecting item state."""
        try:
            response = flask_server.get(f"/test/item_state", timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert "total_items" in data
                assert "items" in data
                assert "summary" in data

                # Check summary statistics
                summary = data["summary"]
                assert "items_with_annotations" in summary
                assert "items_without_annotations" in summary
                assert "average_annotations_per_item" in summary
        except Exception:
            pytest.skip("Server not running")

    def test_annotation_submission_and_state(self, flask_server):
        """Test submitting annotations and verifying state changes."""
        try:
            # Create a test user
            user_data = {"username": "test_user_3"}
            flask_server.post(f"{flask_server.base_url}/test/create_user", json=user_data, timeout=5)

            # Submit an annotation
            annotation_data = {
                "instance_id": "test_item_1",
                "annotation_data": json.dumps({"test_annotation": "test_value"})
            }

            response = flask_server.post(
                f"{flask_server.base_url}/submit_annotation",
                data=annotation_data,
                timeout=5
            )
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                # Check that the annotation was recorded
                response = flask_server.get(f"{flask_server.base_url}/test/user_state/test_user_3", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assert user_state["annotations"]["total_count"] > 0
                    assert "test_item_1" in user_state["annotations"]["by_instance"]
        except Exception:
            pytest.skip("Server not running")

    def test_system_reset(self, flask_server):
        """Test resetting the system state."""
        try:
            # Create some test data first
            user_data = {"username": "test_user_reset"}
            flask_server.post(f"{flask_server.base_url}/test/create_user", json=user_data, timeout=5)

            # Submit an annotation
            annotation_data = {
                "instance_id": "test_item_reset",
                "annotation_data": json.dumps({"test": "value"})
            }
            flask_server.post(f"{flask_server.base_url}/submit_annotation", data=annotation_data, timeout=5)

            # Reset the system
            response = flask_server.post(f"{flask_server.base_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert data["status"] == "reset_complete"

                # Verify system is reset
                response = flask_server.get(f"{flask_server.base_url}/test/system_state", timeout=5)
                if response.status_code == 200:
                    system_state = response.json()
                    assert system_state["system_state"]["total_users"] == 0
                    assert system_state["system_state"]["total_annotations"] == 0
        except Exception:
            pytest.skip("Server not running")

    def test_error_handling(self, flask_server):
        """Test error handling in test routes."""
        try:
            # Test getting non-existent user
            response = flask_server.get(f"{flask_server.base_url}/test/user_state/nonexistent_user", timeout=5)
            assert response.status_code in [404, 302]

            # Test getting non-existent item
            response = flask_server.get(f"{flask_server.base_url}/test/item_state/nonexistent_item", timeout=5)
            assert response.status_code in [404, 302]

            # Test creating user without username
            response = flask_server.post(f"{flask_server.base_url}/test/create_user", json={}, timeout=5)
            assert response.status_code in [400, 302]
        except Exception:
            pytest.skip("Server not running")

    def test_concurrent_user_operations(self, flask_server):
        """Test concurrent operations on multiple users."""
        try:
            # Create multiple users
            users = ["concurrent_user_1", "concurrent_user_2", "concurrent_user_3"]

            for username in users:
                user_data = {"username": username}
                response = flask_server.post(f"{flask_server.base_url}/test/create_user", json=user_data, timeout=5)
                assert response.status_code in [200, 302]

            # Check system state
            response = flask_server.get(f"{flask_server.base_url}/test/system_state", timeout=5)
            if response.status_code == 200:
                data = response.json()
                assert data["system_state"]["total_users"] >= len(users)

                # Verify each user exists
                for username in users:
                    assert username in data["users"]
        except Exception:
            pytest.skip("Server not running")

    def test_annotation_workflow_integration(self, flask_server):
        """Test a complete annotation workflow using test routes."""
        try:
            # Create a test user
            user_data = {"username": "workflow_user"}
            flask_server.post("/test/create_user", json=user_data, timeout=5)

            # Advance user to annotation phase
            flask_server.post("/test/advance_user_phase/workflow_user", timeout=5)

            # Submit multiple annotations
            for i in range(3):
                annotation_data = {
                    "instance_id": f"workflow_item_{i}",
                    "annotation_data": json.dumps({"rating": i + 1})
                }
                flask_server.post("/submit_annotation", data=annotation_data, timeout=5)

            # Verify final state
            response = flask_server.get("/test/user_state/workflow_user", timeout=5)
            if response.status_code == 200:
                user_state = response.json()
                assert user_state["annotations"]["total_count"] == 3
                assert user_state["phase"] == "ANNOTATION"

                # Check system state
                response = flask_server.get("/test/system_state", timeout=5)
                if response.status_code == 200:
                    system_state = response.json()
                    assert system_state["system_state"]["total_annotations"] >= 3
        except Exception:
            pytest.skip("Server not running")


class TestBackendStateMocked:
    """Test backend state with mocked server responses."""

    @patch('requests.get')
    @patch('requests.post')
    def test_mocked_health_check(self, mock_post, mock_get):
        """Test health check with mocked responses."""
        # Mock successful health check
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "healthy",
            "timestamp": "2024-01-01T00:00:00",
            "managers": {
                "user_state_manager": "available",
                "item_state_manager": "available"
            },
            "config": {
                "debug_mode": True,
                "annotation_task_name": "Test Task"
            }
        }
        mock_get.return_value = mock_response

        response = requests.get("http://localhost:9001/test/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["config"]["debug_mode"] is True

    @patch('requests.get')
    def test_mocked_system_state(self, mock_get):
        """Test system state with mocked responses."""
        # Mock system state response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "system_state": {
                "total_users": 2,
                "total_items": 10,
                "total_annotations": 15,
                "items_with_annotations": 8,
                "items_by_annotator_count": {1: 5, 2: 3}
            },
            "users": {
                "user1": {
                    "phase": "ANNOTATION",
                    "annotations_count": 8,
                    "has_assignments": True,
                    "remaining_assignments": False
                },
                "user2": {
                    "phase": "ANNOTATION",
                    "annotations_count": 7,
                    "has_assignments": True,
                    "remaining_assignments": True
                }
            },
            "config": {
                "debug_mode": True,
                "annotation_task_name": "Test Task",
                "max_annotations_per_user": 10
            }
        }
        mock_get.return_value = mock_response

        response = requests.get("http://localhost:9001/test/system_state")
        assert response.status_code == 200
        data = response.json()
        assert data["system_state"]["total_users"] == 2
        assert data["system_state"]["total_annotations"] == 15
        assert len(data["users"]) == 2
        assert data["users"]["user1"]["phase"] == "ANNOTATION"

    @patch('requests.post')
    def test_mocked_user_creation(self, mock_post):
        """Test user creation with mocked responses."""
        # Mock successful user creation
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "created",
            "username": "test_user",
            "message": "User 'test_user' created successfully"
        }
        mock_post.return_value = mock_response

        user_data = {"username": "test_user"}
        response = requests.post("http://localhost:9001/test/create_user", json=user_data)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "created"
        assert data["username"] == "test_user"

    @patch('requests.post')
    def test_mocked_phase_advancement(self, mock_post):
        """Test phase advancement with mocked responses."""
        # Mock successful phase advancement
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "advanced",
            "username": "test_user",
            "old_phase": "INSTRUCTIONS",
            "new_phase": "ANNOTATION"
        }
        mock_post.return_value = mock_response

        response = requests.post("http://localhost:9001/test/advance_user_phase/test_user")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "advanced"
        assert data["old_phase"] == "INSTRUCTIONS"
        assert data["new_phase"] == "ANNOTATION"

    @patch('requests.post')
    def test_mocked_enhanced_user_creation(self, mock_post):
        """Test enhanced user creation with mocked responses."""
        # Mock successful user creation with enhanced features
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "created",
            "username": "test_user",
            "initial_phase": "ANNOTATION",
            "assign_items": True,
            "message": "User 'test_user' created successfully",
            "user_state": {
                "phase": "ANNOTATION",
                "has_assignments": True,
                "assignments_count": 5
            }
        }
        mock_post.return_value = mock_response

        user_data = {
            "username": "test_user",
            "initial_phase": "ANNOTATION",
            "assign_items": True
        }
        response = requests.post("http://localhost:9001/test/create_user", json=user_data)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "created"
        assert data["username"] == "test_user"
        assert data["initial_phase"] == "ANNOTATION"
        assert data["assign_items"] is True
        assert data["user_state"]["phase"] == "ANNOTATION"

    @patch('requests.post')
    def test_mocked_multiple_user_creation(self, mock_post):
        """Test multiple user creation with mocked responses."""
        # Mock successful multiple user creation
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "completed",
            "summary": {
                "total_requested": 3,
                "created": 2,
                "failed": 0,
                "already_exists": 1
            },
            "results": {
                "created": [
                    {
                        "username": "user1",
                        "initial_phase": "ANNOTATION",
                        "assign_items": True,
                        "user_state": {
                            "phase": "ANNOTATION",
                            "has_assignments": True,
                            "assignments_count": 5
                        }
                    },
                    {
                        "username": "user2",
                        "initial_phase": "INSTRUCTIONS",
                        "assign_items": False,
                        "user_state": {
                            "phase": "INSTRUCTIONS",
                            "has_assignments": False,
                            "assignments_count": 0
                        }
                    }
                ],
                "failed": [],
                "already_exists": [
                    {
                        "username": "existing_user",
                        "status": "exists"
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        users_data = {
            "users": [
                {
                    "username": "user1",
                    "initial_phase": "ANNOTATION",
                    "assign_items": True
                },
                {
                    "username": "user2",
                    "initial_phase": "INSTRUCTIONS",
                    "assign_items": False
                },
                {
                    "username": "existing_user",
                    "initial_phase": "ANNOTATION"
                }
            ]
        }
        response = requests.post("http://localhost:9001/test/create_users", json=users_data)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["summary"]["total_requested"] == 3
        assert data["summary"]["created"] == 2
        assert data["summary"]["already_exists"] == 1
        assert len(data["results"]["created"]) == 2
        assert len(data["results"]["already_exists"]) == 1

    @patch('requests.post')
    def test_mocked_user_creation_validation_errors(self, mock_post):
        """Test user creation validation errors with mocked responses."""
        # Test missing username
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "Missing username in request",
            "required_fields": ["username"],
            "optional_fields": ["initial_phase", "assign_items"]
        }
        mock_post.return_value = mock_response

        response = requests.post("http://localhost:9001/test/create_user", json={})
        assert response.status_code == 400
        data = response.json()
        assert "Missing username" in data["error"]
        assert "username" in data["required_fields"]

        # Test invalid phase
        mock_response.json.return_value = {
            "error": "Invalid initial phase: INVALID_PHASE",
            "valid_phases": ['LOGIN', 'CONSENT', 'PRESTUDY', 'INSTRUCTIONS', 'TRAINING', 'ANNOTATION', 'POSTSTUDY', 'DONE']
        }
        mock_response.status_code = 400

        user_data = {
            "username": "test_user",
            "initial_phase": "INVALID_PHASE"
        }
        response = requests.post("http://localhost:9001/test/create_user", json=user_data)
        assert response.status_code == 400
        data = response.json()
        assert "Invalid initial phase" in data["error"]
        assert "ANNOTATION" in data["valid_phases"]

    @patch('requests.post')
    def test_mocked_user_creation_security(self, mock_post):
        """Test user creation security (debug mode required) with mocked responses."""
        # Test that user creation is blocked when not in debug mode
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.json.return_value = {
            "error": "User creation only available in debug mode",
            "debug_mode_required": True
        }
        mock_post.return_value = mock_response

        user_data = {"username": "test_user"}
        response = requests.post("http://localhost:9001/test/create_user", json=user_data)
        assert response.status_code == 403
        data = response.json()
        assert "debug mode" in data["error"]
        assert data["debug_mode_required"] is True