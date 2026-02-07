"""
Direct Uncertainty Estimation

This strategy asks the LLM directly for an uncertainty score on its prediction.
Similar to direct confidence but frames the question differently.
"""

import json
import logging
import re
from typing import Any, Dict, Optional

from .base import UncertaintyEstimator, UncertaintyEstimate

logger = logging.getLogger(__name__)


class DirectUncertaintyEstimator(UncertaintyEstimator):
    """
    Estimate uncertainty by asking the model how uncertain it is.

    This is similar to DirectConfidenceEstimator but frames the question
    as "how uncertain are you?" rather than "how confident are you?".
    Research suggests that different framings can elicit different
    (and sometimes more calibrated) responses from LLMs.

    Pros:
    - Works with all LLM endpoints
    - Different framing may elicit better calibration for some models
    - Focuses on doubt/uncertainty rather than confidence

    Cons:
    - Same calibration concerns as direct confidence
    - May be redundant with direct confidence in many cases
    """

    UNCERTAINTY_PROMPT = """

After providing your label, rate how uncertain you are about this label on a scale from 0 to 100, where:
- 0 = absolutely certain, no doubt whatsoever
- 50 = moderately uncertain, could go either way
- 100 = extremely uncertain, essentially guessing

Consider factors like:
- Ambiguity in the text
- Edge cases or unclear boundaries
- Missing context that would help
- Conflicting signals in the text

Respond in JSON format:
{
    "label": "<your label>",
    "uncertainty": <0-100>,
    "uncertainty_factors": "<what makes you uncertain>"
}
"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the direct uncertainty estimator."""
        super().__init__(config)
        self.prompt_template = self.config.get(
            'prompt_template',
            self.UNCERTAINTY_PROMPT
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
        Estimate uncertainty by querying the model for uncertainty score.

        This method makes an additional API call with a modified prompt
        that asks the model to rate its uncertainty.
        """
        try:
            # Build uncertainty-aware prompt
            full_prompt = prompt + self.prompt_template

            # Query the model
            from pydantic import BaseModel

            class UncertaintyResponse(BaseModel):
                label: str
                uncertainty: float
                uncertainty_factors: str = ""

            response = endpoint.query(full_prompt, UncertaintyResponse)

            # Parse response
            if isinstance(response, str):
                response_data = self._parse_json_response(response)
            elif hasattr(response, 'model_dump'):
                response_data = response.model_dump()
            else:
                response_data = response

            uncertainty = float(response_data.get('uncertainty', 50))
            factors = response_data.get('uncertainty_factors', '')

            # Normalize to 0-1 range
            uncertainty_score = max(0.0, min(100.0, uncertainty)) / 100.0
            confidence_score = 1.0 - uncertainty_score

            return UncertaintyEstimate(
                uncertainty_score=uncertainty_score,
                confidence_score=confidence_score,
                method='direct_uncertainty',
                metadata={
                    'raw_uncertainty': uncertainty,
                    'uncertainty_factors': factors,
                    'response_label': response_data.get('label'),
                }
            )

        except Exception as e:
            logger.warning(
                f"Error in direct uncertainty estimation for {instance_id}: {e}. "
                "Returning default uncertainty."
            )
            return UncertaintyEstimate(
                uncertainty_score=0.5,
                confidence_score=0.5,
                method='direct_uncertainty',
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
            # Try to extract uncertainty with regex
            unc_match = re.search(r'uncertainty["\s:]+(\d+)', content, re.IGNORECASE)
            if unc_match:
                return {'uncertainty': int(unc_match.group(1))}
            return {'uncertainty': 50}

    def supports_endpoint(self, endpoint: Any) -> bool:
        """
        Check if endpoint is supported.

        Direct uncertainty works with any text-generation endpoint.
        """
        return True

    def get_config_defaults(self) -> Dict[str, Any]:
        """Get default configuration."""
        return {
            'prompt_template': self.UNCERTAINTY_PROMPT,
        }
