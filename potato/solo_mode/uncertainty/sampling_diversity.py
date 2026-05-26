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

            logger.info(
                f"[SamplingDiversity] {instance_id}: "
                f"{len(sampled_labels)}/{self.num_samples} samples, "
                f"labels={dict(Counter(sampled_labels))}"
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

        Attempts batched sampling first (vLLM n parameter) for efficiency,
        falls back to sequential calls for other endpoints.

        Args:
            prompt: The labeling prompt
            endpoint: The AI endpoint
            valid_labels: Optional list of valid labels for normalization

        Returns:
            List of sampled labels
        """
        # Try batched sampling first (vLLM/OpenAI support n parameter)
        batched = self._try_batched_sampling(prompt, endpoint, valid_labels)
        if batched is not None:
            return batched

        # Fallback: sequential sampling
        return self._sequential_sampling(prompt, endpoint, valid_labels)

    def _try_batched_sampling(
        self,
        prompt: str,
        endpoint: Any,
        valid_labels: Optional[List[str]] = None
    ) -> Optional[List[str]]:
        """Try to sample N responses in a single API call using the n parameter.

        Works with vLLM and OpenAI-compatible endpoints. Returns None if
        the endpoint doesn't support batched completions.
        """
        # Only attempt for endpoints with base_url (vLLM, OpenAI-compatible)
        base_url = getattr(endpoint, 'base_url', None)
        if not base_url:
            ai_config = getattr(endpoint, 'ai_config', {})
            base_url = ai_config.get('base_url')
        if not base_url:
            return None

        try:
            import requests as req

            headers = {"Content-Type": "application/json"}
            api_key = getattr(endpoint, 'api_key', '')
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            # Get think setting from endpoint config
            ai_config = getattr(endpoint, 'ai_config', {})
            think = ai_config.get('think', False)

            payload = {
                "model": getattr(endpoint, 'model', ''),
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": getattr(endpoint, 'max_tokens', 200),
                "temperature": self.temperature,
                "stream": False,
                "n": self.num_samples,
                "chat_template_kwargs": {"enable_thinking": think},
            }

            timeout = ai_config.get('timeout', 60)
            response = req.post(
                f"{base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )

            if response.status_code != 200:
                return None

            data = response.json()
            choices = data.get("choices", [])
            if len(choices) < 2:
                return None  # Server didn't support n parameter

            sampled_labels = []
            for choice in choices:
                content = choice.get("message", {}).get("content", "")
                if not content:
                    continue

                # Parse label from response
                label = self._extract_label_from_response(content)
                if label and self.normalize_labels and valid_labels:
                    label = self._normalize_label(label, valid_labels)
                if label:
                    sampled_labels.append(label)

            return sampled_labels if sampled_labels else None

        except Exception as e:
            logger.debug(f"Batched sampling failed, falling back to sequential: {e}")
            return None

    def _sequential_sampling(
        self,
        prompt: str,
        endpoint: Any,
        valid_labels: Optional[List[str]] = None
    ) -> List[str]:
        """Sample responses one at a time (fallback for non-batching endpoints)."""
        sampled_labels = []
        original_temp = getattr(endpoint, 'temperature', 0.1)

        try:
            if hasattr(endpoint, 'temperature'):
                endpoint.temperature = self.temperature

            for i in range(self.num_samples):
                try:
                    from pydantic import BaseModel

                    class LabelResponse(BaseModel):
                        label: str

                    response = endpoint.query(prompt, LabelResponse)
                    label = self._extract_label_from_response(response)

                    if label and self.normalize_labels and valid_labels:
                        label = self._normalize_label(label, valid_labels)
                    if label:
                        sampled_labels.append(label)

                except Exception as e:
                    logger.debug(f"Error in sample {i}: {e}")
                    continue

        finally:
            if hasattr(endpoint, 'temperature'):
                endpoint.temperature = original_temp

        return sampled_labels

    @staticmethod
    def _extract_label_from_response(response) -> Optional[str]:
        """Extract a label string from various response formats."""
        import json as json_mod
        import re

        if isinstance(response, dict):
            return response.get('label', str(response))
        elif isinstance(response, str):
            content = response.strip()
            # Try JSON parse
            try:
                data = json_mod.loads(content)
                if isinstance(data, dict):
                    return data.get('label', '')
            except (json_mod.JSONDecodeError, ValueError):
                pass
            # Try extracting from markdown
            match = re.search(r'"label"\s*:\s*"([^"]+)"', content)
            if match:
                return match.group(1)
            return content
        elif hasattr(response, 'model_dump'):
            return response.model_dump().get('label', str(response))
        elif hasattr(response, 'label'):
            return response.label
        return str(response)

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

    def _normalize_label(self, label: Any, valid_labels: List[str]) -> Optional[str]:
        """
        Normalize a label to match one of the valid labels.

        Returns None if no match found. Handles non-string inputs gracefully.
        """
        if label is None:
            return None
        try:
            label_lower = str(label).lower().strip()
        except Exception:
            return None

        for valid in valid_labels:
            if str(valid).lower().strip() == label_lower:
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
