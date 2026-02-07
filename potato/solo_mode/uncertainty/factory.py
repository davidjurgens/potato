"""
Uncertainty Estimator Factory

Factory for creating uncertainty estimators based on configuration.
"""

import logging
from typing import Any, Dict, Optional, Type

from .base import UncertaintyEstimator
from .direct_confidence import DirectConfidenceEstimator
from .direct_uncertainty import DirectUncertaintyEstimator
from .token_entropy import TokenEntropyEstimator
from .sampling_diversity import SamplingDiversityEstimator

logger = logging.getLogger(__name__)


class UncertaintyEstimatorFactory:
    """
    Factory for creating uncertainty estimators.

    Supports registration of custom estimators and configuration-based creation.
    """

    _estimators: Dict[str, Type[UncertaintyEstimator]] = {
        'direct_confidence': DirectConfidenceEstimator,
        'direct_uncertainty': DirectUncertaintyEstimator,
        'token_entropy': TokenEntropyEstimator,
        'sampling_diversity': SamplingDiversityEstimator,
    }

    @classmethod
    def register(cls, name: str, estimator_class: Type[UncertaintyEstimator]) -> None:
        """
        Register a custom uncertainty estimator.

        Args:
            name: Name to register under
            estimator_class: The estimator class
        """
        cls._estimators[name] = estimator_class
        logger.info(f"Registered uncertainty estimator: {name}")

    @classmethod
    def get_available_strategies(cls) -> list:
        """Get list of available strategy names."""
        return list(cls._estimators.keys())

    @classmethod
    def create(
        cls,
        strategy: str,
        config: Optional[Dict[str, Any]] = None
    ) -> UncertaintyEstimator:
        """
        Create an uncertainty estimator by strategy name.

        Args:
            strategy: Strategy name (e.g., 'direct_confidence')
            config: Strategy-specific configuration

        Returns:
            UncertaintyEstimator instance

        Raises:
            ValueError: If strategy is not registered
        """
        if strategy not in cls._estimators:
            available = ', '.join(cls._estimators.keys())
            raise ValueError(
                f"Unknown uncertainty strategy: {strategy}. "
                f"Available strategies: {available}"
            )

        estimator_class = cls._estimators[strategy]
        estimator = estimator_class(config or {})

        # Validate configuration
        errors = estimator.validate_config()
        if errors:
            for error in errors:
                logger.warning(f"Config validation error for {strategy}: {error}")

        logger.info(f"Created uncertainty estimator: {strategy}")
        return estimator

    @classmethod
    def create_from_config(
        cls,
        solo_config: Any
    ) -> UncertaintyEstimator:
        """
        Create an uncertainty estimator from Solo Mode config.

        Args:
            solo_config: SoloModeConfig instance

        Returns:
            UncertaintyEstimator instance
        """
        uncertainty_config = solo_config.uncertainty

        # Build strategy-specific config
        config = {}

        if uncertainty_config.strategy == 'sampling_diversity':
            config = {
                'num_samples': uncertainty_config.num_samples,
                'temperature': uncertainty_config.sampling_temperature,
            }

        return cls.create(uncertainty_config.strategy, config)

    @classmethod
    def get_best_for_endpoint(cls, endpoint: Any) -> str:
        """
        Get the best uncertainty strategy for a given endpoint.

        Prefers more objective measures (token entropy) when available,
        falls back to direct confidence otherwise.

        Args:
            endpoint: The AI endpoint

        Returns:
            Strategy name
        """
        # Try token entropy first (most objective)
        entropy_estimator = TokenEntropyEstimator()
        if entropy_estimator.supports_endpoint(endpoint):
            return 'token_entropy'

        # Default to direct confidence (most compatible)
        return 'direct_confidence'


def create_uncertainty_estimator(
    strategy: str = 'direct_confidence',
    config: Optional[Dict[str, Any]] = None
) -> UncertaintyEstimator:
    """
    Convenience function to create an uncertainty estimator.

    Args:
        strategy: Strategy name
        config: Strategy-specific configuration

    Returns:
        UncertaintyEstimator instance
    """
    return UncertaintyEstimatorFactory.create(strategy, config)
