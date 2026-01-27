"""
Annotation strategies for simulated users.

This module defines different strategies for generating annotations:
- Random: Uniform random selection
- Biased: Weighted selection based on label preferences
- LLM: Use an LLM to generate annotations
- Pattern: Consistent per-user patterns
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple
import random
import logging
import re

from .competence_profiles import CompetenceProfile
from .config import (
    LLMStrategyConfig,
    BiasedStrategyConfig,
    PatternStrategyConfig,
    AnnotationStrategyType,
)

logger = logging.getLogger(__name__)


class AnnotationStrategy(ABC):
    """Abstract base class for annotation strategies.

    Annotation strategies determine how a simulated user generates
    annotations for different schema types.
    """

    @abstractmethod
    def generate_annotation(
        self,
        instance: Dict[str, Any],
        schema: Dict[str, Any],
        competence: CompetenceProfile,
        gold_answer: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate an annotation for the given instance and schema.

        Args:
            instance: The data instance containing text and metadata
            schema: The annotation schema definition
            competence: Competence profile for accuracy modeling
            gold_answer: Gold standard answer if available (for competence)

        Returns:
            Dictionary with annotation data in the format expected by the API
        """
        pass


class RandomStrategy(AnnotationStrategy):
    """Random annotation selection strategy.

    Selects labels uniformly at random. When gold standards are available
    and competence should be correct, uses the gold answer instead.
    """

    def generate_annotation(
        self,
        instance: Dict[str, Any],
        schema: Dict[str, Any],
        competence: CompetenceProfile,
        gold_answer: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate random annotation.

        Args:
            instance: Data instance
            schema: Annotation schema
            competence: Competence profile
            gold_answer: Gold standard if available

        Returns:
            Annotation dictionary
        """
        # Check both 'annotation_type' (config format) and 'type' (API format)
        annotation_type = schema.get("annotation_type") or schema.get("type")
        labels = self._extract_labels(schema)
        schema_name = schema.get("name")

        # If we have gold answer and competence says be correct, use gold
        if gold_answer and schema_name in gold_answer:
            if competence.should_be_correct():
                return self._format_gold_answer(schema_name, gold_answer[schema_name], annotation_type)
            else:
                # Select wrong answer
                correct = gold_answer[schema_name]
                wrong = competence.select_wrong_answer(str(correct), labels)
                return self._format_annotation(schema_name, wrong, annotation_type)

        # No gold standard - just random selection
        return self._generate_by_type(annotation_type, schema, labels, instance)

    def _extract_labels(self, schema: Dict[str, Any]) -> List[str]:
        """Extract label options from schema.

        Args:
            schema: Annotation schema

        Returns:
            List of label names
        """
        labels = schema.get("labels", [])
        if not labels:
            return []

        if isinstance(labels[0], dict):
            return [l.get("name") for l in labels if l.get("name")]
        return [str(l) for l in labels]

    def _format_gold_answer(
        self, schema_name: str, gold_value: Any, annotation_type: str
    ) -> Dict[str, Any]:
        """Format gold answer as annotation.

        Args:
            schema_name: Schema name
            gold_value: Gold standard value
            annotation_type: Type of annotation

        Returns:
            Formatted annotation
        """
        return self._format_annotation(schema_name, gold_value, annotation_type)

    def _format_annotation(
        self, schema_name: str, value: Any, annotation_type: str
    ) -> Dict[str, Any]:
        """Format a value as an annotation.

        Args:
            schema_name: Schema name
            value: Annotation value
            annotation_type: Type of annotation

        Returns:
            Formatted annotation dictionary in the format expected by the server
            (schema:value -> "on" for selection types)
        """
        if annotation_type == "multiselect":
            if isinstance(value, list):
                return {f"{schema_name}:{v}": "on" for v in value}
            return {f"{schema_name}:{value}": "on"}
        elif annotation_type in ["radio", "likert"]:
            # Selection-based types use schema:value format
            return {f"{schema_name}:{value}": "on"}
        elif annotation_type in ["slider", "number"]:
            # Numeric types store the value
            return {f"{schema_name}:{value}": str(value)}
        elif annotation_type in ["text", "textbox"]:
            # Text types store the text content
            return {f"{schema_name}:text": str(value)}
        else:
            # Default: use schema:value format
            return {f"{schema_name}:{value}": "on"}

    def _generate_by_type(
        self,
        annotation_type: str,
        schema: Dict[str, Any],
        labels: List[str],
        instance: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generate annotation based on schema type.

        Args:
            annotation_type: Type of annotation
            schema: Full schema definition
            labels: Available labels
            instance: Data instance

        Returns:
            Generated annotation
        """
        schema_name = schema.get("name")

        if annotation_type == "radio":
            if labels:
                selected_label = random.choice(labels)
                # Format as "schema:label": "on" to match frontend format
                return {f"{schema_name}:{selected_label}": "on"}
            return {}

        elif annotation_type == "multiselect":
            if labels:
                # Select 1-3 random labels
                num_selections = random.randint(1, min(3, len(labels)))
                selections = random.sample(labels, num_selections)
                return {f"{schema_name}:{label}": "on" for label in selections}
            return {}

        elif annotation_type == "likert":
            size = schema.get("size", 5)
            selected_value = str(random.randint(1, size))
            # Format as "schema:value": "on" to match frontend format
            return {f"{schema_name}:{selected_value}": "on"}

        elif annotation_type == "slider":
            min_val = schema.get("min_value", schema.get("min", 0))
            max_val = schema.get("max_value", schema.get("max", 100))
            selected_value = str(random.randint(min_val, max_val))
            # Format as "schema:value": "value" for slider
            return {f"{schema_name}:{selected_value}": selected_value}

        elif annotation_type in ["text", "textbox"]:
            text_response = self._generate_text_response(instance)
            # Format as "schema:text": "value" for textbox
            return {f"{schema_name}:text": text_response}

        elif annotation_type == "number":
            min_val = schema.get("min_value", 0)
            max_val = schema.get("max_value", 100)
            selected_value = str(random.randint(min_val, max_val))
            # Format as "schema:value": "value"
            return {f"{schema_name}:{selected_value}": selected_value}

        elif annotation_type == "span":
            return self._generate_span_annotation(instance, schema, labels)

        else:
            logger.warning(f"Unknown annotation type: {annotation_type}")
            if labels:
                return {schema_name: random.choice(labels)}
            return {}

    def _generate_text_response(self, instance: Dict[str, Any]) -> str:
        """Generate a placeholder text response.

        Args:
            instance: Data instance

        Returns:
            Generated text
        """
        responses = [
            "Simulated annotation response.",
            "This is a test response.",
            "Generated text for testing purposes.",
            "Sample annotation text.",
        ]
        return random.choice(responses)

    def _generate_span_annotation(
        self,
        instance: Dict[str, Any],
        schema: Dict[str, Any],
        labels: List[str],
    ) -> Dict[str, Any]:
        """Generate span annotations for text.

        Args:
            instance: Data instance with text
            schema: Span annotation schema
            labels: Available span labels

        Returns:
            Span annotation dictionary
        """
        text = instance.get("text", "")
        if not text or not labels:
            return {}

        words = text.split()
        if len(words) < 2:
            return {}

        # Generate 0-3 random spans
        num_spans = random.randint(0, min(3, len(words) // 2))
        schema_name = schema.get("name", "spans")
        annotations = {}

        for _ in range(num_spans):
            start_word_idx = random.randint(0, len(words) - 2)
            end_word_idx = random.randint(
                start_word_idx + 1, min(start_word_idx + 5, len(words))
            )

            # Calculate character offsets
            start_char = sum(len(w) + 1 for w in words[:start_word_idx])
            end_char = sum(len(w) + 1 for w in words[:end_word_idx]) - 1

            label = random.choice(labels)
            span_key = f"{schema_name}:{label}:{start_char}:{end_char}"
            annotations[span_key] = "true"

        return annotations


class BiasedStrategy(AnnotationStrategy):
    """Annotation strategy with configurable label biases.

    Selects labels according to configured weights, allowing simulation
    of annotators with specific label preferences.
    """

    def __init__(self, config: BiasedStrategyConfig):
        """Initialize biased strategy.

        Args:
            config: Configuration with label weights
        """
        self.config = config
        self.random_strategy = RandomStrategy()

    def generate_annotation(
        self,
        instance: Dict[str, Any],
        schema: Dict[str, Any],
        competence: CompetenceProfile,
        gold_answer: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate biased annotation.

        Args:
            instance: Data instance
            schema: Annotation schema
            competence: Competence profile
            gold_answer: Gold standard if available

        Returns:
            Annotation dictionary
        """
        # If gold answer available and competence says be correct, use it
        if gold_answer and competence.should_be_correct():
            schema_name = schema.get("name")
            if schema_name in gold_answer:
                annotation_type = schema.get("annotation_type") or schema.get("type")
                return self.random_strategy._format_gold_answer(
                    schema_name, gold_answer[schema_name], annotation_type
                )

        annotation_type = schema.get("annotation_type") or schema.get("type")
        labels = self.random_strategy._extract_labels(schema)
        schema_name = schema.get("name")

        if annotation_type in ["radio", "multiselect"] and labels:
            # Use weighted selection based on bias config
            weights = [self.config.label_weights.get(l, 1.0) for l in labels]
            total = sum(weights)
            if total > 0:
                weights = [w / total for w in weights]
            else:
                weights = [1.0 / len(labels)] * len(labels)

            selected = random.choices(labels, weights=weights, k=1)[0]

            # Use consistent schema:value format for all selection types
            return {f"{schema_name}:{selected}": "on"}

        # Fall back to random for other types
        return self.random_strategy.generate_annotation(
            instance, schema, competence, gold_answer
        )


class LLMStrategy(AnnotationStrategy):
    """LLM-powered annotation strategy.

    Uses the existing potato.ai infrastructure to generate realistic
    annotations based on text content.
    """

    def __init__(self, config: LLMStrategyConfig):
        """Initialize LLM strategy.

        Args:
            config: LLM configuration
        """
        self.config = config
        self.endpoint = self._create_endpoint()
        self.random_strategy = RandomStrategy()

    def _create_endpoint(self):
        """Create LLM endpoint using existing infrastructure.

        Returns:
            AI endpoint or None if creation fails
        """
        try:
            from potato.ai.ai_endpoint import AIEndpointFactory

            ai_config = {
                "ai_support": {
                    "enabled": True,
                    "endpoint_type": self.config.endpoint_type,
                    "ai_config": {
                        "model": self.config.model,
                        "api_key": self.config.api_key,
                        "max_tokens": self.config.max_tokens,
                        "temperature": self.config.temperature,
                    },
                }
            }

            if self.config.base_url:
                ai_config["ai_support"]["ai_config"]["base_url"] = self.config.base_url

            return AIEndpointFactory.create_endpoint(ai_config)

        except Exception as e:
            logger.warning(f"Failed to create LLM endpoint: {e}")
            return None

    def generate_annotation(
        self,
        instance: Dict[str, Any],
        schema: Dict[str, Any],
        competence: CompetenceProfile,
        gold_answer: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate LLM-based annotation.

        Args:
            instance: Data instance
            schema: Annotation schema
            competence: Competence profile
            gold_answer: Gold standard if available

        Returns:
            Annotation dictionary
        """
        if not self.endpoint:
            logger.warning("LLM endpoint not available, falling back to random")
            return self.random_strategy.generate_annotation(
                instance, schema, competence, gold_answer
            )

        try:
            annotation_type = schema.get("annotation_type") or schema.get("type")
            labels = self.random_strategy._extract_labels(schema)
            schema_name = schema.get("name")
            description = schema.get("description", "")
            text = instance.get("text", "")

            # Build prompt for LLM
            prompt = self._build_prompt(text, labels, description, annotation_type)

            # Query LLM
            result = self.endpoint.query(prompt, None)

            # Add noise if configured
            if self.config.add_noise and random.random() < self.config.noise_rate:
                logger.debug("Adding noise to LLM response")
                return self.random_strategy.generate_annotation(
                    instance, schema, competence, gold_answer
                )

            # Parse result
            parsed = self._parse_llm_result(result, labels, schema_name, annotation_type)
            if parsed:
                return parsed

            # Fallback to random
            return self.random_strategy.generate_annotation(
                instance, schema, competence, gold_answer
            )

        except Exception as e:
            logger.warning(f"LLM annotation failed: {e}")
            return self.random_strategy.generate_annotation(
                instance, schema, competence, gold_answer
            )

    def _build_prompt(
        self,
        text: str,
        labels: List[str],
        description: str,
        annotation_type: str,
    ) -> str:
        """Build prompt for LLM.

        Args:
            text: Text to annotate
            labels: Available labels
            description: Task description
            annotation_type: Type of annotation

        Returns:
            Prompt string
        """
        labels_str = ", ".join(labels)

        if annotation_type in ["radio", "multiselect"]:
            prompt = f"""You are an annotator. Given the following text, select the most appropriate label.

Task: {description if description else 'Classify the text'}
Labels: {labels_str}

Text: {text[:500]}

Respond with ONLY the label name, nothing else."""
        elif annotation_type == "likert":
            prompt = f"""You are an annotator. Rate the following text on a scale.

Task: {description if description else 'Rate the text'}

Text: {text[:500]}

Respond with ONLY a number from 1-5, nothing else."""
        else:
            prompt = f"""You are an annotator. Analyze the following text.

Task: {description if description else 'Analyze the text'}

Text: {text[:500]}

Respond briefly."""

        return prompt

    def _parse_llm_result(
        self,
        result: Any,
        labels: List[str],
        schema_name: str,
        annotation_type: str,
    ) -> Optional[Dict[str, Any]]:
        """Parse LLM result into annotation format.

        Args:
            result: LLM response
            labels: Available labels
            schema_name: Schema name
            annotation_type: Type of annotation

        Returns:
            Parsed annotation or None
        """
        if result is None:
            return None

        # Convert to string
        result_str = str(result).strip().lower()

        if annotation_type in ["radio", "multiselect"]:
            # Try to match a label
            for label in labels:
                if label.lower() in result_str or result_str in label.lower():
                    if annotation_type == "radio":
                        return {schema_name: label}
                    else:
                        return {f"{schema_name}:{label}": "on"}

        elif annotation_type == "likert":
            # Try to extract a number
            numbers = re.findall(r"\d+", result_str)
            if numbers:
                return {schema_name: numbers[0]}

        elif annotation_type in ["text", "textbox"]:
            return {schema_name: str(result)[:500]}

        return None


class PatternStrategy(AnnotationStrategy):
    """Pattern-based annotation strategy for consistent user behavior.

    Allows defining specific behavior patterns per user for testing
    scenarios that require consistent annotation patterns.
    """

    def __init__(self, config: PatternStrategyConfig, user_id: str):
        """Initialize pattern strategy.

        Args:
            config: Pattern configuration
            user_id: User ID for pattern lookup
        """
        self.config = config
        self.user_id = user_id
        self.user_pattern = config.patterns.get(user_id, {})
        self.random_strategy = RandomStrategy()

    def generate_annotation(
        self,
        instance: Dict[str, Any],
        schema: Dict[str, Any],
        competence: CompetenceProfile,
        gold_answer: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate pattern-based annotation.

        Args:
            instance: Data instance
            schema: Annotation schema
            competence: Competence profile
            gold_answer: Gold standard if available

        Returns:
            Annotation dictionary
        """
        preferred_label = self.user_pattern.get("preferred_label")
        bias_strength = self.user_pattern.get("bias_strength", 0.5)

        # Check for keyword patterns
        text = instance.get("text", "").lower()
        keyword_labels = self.user_pattern.get("keywords", {})
        for keyword, label in keyword_labels.items():
            if keyword.lower() in text:
                return self.random_strategy._format_annotation(
                    schema.get("name"), label, schema.get("annotation_type")
                )

        # Use preferred label with configured probability
        if preferred_label and random.random() < bias_strength:
            labels = self.random_strategy._extract_labels(schema)
            if preferred_label in labels:
                return self.random_strategy._format_annotation(
                    schema.get("name"),
                    preferred_label,
                    schema.get("annotation_type"),
                )

        # Fall back to random
        return self.random_strategy.generate_annotation(
            instance, schema, competence, gold_answer
        )


class GoldStandardStrategy(AnnotationStrategy):
    """Strategy that uses gold standard answers when available.

    This is primarily useful for testing quality control systems
    by providing known correct annotations.
    """

    def __init__(self):
        self.random_strategy = RandomStrategy()

    def generate_annotation(
        self,
        instance: Dict[str, Any],
        schema: Dict[str, Any],
        competence: CompetenceProfile,
        gold_answer: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate annotation from gold standard.

        Args:
            instance: Data instance
            schema: Annotation schema
            competence: Competence profile (determines if we use gold)
            gold_answer: Gold standard if available

        Returns:
            Annotation dictionary
        """
        schema_name = schema.get("name")
        annotation_type = schema.get("annotation_type") or schema.get("type")

        if gold_answer and schema_name in gold_answer:
            # Use competence to decide if we get it right
            if competence.should_be_correct():
                return self.random_strategy._format_gold_answer(
                    schema_name, gold_answer[schema_name], annotation_type
                )
            else:
                # Select wrong answer
                labels = self.random_strategy._extract_labels(schema)
                correct = str(gold_answer[schema_name])
                wrong = competence.select_wrong_answer(correct, labels)
                return self.random_strategy._format_annotation(
                    schema_name, wrong, annotation_type
                )

        # No gold standard - fall back to random
        return self.random_strategy.generate_annotation(
            instance, schema, competence, gold_answer
        )


def create_strategy(
    strategy_type: AnnotationStrategyType,
    llm_config: Optional[LLMStrategyConfig] = None,
    biased_config: Optional[BiasedStrategyConfig] = None,
    pattern_config: Optional[PatternStrategyConfig] = None,
    user_id: str = "",
) -> AnnotationStrategy:
    """Factory function to create annotation strategies.

    Args:
        strategy_type: Type of strategy to create
        llm_config: LLM configuration (for LLM strategy)
        biased_config: Bias configuration (for biased strategy)
        pattern_config: Pattern configuration (for pattern strategy)
        user_id: User ID (for pattern strategy)

    Returns:
        AnnotationStrategy instance
    """
    if strategy_type == AnnotationStrategyType.RANDOM:
        return RandomStrategy()

    elif strategy_type == AnnotationStrategyType.BIASED:
        if biased_config:
            return BiasedStrategy(biased_config)
        return RandomStrategy()

    elif strategy_type == AnnotationStrategyType.LLM:
        if llm_config:
            return LLMStrategy(llm_config)
        logger.warning("LLM strategy requested but no config provided, using random")
        return RandomStrategy()

    elif strategy_type == AnnotationStrategyType.PATTERN:
        if pattern_config:
            return PatternStrategy(pattern_config, user_id)
        return RandomStrategy()

    elif strategy_type == AnnotationStrategyType.GOLD_STANDARD:
        return GoldStandardStrategy()

    else:
        return RandomStrategy()
