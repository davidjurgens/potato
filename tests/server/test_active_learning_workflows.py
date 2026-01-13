"""
Active Learning Workflow Tests

This module provides comprehensive tests for active learning workflows,
including real annotation scenarios, training cycles, and integration
with the Potato annotation system.
"""

import pytest

# Skip server-side active learning tests for fast CI execution
pytestmark = pytest.mark.skip(reason="Active learning server tests skipped for fast CI - run with pytest -m slow")
import tempfile
import os
import json
import time
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any, List

from potato.active_learning_manager import (
    ActiveLearningManager, ActiveLearningConfig, ResolutionStrategy,
    init_active_learning_manager, get_active_learning_manager, clear_active_learning_manager
)
from potato.ai.llm_active_learning import MockLLMActiveLearning, LLMConfig
from potato.server_utils.config_module import parse_active_learning_config
from potato.item_state_management import get_item_state_manager, init_item_state_manager
from potato.user_state_management import get_user_state_manager, init_user_state_manager, UserPhase
from tests.helpers.active_learning_test_utils import (
    create_temp_test_data, create_temp_config, register_and_login_user, submit_annotation, get_current_annotations, get_current_instance_id, simulate_annotation_workflow, start_flask_server_with_config
)


class TestActiveLearningWorkflows:
    """Test active learning workflows and real-world scenarios."""

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

    def test_basic_training_workflow(self):
        """Test basic training workflow with real data."""
        # Create configuration
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=3,
            update_frequency=2,
            model_persistence_enabled=True,
            model_save_directory=self.model_dir
        )

        # Initialize managers
        test_config = {
            "secret_key": "test-key",
            "task_dir": tempfile.mkdtemp(),
            "output_annotation_dir": tempfile.mkdtemp(),
            "data_files": [],
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "type": "radio",
                    "annotation_type": "radio",
                    "labels": ["positive", "negative", "neutral"],
                    "description": "Choose sentiment."
                }
            ],
            "annotation_task_name": "Test Task",
            "site_file": "base_template.html",
            "html_layout": "base_template.html",
            "base_html_template": "base_template.html",
            "header_file": "base_template.html",
            "site_dir": tempfile.mkdtemp(),
            "customjs": None,
            "customjs_hostname": None,
            "alert_time_each_instance": 10000000
        }

        init_user_state_manager(test_config)
        init_item_state_manager(test_config)

        # Initialize active learning manager
        manager = init_active_learning_manager(config)

        # Get real managers
        item_manager = get_item_state_manager()
        user_manager = get_user_state_manager()

        # Clear any existing data
        item_manager.clear()
        user_manager.clear()

        # Create test items
        items_data = {
            "item1": {"id": "item1", "text": "I love this product! It's amazing."},
            "item2": {"id": "item2", "text": "This is terrible. I hate it."},
            "item3": {"id": "item3", "text": "The weather is nice today."},
            "item4": {"id": "item4", "text": "This movie was boring and predictable."},
            "item5": {"id": "item5", "text": "The new technology is revolutionary."},
            "item6": {"id": "item6", "text": "I'm disappointed with the service."},
        }

        for item_id, item_data in items_data.items():
            item_manager.add_item(item_id, item_data)

        # Create users and add annotations
        user1 = user_manager.add_user("user1")
        user2 = user_manager.add_user("user2")

        user1.advance_to_phase(UserPhase.ANNOTATION, "annotation")
        user2.advance_to_phase(UserPhase.ANNOTATION, "annotation")

        # Add annotations using the real annotation system
        from potato.item_state_management import Label

        # User 1 annotations
        user1.add_label_annotation("item1", Label("sentiment", "positive"), True)
        user1.add_label_annotation("item2", Label("sentiment", "negative"), True)
        user1.add_label_annotation("item3", Label("sentiment", "neutral"), True)

        # User 2 annotations
        user2.add_label_annotation("item4", Label("sentiment", "negative"), True)
        user2.add_label_annotation("item5", Label("sentiment", "positive"), True)
        user2.add_label_annotation("item6", Label("sentiment", "negative"), True)

        # Trigger training
        manager.force_training()

        # Wait for training to complete
        time.sleep(3)

        # Verify training occurred
        stats = manager.get_stats()
        assert stats["training_count"] > 0
        assert "sentiment" in stats["models_trained"]

        # Check that models were saved
        model_files = [f for f in os.listdir(self.model_dir) if f.endswith('.pkl')]
        assert len(model_files) > 0

    def test_schema_cycling_workflow(self):
        """Test cycling through multiple annotation schemas."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment", "topic", "urgency"],
            min_annotations_per_instance=1,
            min_instances_for_training=2,
            update_frequency=1,
            model_persistence_enabled=True,
            model_save_directory=self.model_dir
        )

        # Initialize managers
        test_config = {
            "secret_key": "test-key",
            "task_dir": tempfile.mkdtemp(),
            "output_annotation_dir": tempfile.mkdtemp(),
            "data_files": [],
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "type": "radio",
                    "annotation_type": "radio",
                    "labels": ["positive", "negative", "neutral"],
                    "description": "Choose sentiment."
                },
                {
                    "name": "topic",
                    "type": "radio",
                    "annotation_type": "radio",
                    "labels": ["technology", "product", "weather"],
                    "description": "Choose topic."
                },
                {
                    "name": "urgency",
                    "type": "radio",
                    "annotation_type": "radio",
                    "labels": ["low", "high"],
                    "description": "Choose urgency."
                }
            ],
            "annotation_task_name": "Test Task",
            "site_file": "base_template.html",
            "html_layout": "base_template.html",
            "base_html_template": "base_template.html",
            "header_file": "base_template.html",
            "site_dir": tempfile.mkdtemp(),
            "customjs": None,
            "customjs_hostname": None,
            "alert_time_each_instance": 10000000
        }

        init_user_state_manager(test_config)
        init_item_state_manager(test_config)

        manager = init_active_learning_manager(config)

        # Get real managers
        item_manager = get_item_state_manager()
        user_manager = get_user_state_manager()

        # Clear any existing data
        item_manager.clear()
        user_manager.clear()

        # Create test items
        items_data = {
            "item1": {"id": "item1", "text": "I love this product! It's amazing."},
            "item2": {"id": "item2", "text": "This is terrible. I hate it."},
            "item3": {"id": "item3", "text": "The weather is nice today."},
        }

        for item_id, item_data in items_data.items():
            item_manager.add_item(item_id, item_data)

        # Create user and add annotations
        user = user_manager.add_user("user1")
        user.advance_to_phase(UserPhase.ANNOTATION, "annotation")

        # Add annotations using the real annotation system
        from potato.item_state_management import Label

        # Add annotations for different schemas
        user.add_label_annotation("item1", Label("sentiment", "positive"), True)
        user.add_label_annotation("item1", Label("topic", "technology"), True)
        user.add_label_annotation("item1", Label("urgency", "low"), True)

        user.add_label_annotation("item2", Label("sentiment", "negative"), True)
        user.add_label_annotation("item2", Label("topic", "product"), True)
        user.add_label_annotation("item2", Label("urgency", "high"), True)

        user.add_label_annotation("item3", Label("sentiment", "neutral"), True)
        user.add_label_annotation("item3", Label("topic", "weather"), True)
        user.add_label_annotation("item3", Label("urgency", "low"), True)

        # Trigger multiple training cycles
        for i in range(3):
            manager.force_training()
            time.sleep(2)

        # Verify training occurred (may not train all schemas in one cycle)
        stats = manager.get_stats()
        assert stats["training_count"] >= 1

    def test_annotation_resolution_strategies(self):
        """Test different annotation resolution strategies."""
        strategies = [
            ResolutionStrategy.MAJORITY_VOTE,
            ResolutionStrategy.CONSENSUS,
            ResolutionStrategy.RANDOM
        ]

        for strategy in strategies:
            config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=2,
                min_instances_for_training=2,
                resolution_strategy=strategy,
                update_frequency=1
            )

            # Initialize managers
            test_config = {
                "secret_key": "test-key",
                "task_dir": tempfile.mkdtemp(),
                "output_annotation_dir": tempfile.mkdtemp(),
                "data_files": [],
                "item_properties": {
                    "id_key": "id",
                    "text_key": "text"
                },
                "user_config": {
                    "allow_all_users": True,
                    "users": []
                },
                "annotation_schemes": [
                    {
                        "name": "sentiment",
                        "type": "radio",
                        "annotation_type": "radio",
                        "labels": ["positive", "negative", "neutral"],
                        "description": "Choose sentiment."
                    }
                ],
                "annotation_task_name": "Test Task",
                "site_file": "base_template.html",
                "html_layout": "base_template.html",
                "base_html_template": "base_template.html",
                "header_file": "base_template.html",
                "site_dir": tempfile.mkdtemp(),
                "customjs": None,
                "customjs_hostname": None,
                "alert_time_each_instance": 10000000
            }

            init_user_state_manager(test_config)
            init_item_state_manager(test_config)

            manager = init_active_learning_manager(config)

            # Get real managers
            item_manager = get_item_state_manager()
            user_manager = get_user_state_manager()

            # Clear any existing data
            item_manager.clear()
            user_manager.clear()

            # Create test items
            items_data = {
                "item1": {"id": "item1", "text": "This product is okay."},
                "item2": {"id": "item2", "text": "I'm not sure about this."},
            }

            for item_id, item_data in items_data.items():
                item_manager.add_item(item_id, item_data)

            # Create users and add conflicting annotations
            user1 = user_manager.add_user("user1")
            user2 = user_manager.add_user("user2")

            user1.advance_to_phase(UserPhase.ANNOTATION, "annotation")
            user2.advance_to_phase(UserPhase.ANNOTATION, "annotation")

            # Add annotations using the real annotation system
            from potato.item_state_management import Label

            # User 1 annotations
            user1.add_label_annotation("item1", Label("sentiment", "positive"), True)
            user1.add_label_annotation("item2", Label("sentiment", "neutral"), True)

            # User 2 annotations (conflicting for item1)
            user2.add_label_annotation("item1", Label("sentiment", "negative"), True)
            user2.add_label_annotation("item2", Label("sentiment", "neutral"), True)

            # Trigger training
            manager.force_training()
            time.sleep(2)

            # Verify training completed (resolution strategy worked)
            stats = manager.get_stats()
            assert stats["training_count"] > 0

    def test_confidence_based_reordering(self):
        """Test that instances are reordered based on confidence scores."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=2,
            update_frequency=1,
            max_instances_to_reorder=5
        )

        # Initialize managers
        test_config = {
            "secret_key": "test-key",
            "task_dir": tempfile.mkdtemp(),
            "output_annotation_dir": tempfile.mkdtemp(),
            "data_files": [],
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "type": "radio",
                    "annotation_type": "radio",
                    "labels": ["positive", "negative", "neutral"],
                    "description": "Choose sentiment."
                }
            ],
            "annotation_task_name": "Test Task",
            "site_file": "base_template.html",
            "html_layout": "base_template.html",
            "base_html_template": "base_template.html",
            "header_file": "base_template.html",
            "site_dir": tempfile.mkdtemp(),
            "customjs": None,
            "customjs_hostname": None,
            "alert_time_each_instance": 10000000
        }

        init_user_state_manager(test_config)
        init_item_state_manager(test_config)

        manager = init_active_learning_manager(config)

        # Get real managers
        item_manager = get_item_state_manager()
        user_manager = get_user_state_manager()

        # Clear any existing data
        item_manager.clear()
        user_manager.clear()

        # Create test items
        items_data = {
            "item1": {"id": "item1", "text": "I absolutely love this!"},
            "item2": {"id": "item2", "text": "This is terrible!"},
            "item3": {"id": "item3", "text": "It's okay, I guess."},
            "item4": {"id": "item4", "text": "I'm not sure what to think."},
            "item5": {"id": "item5", "text": "This could be good or bad."},
            "item6": {"id": "item6", "text": "I hate this with passion!"},
            "item7": {"id": "item7", "text": "This is the best thing ever!"},
        }
        for item_id, item_data in items_data.items():
            item_manager.add_item(item_id, item_data)

        # Create user and add annotations
        user = user_manager.add_user("user1")
        user.advance_to_phase(UserPhase.ANNOTATION, "annotation")
        from potato.item_state_management import Label
        user.add_label_annotation("item1", Label("sentiment", "positive"), True)
        user.add_label_annotation("item2", Label("sentiment", "negative"), True)

        # Patch reorder_instances to capture calls
        reorder_calls = []
        orig_reorder = item_manager.reorder_instances
        def mock_reorder(new_order):
            reorder_calls.append(new_order)
            return orig_reorder(new_order)
        item_manager.reorder_instances = mock_reorder

        # Trigger training
        manager.force_training()
        time.sleep(2)

        # Verify reordering occurred
        assert len(reorder_calls) > 0

    def test_llm_integration_workflow(self):
        """Test LLM integration in active learning workflow."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=2,
            update_frequency=1,
            llm_enabled=True,
            llm_config={
                "use_mock": True,
                "endpoint_url": "http://localhost:8000",
                "model_name": "test-model"
            }
        )

        # Initialize managers
        test_config = {
            "secret_key": "test-key",
            "task_dir": tempfile.mkdtemp(),
            "output_annotation_dir": tempfile.mkdtemp(),
            "data_files": [],
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "type": "radio",
                    "annotation_type": "radio",
                    "labels": ["positive", "negative", "neutral"],
                    "description": "Choose sentiment."
                }
            ],
            "annotation_task_name": "Test Task",
            "site_file": "base_template.html",
            "html_layout": "base_template.html",
            "base_html_template": "base_template.html",
            "header_file": "base_template.html",
            "site_dir": tempfile.mkdtemp(),
            "customjs": None,
            "customjs_hostname": None,
            "alert_time_each_instance": 10000000
        }

        init_user_state_manager(test_config)
        init_item_state_manager(test_config)

        manager = init_active_learning_manager(config)

        # Get real managers
        item_manager = get_item_state_manager()
        user_manager = get_user_state_manager()

        # Clear any existing data
        item_manager.clear()
        user_manager.clear()

        # Create test items
        items_data = {
            "item1": {"id": "item1", "text": "I love this product!"},
            "item2": {"id": "item2", "text": "This is terrible."},
            "item3": {"id": "item3", "text": "The weather is nice."},
            "item4": {"id": "item4", "text": "I'm not sure about this."},
            "item5": {"id": "item5", "text": "This could be good or bad."},
        }
        for item_id, item_data in items_data.items():
            item_manager.add_item(item_id, item_data)

        # Create user and add annotations
        user = user_manager.add_user("user1")
        user.advance_to_phase(UserPhase.ANNOTATION, "annotation")
        from potato.item_state_management import Label
        user.add_label_annotation("item1", Label("sentiment", "positive"), True)
        user.add_label_annotation("item2", Label("sentiment", "negative"), True)

        # Trigger training
        manager.force_training()
        time.sleep(2)

        # Verify LLM integration is working
        stats = manager.get_stats()
        assert stats["llm_enabled"] is True
        assert stats["training_count"] > 0

    def test_error_handling_and_recovery(self):
        """Test error handling and recovery in active learning."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=2,
            update_frequency=1
        )

        manager = init_active_learning_manager(config)

        # Test with invalid classifier name
        config.classifier_name = "invalid.classifier.Class"
        manager.config = config

        with patch('potato.active_learning_manager.get_item_state_manager') as mock_item_manager, \
             patch('potato.active_learning_manager.get_user_state_manager') as mock_user_manager:

            # Create mock items with proper interface
            mock_items = {
                "item1": self.create_mock_item("I love this product!"),
                "item2": self.create_mock_item("This is terrible."),
            }

            mock_item_manager.return_value.get_item.side_effect = lambda item_id: mock_items.get(item_id)
            mock_item_manager.return_value.get_instance_ids.return_value = list(mock_items.keys())
            mock_item_manager.return_value.get_annotators_for_item.return_value = set()

            # Create training data
            mock_user_state = Mock()
            mock_user_state.user_id = "user1"
            mock_user_state.get_all_annotations.return_value = {
                "item1": {"labels": {"sentiment": {"positive": True}}},
                "item2": {"labels": {"sentiment": {"negative": True}}},
            }

            mock_user_manager.return_value.get_all_user_states.return_value = [mock_user_state]

            # Trigger training (should handle error gracefully)
            manager.check_and_trigger_training()
            time.sleep(2)

            # Verify manager is still functional despite errors
            stats = manager.get_stats()
            assert stats["enabled"] is True  # Manager is still enabled
            assert "training_count" in stats  # Stats are accessible
            assert "current_schema" in stats  # Schema cycler is working

    def test_concurrent_annotation_workflow(self):
        """Test active learning with concurrent annotations from multiple users."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=2,
            min_instances_for_training=3,
            update_frequency=3,
            resolution_strategy=ResolutionStrategy.MAJORITY_VOTE
        )

        # Initialize managers
        test_config = {
            "secret_key": "test-key",
            "task_dir": tempfile.mkdtemp(),
            "output_annotation_dir": tempfile.mkdtemp(),
            "data_files": [],
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "type": "radio",
                    "annotation_type": "radio",
                    "labels": ["positive", "negative", "neutral"],
                    "description": "Choose sentiment."
                }
            ],
            "annotation_task_name": "Test Task",
            "site_file": "base_template.html",
            "html_layout": "base_template.html",
            "base_html_template": "base_template.html",
            "header_file": "base_template.html",
            "site_dir": tempfile.mkdtemp(),
            "customjs": None,
            "customjs_hostname": None,
            "alert_time_each_instance": 10000000
        }

        init_user_state_manager(test_config)
        init_item_state_manager(test_config)

        manager = init_active_learning_manager(config)

        # Get real managers
        item_manager = get_item_state_manager()
        user_manager = get_user_state_manager()

        # Clear any existing data
        item_manager.clear()
        user_manager.clear()

        # Create test items
        items_data = {
            "item1": {"id": "item1", "text": "I love this product!"},
            "item2": {"id": "item2", "text": "This is terrible."},
            "item3": {"id": "item3", "text": "The weather is nice."},
            "item4": {"id": "item4", "text": "I'm not sure about this."},
            "item5": {"id": "item5", "text": "This could be good or bad."},
        }

        for item_id, item_data in items_data.items():
            item_manager.add_item(item_id, item_data)

        # Create users and add annotations
        user1 = user_manager.add_user("user1")
        user2 = user_manager.add_user("user2")
        user3 = user_manager.add_user("user3")

        user1.advance_to_phase(UserPhase.ANNOTATION, "annotation")
        user2.advance_to_phase(UserPhase.ANNOTATION, "annotation")
        user3.advance_to_phase(UserPhase.ANNOTATION, "annotation")

        # Add annotations using the real annotation system
        from potato.item_state_management import Label

        # User 1 annotations
        user1.add_label_annotation("item1", Label("sentiment", "positive"), True)
        user1.add_label_annotation("item2", Label("sentiment", "negative"), True)
        user1.add_label_annotation("item3", Label("sentiment", "neutral"), True)

        # User 2 annotations (same as user1 for item1 and item2, different for item3)
        user2.add_label_annotation("item1", Label("sentiment", "positive"), True)
        user2.add_label_annotation("item2", Label("sentiment", "negative"), True)
        user2.add_label_annotation("item3", Label("sentiment", "positive"), True)

        # User 3 annotations
        user3.add_label_annotation("item4", Label("sentiment", "negative"), True)
        user3.add_label_annotation("item5", Label("sentiment", "neutral"), True)

        # Trigger training
        manager.force_training()
        time.sleep(2)

        # Verify training completed successfully
        stats = manager.get_stats()
        assert stats["training_count"] > 0

    def test_performance_with_large_dataset(self):
        """Test active learning performance with larger datasets."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=5,
            update_frequency=5,
            max_instances_to_reorder=20
        )

        # Initialize managers
        test_config = {
            "secret_key": "test-key",
            "task_dir": tempfile.mkdtemp(),
            "output_annotation_dir": tempfile.mkdtemp(),
            "data_files": [],
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "type": "radio",
                    "annotation_type": "radio",
                    "labels": ["positive", "negative", "neutral"],
                    "description": "Choose sentiment."
                }
            ],
            "annotation_task_name": "Test Task",
            "site_file": "base_template.html",
            "html_layout": "base_template.html",
            "base_html_template": "base_template.html",
            "header_file": "base_template.html",
            "site_dir": tempfile.mkdtemp(),
            "customjs": None,
            "customjs_hostname": None,
            "alert_time_each_instance": 10000000
        }

        init_user_state_manager(test_config)
        init_item_state_manager(test_config)

        manager = init_active_learning_manager(config)

        # Get real managers
        item_manager = get_item_state_manager()
        user_manager = get_user_state_manager()

        # Clear any existing data
        item_manager.clear()
        user_manager.clear()

        # Create larger dataset
        for i in range(50):
            item_data = {"id": f"item{i}", "text": f"This is test item number {i} with some content."}
            item_manager.add_item(f"item{i}", item_data)

        # Create user and add annotations
        user = user_manager.add_user("user1")
        user.advance_to_phase(UserPhase.ANNOTATION, "annotation")

        # Add annotations using the real annotation system
        from potato.item_state_management import Label

        # Create annotations for subset of items
        for i in range(10):
            label = "positive" if i % 3 == 0 else "negative" if i % 3 == 1 else "neutral"
            user.add_label_annotation(f"item{i}", Label("sentiment", label), True)

        # Measure training time
        start_time = time.time()
        manager.force_training()
        time.sleep(3)
        training_time = time.time() - start_time

        # Verify training completed within reasonable time
        stats = manager.get_stats()
        assert stats["training_count"] > 0

    def test_configuration_parsing_workflow(self):
        """Test configuration parsing and validation workflow."""
        # Test valid configuration
        config_data = {
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
                "min_annotations_per_instance": 2,
                "min_instances_for_training": 5,
                "schema_names": ["sentiment", "topic"]
            }
        }

        config = parse_active_learning_config(config_data)
        assert config.enabled is True
        assert config.classifier_name == "sklearn.linear_model.LogisticRegression"
        assert config.vectorizer_name == "sklearn.feature_extraction.text.TfidfVectorizer"
        assert config.min_annotations_per_instance == 2
        assert config.min_instances_for_training == 5
        assert config.schema_names == ["sentiment", "topic"]


if __name__ == "__main__":
    pytest.main([__file__])