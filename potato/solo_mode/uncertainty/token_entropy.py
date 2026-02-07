"""
Token Entropy Uncertainty Estimation

This strategy measures uncertainty based on the entropy of token probabilities
in the model's response. Requires endpoints that support logprobs.
"""

import logging
import math
from typing import Any, Dict, List, Optional

from .base import UncertaintyEstimator, UncertaintyEstimate

logger = logging.getLogger(__name__)


class TokenEntropyEstimator(UncertaintyEstimator):
    """
    Estimate uncertainty from token probability distributions.

    This strategy analyzes the entropy of the probability distribution
    over possible next tokens, particularly for tokens that represent
    the answer/label. High entropy indicates the model is uncertain
    between multiple options.

    Pros:
    - Objective measure based on actual model computations
    - No additional prompting required
    - Can be computed in a single pass

    Cons:
    - Requires endpoints that return logprobs (OpenAI, vLLM)
    - Not available for all models (Anthropic, many others)
    - May not correlate well with semantic uncertainty
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the token entropy estimator."""
        super().__init__(config)
        # Number of top tokens to consider for entropy calculation
        self.top_logprobs = self.config.get('top_logprobs', 5)
        # Whether to use only the first answer token or average across all
        self.use_first_token_only = self.config.get('use_first_token_only', True)
        # Normalization factor (max entropy for top_logprobs choices)
        self.max_entropy = math.log(self.top_logprobs)

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
        Estimate uncertainty from token entropy.

        This requires the endpoint to support logprobs. If not supported
        or if the query fails, returns a default uncertainty estimate.
        """
        if not self.supports_endpoint(endpoint):
            logger.warning(
                f"Token entropy not supported for endpoint {type(endpoint).__name__}. "
                "Returning default uncertainty."
            )
            return UncertaintyEstimate(
                uncertainty_score=0.5,
                confidence_score=0.5,
                method='token_entropy',
                metadata={'error': 'Endpoint does not support logprobs'}
            )

        try:
            # Query with logprobs enabled
            logprobs_data = self._query_with_logprobs(prompt, endpoint)

            if not logprobs_data:
                return UncertaintyEstimate(
                    uncertainty_score=0.5,
                    confidence_score=0.5,
                    method='token_entropy',
                    metadata={'error': 'No logprobs returned'}
                )

            # Calculate entropy from logprobs
            entropy = self._calculate_entropy(logprobs_data)

            # Normalize to 0-1 range
            # Higher entropy = higher uncertainty
            uncertainty_score = min(1.0, entropy / self.max_entropy)
            confidence_score = 1.0 - uncertainty_score

            return UncertaintyEstimate(
                uncertainty_score=uncertainty_score,
                confidence_score=confidence_score,
                method='token_entropy',
                metadata={
                    'raw_entropy': entropy,
                    'max_entropy': self.max_entropy,
                    'num_tokens_analyzed': len(logprobs_data),
                }
            )

        except Exception as e:
            logger.warning(
                f"Error in token entropy estimation for {instance_id}: {e}. "
                "Returning default uncertainty."
            )
            return UncertaintyEstimate(
                uncertainty_score=0.5,
                confidence_score=0.5,
                method='token_entropy',
                metadata={'error': str(e)}
            )

    def _query_with_logprobs(
        self,
        prompt: str,
        endpoint: Any
    ) -> Optional[List[Dict[str, float]]]:
        """
        Query the endpoint with logprobs enabled.

        Returns a list of dictionaries mapping tokens to log probabilities.
        """
        # This is endpoint-specific. Currently supports OpenAI-style endpoints.
        try:
            # Check if endpoint has OpenAI-style logprobs support
            if hasattr(endpoint, 'client') and hasattr(endpoint.client, 'chat'):
                # OpenAI-style endpoint
                response = endpoint.client.chat.completions.create(
                    model=endpoint.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=endpoint.max_tokens,
                    temperature=endpoint.temperature,
                    logprobs=True,
                    top_logprobs=self.top_logprobs,
                )

                if response.choices and response.choices[0].logprobs:
                    content_logprobs = response.choices[0].logprobs.content
                    if content_logprobs:
                        return [
                            {
                                lp.token: lp.logprob
                                for lp in token_info.top_logprobs
                            }
                            for token_info in content_logprobs
                        ]

            # vLLM endpoint
            elif hasattr(endpoint, 'query_with_logprobs'):
                return endpoint.query_with_logprobs(prompt, self.top_logprobs)

        except Exception as e:
            logger.debug(f"Error querying with logprobs: {e}")

        return None

    def _calculate_entropy(
        self,
        logprobs_data: List[Dict[str, float]]
    ) -> float:
        """
        Calculate entropy from logprobs data.

        Args:
            logprobs_data: List of dicts mapping tokens to log probabilities

        Returns:
            Average entropy across analyzed tokens
        """
        if not logprobs_data:
            return 0.5 * self.max_entropy  # Default to mid-range entropy

        if self.use_first_token_only:
            # Only use the first token (often contains the label)
            logprobs_data = logprobs_data[:1]

        entropies = []
        for token_logprobs in logprobs_data:
            if not token_logprobs:
                continue

            # Convert log probabilities to probabilities
            probs = [math.exp(lp) for lp in token_logprobs.values()]

            # Normalize (in case probabilities don't sum to 1)
            total = sum(probs)
            if total > 0:
                probs = [p / total for p in probs]

            # Calculate entropy: H = -sum(p * log(p))
            entropy = 0.0
            for p in probs:
                if p > 0:
                    entropy -= p * math.log(p)

            entropies.append(entropy)

        if not entropies:
            return 0.5 * self.max_entropy

        return sum(entropies) / len(entropies)

    def supports_endpoint(self, endpoint: Any) -> bool:
        """
        Check if endpoint supports logprobs.

        Currently supports:
        - OpenAI-style endpoints (openai, vllm with OpenAI API)
        - vLLM endpoints with logprobs support
        """
        endpoint_type = type(endpoint).__name__.lower()

        # Known supported endpoint types
        supported_types = [
            'openaiendpoint',
            'vllmendpoint',
        ]

        if any(st in endpoint_type for st in supported_types):
            return True

        # Check for explicit logprobs support
        if hasattr(endpoint, 'supports_logprobs'):
            return endpoint.supports_logprobs

        # Check for query_with_logprobs method
        if hasattr(endpoint, 'query_with_logprobs'):
            return True

        return False

    def get_config_defaults(self) -> Dict[str, Any]:
        """Get default configuration."""
        return {
            'top_logprobs': 5,
            'use_first_token_only': True,
        }
