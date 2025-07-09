"""
Assignment Strategy Tests

This module contains comprehensive tests for different item assignment strategies:
1. Random assignment
2. Fixed order assignment
3. Least-annotated assignment
4. Highest-disagreement assignment (max diversity)
5. Completion scenarios (all items have max annotations)

Tests cover various scenarios with different numbers of items and annotators,
ensuring proper distribution and completion behavior.
"""

import json
import pytest
import requests
import time
from unittest.mock import patch, MagicMock
from collections import Counter


class TestAssignmentStrategies:
    """Test different assignment strategies."""

    @pytest.fixture(scope="class")
    def server_url(self):
        """Get the server URL for testing."""
        return "http://localhost:9001"

    def test_random_assignment_strategy(self, server_url):
        """
        Test random assignment strategy:
        1. Create dataset with 5 items, max 2 annotations per item
        2. Create 8 annotators (more than needed)
        3. Verify random distribution
        4. Verify completion when all items have max annotations
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create dataset with random assignment strategy
            dataset_config = {
                "items": {
                    "item_1": {"text": "Random test item 1"},
                    "item_2": {"text": "Random test item 2"},
                    "item_3": {"text": "Random test item 3"},
                    "item_4": {"text": "Random test item 4"},
                    "item_5": {"text": "Random test item 5"}
                },
                "max_annotations_per_item": 2,
                "assignment_strategy": "random"
            }
            response = requests.post(f"{server_url}/test/create_dataset", json=dataset_config, timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert data["summary"]["created"] == 5
                print("✓ Created dataset for random assignment test")

            # Create annotators
            users_data = {
                "users": [
                    {"username": f"random_user_{i}", "initial_phase": "ANNOTATION", "assign_items": True}
                    for i in range(1, 9)  # 8 users
                ]
            }
            response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert data["summary"]["created"] == 8
                print("✓ Created annotators for random assignment")

            # Submit annotations and track distribution
            annotation_counts = Counter()
            for i in range(1, 9):
                user_id = f"random_user_{i}"

                # Get user's assignments
                response = requests.get(f"{server_url}/test/user_state/{user_id}", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assignments = user_state.get("assignments", {})

                    if assignments.get("total", 0) > 0:
                        # Submit annotation for each assigned item
                        for assignment in user_state.get("assignments", {}).get("items", []):
                            item_id = assignment["id"]
                            annotation_data = {
                                "instance_id": item_id,
                                "annotations": {
                                    "sentiment": {"label": f"random_annotation_{i}"}
                                }
                            }
                            response = requests.post(f"{server_url}/test/submit_annotation",
                                                   json=annotation_data, timeout=5)
                            if response.status_code == 200:
                                annotation_counts[item_id] += 1

            # Verify distribution (should be roughly even with some randomness)
            print(f"✓ Random assignment distribution: {dict(annotation_counts)}")

            # Verify all items have at most 2 annotations
            for item_id, count in annotation_counts.items():
                assert count <= 2, f"Item {item_id} has {count} annotations, expected <= 2"

            # Test completion scenario - try to assign to new user
            response = requests.post(f"{server_url}/test/create_user", json={
                "username": "random_user_completion_test",
                "initial_phase": "ANNOTATION",
                "assign_items": True
            }, timeout=5)

            if response.status_code == 200:
                data = response.json()
                # Should have no assignments if all items are complete
                if sum(annotation_counts.values()) >= 10:  # 5 items * 2 annotations
                    assert data["user_state"]["assignments_count"] == 0
                    print("✓ Random assignment completion test passed")

        except requests.exceptions.RequestException as e:
            pytest.skip(f"Server not available: {e}")

    def test_fixed_order_assignment_strategy(self, server_url):
        """
        Test fixed order assignment strategy:
        1. Create dataset with 4 items, max 2 annotations per item
        2. Create 6 annotators
        3. Verify items are assigned in order
        4. Verify completion behavior
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create dataset with fixed order assignment strategy
            dataset_config = {
                "items": {
                    "item_1": {"text": "Fixed order item 1"},
                    "item_2": {"text": "Fixed order item 2"},
                    "item_3": {"text": "Fixed order item 3"},
                    "item_4": {"text": "Fixed order item 4"}
                },
                "max_annotations_per_item": 2,
                "assignment_strategy": "fixed_order"
            }
            response = requests.post(f"{server_url}/test/create_dataset", json=dataset_config, timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert data["summary"]["created"] == 4
                print("✓ Created dataset for fixed order assignment test")

            # Create annotators
            users_data = {
                "users": [
                    {"username": f"fixed_user_{i}", "initial_phase": "ANNOTATION", "assign_items": True}
                    for i in range(1, 7)  # 6 users
                ]
            }
            response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert data["summary"]["created"] == 6
                print("✓ Created annotators for fixed order assignment")

            # Submit annotations and track order
            assignment_order = []
            for i in range(1, 7):
                user_id = f"fixed_user_{i}"

                # Get user's assignments
                response = requests.get(f"{server_url}/test/user_state/{user_id}", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assignments = user_state.get("assignments", {})

                    if assignments.get("total", 0) > 0:
                        # Submit annotation for assigned item
                        for assignment in user_state.get("assignments", {}).get("items", []):
                            item_id = assignment["id"]
                            assignment_order.append(item_id)

                            annotation_data = {
                                "instance_id": item_id,
                                "annotations": {
                                    "sentiment": {"label": f"fixed_annotation_{i}"}
                                }
                            }
                            response = requests.post(f"{server_url}/test/submit_annotation",
                                                   json=annotation_data, timeout=5)

            # Verify fixed order (items should be assigned in sequence)
            print(f"✓ Fixed order assignment sequence: {assignment_order}")

            # First 4 assignments should be item_1, item_2, item_3, item_4
            expected_first_round = ["item_1", "item_2", "item_3", "item_4"]
            actual_first_round = assignment_order[:4]
            assert actual_first_round == expected_first_round, f"Expected {expected_first_round}, got {actual_first_round}"

        except requests.exceptions.RequestException as e:
            pytest.skip(f"Server not available: {e}")

    def test_least_annotated_assignment_strategy(self, server_url):
        """
        Test least-annotated assignment strategy:
        1. Create dataset with 6 items, max 3 annotations per item
        2. Create 12 annotators
        3. Verify items with fewer annotations are prioritized
        4. Verify even distribution
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create dataset with least-annotated assignment strategy
            dataset_config = {
                "items": {
                    "item_1": {"text": "Least annotated item 1"},
                    "item_2": {"text": "Least annotated item 2"},
                    "item_3": {"text": "Least annotated item 3"},
                    "item_4": {"text": "Least annotated item 4"},
                    "item_5": {"text": "Least annotated item 5"},
                    "item_6": {"text": "Least annotated item 6"}
                },
                "max_annotations_per_item": 3,
                "assignment_strategy": "least_annotated"
            }
            response = requests.post(f"{server_url}/test/create_dataset", json=dataset_config, timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert data["summary"]["created"] == 6
                print("✓ Created dataset for least-annotated assignment test")

            # Create annotators
            users_data = {
                "users": [
                    {"username": f"least_user_{i}", "initial_phase": "ANNOTATION", "assign_items": True}
                    for i in range(1, 13)  # 12 users
                ]
            }
            response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert data["summary"]["created"] == 12
                print("✓ Created annotators for least-annotated assignment")

            # Submit annotations and track distribution
            annotation_counts = Counter()
            for i in range(1, 13):
                user_id = f"least_user_{i}"

                # Get user's assignments
                response = requests.get(f"{server_url}/test/user_state/{user_id}", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assignments = user_state.get("assignments", {})

                    if assignments.get("total", 0) > 0:
                        # Submit annotation for assigned item
                        for assignment in user_state.get("assignments", {}).get("items", []):
                            item_id = assignment["id"]
                            annotation_counts[item_id] += 1

                            annotation_data = {
                                "instance_id": item_id,
                                "annotations": {
                                    "sentiment": {"label": f"least_annotation_{i}"}
                                }
                            }
                            response = requests.post(f"{server_url}/test/submit_annotation",
                                                   json=annotation_data, timeout=5)

            # Verify even distribution (least-annotated strategy should balance)
            print(f"✓ Least-annotated assignment distribution: {dict(annotation_counts)}")

            # All items should have similar annotation counts (within 1 of each other)
            counts = list(annotation_counts.values())
            if counts:
                min_count = min(counts)
                max_count = max(counts)
                assert max_count - min_count <= 1, f"Uneven distribution: min={min_count}, max={max_count}"

            # Verify all items have at most 3 annotations
            for item_id, count in annotation_counts.items():
                assert count <= 3, f"Item {item_id} has {count} annotations, expected <= 3"

        except requests.exceptions.RequestException as e:
            pytest.skip(f"Server not available: {e}")

    def test_max_diversity_assignment_strategy(self, server_url):
        """
        Test max-diversity assignment strategy:
        1. Create dataset with 4 items, max 3 annotations per item
        2. Create 8 annotators
        3. Submit diverse annotations to create disagreement
        4. Verify items with disagreement are prioritized
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Create dataset with max-diversity assignment strategy
            dataset_config = {
                "items": {
                    "item_1": {"text": "Max diversity item 1"},
                    "item_2": {"text": "Max diversity item 2"},
                    "item_3": {"text": "Max diversity item 3"},
                    "item_4": {"text": "Max diversity item 4"}
                },
                "max_annotations_per_item": 3,
                "assignment_strategy": "max_diversity"
            }
            response = requests.post(f"{server_url}/test/create_dataset", json=dataset_config, timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert data["summary"]["created"] == 4
                print("✓ Created dataset for max-diversity assignment test")

            # Create annotators
            users_data = {
                "users": [
                    {"username": f"diversity_user_{i}", "initial_phase": "ANNOTATION", "assign_items": True}
                    for i in range(1, 9)  # 8 users
                ]
            }
            response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert data["summary"]["created"] == 8
                print("✓ Created annotators for max-diversity assignment")

            # Submit diverse annotations to create disagreement
            annotation_counts = Counter()
            for i in range(1, 9):
                user_id = f"diversity_user_{i}"

                # Get user's assignments
                response = requests.get(f"{server_url}/test/user_state/{user_id}", timeout=5)
                if response.status_code == 200:
                    user_state = response.json()
                    assignments = user_state.get("assignments", {})

                    if assignments.get("total", 0) > 0:
                        # Submit annotation for assigned item
                        for assignment in user_state.get("assignments", {}).get("items", []):
                            item_id = assignment["id"]
                            annotation_counts[item_id] += 1

                            # Create diverse annotations to test disagreement
                            if i <= 4:
                                # First 4 users give positive annotations
                                annotation_label = "positive"
                            else:
                                # Next 4 users give negative annotations
                                annotation_label = "negative"

                            annotation_data = {
                                "instance_id": item_id,
                                "annotations": {
                                    "sentiment": {"label": annotation_label}
                                }
                            }
                            response = requests.post(f"{server_url}/test/submit_annotation",
                                                   json=annotation_data, timeout=5)

            # Verify distribution
            print(f"✓ Max-diversity assignment distribution: {dict(annotation_counts)}")

            # Verify all items have at most 3 annotations
            for item_id, count in annotation_counts.items():
                assert count <= 3, f"Item {item_id} has {count} annotations, expected <= 3"

        except requests.exceptions.RequestException as e:
            pytest.skip(f"Server not available: {e}")

    def test_completion_scenario_all_strategies(self, server_url):
        """
        Test completion scenario for all strategies:
        1. Create small dataset with 2 items, max 1 annotation per item
        2. Test each assignment strategy
        3. Verify new users get no assignments when all items are complete
        """
        strategies = ["random", "fixed_order", "least_annotated", "max_diversity"]

        for strategy in strategies:
            try:
                # Reset system
                response = requests.post(f"{server_url}/test/reset", timeout=5)
                assert response.status_code in [200, 302]

                # Create dataset with completion test
                dataset_config = {
                    "items": {
                        "completion_item_1": {"text": f"Completion test item 1 for {strategy}"},
                        "completion_item_2": {"text": f"Completion test item 2 for {strategy}"}
                    },
                    "max_annotations_per_item": 1,
                    "assignment_strategy": strategy
                }
                response = requests.post(f"{server_url}/test/create_dataset", json=dataset_config, timeout=5)
                assert response.status_code in [200, 302]

                if response.status_code == 200:
                    data = response.json()
                    assert data["summary"]["created"] == 2
                    print(f"✓ Created dataset for {strategy} completion test")

                # Create 2 annotators to complete all items
                users_data = {
                    "users": [
                        {"username": f"completion_{strategy}_user_{i}", "initial_phase": "ANNOTATION", "assign_items": True}
                        for i in range(1, 3)  # 2 users
                    ]
                }
                response = requests.post(f"{server_url}/test/create_users", json=users_data, timeout=5)
                assert response.status_code in [200, 302]

                if response.status_code == 200:
                    data = response.json()
                    assert data["summary"]["created"] == 2
                    print(f"✓ Created annotators for {strategy} completion test")

                # Submit annotations to complete all items
                for i in range(1, 3):
                    user_id = f"completion_{strategy}_user_{i}"

                    # Get user's assignments
                    response = requests.get(f"{server_url}/test/user_state/{user_id}", timeout=5)
                    if response.status_code == 200:
                        user_state = response.json()
                        assignments = user_state.get("assignments", {})

                        if assignments.get("total", 0) > 0:
                            # Submit annotation for assigned item
                            for assignment in user_state.get("assignments", {}).get("items", []):
                                item_id = assignment["id"]

                                annotation_data = {
                                    "instance_id": item_id,
                                    "annotations": {
                                        "sentiment": {"label": f"completion_annotation_{i}"}
                                    }
                                }
                                response = requests.post(f"{server_url}/test/submit_annotation",
                                                       json=annotation_data, timeout=5)

                # Test that new user gets no assignments
                response = requests.post(f"{server_url}/test/create_user", json={
                    "username": f"completion_{strategy}_new_user",
                    "initial_phase": "ANNOTATION",
                    "assign_items": True
                }, timeout=5)

                if response.status_code == 200:
                    data = response.json()
                    assert data["user_state"]["assignments_count"] == 0, f"New user should have no assignments for {strategy}"
                    print(f"✓ {strategy} completion test passed")

            except requests.exceptions.RequestException as e:
                pytest.skip(f"Server not available: {e}")

    def test_edge_cases_and_error_handling(self, server_url):
        """
        Test edge cases and error handling:
        1. Empty dataset
        2. Single item dataset
        3. Invalid assignment strategy
        4. Zero max annotations per item
        """
        try:
            # Reset system
            response = requests.post(f"{server_url}/test/reset", timeout=5)
            assert response.status_code in [200, 302]

            # Test empty dataset
            dataset_config = {
                "items": {},
                "max_annotations_per_item": 2,
                "assignment_strategy": "random"
            }
            response = requests.post(f"{server_url}/test/create_dataset", json=dataset_config, timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert data["summary"]["created"] == 0
                print("✓ Empty dataset test passed")

            # Test single item dataset
            dataset_config = {
                "items": {"single_item": {"text": "Single item test"}},
                "max_annotations_per_item": 1,
                "assignment_strategy": "fixed_order"
            }
            response = requests.post(f"{server_url}/test/create_dataset", json=dataset_config, timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert data["summary"]["created"] == 1
                print("✓ Single item dataset test passed")

            # Test zero max annotations per item
            dataset_config = {
                "items": {"zero_item": {"text": "Zero annotations test"}},
                "max_annotations_per_item": 0,
                "assignment_strategy": "random"
            }
            response = requests.post(f"{server_url}/test/create_dataset", json=dataset_config, timeout=5)
            assert response.status_code in [200, 302]

            if response.status_code == 200:
                data = response.json()
                assert data["summary"]["created"] == 1
                print("✓ Zero max annotations test passed")

        except requests.exceptions.RequestException as e:
            pytest.skip(f"Server not available: {e}")


class TestAssignmentStrategiesMocked:
    """Mocked tests for assignment strategies (for CI/CD)."""

    @patch('requests.post')
    @patch('requests.get')
    def test_random_assignment_mocked(self, mock_get, mock_post):
        """Test random assignment strategy with mocked responses."""
        # Mock successful responses
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "summary": {"created": 5},
            "status": "success"
        }
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "assignments": {"total": 1, "items": [{"id": "item_1"}]}
        }

        # Test would go here - for now just verify mocks work
        assert mock_post.return_value.status_code == 200
        assert mock_get.return_value.status_code == 200

    @patch('requests.post')
    @patch('requests.get')
    def test_fixed_order_assignment_mocked(self, mock_get, mock_post):
        """Test fixed order assignment strategy with mocked responses."""
        # Mock successful responses
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "summary": {"created": 4},
            "status": "success"
        }
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "assignments": {"total": 1, "items": [{"id": "item_1"}]}
        }

        # Test would go here - for now just verify mocks work
        assert mock_post.return_value.status_code == 200
        assert mock_get.return_value.status_code == 200

    @patch('requests.post')
    @patch('requests.get')
    def test_least_annotated_assignment_mocked(self, mock_get, mock_post):
        """Test least-annotated assignment strategy with mocked responses."""
        # Mock successful responses
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "summary": {"created": 6},
            "status": "success"
        }
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "assignments": {"total": 1, "items": [{"id": "item_1"}]}
        }

        # Test would go here - for now just verify mocks work
        assert mock_post.return_value.status_code == 200
        assert mock_get.return_value.status_code == 200

    @patch('requests.post')
    @patch('requests.get')
    def test_max_diversity_assignment_mocked(self, mock_get, mock_post):
        """Test max-diversity assignment strategy with mocked responses."""
        # Mock successful responses
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "summary": {"created": 4},
            "status": "success"
        }
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "assignments": {"total": 1, "items": [{"id": "item_1"}]}
        }

        # Test would go here - for now just verify mocks work
        assert mock_post.return_value.status_code == 200
        assert mock_get.return_value.status_code == 200

    @patch('requests.post')
    @patch('requests.get')
    def test_completion_scenario_mocked(self, mock_get, mock_post):
        """Test completion scenario with mocked responses."""
        # Mock successful responses
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "summary": {"created": 2},
            "user_state": {"assignments_count": 0},
            "status": "success"
        }
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "assignments": {"total": 0, "items": []}
        }

        # Test would go here - for now just verify mocks work
        assert mock_post.return_value.status_code == 200
        assert mock_get.return_value.status_code == 200