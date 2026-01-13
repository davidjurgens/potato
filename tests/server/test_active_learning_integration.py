"""
Active Learning Integration Tests

This module provides integration tests for active learning with the actual
Potato server components, including real annotation workflows and server
integration.

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
from potato.server_utils.config_module import (
    load_and_validate_config, validate_active_learning_config, parse_active_learning_config,
    ConfigValidationError
)
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


class TestActiveLearningServerIntegration:
    """Test active learning integration with Potato server components."""

    def setup_method(self):
        """Set up test environment."""
        clear_active_learning_manager()

        # Create temporary directories
        self.temp_dir = tempfile.mkdtemp()
        self.config_dir = os.path.join(self.temp_dir, "configs")
        self.data_dir = os.path.join(self.temp_dir, "data")
        self.output_dir = os.path.join(self.temp_dir, "output")

        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    def teardown_method(self):
        """Clean up test environment."""
        clear_active_learning_manager()

    def create_test_config(self, config_data: Dict[str, Any]) -> str:
        """Create a test configuration file."""
        config_file = os.path.join(self.config_dir, "test_config.yaml")
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)
        return config_file

    def create_test_data(self, data: List[Dict[str, Any]]) -> str:
        """Create test data file in the temp_dir for proper path resolution."""
        data_file = os.path.join(self.temp_dir, "test_data.json")
        with open(data_file, 'w') as f:
            json.dump(data, f)
        return "test_data.json"  # Return relative path from task_dir

    def test_config_loading_with_active_learning(self):
        """Test loading Potato configuration with active learning enabled."""
        test_data = [
            {"id": "item1", "text": "I love this product!"},
            {"id": "item2", "text": "This is terrible."},
            {"id": "item3", "text": "The weather is nice."},
        ]
        data_file = self.create_test_data(test_data)

        config_data = {
            "project_name": "Active Learning Test",
            "project_description": "Testing active learning integration",
            "item_properties": {"id_key": "id", "text_key": "text"},
            "data_files": [data_file],
            "task_dir": self.temp_dir,
            "output_annotation_dir": self.output_dir,
            "annotation_task_name": "sentiment_analysis",
            "alert_time_each_instance": 30,
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "title": "Sentiment Analysis",
                    "description": "Classify the sentiment",
                    "labels": [
                        {"name": "positive", "title": "Positive"},
                        {"name": "negative", "title": "Negative"},
                        {"name": "neutral", "title": "Neutral"}
                    ]
                }
            ],
            "active_learning": {
                "enabled": True,
                "classifier": {"name": "sklearn.linear_model.LogisticRegression"},
                "vectorizer": {"name": "sklearn.feature_extraction.text.TfidfVectorizer"},
                "min_annotations_per_instance": 1,
                "min_instances_for_training": 3,
                "schema_names": ["sentiment"]
            }
        }

        config_file = self.create_test_config(config_data)
        config = load_and_validate_config(config_file, self.temp_dir)

        assert config is not None
        assert "active_learning" in config
        assert config["active_learning"]["enabled"] is True

    def test_active_learning_with_real_annotation_data(self):
        """Test active learning with realistic annotation data."""
        # Create test data
        test_data = [
            {"id": "item_0", "text": "I absolutely love this product! Amazing!"},
            {"id": "item_1", "text": "This is terrible. I hate it."},
            {"id": "item_2", "text": "The weather is nice today."},
            {"id": "item_3", "text": "Not sure about this one."},
            {"id": "item_4", "text": "Fantastic experience! Highly recommend!"},
            {"id": "item_5", "text": "Worst purchase ever. Total waste."},
        ]

        # Create mock items
        mock_items = {item["id"]: create_mock_item(item["text"]) for item in test_data}

        # Create annotations with proper Label format
        annotations = {
            "item_0": {"sentiment": "positive"},
            "item_1": {"sentiment": "negative"},
            "item_2": {"sentiment": "neutral"},
            "item_3": {"sentiment": "neutral"},
            "item_4": {"sentiment": "positive"},
            "item_5": {"sentiment": "negative"},
        }
        mock_user = create_mock_user_state("user1", annotations)

        # CRITICAL: Set up mocks BEFORE initializing manager
        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            # Configure item manager mock
            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            # Configure user manager mock - note: get_all_users() not get_all_user_states()
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
            time.sleep(1.0)  # Wait for background thread

            # Verify training completed
            stats = manager.get_stats()
            assert stats["training_count"] >= 1, f"Expected training to occur, got stats: {stats}"

    def test_multiple_schema_active_learning(self):
        """Test active learning with multiple annotation schemas."""
        # Create mock items
        mock_items = {
            "item1": create_mock_item("I love this new smartphone! The camera is incredible."),
            "item2": create_mock_item("This political decision is terrible for our country."),
            "item3": create_mock_item("The weather today is quite pleasant."),
            "item4": create_mock_item("Revolutionary technology that will change everything."),
            "item5": create_mock_item("Disappointed with the election results."),
        }

        # Multi-schema annotations
        annotations = {
            "item1": {"sentiment": "positive", "topic": "technology"},
            "item2": {"sentiment": "negative", "topic": "politics"},
            "item3": {"sentiment": "neutral", "topic": "weather"},
            "item4": {"sentiment": "positive", "topic": "technology"},
            "item5": {"sentiment": "negative", "topic": "politics"},
        }
        mock_user = create_mock_user_state("user1", annotations)

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()
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

    def test_error_handling_in_config_validation(self):
        """Test error handling in active learning configuration validation."""
        invalid_config = {
            "active_learning": {
                "enabled": True,
                "schema_names": ["test"],
                "random_sample_percent": 1.5,  # Invalid: must be 0-1
            }
        }

        with pytest.raises(ConfigValidationError):
            validate_active_learning_config(invalid_config)

    def test_backward_compatibility(self):
        """Test backward compatibility with configurations without active learning."""
        test_data = [
            {"id": "item1", "text": "I love this product!"},
            {"id": "item2", "text": "This is terrible."},
        ]
        data_file = self.create_test_data(test_data)

        config_data = {
            "project_name": "Backward Compatibility Test",
            "project_description": "Testing backward compatibility",
            "item_properties": {"id_key": "id", "text_key": "text"},
            "data_files": [data_file],
            "task_dir": self.temp_dir,
            "output_annotation_dir": self.output_dir,
            "annotation_task_name": "sentiment_analysis",
            "alert_time_each_instance": 30,
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "title": "Sentiment Analysis",
                    "description": "Classify the sentiment",
                    "labels": [
                        {"name": "positive", "title": "Positive"},
                        {"name": "negative", "title": "Negative"}
                    ]
                }
            ]
        }

        config_file = self.create_test_config(config_data)
        config = load_and_validate_config(config_file, self.temp_dir)

        assert config is not None
        assert "active_learning" not in config

    def test_performance_metrics_tracking(self):
        """Test performance metrics tracking in active learning."""
        mock_items = {
            "item1": create_mock_item("I love this product!"),
            "item2": create_mock_item("This is terrible."),
            "item3": create_mock_item("The weather is nice."),
            "item4": create_mock_item("This movie was boring."),
            "item5": create_mock_item("Amazing technology!"),
        }

        annotations = {
            "item1": {"sentiment": "positive"},
            "item2": {"sentiment": "negative"},
            "item3": {"sentiment": "neutral"},
            "item4": {"sentiment": "negative"},
            "item5": {"sentiment": "positive"},
        }
        mock_user = create_mock_user_state("user1", annotations)

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()
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

            start_time = time.time()
            manager.check_and_trigger_training()
            time.sleep(1.0)
            training_time = time.time() - start_time

            stats = manager.get_stats()
            assert stats["training_count"] >= 1
            assert training_time < 10.0  # Should complete quickly
            assert "last_training_time" in stats


if __name__ == "__main__":
    pytest.main([__file__])
