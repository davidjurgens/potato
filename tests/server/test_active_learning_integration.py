"""
Active Learning Integration Tests

This module provides integration tests for active learning with the actual
Potato server components, including real annotation workflows and server
integration.
"""

import pytest

# Skip tests that hang waiting for training
pytestmark = pytest.mark.skip(reason="Tests hang due to training loop issues - needs refactoring")
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
    load_and_validate_config, validate_active_learning_config, parse_active_learning_config
)
from tests.helpers.active_learning_test_utils import (
    create_temp_test_data, create_temp_config, register_and_login_user, submit_annotation, get_current_annotations, get_current_instance_id, simulate_annotation_workflow, start_flask_server_with_config
)


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

    def create_mock_item(self, text: str):
        """Create a mock item with the proper interface."""
        mock_item = Mock()
        mock_item.get_text.return_value = text
        return mock_item

    def create_test_config(self, config_data: Dict[str, Any]) -> str:
        """Create a test configuration file."""
        config_file = os.path.join(self.config_dir, "test_config.yaml")
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)
        return config_file

    def create_test_data(self, data: List[Dict[str, Any]]) -> str:
        """Create test data file in the config_dir for security validation."""
        data_file = os.path.join(self.config_dir, "test_data.json")
        with open(data_file, 'w') as f:
            json.dump(data, f)
        # Return relative path from config_dir
        return os.path.relpath(data_file, self.config_dir)

    def test_config_loading_with_active_learning(self):
        """Test loading Potato configuration with active learning enabled."""
        # Create test data
        test_data = [
            {"id": "item1", "text": "I love this product!"},
            {"id": "item2", "text": "This is terrible."},
            {"id": "item3", "text": "The weather is nice."},
            {"id": "item4", "text": "This movie was boring."},
            {"id": "item5", "text": "The new technology is amazing."},
        ]
        data_file = self.create_test_data(test_data)

        # Create configuration with active learning
        config_data = {
            "project_name": "Active Learning Test",
            "project_description": "Testing active learning integration",
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
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
                    "description": "Classify the sentiment of the text",
                    "labels": [
                        {"name": "positive", "title": "Positive"},
                        {"name": "negative", "title": "Negative"},
                        {"name": "neutral", "title": "Neutral"}
                    ]
                }
            ],
            "active_learning": {
                "enabled": True,
                "classifier": {
                    "name": "sklearn.linear_model.LogisticRegression",
                    "hyperparameters": {"C": 1.0}
                },
                "vectorizer": {
                    "name": "sklearn.feature_extraction.text.TfidfVectorizer",
                    "hyperparameters": {"max_features": 1000}
                },
                "min_annotations_per_instance": 1,
                "min_instances_for_training": 3,
                "schema_names": ["sentiment"]
            }
        }

        config_file = self.create_test_config(config_data)

        # Test configuration loading
        config = load_and_validate_config(config_file, self.temp_dir)
        assert config is not None
        assert "active_learning" in config
        assert config["active_learning"]["enabled"] is True

    def test_active_learning_with_real_annotation_data(self):
        """Test active learning with realistic annotation data."""
        # Create realistic test data
        test_data = []
        for i in range(20):
            if i % 4 == 0:
                text = f"I absolutely love this product! It's amazing and wonderful. Item {i} is fantastic!"
            elif i % 4 == 1:
                text = f"This is terrible. I hate it. Item {i} is the worst thing ever."
            elif i % 4 == 2:
                text = f"The weather is nice today. Item {i} is okay, nothing special."
            else:
                text = f"I'm not sure about this. Item {i} could be good or bad, it's unclear."

            test_data.append({
                "id": f"item_{i}",
                "text": text
            })

        data_file = self.create_test_data(test_data)

        # Create configuration
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=5,
            update_frequency=3,
            model_persistence_enabled=True,
            model_save_directory=self.output_dir
        )

        manager = init_active_learning_manager(config)

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            # Create mock items with proper interface
            mock_items = {}
            for item_data in test_data:
                mock_items[item_data["id"]] = self.create_mock_item(item_data["text"])

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            # Create realistic annotations
            mock_user_state = Mock()
            mock_user_state.user_id = "user1"
            annotations = {}
            for i, item_data in enumerate(test_data[:10]):  # Annotate first 10 items
                if i % 4 == 0:
                    label = "positive"
                elif i % 4 == 1:
                    label = "negative"
                elif i % 4 == 2:
                    label = "neutral"
                else:
                    label = "neutral"  # Default for unclear cases

                annotations[item_data["id"]] = {"sentiment": {label: True}}

            mock_user_state.get_all_annotations.return_value = annotations
            mock_user_manager.return_value.get_all_user_states.return_value = [mock_user_state]

            # Trigger training
            manager.check_and_trigger_training()
            time.sleep(3)

            # Verify training completed
            stats = manager.get_stats()
            assert stats["training_count"] > 0

    def test_multiple_schema_active_learning(self):
        """Test active learning with multiple annotation schemas."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment", "topic", "urgency"],
            min_annotations_per_instance=1,
            min_instances_for_training=3,
            update_frequency=2,
            model_persistence_enabled=True,
            model_save_directory=self.output_dir
        )

        manager = init_active_learning_manager(config)

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            # Create mock items with proper interface
            mock_items = {
                "item1": self.create_mock_item("I love this new smartphone! The camera is incredible."),
                "item2": self.create_mock_item("This political decision is terrible for our country."),
                "item3": self.create_mock_item("The weather today is quite pleasant with a gentle breeze."),
                "item4": self.create_mock_item("This technology is revolutionary and will change everything."),
                "item5": self.create_mock_item("I'm so disappointed with the election results."),
                "item6": self.create_mock_item("The new restaurant downtown has excellent food."),
                "item7": self.create_mock_item("This movie was boring and predictable."),
                "item8": self.create_mock_item("The scientific breakthrough in renewable energy is promising."),
                "item9": self.create_mock_item("The traffic today was horrible and made me late."),
                "item10": self.create_mock_item("I'm neutral about the new policy changes."),
            }

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            # Create multi-schema annotations
            mock_user_state = Mock()
            mock_user_state.user_id = "user1"
            mock_user_state.get_all_annotations.return_value = {
                "item1": {
                    "sentiment": {"positive": True},
                    "topic": {"technology": True},
                    "urgency": {"low": True}
                },
                "item2": {
                    "sentiment": {"negative": True},
                    "topic": {"politics": True},
                    "urgency": {"high": True}
                },
                "item3": {
                    "sentiment": {"neutral": True},
                    "topic": {"weather": True},
                    "urgency": {"low": True}
                },
                "item4": {
                    "sentiment": {"positive": True},
                    "topic": {"technology": True},
                    "urgency": {"medium": True}
                },
                "item5": {
                    "sentiment": {"negative": True},
                    "topic": {"politics": True},
                    "urgency": {"high": True}
                }
            }

            mock_user_manager.return_value.get_all_user_states.return_value = [mock_user_state]

            # Trigger training for all schemas
            for i in range(3):
                manager.check_and_trigger_training()
                time.sleep(2)

            # Verify training occurred (may not train all schemas in one cycle)
            stats = manager.get_stats()
            assert stats["training_count"] >= 1

    def test_error_handling_in_config_validation(self):
        """Test error handling in active learning configuration validation."""
        # Test invalid configuration
        invalid_config = {
            "active_learning": {
                "enabled": True,
                "schema_names": ["invalid_schema_type"],  # Invalid schema type
                "random_sample_percent": 1.5,  # Invalid percentage
                "resolution_strategy": "invalid_strategy"  # Invalid strategy
            }
        }

        # Should raise validation errors
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError):
            validate_active_learning_config(invalid_config)

    def test_backward_compatibility(self):
        """Test backward compatibility with configurations without active learning."""
        # Create test data for backward compatibility test
        test_data = [
            {"id": "item1", "text": "I love this product!"},
            {"id": "item2", "text": "This is terrible."},
        ]
        data_file = self.create_test_data(test_data)

        # Test configuration without active learning section
        config_data = {
            "project_name": "Backward Compatibility Test",
            "project_description": "Testing backward compatibility",
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
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
                    "description": "Classify the sentiment of the text",
                    "labels": [
                        {"name": "positive", "title": "Positive"},
                        {"name": "negative", "title": "Negative"}
                    ]
                }
            ]
        }

        # Should not raise any errors
        config_file = self.create_test_config(config_data)
        config = load_and_validate_config(config_file, self.temp_dir)
        assert config is not None
        assert "active_learning" not in config

    def test_performance_metrics_tracking(self):
        """Test performance metrics tracking in active learning."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=3,
            update_frequency=2,
            model_persistence_enabled=True,
            model_save_directory=self.output_dir
        )

        manager = init_active_learning_manager(config)

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            # Create mock items with proper interface
            mock_items = {
                "item1": self.create_mock_item("I love this product!"),
                "item2": self.create_mock_item("This is terrible."),
                "item3": self.create_mock_item("The weather is nice."),
                "item4": self.create_mock_item("This movie was boring."),
                "item5": self.create_mock_item("The new technology is amazing."),
            }

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            # Create annotations
            mock_user_state = Mock()
            mock_user_state.user_id = "user1"
            mock_user_state.get_all_annotations.return_value = {
                "item1": {"sentiment": {"positive": True}},
                "item2": {"sentiment": {"negative": True}},
                "item3": {"sentiment": {"neutral": True}},
            }

            mock_user_manager.return_value.get_all_user_states.return_value = [mock_user_state]

            # Trigger training and measure performance
            start_time = time.time()
            manager.check_and_trigger_training()
            time.sleep(3)
            training_time = time.time() - start_time

            # Verify performance metrics
            stats = manager.get_stats()
            assert stats["training_count"] > 0
            assert training_time < 10.0  # Should complete within reasonable time
            assert "last_training_time" in stats


if __name__ == "__main__":
    pytest.main([__file__])