"""
Direct Confidence Estimation

This strategy asks the LLM directly for a confidence score on its prediction.
"""

import json
import logging
import re
from typing import Any, Dict, Optional

from .base import UncertaintyEstimator, UncertaintyEstimate

logger = logging.getLogger(__name__)


class DirectConfidenceEstimator(UncertaintyEstimator):
    """
    Estimate uncertainty by asking the model for a confidence score.

    This is the simplest and most broadly compatible strategy. It appends
    a request for a confidence score to the labeling prompt and parses
    the model's self-reported confidence.

    Pros:
    - Works with all LLM endpoints
    - Simple to implement and understand
    - Can get confidence explanation/reasoning

    Cons:
    - Models may be miscalibrated (overconfident or underconfident)
    - Adds to prompt length and response time
    """

    CONFIDENCE_PROMPT = """

After providing your label, also rate your confidence in this label on a scale from 0 to 100, where:
- 0 = completely uncertain, essentially guessing
- 50 = somewhat confident but could easily be wrong
- 100 = absolutely certain

Respond in JSON format:
{
    "label": "<your label>",
    "confidence": <0-100>,
    "reasoning": "<brief explanation of your confidence level>"
}
"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the direct confidence estimator."""
        super().__init__(config)
        self.prompt_template = self.config.get(
            'prompt_template',
            self.CONFIDENCE_PROMPT
        )

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
        Estimate uncertainty by querying the model for confidence.

        This method makes an additional API call with a modified prompt
        that asks the model to rate its confidence.
        """
        try:
            # Build confidence-aware prompt
            full_prompt = prompt + self.prompt_template

            # Query the model
            from pydantic import BaseModel

            class ConfidenceResponse(BaseModel):
                label: str
                confidence: float
                reasoning: str = ""

            response = endpoint.query(full_prompt, ConfidenceResponse)

            # Parse response
            if isinstance(response, str):
                response_data = self._parse_json_response(response)
            elif hasattr(response, 'model_dump'):
                response_data = response.model_dump()
            else:
                response_data = response

            confidence = float(response_data.get('confidence', 50))
            reasoning = response_data.get('reasoning', '')

            # Normalize to 0-1 range
            confidence_score = max(0.0, min(100.0, confidence)) / 100.0
            uncertainty_score = 1.0 - confidence_score

            return UncertaintyEstimate(
                uncertainty_score=uncertainty_score,
                confidence_score=confidence_score,
                method='direct_confidence',
                metadata={
                    'raw_confidence': confidence,
                    'reasoning': reasoning,
                    'response_label': response_data.get('label'),
                }
            )

        except Exception as e:
            logger.warning(
                f"Error in direct confidence estimation for {instance_id}: {e}. "
                "Returning default uncertainty."
            )
            return UncertaintyEstimate(
                uncertainty_score=0.5,
                confidence_score=0.5,
                method='direct_confidence',
                metadata={'error': str(e)}
            )

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON from response, handling markdown code blocks."""
        content = response.strip()

        # Try to extract JSON from markdown code blocks
        if '```json' in content:
            match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
            if match:
                content = match.group(1).strip()
        elif '```' in content:
            match = re.search(r'```\s*([\s\S]*?)\s*```', content)
            if match:
                content = match.group(1).strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Try to extract confidence with regex
            conf_match = re.search(r'confidence["\s:]+(\d+)', content, re.IGNORECASE)
            if conf_match:
                return {'confidence': int(conf_match.group(1))}
            return {'confidence': 50}

    def supports_endpoint(self, endpoint: Any) -> bool:
        """
        Check if endpoint is supported.

        Direct confidence works with any text-generation endpoint.
        """
        # All endpoints that can generate text are supported
        return True

    def get_config_defaults(self) -> Dict[str, Any]:
        """Get default configuration."""
        return {
            'prompt_template': self.CONFIDENCE_PROMPT,
        }
