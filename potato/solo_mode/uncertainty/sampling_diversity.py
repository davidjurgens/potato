"""
Sampling Diversity Uncertainty Estimation

This strategy runs the model multiple times at high temperature and measures
the diversity of responses to estimate uncertainty.
"""

import logging
from collections import Counter
from typing import Any, Dict, List, Optional

from .base import UncertaintyEstimator, UncertaintyEstimate

logger = logging.getLogger(__name__)


class SamplingDiversityEstimator(UncertaintyEstimator):
    """
    Estimate uncertainty by sampling multiple responses at high temperature.

    This strategy runs the model N times with high temperature and measures
    how much the predicted labels vary. High diversity in responses indicates
    the model is uncertain about the correct answer.

    Pros:
    - Captures actual model uncertainty in a direct way
    - Works with all model endpoints
    - Provides interpretable diversity metrics

    Cons:
    - Requires N API calls per instance (expensive)
    - Slower than other methods
    - May not work well for deterministic prompts
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the sampling diversity estimator."""
        super().__init__(config)
        self.num_samples = self.config.get('num_samples', 5)
        self.temperature = self.config.get('temperature', 1.0)
        self.normalize_labels = self.config.get('normalize_labels', True)

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
        Estimate uncertainty by sampling multiple responses.

        Makes N API calls at high temperature and measures label diversity.
        """
        try:
            # Get valid labels for normalization
            valid_labels = self._get_valid_labels(schema_info) if schema_info else None

            # Sample multiple responses
            sampled_labels = self._sample_responses(
                prompt, endpoint, valid_labels
            )

            if not sampled_labels:
                return UncertaintyEstimate(
                    uncertainty_score=0.5,
                    confidence_score=0.5,
                    method='sampling_diversity',
                    metadata={'error': 'No valid samples obtained'}
                )

            # Calculate diversity metrics
            label_counts = Counter(sampled_labels)
            total_samples = len(sampled_labels)
            unique_labels = len(label_counts)

            # Most common label and its count
            most_common_label, most_common_count = label_counts.most_common(1)[0]

            # Uncertainty = 1 - (most_common_count / total_samples)
            # If all samples agree, uncertainty = 0
            # If samples are evenly distributed, uncertainty approaches 1
            consistency_score = most_common_count / total_samples
            uncertainty_score = 1.0 - consistency_score

            # Alternative: Entropy-based diversity
            entropy = self._calculate_entropy(label_counts, total_samples)
            max_entropy = self._max_entropy(unique_labels)
            normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0

            return UncertaintyEstimate(
                uncertainty_score=uncertainty_score,
                confidence_score=consistency_score,
                method='sampling_diversity',
                metadata={
                    'num_samples': total_samples,
                    'unique_labels': unique_labels,
                    'label_distribution': dict(label_counts),
                    'most_common_label': most_common_label,
                    'most_common_count': most_common_count,
                    'consistency_score': consistency_score,
                    'normalized_entropy': normalized_entropy,
                }
            )

        except Exception as e:
            logger.warning(
                f"Error in sampling diversity estimation for {instance_id}: {e}. "
                "Returning default uncertainty."
            )
            return UncertaintyEstimate(
                uncertainty_score=0.5,
                confidence_score=0.5,
                method='sampling_diversity',
                metadata={'error': str(e)}
            )

    def _sample_responses(
        self,
        prompt: str,
        endpoint: Any,
        valid_labels: Optional[List[str]] = None
    ) -> List[str]:
        """
        Sample multiple responses from the model at high temperature.

        Args:
            prompt: The labeling prompt
            endpoint: The AI endpoint
            valid_labels: Optional list of valid labels for normalization

        Returns:
            List of sampled labels
        """
        sampled_labels = []

        # Store original temperature
        original_temp = getattr(endpoint, 'temperature', 0.1)

        try:
            # Set high temperature for sampling
            if hasattr(endpoint, 'temperature'):
                endpoint.temperature = self.temperature

            for i in range(self.num_samples):
                try:
                    # Query the model
                    from pydantic import BaseModel

                    class LabelResponse(BaseModel):
                        label: str

                    response = endpoint.query(prompt, LabelResponse)

                    # Parse response
                    if isinstance(response, str):
                        label = response.strip()
                    elif hasattr(response, 'model_dump'):
                        label = response.model_dump().get('label', str(response))
                    elif hasattr(response, 'label'):
                        label = response.label
                    else:
                        label = str(response)

                    # Normalize label
                    if self.normalize_labels and valid_labels:
                        label = self._normalize_label(label, valid_labels)
                        if label is None:
                            continue  # Skip invalid labels

                    sampled_labels.append(label)

                except Exception as e:
                    logger.debug(f"Error in sample {i}: {e}")
                    continue

        finally:
            # Restore original temperature
            if hasattr(endpoint, 'temperature'):
                endpoint.temperature = original_temp

        return sampled_labels

    def _get_valid_labels(self, schema_info: Dict[str, Any]) -> Optional[List[str]]:
        """Extract valid labels from schema info."""
        labels = schema_info.get('labels', [])
        valid_labels = []
        for label in labels:
            if isinstance(label, str):
                valid_labels.append(label)
            elif isinstance(label, dict):
                valid_labels.append(label.get('name', str(label)))
        return valid_labels if valid_labels else None

    def _normalize_label(self, label: str, valid_labels: List[str]) -> Optional[str]:
        """
        Normalize a label to match one of the valid labels.

        Returns None if no match found.
        """
        label_lower = label.lower().strip()

        for valid in valid_labels:
            if valid.lower().strip() == label_lower:
                return valid

        # No match found
        return None

    def _calculate_entropy(
        self,
        label_counts: Counter,
        total: int
    ) -> float:
        """Calculate Shannon entropy of label distribution."""
        import math

        entropy = 0.0
        for count in label_counts.values():
            if count > 0:
                p = count / total
                entropy -= p * math.log2(p)

        return entropy

    def _max_entropy(self, num_classes: int) -> float:
        """Calculate maximum possible entropy for N classes."""
        import math

        if num_classes <= 1:
            return 0.0
        return math.log2(num_classes)

    def supports_endpoint(self, endpoint: Any) -> bool:
        """
        Check if endpoint is supported.

        Sampling diversity works with any text-generation endpoint,
        though it requires setting temperature.
        """
        return True

    def get_config_defaults(self) -> Dict[str, Any]:
        """Get default configuration."""
        return {
            'num_samples': 5,
            'temperature': 1.0,
            'normalize_labels': True,
        }

    def validate_config(self) -> List[str]:
        """Validate configuration."""
        errors = []

        if self.num_samples < 2:
            errors.append("num_samples must be at least 2")

        if self.temperature <= 0:
            errors.append("temperature must be positive")

        return errors
