"""
Performance and Scalability Tests for Active Learning

This module contains tests for large dataset training, classifier comparison, concurrent annotations, and model persistence with large models.
"""

import pytest
import time
from tests.helpers.active_learning_test_utils import start_flask_server_with_config
from potato.active_learning_manager import ActiveLearningConfig, init_active_learning_manager, clear_active_learning_manager

class TestActiveLearningPerformance:
    """Performance and scalability tests for active learning."""

    def setup_method(self):
        clear_active_learning_manager()
        from potato.item_state_management import clear_item_state_manager
        from potato.user_state_management import clear_user_state_manager
        clear_item_state_manager()
        clear_user_state_manager()

    def teardown_method(self):
        clear_active_learning_manager()
        from potato.item_state_management import clear_item_state_manager
        from potato.user_state_management import clear_user_state_manager
        clear_item_state_manager()
        clear_user_state_manager()

    def test_large_dataset_training_performance(self):
        """Test that training with 1000 items completes in reasonable time."""
        from potato.item_state_management import init_item_state_manager, get_item_state_manager
        from potato.user_state_management import init_user_state_manager, get_user_state_manager
        from potato.phase import UserPhase

        # Create 1000 items
        items = [
            {"id": f"item_{i}", "text": f"This is item {i} for performance testing with some longer text content to make it more realistic."}
            for i in range(1000)
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

        # Add all items
        for item in items:
            item_manager.add_item(item["id"], item)

        # Create a user and add annotations
        user = user_manager.add_user("test_user@example.com")
        user.advance_to_phase(UserPhase.ANNOTATION, None)

        # Assign first 100 items to user
        for i in range(100):
            user.assign_instance(item_manager.get_item(f"item_{i}"))

        # Annotate 50 items with diverse labels
        labels = ["positive", "negative", "neutral"]
        for i in range(50):
            label = labels[i % 3]
            user.set_annotation(f"item_{i}", {"sentiment": label}, None, None)

        # Initialize active learning manager
        al_config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=10
        )
        manager = init_active_learning_manager(al_config)

        # Time the training process
        start_time = time.time()
        manager.check_and_trigger_training()

        # Wait for training to complete
        max_wait = 30  # seconds
        while time.time() - start_time < max_wait:
            stats = manager.get_stats()
            if stats["training_count"] > 0:
                break
            time.sleep(0.1)

        elapsed = time.time() - start_time

        # Verify training completed successfully
        stats = manager.get_stats()
        assert stats["training_count"] > 0, "Training should have completed"
        assert elapsed < 30, f"Training took too long: {elapsed:.2f} seconds"

        print(f"Training completed in {elapsed:.2f} seconds with {stats['training_count']} training runs")

    def test_classifier_comparison_performance(self):
        """Test performance comparison between different classifiers."""
        from potato.item_state_management import init_item_state_manager, get_item_state_manager
        from potato.user_state_management import init_user_state_manager, get_user_state_manager
        from potato.phase import UserPhase

        # Create test data
        items = [
            {"id": f"item_{i}", "text": f"This is item {i} for classifier comparison testing."}
            for i in range(200)
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

        # Add items and create annotations
        for item in items:
            item_manager.add_item(item["id"], item)

        user = user_manager.add_user("test_user@example.com")
        user.advance_to_phase(UserPhase.ANNOTATION, None)

        # Annotate 30 items with diverse labels
        labels = ["positive", "negative", "neutral"]
        for i in range(30):
            label = labels[i % 3]
            user.set_annotation(f"item_{i}", {"sentiment": label}, None, None)

        # Test LogisticRegression
        start_time = time.time()
        lr_config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            classifier_name="sklearn.linear_model.LogisticRegression",
            min_annotations_per_instance=1,
            min_instances_for_training=10
        )
        lr_manager = init_active_learning_manager(lr_config)
        lr_manager.check_and_trigger_training()

        # Wait for training
        while time.time() - start_time < 10:
            stats = lr_manager.get_stats()
            if stats["training_count"] > 0:
                break
            time.sleep(0.1)

        lr_time = time.time() - start_time
        clear_active_learning_manager()

        # Test RandomForest
        start_time = time.time()
        rf_config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            classifier_name="sklearn.ensemble.RandomForestClassifier",
            min_annotations_per_instance=1,
            min_instances_for_training=10
        )
        rf_manager = init_active_learning_manager(rf_config)
        rf_manager.check_and_trigger_training()

        # Wait for training
        while time.time() - start_time < 10:
            stats = rf_manager.get_stats()
            if stats["training_count"] > 0:
                break
            time.sleep(0.1)

        rf_time = time.time() - start_time

        # Both should complete within reasonable time
        assert lr_time < 10, f"LogisticRegression took too long: {lr_time:.2f} seconds"
        assert rf_time < 15, f"RandomForest took too long: {rf_time:.2f} seconds"

        print(f"LogisticRegression: {lr_time:.2f}s, RandomForest: {rf_time:.2f}s")

    def test_model_persistence_performance(self):
        """Test performance of model saving and loading with large models."""
        import tempfile
        import os
        from potato.item_state_management import init_item_state_manager, get_item_state_manager
        from potato.user_state_management import init_user_state_manager, get_user_state_manager
        from potato.phase import UserPhase

        # Create temporary directory for model persistence
        temp_dir = tempfile.mkdtemp()

        try:
            # Create test data
            items = [
                {"id": f"item_{i}", "text": f"This is item {i} for model persistence testing with longer text content."}
                for i in range(500)
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

            # Add items and create annotations
            for item in items:
                item_manager.add_item(item["id"], item)

            user = user_manager.add_user("test_user@example.com")
            user.advance_to_phase(UserPhase.ANNOTATION, None)

            # Annotate 100 items with diverse labels
            labels = ["positive", "negative", "neutral"]
            for i in range(100):
                label = labels[i % 3]
                user.set_annotation(f"item_{i}", {"sentiment": label}, None, None)

            # Test with model persistence enabled
            al_config = ActiveLearningConfig(
                enabled=True,
                schema_names=["sentiment"],
                min_annotations_per_instance=1,
                min_instances_for_training=10,
                model_persistence_enabled=True,
                model_save_directory=temp_dir,
                model_retention_count=3
            )

            manager = init_active_learning_manager(al_config)

            # Time the training and saving process
            start_time = time.time()
            manager.check_and_trigger_training()

            # Wait for training to complete
            max_wait = 20
            while time.time() - start_time < max_wait:
                stats = manager.get_stats()
                if stats["training_count"] > 0:
                    break
                time.sleep(0.1)

            training_time = time.time() - start_time

            # Check that model files were created
            model_files = [f for f in os.listdir(temp_dir) if f.endswith('.pkl')]
            assert len(model_files) > 0, "Model files should have been created"

            # Test model loading performance
            start_time = time.time()
            from potato.active_learning_manager import ModelPersistence
            model_persistence = ModelPersistence(temp_dir, retention_count=3)

            # Load the most recent model
            if model_files:
                latest_model_file = sorted(model_files)[-1]
                model_path = os.path.join(temp_dir, latest_model_file)
                loaded_model = model_persistence.load_model(model_path)
                assert loaded_model is not None, "Model should load successfully"

            loading_time = time.time() - start_time

            # Performance assertions
            assert training_time < 20, f"Training with persistence took too long: {training_time:.2f} seconds"
            assert loading_time < 5, f"Model loading took too long: {loading_time:.2f} seconds"

            print(f"Training with persistence: {training_time:.2f}s, Model loading: {loading_time:.2f}s")
            print(f"Created {len(model_files)} model files")

        finally:
            # Cleanup
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)