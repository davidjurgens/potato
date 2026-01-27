"""
In-Context Learning Prompt Builder

This module builds effective prompts for in-context learning based labeling.
It formats high-confidence examples and target instances into prompts that
elicit accurate label predictions with confidence scores.
"""

import json
import logging
import re
from typing import Dict, List, Any, Tuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from potato.ai.icl_labeler import HighConfidenceExample

logger = logging.getLogger(__name__)


class ICLPromptBuilder:
    """
    Builds effective prompts for in-context learning.

    The prompt structure:
    1. System instructions explaining the task
    2. Schema description and available labels
    3. High-confidence examples with their labels
    4. Target text to label
    5. Output format instructions (JSON with label, confidence, reasoning)
    """

    def __init__(self, max_example_length: int = 500, max_target_length: int = 1000):
        """
        Initialize the prompt builder.

        Args:
            max_example_length: Maximum characters per example text
            max_target_length: Maximum characters for target text
        """
        self.max_example_length = max_example_length
        self.max_target_length = max_target_length

    def build_prompt(
        self,
        schema: Dict[str, Any],
        examples: List['HighConfidenceExample'],
        target_text: str
    ) -> str:
        """
        Build a complete ICL prompt.

        Args:
            schema: Annotation schema dictionary with name, description, labels
            examples: List of high-confidence examples
            target_text: The text to be labeled

        Returns:
            Complete prompt string
        """
        parts = []

        # System instructions
        parts.append(self._build_system_prompt(schema))

        # Examples section
        if examples:
            parts.append("\n## Examples\n")
            parts.append("Here are examples of correctly labeled texts:\n")
            for i, example in enumerate(examples, 1):
                parts.append(self._format_example(example, i))

        # Target text section
        parts.append("\n## Your Task\n")
        parts.append("Now label the following text:\n")
        parts.append(f'Text: "{self._truncate_text(target_text, self.max_target_length)}"\n')

        # Output format instructions
        parts.append(self._build_output_instructions(schema))

        return "\n".join(parts)

    def _build_system_prompt(self, schema: Dict[str, Any]) -> str:
        """Build the system/instruction portion of the prompt."""
        schema_name = schema.get('name', 'unknown')
        description = schema.get('description', 'Label the text according to the schema.')
        labels = self._get_labels_from_schema(schema)
        annotation_type = schema.get('annotation_type', 'radio')

        prompt = f"""You are an expert annotation assistant. Your task is to label text according to a specific annotation schema.

## Schema: {schema_name}

**Description:** {description}

**Available Labels:** {', '.join(labels)}
"""

        # Add type-specific instructions
        if annotation_type == 'radio':
            prompt += "\n**Task Type:** Single-choice classification. Select exactly ONE label.\n"
        elif annotation_type == 'multiselect':
            prompt += "\n**Task Type:** Multi-label classification. Select ALL applicable labels.\n"
        elif annotation_type == 'likert':
            prompt += "\n**Task Type:** Rating scale. Choose the most appropriate rating.\n"

        return prompt

    def _format_example(self, example: 'HighConfidenceExample', index: int) -> str:
        """Format a single example for the prompt."""
        truncated_text = self._truncate_text(example.text, self.max_example_length)

        return f"""
### Example {index}
Text: "{truncated_text}"
Label: **{example.label}**
(Agreement: {example.agreement_score:.0%} from {example.annotator_count} annotators)
"""

    def _build_output_instructions(self, schema: Dict[str, Any]) -> str:
        """Build instructions for the expected output format."""
        labels = self._get_labels_from_schema(schema)
        labels_json = json.dumps(labels)

        return f"""
## Output Format

Respond with a JSON object containing:
- `label`: Your chosen label (must be one of: {labels_json})
- `confidence`: Your confidence score from 0.0 to 1.0
  - 1.0 = Absolutely certain
  - 0.7-0.9 = High confidence
  - 0.5-0.7 = Moderate confidence
  - 0.3-0.5 = Low confidence
  - 0.0-0.3 = Very uncertain
- `reasoning`: Brief explanation for your choice (1-2 sentences)

**Important:**
- Only use labels from the provided list
- Be honest about your confidence - if uncertain, give a lower score
- Base your decision on the examples and schema description

Example response:
```json
{{"label": "example_label", "confidence": 0.85, "reasoning": "The text shows clear indicators of..."}}
```

Now provide your response as JSON:
"""

    def _get_labels_from_schema(self, schema: Dict[str, Any]) -> List[str]:
        """Extract label names from schema definition."""
        labels = schema.get('labels', [])
        result = []
        for label in labels:
            if isinstance(label, str):
                result.append(label)
            elif isinstance(label, dict):
                result.append(label.get('name', str(label)))
        return result

    def _truncate_text(self, text: str, max_length: int) -> str:
        """Truncate text to max length, preserving word boundaries."""
        if len(text) <= max_length:
            return text

        truncated = text[:max_length]
        # Try to break at word boundary
        last_space = truncated.rfind(' ')
        if last_space > max_length * 0.8:
            truncated = truncated[:last_space]

        return truncated + "..."

    def parse_response(
        self,
        response: str,
        schema: Dict[str, Any]
    ) -> Tuple[Optional[str], float, str]:
        """
        Parse the LLM response to extract label, confidence, and reasoning.

        Args:
            response: Raw response from LLM
            schema: Schema for validation

        Returns:
            Tuple of (label, confidence, reasoning) or (None, 0.0, "") on failure
        """
        try:
            # Try to parse as JSON directly
            data = self._extract_json(response)
            if data:
                label = data.get('label', '')
                confidence = float(data.get('confidence', 0.5))
                reasoning = data.get('reasoning', '')

                # Validate label
                valid_labels = self._get_labels_from_schema(schema)
                if label in valid_labels:
                    return label, min(1.0, max(0.0, confidence)), reasoning

                # Try fuzzy matching
                matched = self._fuzzy_match_label(label, valid_labels)
                if matched:
                    return matched, min(1.0, max(0.0, confidence)), reasoning

            # Fallback: try to extract label from text
            return self._extract_label_from_text(response, schema)

        except Exception as e:
            logger.warning(f"Error parsing response: {e}")
            return None, 0.0, ""

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from text, handling markdown code blocks."""
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON in code blocks
        json_patterns = [
            r'```json\s*(.*?)\s*```',
            r'```\s*(.*?)\s*```',
            r'\{[^{}]*"label"[^{}]*\}'
        ]

        for pattern in json_patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    json_str = match.group(1) if match.lastindex else match.group(0)
                    return json.loads(json_str)
                except (json.JSONDecodeError, IndexError):
                    continue

        return None

    def _fuzzy_match_label(self, label: str, valid_labels: List[str]) -> Optional[str]:
        """Try to match label with case-insensitive comparison."""
        label_lower = label.lower().strip()
        for valid in valid_labels:
            if valid.lower().strip() == label_lower:
                return valid
        return None

    def _extract_label_from_text(
        self,
        text: str,
        schema: Dict[str, Any]
    ) -> Tuple[Optional[str], float, str]:
        """Fallback: try to extract label directly from text."""
        valid_labels = self._get_labels_from_schema(schema)
        text_lower = text.lower()

        for label in valid_labels:
            # Look for label mentioned in text
            if label.lower() in text_lower:
                return label, 0.5, "Extracted from response text (low confidence)"

        return None, 0.0, ""


class MultiSelectPromptBuilder(ICLPromptBuilder):
    """
    Specialized prompt builder for multi-select (multi-label) tasks.
    """

    def _build_output_instructions(self, schema: Dict[str, Any]) -> str:
        """Build output instructions for multi-select."""
        labels = self._get_labels_from_schema(schema)
        labels_json = json.dumps(labels)

        return f"""
## Output Format

Respond with a JSON object containing:
- `labels`: Array of selected labels (from: {labels_json})
- `confidence`: Your overall confidence score from 0.0 to 1.0
- `reasoning`: Brief explanation for your choices

Example response:
```json
{{"labels": ["label1", "label2"], "confidence": 0.8, "reasoning": "The text exhibits both..."}}
```

Now provide your response as JSON:
"""

    def parse_response(
        self,
        response: str,
        schema: Dict[str, Any]
    ) -> Tuple[Optional[List[str]], float, str]:
        """Parse multi-select response."""
        try:
            data = self._extract_json(response)
            if data:
                labels = data.get('labels', [])
                confidence = float(data.get('confidence', 0.5))
                reasoning = data.get('reasoning', '')

                valid_labels = self._get_labels_from_schema(schema)
                validated = [l for l in labels if l in valid_labels]

                if validated:
                    return validated, min(1.0, max(0.0, confidence)), reasoning

            return None, 0.0, ""

        except Exception as e:
            logger.warning(f"Error parsing multi-select response: {e}")
            return None, 0.0, ""
