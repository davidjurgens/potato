"""
Confusion Analyzer for Solo Mode

Enriches confusion matrix data with example instances, LLM reasoning,
and optional root cause / guideline suggestions via LLM.
"""

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ConfusionExample:
    """A single instance that contributed to a confusion pattern."""
    instance_id: str
    text: str  # truncated display text
    llm_reasoning: Optional[str] = None
    llm_confidence: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'instance_id': self.instance_id,
            'text': self.text,
        }
        if self.llm_reasoning is not None:
            result['llm_reasoning'] = self.llm_reasoning
        if self.llm_confidence is not None:
            result['llm_confidence'] = self.llm_confidence
        return result


@dataclass
class ConfusionPattern:
    """An enriched confusion pattern with examples and optional analysis."""
    predicted_label: str
    actual_label: str
    count: int
    percent: float
    examples: List[ConfusionExample] = field(default_factory=list)
    root_cause: Optional[str] = None
    guideline_suggestion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'predicted_label': self.predicted_label,
            'actual_label': self.actual_label,
            'count': self.count,
            'percent': self.percent,
            'examples': [e.to_dict() for e in self.examples],
        }
        if self.root_cause is not None:
            result['root_cause'] = self.root_cause
        if self.guideline_suggestion is not None:
            result['guideline_suggestion'] = self.guideline_suggestion
        return result


class ConfusionAnalyzer:
    """Analyzes confusion patterns and optionally generates root causes / suggestions.

    Enriches the raw confusion matrix from ValidationTracker with example
    instances, LLM reasoning, and optional LLM-powered analysis.
    """

    MAX_TEXT_LENGTH = 200
    MAX_EXAMPLES_PER_PATTERN = 5

    def __init__(self, app_config: Dict[str, Any], solo_config: Any):
        self.app_config = app_config
        self.solo_config = solo_config
        self._endpoint = None

    def analyze(
        self,
        comparison_history: List[Dict[str, Any]],
        predictions: Dict[str, Dict[str, Any]],
        text_getter: Optional[Callable[[str], str]] = None,
    ) -> List[ConfusionPattern]:
        """Build enriched confusion patterns from comparison history.

        Args:
            comparison_history: List of comparison dicts with instance_id,
                human_label, llm_label, agrees fields.
            predictions: Dict of instance_id -> schema_name -> LLMPrediction.
            text_getter: Optional callable(instance_id) -> text string.

        Returns:
            List of ConfusionPattern sorted by count descending.
        """
        ca_config = self.solo_config.confusion_analysis

        # Group disagreements by (llm_label, human_label)
        groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for record in comparison_history:
            if record.get('agrees'):
                continue
            key = (str(record['llm_label']), str(record['human_label']))
            groups[key].append(record)

        # Filter by minimum instance count
        patterns = []
        for (predicted, actual), records in groups.items():
            if len(records) < ca_config.min_instances_for_pattern:
                continue

            total_disagreements = sum(
                1 for r in comparison_history if not r.get('agrees')
            )
            percent = (
                len(records) / total_disagreements * 100
                if total_disagreements > 0 else 0.0
            )

            # Build examples
            examples = []
            for record in records[:self.MAX_EXAMPLES_PER_PATTERN]:
                iid = record['instance_id']
                text = ''
                if text_getter is not None:
                    try:
                        raw = text_getter(iid)
                        text = self._truncate(raw)
                    except Exception:
                        text = ''

                # Get reasoning and confidence from predictions
                reasoning = None
                confidence = None
                if iid in predictions:
                    for schema_preds in predictions[iid].values():
                        pred = schema_preds
                        reasoning = (
                            pred.reasoning
                            if hasattr(pred, 'reasoning')
                            else pred.get('reasoning')
                        )
                        confidence = (
                            pred.confidence_score
                            if hasattr(pred, 'confidence_score')
                            else pred.get('confidence_score')
                        )
                        break

                examples.append(ConfusionExample(
                    instance_id=iid,
                    text=text,
                    llm_reasoning=reasoning,
                    llm_confidence=confidence,
                ))

            patterns.append(ConfusionPattern(
                predicted_label=predicted,
                actual_label=actual,
                count=len(records),
                percent=round(percent, 1),
                examples=examples,
            ))

        # Sort by count descending, limit
        patterns.sort(key=lambda p: p.count, reverse=True)
        return patterns[:ca_config.max_patterns]

    def get_confusion_matrix_data(
        self,
        confusion_matrix: Dict[Tuple[str, str], int],
        labels: List[str],
        label_accuracy: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Build heatmap-ready data from raw confusion matrix.

        Args:
            confusion_matrix: Dict of (predicted, actual) -> count.
            labels: All label names.
            label_accuracy: Optional per-label accuracy dict.

        Returns:
            Dict with labels, cells, max_count, and label_accuracy.
        """
        cells = []
        max_count = 0
        for predicted in labels:
            for actual in labels:
                count = confusion_matrix.get((predicted, actual), 0)
                cells.append({
                    'predicted': predicted,
                    'actual': actual,
                    'count': count,
                })
                if count > max_count:
                    max_count = count

        return {
            'labels': labels,
            'cells': cells,
            'max_count': max_count,
            'label_accuracy': label_accuracy or {},
        }

    def generate_root_cause(self, pattern: ConfusionPattern) -> Optional[str]:
        """Use LLM to explain why a confusion pattern occurs.

        Args:
            pattern: The confusion pattern to analyze.

        Returns:
            Root cause explanation string, or None if unavailable.
        """
        endpoint = self._get_revision_endpoint()
        if endpoint is None:
            return None

        examples_text = "\n".join(
            f"- Instance {e.instance_id}: \"{e.text}\""
            + (f" (LLM reasoning: {e.llm_reasoning})" if e.llm_reasoning else "")
            for e in pattern.examples
        )

        prompt = (
            f"The LLM predicted \"{pattern.predicted_label}\" when the correct "
            f"label was \"{pattern.actual_label}\", {pattern.count} times.\n\n"
            f"Example instances:\n{examples_text}\n\n"
            f"In 2-3 sentences, explain the most likely root cause of this "
            f"confusion. What pattern in the text makes these labels hard to "
            f"distinguish?\n\n"
            f"Respond with JSON:\n"
            f'{{"root_cause": "<your explanation>"}}'
        )

        try:
            response = endpoint.query(prompt)
            data = self._parse_json(response)
            return data.get('root_cause')
        except Exception as e:
            logger.warning(f"Root cause generation failed: {e}")
            return None

    def suggest_guideline(
        self,
        pattern: ConfusionPattern,
        current_prompt: str,
    ) -> Optional[str]:
        """Use LLM to suggest a guideline to disambiguate a confusion pattern.

        Args:
            pattern: The confusion pattern to address.
            current_prompt: The current annotation prompt text.

        Returns:
            Guideline suggestion string, or None if unavailable.
        """
        endpoint = self._get_revision_endpoint()
        if endpoint is None:
            return None

        root_cause = pattern.root_cause or "Unknown"

        prompt = (
            f"An annotation system confuses \"{pattern.predicted_label}\" with "
            f"\"{pattern.actual_label}\" ({pattern.count} times).\n\n"
            f"Root cause: {root_cause}\n\n"
            f"Current annotation prompt (excerpt):\n"
            f"---\n{current_prompt[:1000]}\n---\n\n"
            f"Suggest a concise guideline (1-2 sentences) to add to the prompt "
            f"that would help disambiguate \"{pattern.predicted_label}\" from "
            f"\"{pattern.actual_label}\".\n\n"
            f"Respond with JSON:\n"
            f'{{"suggestion": "<your guideline>"}}'
        )

        try:
            response = endpoint.query(prompt)
            data = self._parse_json(response)
            return data.get('suggestion')
        except Exception as e:
            logger.warning(f"Guideline suggestion failed: {e}")
            return None

    def _get_revision_endpoint(self) -> Optional[Any]:
        """Get or create an AI endpoint for LLM analysis."""
        if self._endpoint is not None:
            return self._endpoint

        try:
            from potato.ai.ai_endpoint import AIEndpointFactory

            models = (
                self.solo_config.revision_models
                or self.solo_config.labeling_models
            )
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
                        endpoint_config['ai_support']['ai_config']['api_key'] = (
                            model_config.api_key
                        )

                    endpoint = AIEndpointFactory.create_endpoint(endpoint_config)
                    if endpoint:
                        self._endpoint = endpoint
                        return endpoint
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Could not create analysis endpoint: {e}")

        return None

    def _truncate(self, text: str) -> str:
        """Truncate text to MAX_TEXT_LENGTH."""
        if not text:
            return ''
        if len(text) <= self.MAX_TEXT_LENGTH:
            return text
        return text[:self.MAX_TEXT_LENGTH] + '...'

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
