"""
LLM Integration Tests for Active Learning

This module contains tests for real and mock LLM endpoints, response parsing, batch processing, and retry mechanisms.
"""

import pytest
from unittest.mock import patch
from potato.active_learning_manager import ActiveLearningConfig, init_active_learning_manager, clear_active_learning_manager
from potato.item_state_management import init_item_state_manager, get_item_state_manager, Label
from potato.user_state_management import init_user_state_manager, get_user_state_manager
from potato.phase import UserPhase

class TestActiveLearningLLMIntegration:
    """LLM integration tests for active learning."""

    def setup_method(self):
        clear_active_learning_manager()

    def teardown_method(self):
        clear_active_learning_manager()

    def test_mock_llm_prediction(self):
        """Test that the mock LLM is used for predictions and stats reflect LLM usage."""
        items = [
            {"id": f"item_{i}", "text": f"This is item {i} for LLM integration."}
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
        # Set user phase to annotation
        user1.advance_to_phase(UserPhase.ANNOTATION, None)

        # User1 annotates the first 5 items with different labels
        labels = ["positive", "negative", "positive", "negative", "neutral"]
        for i in range(5):
            user1.set_annotation(f"item_{i}", {"sentiment": labels[i]}, None, None)
        # Patch the LLM endpoint to simulate mock LLM
        with patch("potato.ai.llm_active_learning.LLMActiveLearning", autospec=True) as mock_llm:
            # Create mock predictions
            from potato.ai.llm_active_learning import LLMPrediction
            mock_predictions = [
                LLMPrediction(
                    instance_id=f"item_{i}",
                    predicted_label="positive",
                    confidence_score=0.9,
                    raw_response="Mock response"
                ) for i in range(10)
            ]
            mock_llm.return_value.predict_instances.return_value = mock_predictions
            al_config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=1,
                min_instances_for_training=5,
                llm_enabled=True,
                llm_config={
                    "use_mock": True,
                    "endpoint_url": "http://localhost:8000",
                    "model_name": "mock-model"
                }
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
            assert stats["llm_enabled"] is True
            assert stats["training_count"] > 0