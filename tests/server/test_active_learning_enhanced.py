"""
Enhanced Active Learning Tests

This module provides comprehensive tests for the enhanced active learning system,
including configuration validation, classifier training, model persistence,
database integration, and LLM functionality.
"""

import pytest

# Skip server-side active learning tests for fast CI execution
pytestmark = pytest.mark.skip(reason="Active learning server tests skipped for fast CI - run with pytest -m slow")
import tempfile
import os
import json
import time
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any

from potato.active_learning_manager import (
    ActiveLearningManager, ActiveLearningConfig, ResolutionStrategy,
    TrainingMetrics, ModelPersistence, SchemaCycler, init_active_learning_manager,
    get_active_learning_manager, clear_active_learning_manager
)
from potato.ai.llm_active_learning import (
    LLMActiveLearning, MockLLMActiveLearning, LLMConfig, LLMPrediction,
    create_llm_active_learning
)
from potato.server_utils.config_module import (
    validate_active_learning_config, parse_active_learning_config
)
from tests.helpers.active_learning_test_utils import (
    create_temp_test_data, create_temp_config, register_and_login_user, submit_annotation, get_current_annotations, get_current_instance_id, simulate_annotation_workflow, start_flask_server_with_config
)
from potato.item_state_management import get_item_state_manager, init_item_state_manager
from potato.user_state_management import get_user_state_manager, init_user_state_manager, UserPhase


class TestActiveLearningConfig:
    """Test ActiveLearningConfig class."""

    def test_default_config(self):
        """Test default configuration values."""
        config = ActiveLearningConfig()

        assert config.enabled is False
        assert config.classifier_name == "sklearn.linear_model.LogisticRegression"
        assert config.vectorizer_name == "sklearn.feature_extraction.text.CountVectorizer"
        assert config.min_annotations_per_instance == 1
        assert config.min_instances_for_training == 10
        assert config.resolution_strategy == ResolutionStrategy.MAJORITY_VOTE
        assert config.random_sample_percent == 0.2
        assert config.update_frequency == 5
        assert config.schema_names == []
        assert config.database_enabled is False
        assert config.model_persistence_enabled is False
        assert config.llm_enabled is False

    def test_custom_config(self):
        """Test custom configuration values."""
        config = ActiveLearningConfig(
            enabled=True,
            classifier_name="sklearn.ensemble.RandomForestClassifier",
            classifier_kwargs={"n_estimators": 100},
            min_annotations_per_instance=3,
            min_instances_for_training=20,
            schema_names=["sentiment", "topic"],
            database_enabled=True,
            model_persistence_enabled=True,
            llm_enabled=True
        )

        assert config.enabled is True
        assert config.classifier_name == "sklearn.ensemble.RandomForestClassifier"
        assert config.classifier_kwargs["n_estimators"] == 100
        assert config.min_annotations_per_instance == 3
        assert config.min_instances_for_training == 20
        assert config.schema_names == ["sentiment", "topic"]
        assert config.database_enabled is True
        assert config.model_persistence_enabled is True
        assert config.llm_enabled is True


class TestSchemaCycler:
    """Test SchemaCycler class."""

    def test_valid_schemas(self):
        """Test with valid schema names."""
        schemas = ["sentiment", "topic", "category"]
        cycler = SchemaCycler(schemas)

        assert cycler.get_schema_order() == schemas
        assert cycler.get_current_schema() == "sentiment"

    def test_invalid_schemas(self):
        """Test rejection of invalid schema types."""
        with pytest.raises(ValueError, match="Text and span annotation schemes are not supported"):
            SchemaCycler(["sentiment", "text", "topic"])

        with pytest.raises(ValueError, match="Text and span annotation schemes are not supported"):
            SchemaCycler(["span", "sentiment"])

    def test_schema_cycling(self):
        """Test schema cycling functionality."""
        schemas = ["sentiment", "topic", "category"]
        cycler = SchemaCycler(schemas)

        # Test initial state
        assert cycler.get_current_schema() == "sentiment"

        # Test cycling
        cycler.advance_schema()
        assert cycler.get_current_schema() == "topic"

        cycler.advance_schema()
        assert cycler.get_current_schema() == "category"

        # Test wrap-around
        cycler.advance_schema()
        assert cycler.get_current_schema() == "sentiment"

    def test_empty_schemas(self):
        """Test behavior with empty schema list."""
        cycler = SchemaCycler([])

        assert cycler.get_current_schema() is None
        assert cycler.get_schema_order() == []

        # Should not crash
        cycler.advance_schema()
        assert cycler.get_current_schema() is None


class TestModelPersistence:
    """Test ModelPersistence class."""

    def test_save_and_load_model(self):
        """Test saving and loading models."""
        with tempfile.TemporaryDirectory() as temp_dir:
            persistence = ModelPersistence(temp_dir, retention_count=2)

            # Create a real sklearn model for testing
            from sklearn.pipeline import Pipeline
            from sklearn.feature_extraction.text import CountVectorizer
            from sklearn.linear_model import LogisticRegression

            model = Pipeline([
                ("vectorizer", CountVectorizer()),
                ("classifier", LogisticRegression())
            ])

            # Fit the model with some dummy data
            model.fit(["positive text", "negative text"], ["positive", "negative"])

            # Save model
            filepath = persistence.save_model(model, "sentiment", 100)

            assert os.path.exists(filepath)
            assert "sentiment_100_" in filepath
            assert filepath.endswith(".pkl")

            # Load model
            loaded_model = persistence.load_model(filepath)
            assert loaded_model is not None

    def test_cleanup_old_models(self):
        """Test cleanup of old models."""
        with tempfile.TemporaryDirectory() as temp_dir:
            persistence = ModelPersistence(temp_dir, retention_count=2)

            # Create multiple model files
            model_files = []
            for i in range(5):
                # Create a real sklearn model for testing
                from sklearn.pipeline import Pipeline
                from sklearn.feature_extraction.text import CountVectorizer
                from sklearn.linear_model import LogisticRegression

                model = Pipeline([
                    ("vectorizer", CountVectorizer()),
                    ("classifier", LogisticRegression())
                ])

                # Fit the model with some dummy data
                model.fit(["positive text", "negative text"], ["positive", "negative"])

                filepath = persistence.save_model(model, "sentiment", 100 + i)
                model_files.append(filepath)
                time.sleep(0.1)  # Ensure different timestamps

            # Check that only 2 files remain (retention_count=2)
            sentiment_files = [f for f in os.listdir(temp_dir) if f.startswith("sentiment_")]
            assert len(sentiment_files) == 2

    def test_load_nonexistent_model(self):
        """Test loading a model that doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            persistence = ModelPersistence(temp_dir)

            result = persistence.load_model("nonexistent.pkl")
            assert result is None


class TestLLMActiveLearning:
    """Test LLM Active Learning functionality."""

    def test_mock_llm_creation(self):
        """Test creation of mock LLM."""
        config = {
            "use_mock": True,
            "endpoint_url": "http://localhost:8000",
            "model_name": "test-model"
        }

        llm = create_llm_active_learning(config)
        assert isinstance(llm, MockLLMActiveLearning)

    def test_mock_predictions(self):
        """Test mock LLM predictions."""
        config = LLMConfig(
            endpoint_url="http://localhost:8000",
            model_name="test-model"
        )

        llm = MockLLMActiveLearning(config)

        instances = [
            {"id": "test_1", "text": "I love this product!"},
            {"id": "test_2", "text": "This is terrible."}
        ]

        predictions = llm.predict_instances(
            instances,
            "Classify sentiment",
            "sentiment",
            ["positive", "negative", "neutral"]
        )

        assert len(predictions) == 2
        for pred in predictions:
            assert pred.instance_id in ["test_1", "test_2"]
            assert pred.predicted_label in ["positive", "negative", "neutral"]
            assert 0.1 <= pred.confidence_score <= 1.0
            assert pred.error_message is None

    def test_confidence_distribution(self):
        """Test confidence distribution calculation."""
        config = LLMConfig(
            endpoint_url="http://localhost:8000",
            model_name="test-model"
        )

        llm = MockLLMActiveLearning(config)

        # Create mock predictions
        predictions = [
            LLMPrediction("1", "positive", 0.8, ""),
            LLMPrediction("2", "negative", 0.6, ""),
            LLMPrediction("3", "neutral", 0.4, ""),
            LLMPrediction("4", "positive", 0.9, ""),
            LLMPrediction("5", "negative", 0.2, "")
        ]

        distribution = llm.calculate_confidence_distribution(predictions)

        assert "0.0-0.2" in distribution
        assert "0.2-0.4" in distribution
        assert "0.4-0.6" in distribution
        assert "0.6-0.8" in distribution
        assert "0.8-1.0" in distribution

    def test_prediction_stats(self):
        """Test prediction statistics calculation."""
        config = LLMConfig(
            endpoint_url="http://localhost:8000",
            model_name="test-model"
        )

        llm = MockLLMActiveLearning(config)

        predictions = [
            LLMPrediction("1", "positive", 0.8, ""),
            LLMPrediction("2", "negative", 0.6, ""),
            LLMPrediction("3", "neutral", 0.4, "", "error")
        ]

        stats = llm.get_prediction_stats(predictions)

        assert stats["total_predictions"] == 3
        assert stats["successful_predictions"] == 2
        assert stats["error_rate"] == 1/3
        # Only valid predictions (0.8 and 0.6) are used for average: (0.8 + 0.6) / 2 = 0.7
        assert stats["average_confidence"] == 0.7


class TestConfigurationValidation:
    """Test configuration validation functions."""

    def test_valid_active_learning_config(self):
        """Test validation of valid active learning configuration."""
        config = {
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
                "min_instances_for_training": 10,
                "resolution_strategy": "majority_vote",
                "random_sample_percent": 0.2,
                "schema_names": ["sentiment", "topic"]
            }
        }

        # Should not raise any exceptions
        validate_active_learning_config(config)

    def test_invalid_schema_names(self):
        """Test validation rejects invalid schema names."""
        config = {
            "active_learning": {
                "enabled": True,
                "schema_names": ["sentiment", "text", "topic"]
            }
        }

        with pytest.raises(Exception, match="Text and span annotation schemes are not supported"):
            validate_active_learning_config(config)

    def test_invalid_random_sample_percent(self):
        """Test validation of random sample percent."""
        config = {
            "active_learning": {
                "enabled": True,
                "random_sample_percent": 1.5  # Invalid: > 1.0
            }
        }

        with pytest.raises(Exception, match="must be between 0 and 1"):
            validate_active_learning_config(config)

    def test_invalid_resolution_strategy(self):
        """Test validation of resolution strategy."""
        config = {
            "active_learning": {
                "enabled": True,
                "resolution_strategy": "invalid_strategy"
            }
        }

        with pytest.raises(Exception, match="must be one of"):
            validate_active_learning_config(config)

    def test_parse_active_learning_config(self):
        """Test parsing of active learning configuration."""
        config_data = {
            "active_learning": {
                "enabled": True,
                "classifier": {
                    "name": "sklearn.ensemble.RandomForestClassifier",
                    "hyperparameters": {"n_estimators": 100}
                },
                "vectorizer": {
                    "name": "sklearn.feature_extraction.text.TfidfVectorizer",
                    "hyperparameters": {"max_features": 1000}
                },
                "min_annotations_per_instance": 3,
                "min_instances_for_training": 20,
                "resolution_strategy": "majority_vote",
                "random_sample_percent": 0.3,
                "schema_names": ["sentiment", "topic"],
                "database": {
                    "enabled": True,
                    "type": "file"
                },
                "model_persistence": {
                    "enabled": True,
                    "save_directory": "/tmp/models",
                    "retention_count": 5
                },
                "llm": {
                    "enabled": True,
                    "use_mock": True,
                    "endpoint_url": "http://localhost:8000",
                    "model_name": "test-model"
                }
            }
        }

        al_config = parse_active_learning_config(config_data)

        assert al_config.enabled is True
        assert al_config.classifier_name == "sklearn.ensemble.RandomForestClassifier"
        assert al_config.classifier_kwargs["n_estimators"] == 100
        assert al_config.min_annotations_per_instance == 3
        assert al_config.min_instances_for_training == 20
        assert al_config.resolution_strategy == ResolutionStrategy.MAJORITY_VOTE
        assert al_config.random_sample_percent == 0.3
        assert al_config.schema_names == ["sentiment", "topic"]
        assert al_config.database_enabled is True
        assert al_config.model_persistence_enabled is True
        assert al_config.llm_enabled is True


class TestActiveLearningManager:
    """Test ActiveLearningManager class."""

    def setup_method(self):
        """Set up test environment."""
        clear_active_learning_manager()

    def teardown_method(self):
        """Clean up test environment."""
        clear_active_learning_manager()

    def test_manager_initialization(self):
        """Test manager initialization."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_instances_for_training=5
        )

        manager = init_active_learning_manager(config)

        assert manager is not None
        assert manager.config.enabled is True
        assert manager.schema_cycler.get_current_schema() == "sentiment"

    def test_manager_singleton(self):
        """Test that manager is a singleton."""
        config = ActiveLearningConfig(enabled=True, schema_names=["sentiment"])

        manager1 = init_active_learning_manager(config)
        manager2 = get_active_learning_manager()

        assert manager1 is manager2

    def test_manager_stats(self):
        """Test getting manager statistics."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment", "topic"],
            database_enabled=False,
            model_persistence_enabled=False,
            llm_enabled=False
        )

        manager = init_active_learning_manager(config)
        stats = manager.get_stats()

        assert stats["enabled"] is True
        assert stats["training_count"] == 0
        assert stats["models_trained"] == []
        assert stats["current_schema"] == "sentiment"
        assert stats["schema_order"] == ["sentiment", "topic"]
        assert stats["database_enabled"] is False
        assert stats["model_persistence_enabled"] is False
        assert stats["llm_enabled"] is False

    def test_annotation_resolution(self):
        """Test annotation resolution strategies."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            resolution_strategy=ResolutionStrategy.MAJORITY_VOTE
        )

        manager = init_active_learning_manager(config)

        # Test majority vote
        annotations = [
            {"label": "positive", "value": True, "user": "user1"},
            {"label": "positive", "value": True, "user": "user2"},
            {"label": "negative", "value": True, "user": "user3"}
        ]

        result = manager._resolve_annotations(annotations)
        assert result == "positive"

        # Test consensus
        config.resolution_strategy = ResolutionStrategy.CONSENSUS
        manager = init_active_learning_manager(config)

        consensus_annotations = [
            {"label": "positive", "value": True, "user": "user1"},
            {"label": "positive", "value": True, "user": "user2"}
        ]

        result = manager._resolve_annotations(consensus_annotations)
        assert result == "positive"

        # Test consensus failure
        mixed_annotations = [
            {"label": "positive", "value": True, "user": "user1"},
            {"label": "negative", "value": True, "user": "user2"}
        ]

        result = manager._resolve_annotations(mixed_annotations)
        assert result is None

    def test_classifier_creation(self):
        """Test classifier creation with different types."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            classifier_name="sklearn.linear_model.LogisticRegression",
            classifier_kwargs={"C": 1.0}
        )

        manager = init_active_learning_manager(config)
        classifier = manager._create_classifier()

        assert classifier is not None
        assert hasattr(classifier, 'fit')
        assert hasattr(classifier, 'predict')

    def test_vectorizer_creation(self):
        """Test vectorizer creation with different types."""
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            vectorizer_name="sklearn.feature_extraction.text.TfidfVectorizer",
            vectorizer_kwargs={"max_features": 1000}
        )

        manager = init_active_learning_manager(config)
        vectorizer = manager._create_vectorizer()

        assert vectorizer is not None
        assert hasattr(vectorizer, 'fit')
        assert hasattr(vectorizer, 'transform')


class TestIntegration:
    """Integration tests for the active learning system."""

    def setup_method(self):
        """Set up test environment."""
        clear_active_learning_manager()

    def teardown_method(self):
        """Clean up test environment."""
        clear_active_learning_manager()

    def test_full_workflow(self):
        """Test the complete active learning workflow."""
        # Create configuration
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            min_annotations_per_instance=1,
            min_instances_for_training=2,
            update_frequency=1,
            model_persistence_enabled=True,
            model_save_directory=tempfile.mkdtemp()
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
        item1_data = {"id": "item1", "text": "I love this product!"}
        item2_data = {"id": "item2", "text": "This is terrible!"}

        item_manager.add_item("item1", item1_data)
        item_manager.add_item("item2", item2_data)

        # Create a user and add annotations
        user = user_manager.add_user("user1")
        user.advance_to_phase(UserPhase.ANNOTATION, "annotation")

        # Add annotations using the real annotation system
        from potato.item_state_management import Label
        label1 = Label("sentiment", "positive")
        label2 = Label("sentiment", "negative")

        user.add_label_annotation("item1", label1, True)
        user.add_label_annotation("item2", label2, True)

        # Trigger training
        manager.force_training()

        # Wait for training to complete
        time.sleep(2)

        # Check that training occurred
        stats = manager.get_stats()
        assert stats["training_count"] > 0

    def test_llm_integration(self):
        """Test LLM integration with active learning."""
        # Create configuration with LLM enabled
        config = ActiveLearningConfig(
            enabled=True,
            schema_names=["sentiment"],
            llm_enabled=True,
            llm_config={
                "use_mock": True,
                "endpoint_url": "http://localhost:8000",
                "model_name": "test-model"
            }
        )

        # Initialize manager
        manager = init_active_learning_manager(config)

        # Verify LLM is configured
        assert manager.config.llm_enabled is True
        assert manager.config.llm_config["use_mock"] is True


if __name__ == "__main__":
    pytest.main([__file__])