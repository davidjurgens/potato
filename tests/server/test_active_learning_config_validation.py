"""
Configuration Validation Tests for Active Learning

This module contains tests for classifier/vectorizer types, invalid hyperparameters, schema name validation, DB/model path validation, and LLM config validation.
"""

import pytest
from potato.server_utils.config_module import validate_active_learning_config, ConfigValidationError

class TestActiveLearningConfigValidation:
    """Configuration validation tests for active learning."""

    def test_missing_classifier_name(self):
        """Test that missing classifier name raises a validation error."""
        config = {
            "active_learning": {
                "enabled": True,
                "classifier": {},  # Missing name
                "vectorizer": {"name": "sklearn.feature_extraction.text.CountVectorizer"},
                "min_annotations_per_instance": 1,
                "min_instances_for_training": 5,
                "schema_names": ["sentiment"]
            }
        }
        with pytest.raises(ConfigValidationError):
            validate_active_learning_config(config)

    def test_invalid_classifier_type(self):
        """Test that invalid classifier type raises a validation error."""
        config = {
            "active_learning": {
                "enabled": True,
                "classifier": {"name": 123},  # Invalid: not a string
                "vectorizer": {"name": "sklearn.feature_extraction.text.CountVectorizer"},
                "min_annotations_per_instance": 1,
                "min_instances_for_training": 5,
                "schema_names": ["sentiment"]
            }
        }
        with pytest.raises(ConfigValidationError):
            validate_active_learning_config(config)

    def test_invalid_vectorizer_type(self):
        """Test that invalid vectorizer type raises a validation error."""
        config = {
            "active_learning": {
                "enabled": True,
                "classifier": {"name": "sklearn.linear_model.LogisticRegression"},
                "vectorizer": {"name": 456},  # Invalid: not a string
                "min_annotations_per_instance": 1,
                "min_instances_for_training": 5,
                "schema_names": ["sentiment"]
            }
        }
        with pytest.raises(ConfigValidationError):
            validate_active_learning_config(config)

    def test_negative_min_annotations(self):
        """Test that negative min_annotations_per_instance raises a validation error."""
        config = {
            "active_learning": {
                "enabled": True,
                "classifier": {"name": "sklearn.linear_model.LogisticRegression"},
                "vectorizer": {"name": "sklearn.feature_extraction.text.CountVectorizer"},
                "min_annotations_per_instance": -1,  # Invalid
                "min_instances_for_training": 5,
                "schema_names": ["sentiment"]
            }
        }
        with pytest.raises(ConfigValidationError):
            validate_active_learning_config(config)

    def test_negative_min_instances(self):
        """Test that negative min_instances_for_training raises a validation error."""
        config = {
            "active_learning": {
                "enabled": True,
                "classifier": {"name": "sklearn.linear_model.LogisticRegression"},
                "vectorizer": {"name": "sklearn.feature_extraction.text.CountVectorizer"},
                "min_annotations_per_instance": 1,
                "min_instances_for_training": -5,  # Invalid
                "schema_names": ["sentiment"]
            }
        }
        with pytest.raises(ConfigValidationError):
            validate_active_learning_config(config)

    def test_empty_schema_names(self):
        """Test that empty schema_names raises a validation error."""
        config = {
            "active_learning": {
                "enabled": True,
                "classifier": {"name": "sklearn.linear_model.LogisticRegression"},
                "vectorizer": {"name": "sklearn.feature_extraction.text.CountVectorizer"},
                "min_annotations_per_instance": 1,
                "min_instances_for_training": 5,
                "schema_names": []  # Empty
            }
        }
        with pytest.raises(ConfigValidationError):
            validate_active_learning_config(config)

    def test_invalid_resolution_strategy(self):
        """Test that invalid resolution strategy raises a validation error."""
        config = {
            "active_learning": {
                "enabled": True,
                "classifier": {"name": "sklearn.linear_model.LogisticRegression"},
                "vectorizer": {"name": "sklearn.feature_extraction.text.CountVectorizer"},
                "min_annotations_per_instance": 1,
                "min_instances_for_training": 5,
                "schema_names": ["sentiment"],
                "resolution_strategy": "invalid_strategy"  # Invalid
            }
        }
        with pytest.raises(ConfigValidationError):
            validate_active_learning_config(config)

    def test_invalid_random_sample_percent(self):
        """Test that invalid random_sample_percent raises a validation error."""
        config = {
            "active_learning": {
                "enabled": True,
                "classifier": {"name": "sklearn.linear_model.LogisticRegression"},
                "vectorizer": {"name": "sklearn.feature_extraction.text.CountVectorizer"},
                "min_annotations_per_instance": 1,
                "min_instances_for_training": 5,
                "schema_names": ["sentiment"],
                "random_sample_percent": 150  # Invalid (> 100)
            }
        }
        with pytest.raises(ConfigValidationError):
            validate_active_learning_config(config)

    def test_invalid_model_retention_count(self):
        """Test that invalid model_retention_count raises a validation error."""
        config = {
            "active_learning": {
                "enabled": True,
                "classifier": {"name": "sklearn.linear_model.LogisticRegression"},
                "vectorizer": {"name": "sklearn.feature_extraction.text.CountVectorizer"},
                "min_annotations_per_instance": 1,
                "min_instances_for_training": 5,
                "schema_names": ["sentiment"],
                "model_persistence_enabled": True,
                "model_retention_count": 0  # Invalid (must be > 0)
            }
        }
        with pytest.raises(ConfigValidationError):
            validate_active_learning_config(config)

    def test_valid_configuration(self):
        """Test that a valid configuration passes validation."""
        config = {
            "active_learning": {
                "enabled": True,
                "classifier": {"name": "sklearn.linear_model.LogisticRegression"},
                "vectorizer": {"name": "sklearn.feature_extraction.text.CountVectorizer"},
                "min_annotations_per_instance": 1,
                "min_instances_for_training": 5,
                "schema_names": ["sentiment"],
                "resolution_strategy": "majority_vote",
                "random_sample_percent": 20.0,
                "update_frequency": 5
            }
        }
        # Should not raise any exception
        validate_active_learning_config(config)

    def test_llm_config_validation(self):
        """Test LLM configuration validation."""
        config = {
            "active_learning": {
                "enabled": True,
                "classifier": {"name": "sklearn.linear_model.LogisticRegression"},
                "vectorizer": {"name": "sklearn.feature_extraction.text.CountVectorizer"},
                "min_annotations_per_instance": 1,
                "min_instances_for_training": 5,
                "schema_names": ["sentiment"],
                "llm_enabled": True,
                "llm_config": {
                    "endpoint_url": "http://localhost:8000",
                    "model_name": "test-model",
                    "timeout": 30,
                    "batch_size": 10
                }
            }
        }
        # Should not raise any exception
        validate_active_learning_config(config)

    def test_invalid_llm_config(self):
        """Test that invalid LLM configuration raises a validation error."""
        config = {
            "active_learning": {
                "enabled": True,
                "classifier": {"name": "sklearn.linear_model.LogisticRegression"},
                "vectorizer": {"name": "sklearn.feature_extraction.text.CountVectorizer"},
                "min_annotations_per_instance": 1,
                "min_instances_for_training": 5,
                "schema_names": ["sentiment"],
                "llm_enabled": True,
                "llm_config": {
                    "endpoint_url": "",  # Invalid empty URL
                    "model_name": "test-model"
                }
            }
        }
        with pytest.raises(ConfigValidationError):
            validate_active_learning_config(config)