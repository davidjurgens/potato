"""
Active Learning End-to-End Tests

This module provides end-to-end tests that simulate complete annotation
sessions with active learning, including user interactions, model training
cycles, and real-world scenarios.
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
from tests.helpers.active_learning_test_utils import (
    create_temp_test_data, create_temp_config, register_and_login_user, submit_annotation, get_current_annotations, get_current_instance_id, simulate_annotation_workflow, start_flask_server_with_config
)


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

    def create_mock_item(self, text: str):
        """Create a mock item with the proper interface."""
        mock_item = Mock()
        mock_item.get_text.return_value = text
        return mock_item

    def simulate_annotation_session(self, config: ActiveLearningConfig,
                                  initial_annotations: Dict[str, Dict],
                                  additional_annotations: List[Dict],
                                  expected_training_cycles: int = 2):
        """Simulate a complete annotation session with active learning."""

        # Initialize manager
        manager = init_active_learning_manager(config)

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            # Create mock items with proper interface
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
                mock_items[f"item{i}"] = self.create_mock_item(text)

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            # Track annotation state
            current_annotations = initial_annotations.copy()

            # Mock user manager that returns current annotations
            def get_user_states():
                mock_user_state = Mock()
                mock_user_state.user_id = "user1"
                mock_user_state.get_all_annotations.return_value = current_annotations
                return [mock_user_state]

            mock_user_manager.return_value.get_all_user_states = get_user_states

            # Initial training check
            manager.check_and_trigger_training()
            time.sleep(2)

            # Simulate additional annotations and training cycles
            training_cycles = 0
            for i, new_annotations in enumerate(additional_annotations):
                # Add new annotations
                current_annotations.update(new_annotations)

                # Trigger training check
                manager.check_and_trigger_training()
                time.sleep(2)

                # Check if training occurred
                stats = manager.get_stats()
                if stats["training_count"] > training_cycles:
                    training_cycles = stats["training_count"]

            # Verify expected number of training cycles
            assert training_cycles >= expected_training_cycles

            return manager

    def test_complete_annotation_session_sentiment(self):
        """Test complete annotation session with sentiment analysis."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=3,
            update_frequency=2,
            model_persistence_enabled=True,
            model_save_directory=self.model_dir
        )

        # Initial annotations
        initial_annotations = {
            "item0": {"sentiment": {"positive": True}},
            "item1": {"sentiment": {"negative": True}},
            "item2": {"sentiment": {"neutral": True}},
            "item3": {"sentiment": {"neutral": True}},
            "item4": {"sentiment": {"positive": True}},
        }

        # Progressive annotations
        additional_annotations = [
            {
                "item5": {"sentiment": {"negative": True}},
                "item6": {"sentiment": {"neutral": True}},
                "item7": {"sentiment": {"positive": True}},
            },
            {
                "item8": {"sentiment": {"negative": True}},
                "item9": {"sentiment": {"positive": True}},
                "item10": {"sentiment": {"neutral": True}},
            },
            {
                "item11": {"sentiment": {"positive": True}},
                "item12": {"sentiment": {"negative": True}},
                "item13": {"sentiment": {"neutral": True}},
            }
        ]

        manager = self.simulate_annotation_session(
            config, initial_annotations, additional_annotations, expected_training_cycles=2
        )

        # Verify final state
        stats = manager.get_stats()
        assert stats["training_count"] >= 2
        assert stats["enabled"] is True

    def test_multi_schema_annotation_session(self):
        """Test annotation session with multiple schemas."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment", "topic", "urgency"],
            min_annotations_per_instance=1,
            min_instances_for_training=2,
            update_frequency=1,
            model_persistence_enabled=True,
            model_save_directory=self.model_dir
        )

        # Initial multi-schema annotations
        initial_annotations = {
            "item0": {
                "sentiment": {"positive": True},
                "topic": {"technology": True},
                "urgency": {"low": True}
            },
            "item1": {
                "sentiment": {"negative": True},
                "topic": {"politics": True},
                "urgency": {"high": True}
            },
            "item2": {
                "sentiment": {"neutral": True},
                "topic": {"weather": True},
                "urgency": {"low": True}
            }
        }

        # Progressive multi-schema annotations
        additional_annotations = [
            {
                "item3": {
                    "sentiment": {"positive": True},
                    "topic": {"technology": True},
                    "urgency": {"medium": True}
                },
                "item4": {
                    "sentiment": {"negative": True},
                    "topic": {"politics": True},
                    "urgency": {"high": True}
                }
            },
            {
                "item5": {
                    "sentiment": {"neutral": True},
                    "topic": {"entertainment": True},
                    "urgency": {"low": True}
                },
                "item6": {
                    "sentiment": {"positive": True},
                    "topic": {"technology": True},
                    "urgency": {"medium": True}
                }
            }
        ]

        manager = self.simulate_annotation_session(
            config, initial_annotations, additional_annotations, expected_training_cycles=3
        )

        # Verify all schemas were trained
        stats = manager.get_stats()
        assert stats["training_count"] >= 3

    def test_active_learning_with_conflicting_annotations(self):
        """Test active learning with conflicting annotations from multiple users."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=2,
            min_instances_for_training=3,
            update_frequency=2,
            resolution_strategy=ResolutionStrategy.MAJORITY_VOTE
        )

        manager = init_active_learning_manager(config)

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            # Create mock items with proper interface
            mock_items = {
                "item1": self.create_mock_item("This product is okay, I'm not sure."),
                "item2": self.create_mock_item("I'm conflicted about this."),
                "item3": self.create_mock_item("This could be good or bad."),
            }

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            # Create conflicting annotations from multiple users
            mock_user_state1 = Mock()
            mock_user_state1.user_id = "user1"
            mock_user_state1.get_all_annotations.return_value = {
                "item1": {"sentiment": {"positive": True}},
                "item2": {"sentiment": {"neutral": True}},
                "item3": {"sentiment": {"positive": True}},
            }

            mock_user_state2 = Mock()
            mock_user_state2.user_id = "user2"
            mock_user_state2.get_all_annotations.return_value = {
                "item1": {"sentiment": {"negative": True}},
                "item2": {"sentiment": {"neutral": True}},
                "item3": {"sentiment": {"negative": True}},
            }

            mock_user_state3 = Mock()
            mock_user_state3.user_id = "user3"
            mock_user_state3.get_all_annotations.return_value = {
                "item1": {"sentiment": {"positive": True}},
                "item2": {"sentiment": {"positive": True}},
                "item3": {"sentiment": {"neutral": True}},
            }

            mock_user_manager.return_value.get_all_user_states.return_value = [
                mock_user_state1, mock_user_state2, mock_user_state3
            ]

            # Trigger training
            manager.check_and_trigger_training()
            time.sleep(3)

            # Verify training completed despite conflicts
            stats = manager.get_stats()
            assert stats["training_count"] > 0

    def test_active_learning_performance_monitoring(self):
        """Test performance monitoring during active learning sessions."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=3,
            update_frequency=2,
            model_persistence_enabled=True,
            model_save_directory=self.model_dir
        )

        manager = init_active_learning_manager(config)

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            # Create mock items with proper interface
            mock_items = {}
            for i in range(20):
                mock_items[f"item{i}"] = self.create_mock_item(f"This is test item {i} with some content.")

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            # Create progressive annotations
            mock_user_state = Mock()
            mock_user_state.user_id = "user1"
            mock_user_state.get_all_annotations.return_value = {
                "item0": {"sentiment": {"positive": True}},
                "item1": {"sentiment": {"negative": True}},
                "item2": {"sentiment": {"neutral": True}},
            }

            mock_user_manager.return_value.get_all_user_states.return_value = [mock_user_state]

            # Monitor performance over multiple training cycles
            performance_metrics = []
            for i in range(3):
                start_time = time.time()
                manager.check_and_trigger_training()
                time.sleep(2)
                training_time = time.time() - start_time

                stats = manager.get_stats()
                performance_metrics.append({
                    "cycle": i + 1,
                    "training_time": training_time,
                    "training_count": stats["training_count"],
                    "accuracy": stats.get("last_accuracy", 0.0)
                })

            # Verify performance metrics are reasonable
            assert len(performance_metrics) == 3
            for metric in performance_metrics:
                assert metric["training_time"] < 10.0  # Should complete within reasonable time
                assert metric["training_count"] > 0

    def test_active_learning_with_insufficient_data(self):
        """Test active learning behavior with insufficient training data."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=10,  # High threshold
            update_frequency=2
        )

        manager = init_active_learning_manager(config)

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            # Create mock items with proper interface
            mock_items = {
                "item1": self.create_mock_item("I love this product!"),
                "item2": self.create_mock_item("This is terrible."),
                "item3": self.create_mock_item("The weather is nice."),
            }

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            # Create insufficient annotations
            mock_user_state = Mock()
            mock_user_state.user_id = "user1"
            mock_user_state.get_all_annotations.return_value = {
                "item1": {"sentiment": {"positive": True}},
                "item2": {"sentiment": {"negative": True}},
                "item3": {"sentiment": {"neutral": True}},
            }

            mock_user_manager.return_value.get_all_user_states.return_value = [mock_user_state]

            # Trigger training (should not train due to insufficient data)
            manager.check_and_trigger_training()
            time.sleep(2)

            # Verify no training occurred
            stats = manager.get_stats()
            assert stats["training_count"] == 0

    def test_active_learning_error_recovery(self):
        """Test error recovery in active learning workflows."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=3,
            update_frequency=2
        )

        manager = init_active_learning_manager(config)

        # Test with invalid classifier configuration
        config.classifier_name = "invalid.classifier.Class"
        manager.config = config

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            # Create mock items with proper interface
            mock_items = {
                "item1": self.create_mock_item("I love this product!"),
                "item2": self.create_mock_item("This is terrible."),
                "item3": self.create_mock_item("The weather is nice."),
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

            # Trigger training (should handle error gracefully)
            manager.check_and_trigger_training()
            time.sleep(2)

            # Verify manager is still functional despite errors
            stats = manager.get_stats()
            assert "error_count" in stats

    def test_active_learning_with_large_dataset(self):
        """Test active learning performance with large datasets."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=5,
            update_frequency=5,
            max_instances_to_reorder=20
        )

        manager = init_active_learning_manager(config)

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            # Create large dataset
            mock_items = {}
            for i in range(100):
                mock_items[f"item{i}"] = self.create_mock_item(f"This is test item {i} with substantial content for testing purposes.")

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            # Create annotations for subset
            mock_user_state = Mock()
            mock_user_state.user_id = "user1"
            annotations = {}
            for i in range(15):
                label = "positive" if i % 3 == 0 else "negative" if i % 3 == 1 else "neutral"
                annotations[f"item{i}"] = {"sentiment": {label: True}}

            mock_user_state.get_all_annotations.return_value = annotations
            mock_user_manager.return_value.get_all_user_states.return_value = [mock_user_state]

            # Measure performance with large dataset
            start_time = time.time()
            manager.check_and_trigger_training()
            time.sleep(3)
            training_time = time.time() - start_time

            # Verify performance is reasonable
            stats = manager.get_stats()
            assert stats["training_count"] > 0
            assert training_time < 15.0  # Should complete within reasonable time even with large dataset


if __name__ == "__main__":
    pytest.main([__file__])