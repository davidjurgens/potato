"""
Labeling Function Extraction and Application

Inspired by ALCHEmist (NeurIPS 2024): extracts reusable labeling functions
from high-confidence LLM predictions to label instances without API calls.

A labeling function encodes a pattern like:
  "When text contains 'love it' -> positive (confidence: 0.95)"

These functions are extracted from LLM reasoning on high-confidence predictions,
then applied to unlabeled instances via majority voting.
"""

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ABSTAIN = "__ABSTAIN__"


@dataclass
class LabelingFunction:
    """A reusable labeling function extracted from LLM patterns.

    Each function encodes a condition-label mapping discovered from
    high-confidence LLM predictions.
    """
    id: str
    pattern_text: str           # Human-readable pattern description
    condition: str              # The condition part (e.g., "text contains 'great'")
    label: str                  # The label to assign when condition matches
    confidence: float           # Source LLM confidence when pattern was discovered
    source_instance_ids: List[str] = field(default_factory=list)
    coverage: int = 0           # Number of instances this function matched
    accuracy: Optional[float] = None  # Accuracy against human labels if known
    enabled: bool = True
    created_at: str = ""
    extracted_from_reasoning: str = ""  # Original LLM reasoning snippet

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'id': self.id,
            'pattern_text': self.pattern_text,
            'condition': self.condition,
            'label': self.label,
            'confidence': self.confidence,
            'source_instance_ids': self.source_instance_ids,
            'coverage': self.coverage,
            'accuracy': self.accuracy,
            'enabled': self.enabled,
            'created_at': self.created_at,
            'extracted_from_reasoning': self.extracted_from_reasoning,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LabelingFunction':
        """Deserialize from dictionary."""
        return cls(
            id=data['id'],
            pattern_text=data['pattern_text'],
            condition=data['condition'],
            label=data['label'],
            confidence=data.get('confidence', 0.0),
            source_instance_ids=data.get('source_instance_ids', []),
            coverage=data.get('coverage', 0),
            accuracy=data.get('accuracy'),
            enabled=data.get('enabled', True),
            created_at=data.get('created_at', ''),
            extracted_from_reasoning=data.get('extracted_from_reasoning', ''),
        )


@dataclass
class LabelingFunctionVote:
    """A vote from a labeling function for a specific instance."""
    function_id: str
    label: str
    confidence: float


@dataclass
class ApplyResult:
    """Result of applying labeling functions to an instance."""
    instance_id: str
    label: Optional[str] = None
    votes: List[LabelingFunctionVote] = field(default_factory=list)
    abstained: bool = True
    vote_agreement: float = 0.0  # Fraction of votes that agree on the label

    def to_dict(self) -> Dict[str, Any]:
        return {
            'instance_id': self.instance_id,
            'label': self.label,
            'abstained': self.abstained,
            'vote_agreement': self.vote_agreement,
            'num_votes': len(self.votes),
        }


EXTRACTION_PROMPT = """Analyze the following high-confidence LLM predictions and extract reusable labeling patterns.

For each prediction, the LLM was highly confident about its label. Extract patterns that could be applied to new instances without calling the LLM.

Predictions:
{predictions_text}

Extract labeling functions as a JSON array. Each function should have:
- "pattern_text": A human-readable description of the pattern
- "condition": A simple text-matching condition (e.g., "text contains 'keyword'", "text starts with 'pattern'", "text mentions sentiment words like 'great', 'love'")
- "label": The label to assign when the condition matches
- "keywords": List of keywords/phrases that trigger this pattern

Return ONLY a JSON array of objects. Example:
[
  {{
    "pattern_text": "Positive sentiment keywords like 'love', 'great', 'amazing'",
    "condition": "text contains positive sentiment keywords",
    "label": "positive",
    "keywords": ["love", "great", "amazing", "excellent", "wonderful"]
  }}
]"""


class LabelingFunctionExtractor:
    """Extracts labeling functions from high-confidence LLM predictions.

    Analyzes patterns in LLM reasoning to discover reusable rules
    that can label future instances without API calls.
    """

    def __init__(self, app_config: Dict, solo_config):
        self._app_config = app_config
        self._solo_config = solo_config
        self._lf_config = solo_config.labeling_functions
        self._endpoint = None

    def extract_from_predictions(
        self,
        predictions: List[Dict[str, Any]],
    ) -> List[LabelingFunction]:
        """Extract labeling functions from high-confidence predictions.

        Args:
            predictions: List of dicts with 'instance_id', 'text',
                'predicted_label', 'confidence', 'reasoning'.

        Returns:
            List of extracted LabelingFunction objects.
        """
        if not predictions:
            return []

        # Filter to high-confidence predictions
        min_conf = self._lf_config.min_confidence
        high_conf = [p for p in predictions if p.get('confidence', 0) >= min_conf]

        if not high_conf:
            return []

        # Group by label
        by_label: Dict[str, List[Dict]] = {}
        for p in high_conf:
            label = str(p.get('predicted_label', ''))
            by_label.setdefault(label, []).append(p)

        # Try LLM-assisted extraction first
        functions = self._extract_with_llm(high_conf)

        # Fallback to keyword-based extraction if LLM fails
        if not functions:
            functions = self._extract_keyword_patterns(by_label)

        # Limit to max_functions
        max_fns = self._lf_config.max_functions
        if len(functions) > max_fns:
            # Keep highest-confidence functions
            functions.sort(key=lambda f: f.confidence, reverse=True)
            functions = functions[:max_fns]

        return functions

    def _extract_with_llm(
        self, predictions: List[Dict[str, Any]]
    ) -> List[LabelingFunction]:
        """Use LLM to extract labeling functions from prediction patterns."""
        endpoint = self._get_endpoint()
        if endpoint is None:
            return []

        # Build prompt with prediction examples (limit to 20 for context)
        sample = predictions[:20]
        pred_lines = []
        for p in sample:
            text = str(p.get('text', ''))[:200]
            pred_lines.append(
                f"- Text: \"{text}\"\n"
                f"  Label: {p.get('predicted_label')} "
                f"(confidence: {p.get('confidence', 0):.2f})\n"
                f"  Reasoning: {p.get('reasoning', 'N/A')}"
            )

        prompt = EXTRACTION_PROMPT.format(
            predictions_text="\n\n".join(pred_lines)
        )

        try:
            response = endpoint.query(prompt)
            parsed = self._parse_json_array(response)
            if not parsed:
                return []

            functions = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                pattern_text = item.get('pattern_text', '')
                condition = item.get('condition', '')
                label = item.get('label', '')
                keywords = item.get('keywords', [])

                if not label or (not condition and not keywords):
                    continue

                # Find source instances matching this pattern
                source_ids = []
                for p in predictions:
                    if str(p.get('predicted_label', '')) == label:
                        source_ids.append(p['instance_id'])
                        if len(source_ids) >= 5:
                            break

                # Compute average confidence for matching predictions
                matching_confs = [
                    p['confidence'] for p in predictions
                    if str(p.get('predicted_label', '')) == label
                ]
                avg_conf = (
                    sum(matching_confs) / len(matching_confs)
                    if matching_confs else 0.0
                )

                fn = LabelingFunction(
                    id=f"lf_{uuid.uuid4().hex[:8]}",
                    pattern_text=pattern_text,
                    condition=condition,
                    label=label,
                    confidence=avg_conf,
                    source_instance_ids=source_ids,
                    extracted_from_reasoning=', '.join(keywords) if keywords else condition,
                )
                functions.append(fn)

            logger.info(f"LLM extracted {len(functions)} labeling functions")
            return functions

        except Exception as e:
            logger.warning(f"LLM extraction failed: {e}")
            return []

    def _extract_keyword_patterns(
        self, by_label: Dict[str, List[Dict]]
    ) -> List[LabelingFunction]:
        """Fallback: extract keyword patterns from prediction texts.

        Groups predictions by label and finds common words/phrases
        that appear frequently in texts with the same label.
        """
        functions = []

        for label, preds in by_label.items():
            if len(preds) < self._lf_config.min_coverage:
                continue

            # Collect all words from texts for this label
            word_counts: Dict[str, int] = {}
            word_instances: Dict[str, List[str]] = {}
            for p in preds:
                text = str(p.get('text', '')).lower()
                words = set(re.findall(r'\b\w{3,}\b', text))
                for w in words:
                    word_counts[w] = word_counts.get(w, 0) + 1
                    word_instances.setdefault(w, []).append(p['instance_id'])

            # Find words that appear in >= min_coverage predictions
            min_cov = self._lf_config.min_coverage
            common_words = {
                w: c for w, c in word_counts.items()
                if c >= min_cov
            }

            if not common_words:
                continue

            # Filter out very common words (> 80% of all predictions)
            total = len(preds)
            significant = {
                w: c for w, c in common_words.items()
                if c <= total * 0.8
            }

            if not significant:
                continue

            # Take top keywords by frequency
            top_keywords = sorted(
                significant.items(), key=lambda x: x[1], reverse=True
            )[:5]

            keywords = [w for w, _ in top_keywords]
            avg_conf = (
                sum(p.get('confidence', 0) for p in preds) / len(preds)
            )
            source_ids = [p['instance_id'] for p in preds[:5]]

            fn = LabelingFunction(
                id=f"lf_{uuid.uuid4().hex[:8]}",
                pattern_text=(
                    f"Text containing keywords like "
                    f"'{', '.join(keywords)}' -> {label}"
                ),
                condition=f"text contains any of: {', '.join(keywords)}",
                label=label,
                confidence=avg_conf,
                source_instance_ids=source_ids,
                coverage=len(preds),
                extracted_from_reasoning=', '.join(keywords),
            )
            functions.append(fn)

        return functions

    def _get_endpoint(self):
        """Get or create an AI endpoint for extraction."""
        if self._endpoint is not None:
            return self._endpoint

        try:
            from potato.ai.ai_endpoint import AIEndpointFactory

            models = (
                self._solo_config.revision_models
                or self._solo_config.labeling_models
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
            logger.warning(f"Could not create extraction endpoint: {e}")

        return None

    def _parse_json_array(self, response: str) -> Optional[list]:
        """Parse a JSON array from LLM response."""
        import json

        if not response:
            return None

        # Try direct parse
        text = response.strip()
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result
        except (json.JSONDecodeError, TypeError):
            pass

        # Try extracting from markdown code fence
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(1).strip())
                if isinstance(result, list):
                    return result
            except (json.JSONDecodeError, TypeError):
                pass

        # Try finding array brackets
        start = text.find('[')
        end = text.rfind(']')
        if start >= 0 and end > start:
            try:
                result = json.loads(text[start:end + 1])
                if isinstance(result, list):
                    return result
            except (json.JSONDecodeError, TypeError):
                pass

        return None


class LabelingFunctionApplier:
    """Applies labeling functions to instances for weak supervision.

    Uses majority voting among matching labeling functions to assign labels
    without calling the LLM.
    """

    def __init__(self, vote_threshold: float = 0.5):
        self._vote_threshold = vote_threshold

    def apply(
        self,
        instance_id: str,
        text: str,
        functions: List[LabelingFunction],
    ) -> ApplyResult:
        """Apply all enabled labeling functions to an instance.

        Args:
            instance_id: The instance identifier.
            text: The instance text.
            functions: List of labeling functions to try.

        Returns:
            ApplyResult with the voted label or abstention.
        """
        votes: List[LabelingFunctionVote] = []
        text_lower = text.lower()

        for fn in functions:
            if not fn.enabled:
                continue

            if self._matches(fn, text_lower):
                votes.append(LabelingFunctionVote(
                    function_id=fn.id,
                    label=fn.label,
                    confidence=fn.confidence,
                ))

        if not votes:
            return ApplyResult(instance_id=instance_id, abstained=True)

        # Majority vote weighted by confidence
        label_scores: Dict[str, float] = {}
        for v in votes:
            label_scores[v.label] = label_scores.get(v.label, 0) + v.confidence

        # Find winning label
        best_label = max(label_scores, key=label_scores.get)
        total_score = sum(label_scores.values())
        agreement = label_scores[best_label] / total_score if total_score > 0 else 0

        # Check if agreement meets threshold
        if agreement < self._vote_threshold:
            return ApplyResult(
                instance_id=instance_id,
                votes=votes,
                abstained=True,
                vote_agreement=agreement,
            )

        return ApplyResult(
            instance_id=instance_id,
            label=best_label,
            votes=votes,
            abstained=False,
            vote_agreement=agreement,
        )

    def apply_batch(
        self,
        instances: List[Dict[str, str]],
        functions: List[LabelingFunction],
    ) -> List[ApplyResult]:
        """Apply labeling functions to a batch of instances.

        Args:
            instances: List of dicts with 'instance_id' and 'text'.
            functions: List of labeling functions.

        Returns:
            List of ApplyResult, one per instance.
        """
        enabled = [f for f in functions if f.enabled]
        if not enabled:
            return [
                ApplyResult(instance_id=inst['instance_id'], abstained=True)
                for inst in instances
            ]

        return [
            self.apply(inst['instance_id'], inst['text'], enabled)
            for inst in instances
        ]

    def _matches(self, fn: LabelingFunction, text_lower: str) -> bool:
        """Check if a labeling function matches the given text.

        Uses keyword matching from the function's extracted_from_reasoning
        and condition fields.
        """
        # Extract keywords from the function
        keywords = self._get_keywords(fn)

        if not keywords:
            return False

        # Check if any keyword appears in the text
        return any(kw in text_lower for kw in keywords)

    def _get_keywords(self, fn: LabelingFunction) -> List[str]:
        """Extract lowercase keywords from a labeling function."""
        keywords = []

        # Parse keywords from extracted_from_reasoning (comma-separated)
        reasoning = fn.extracted_from_reasoning
        if reasoning:
            parts = [p.strip().lower() for p in reasoning.split(',')]
            keywords.extend(p for p in parts if p and len(p) >= 2)

        # Parse keywords from condition if it has "contains" pattern
        condition = fn.condition.lower()
        # Match patterns like "text contains 'word'" or "any of: word1, word2"
        contains_match = re.findall(r"'([^']+)'", condition)
        if contains_match:
            keywords.extend(w.lower() for w in contains_match)

        any_of_match = re.search(r'any of:\s*(.+)', condition)
        if any_of_match:
            parts = [p.strip().lower() for p in any_of_match.group(1).split(',')]
            keywords.extend(p for p in parts if p and len(p) >= 2)

        return keywords


class LabelingFunctionManager:
    """Manages the lifecycle of labeling functions.

    Handles extraction, storage, application, and statistics tracking.
    """

    def __init__(self, app_config: Dict, solo_config):
        self._app_config = app_config
        self._solo_config = solo_config
        self._lf_config = solo_config.labeling_functions
        self._functions: Dict[str, LabelingFunction] = {}
        self._extractor = LabelingFunctionExtractor(app_config, solo_config)
        self._applier = LabelingFunctionApplier(
            vote_threshold=self._lf_config.vote_threshold
        )
        self._instances_labeled: int = 0
        self._instances_abstained: int = 0

    @property
    def enabled(self) -> bool:
        return self._lf_config.enabled

    def get_all_functions(self) -> List[LabelingFunction]:
        """Get all labeling functions."""
        return list(self._functions.values())

    def get_enabled_functions(self) -> List[LabelingFunction]:
        """Get only enabled labeling functions."""
        return [f for f in self._functions.values() if f.enabled]

    def get_function(self, function_id: str) -> Optional[LabelingFunction]:
        """Get a specific labeling function by ID."""
        return self._functions.get(function_id)

    def add_function(self, fn: LabelingFunction) -> None:
        """Add a labeling function."""
        self._functions[fn.id] = fn

    def toggle_function(self, function_id: str) -> Optional[bool]:
        """Toggle a function's enabled state. Returns new state or None."""
        fn = self._functions.get(function_id)
        if fn is None:
            return None
        fn.enabled = not fn.enabled
        return fn.enabled

    def remove_function(self, function_id: str) -> bool:
        """Remove a labeling function."""
        return self._functions.pop(function_id, None) is not None

    def extract_functions(
        self,
        predictions: List[Dict[str, Any]],
    ) -> List[LabelingFunction]:
        """Extract new labeling functions from predictions.

        Args:
            predictions: List of dicts with instance_id, text,
                predicted_label, confidence, reasoning.

        Returns:
            List of newly extracted functions.
        """
        new_fns = self._extractor.extract_from_predictions(predictions)

        for fn in new_fns:
            self._functions[fn.id] = fn

        if new_fns:
            logger.info(
                f"Extracted {len(new_fns)} labeling functions "
                f"(total: {len(self._functions)})"
            )

        return new_fns

    def try_label(
        self, instance_id: str, text: str
    ) -> Optional[ApplyResult]:
        """Try to label an instance using labeling functions.

        Returns:
            ApplyResult if a label was assigned, None if abstained or disabled.
        """
        if not self._lf_config.enabled:
            return None

        enabled = self.get_enabled_functions()
        if not enabled:
            return None

        result = self._applier.apply(instance_id, text, enabled)

        if result.abstained:
            self._instances_abstained += 1
            return None

        self._instances_labeled += 1

        # Update coverage counts
        for vote in result.votes:
            fn = self._functions.get(vote.function_id)
            if fn:
                fn.coverage += 1

        return result

    def apply_batch(
        self, instances: List[Dict[str, str]]
    ) -> Tuple[List[ApplyResult], List[Dict[str, str]]]:
        """Apply labeling functions to a batch, returning labeled and remaining.

        Args:
            instances: List of dicts with instance_id and text.

        Returns:
            Tuple of (labeled_results, unlabeled_instances).
        """
        if not self._lf_config.enabled:
            return [], instances

        enabled = self.get_enabled_functions()
        if not enabled:
            return [], instances

        labeled = []
        remaining = []

        for inst in instances:
            result = self._applier.apply(
                inst['instance_id'], inst['text'], enabled
            )
            if result.abstained:
                remaining.append(inst)
                self._instances_abstained += 1
            else:
                labeled.append(result)
                self._instances_labeled += 1
                # Update coverage
                for vote in result.votes:
                    fn = self._functions.get(vote.function_id)
                    if fn:
                        fn.coverage += 1

        return labeled, remaining

    def get_stats(self) -> Dict[str, Any]:
        """Get labeling function statistics."""
        functions = list(self._functions.values())
        enabled = [f for f in functions if f.enabled]

        return {
            'enabled': self._lf_config.enabled,
            'total_functions': len(functions),
            'enabled_functions': len(enabled),
            'instances_labeled': self._instances_labeled,
            'instances_abstained': self._instances_abstained,
            'total_coverage': sum(f.coverage for f in functions),
            'avg_confidence': (
                sum(f.confidence for f in functions) / len(functions)
                if functions else 0.0
            ),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize state for persistence."""
        return {
            'functions': [f.to_dict() for f in self._functions.values()],
            'instances_labeled': self._instances_labeled,
            'instances_abstained': self._instances_abstained,
        }

    def load_state(self, data: Dict[str, Any]) -> None:
        """Restore state from persisted data."""
        self._functions = {}
        for fn_data in data.get('functions', []):
            fn = LabelingFunction.from_dict(fn_data)
            self._functions[fn.id] = fn
        self._instances_labeled = data.get('instances_labeled', 0)
        self._instances_abstained = data.get('instances_abstained', 0)
