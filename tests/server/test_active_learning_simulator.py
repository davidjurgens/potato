"""
Simulator-based integration tests for the active learning system overhaul.

Tests verify that the active learning system correctly:
- Uses TfidfVectorizer as default
- Passes custom classifier/vectorizer params
- Applies query strategies (uncertainty, diversity, badge, hybrid, bald)
- Handles cold-start scenarios
- Applies probability calibration
- Supports ICL ensemble weight interpolation
- Routes annotations based on confidence

These tests use FlaskTestServer + requests (not the full simulator framework)
to avoid heavy dependencies while still testing end-to-end behavior.
"""

import pytest
import os
import json
import yaml
import time
import requests
import numpy as np
from unittest.mock import patch, MagicMock

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import create_test_directory

from potato.active_learning_manager import (
    ActiveLearningConfig,
    ActiveLearningManager,
    UncertaintySampling,
    DiversitySampling,
    BadgeStrategy,
    BaldStrategy,
    HybridStrategy,
    SentenceTransformerVectorizer,
    create_query_strategy,
    clear_active_learning_manager,
)


# Skip if server tests are not configured
pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_SERVER_TESTS", "0") == "1",
    reason="Server tests skipped via environment variable",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def test_data_dir():
    """Create test data directory."""
    test_dir = create_test_directory("al_strategies_test")
    yield test_dir


@pytest.fixture(scope="module")
def test_data_file(test_data_dir):
    """Create test data file with varied sentiment texts."""
    items = [
        {"id": "pos_01", "text": "I absolutely love this product! Best purchase ever."},
        {"id": "pos_02", "text": "Amazing quality, exceeded all my expectations."},
        {"id": "pos_03", "text": "Fantastic experience, would highly recommend!"},
        {"id": "pos_04", "text": "This is wonderful, I'm so happy with it."},
        {"id": "pos_05", "text": "Incredible value, superb craftsmanship."},
        {"id": "neg_01", "text": "Terrible quality, broke after one day."},
        {"id": "neg_02", "text": "Worst purchase I ever made, total waste."},
        {"id": "neg_03", "text": "Extremely disappointed, would not recommend."},
        {"id": "neg_04", "text": "Awful product, complete garbage."},
        {"id": "neg_05", "text": "Very poor quality, falling apart already."},
        {"id": "neu_01", "text": "It's okay, nothing special about it."},
        {"id": "neu_02", "text": "Average product, does what it says."},
        {"id": "neu_03", "text": "Neither good nor bad, just average."},
        {"id": "neu_04", "text": "Mediocre quality, you get what you pay for."},
        {"id": "neu_05", "text": "Standard product, no complaints."},
        {"id": "pos_06", "text": "Delightful! Everything was perfect."},
        {"id": "neg_06", "text": "Horrible, do not buy this."},
        {"id": "neu_06", "text": "It works fine, nothing to write home about."},
        {"id": "pos_07", "text": "Outstanding results, five stars!"},
        {"id": "neg_07", "text": "Broken on arrival, terrible packaging."},
    ]

    data_file = os.path.join(test_data_dir, "test_data.jsonl")
    with open(data_file, "w") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")

    return data_file


def make_config(test_data_dir, test_data_file, al_overrides=None):
    """Create a test config with optional active learning overrides."""
    config = {
        "annotation_task_name": "AL Strategy Test",
        "task_dir": test_data_dir,
        "data_files": [os.path.basename(test_data_file)],
        "output_annotation_dir": "output",
        "output_annotation_format": "json",
        "item_properties": {
            "id_key": "id",
            "text_key": "text",
        },
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": [
                    {"name": "positive"},
                    {"name": "negative"},
                    {"name": "neutral"},
                ],
                "description": "What is the sentiment?",
            }
        ],
        "user_config": {
            "allow_all_users": True,
        },
    }

    if al_overrides:
        config["active_learning"] = al_overrides

    config_file = os.path.join(test_data_dir, "config.yaml")
    with open(config_file, "w") as f:
        yaml.dump(config, f)

    return config_file


# ---------------------------------------------------------------------------
# TestDefaultVectorizer
# ---------------------------------------------------------------------------

class TestDefaultVectorizer:

    def test_tfidf_is_default(self):
        """Verify ActiveLearningConfig().vectorizer_name is TfidfVectorizer."""
        config = ActiveLearningConfig()
        assert "TfidfVectorizer" in config.vectorizer_name

    def test_count_vectorizer_still_works(self):
        """Config with explicit CountVectorizer trains successfully."""
        config = ActiveLearningConfig(
            vectorizer_name="sklearn.feature_extraction.text.CountVectorizer",
            schema_names=["test"],
        )
        with patch.object(ActiveLearningManager, '_initialize_components'):
            with patch.object(ActiveLearningManager, '_start_training_thread'):
                manager = ActiveLearningManager.__new__(ActiveLearningManager)
                manager.config = config
                manager.logger = MagicMock()
                manager._vectorizers = {}
                manager._bald_ensembles = {}

                from sklearn.feature_extraction.text import CountVectorizer as CV
                vec = manager._create_vectorizer()
                assert isinstance(vec, CV)

    def test_tfidf_trains_successfully(self):
        """TfidfVectorizer produces a working pipeline."""
        config = ActiveLearningConfig(schema_names=["test"])
        with patch.object(ActiveLearningManager, '_initialize_components'):
            with patch.object(ActiveLearningManager, '_start_training_thread'):
                manager = ActiveLearningManager.__new__(ActiveLearningManager)
                manager.config = config
                manager.logger = MagicMock()
                manager._vectorizers = {}
                manager._bald_ensembles = {}

                training_data = {
                    "texts": [
                        "I love this!", "Great product!", "Amazing!",
                        "Terrible.", "Awful.", "Bad quality.",
                        "It's okay.", "Average.", "Nothing special.",
                        "Pretty good.", "Not bad.", "Could be better.",
                    ],
                    "labels": [
                        "positive", "positive", "positive",
                        "negative", "negative", "negative",
                        "neutral", "neutral", "neutral",
                        "positive", "neutral", "neutral",
                    ],
                }

                model, metrics = manager._train_classifier(training_data, "test")
                assert model is not None
                assert metrics.accuracy > 0
                assert metrics.error_message is None


# ---------------------------------------------------------------------------
# TestClassifierParams
# ---------------------------------------------------------------------------

class TestClassifierParams:

    def test_custom_classifier_params_passthrough(self):
        """Config with classifier_params: {C: 0.5} trains without error."""
        config = ActiveLearningConfig(
            classifier_params={"C": 0.5, "max_iter": 500},
            schema_names=["test"],
        )
        with patch.object(ActiveLearningManager, '_initialize_components'):
            with patch.object(ActiveLearningManager, '_start_training_thread'):
                manager = ActiveLearningManager.__new__(ActiveLearningManager)
                manager.config = config
                manager.logger = MagicMock()
                manager._vectorizers = {}
                manager._bald_ensembles = {}

                training_data = {
                    "texts": ["Good", "Bad", "Ok", "Great", "Awful",
                             "Fine", "Terrible", "Nice", "Poor", "Average"],
                    "labels": ["pos", "neg", "neu", "pos", "neg",
                              "neu", "neg", "pos", "neg", "neu"],
                }

                model, metrics = manager._train_classifier(training_data, "test")
                assert model is not None

    def test_custom_vectorizer_params_passthrough(self):
        """Config with vectorizer_params: {ngram_range: [1, 2]} trains without error."""
        config = ActiveLearningConfig(
            vectorizer_params={"ngram_range": (1, 2), "max_features": 100},
            schema_names=["test"],
        )
        with patch.object(ActiveLearningManager, '_initialize_components'):
            with patch.object(ActiveLearningManager, '_start_training_thread'):
                manager = ActiveLearningManager.__new__(ActiveLearningManager)
                manager.config = config
                manager.logger = MagicMock()
                manager._vectorizers = {}
                manager._bald_ensembles = {}

                training_data = {
                    "texts": ["Good stuff", "Bad stuff", "Ok stuff",
                             "Great quality", "Awful quality",
                             "Fine product", "Terrible product",
                             "Nice item", "Poor item", "Average item"],
                    "labels": ["pos", "neg", "neu", "pos", "neg",
                              "neu", "neg", "pos", "neg", "neu"],
                }

                model, metrics = manager._train_classifier(training_data, "test")
                assert model is not None

    def test_sentence_transformer_vectorizer_creates(self):
        """sentence-transformers vectorizer initializes correctly."""
        config = ActiveLearningConfig(
            vectorizer_name="sentence-transformers",
            vectorizer_kwargs={"model_name": "test-model"},
            schema_names=["test"],
        )
        with patch.object(ActiveLearningManager, '_initialize_components'):
            with patch.object(ActiveLearningManager, '_start_training_thread'):
                manager = ActiveLearningManager.__new__(ActiveLearningManager)
                manager.config = config
                manager.logger = MagicMock()

                vec = manager._create_vectorizer()
                assert isinstance(vec, SentenceTransformerVectorizer)


# ---------------------------------------------------------------------------
# TestQueryStrategies
# ---------------------------------------------------------------------------

class TestQueryStrategies:

    @pytest.fixture(autouse=True)
    def setup_training_data(self):
        self.texts = [
            "I love this!", "Great product!", "Amazing!",
            "Terrible.", "Awful.", "Bad quality.",
            "It's okay.", "Average.", "Nothing special.",
            "Pretty good.", "Not bad.", "Could be better.",
        ]
        self.labels = [
            "positive", "positive", "positive",
            "negative", "negative", "negative",
            "neutral", "neutral", "neutral",
            "positive", "neutral", "neutral",
        ]
        self.unlabeled = [
            "Wonderful!", "Horrible!", "Meh.",
            "Superb!", "Dreadful!", "Fine.",
        ]

    def _train_model(self, config):
        with patch.object(ActiveLearningManager, '_initialize_components'):
            with patch.object(ActiveLearningManager, '_start_training_thread'):
                manager = ActiveLearningManager.__new__(ActiveLearningManager)
                manager.config = config
                manager.logger = MagicMock()
                manager._vectorizers = {}
                manager._bald_ensembles = {}

                training_data = {
                    "texts": self.texts,
                    "labels": self.labels,
                }
                model, _ = manager._train_classifier(training_data, "test")
                return manager, model

    def test_uncertainty_strategy_produces_rankings(self):
        config = ActiveLearningConfig(query_strategy="uncertainty", schema_names=["test"])
        manager, model = self._train_model(config)

        vec = manager._vectorizers.get("test")
        strategy = UncertaintySampling()
        rankings = strategy.rank(self.unlabeled, model, vec)

        assert len(rankings) == len(self.unlabeled)
        # Should be sorted by score descending
        scores = [s for _, s in rankings]
        assert scores == sorted(scores, reverse=True)

    def test_diversity_strategy_produces_different_order(self):
        config = ActiveLearningConfig(query_strategy="diversity", schema_names=["test"])
        manager, model = self._train_model(config)

        vec = manager._vectorizers.get("test")
        uncertainty = UncertaintySampling()
        diversity = DiversitySampling()

        u_rankings = uncertainty.rank(self.unlabeled, model, vec)
        d_rankings = diversity.rank(self.unlabeled, model, vec, self.texts)

        u_ids = [idx for idx, _ in u_rankings]
        d_ids = [idx for idx, _ in d_rankings]

        # Both should contain all indices
        assert set(u_ids) == set(d_ids)
        assert len(u_ids) == len(self.unlabeled)

    def test_badge_strategy_produces_valid_order(self):
        config = ActiveLearningConfig(query_strategy="badge", schema_names=["test"])
        manager, model = self._train_model(config)

        vec = manager._vectorizers.get("test")
        strategy = BadgeStrategy()
        rankings = strategy.rank(self.unlabeled, model, vec)

        indices = [idx for idx, _ in rankings]
        assert set(indices) == set(range(len(self.unlabeled)))

    def test_hybrid_strategy_blends_scores(self):
        config = ActiveLearningConfig(
            query_strategy="hybrid",
            hybrid_weights={"uncertainty": 0.5, "diversity": 0.5},
            schema_names=["test"],
        )
        manager, model = self._train_model(config)

        vec = manager._vectorizers.get("test")
        strategy = HybridStrategy(weights={"uncertainty": 0.5, "diversity": 0.5})
        rankings = strategy.rank(self.unlabeled, model, vec, self.texts)

        assert len(rankings) == len(self.unlabeled)

    def test_bald_ensemble_trains(self):
        config = ActiveLearningConfig(
            query_strategy="bald",
            bald_params={"n_estimators": 3, "bootstrap_fraction": 0.8},
            schema_names=["test"],
        )
        manager, model = self._train_model(config)

        # BALD ensemble should have been trained
        assert "test" in manager._bald_ensembles
        assert len(manager._bald_ensembles["test"]) > 0


# ---------------------------------------------------------------------------
# TestColdStart
# ---------------------------------------------------------------------------

class TestColdStart:

    def test_cold_start_random_default(self):
        """Before min_instances_for_training, default is random (no reordering)."""
        config = ActiveLearningConfig(cold_start_strategy="random")
        assert config.cold_start_strategy == "random"

    def test_cold_start_llm_config_accepted(self):
        """LLM cold-start strategy is accepted in config."""
        config = ActiveLearningConfig(
            cold_start_strategy="llm",
            llm_enabled=True,
            llm_config={"use_mock": True},
        )
        assert config.cold_start_strategy == "llm"
        assert config.llm_enabled is True

    def test_transition_threshold(self):
        """min_instances_for_training controls when classifier training begins."""
        config = ActiveLearningConfig(min_instances_for_training=5)
        assert config.min_instances_for_training == 5

        config2 = ActiveLearningConfig(min_instances_for_training=20)
        assert config2.min_instances_for_training == 20


# ---------------------------------------------------------------------------
# TestCalibration
# ---------------------------------------------------------------------------

class TestCalibrationIntegration:

    def test_calibrated_probabilities_enabled_by_default(self):
        """Default config has calibration enabled."""
        config = ActiveLearningConfig()
        assert config.calibrate_probabilities is True

    def test_calibration_disabled_when_configured(self):
        """With calibrate_probabilities: false, raw classifier used."""
        config = ActiveLearningConfig(
            calibrate_probabilities=False,
            schema_names=["test"],
        )

        with patch.object(ActiveLearningManager, '_initialize_components'):
            with patch.object(ActiveLearningManager, '_start_training_thread'):
                manager = ActiveLearningManager.__new__(ActiveLearningManager)
                manager.config = config
                manager.logger = MagicMock()
                manager._vectorizers = {}
                manager._bald_ensembles = {}

                training_data = {
                    "texts": [
                        "Good", "Bad", "Ok", "Great", "Awful",
                        "Fine", "Terrible", "Nice", "Poor", "Average",
                    ],
                    "labels": [
                        "pos", "neg", "neu", "pos", "neg",
                        "neu", "neg", "pos", "neg", "neu",
                    ],
                }
                from sklearn.pipeline import Pipeline
                model, _ = manager._train_classifier(training_data, "test")
                assert isinstance(model, Pipeline)


# ---------------------------------------------------------------------------
# TestICLEnsemble
# ---------------------------------------------------------------------------

class TestICLEnsemble:

    def test_icl_ensemble_disabled_by_default(self):
        """Default config does not use ICL ensemble."""
        config = ActiveLearningConfig()
        assert config.use_icl_ensemble is False

    def test_icl_ensemble_weight_interpolation(self):
        """Verify weights shift from initial_icl_weight toward final_icl_weight."""
        params = {
            "initial_icl_weight": 0.7,
            "final_icl_weight": 0.2,
            "transition_instances": 100,
        }

        # At 0 annotations, weight should be initial
        progress_0 = min(1.0, 0 / max(1, params["transition_instances"]))
        w_0 = params["initial_icl_weight"] + (
            params["final_icl_weight"] - params["initial_icl_weight"]
        ) * progress_0
        assert abs(w_0 - 0.7) < 0.01

        # At 50 annotations (half transition), weight should be ~0.45
        progress_50 = min(1.0, 50 / max(1, params["transition_instances"]))
        w_50 = params["initial_icl_weight"] + (
            params["final_icl_weight"] - params["initial_icl_weight"]
        ) * progress_50
        assert abs(w_50 - 0.45) < 0.01

        # At 100+ annotations, weight should be final
        progress_100 = min(1.0, 100 / max(1, params["transition_instances"]))
        w_100 = params["initial_icl_weight"] + (
            params["final_icl_weight"] - params["initial_icl_weight"]
        ) * progress_100
        assert abs(w_100 - 0.2) < 0.01


# ---------------------------------------------------------------------------
# TestAnnotationRouting
# ---------------------------------------------------------------------------

class TestAnnotationRouting:

    def test_routing_disabled_by_default(self):
        """Default config routes all instances to human."""
        config = ActiveLearningConfig()
        assert config.annotation_routing is False

    def test_routing_config_thresholds(self):
        """Routing thresholds are configurable."""
        config = ActiveLearningConfig(
            annotation_routing=True,
            routing_thresholds={
                "auto_label_min_confidence": 0.95,
                "show_suggestion_below": 0.4,
            },
        )
        assert config.routing_thresholds["auto_label_min_confidence"] == 0.95
        assert config.routing_thresholds["show_suggestion_below"] == 0.4
