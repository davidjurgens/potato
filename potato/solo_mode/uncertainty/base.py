"""
Uncertainty Estimator Base Classes

This module defines the abstract base class for uncertainty estimation strategies.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import logging

logger = logging.getLogger(__name__)


@dataclass
class UncertaintyEstimate:
    """
    Result of uncertainty estimation for a single prediction.

    Attributes:
        uncertainty_score: The uncertainty score (0.0 = certain, 1.0 = uncertain)
        confidence_score: The confidence score (1.0 - uncertainty_score)
        method: The estimation method used
        metadata: Additional method-specific information
    """
    uncertainty_score: float
    confidence_score: float
    method: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Ensure scores are in valid range."""
        self.uncertainty_score = max(0.0, min(1.0, self.uncertainty_score))
        self.confidence_score = max(0.0, min(1.0, self.confidence_score))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'uncertainty_score': self.uncertainty_score,
            'confidence_score': self.confidence_score,
            'method': self.method,
            'timestamp': self.timestamp.isoformat(),
            'metadata': self.metadata,
        }


class UncertaintyEstimator(ABC):
    """
    Abstract base class for uncertainty estimation strategies.

    Subclasses implement different methods for estimating how uncertain
    an LLM is about its predictions. Strategies include:
    - Directly asking the model for confidence/uncertainty scores
    - Analyzing token probability distributions (entropy)
    - Running multiple samples and measuring label diversity
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the uncertainty estimator.

        Args:
            config: Strategy-specific configuration
        """
        self.config = config or {}
        self.name = self.__class__.__name__

    @abstractmethod
    def estimate_uncertainty(
        self,
        instance_id: str,
        text: str,
        prompt: str,
        predicted_label: Any,
        endpoint: Any,
        schema_info: Optional[Dict[str, Any]] = None
    ) -> UncertaintyEstimate:
        """
        Estimate uncertainty for a prediction.

        Args:
            instance_id: The instance being labeled
            text: The text content to label
            prompt: The labeling prompt
            predicted_label: The label that was predicted
            endpoint: The AI endpoint to use
            schema_info: Optional annotation schema information

        Returns:
            UncertaintyEstimate with uncertainty and confidence scores
        """
        pass

    @abstractmethod
    def supports_endpoint(self, endpoint: Any) -> bool:
        """
        Check if this strategy supports the given endpoint.

        Some strategies (like token entropy) require specific endpoint
        capabilities like logprobs support.

        Args:
            endpoint: The AI endpoint to check

        Returns:
            True if this strategy can be used with the endpoint
        """
        pass

    def get_method_name(self) -> str:
        """Get the name of this estimation method."""
        return self.name

    def get_config_defaults(self) -> Dict[str, Any]:
        """Get default configuration values for this strategy."""
        return {}

    def validate_config(self) -> List[str]:
        """
        Validate the configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        return []
