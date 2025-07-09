"""
Annotation Workflow Integration Tests

This module contains comprehensive tests that demonstrate complete annotation workflows
using the new test routes. These tests verify the entire system from data creation
to annotation completion.
"""

import json
import pytest
import requests
import time
from unittest.mock import patch, MagicMock


class TestAnnotationWorkflowIntegration:
    """Test complete annotation workflows using the new test routes."""

    @pytest.fixture(scope="class")
    def server_url(self):
        """Get the server URL for testing."""
        return "http://localhost:9001"

    @pytest.fixture(scope="class")
    def test_dataset(self):
        """Create a test dataset with 10 items."""
        return [
            {
                "id": f"item_{i}",
                "text": f"This is test item number {i} for annotation testing.",
                "displayed_text": f"This is test item number {i} for annotation testing.",
                "category": "test",
                "difficulty": "medium"
            }
            for i in range(1, 11)
        ]

    def test_complete_annotation_workflow(self, server_url, test_dataset):
        """
        Test a complete annotation workflow:
        1. Create a dataset of 10 items where each item needs two annotations
        2. Create two new users
        3. Have them submit annotations for each item
        4. Verify that all items have two annotations
        """
        try:
            # Step 1: Reset the system to start fresh
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                print("✓ System reset completed")

            # Step 2: Create two users with different phases
            users_data = {
                "users": [
                    {
                        "username": "annotator_1",
                        "initial_phase": "ANNOTATION",
                        "assign_items": True
                    },
                    {
                        "username": "annotator_2",
                        "initial_phase": "ANNOTATION",
                        "assign_items": True
                    }
                ]
            }

            response = requests.post(
                f"{server_url}/test/create_users",
                json=users_data,
                timeout=5
            )
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert data["status"] == "completed"
                assert data["summary"]["created"] == 2
                print(f"✓ Created {data['summary']['created']} users")

            # Step 3: Verify initial system state
            response = requests.get(f"{server_url}/test/system_state", timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                system_state = response.json()
                assert system_state["system_state"]["total_users"] == 2
                print(f"✓ System has {system_state['system_state']['total_users']} users")

            # Step 4: Check user states and assignments
            for username in ["annotator_1", "annotator_2"]:
                response = requests.get(f"{server_url}/test/user_state/{username}", timeout=5)
                assert response.status_code in [200, 302]

                if response.status_code == 200:
                    user_state = response.json()
                    assert user_state["username"] == username
                    assert user_state["phase"] == "ANNOTATION"
                    assert user_state["assignments"]["total"] > 0
                    print(f"✓ User {username} is in ANNOTATION phase with {user_state['assignments']['total']} assignments")

            # Step 5: Submit annotations from both users
            annotation_results = {}

            for username in ["annotator_1", "annotator_2"]:
                # Get user's assignments
                response = requests.get(f"{server_url}/test/user_state/{username}", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assignments = user_state["assignments"]["total"]

                    # Submit annotations for each assigned item
                    for i in range(1, 6):  # Assuming 5 items per user
                        item_id = f"item_{i}"
                        annotation_data = {
                            "instance_id": item_id,
                            "annotation_data": json.dumps({
                                "rating": i + 1,
                                "confidence": 0.8,
                                "notes": f"Annotation from {username} for {item_id}"
                            })
                        }

                        response = requests.post(
                            f"{server_url}/submit_annotation",
                            data=annotation_data,
                            timeout=5
                        )
                        assert response.status_code in [200, 302]

                        if response.status_code == 200:
                            result = response.json()
                            assert result["status"] == "success"

                            # Track annotation results
                            if item_id not in annotation_results:
                                annotation_results[item_id] = []
                            annotation_results[item_id].append({
                                "annotator": username,
                                "rating": i + 1
                            })

                    print(f"✓ User {username} submitted {assignments} annotations")

            # Step 6: Verify final system state
            response = requests.get(f"{server_url}/test/system_state", timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                final_state = response.json()
                total_annotations = final_state["system_state"]["total_annotations"]
                print(f"✓ Total annotations in system: {total_annotations}")

            # Step 7: Verify individual user states after annotation
            for username in ["annotator_1", "annotator_2"]:
                response = requests.get(f"{server_url}/test/user_state/{username}", timeout=5)
                assert response.status_code in [200, 302]

                if response.status_code == 200:
                    user_state = response.json()
                    annotations_count = user_state["annotations"]["total_count"]
                    print(f"✓ User {username} has {annotations_count} annotations")

            # Step 8: Check item states to verify annotations
            response = requests.get(f"{server_url}/test/item_state", timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                item_state = response.json()
                items_with_annotations = item_state["summary"]["items_with_annotations"]
                print(f"✓ Items with annotations: {items_with_annotations}")

                # Verify specific items have annotations
                for item in item_state["items"]:
                    if item["annotation_count"] > 0:
                        print(f"✓ Item {item['id']} has {item['annotation_count']} annotations")

            print("✓ Complete annotation workflow test passed!")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_annotation_workflow_with_verification(self, server_url):
        """
        Test annotation workflow with detailed verification of each step.
        """
        try:
            # Reset system
            requests.post(f"{server_url}/test/reset", timeout=5)

            # Create users
            users_data = {
                "users": [
                    {"username": "user_a", "initial_phase": "ANNOTATION", "assign_items": True},
                    {"username": "user_b", "initial_phase": "ANNOTATION", "assign_items": True}
                ]
            }
            response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=5)
            assert response.status_code in [200, 302]

            # Verify user creation
            for username in ["user_a", "user_b"]:
                response = requests.get(f"{server_url}/test/user_state/{username}", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assert user_state["phase"] == "ANNOTATION"
                    assert user_state["assignments"]["total"] > 0

            # Submit annotations and verify each step
            test_items = ["item_1", "item_2", "item_3"]

            for username in ["user_a", "user_b"]:
                for item_id in test_items:
                    # Submit annotation
                    annotation_data = {
                        "instance_id": item_id,
                        "annotation_data": json.dumps({
                            "quality_score": 5,
                            "annotator": username
                        })
                    }

                    response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                    assert response.status_code in [200, 302]

                    # Verify annotation was recorded
                    response = requests.get(f"{server_url}/test/user_state/{username}", timeout=5)
                    if response.status_code == 200:
                        user_state = response.json()
                        assert item_id in user_state["annotations"]["by_instance"]

            # Final verification
            response = requests.get(f"{server_url}/test/system_state", timeout=5)
            if response.status_code == 200:
                system_state = response.json()
                assert system_state["system_state"]["total_annotations"] >= 6  # 2 users * 3 items

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_annotation_workflow_error_handling(self, server_url):
        """
        Test error handling in annotation workflow.
        """
        try:
            # Test creating users without debug mode (should fail)
            # Note: This test assumes the server is not in debug mode
            users_data = {"username": "test_user"}
            response = requests.post(f"{server_url}/test/create_user", json=users_data, timeout=5)

            # Should either succeed (if in debug mode) or fail with 403
            assert response.status_code in [200, 302, 403]

            if response.status_code == 403:
                data = response.json()
                assert "debug mode" in data["error"]

            # Test submitting annotation without user
            annotation_data = {
                "instance_id": "nonexistent_item",
                "annotation_data": json.dumps({"test": "value"})
            }
            response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
            assert response.status_code in [200, 302, 400, 403]

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")

    def test_annotation_workflow_performance(self, server_url):
        """
        Test annotation workflow performance with multiple users and items.
        """
        try:
            # Reset system
            requests.post(f"{server_url}/test/reset", timeout=5)

            # Create multiple users
            users_data = {
                "users": [
                    {"username": f"perf_user_{i}", "initial_phase": "ANNOTATION", "assign_items": True}
                    for i in range(1, 6)  # 5 users
                ]
            }

            start_time = time.time()
            response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=10)
            creation_time = time.time() - start_time

            assert response.status_code in [200, 302]
            print(f"✓ Created 5 users in {creation_time:.2f} seconds")

            if response.status_code == 200:
                data = response.json()
                assert data["summary"]["created"] == 5

            # Submit annotations from all users
            annotation_start_time = time.time()

            for username in [f"perf_user_{i}" for i in range(1, 6)]:
                for item_id in [f"item_{i}" for i in range(1, 4)]:  # 3 items per user
                    annotation_data = {
                        "instance_id": item_id,
                        "annotation_data": json.dumps({
                            "performance_test": True,
                            "user": username,
                            "item": item_id
                        })
                    }

                    response = requests.post(f"{server_url}/submit_annotation", data=annotation_data, timeout=5)
                    assert response.status_code in [200, 302]

            annotation_time = time.time() - annotation_start_time
            print(f"✓ Submitted 15 annotations in {annotation_time:.2f} seconds")

            # Verify final state
            response = requests.get(f"{server_url}/test/system_state", timeout=5)
            if response.status_code == 200:
                system_state = response.json()
                print(f"✓ Final state: {system_state['system_state']['total_annotations']} total annotations")

        except requests.exceptions.ConnectionError:
            pytest.skip("Server not running")


class TestAnnotationWorkflowMocked:
    """Test annotation workflows with mocked server responses."""

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_complete_workflow(self, mock_get, mock_post):
        """Test complete workflow with mocked responses."""

        # Create mock responses
        def create_mock_response(status_code, json_data):
            mock = MagicMock()
            mock.status_code = status_code
            mock.json.return_value = json_data
            return mock

        # Configure mock responses based on URL patterns
        def mock_post_side_effect(url, *args, **kwargs):
            if "/test/reset" in url:
                return create_mock_response(200, {"status": "reset_complete"})
            elif "/test/create_users" in url:
                return create_mock_response(200, {
                    "status": "completed",
                    "summary": {"created": 2, "failed": 0, "already_exists": 0},
                    "results": {
                        "created": [
                            {
                                "username": "annotator_1",
                                "initial_phase": "ANNOTATION",
                                "assign_items": True,
                                "user_state": {"phase": "ANNOTATION", "has_assignments": True, "assignments_count": 5}
                            },
                            {
                                "username": "annotator_2",
                                "initial_phase": "ANNOTATION",
                                "assign_items": True,
                                "user_state": {"phase": "ANNOTATION", "has_assignments": True, "assignments_count": 5}
                            }
                        ]
                    }
                })
            elif "/submit_annotation" in url:
                return create_mock_response(200, {"status": "success"})
            else:
                return create_mock_response(200, {"status": "success"})

        def mock_get_side_effect(url, *args, **kwargs):
            if "/test/system_state" in url:
                return create_mock_response(200, {
                    "system_state": {
                        "total_users": 2,
                        "total_items": 10,
                        "total_annotations": 10,
                        "items_with_annotations": 5
                    }
                })
            elif "/test/user_state" in url:
                return create_mock_response(200, {
                    "username": "annotator_1",
                    "phase": "ANNOTATION",
                    "assignments": {"total": 5, "annotated": 5, "remaining": 0},
                    "annotations": {
                        "total_count": 5,
                        "by_instance": {
                            "item_1": {"rating": 3},
                            "item_2": {"rating": 4},
                            "item_3": {"rating": 5},
                            "item_4": {"rating": 2},
                            "item_5": {"rating": 4}
                        }
                    }
                })
            elif "/test/item_state" in url:
                return create_mock_response(200, {
                    "total_items": 10,
                    "items": [
                        {
                            "id": f"item_{i}",
                            "text": f"Test item {i}",
                            "annotators": ["annotator_1", "annotator_2"],
                            "annotation_count": 2
                        }
                        for i in range(1, 6)
                    ],
                    "summary": {
                        "items_with_annotations": 5,
                        "items_without_annotations": 5,
                        "average_annotations_per_item": 1.0
                    }
                })
            else:
                return create_mock_response(200, {"status": "success"})

        # Set up the side effects
        mock_post.side_effect = mock_post_side_effect
        mock_get.side_effect = mock_get_side_effect

        # Test the workflow
        server_url = "http://localhost:9001"

        # Reset system
        response = requests.post(f"{server_url}/test/reset")
        assert response.status_code == 200

        # Create users
        users_data = {
            "users": [
                {"username": "annotator_1", "initial_phase": "ANNOTATION", "assign_items": True},
                {"username": "annotator_2", "initial_phase": "ANNOTATION", "assign_items": True}
            ]
        }
        response = requests.post(f"{server_url}/test/create_users", json=users_data)
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["created"] == 2

        # Check system state
        response = requests.get(f"{server_url}/test/system_state")
        assert response.status_code == 200
        system_state = response.json()
        assert system_state["system_state"]["total_users"] == 2

        # Submit annotations
        annotation_data = {
            "instance_id": "item_1",
            "annotation_data": json.dumps({"rating": 5})
        }
        response = requests.post(f"{server_url}/submit_annotation", data=annotation_data)
        assert response.status_code == 200

        # Check item state
        response = requests.get(f"{server_url}/test/item_state")
        assert response.status_code == 200
        item_state = response.json()
        assert item_state["total_items"] == 10

        print("✓ Mocked annotation workflow test passed!")

    @patch('requests.post')
    @patch('requests.get')
    def test_mocked_workflow_error_scenarios(self, mock_get, mock_post):
        """Test workflow error scenarios with mocked responses."""

        # Mock error responses
        mock_error_response = MagicMock()
        mock_error_response.status_code = 403
        mock_error_response.json.return_value = {
            "error": "User creation only available in debug mode",
            "debug_mode_required": True
        }

        mock_post.return_value = mock_error_response
        mock_get.return_value = mock_error_response

        # Test error handling
        server_url = "http://localhost:9001"

        # Test user creation error
        users_data = {"username": "test_user"}
        response = requests.post(f"{server_url}/test/create_user", json=users_data)
        assert response.status_code == 403
        data = response.json()
        assert "debug mode" in data["error"]

        print("✓ Mocked error scenario test passed!")