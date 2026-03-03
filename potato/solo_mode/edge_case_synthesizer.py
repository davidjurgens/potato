"""
Edge Case Synthesizer for Solo Mode

This module generates synthetic edge case examples to test and refine
annotation prompts. It identifies boundary conditions and ambiguous cases
to help improve prompt quality before large-scale annotation.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
import threading

logger = logging.getLogger(__name__)


EDGE_CASE_SYNTHESIS_TEMPLATE = """You are an expert at identifying edge cases and boundary conditions for annotation tasks.

Given an annotation task description and some example data, generate synthetic examples
that would be difficult to label correctly. Focus on cases that:
1. Lie on the boundary between two labels
2. Have ambiguous or mixed signals
3. Require careful interpretation of the guidelines
4. Test specific aspects of the annotation criteria

## Task Description
{task_description}

## Annotation Guidelines/Prompt
{prompt}

## Available Labels
{labels}

## Example Data (for context)
{examples}

## Requirements
- Generate {num_cases} diverse edge cases
- Each case should test a different aspect of the guidelines
- Include cases that might reveal gaps in the current instructions
- Make the examples realistic and varied

## Output Format
Respond with JSON:
{{
    "edge_cases": [
        {{
            "text": "<the synthetic text>",
            "boundary_labels": ["<label1>", "<label2>"],
            "difficulty_reason": "<why this is a hard case>",
            "which_aspect": "<what guideline aspect this tests>"
        }},
        ...
    ]
}}
"""


@dataclass
class EdgeCase:
    """A synthesized edge case example."""
    id: str
    text: str
    boundary_labels: List[str]  # Labels this case is ambiguous between
    difficulty_reason: str
    which_aspect: str
    synthesized_at: datetime = field(default_factory=datetime.now)

    # Human label (filled after labeling)
    human_label: Optional[str] = None
    labeler_notes: Optional[str] = None
    labeled_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'id': self.id,
            'text': self.text,
            'boundary_labels': self.boundary_labels,
            'difficulty_reason': self.difficulty_reason,
            'which_aspect': self.which_aspect,
            'synthesized_at': self.synthesized_at.isoformat(),
            'human_label': self.human_label,
            'labeler_notes': self.labeler_notes,
            'labeled_at': self.labeled_at.isoformat() if self.labeled_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EdgeCase':
        """Deserialize from dictionary."""
        return cls(
            id=data['id'],
            text=data['text'],
            boundary_labels=data['boundary_labels'],
            difficulty_reason=data['difficulty_reason'],
            which_aspect=data['which_aspect'],
            synthesized_at=datetime.fromisoformat(data['synthesized_at']),
            human_label=data.get('human_label'),
            labeler_notes=data.get('labeler_notes'),
            labeled_at=(
                datetime.fromisoformat(data['labeled_at'])
                if data.get('labeled_at') else None
            ),
        )


class EdgeCaseSynthesizer:
    """
    Synthesizes edge cases for testing annotation prompts.

    This class generates synthetic examples that are designed to be
    difficult to label, helping to identify weaknesses in the annotation
    guidelines before they cause problems during actual annotation.
    """

    def __init__(self, config: Dict[str, Any], solo_config: Any):
        """
        Initialize the edge case synthesizer.

        Args:
            config: Full application configuration
            solo_config: SoloModeConfig instance
        """
        self.config = config
        self.solo_config = solo_config
        self._lock = threading.RLock()

        # Edge case storage
        self.edge_cases: Dict[str, EdgeCase] = {}  # id -> EdgeCase
        self.synthesis_rounds: List[Dict[str, Any]] = []

        # Track which aspects have been tested
        self.tested_aspects: Set[str] = set()

        # AI endpoint (lazy init)
        self._synthesis_endpoint = None

        # Counter for generating IDs
        self._id_counter = 0

    def _get_synthesis_endpoint(self) -> Optional[Any]:
        """Get or create AI endpoint for synthesis."""
        if self._synthesis_endpoint is not None:
            return self._synthesis_endpoint

        if not self.solo_config.revision_models:
            logger.warning("No models configured for edge case synthesis")
            return None

        try:
            from potato.ai.ai_endpoint import AIEndpointFactory

            for model_config in self.solo_config.revision_models:
                try:
                    endpoint_config = {
                        'ai_support': {
                            'enabled': True,
                            'endpoint_type': model_config.endpoint_type,
                            'ai_config': {
                                'model': model_config.model,
                                'max_tokens': model_config.max_tokens,
                                'temperature': 0.7,  # Higher temperature for diversity
                            }
                        }
                    }
                    if model_config.api_key:
                        endpoint_config['ai_support']['ai_config']['api_key'] = model_config.api_key

                    endpoint = AIEndpointFactory.create_endpoint(endpoint_config)
                    if endpoint:
                        self._synthesis_endpoint = endpoint
                        return endpoint
                except Exception as e:
                    logger.debug(f"Failed to create synthesis endpoint: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error creating synthesis endpoint: {e}")

        return None

    def synthesize_edge_cases(
        self,
        task_description: str,
        prompt: str,
        num_cases: int = 5,
        existing_examples: Optional[List[str]] = None
    ) -> List[EdgeCase]:
        """
        Generate edge case examples.

        Args:
            task_description: Description of the annotation task
            prompt: Current annotation prompt/guidelines
            num_cases: Number of edge cases to generate
            existing_examples: Optional list of real examples for context

        Returns:
            List of generated EdgeCase objects
        """
        endpoint = self._get_synthesis_endpoint()
        if endpoint is None:
            logger.warning("No endpoint available for edge case synthesis")
            return []

        try:
            # Get labels from config
            schemes = self.config.get('annotation_schemes', [])
            labels = self._extract_labels(schemes)

            # Format examples
            examples_text = self._format_examples(existing_examples or [])

            synthesis_prompt = EDGE_CASE_SYNTHESIS_TEMPLATE.format(
                task_description=task_description,
                prompt=prompt,
                labels=labels,
                examples=examples_text,
                num_cases=num_cases,
            )

            from pydantic import BaseModel

            class EdgeCaseResponse(BaseModel):
                edge_cases: List[Dict[str, Any]] = []

            response = endpoint.query(synthesis_prompt, EdgeCaseResponse)

            # Parse response
            if isinstance(response, str):
                response_data = self._parse_json_response(response)
            elif hasattr(response, 'model_dump'):
                response_data = response.model_dump()
            else:
                response_data = response

            cases = response_data.get('edge_cases', [])
            generated = []

            with self._lock:
                for case_data in cases:
                    case = EdgeCase(
                        id=self._generate_id(),
                        text=case_data.get('text', ''),
                        boundary_labels=case_data.get('boundary_labels', []),
                        difficulty_reason=case_data.get('difficulty_reason', ''),
                        which_aspect=case_data.get('which_aspect', ''),
                    )

                    if case.text:  # Only add if we got text
                        self.edge_cases[case.id] = case
                        self.tested_aspects.add(case.which_aspect)
                        generated.append(case)

                # Record synthesis round
                self.synthesis_rounds.append({
                    'timestamp': datetime.now().isoformat(),
                    'num_requested': num_cases,
                    'num_generated': len(generated),
                    'case_ids': [c.id for c in generated],
                })

            logger.info(f"Synthesized {len(generated)} edge cases")
            return generated

        except Exception as e:
            logger.error(f"Error synthesizing edge cases: {e}")
            return []

    def _generate_id(self) -> str:
        """Generate a unique edge case ID."""
        self._id_counter += 1
        return f"edge_{self._id_counter:04d}"

    def _extract_labels(self, schemes: List[Dict[str, Any]]) -> str:
        """Extract label names from annotation schemes."""
        all_labels = []
        for scheme in schemes:
            labels = scheme.get('labels', [])
            for label in labels:
                if isinstance(label, str):
                    all_labels.append(label)
                elif isinstance(label, dict):
                    name = label.get('name', '')
                    desc = label.get('description', '')
                    all_labels.append(f"{name}: {desc}" if desc else name)
        return '\n- '.join([''] + all_labels)

    def _format_examples(self, examples: List[str]) -> str:
        """Format example data for the prompt."""
        if not examples:
            return "No existing examples available."

        formatted = []
        for i, ex in enumerate(examples[:5]):  # Limit to 5 examples
            text = ex[:200] if len(ex) > 200 else ex
            formatted.append(f"{i+1}. \"{text}\"")
        return '\n'.join(formatted)

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON from response."""
        content = response.strip()

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
            return {'edge_cases': []}

    def get_edge_case(self, case_id: str) -> Optional[EdgeCase]:
        """Get an edge case by ID."""
        with self._lock:
            return self.edge_cases.get(case_id)

    def get_unlabeled_edge_cases(self) -> List[EdgeCase]:
        """Get edge cases that haven't been labeled yet."""
        with self._lock:
            return [
                case for case in self.edge_cases.values()
                if case.human_label is None
            ]

    def get_all_edge_cases(self) -> List[EdgeCase]:
        """Get all edge cases."""
        with self._lock:
            return list(self.edge_cases.values())

    def record_label(
        self,
        case_id: str,
        label: str,
        notes: Optional[str] = None
    ) -> bool:
        """
        Record a human label for an edge case.

        Args:
            case_id: The edge case ID
            label: The assigned label
            notes: Optional labeler notes

        Returns:
            True if label was recorded
        """
        with self._lock:
            if case_id not in self.edge_cases:
                logger.warning(f"Unknown edge case: {case_id}")
                return False

            case = self.edge_cases[case_id]
            case.human_label = label
            case.labeler_notes = notes
            case.labeled_at = datetime.now()

            logger.info(f"Recorded label '{label}' for edge case {case_id}")
            return True

    def get_labeled_edge_cases(self) -> List[EdgeCase]:
        """Get edge cases that have been labeled."""
        with self._lock:
            return [
                case for case in self.edge_cases.values()
                if case.human_label is not None
            ]

    def get_cases_for_prompt_revision(self) -> List[Dict[str, Any]]:
        """
        Get labeled edge cases formatted for prompt revision.

        Returns cases where the LLM might have been confused,
        formatted for the prompt revision system.
        """
        with self._lock:
            cases = []
            for case in self.get_labeled_edge_cases():
                cases.append({
                    'text': case.text,
                    'expected_label': case.human_label,
                    'boundary_labels': case.boundary_labels,
                    'difficulty_reason': case.difficulty_reason,
                    'which_aspect': case.which_aspect,
                    'labeler_notes': case.labeler_notes,
                })
            return cases

    def get_tested_aspects(self) -> Set[str]:
        """Get the set of aspects that have been tested."""
        with self._lock:
            return self.tested_aspects.copy()

    def get_status(self) -> Dict[str, Any]:
        """Get synthesizer status."""
        with self._lock:
            total = len(self.edge_cases)
            labeled = len([c for c in self.edge_cases.values() if c.human_label])
            return {
                'total_edge_cases': total,
                'labeled': labeled,
                'unlabeled': total - labeled,
                'synthesis_rounds': len(self.synthesis_rounds),
                'tested_aspects': list(self.tested_aspects),
            }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for persistence."""
        with self._lock:
            return {
                'edge_cases': {
                    cid: case.to_dict()
                    for cid, case in self.edge_cases.items()
                },
                'synthesis_rounds': self.synthesis_rounds,
                'tested_aspects': list(self.tested_aspects),
                'id_counter': self._id_counter,
            }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load from dictionary."""
        with self._lock:
            self.edge_cases = {
                cid: EdgeCase.from_dict(case_data)
                for cid, case_data in data.get('edge_cases', {}).items()
            }
            self.synthesis_rounds = data.get('synthesis_rounds', [])
            self.tested_aspects = set(data.get('tested_aspects', []))
            self._id_counter = data.get('id_counter', len(self.edge_cases))
