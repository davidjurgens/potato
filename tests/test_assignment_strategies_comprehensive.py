#!/usr/bin/env python3
"""
Comprehensive Assignment Strategy Tests

This module contains comprehensive tests for all item assignment strategies using FlaskTestServer.
Tests verify that each assignment strategy works correctly with at least 10 instances.

Assignment Strategies Tested:
1. Random assignment
2. Fixed order assignment
3. Least-annotated assignment
4. Max-diversity assignment
5. Active learning assignment (placeholder)
6. LLM confidence assignment (placeholder)

Each test creates a dataset with 10+ instances and verifies:
- Proper assignment distribution
- Completion scenarios
- Strategy-specific behavior
"""

import pytest
import json
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tests.flask_test_setup import FlaskTestServer


class TestAssignmentStrategiesComprehensive:
    """Comprehensive tests for all assignment strategies using FlaskTestServer."""

    @pytest.fixture
    def flask_server(self):
        """Create a Flask test server for assignment strategy tests."""
        server = FlaskTestServer(port=9001, debug=True)
        try:
            server.start_server()
            yield server
        finally:
            server.stop_server()

    def create_test_dataset(self, flask_server, strategy, max_annotations_per_item=3):
        """Create a test dataset with 12 instances for assignment strategy testing."""

        # Create 12 test instances with varied content
        test_items = {
            f"item_{i:02d}": {
                "id": f"item_{i:02d}",
                "text": f"This is test item {i} with some content for annotation strategy testing. "
                       f"It contains various topics and sentiments to test different assignment methods.",
                "displayed_text": f"Test Item {i}: Sample content for assignment strategy testing"
            }
            for i in range(1, 13)  # 12 items total
        }

        # Create dataset with specified strategy
        dataset_data = {
            "items": test_items,
            "max_annotations_per_item": max_annotations_per_item,
            "assignment_strategy": strategy
        }

        response = flask_server.post("/test/create_dataset", json=dataset_data, timeout=10)
        assert response.status_code == 200, f"Failed to create dataset: {response.text}"

        result = response.json()
        assert result["status"] == "created"
        assert result["summary"]["created"] == 12
        assert result["summary"]["assignment_strategy"] == strategy
        assert result["summary"]["max_annotations_per_item"] == max_annotations_per_item

        return test_items

    def create_test_users(self, flask_server, num_users=8):
        """Create test users for assignment testing."""
        users_data = {
            "users": [
                {
                    "user_id": f"test_user_{i}",
                    "initial_phase": "annotation",
                    "assign_items": True
                }
                for i in range(1, num_users + 1)
            ]
        }

        response = flask_server.post("/test/create_users", json=users_data, timeout=10)
        assert response.status_code == 200, f"Failed to create users: {response.text}"

        result = response.json()
        assert result["status"] == "created"
        assert len(result["users"]) == num_users

        return [f"test_user_{i}" for i in range(1, num_users + 1)]

    def submit_test_annotation(self, flask_server, user_id, instance_id, annotation_value="option_1"):
        """Submit a test annotation for an instance."""
        annotation_data = {
            "instance_id": instance_id,
            "annotations": {
                "radio_choice": {"label": annotation_value}
            },
            "user_id": user_id
        }

        response = flask_server.post("/test/submit_annotation", json=annotation_data, timeout=10)
        assert response.status_code == 200, f"Failed to submit annotation: {response.text}"

        result = response.json()
        assert result["status"] == "submitted"
        return result

    def get_user_assignments(self, flask_server, user_id):
        """Get current assignments for a user."""
        response = flask_server.get(f"/test/user_state/{user_id}", timeout=10)
        assert response.status_code == 200, f"Failed to get user state: {response.text}"

        user_state = response.json()
        assignments = user_state.get("assignments", {})
        assigned_items = assignments.get("items", [])

        # Extract just the item IDs from the assignment objects
        item_ids = [item.get("id") for item in assigned_items if isinstance(item, dict) and "id" in item]
        return item_ids

    def test_basic_assignment_functionality(self, flask_server):
        """Test basic assignment functionality to debug issues."""

        # Reset system first
        response = flask_server.post("/test/reset", timeout=10)
        assert response.status_code == 200

        # Create a simple dataset
        simple_dataset = {
            "items": {
                "item_1": {"id": "item_1", "text": "Test item 1"},
                "item_2": {"id": "item_2", "text": "Test item 2"},
                "item_3": {"id": "item_3", "text": "Test item 3"}
            },
            "max_annotations_per_item": 2,
            "assignment_strategy": "random"
        }

        response = flask_server.post("/test/create_dataset", json=simple_dataset, timeout=10)
        assert response.status_code == 200
        print(f"Dataset creation response: {response.json()}")

        # Create a single user
        user_data = {
            "users": [{"user_id": "debug_user", "initial_phase": "annotation", "assign_items": True}]
        }

        response = flask_server.post("/test/create_users", json=user_data, timeout=10)
        assert response.status_code == 200
        print(f"User creation response: {response.json()}")

        # Check user state
        response = flask_server.get("/test/user_state/debug_user", timeout=10)
        assert response.status_code == 200
        user_state = response.json()
        print(f"User state: {user_state}")

        # Check if user has assignments
        assignments = user_state.get("assignments", {})
        assigned_items = assignments.get("items", [])
        print(f"Assigned items: {assigned_items}")

        # Basic assertion - user should have some assignments
        assert len(assigned_items) > 0, "User should have assignments"

    def test_random_assignment_strategy(self, flask_server):
        """Test random assignment strategy with 12 instances."""

        # Create dataset with random assignment
        test_items = self.create_test_dataset(flask_server, "random", max_annotations_per_item=3)

        # Create 8 users
        user_ids = self.create_test_users(flask_server, num_users=8)

        # Track assignments for each user
        user_assignments = {}
        all_assigned_items = set()

        # Test initial assignments for all users
        for user_id in user_ids:
            # Get user state to see assignments
            assignments = self.get_user_assignments(flask_server, user_id)
            assigned_items = assignments.get("items", [])

            user_assignments[user_id] = assigned_items
            all_assigned_items.update(assigned_items)

            # Verify user has assignments
            assert len(assigned_items) > 0, f"User {user_id} should have assignments"
            print(f"User {user_id} assigned: {assigned_items}")

        # Verify random distribution (not all users get same items)
        first_user_items = set(user_assignments[user_ids[0]])
        different_assignments = 0

        for user_id in user_ids[1:]:
            if set(user_assignments[user_id]) != first_user_items:
                different_assignments += 1

        # At least 50% of users should have different assignments (random distribution)
        assert different_assignments >= len(user_ids) * 0.5, "Random assignment should create varied distributions"

        # Test completion scenario by annotating all items
        for user_id in user_ids:
            assignments = self.get_user_assignments(flask_server, user_id)
            assigned_items = assignments.get("items", [])

            # Submit annotations for all assigned items
            for item_id in assigned_items:
                self.submit_test_annotation(flask_server, user_id, item_id)

        # Verify completion - new users should get no assignments
        new_user_data = {
            "users": [{"user_id": "completion_test_user", "initial_phase": "annotation", "assign_items": True}]
        }

        response = flask_server.post("/test/create_users", json=new_user_data, timeout=10)
        assert response.status_code == 200

        # Check that new user has no assignments (all items completed)
        assignments = self.get_user_assignments(flask_server, "completion_test_user")
        assert len(assignments.get("items", [])) == 0, "New user should have no assignments when all items are completed"

    def test_fixed_order_assignment_strategy(self, flask_server):
        """Test fixed order assignment strategy with 12 instances."""

        # Create dataset with fixed order assignment
        test_items = self.create_test_dataset(flask_server, "fixed_order", max_annotations_per_item=2)

        # Create 6 users
        user_ids = self.create_test_users(flask_server, num_users=6)

        # Track assignment order
        assignment_order = []

        # Test initial assignments
        for user_id in user_ids:
            assignments = self.get_user_assignments(flask_server, user_id)
            assigned_items = assignments.get("items", [])

            assignment_order.extend(assigned_items)
            assert len(assigned_items) > 0, f"User {user_id} should have assignments"
            print(f"User {user_id} assigned: {assigned_items}")

        # Verify fixed order (should follow item_01, item_02, item_03, etc.)
        expected_order = [f"item_{i:02d}" for i in range(1, 13)]

        # Check that assignments follow the expected order
        for i, item_id in enumerate(assignment_order[:len(expected_order)]):
            assert item_id == expected_order[i], f"Fixed order assignment failed: expected {expected_order[i]}, got {item_id}"

        # Test completion by annotating all items
        for user_id in user_ids:
            assignments = self.get_user_assignments(flask_server, user_id)
            assigned_items = assignments.get("items", [])

            for item_id in assigned_items:
                self.submit_test_annotation(flask_server, user_id, item_id)

        # Verify completion
        new_user_data = {
            "users": [{"user_id": "fixed_order_completion_user", "initial_phase": "annotation", "assign_items": True}]
        }

        response = flask_server.post("/test/create_users", json=new_user_data, timeout=10)
        assert response.status_code == 200

        assignments = self.get_user_assignments(flask_server, "fixed_order_completion_user")
        assert len(assignments.get("items", [])) == 0, "New user should have no assignments when all items are completed"

    def test_least_annotated_assignment_strategy(self, flask_server):
        """Test least-annotated assignment strategy with 12 instances."""

        # Create dataset with least-annotated assignment
        test_items = self.create_test_dataset(flask_server, "least_annotated", max_annotations_per_item=3)

        # Create 12 users to test distribution
        user_ids = self.create_test_users(flask_server, num_users=12)

        # Track annotation counts for each item
        item_annotation_counts = {f"item_{i:02d}": 0 for i in range(1, 13)}

        # Test initial assignments and submit some annotations
        for i, user_id in enumerate(user_ids[:6]):  # First 6 users
            assignments = self.get_user_assignments(flask_server, user_id)
            assigned_items = assignments.get("items", [])

            assert len(assigned_items) > 0, f"User {user_id} should have assignments"

            # Submit annotation for first assigned item
            if assigned_items:
                item_id = assigned_items[0]
                self.submit_test_annotation(flask_server, user_id, item_id)
                item_annotation_counts[item_id] += 1
                print(f"User {user_id} annotated {item_id}, count now: {item_annotation_counts[item_id]}")

        # Create new users and verify they get least-annotated items
        new_users_data = {
            "users": [
                {"user_id": f"least_annotated_user_{i}", "initial_phase": "annotation", "assign_items": True}
                for i in range(1, 4)
            ]
        }

        response = flask_server.post("/test/create_users", json=new_users_data, timeout=10)
        assert response.status_code == 200

        # Check that new users get items with fewer annotations
        for i in range(1, 4):
            user_id = f"least_annotated_user_{i}"
            assignments = self.get_user_assignments(flask_server, user_id)
            assigned_items = assignments.get("items", [])

            if assigned_items:
                # Verify assigned items have fewer annotations
                for item_id in assigned_items:
                    annotation_count = item_annotation_counts[item_id]
                    assert annotation_count <= 1, f"Least-annotated strategy should prioritize items with fewer annotations, but {item_id} has {annotation_count}"

    def test_max_diversity_assignment_strategy(self, flask_server):
        """Test max-diversity assignment strategy with 12 instances."""

        # Create dataset with max-diversity assignment
        test_items = self.create_test_dataset(flask_server, "max_diversity", max_annotations_per_item=3)

        # Create 8 users
        user_ids = self.create_test_users(flask_server, num_users=8)

        # First, create diverse annotations on some items
        diverse_items = ["item_01", "item_02", "item_03"]
        diverse_annotations = ["option_1", "option_2", "option_3"]

        # Submit diverse annotations to create disagreement
        for i, item_id in enumerate(diverse_items):
            for j, user_id in enumerate(user_ids[:3]):
                annotation_value = diverse_annotations[(i + j) % 3]  # Cycle through different annotations
                self.submit_test_annotation(flask_server, user_id, item_id, annotation_value)
                print(f"Created diverse annotation: {user_id} -> {item_id} -> {annotation_value}")

        # Create new users and verify they get items with diverse annotations
        new_users_data = {
            "users": [
                {"user_id": f"diversity_user_{i}", "initial_phase": "annotation", "assign_items": True}
                for i in range(1, 4)
            ]
        }

        response = flask_server.post("/test/create_users", json=new_users_data, timeout=10)
        assert response.status_code == 200

        # Check that new users get assignments (max-diversity should prioritize diverse items)
        for i in range(1, 4):
            user_id = f"diversity_user_{i}"
            assignments = self.get_user_assignments(flask_server, user_id)
            assigned_items = assignments.get("items", [])

            # Max-diversity should still assign items (the strategy prioritizes diverse items)
            assert len(assigned_items) > 0, f"Max-diversity user {user_id} should have assignments"

    def test_active_learning_assignment_strategy(self, flask_server):
        """Test active learning assignment strategy (placeholder implementation)."""

        # Create dataset with active learning assignment
        test_items = self.create_test_dataset(flask_server, "active_learning", max_annotations_per_item=2)

        # Create 6 users
        user_ids = self.create_test_users(flask_server, num_users=6)

        # Test that active learning currently falls back to random assignment
        user_assignments = {}

        for user_id in user_ids:
            assignments = self.get_user_assignments(flask_server, user_id)
            assigned_items = assignments.get("items", [])

            user_assignments[user_id] = assigned_items
            assert len(assigned_items) > 0, f"User {user_id} should have assignments"
            print(f"Active learning user {user_id} assigned: {assigned_items}")

        # Verify that assignments are made (placeholder implementation should work)
        all_assigned = any(len(items) > 0 for items in user_assignments.values())
        assert all_assigned, "Active learning placeholder should assign items"

    def test_llm_confidence_assignment_strategy(self, flask_server):
        """Test LLM confidence assignment strategy (placeholder implementation)."""

        # Create dataset with LLM confidence assignment
        test_items = self.create_test_dataset(flask_server, "llm_confidence", max_annotations_per_item=2)

        # Create 6 users
        user_ids = self.create_test_users(flask_server, num_users=6)

        # Test that LLM confidence currently falls back to random assignment
        user_assignments = {}

        for user_id in user_ids:
            assignments = self.get_user_assignments(flask_server, user_id)
            assigned_items = assignments.get("items", [])

            user_assignments[user_id] = assigned_items
            assert len(assigned_items) > 0, f"User {user_id} should have assignments"
            print(f"LLM confidence user {user_id} assigned: {assigned_items}")

        # Verify that assignments are made (placeholder implementation should work)
        all_assigned = any(len(items) > 0 for items in user_assignments.values())
        assert all_assigned, "LLM confidence placeholder should assign items"

    def test_assignment_strategy_completion_scenarios(self, flask_server):
        """Test completion scenarios for all assignment strategies."""

        strategies = ["random", "fixed_order", "least_annotated", "max_diversity"]

        for strategy in strategies:
            print(f"\nTesting completion scenario for {strategy} strategy")

            # Reset system
            response = flask_server.post("/test/reset", timeout=10)
            assert response.status_code == 200

            # Create dataset
            test_items = self.create_test_dataset(flask_server, strategy, max_annotations_per_item=2)

            # Create users and complete all annotations
            user_ids = self.create_test_users(flask_server, num_users=8)

            # Complete all annotations
            for user_id in user_ids:
                assignments = self.get_user_assignments(flask_server, user_id)
                assigned_items = assignments.get("items", [])

                for item_id in assigned_items:
                    self.submit_test_annotation(flask_server, user_id, item_id)

            # Verify completion - new user should get no assignments
            completion_user_data = {
                "users": [{"user_id": f"completion_user_{strategy}", "initial_phase": "annotation", "assign_items": True}]
            }

            response = flask_server.post("/test/create_users", json=completion_user_data, timeout=10)
            assert response.status_code == 200

            assignments = self.get_user_assignments(flask_server, f"completion_user_{strategy}")
            assert len(assignments.get("items", [])) == 0, f"Completion test failed for {strategy} strategy"

    def test_assignment_strategy_edge_cases(self, flask_server):
        """Test edge cases for assignment strategies."""

        # Test with single item
        single_item_data = {
            "items": {
                "single_item": {
                    "id": "single_item",
                    "text": "This is the only item for testing",
                    "displayed_text": "Single Item Test"
                }
            },
            "max_annotations_per_item": 3,
            "assignment_strategy": "random"
        }

        response = flask_server.post("/test/create_dataset", json=single_item_data, timeout=10)
        assert response.status_code == 200

        # Create users
        user_ids = self.create_test_users(flask_server, num_users=3)

        # Verify all users get the single item
        for user_id in user_ids:
            assignments = self.get_user_assignments(flask_server, user_id)
            assigned_items = assignments.get("items", [])
            assert "single_item" in assigned_items, f"User {user_id} should be assigned the single item"

        # Test with zero max annotations
        response = flask_server.post("/test/reset", timeout=10)
        assert response.status_code == 200

        zero_max_data = {
            "items": {
                f"item_{i}": {
                    "id": f"item_{i}",
                    "text": f"Test item {i}",
                    "displayed_text": f"Test Item {i}"
                }
                for i in range(1, 6)
            },
            "max_annotations_per_item": 0,
            "assignment_strategy": "random"
        }

        response = flask_server.post("/test/create_dataset", json=zero_max_data, timeout=10)
        assert response.status_code == 200

        # Create user and verify no assignments
        user_data = {
            "users": [{"user_id": "zero_max_user", "initial_phase": "annotation", "assign_items": True}]
        }

        response = flask_server.post("/test/create_users", json=user_data, timeout=10)
        assert response.status_code == 200

        assignments = self.get_user_assignments(flask_server, "zero_max_user")
        assert len(assignments.get("items", [])) == 0, "User should have no assignments with zero max annotations"


if __name__ == "__main__":
    # Run tests directly
    pytest.main([__file__, "-v"])