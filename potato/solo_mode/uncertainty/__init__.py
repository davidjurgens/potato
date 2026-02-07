"""
Uncertainty Estimation Module

This module provides pluggable strategies for estimating LLM prediction uncertainty.

Available strategies:
- DirectConfidenceEstimator: Ask model for confidence score (0-100)
- DirectUncertaintyEstimator: Ask model for uncertainty score (0-100)
- TokenEntropyEstimator: Entropy of answer token probabilities (requires logprobs)
- SamplingDiversityEstimator: Multiple runs at high temperature, measure label diversity
"""

from .base import UncertaintyEstimator, UncertaintyEstimate
from .direct_confidence import DirectConfidenceEstimator
from .direct_uncertainty import DirectUncertaintyEstimator
from .token_entropy import TokenEntropyEstimator
from .sampling_diversity import SamplingDiversityEstimator
from .factory import UncertaintyEstimatorFactory, create_uncertainty_estimator

__all__ = [
    # Base
    'UncertaintyEstimator',
    'UncertaintyEstimate',
    # Implementations
    'DirectConfidenceEstimator',
    'DirectUncertaintyEstimator',
    'TokenEntropyEstimator',
    'SamplingDiversityEstimator',
    # Factory
    'UncertaintyEstimatorFactory',
    'create_uncertainty_estimator',
]
