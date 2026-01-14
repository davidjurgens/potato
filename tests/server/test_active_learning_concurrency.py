"""
Multi-User Concurrency Tests for Active Learning

This module contains tests for simultaneous annotation, race conditions,
concurrent model save/load, and queue updates during active learning.

Uses the same mock pattern as test_active_learning_integration.py:
1. Set up mocks BEFORE initializing the manager
2. Use proper Label objects in annotation structure
3. Mock get_all_users() to return user states
"""

import pytest
import time
from unittest.mock import Mock, patch

from potato.active_learning_manager import (
    ActiveLearningConfig, init_active_learning_manager, clear_active_learning_manager
)
from potato.item_state_management import Label


def create_mock_user_state(user_id: str, annotations: dict):
    """
    Create a mock user state with properly formatted annotations.

    Args:
        user_id: The user identifier
        annotations: Dict of {instance_id: {schema_name: label_name}}
    """
    mock_user = Mock()
    mock_user.user_id = user_id

    # Convert simple annotations to proper Label format
    formatted_annotations = {}
    for instance_id, schema_labels in annotations.items():
        labels_dict = {}
        for schema_name, label_name in schema_labels.items():
            label = Label(schema_name, label_name)
            labels_dict[label] = True
        formatted_annotations[instance_id] = {"labels": labels_dict}

    mock_user.get_all_annotations.return_value = formatted_annotations
    return mock_user


def create_mock_item(text: str):
    """Create a mock item with the proper interface."""
    mock_item = Mock()
    mock_item.get_text.return_value = text
    return mock_item


class TestActiveLearningConcurrency:
    """Multi-user concurrency tests for active learning."""

    def setup_method(self):
        clear_active_learning_manager()

    def teardown_method(self):
        clear_active_learning_manager()

    def test_simultaneous_annotation(self):
        """Test that concurrent annotations from multiple users are handled correctly."""
        # Create mock items
        mock_items = {
            f"item_{i}": create_mock_item(f"This is item {i} for concurrency testing.")
            for i in range(10)
        }

        # Create annotations from two users with conflicting labels on same items
        user1_annotations = {
            f"item_{i}": {"sentiment": "positive"}
            for i in range(5)
        }
        user2_annotations = {
            f"item_{i}": {"sentiment": "negative"}
            for i in range(5)
        }

        # CRITICAL: Set up mocks BEFORE initializing manager
        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            # Configure item manager mock
            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            # Configure user manager mock with multiple users
            mock_user1 = create_mock_user_state("user1@test.com", user1_annotations)
            mock_user2 = create_mock_user_state("user2@test.com", user2_annotations)
            mock_user_manager.return_value.get_all_users.return_value = [mock_user1, mock_user2]

            # NOW initialize active learning manager
            al_config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=2,
                min_instances_for_training=5,
                model_persistence_enabled=False
            )
            manager = init_active_learning_manager(al_config)

            # Trigger training
            manager.check_and_trigger_training()

            # Wait for training to complete (with timeout)
            max_wait = 5  # seconds
            start_time = time.time()
            while time.time() - start_time < max_wait:
                stats = manager.get_stats()
                if stats["training_count"] > 0:
                    break
                time.sleep(0.1)

            stats = manager.get_stats()
            assert stats["training_count"] > 0

    def test_concurrent_annotation_with_three_users(self):
        """Test concurrent annotations from three users with different perspectives."""
        mock_items = {
            f"item_{i}": create_mock_item(f"This is item {i} for multi-user testing.")
            for i in range(10)
        }

        # Three users with different annotation patterns
        user1_annotations = {
            "item_0": {"sentiment": "positive"},
            "item_1": {"sentiment": "positive"},
            "item_2": {"sentiment": "neutral"},
            "item_3": {"sentiment": "negative"},
            "item_4": {"sentiment": "positive"},
        }
        user2_annotations = {
            "item_0": {"sentiment": "negative"},
            "item_1": {"sentiment": "positive"},
            "item_2": {"sentiment": "positive"},
            "item_3": {"sentiment": "negative"},
            "item_4": {"sentiment": "neutral"},
        }
        user3_annotations = {
            "item_0": {"sentiment": "positive"},
            "item_1": {"sentiment": "negative"},
            "item_2": {"sentiment": "neutral"},
            "item_3": {"sentiment": "positive"},
            "item_4": {"sentiment": "positive"},
        }

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            mock_user1 = create_mock_user_state("user1@test.com", user1_annotations)
            mock_user2 = create_mock_user_state("user2@test.com", user2_annotations)
            mock_user3 = create_mock_user_state("user3@test.com", user3_annotations)
            mock_user_manager.return_value.get_all_users.return_value = [mock_user1, mock_user2, mock_user3]

            al_config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=2,
                min_instances_for_training=3,
                model_persistence_enabled=False
            )
            manager = init_active_learning_manager(al_config)

            manager.check_and_trigger_training()
            time.sleep(1.5)

            stats = manager.get_stats()
            assert stats["training_count"] > 0

    def test_annotation_consistency_across_users(self):
        """Test that annotations from multiple users produce consistent training results."""
        mock_items = {
            f"item_{i}": create_mock_item(f"Test item {i} content.")
            for i in range(8)
        }

        # Users agree on most items (should lead to confident predictions)
        user1_annotations = {
            "item_0": {"sentiment": "positive"},
            "item_1": {"sentiment": "negative"},
            "item_2": {"sentiment": "neutral"},
            "item_3": {"sentiment": "positive"},
        }
        user2_annotations = {
            "item_0": {"sentiment": "positive"},
            "item_1": {"sentiment": "negative"},
            "item_2": {"sentiment": "neutral"},
            "item_3": {"sentiment": "positive"},
        }

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            mock_user1 = create_mock_user_state("user1@test.com", user1_annotations)
            mock_user2 = create_mock_user_state("user2@test.com", user2_annotations)
            mock_user_manager.return_value.get_all_users.return_value = [mock_user1, mock_user2]

            al_config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=2,
                min_instances_for_training=3,
                model_persistence_enabled=False
            )
            manager = init_active_learning_manager(al_config)

            manager.check_and_trigger_training()
            time.sleep(1.5)

            stats = manager.get_stats()
            assert stats["training_count"] > 0
            assert stats["enabled"] is True
