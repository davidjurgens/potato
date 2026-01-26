"""
Performance and Scalability Tests for Active Learning

This module contains tests for large dataset training, classifier comparison,
concurrent annotations, and model persistence with large models.
"""

import pytest
import time
from potato.active_learning_manager import ActiveLearningConfig, init_active_learning_manager, clear_active_learning_manager
from potato.item_state_management import Label


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

        # Annotate 50 items with diverse labels using Label objects
        labels = ["positive", "negative", "neutral"]
        for i in range(50):
            label = labels[i % 3]
            user.add_label_annotation(f"item_{i}", Label("sentiment", label), True)

        # Initialize active learning manager
        al_config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=10
        )
        manager = init_active_learning_manager(al_config)

        # Time the training process - use force_training to ensure it runs
        start_time = time.time()
        manager.force_training()

        # Wait for training to complete with strict timeout
        max_wait = 10  # seconds
        trained = False
        while time.time() - start_time < max_wait:
            stats = manager.get_stats()
            if stats["training_count"] > 0:
                trained = True
                break
            time.sleep(0.2)

        elapsed = time.time() - start_time

        assert trained, f"Training did not complete within {max_wait} seconds"
        assert elapsed < max_wait, f"Training took too long: {elapsed:.2f} seconds"

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

        # Annotate 30 items with diverse labels using Label objects
        labels = ["positive", "negative", "neutral"]
        for i in range(30):
            label = labels[i % 3]
            user.add_label_annotation(f"item_{i}", Label("sentiment", label), True)

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
        lr_manager.force_training()

        # Wait for training with timeout
        max_wait = 5
        lr_trained = False
        while time.time() - start_time < max_wait:
            stats = lr_manager.get_stats()
            if stats["training_count"] > 0:
                lr_trained = True
                break
            time.sleep(0.2)

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
        rf_manager.force_training()

        # Wait for training with timeout
        rf_trained = False
        while time.time() - start_time < max_wait:
            stats = rf_manager.get_stats()
            if stats["training_count"] > 0:
                rf_trained = True
                break
            time.sleep(0.2)

        rf_time = time.time() - start_time

        # At least one classifier should train successfully
        assert lr_trained or rf_trained, "Neither classifier completed training"

    def test_model_persistence_performance(self):
        """Test performance of model saving and loading with large models."""
        import tempfile
        import os
        import shutil
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

            # Annotate 100 items with diverse labels using Label objects
            labels = ["positive", "negative", "neutral"]
            for i in range(100):
                label = labels[i % 3]
                user.add_label_annotation(f"item_{i}", Label("sentiment", label), True)

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
            manager.force_training()

            # Wait for training to complete with strict timeout
            max_wait = 10
            trained = False
            while time.time() - start_time < max_wait:
                stats = manager.get_stats()
                if stats["training_count"] > 0:
                    trained = True
                    break
                time.sleep(0.2)

            training_time = time.time() - start_time

            assert trained, f"Training did not complete within {max_wait} seconds"

            # Check that model files were created
            model_files = [f for f in os.listdir(temp_dir) if f.endswith('.pkl')]
            assert len(model_files) > 0, "No model files were created"

            # Test model loading performance
            start_time = time.time()
            from potato.active_learning_manager import ModelPersistence
            model_persistence = ModelPersistence(temp_dir, retention_count=3)

            # Load the most recent model
            latest_model_file = sorted(model_files)[-1]
            model_path = os.path.join(temp_dir, latest_model_file)
            loaded_model = model_persistence.load_model(model_path)
            loading_time = time.time() - start_time

            assert loaded_model is not None, "Model loading returned None"
            assert loading_time < 5.0, f"Model loading took too long: {loading_time:.2f}s"

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)
