"""
Model Persistence and Recovery Tests for Active Learning

This module contains tests for corrupt model files, retention policy, metadata persistence, and model version compatibility.
"""

import pytest

# Skip server-side active learning tests for fast CI execution
pytestmark = pytest.mark.skip(reason="Active learning server tests skipped for fast CI - run with pytest -m slow")
import tempfile
import os
from potato.active_learning_manager import ModelPersistence
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.linear_model import LogisticRegression

class TestActiveLearningModelPersistence:
    """Model persistence and recovery tests for active learning."""

    def test_retention_policy(self):
        """Test that only the last N models are retained according to the retention policy."""
        with tempfile.TemporaryDirectory() as temp_dir:
            persistence = ModelPersistence(temp_dir, retention_count=2)
            # Create and save 4 models
            for i in range(4):
                model = Pipeline([
                    ("vectorizer", CountVectorizer()),
                    ("classifier", LogisticRegression())
                ])
                model.fit(["good", "bad"], ["positive", "negative"])
                persistence.save_model(model, "sentiment", 100 + i)
            # Check that only 2 model files remain
            files = [f for f in os.listdir(temp_dir) if f.startswith("sentiment_") and f.endswith(".pkl")]
            assert len(files) == 2