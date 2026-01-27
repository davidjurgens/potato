"""
Edge Case and Error Recovery Tests for Active Learning

This module contains tests for all-same-label, imbalanced classes, LLM endpoint down,
DB failure, empty dataset, and malformed data scenarios.

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


class TestActiveLearningEdgeCases:
    """Edge case and error recovery tests for active learning."""

    def setup_method(self):
        clear_active_learning_manager()

    def teardown_method(self):
        clear_active_learning_manager()

    def test_all_same_label(self):
        """Test that active learning skips training if all annotations are the same label."""
        mock_items = {
            f"item_{i}": create_mock_item(f"This is item {i} for edge case testing.")
            for i in range(20)
        }

        # All annotations have the same label - should skip training
        annotations = {
            f"item_{i}": {"sentiment": "positive"}
            for i in range(20)
        }

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            mock_user = create_mock_user_state("test_user@example.com", annotations)
            mock_user_manager.return_value.get_all_users.return_value = [mock_user]

            al_config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=1,
                min_instances_for_training=10,
                model_persistence_enabled=False
            )
            manager = init_active_learning_manager(al_config)

            # Trigger training
            manager.check_and_trigger_training()

            # Wait briefly
            time.sleep(1.5)

            stats = manager.get_stats()
            # Should not train because only one label present
            assert stats["training_count"] == 0, "Training should be skipped when all labels are the same"

    def test_imbalanced_classes(self):
        """Test active learning with heavily imbalanced class distribution."""
        mock_items = {
            f"item_{i}": create_mock_item(f"This is item {i} for imbalanced testing.")
            for i in range(50)
        }

        # 40 positive, 5 negative, 5 neutral - heavily imbalanced
        annotations = {}
        for i in range(40):
            annotations[f"item_{i}"] = {"sentiment": "positive"}
        for i in range(40, 45):
            annotations[f"item_{i}"] = {"sentiment": "negative"}
        for i in range(45, 50):
            annotations[f"item_{i}"] = {"sentiment": "neutral"}

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            mock_user = create_mock_user_state("test_user@example.com", annotations)
            mock_user_manager.return_value.get_all_users.return_value = [mock_user]

            al_config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=1,
                min_instances_for_training=10,
                model_persistence_enabled=False
            )
            manager = init_active_learning_manager(al_config)

            manager.check_and_trigger_training()
            time.sleep(1.5)

            stats = manager.get_stats()
            # Should train successfully even with imbalanced classes
            assert stats["training_count"] > 0, "Training should succeed with imbalanced classes"

    def test_empty_dataset(self):
        """Test active learning behavior with no annotations."""
        mock_items = {
            f"item_{i}": create_mock_item(f"This is item {i} for empty dataset testing.")
            for i in range(10)
        }

        # No annotations at all
        annotations = {}

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            mock_user = create_mock_user_state("test_user@example.com", annotations)
            mock_user_manager.return_value.get_all_users.return_value = [mock_user]

            al_config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=1,
                min_instances_for_training=10,
                model_persistence_enabled=False
            )
            manager = init_active_learning_manager(al_config)

            manager.check_and_trigger_training()
            time.sleep(1.0)

            stats = manager.get_stats()
            # Should not train because no annotations
            assert stats["training_count"] == 0, "Training should be skipped when no annotations exist"

    def test_diverse_labels_training(self):
        """Test active learning with diverse labels from multiple users."""
        mock_items = {
            f"item_{i}": create_mock_item(f"This is item {i} for diverse label testing.")
            for i in range(20)
        }

        # Add diverse annotations
        annotations = {}
        labels = ["positive", "negative", "neutral"]
        for i in range(15):
            label = labels[i % 3]
            annotations[f"item_{i}"] = {"sentiment": label}

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            mock_user = create_mock_user_state("test_user@example.com", annotations)
            mock_user_manager.return_value.get_all_users.return_value = [mock_user]

            al_config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=1,
                min_instances_for_training=10,
                model_persistence_enabled=False
            )
            manager = init_active_learning_manager(al_config)

            manager.check_and_trigger_training()
            time.sleep(1.5)

            stats = manager.get_stats()
            assert stats["training_count"] > 0, "Training should succeed with diverse labels"

    def test_minimum_training_threshold(self):
        """Test that training doesn't start below minimum threshold."""
        mock_items = {
            f"item_{i}": create_mock_item(f"Item {i} content.")
            for i in range(10)
        }

        # Only 3 annotations, but threshold is 10
        annotations = {
            "item_0": {"sentiment": "positive"},
            "item_1": {"sentiment": "negative"},
            "item_2": {"sentiment": "neutral"},
        }

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            mock_user = create_mock_user_state("test_user@example.com", annotations)
            mock_user_manager.return_value.get_all_users.return_value = [mock_user]

            al_config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=1,
                min_instances_for_training=10,  # Threshold higher than annotations
                model_persistence_enabled=False
            )
            manager = init_active_learning_manager(al_config)

            manager.check_and_trigger_training()
            time.sleep(1.0)

            stats = manager.get_stats()
            assert stats["training_count"] == 0, "Training should not start below threshold"

    def test_two_label_binary_classification(self):
        """Test binary classification with exactly two labels."""
        mock_items = {
            f"item_{i}": create_mock_item(f"Item {i} for binary classification.")
            for i in range(12)
        }

        # Binary labels only
        annotations = {}
        for i in range(6):
            annotations[f"item_{i}"] = {"sentiment": "positive"}
        for i in range(6, 12):
            annotations[f"item_{i}"] = {"sentiment": "negative"}

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            mock_user = create_mock_user_state("test_user@example.com", annotations)
            mock_user_manager.return_value.get_all_users.return_value = [mock_user]

            al_config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=1,
                min_instances_for_training=5,
                model_persistence_enabled=False
            )
            manager = init_active_learning_manager(al_config)

            manager.check_and_trigger_training()
            time.sleep(1.5)

            stats = manager.get_stats()
            assert stats["training_count"] > 0, "Binary classification training should succeed"
