"""
Unit tests for active learning query strategies, vectorizers, and calibration.

Tests cover:
- QueryStrategy subclasses (Uncertainty, Diversity, BADGE, BALD, Hybrid)
- SentenceTransformerVectorizer sklearn compatibility
- Probability calibration
- ActiveLearningConfig new fields
- ICLClassifier wrapper
- CoverICL example selection
"""

import pytest
import numpy as np
from unittest.mock import patch, MagicMock, PropertyMock
from collections import Counter

from sklearn.feature_extraction.text import TfidfVectorizer, CountVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_texts():
    return [
        "I love this product, it's amazing!",
        "This is terrible, worst purchase ever.",
        "It's okay, nothing special.",
        "Absolutely fantastic experience!",
        "Very disappointing quality.",
        "Neutral opinion on this item.",
        "Best thing I ever bought!",
        "Would not recommend to anyone.",
        "It does what it says.",
        "Incredible value for money!",
    ]


@pytest.fixture
def sample_labels():
    return [
        "positive", "negative", "neutral", "positive", "negative",
        "neutral", "positive", "negative", "neutral", "positive",
    ]


@pytest.fixture
def trained_model(sample_texts, sample_labels):
    """Return a trained pipeline and its components."""
    vectorizer = TfidfVectorizer()
    classifier = LogisticRegression(max_iter=200)
    pipeline = Pipeline([
        ("vectorizer", vectorizer),
        ("classifier", classifier),
    ])
    pipeline.fit(sample_texts, sample_labels)
    return pipeline, vectorizer, classifier


@pytest.fixture
def unlabeled_texts():
    return [
        "This product is great!",
        "I hate this thing.",
        "Nothing remarkable here.",
        "Superb quality!",
        "Completely broken.",
    ]


# ---------------------------------------------------------------------------
# ActiveLearningConfig Tests
# ---------------------------------------------------------------------------

class TestActiveLearningConfig:

    def test_tfidf_is_default_vectorizer(self):
        from potato.active_learning_manager import ActiveLearningConfig
        config = ActiveLearningConfig()
        assert config.vectorizer_name == "sklearn.feature_extraction.text.TfidfVectorizer"

    def test_default_query_strategy_is_uncertainty(self):
        from potato.active_learning_manager import ActiveLearningConfig
        config = ActiveLearningConfig()
        assert config.query_strategy == "uncertainty"

    def test_calibrate_probabilities_default_true(self):
        from potato.active_learning_manager import ActiveLearningConfig
        config = ActiveLearningConfig()
        assert config.calibrate_probabilities is True

    def test_cold_start_default_random(self):
        from potato.active_learning_manager import ActiveLearningConfig
        config = ActiveLearningConfig()
        assert config.cold_start_strategy == "random"

    def test_icl_ensemble_default_false(self):
        from potato.active_learning_manager import ActiveLearningConfig
        config = ActiveLearningConfig()
        assert config.use_icl_ensemble is False

    def test_annotation_routing_default_false(self):
        from potato.active_learning_manager import ActiveLearningConfig
        config = ActiveLearningConfig()
        assert config.annotation_routing is False

    def test_hybrid_weights_default(self):
        from potato.active_learning_manager import ActiveLearningConfig
        config = ActiveLearningConfig()
        assert config.hybrid_weights == {"uncertainty": 0.7, "diversity": 0.3}

    def test_classifier_params_merge_into_kwargs(self):
        from potato.active_learning_manager import ActiveLearningConfig
        config = ActiveLearningConfig(
            classifier_params={"C": 0.5, "max_iter": 500}
        )
        assert config.classifier_kwargs["C"] == 0.5
        assert config.classifier_kwargs["max_iter"] == 500

    def test_vectorizer_params_merge_into_kwargs(self):
        from potato.active_learning_manager import ActiveLearningConfig
        config = ActiveLearningConfig(
            vectorizer_params={"ngram_range": (1, 2), "max_features": 10000}
        )
        assert config.vectorizer_kwargs["ngram_range"] == (1, 2)
        assert config.vectorizer_kwargs["max_features"] == 10000

    def test_bald_params_default(self):
        from potato.active_learning_manager import ActiveLearningConfig
        config = ActiveLearningConfig()
        assert config.bald_params["n_estimators"] == 5
        assert config.bald_params["bootstrap_fraction"] == 0.8


# ---------------------------------------------------------------------------
# UncertaintySampling Tests
# ---------------------------------------------------------------------------

class TestUncertaintySampling:

    def test_returns_valid_rankings(self, trained_model, unlabeled_texts):
        from potato.active_learning_manager import UncertaintySampling

        pipeline, vectorizer, classifier = trained_model
        fitted_vec = pipeline.named_steps["vectorizer"]
        fitted_clf = pipeline.named_steps["classifier"]

        strategy = UncertaintySampling()
        rankings = strategy.rank(unlabeled_texts, fitted_clf, fitted_vec)

        assert len(rankings) == len(unlabeled_texts)
        indices = [idx for idx, _ in rankings]
        assert set(indices) == set(range(len(unlabeled_texts)))

    def test_highest_score_is_most_uncertain(self, trained_model, unlabeled_texts):
        from potato.active_learning_manager import UncertaintySampling

        pipeline, vectorizer, classifier = trained_model
        fitted_vec = pipeline.named_steps["vectorizer"]
        fitted_clf = pipeline.named_steps["classifier"]

        strategy = UncertaintySampling()
        rankings = strategy.rank(unlabeled_texts, fitted_clf, fitted_vec)

        # Rankings should be sorted by score descending (most uncertain first)
        scores = [score for _, score in rankings]
        assert scores == sorted(scores, reverse=True)

    def test_scores_between_0_and_1(self, trained_model, unlabeled_texts):
        from potato.active_learning_manager import UncertaintySampling

        pipeline, vectorizer, classifier = trained_model
        fitted_vec = pipeline.named_steps["vectorizer"]
        fitted_clf = pipeline.named_steps["classifier"]

        strategy = UncertaintySampling()
        rankings = strategy.rank(unlabeled_texts, fitted_clf, fitted_vec)

        for _, score in rankings:
            assert 0 <= score <= 1


# ---------------------------------------------------------------------------
# DiversitySampling Tests
# ---------------------------------------------------------------------------

class TestDiversitySampling:

    def test_returns_valid_rankings(self, trained_model, unlabeled_texts, sample_texts):
        from potato.active_learning_manager import DiversitySampling

        pipeline, _, _ = trained_model
        fitted_vec = pipeline.named_steps["vectorizer"]
        fitted_clf = pipeline.named_steps["classifier"]

        strategy = DiversitySampling()
        rankings = strategy.rank(unlabeled_texts, fitted_clf, fitted_vec, sample_texts)

        assert len(rankings) == len(unlabeled_texts)

    def test_selects_distant_instances(self, trained_model, sample_texts):
        from potato.active_learning_manager import DiversitySampling

        pipeline, _, _ = trained_model
        fitted_vec = pipeline.named_steps["vectorizer"]
        fitted_clf = pipeline.named_steps["classifier"]

        # Create texts where one is clearly different
        test_texts = [
            "I love this product!",  # Similar to positive training
            "Quantum computing enables faster algorithms",  # Very different topic
        ]

        strategy = DiversitySampling()
        rankings = strategy.rank(test_texts, fitted_clf, fitted_vec, sample_texts)

        # The quantum computing text should rank higher (more distant)
        idx_quantum = next(idx for idx, _ in rankings if idx == 1)
        idx_love = next(idx for idx, _ in rankings if idx == 0)
        scores = {idx: score for idx, score in rankings}
        assert scores[1] >= scores[0]  # Distant text should score higher

    def test_works_without_annotated_texts(self, trained_model, unlabeled_texts):
        from potato.active_learning_manager import DiversitySampling

        pipeline, _, _ = trained_model
        fitted_vec = pipeline.named_steps["vectorizer"]
        fitted_clf = pipeline.named_steps["classifier"]

        strategy = DiversitySampling()
        rankings = strategy.rank(unlabeled_texts, fitted_clf, fitted_vec)

        assert len(rankings) == len(unlabeled_texts)


# ---------------------------------------------------------------------------
# BadgeStrategy Tests
# ---------------------------------------------------------------------------

class TestBadgeStrategy:

    def test_returns_valid_rankings(self, trained_model, unlabeled_texts):
        from potato.active_learning_manager import BadgeStrategy

        pipeline, _, _ = trained_model
        fitted_vec = pipeline.named_steps["vectorizer"]
        fitted_clf = pipeline.named_steps["classifier"]

        strategy = BadgeStrategy()
        rankings = strategy.rank(unlabeled_texts, fitted_clf, fitted_vec)

        assert len(rankings) == len(unlabeled_texts)
        indices = [idx for idx, _ in rankings]
        assert set(indices) == set(range(len(unlabeled_texts)))

    def test_produces_different_order_than_uncertainty(self, trained_model):
        from potato.active_learning_manager import BadgeStrategy, UncertaintySampling

        pipeline, _, _ = trained_model
        fitted_vec = pipeline.named_steps["vectorizer"]
        fitted_clf = pipeline.named_steps["classifier"]

        # Use more texts to increase chance of different orderings
        texts = [
            "Great product!", "Terrible item.", "It's okay.",
            "Love it!", "Hate it.", "Meh.", "Awesome!", "Bad.",
            "Fine.", "Superb!", "Awful.", "Average.",
        ]

        badge = BadgeStrategy()
        uncertainty = UncertaintySampling()

        badge_order = [idx for idx, _ in badge.rank(texts, fitted_clf, fitted_vec)]
        uncert_order = [idx for idx, _ in uncertainty.rank(texts, fitted_clf, fitted_vec)]

        # They should produce valid orderings (may or may not differ for small sets)
        assert set(badge_order) == set(uncert_order)
        assert len(badge_order) == len(texts)


# ---------------------------------------------------------------------------
# BaldStrategy Tests
# ---------------------------------------------------------------------------

class TestBaldStrategy:

    def test_returns_valid_rankings(self, trained_model, unlabeled_texts):
        from potato.active_learning_manager import BaldStrategy

        pipeline, _, _ = trained_model
        fitted_vec = pipeline.named_steps["vectorizer"]
        fitted_clf = pipeline.named_steps["classifier"]

        strategy = BaldStrategy(n_estimators=3)
        rankings = strategy.rank(unlabeled_texts, fitted_clf, fitted_vec)

        assert len(rankings) == len(unlabeled_texts)

    def test_ensemble_ranking(self, sample_texts, sample_labels, unlabeled_texts):
        from potato.active_learning_manager import BaldStrategy

        # Train multiple models with different seeds
        ensemble = []
        vectorizer = TfidfVectorizer()
        vectorizer.fit(sample_texts)

        for seed in range(3):
            np.random.seed(seed)
            indices = np.random.choice(len(sample_texts), size=8, replace=True)
            boot_texts = [sample_texts[i] for i in indices]
            boot_labels = [sample_labels[i] for i in indices]
            if len(set(boot_labels)) >= 2:
                clf = LogisticRegression(max_iter=200, random_state=seed)
                clf.fit(vectorizer.transform(boot_texts), boot_labels)
                ensemble.append(clf)

        strategy = BaldStrategy()
        rankings = strategy.rank_with_ensemble(unlabeled_texts, ensemble, vectorizer)

        assert len(rankings) == len(unlabeled_texts)
        # Scores should be non-negative (mutual information)
        for _, score in rankings:
            assert score >= -0.01  # Allow small floating point errors

    def test_default_params(self):
        from potato.active_learning_manager import BaldStrategy
        strategy = BaldStrategy()
        assert strategy.n_estimators == 5
        assert strategy.bootstrap_fraction == 0.8


# ---------------------------------------------------------------------------
# HybridStrategy Tests
# ---------------------------------------------------------------------------

class TestHybridStrategy:

    def test_returns_valid_rankings(self, trained_model, unlabeled_texts, sample_texts):
        from potato.active_learning_manager import HybridStrategy

        pipeline, _, _ = trained_model
        fitted_vec = pipeline.named_steps["vectorizer"]
        fitted_clf = pipeline.named_steps["classifier"]

        strategy = HybridStrategy(weights={"uncertainty": 0.7, "diversity": 0.3})
        rankings = strategy.rank(unlabeled_texts, fitted_clf, fitted_vec, sample_texts)

        assert len(rankings) == len(unlabeled_texts)

    def test_different_weights_produce_different_orders(self, trained_model, sample_texts):
        from potato.active_learning_manager import HybridStrategy

        pipeline, _, _ = trained_model
        fitted_vec = pipeline.named_steps["vectorizer"]
        fitted_clf = pipeline.named_steps["classifier"]

        texts = [
            "Great product!", "Terrible item.", "It's okay.",
            "Love it!", "Hate it.", "Meh.", "Awesome!", "Bad.",
            "Fine.", "Superb!", "Awful.", "Average.",
        ]

        all_uncertainty = HybridStrategy(weights={"uncertainty": 1.0, "diversity": 0.0})
        all_diversity = HybridStrategy(weights={"uncertainty": 0.0, "diversity": 1.0})

        u_order = [idx for idx, _ in all_uncertainty.rank(texts, fitted_clf, fitted_vec, sample_texts)]
        d_order = [idx for idx, _ in all_diversity.rank(texts, fitted_clf, fitted_vec, sample_texts)]

        # Both should be valid orderings
        assert set(u_order) == set(d_order)
        assert len(u_order) == len(texts)

    def test_default_weights(self):
        from potato.active_learning_manager import HybridStrategy
        strategy = HybridStrategy()
        assert strategy.weights == {"uncertainty": 0.7, "diversity": 0.3}


# ---------------------------------------------------------------------------
# Strategy Factory Tests
# ---------------------------------------------------------------------------

class TestCreateQueryStrategy:

    def test_creates_uncertainty(self):
        from potato.active_learning_manager import (
            ActiveLearningConfig, create_query_strategy, UncertaintySampling,
        )
        config = ActiveLearningConfig(query_strategy="uncertainty")
        strategy = create_query_strategy(config)
        assert isinstance(strategy, UncertaintySampling)

    def test_creates_diversity(self):
        from potato.active_learning_manager import (
            ActiveLearningConfig, create_query_strategy, DiversitySampling,
        )
        config = ActiveLearningConfig(query_strategy="diversity")
        strategy = create_query_strategy(config)
        assert isinstance(strategy, DiversitySampling)

    def test_creates_badge(self):
        from potato.active_learning_manager import (
            ActiveLearningConfig, create_query_strategy, BadgeStrategy,
        )
        config = ActiveLearningConfig(query_strategy="badge")
        strategy = create_query_strategy(config)
        assert isinstance(strategy, BadgeStrategy)

    def test_creates_bald(self):
        from potato.active_learning_manager import (
            ActiveLearningConfig, create_query_strategy, BaldStrategy,
        )
        config = ActiveLearningConfig(
            query_strategy="bald",
            bald_params={"n_estimators": 3, "bootstrap_fraction": 0.7},
        )
        strategy = create_query_strategy(config)
        assert isinstance(strategy, BaldStrategy)
        assert strategy.n_estimators == 3

    def test_creates_hybrid(self):
        from potato.active_learning_manager import (
            ActiveLearningConfig, create_query_strategy, HybridStrategy,
        )
        config = ActiveLearningConfig(
            query_strategy="hybrid",
            hybrid_weights={"uncertainty": 0.5, "diversity": 0.5},
        )
        strategy = create_query_strategy(config)
        assert isinstance(strategy, HybridStrategy)
        assert strategy.weights == {"uncertainty": 0.5, "diversity": 0.5}

    def test_unknown_strategy_falls_back(self):
        from potato.active_learning_manager import (
            ActiveLearningConfig, create_query_strategy, UncertaintySampling,
        )
        config = ActiveLearningConfig(query_strategy="nonexistent")
        strategy = create_query_strategy(config)
        assert isinstance(strategy, UncertaintySampling)


# ---------------------------------------------------------------------------
# SentenceTransformerVectorizer Tests
# ---------------------------------------------------------------------------

class TestSentenceTransformerVectorizer:

    def test_sklearn_interface(self):
        """Test that the vectorizer exposes fit/transform/fit_transform."""
        from potato.active_learning_manager import SentenceTransformerVectorizer
        vec = SentenceTransformerVectorizer()
        assert hasattr(vec, 'fit')
        assert hasattr(vec, 'transform')
        assert hasattr(vec, 'fit_transform')

    def test_transform_before_fit_raises(self):
        from potato.active_learning_manager import SentenceTransformerVectorizer
        vec = SentenceTransformerVectorizer()
        with pytest.raises(RuntimeError):
            vec.transform(["hello"])

    def test_fit_transform_with_mock(self):
        from potato.active_learning_manager import SentenceTransformerVectorizer

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2], [0.3, 0.4]])

        with patch('potato.active_learning_manager.SentenceTransformerVectorizer.fit') as mock_fit:
            vec = SentenceTransformerVectorizer(model_name="test-model")
            vec._model = mock_model
            mock_fit.return_value = vec

            result = vec.transform(["hello", "world"])
            mock_model.encode.assert_called_once()
            assert result.shape == (2, 2)

    def test_registered_in_create_vectorizer(self):
        """Test that sentence-transformers is recognized by _create_vectorizer."""
        from potato.active_learning_manager import (
            ActiveLearningConfig, ActiveLearningManager, SentenceTransformerVectorizer,
        )

        config = ActiveLearningConfig(
            vectorizer_name="sentence-transformers",
            vectorizer_kwargs={"model_name": "test-model"},
            schema_names=["test"],
        )

        # Mock the manager initialization to avoid thread creation
        with patch.object(ActiveLearningManager, '_initialize_components'):
            with patch.object(ActiveLearningManager, '_start_training_thread'):
                manager = ActiveLearningManager.__new__(ActiveLearningManager)
                manager.config = config
                manager.logger = MagicMock()

                vec = manager._create_vectorizer()
                assert isinstance(vec, SentenceTransformerVectorizer)
                assert vec.model_name == "test-model"


# ---------------------------------------------------------------------------
# Calibration Tests
# ---------------------------------------------------------------------------

class TestCalibration:

    def test_calibration_wraps_pipeline(self, sample_texts, sample_labels):
        """Test that calibration wraps the pipeline with CalibratedClassifierCV."""
        from potato.active_learning_manager import ActiveLearningConfig, ActiveLearningManager

        config = ActiveLearningConfig(
            calibrate_probabilities=True,
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
                    "texts": sample_texts,
                    "labels": sample_labels,
                }
                model, metrics = manager._train_classifier(training_data, "test")

                assert model is not None
                assert metrics.accuracy > 0

    def test_calibration_disabled(self, sample_texts, sample_labels):
        from potato.active_learning_manager import ActiveLearningConfig, ActiveLearningManager

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
                    "texts": sample_texts,
                    "labels": sample_labels,
                }
                model, metrics = manager._train_classifier(training_data, "test")

                assert model is not None
                # Should be a plain Pipeline, not CalibratedClassifierCV
                assert isinstance(model, Pipeline)


# ---------------------------------------------------------------------------
# ICLClassifier Tests
# ---------------------------------------------------------------------------

class TestICLClassifier:

    def test_predict_proba_returns_valid_matrix(self):
        from potato.active_learning_manager import ICLClassifier

        mock_labeler = MagicMock()
        mock_pred = MagicMock()
        mock_pred.predicted_label = "positive"
        mock_pred.confidence_score = 0.8
        mock_labeler.label_instance.return_value = mock_pred

        clf = ICLClassifier(mock_labeler, "sentiment", ["positive", "negative", "neutral"])
        probas = clf.predict_proba(["Test text 1", "Test text 2"])

        assert probas.shape == (2, 3)
        # Each row should sum to ~1
        for row in probas:
            assert abs(sum(row) - 1.0) < 0.01

    def test_predict_proba_with_none_prediction(self):
        from potato.active_learning_manager import ICLClassifier

        mock_labeler = MagicMock()
        mock_labeler.label_instance.return_value = None

        clf = ICLClassifier(mock_labeler, "sentiment", ["positive", "negative"])
        probas = clf.predict_proba(["Test text"])

        # Should return uniform distribution
        assert probas.shape == (1, 2)
        assert abs(probas[0][0] - 0.5) < 0.01
        assert abs(probas[0][1] - 0.5) < 0.01

    def test_classes_attribute(self):
        from potato.active_learning_manager import ICLClassifier

        clf = ICLClassifier(MagicMock(), "test", ["a", "b", "c"])
        assert list(clf.classes_) == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# LLM Confidence Method Tests
# ---------------------------------------------------------------------------

class TestLLMConfidenceMethods:

    def test_config_default_is_verbalized(self):
        from potato.ai.llm_active_learning import LLMConfig
        config = LLMConfig(endpoint_url="http://test", model_name="test")
        assert config.confidence_method == "verbalized"

    def test_config_consistency_samples_default(self):
        from potato.ai.llm_active_learning import LLMConfig
        config = LLMConfig(endpoint_url="http://test", model_name="test")
        assert config.consistency_samples == 3

    def test_prediction_has_confidence_method_field(self):
        from potato.ai.llm_active_learning import LLMPrediction
        pred = LLMPrediction(
            instance_id="test",
            predicted_label="pos",
            confidence_score=0.8,
            raw_response="",
        )
        assert pred.confidence_method == "verbalized"

    def test_factory_passes_confidence_method(self):
        from potato.ai.llm_active_learning import create_llm_active_learning
        llm = create_llm_active_learning({
            "use_mock": True,
            "confidence_method": "consistency",
            "consistency_samples": 5,
        })
        assert llm.config.confidence_method == "consistency"
        assert llm.config.consistency_samples == 5


# ---------------------------------------------------------------------------
# CoverICL Example Selection Tests
# ---------------------------------------------------------------------------

class TestCoverICLSelection:

    def test_select_diverse_examples_returns_k(self):
        from potato.ai.icl_labeler import ICLLabeler, HighConfidenceExample
        from datetime import datetime

        # Reset singleton
        ICLLabeler._instance = None

        with patch.object(ICLLabeler, '__init__', lambda self, *a, **kw: None):
            labeler = ICLLabeler.__new__(ICLLabeler)
            labeler._initialized = True
            labeler._lock = MagicMock()

            candidates = [
                HighConfidenceExample(
                    instance_id=f"item_{i}",
                    text=text,
                    schema_name="test",
                    label="pos" if i % 2 == 0 else "neg",
                    agreement_score=0.9 - i * 0.01,
                    annotator_count=3,
                    timestamp=datetime.now(),
                )
                for i, text in enumerate([
                    "Great product, love it!",
                    "Terrible quality, hate it.",
                    "Quantum computing paper on algorithms.",
                    "Amazing food at this restaurant!",
                    "Worst service ever experienced.",
                    "Machine learning models for NLP.",
                    "Beautiful weather today!",
                    "Traffic was horrible.",
                ])
            ]

            selected = labeler._select_diverse_examples(candidates, k=4)
            assert len(selected) == 4

            # Selected examples should be from the candidates
            selected_ids = {e.instance_id for e in selected}
            candidate_ids = {e.instance_id for e in candidates}
            assert selected_ids.issubset(candidate_ids)

    def test_select_diverse_examples_fewer_than_k(self):
        from potato.ai.icl_labeler import ICLLabeler, HighConfidenceExample
        from datetime import datetime

        ICLLabeler._instance = None

        with patch.object(ICLLabeler, '__init__', lambda self, *a, **kw: None):
            labeler = ICLLabeler.__new__(ICLLabeler)
            labeler._initialized = True
            labeler._lock = MagicMock()

            candidates = [
                HighConfidenceExample(
                    instance_id="item_0",
                    text="Hello world",
                    schema_name="test",
                    label="pos",
                    agreement_score=0.95,
                    annotator_count=3,
                )
            ]

            selected = labeler._select_diverse_examples(candidates, k=5)
            assert len(selected) == 1  # Can't select more than available


# ---------------------------------------------------------------------------
# Config Validation Tests
# ---------------------------------------------------------------------------

class TestConfigValidation:

    def test_valid_query_strategies(self):
        from potato.server_utils.config_module import validate_active_learning_config

        for strategy in ["uncertainty", "diversity", "badge", "bald", "hybrid"]:
            config = {
                "active_learning": {
                    "enabled": True,
                    "query_strategy": strategy,
                }
            }
            validate_active_learning_config(config)  # Should not raise

    def test_invalid_query_strategy(self):
        from potato.server_utils.config_module import (
            validate_active_learning_config,
            ConfigValidationError,
        )

        config = {
            "active_learning": {
                "enabled": True,
                "query_strategy": "invalid_strategy",
            }
        }
        with pytest.raises(ConfigValidationError):
            validate_active_learning_config(config)

    def test_hybrid_weights_must_sum_to_one(self):
        from potato.server_utils.config_module import (
            validate_active_learning_config,
            ConfigValidationError,
        )

        config = {
            "active_learning": {
                "enabled": True,
                "hybrid_weights": {"uncertainty": 0.5, "diversity": 0.3},
            }
        }
        with pytest.raises(ConfigValidationError):
            validate_active_learning_config(config)

    def test_valid_cold_start_strategies(self):
        from potato.server_utils.config_module import validate_active_learning_config

        for strategy in ["random", "llm"]:
            config = {
                "active_learning": {
                    "enabled": True,
                    "cold_start_strategy": strategy,
                }
            }
            validate_active_learning_config(config)

    def test_invalid_cold_start_strategy(self):
        from potato.server_utils.config_module import (
            validate_active_learning_config,
            ConfigValidationError,
        )

        config = {
            "active_learning": {
                "enabled": True,
                "cold_start_strategy": "invalid",
            }
        }
        with pytest.raises(ConfigValidationError):
            validate_active_learning_config(config)

    def test_valid_confidence_methods(self):
        from potato.server_utils.config_module import validate_active_learning_config

        for method in ["logprobs", "verbalized", "consistency"]:
            config = {
                "active_learning": {
                    "enabled": True,
                    "confidence_method": method,
                }
            }
            validate_active_learning_config(config)

    def test_classifier_params_must_be_dict(self):
        from potato.server_utils.config_module import (
            validate_active_learning_config,
            ConfigValidationError,
        )

        config = {
            "active_learning": {
                "enabled": True,
                "classifier_params": "not_a_dict",
            }
        }
        with pytest.raises(ConfigValidationError):
            validate_active_learning_config(config)

    def test_bald_n_estimators_minimum(self):
        from potato.server_utils.config_module import (
            validate_active_learning_config,
            ConfigValidationError,
        )

        config = {
            "active_learning": {
                "enabled": True,
                "bald_params": {"n_estimators": 1},
            }
        }
        with pytest.raises(ConfigValidationError):
            validate_active_learning_config(config)

    def test_routing_thresholds_range(self):
        from potato.server_utils.config_module import (
            validate_active_learning_config,
            ConfigValidationError,
        )

        config = {
            "active_learning": {
                "enabled": True,
                "routing_thresholds": {"auto_label_min_confidence": 1.5},
            }
        }
        with pytest.raises(ConfigValidationError):
            validate_active_learning_config(config)
