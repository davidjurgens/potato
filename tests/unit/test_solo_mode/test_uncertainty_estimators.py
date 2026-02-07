"""
Unit tests for Solo Mode Uncertainty Estimators

Tests uncertainty estimation strategies including direct confidence,
direct uncertainty, token entropy, and sampling diversity.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from potato.solo_mode.uncertainty.base import UncertaintyEstimator, UncertaintyEstimate
from potato.solo_mode.uncertainty.direct_confidence import DirectConfidenceEstimator
from potato.solo_mode.uncertainty.direct_uncertainty import DirectUncertaintyEstimator
from potato.solo_mode.uncertainty.token_entropy import TokenEntropyEstimator
from potato.solo_mode.uncertainty.sampling_diversity import SamplingDiversityEstimator
from potato.solo_mode.uncertainty.factory import (
    UncertaintyEstimatorFactory,
    create_uncertainty_estimator,
)


class TestUncertaintyEstimate:
    """Tests for UncertaintyEstimate dataclass."""

    def test_score_normalization(self):
        """Scores should be clamped to [0, 1]."""
        # Test high values
        estimate = UncertaintyEstimate(
            uncertainty_score=1.5,
            confidence_score=1.5,
            method='test'
        )
        assert estimate.uncertainty_score == 1.0
        assert estimate.confidence_score == 1.0

        # Test negative values
        estimate = UncertaintyEstimate(
            uncertainty_score=-0.5,
            confidence_score=-0.5,
            method='test'
        )
        assert estimate.uncertainty_score == 0.0
        assert estimate.confidence_score == 0.0

    def test_to_dict(self):
        """Test serialization."""
        estimate = UncertaintyEstimate(
            uncertainty_score=0.3,
            confidence_score=0.7,
            method='test_method',
            metadata={'key': 'value'}
        )
        d = estimate.to_dict()
        assert d['uncertainty_score'] == 0.3
        assert d['confidence_score'] == 0.7
        assert d['method'] == 'test_method'
        assert d['metadata'] == {'key': 'value'}
        assert 'timestamp' in d


class TestDirectConfidenceEstimator:
    """Tests for DirectConfidenceEstimator."""

    @pytest.fixture
    def estimator(self):
        return DirectConfidenceEstimator()

    @pytest.fixture
    def mock_endpoint(self):
        endpoint = MagicMock()
        return endpoint

    def test_supports_all_endpoints(self, estimator, mock_endpoint):
        """Direct confidence should work with any endpoint."""
        assert estimator.supports_endpoint(mock_endpoint) is True

    def test_get_method_name(self, estimator):
        """Method name should be set."""
        assert 'confidence' in estimator.get_method_name().lower()

    def test_parse_json_response(self, estimator):
        """Test JSON parsing from various formats."""
        # Plain JSON
        result = estimator._parse_json_response('{"confidence": 80}')
        assert result['confidence'] == 80

        # JSON in code block
        result = estimator._parse_json_response('```json\n{"confidence": 90}\n```')
        assert result['confidence'] == 90

        # Regex fallback - pattern is "confidence" followed by digits
        result = estimator._parse_json_response('confidence: 75')
        assert result['confidence'] == 75

    def test_estimate_success(self, estimator, mock_endpoint):
        """Test successful uncertainty estimation."""
        mock_endpoint.query.return_value = MagicMock(
            model_dump=lambda: {
                'label': 'positive',
                'confidence': 85,
                'reasoning': 'Clear sentiment'
            }
        )

        estimate = estimator.estimate_uncertainty(
            instance_id='test-1',
            text='Great product!',
            prompt='Label the sentiment:',
            predicted_label='positive',
            endpoint=mock_endpoint
        )

        assert estimate.method == 'direct_confidence'
        assert estimate.confidence_score == 0.85
        assert abs(estimate.uncertainty_score - 0.15) < 0.001  # Float comparison
        assert estimate.metadata['raw_confidence'] == 85

    def test_estimate_handles_error(self, estimator, mock_endpoint):
        """Test that errors return default estimate."""
        mock_endpoint.query.side_effect = Exception("API error")

        estimate = estimator.estimate_uncertainty(
            instance_id='test-1',
            text='Test text',
            prompt='Test prompt',
            predicted_label='test',
            endpoint=mock_endpoint
        )

        assert estimate.uncertainty_score == 0.5
        assert estimate.confidence_score == 0.5
        assert 'error' in estimate.metadata


class TestDirectUncertaintyEstimator:
    """Tests for DirectUncertaintyEstimator."""

    @pytest.fixture
    def estimator(self):
        return DirectUncertaintyEstimator()

    def test_estimate_success(self, estimator):
        """Test successful uncertainty estimation."""
        mock_endpoint = MagicMock()
        mock_endpoint.query.return_value = MagicMock(
            model_dump=lambda: {
                'label': 'neutral',
                'uncertainty': 30,
                'uncertainty_factors': 'Mixed signals'
            }
        )

        estimate = estimator.estimate_uncertainty(
            instance_id='test-1',
            text='Okay product.',
            prompt='Label:',
            predicted_label='neutral',
            endpoint=mock_endpoint
        )

        assert estimate.method == 'direct_uncertainty'
        assert estimate.uncertainty_score == 0.30
        assert estimate.confidence_score == 0.70


class TestTokenEntropyEstimator:
    """Tests for TokenEntropyEstimator."""

    @pytest.fixture
    def estimator(self):
        return TokenEntropyEstimator()

    def test_supports_openai_endpoint(self, estimator):
        """Token entropy should support OpenAI-style endpoints."""
        endpoint = MagicMock()
        endpoint.__class__.__name__ = 'OpenAIEndpoint'
        assert estimator.supports_endpoint(endpoint) is True

    def test_does_not_support_anthropic(self, estimator):
        """Token entropy should not support Anthropic (no logprobs)."""
        endpoint = MagicMock()
        endpoint.__class__.__name__ = 'AnthropicEndpoint'
        # Remove any logprobs support indicators
        delattr(endpoint, 'supports_logprobs') if hasattr(endpoint, 'supports_logprobs') else None
        delattr(endpoint, 'query_with_logprobs') if hasattr(endpoint, 'query_with_logprobs') else None
        assert estimator.supports_endpoint(endpoint) is False

    def test_calculate_entropy(self, estimator):
        """Test entropy calculation from logprobs."""
        import math

        # Uniform distribution (max entropy)
        logprobs_uniform = [{'a': -1.609, 'b': -1.609, 'c': -1.609, 'd': -1.609, 'e': -1.609}]  # ~0.2 each
        entropy = estimator._calculate_entropy(logprobs_uniform)
        assert entropy > 1.5  # Should be close to log(5) ≈ 1.609

        # Peaked distribution (low entropy)
        logprobs_peaked = [{'a': -0.01, 'b': -5.0, 'c': -5.0, 'd': -5.0, 'e': -5.0}]  # ~99% on 'a'
        entropy = estimator._calculate_entropy(logprobs_peaked)
        assert entropy < 0.5  # Should be close to 0

    def test_returns_default_when_unsupported(self, estimator):
        """Should return 0.5 uncertainty for unsupported endpoints."""
        endpoint = MagicMock()
        endpoint.__class__.__name__ = 'UnsupportedEndpoint'

        estimate = estimator.estimate_uncertainty(
            instance_id='test-1',
            text='Test',
            prompt='Test',
            predicted_label='test',
            endpoint=endpoint
        )

        assert estimate.uncertainty_score == 0.5
        assert 'error' in estimate.metadata


class TestSamplingDiversityEstimator:
    """Tests for SamplingDiversityEstimator."""

    @pytest.fixture
    def estimator(self):
        return SamplingDiversityEstimator({'num_samples': 5, 'temperature': 1.0})

    def test_supports_all_endpoints(self, estimator):
        """Sampling diversity should work with any endpoint."""
        assert estimator.supports_endpoint(MagicMock()) is True

    def test_config_validation(self):
        """Test configuration validation."""
        # Invalid num_samples
        est = SamplingDiversityEstimator({'num_samples': 1})
        errors = est.validate_config()
        assert any('num_samples' in e for e in errors)

        # Invalid temperature
        est = SamplingDiversityEstimator({'temperature': 0})
        errors = est.validate_config()
        assert any('temperature' in e for e in errors)

    def test_normalize_label(self, estimator):
        """Test label normalization."""
        valid_labels = ['Positive', 'Negative', 'Neutral']

        assert estimator._normalize_label('positive', valid_labels) == 'Positive'
        assert estimator._normalize_label('NEGATIVE', valid_labels) == 'Negative'
        assert estimator._normalize_label('invalid', valid_labels) is None

    def test_calculate_entropy(self, estimator):
        """Test entropy calculation from label counts."""
        from collections import Counter
        import math

        # All same label (zero entropy)
        counts = Counter(['A', 'A', 'A', 'A', 'A'])
        entropy = estimator._calculate_entropy(counts, 5)
        assert entropy == 0.0

        # Uniform distribution
        counts = Counter(['A', 'B', 'C', 'D', 'E'])
        entropy = estimator._calculate_entropy(counts, 5)
        assert abs(entropy - math.log2(5)) < 0.01

    def test_estimate_with_consistent_responses(self, estimator):
        """Test estimation when all samples agree."""
        mock_endpoint = MagicMock()
        mock_endpoint.temperature = 0.1

        # All responses return same label
        mock_endpoint.query.return_value = MagicMock(
            model_dump=lambda: {'label': 'positive'}
        )

        estimate = estimator.estimate_uncertainty(
            instance_id='test-1',
            text='Great!',
            prompt='Sentiment:',
            predicted_label='positive',
            endpoint=mock_endpoint,
            schema_info={'labels': ['positive', 'negative']}
        )

        # High consistency = low uncertainty
        assert estimate.uncertainty_score < 0.5
        assert estimate.metadata['num_samples'] == 5
        assert estimate.metadata['most_common_label'] == 'positive'

    def test_estimate_with_diverse_responses(self, estimator):
        """Test estimation when samples vary."""
        mock_endpoint = MagicMock()
        mock_endpoint.temperature = 0.1

        # Alternating responses
        responses = ['positive', 'negative', 'positive', 'neutral', 'negative']
        mock_endpoint.query.side_effect = [
            MagicMock(model_dump=lambda l=label: {'label': l})
            for label in responses
        ]

        estimate = estimator.estimate_uncertainty(
            instance_id='test-1',
            text='Okay.',
            prompt='Sentiment:',
            predicted_label='positive',
            endpoint=mock_endpoint,
            schema_info={'labels': ['positive', 'negative', 'neutral']}
        )

        # High diversity = high uncertainty
        assert estimate.uncertainty_score > 0.3


class TestUncertaintyEstimatorFactory:
    """Tests for UncertaintyEstimatorFactory."""

    def test_get_available_strategies(self):
        """Factory should list all strategies."""
        strategies = UncertaintyEstimatorFactory.get_available_strategies()
        assert 'direct_confidence' in strategies
        assert 'direct_uncertainty' in strategies
        assert 'token_entropy' in strategies
        assert 'sampling_diversity' in strategies

    def test_create_by_name(self):
        """Factory should create estimators by name."""
        estimator = UncertaintyEstimatorFactory.create('direct_confidence')
        assert isinstance(estimator, DirectConfidenceEstimator)

        estimator = UncertaintyEstimatorFactory.create('sampling_diversity')
        assert isinstance(estimator, SamplingDiversityEstimator)

    def test_create_invalid_raises(self):
        """Factory should raise for unknown strategies."""
        with pytest.raises(ValueError) as exc_info:
            UncertaintyEstimatorFactory.create('unknown_strategy')
        assert 'Unknown uncertainty strategy' in str(exc_info.value)

    def test_create_with_config(self):
        """Factory should pass config to estimator."""
        estimator = UncertaintyEstimatorFactory.create(
            'sampling_diversity',
            {'num_samples': 10, 'temperature': 0.5}
        )
        assert estimator.num_samples == 10
        assert estimator.temperature == 0.5

    def test_register_custom(self):
        """Factory should allow custom estimator registration."""
        class CustomEstimator(UncertaintyEstimator):
            def estimate_uncertainty(self, *args, **kwargs):
                return UncertaintyEstimate(0.5, 0.5, 'custom')
            def supports_endpoint(self, endpoint):
                return True

        UncertaintyEstimatorFactory.register('custom', CustomEstimator)
        assert 'custom' in UncertaintyEstimatorFactory.get_available_strategies()

        estimator = UncertaintyEstimatorFactory.create('custom')
        assert isinstance(estimator, CustomEstimator)

    def test_get_best_for_endpoint(self):
        """Factory should select best strategy for endpoint."""
        # Unknown endpoint should get direct_confidence (default fallback)
        # Use spec to prevent auto-creating attributes like query_with_logprobs
        unknown_endpoint = MagicMock(spec=['query'])
        unknown_endpoint.__class__.__name__ = 'CustomEndpoint'
        strategy = UncertaintyEstimatorFactory.get_best_for_endpoint(unknown_endpoint)
        assert strategy == 'direct_confidence'

        # VLLMEndpoint should get token_entropy (supports logprobs)
        vllm_endpoint = MagicMock()
        vllm_endpoint.__class__.__name__ = 'VLLMEndpoint'
        strategy = UncertaintyEstimatorFactory.get_best_for_endpoint(vllm_endpoint)
        assert strategy == 'token_entropy'


class TestCreateUncertaintyEstimator:
    """Tests for convenience function."""

    def test_default_strategy(self):
        """Default strategy should be direct_confidence."""
        estimator = create_uncertainty_estimator()
        assert isinstance(estimator, DirectConfidenceEstimator)

    def test_with_strategy(self):
        """Should respect strategy parameter."""
        estimator = create_uncertainty_estimator('sampling_diversity')
        assert isinstance(estimator, SamplingDiversityEstimator)
