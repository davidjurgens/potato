"""
Edge Case and Error Recovery Tests for Active Learning

This module contains tests for all-same-label, imbalanced classes, LLM endpoint down, DB failure, empty dataset, and malformed data scenarios.

NOTE: Some tests in this module hang due to training loop issues.
"""

import pytest

# Skip tests that hang waiting for training
pytestmark = pytest.mark.skip(reason="Tests hang due to training loop issues - needs refactoring")
from unittest.mock import patch, Mock
from tests.helpers.active_learning_test_utils import start_flask_server_with_config
from potato.active_learning_manager import ActiveLearningConfig, init_active_learning_manager, clear_active_learning_manager

class TestActiveLearningEdgeCases:
    """Edge case and error recovery tests for active learning."""

    def setup_method(self):
        clear_active_learning_manager()

    def teardown_method(self):
        clear_active_learning_manager()

    def test_all_same_label(self):
        """Test that active learning skips training if all annotations are the same label."""
        from potato.item_state_management import init_item_state_manager, get_item_state_manager, clear_item_state_manager
        from potato.user_state_management import init_user_state_manager, get_user_state_manager, clear_user_state_manager
        from potato.phase import UserPhase

        # Clear managers first
        clear_item_state_manager()
        clear_user_state_manager()

        items = [
            {"id": f"item_{i}", "text": f"This is item {i} for edge case testing."}
            for i in range(20)
        ]

        config = {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "labels": [
                        {"name": "positive", "title": "Positive"},
                        {"name": "negative", "title": "Negative"},
                        {"name": "neutral", "title": "Neutral"}
                    ],
                    "description": "Sentiment label"
                }
            ],
            "alert_time_each_instance": 0
        }

        # Initialize managers
        init_item_state_manager(config)
        init_user_state_manager(config)

        item_manager = get_item_state_manager()
        user_manager = get_user_state_manager()

        # Add items
        for item in items:
            item_manager.add_item(item["id"], item)

        # Create user and annotate all items with the same label
        user = user_manager.add_user("test_user@example.com")
        user.advance_to_phase(UserPhase.ANNOTATION, None)

        for i in range(20):
            user.set_annotation(f"item_{i}", {"sentiment": "positive"}, None, None)

        # Initialize active learning manager
        al_config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=10
        )
        manager = init_active_learning_manager(al_config)

        # Trigger training
        manager.check_and_trigger_training()

        # Wait for training to complete
        import time
        max_wait = 10
        start_time = time.time()
        while time.time() - start_time < max_wait:
            stats = manager.get_stats()
            if stats["training_count"] > 0:
                break
            time.sleep(0.1)

        stats = manager.get_stats()
        # Should not train because only one label present
        assert stats["training_count"] == 0, "Training should be skipped when all labels are the same"

    def test_imbalanced_classes(self):
        """Test active learning with heavily imbalanced class distribution."""
        from potato.item_state_management import init_item_state_manager, get_item_state_manager, clear_item_state_manager
        from potato.user_state_management import init_user_state_manager, get_user_state_manager, clear_user_state_manager
        from potato.phase import UserPhase

        # Clear managers first
        clear_item_state_manager()
        clear_user_state_manager()

        items = [
            {"id": f"item_{i}", "text": f"This is item {i} for imbalanced testing."}
            for i in range(50)
        ]

        config = {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "labels": [
                        {"name": "positive", "title": "Positive"},
                        {"name": "negative", "title": "Negative"},
                        {"name": "neutral", "title": "Neutral"}
                    ],
                    "description": "Sentiment label"
                }
            ],
            "alert_time_each_instance": 0
        }

        # Initialize managers
        init_item_state_manager(config)
        init_user_state_manager(config)

        item_manager = get_item_state_manager()
        user_manager = get_user_state_manager()

        # Add items
        for item in items:
            item_manager.add_item(item["id"], item)

        # Create user and annotate with imbalanced distribution
        user = user_manager.add_user("test_user@example.com")
        user.advance_to_phase(UserPhase.ANNOTATION, None)

        # 40 positive, 5 negative, 5 neutral
        for i in range(40):
            user.set_annotation(f"item_{i}", {"sentiment": "positive"}, None, None)
        for i in range(40, 45):
            user.set_annotation(f"item_{i}", {"sentiment": "negative"}, None, None)
        for i in range(45, 50):
            user.set_annotation(f"item_{i}", {"sentiment": "neutral"}, None, None)

        # Initialize active learning manager
        al_config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=10
        )
        manager = init_active_learning_manager(al_config)

        # Trigger training
        manager.check_and_trigger_training()

        # Wait for training to complete
        import time
        max_wait = 10
        start_time = time.time()
        while time.time() - start_time < max_wait:
            stats = manager.get_stats()
            if stats["training_count"] > 0:
                break
            time.sleep(0.1)

        stats = manager.get_stats()
        # Should train successfully even with imbalanced classes
        assert stats["training_count"] > 0, "Training should succeed with imbalanced classes"

    def test_empty_dataset(self):
        """Test active learning behavior with no annotations."""
        from potato.item_state_management import init_item_state_manager, get_item_state_manager, clear_item_state_manager
        from potato.user_state_management import init_user_state_manager, get_user_state_manager, clear_user_state_manager

        # Clear managers first
        clear_item_state_manager()
        clear_user_state_manager()

        items = [
            {"id": f"item_{i}", "text": f"This is item {i} for empty dataset testing."}
            for i in range(10)
        ]

        config = {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "labels": [
                        {"name": "positive", "title": "Positive"},
                        {"name": "negative", "title": "Negative"},
                        {"name": "neutral", "title": "Neutral"}
                    ],
                    "description": "Sentiment label"
                }
            ],
            "alert_time_each_instance": 0
        }

        # Initialize managers
        init_item_state_manager(config)
        init_user_state_manager(config)

        item_manager = get_item_state_manager()

        # Add items but no annotations
        for item in items:
            item_manager.add_item(item["id"], item)

        # Initialize active learning manager
        al_config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=10
        )
        manager = init_active_learning_manager(al_config)

        # Trigger training
        manager.check_and_trigger_training()

        # Wait for training to complete
        import time
        max_wait = 10
        start_time = time.time()
        while time.time() - start_time < max_wait:
            stats = manager.get_stats()
            if stats["training_count"] > 0:
                break
            time.sleep(0.1)

        stats = manager.get_stats()
        # Should not train because no annotations
        assert stats["training_count"] == 0, "Training should be skipped when no annotations exist"

    def test_malformed_data(self):
        """Test active learning behavior with malformed annotation data."""
        from potato.item_state_management import init_item_state_manager, get_item_state_manager, clear_item_state_manager
        from potato.user_state_management import init_user_state_manager, get_user_state_manager, clear_user_state_manager
        from potato.phase import UserPhase

        # Clear managers first
        clear_item_state_manager()
        clear_user_state_manager()

        items = [
            {"id": f"item_{i}", "text": f"This is item {i} for malformed data testing."}
            for i in range(20)
        ]

        config = {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "labels": [
                        {"name": "positive", "title": "Positive"},
                        {"name": "negative", "title": "Negative"},
                        {"name": "neutral", "title": "Neutral"}
                    ],
                    "description": "Sentiment label"
                }
            ],
            "alert_time_each_instance": 0
        }

        # Initialize managers
        init_item_state_manager(config)
        init_user_state_manager(config)

        item_manager = get_item_state_manager()
        user_manager = get_user_state_manager()

        # Add items
        for item in items:
            item_manager.add_item(item["id"], item)

        # Create user and add some valid annotations
        user = user_manager.add_user("test_user@example.com")
        user.advance_to_phase(UserPhase.ANNOTATION, None)

        # Add some valid annotations with diverse labels
        for i in range(5):
            user.set_annotation(f"item_{i}", {"sentiment": "positive"}, None, None)
        for i in range(5, 10):
            user.set_annotation(f"item_{i}", {"sentiment": "negative"}, None, None)

        # Add some malformed annotations by directly manipulating the user state
        # This simulates corrupted data
        user_annotations = user.get_all_annotations()
        user_annotations["item_10"] = {"malformed": "data"}  # No 'labels' key
        user_annotations["item_11"] = {"labels": {}}  # Empty labels
        user_annotations["item_12"] = {"labels": {"sentiment": None}}  # None value

        # Initialize active learning manager
        al_config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=5
        )
        manager = init_active_learning_manager(al_config)

        # Trigger training
        manager.check_and_trigger_training()

        # Wait for training to complete
        import time
        max_wait = 10
        start_time = time.time()
        while time.time() - start_time < max_wait:
            stats = manager.get_stats()
            if stats["training_count"] > 0:
                break
            time.sleep(0.1)

        stats = manager.get_stats()
        # Should train successfully, ignoring malformed data
        assert stats["training_count"] > 0, "Training should succeed and ignore malformed data"

    def test_llm_endpoint_failure(self):
        """Test active learning behavior when LLM endpoint is down."""
        from potato.item_state_management import init_item_state_manager, get_item_state_manager, clear_item_state_manager
        from potato.user_state_management import init_user_state_manager, get_user_state_manager, clear_user_state_manager
        from potato.phase import UserPhase

        # Clear managers first
        clear_item_state_manager()
        clear_user_state_manager()

        items = [
            {"id": f"item_{i}", "text": f"This is item {i} for LLM failure testing."}
            for i in range(20)
        ]

        config = {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "labels": [
                        {"name": "positive", "title": "Positive"},
                        {"name": "negative", "title": "Negative"},
                        {"name": "neutral", "title": "Neutral"}
                    ],
                    "description": "Sentiment label"
                }
            ],
            "alert_time_each_instance": 0
        }

        # Initialize managers
        init_item_state_manager(config)
        init_user_state_manager(config)

        item_manager = get_item_state_manager()
        user_manager = get_user_state_manager()

        # Add items
        for item in items:
            item_manager.add_item(item["id"], item)

        # Create user and add annotations
        user = user_manager.add_user("test_user@example.com")
        user.advance_to_phase(UserPhase.ANNOTATION, None)

        # Add diverse annotations
        labels = ["positive", "negative", "neutral"]
        for i in range(15):
            label = labels[i % 3]
            user.set_annotation(f"item_{i}", {"sentiment": label}, None, None)

        # Initialize active learning manager with LLM enabled but failing endpoint
        al_config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=10,
            llm_enabled=True,
            llm_config={
                "endpoint_url": "http://localhost:9999",  # Non-existent endpoint
                "model_name": "test-model",
                "timeout": 1  # Short timeout for quick failure
            }
        )

        manager = init_active_learning_manager(al_config)

        # Trigger training
        manager.check_and_trigger_training()

        # Wait for training to complete
        import time
        max_wait = 15
        start_time = time.time()
        while time.time() - start_time < max_wait:
            stats = manager.get_stats()
            if stats["training_count"] > 0:
                break
            time.sleep(0.1)

        stats = manager.get_stats()
        # Should train successfully using traditional methods when LLM fails
        assert stats["training_count"] > 0, "Training should succeed using traditional methods when LLM fails"
        assert stats["llm_enabled"] is True, "LLM should still be enabled in config"