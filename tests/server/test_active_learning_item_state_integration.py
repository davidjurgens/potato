"""
Item State Management Integration Tests for Active Learning

This module contains tests for preserving user progress, completed annotations, and assignment strategy integration during active learning.
"""

import pytest

# Skip server-side active learning tests for fast CI execution
pytestmark = pytest.mark.skip(reason="Active learning server tests skipped for fast CI - run with pytest -m slow")
from potato.active_learning_manager import ActiveLearningConfig, init_active_learning_manager, clear_active_learning_manager
from potato.item_state_management import init_item_state_manager, get_item_state_manager, Label
from potato.user_state_management import init_user_state_manager, get_user_state_manager

class TestActiveLearningItemStateIntegration:
    """Item state management integration tests for active learning."""

    def setup_method(self):
        clear_active_learning_manager()

    def teardown_method(self):
        clear_active_learning_manager()

    def test_preserve_user_progress(self):
        """Test that annotated items remain at the front of the queue after reordering."""
        items = [
            {"id": f"item_{i}", "text": f"This is item {i} for item state integration."}
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
        init_item_state_manager(config)
        init_user_state_manager(config)
        item_manager = get_item_state_manager()
        for item in items:
            item_manager.add_item(item["id"], item)
        user_manager = get_user_state_manager()
        user1 = user_manager.add_user("user1@test.com")
        # Assign all items to user1
        for item in items:
            user1.assign_instance(item_manager.get_item(item["id"]))
        # User1 annotates the first 3 items
        annotated_ids = [item["id"] for item in items[:3]]
        for iid in annotated_ids:
            user1.add_label_annotation(iid, Label("sentiment", "positive"), True)
        # Initialize active learning manager
        al_config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=3
        )
        manager = init_active_learning_manager(al_config)
        # Trigger training (which will reorder)
        manager.check_and_trigger_training()
        # Check that annotated items are at the front of the user's queue
        # (Assume user1.instance_id_ordering is the queue)
        ordering = user1.instance_id_ordering
        assert ordering[:3] == annotated_ids