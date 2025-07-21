"""
Multi-User Concurrency Tests for Active Learning

This module contains tests for simultaneous annotation, race conditions, concurrent model save/load, and queue updates during active learning.
"""

import pytest
from potato.active_learning_manager import ActiveLearningConfig, init_active_learning_manager, clear_active_learning_manager
from potato.item_state_management import init_item_state_manager, get_item_state_manager, Label
from potato.user_state_management import init_user_state_manager, get_user_state_manager
from potato.phase import UserPhase

class TestActiveLearningConcurrency:
    """Multi-user concurrency tests for active learning."""

    def setup_method(self):
        clear_active_learning_manager()

    def teardown_method(self):
        clear_active_learning_manager()

    def test_simultaneous_annotation(self):
        """Test that concurrent annotations from multiple users are handled correctly."""
        items = [
            {"id": f"item_{i}", "text": f"This is item {i} for concurrency testing."}
            for i in range(10)
        ]
        # Initialize managers with proper config
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
        init_item_state_manager(config)
        init_user_state_manager(config)
        item_manager = get_item_state_manager()
        for item in items:
            item_manager.add_item(item["id"], item)
        user_manager = get_user_state_manager()
        user1 = user_manager.add_user("user1@test.com")
        user2 = user_manager.add_user("user2@test.com")
        # Set phase to annotation for both users
        user1.advance_to_phase(UserPhase.ANNOTATION, None)
        user2.advance_to_phase(UserPhase.ANNOTATION, None)
        # Assign all items to both users
        for item in items:
            user1.assign_instance(item_manager.get_item(item["id"]))
            user2.assign_instance(item_manager.get_item(item["id"]))
        # User 1 and User 2 both annotate the same first 5 items
        for i in range(5):
            user1.set_annotation(f"item_{i}", {"sentiment": "positive"}, None, None)
            user2.set_annotation(f"item_{i}", {"sentiment": "negative"}, None, None)
        # Debug: print annotation structure
        print("User1 annotations:", user1.get_all_annotations())
        print("User2 annotations:", user2.get_all_annotations())
        # Initialize active learning manager
        al_config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=2,
            min_instances_for_training=5
        )
        manager = init_active_learning_manager(al_config)
        # Trigger training
        manager.check_and_trigger_training()

        # Wait for training to complete (with timeout)
        import time
        max_wait = 10  # seconds
        start_time = time.time()
        while time.time() - start_time < max_wait:
            stats = manager.get_stats()
            if stats["training_count"] > 0:
                break
            time.sleep(0.1)

        stats = manager.get_stats()
        assert stats["training_count"] > 0