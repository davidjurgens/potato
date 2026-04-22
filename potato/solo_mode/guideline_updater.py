"""
Guideline Updater for Solo Mode

Injects approved edge case rules into the annotation prompt and identifies
instances that should be re-annotated with the improved prompt.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Set

from .edge_case_rules import EdgeCaseCategory

logger = logging.getLogger(__name__)

INJECTION_PROMPT_TEMPLATE = """You are updating annotation guidelines to incorporate newly discovered edge case rules.

Current annotation prompt:
---
{current_prompt}
---

New edge case rules to incorporate:
{rules_text}

Your task: Produce an updated version of the annotation prompt that naturally integrates
these edge case rules. Add them as an "Edge Case Guidelines" section near the end of
the prompt, before any response format instructions. Keep the original prompt intact
and simply append the new guidelines.

Respond with JSON:
{{
    "updated_prompt": "<the full updated prompt text>"
}}
"""


class GuidelineUpdater:
    """Updates annotation prompts with approved edge case rules.

    Handles:
    - Injecting approved rules into the prompt via LLM or direct append
    - Identifying instances for re-annotation based on confidence
    """

    def __init__(
        self,
        app_config: Dict[str, Any],
        solo_config: Any,
    ):
        """Initialize the guideline updater.

        Args:
            app_config: Full application configuration
            solo_config: SoloModeConfig instance
        """
        self.app_config = app_config
        self.solo_config = solo_config
        self._endpoint = None

    def _get_revision_endpoint(self) -> Optional[Any]:
        """Get or create an AI endpoint for prompt revision."""
        if self._endpoint is not None:
            return self._endpoint

        try:
            from potato.ai.ai_endpoint import AIEndpointFactory

            models = self.solo_config.revision_models or self.solo_config.labeling_models
            for model_config in models:
                try:
                    endpoint_config = {
                        'ai_support': {
                            'enabled': True,
                            'endpoint_type': model_config.endpoint_type,
                            'ai_config': {
                                'model': model_config.model,
                                'max_tokens': model_config.max_tokens,
                                'temperature': 0.3,
                            }
                        }
                    }
                    if model_config.api_key:
                        endpoint_config['ai_support']['ai_config']['api_key'] = model_config.api_key
                    if model_config.base_url:
                        endpoint_config['ai_support']['ai_config']['base_url'] = model_config.base_url

                    endpoint = AIEndpointFactory.create_endpoint(endpoint_config)
                    if endpoint:
                        self._endpoint = endpoint
                        return endpoint
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Could not create revision endpoint: {e}")

        return None

    def inject_rules_into_prompt(
        self,
        current_prompt: str,
        approved_categories: List[EdgeCaseCategory],
    ) -> str:
        """Integrate approved edge case rules into the annotation prompt.

        Tries to use the revision model for natural integration. Falls back
        to direct append if the model is unavailable.

        Args:
            current_prompt: The current annotation prompt text
            approved_categories: List of approved categories to incorporate

        Returns:
            Updated prompt text with edge case rules integrated
        """
        if not approved_categories:
            return current_prompt

        rules_text = "\n".join(
            f"- {cat.summary_rule}" for cat in approved_categories
        )

        # Try LLM-assisted integration
        endpoint = self._get_revision_endpoint()
        if endpoint is not None:
            try:
                prompt = INJECTION_PROMPT_TEMPLATE.format(
                    current_prompt=current_prompt,
                    rules_text=rules_text,
                )
                response = endpoint.query(prompt)
                response_data = self._parse_json(response)
                updated = response_data.get('updated_prompt', '')
                if updated:
                    logger.info("Injected rules via LLM revision")
                    return updated
            except Exception as e:
                logger.warning(f"LLM-assisted rule injection failed: {e}")

        # Fallback: direct append
        return self._direct_inject(current_prompt, rules_text)

    def _direct_inject(self, current_prompt: str, rules_text: str) -> str:
        """Directly append edge case guidelines to the prompt."""
        section = f"\n\n## Edge Case Guidelines\n\nThe following edge cases have been identified. Apply these rules when relevant:\n{rules_text}\n"

        # Try to insert before response format instructions
        # Look for common format instruction patterns
        format_markers = [
            "Respond with JSON",
            "respond with json",
            "Output format:",
            "Response format:",
        ]
        for marker in format_markers:
            idx = current_prompt.find(marker)
            if idx > 0:
                return current_prompt[:idx] + section + "\n" + current_prompt[idx:]

        # Otherwise append at end
        return current_prompt + section

    def get_instances_for_reannotation(
        self,
        predictions: Dict[str, Dict[str, Any]],
        old_prompt_version: int,
        reannotation_counts: Optional[Dict[str, int]] = None,
    ) -> List[str]:
        """Get instances that should be re-annotated with the improved prompt.

        Selects instances that:
        - Were labeled with the old prompt version
        - Have confidence below the re-annotation threshold
        - Haven't exceeded max re-annotations

        Args:
            predictions: Dict of instance_id -> schema -> prediction
            old_prompt_version: The prompt version to find instances for
            reannotation_counts: Optional dict tracking per-instance re-annotation count

        Returns:
            List of instance IDs that should be re-annotated
        """
        ecr_config = self.solo_config.edge_case_rules
        threshold = ecr_config.reannotation_confidence_threshold
        max_reannotations = ecr_config.max_reannotations_per_instance
        counts = reannotation_counts or {}

        candidates = []
        for instance_id, schemas in predictions.items():
            for schema_name, pred in schemas.items():
                # Check if labeled with old prompt version
                pred_version = (
                    pred.prompt_version if hasattr(pred, 'prompt_version')
                    else pred.get('prompt_version', 0)
                )
                if pred_version != old_prompt_version:
                    continue

                # Check confidence
                confidence = (
                    pred.confidence_score if hasattr(pred, 'confidence_score')
                    else pred.get('confidence_score', 1.0)
                )
                if confidence >= threshold:
                    continue

                # Check re-annotation limit
                current_count = counts.get(instance_id, 0)
                if current_count >= max_reannotations:
                    continue

                candidates.append(instance_id)
                break  # Only need to check one schema per instance

        logger.info(
            f"Found {len(candidates)} instances for re-annotation "
            f"(old_version={old_prompt_version}, threshold={threshold})"
        )
        return candidates

    def _parse_json(self, response: Any) -> Dict[str, Any]:
        """Parse JSON from an LLM response."""
        if isinstance(response, dict):
            return response
        if hasattr(response, 'model_dump'):
            return response.model_dump()

        content = str(response).strip()
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
        if match:
            content = match.group(1).strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {}
