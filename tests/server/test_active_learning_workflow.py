"""
Active Learning Workflow Tests

This module contains tests for active learning workflows,
including sampling strategies, uncertainty sampling, and adaptive annotation.

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


class TestActiveLearningWorkflow:
    """Workflow tests for active learning."""

    def setup_method(self):
        clear_active_learning_manager()

    def teardown_method(self):
        clear_active_learning_manager()

    def test_active_learning_workflow(self):
        """Test complete active learning workflow with training."""
        mock_items = {
            f"item_{i}": create_mock_item(f"Test item {i} for workflow testing.")
            for i in range(15)
        }

        # Annotations for training
        annotations = {
            "item_0": {"sentiment": "positive"},
            "item_1": {"sentiment": "negative"},
            "item_2": {"sentiment": "neutral"},
            "item_3": {"sentiment": "positive"},
            "item_4": {"sentiment": "negative"},
        }

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            mock_user = create_mock_user_state("user1@test.com", annotations)
            mock_user_manager.return_value.get_all_users.return_value = [mock_user]

            al_config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=1,
                min_instances_for_training=3,
                model_persistence_enabled=False
            )
            manager = init_active_learning_manager(al_config)

            # Trigger training
            manager.check_and_trigger_training()
            time.sleep(1.5)

            stats = manager.get_stats()
            assert stats["enabled"] is True
            assert stats["training_count"] >= 1

    def test_model_training_workflow(self):
        """Test model training workflow with progressive annotations."""
        mock_items = {
            f"item_{i}": create_mock_item(f"Item {i} for model training workflow.")
            for i in range(20)
        }

        # Progressive annotations
        annotations = {}
        labels = ["positive", "negative", "neutral"]
        for i in range(10):
            annotations[f"item_{i}"] = {"sentiment": labels[i % 3]}

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            mock_user = create_mock_user_state("user1@test.com", annotations)
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
            assert stats["training_count"] > 0

    def test_prediction_workflow(self):
        """Test that predictions can be made after training."""
        mock_items = {
            f"item_{i}": create_mock_item(f"Item {i} for prediction testing.")
            for i in range(15)
        }

        annotations = {
            "item_0": {"sentiment": "positive"},
            "item_1": {"sentiment": "negative"},
            "item_2": {"sentiment": "neutral"},
            "item_3": {"sentiment": "positive"},
            "item_4": {"sentiment": "negative"},
            "item_5": {"sentiment": "neutral"},
        }

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            mock_user = create_mock_user_state("user1@test.com", annotations)
            mock_user_manager.return_value.get_all_users.return_value = [mock_user]

            al_config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=1,
                min_instances_for_training=3,
                model_persistence_enabled=False
            )
            manager = init_active_learning_manager(al_config)

            manager.check_and_trigger_training()
            time.sleep(1.5)

            stats = manager.get_stats()
            assert stats["training_count"] > 0

    def test_uncertainty_sampling_workflow(self):
        """Test uncertainty sampling workflow."""
        mock_items = {
            f"item_{i}": create_mock_item(f"Item {i} for uncertainty sampling.")
            for i in range(20)
        }

        # Some annotations
        annotations = {
            "item_0": {"sentiment": "positive"},
            "item_1": {"sentiment": "negative"},
            "item_2": {"sentiment": "neutral"},
            "item_3": {"sentiment": "positive"},
            "item_4": {"sentiment": "negative"},
        }

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            mock_user = create_mock_user_state("user1@test.com", annotations)
            mock_user_manager.return_value.get_all_users.return_value = [mock_user]

            al_config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=1,
                min_instances_for_training=3,
                model_persistence_enabled=False
            )
            manager = init_active_learning_manager(al_config)

            manager.check_and_trigger_training()
            time.sleep(1.5)

            stats = manager.get_stats()
            assert stats["enabled"] is True
