"""
Active Learning End-to-End Tests

This module provides end-to-end tests that simulate complete annotation
sessions with active learning, including user interactions, model training
cycles, and real-world scenarios.

TEMPLATE: This file demonstrates the correct pattern for mocking active learning tests:
1. Set up mocks BEFORE initializing the manager (background thread needs them)
2. Use proper Label objects in annotation structure
3. Mock get_all_users() to return user states with proper annotation format
"""

import pytest
import tempfile
import os
import json
import time
import yaml
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any, List

from potato.active_learning_manager import (
    ActiveLearningManager, ActiveLearningConfig, ResolutionStrategy,
    init_active_learning_manager, get_active_learning_manager, clear_active_learning_manager
)
from potato.server_utils.config_module import parse_active_learning_config
from potato.item_state_management import Label


def create_mock_user_state(user_id: str, annotations: Dict[str, Dict[str, str]]):
    """
    Create a mock user state with properly formatted annotations.

    Args:
        user_id: The user identifier
        annotations: Dict of {instance_id: {schema_name: label_name}}
                    e.g., {"item1": {"sentiment": "positive"}}

    Returns:
        Mock user state with proper Label objects
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


class TestActiveLearningEndToEnd:
    """End-to-end tests for active learning workflows."""

    def setup_method(self):
        """Set up test environment."""
        clear_active_learning_manager()

        # Create temporary directories
        self.temp_dir = tempfile.mkdtemp()
        self.model_dir = os.path.join(self.temp_dir, "models")
        os.makedirs(self.model_dir, exist_ok=True)

    def teardown_method(self):
        """Clean up test environment."""
        clear_active_learning_manager()

    def test_complete_annotation_session_sentiment(self):
        """Test complete annotation session with sentiment analysis."""
        # Create mock items
        mock_items = {}
        for i in range(50):
            if i % 5 == 0:
                text = f"I absolutely love this product! It's amazing and wonderful. Item {i} is fantastic!"
            elif i % 5 == 1:
                text = f"This is terrible. I hate it. Item {i} is the worst thing ever."
            elif i % 5 == 2:
                text = f"The weather is nice today. Item {i} is okay, nothing special."
            elif i % 5 == 3:
                text = f"I'm not sure about this. Item {i} could be good or bad, it's unclear."
            else:
                text = f"This is a mixed review. Item {i} has both good and bad aspects."
            mock_items[f"item{i}"] = create_mock_item(text)

        # Initial annotations
        initial_annotations = {
            "item0": {"sentiment": "positive"},
            "item1": {"sentiment": "negative"},
            "item2": {"sentiment": "neutral"},
            "item3": {"sentiment": "neutral"},
            "item4": {"sentiment": "positive"},
        }

        # CRITICAL: Set up mocks BEFORE initializing manager
        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            # Configure item manager mock
            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            # Configure user manager mock with proper Label format
            mock_user = create_mock_user_state("user1", initial_annotations)
            mock_user_manager.return_value.get_all_users.return_value = [mock_user]

            # NOW initialize manager (after mocks are set up)
            config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=1,
                min_instances_for_training=3,
                update_frequency=2,
                model_persistence_enabled=False
            )
            manager = init_active_learning_manager(config)

            # Trigger training
            manager.check_and_trigger_training()
            time.sleep(1.5)

            # Verify training completed
            stats = manager.get_stats()
            assert stats["training_count"] >= 1, f"Expected training to occur, got stats: {stats}"
            assert stats["enabled"] is True

    def test_multi_schema_annotation_session(self):
        """Test annotation session with multiple schemas."""
        # Create mock items
        mock_items = {
            "item0": create_mock_item("I love this new smartphone! The camera is incredible."),
            "item1": create_mock_item("This political decision is terrible for our country."),
            "item2": create_mock_item("The weather today is quite pleasant."),
            "item3": create_mock_item("Revolutionary technology that will change everything."),
            "item4": create_mock_item("Disappointed with the election results."),
        }

        # Multi-schema annotations
        annotations = {
            "item0": {"sentiment": "positive", "topic": "technology"},
            "item1": {"sentiment": "negative", "topic": "politics"},
            "item2": {"sentiment": "neutral", "topic": "weather"},
            "item3": {"sentiment": "positive", "topic": "technology"},
            "item4": {"sentiment": "negative", "topic": "politics"},
        }

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            mock_user = create_mock_user_state("user1", annotations)
            mock_user_manager.return_value.get_all_users.return_value = [mock_user]

            config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment", "topic"],
                min_annotations_per_instance=1,
                min_instances_for_training=3,
                update_frequency=2,
                model_persistence_enabled=False
            )
            manager = init_active_learning_manager(config)

            # Trigger training multiple times for schema cycling
            for _ in range(3):
                manager.check_and_trigger_training()
                time.sleep(0.5)

            stats = manager.get_stats()
            assert stats["training_count"] >= 1

    def test_active_learning_with_conflicting_annotations(self):
        """Test active learning with conflicting annotations from multiple users."""
        # Create mock items
        mock_items = {
            "item1": create_mock_item("This product is okay, I'm not sure."),
            "item2": create_mock_item("I'm conflicted about this."),
            "item3": create_mock_item("This could be good or bad."),
        }

        # Create conflicting annotations from multiple users
        user1_annotations = {
            "item1": {"sentiment": "positive"},
            "item2": {"sentiment": "neutral"},
            "item3": {"sentiment": "positive"},
        }
        user2_annotations = {
            "item1": {"sentiment": "negative"},
            "item2": {"sentiment": "neutral"},
            "item3": {"sentiment": "negative"},
        }
        user3_annotations = {
            "item1": {"sentiment": "positive"},
            "item2": {"sentiment": "positive"},
            "item3": {"sentiment": "neutral"},
        }

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            mock_user1 = create_mock_user_state("user1", user1_annotations)
            mock_user2 = create_mock_user_state("user2", user2_annotations)
            mock_user3 = create_mock_user_state("user3", user3_annotations)
            mock_user_manager.return_value.get_all_users.return_value = [mock_user1, mock_user2, mock_user3]

            config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=2,
                min_instances_for_training=3,
                update_frequency=2,
                resolution_strategy=ResolutionStrategy.MAJORITY_VOTE,
                model_persistence_enabled=False
            )
            manager = init_active_learning_manager(config)

            # Trigger training
            manager.check_and_trigger_training()
            time.sleep(1.5)

            # Verify training completed despite conflicts
            stats = manager.get_stats()
            assert stats["training_count"] > 0

    def test_active_learning_performance_monitoring(self):
        """Test performance monitoring during active learning sessions."""
        mock_items = {}
        for i in range(20):
            mock_items[f"item{i}"] = create_mock_item(f"This is test item {i} with some content.")

        annotations = {
            "item0": {"sentiment": "positive"},
            "item1": {"sentiment": "negative"},
            "item2": {"sentiment": "neutral"},
            "item3": {"sentiment": "positive"},
            "item4": {"sentiment": "negative"},
        }

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            mock_user = create_mock_user_state("user1", annotations)
            mock_user_manager.return_value.get_all_users.return_value = [mock_user]

            config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=1,
                min_instances_for_training=3,
                update_frequency=2,
                model_persistence_enabled=False
            )
            manager = init_active_learning_manager(config)

            # Monitor performance over multiple training cycles
            start_time = time.time()
            manager.check_and_trigger_training()
            time.sleep(1.5)
            training_time = time.time() - start_time

            stats = manager.get_stats()
            assert stats["training_count"] >= 1
            assert training_time < 10.0  # Should complete quickly
            assert "last_training_time" in stats

    def test_active_learning_with_insufficient_data(self):
        """Test active learning behavior with insufficient training data."""
        mock_items = {
            "item1": create_mock_item("I love this product!"),
            "item2": create_mock_item("This is terrible."),
            "item3": create_mock_item("The weather is nice."),
        }

        # Only 3 annotations, but we require 10
        annotations = {
            "item1": {"sentiment": "positive"},
            "item2": {"sentiment": "negative"},
            "item3": {"sentiment": "neutral"},
        }

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            mock_user = create_mock_user_state("user1", annotations)
            mock_user_manager.return_value.get_all_users.return_value = [mock_user]

            config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=1,
                min_instances_for_training=10,  # High threshold
                update_frequency=2,
                model_persistence_enabled=False
            )
            manager = init_active_learning_manager(config)

            # Trigger training (should not train due to insufficient data)
            manager.check_and_trigger_training()
            time.sleep(1.0)

            # Verify no training occurred
            stats = manager.get_stats()
            assert stats["training_count"] == 0

    def test_active_learning_with_large_dataset(self):
        """Test active learning performance with large datasets."""
        # Create large dataset
        mock_items = {}
        for i in range(100):
            mock_items[f"item{i}"] = create_mock_item(f"This is test item {i} with substantial content for testing purposes.")

        # Create annotations for subset
        annotations = {}
        for i in range(15):
            label = "positive" if i % 3 == 0 else "negative" if i % 3 == 1 else "neutral"
            annotations[f"item{i}"] = {"sentiment": label}

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            mock_user = create_mock_user_state("user1", annotations)
            mock_user_manager.return_value.get_all_users.return_value = [mock_user]

            config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=1,
                min_instances_for_training=5,
                update_frequency=5,
                max_instances_to_reorder=20,
                model_persistence_enabled=False
            )
            manager = init_active_learning_manager(config)

            # Measure performance with large dataset
            start_time = time.time()
            manager.check_and_trigger_training()
            time.sleep(1.5)
            training_time = time.time() - start_time

            # Verify performance is reasonable
            stats = manager.get_stats()
            assert stats["training_count"] > 0
            assert training_time < 15.0  # Should complete within reasonable time


if __name__ == "__main__":
    pytest.main([__file__])
