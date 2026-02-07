"""
Prompt Manager for Solo Mode

This module handles prompt synthesis, versioning, and revision for Solo Mode.
It generates annotation prompts from task descriptions and refines them
based on edge cases and human feedback.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import threading

logger = logging.getLogger(__name__)


PROMPT_SYNTHESIS_TEMPLATE = """You are an expert at creating annotation guidelines and prompts.

Given a task description and annotation schema, synthesize a clear, actionable prompt
that an LLM can use to label text instances accurately.

## Task Description
{task_description}

## Annotation Schema
{schema_info}

## Available Labels
{labels}

## Requirements for the Prompt
1. Be clear and unambiguous about what each label means
2. Include decision criteria for edge cases
3. Provide examples if helpful (but keep it concise)
4. Specify what to do when uncertain
5. Format should be easy for an LLM to follow

## Output Format
Respond with JSON:
{{
    "prompt": "<the annotation prompt>",
    "explanation": "<brief explanation of design choices>"
}}
"""


PROMPT_REVISION_TEMPLATE = """You are an expert at refining annotation guidelines.

The current annotation prompt is not working well for certain cases.
Based on the feedback, revise the prompt to handle these cases correctly.

## Current Prompt
{current_prompt}

## Cases Where the Prompt Failed
{failed_cases}

## Expected vs. Actual Labels
{label_discrepancies}

## Requirements
1. Modify the prompt to handle these edge cases
2. Do not change things that are working well
3. Add specific guidance for the problematic patterns
4. Keep the prompt concise and clear

## Output Format
Respond with JSON:
{{
    "prompt": "<the revised annotation prompt>",
    "changes_made": ["<change 1>", "<change 2>", ...],
    "explanation": "<why these changes should help>"
}}
"""


@dataclass
class PromptRevision:
    """Record of a prompt revision."""
    from_version: int
    to_version: int
    changes_made: List[str]
    trigger: str  # 'edge_case', 'disagreement', 'optimization', 'manual'
    failed_cases: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'from_version': self.from_version,
            'to_version': self.to_version,
            'changes_made': self.changes_made,
            'trigger': self.trigger,
            'failed_cases': self.failed_cases,
            'timestamp': self.timestamp.isoformat(),
        }


class PromptManager:
    """
    Manager for annotation prompts in Solo Mode.

    Responsibilities:
    - Synthesize initial prompts from task descriptions
    - Version and track prompt history
    - Revise prompts based on failures and edge cases
    - Store and retrieve prompts for labeling
    """

    def __init__(self, config: Dict[str, Any], solo_config: Any):
        """
        Initialize the prompt manager.

        Args:
            config: Full application configuration
            solo_config: SoloModeConfig instance
        """
        self.config = config
        self.solo_config = solo_config
        self._lock = threading.RLock()

        # Prompt state
        self.task_description: str = ""
        self.schema_info: Dict[str, Any] = {}
        self.prompts: List[Dict[str, Any]] = []  # Versioned prompts
        self.current_version: int = 0
        self.revisions: List[PromptRevision] = []

        # State directory
        self.state_dir = solo_config.state_dir
        self._prompt_file = 'prompts.json'

        # AI endpoint for synthesis/revision (lazy init)
        self._revision_endpoint = None

    def _get_revision_endpoint(self) -> Optional[Any]:
        """Get or create the AI endpoint for prompt revision."""
        if self._revision_endpoint is not None:
            return self._revision_endpoint

        if not self.solo_config.revision_models:
            logger.warning("No revision models configured")
            return None

        try:
            from potato.ai.ai_endpoint import AIEndpointFactory

            # Try revision models in order until one works
            for model_config in self.solo_config.revision_models:
                try:
                    endpoint_config = {
                        'ai_support': {
                            'enabled': True,
                            'endpoint_type': model_config.endpoint_type,
                            'ai_config': {
                                'model': model_config.model,
                                'max_tokens': model_config.max_tokens,
                                'temperature': model_config.temperature,
                            }
                        }
                    }
                    if model_config.api_key:
                        endpoint_config['ai_support']['ai_config']['api_key'] = model_config.api_key

                    endpoint = AIEndpointFactory.create_endpoint(endpoint_config)
                    if endpoint:
                        self._revision_endpoint = endpoint
                        logger.info(f"Using revision endpoint: {model_config.endpoint_type}/{model_config.model}")
                        return endpoint
                except Exception as e:
                    logger.debug(f"Failed to create revision endpoint {model_config.model}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error creating revision endpoint: {e}")

        return None

    def set_task_description(self, description: str) -> None:
        """Set the task description for prompt synthesis."""
        with self._lock:
            self.task_description = description
            self._save_state()

    def get_task_description(self) -> str:
        """Get the current task description."""
        with self._lock:
            return self.task_description

    def set_schema_info(self, schema_info: Dict[str, Any]) -> None:
        """Set the annotation schema information."""
        with self._lock:
            self.schema_info = schema_info
            self._save_state()

    def synthesize_prompt(self, task_description: str) -> Optional[str]:
        """
        Synthesize an initial annotation prompt from a task description.

        Args:
            task_description: The user's description of the annotation task

        Returns:
            The synthesized prompt text, or None if synthesis failed
        """
        self.set_task_description(task_description)

        endpoint = self._get_revision_endpoint()
        if endpoint is None:
            logger.warning("No endpoint available for prompt synthesis")
            return self._create_fallback_prompt()

        try:
            # Get schema info from config
            schemes = self.config.get('annotation_schemes', [])
            if not schemes:
                logger.warning("No annotation schemes configured")
                return self._create_fallback_prompt()

            schema_info = self._format_schema_info(schemes)
            labels = self._extract_labels(schemes)

            # Build synthesis prompt
            synthesis_prompt = PROMPT_SYNTHESIS_TEMPLATE.format(
                task_description=task_description,
                schema_info=schema_info,
                labels=labels,
            )

            # Query endpoint
            from pydantic import BaseModel

            class SynthesisResponse(BaseModel):
                prompt: str
                explanation: str = ""

            response = endpoint.query(synthesis_prompt, SynthesisResponse)

            # Parse response
            if isinstance(response, str):
                response_data = self._parse_json_response(response)
            elif hasattr(response, 'model_dump'):
                response_data = response.model_dump()
            else:
                response_data = response

            prompt_text = response_data.get('prompt', '')
            explanation = response_data.get('explanation', '')

            if prompt_text:
                # Store as first version
                self._add_prompt_version(
                    prompt_text=prompt_text,
                    created_by='llm_synthesis',
                    source_description=f"Synthesized from task description. {explanation}"
                )
                return prompt_text

        except Exception as e:
            logger.error(f"Error synthesizing prompt: {e}")

        return self._create_fallback_prompt()

    def _create_fallback_prompt(self) -> str:
        """Create a basic fallback prompt when synthesis fails."""
        schemes = self.config.get('annotation_schemes', [])
        labels = self._extract_labels(schemes)

        prompt = f"""Task: {self.task_description}

Please read the text carefully and assign the most appropriate label.

Available labels: {labels}

Respond with just the label name that best fits the text.
"""
        self._add_prompt_version(
            prompt_text=prompt,
            created_by='fallback',
            source_description="Basic fallback prompt"
        )
        return prompt

    def _format_schema_info(self, schemes: List[Dict[str, Any]]) -> str:
        """Format annotation schemes for the synthesis prompt."""
        info_parts = []
        for scheme in schemes:
            name = scheme.get('name', 'unknown')
            ann_type = scheme.get('annotation_type', 'unknown')
            description = scheme.get('description', '')
            info_parts.append(f"- {name}: {ann_type} ({description})")
        return '\n'.join(info_parts)

    def _extract_labels(self, schemes: List[Dict[str, Any]]) -> str:
        """Extract label names from annotation schemes."""
        all_labels = []
        for scheme in schemes:
            labels = scheme.get('labels', [])
            for label in labels:
                if isinstance(label, str):
                    all_labels.append(label)
                elif isinstance(label, dict):
                    all_labels.append(label.get('name', str(label)))
        return ', '.join(all_labels)

    def _add_prompt_version(
        self,
        prompt_text: str,
        created_by: str,
        source_description: str = ""
    ) -> int:
        """
        Add a new prompt version.

        Returns:
            The new version number
        """
        with self._lock:
            new_version = len(self.prompts) + 1
            parent = self.current_version if self.current_version > 0 else None

            prompt_data = {
                'version': new_version,
                'prompt_text': prompt_text,
                'created_at': datetime.now().isoformat(),
                'created_by': created_by,
                'source_description': source_description,
                'parent_version': parent,
                'validation_accuracy': None,
            }

            self.prompts.append(prompt_data)
            self.current_version = new_version
            self._save_state()

            logger.info(f"Added prompt version {new_version} by {created_by}")
            return new_version

    def get_current_prompt(self) -> Optional[str]:
        """Get the current prompt text."""
        with self._lock:
            if not self.prompts or self.current_version == 0:
                return None
            return self.prompts[self.current_version - 1]['prompt_text']

    def get_prompt_version(self, version: int) -> Optional[Dict[str, Any]]:
        """Get a specific prompt version."""
        with self._lock:
            if 0 < version <= len(self.prompts):
                return self.prompts[version - 1].copy()
            return None

    def get_all_versions(self) -> List[Dict[str, Any]]:
        """Get all prompt versions."""
        with self._lock:
            return [p.copy() for p in self.prompts]

    def update_prompt(self, prompt_text: str, created_by: str = 'user') -> int:
        """
        Update the prompt by creating a new version.

        Args:
            prompt_text: The new prompt text
            created_by: Who created this version

        Returns:
            The new version number
        """
        return self._add_prompt_version(
            prompt_text=prompt_text,
            created_by=created_by,
            source_description="Manual update"
        )

    def revise_prompt(
        self,
        failed_cases: List[Dict[str, Any]],
        trigger: str = 'edge_case'
    ) -> Optional[str]:
        """
        Revise the prompt based on failed cases.

        Args:
            failed_cases: List of cases where the prompt produced wrong labels
            trigger: What triggered the revision

        Returns:
            The revised prompt text, or None if revision failed
        """
        current = self.get_current_prompt()
        if not current:
            logger.warning("No current prompt to revise")
            return None

        endpoint = self._get_revision_endpoint()
        if endpoint is None:
            logger.warning("No endpoint available for prompt revision")
            return None

        try:
            # Format failed cases
            cases_text = self._format_failed_cases(failed_cases)
            discrepancies = self._format_discrepancies(failed_cases)

            revision_prompt = PROMPT_REVISION_TEMPLATE.format(
                current_prompt=current,
                failed_cases=cases_text,
                label_discrepancies=discrepancies,
            )

            from pydantic import BaseModel

            class RevisionResponse(BaseModel):
                prompt: str
                changes_made: List[str] = []
                explanation: str = ""

            response = endpoint.query(revision_prompt, RevisionResponse)

            # Parse response
            if isinstance(response, str):
                response_data = self._parse_json_response(response)
            elif hasattr(response, 'model_dump'):
                response_data = response.model_dump()
            else:
                response_data = response

            new_prompt = response_data.get('prompt', '')
            changes = response_data.get('changes_made', [])
            explanation = response_data.get('explanation', '')

            if new_prompt and new_prompt != current:
                # Record revision
                from_version = self.current_version
                new_version = self._add_prompt_version(
                    prompt_text=new_prompt,
                    created_by='llm_revision',
                    source_description=f"Revision triggered by {trigger}. {explanation}"
                )

                revision = PromptRevision(
                    from_version=from_version,
                    to_version=new_version,
                    changes_made=changes,
                    trigger=trigger,
                    failed_cases=failed_cases,
                )
                self.revisions.append(revision)
                self._save_state()

                logger.info(f"Revised prompt: {len(changes)} changes made")
                return new_prompt

        except Exception as e:
            logger.error(f"Error revising prompt: {e}")

        return None

    def _format_failed_cases(self, cases: List[Dict[str, Any]]) -> str:
        """Format failed cases for the revision prompt."""
        formatted = []
        for i, case in enumerate(cases[:10]):  # Limit to 10 cases
            text = case.get('text', '')[:200]  # Truncate long text
            expected = case.get('expected_label', 'unknown')
            actual = case.get('actual_label', 'unknown')
            formatted.append(f"{i+1}. Text: \"{text}\"\n   Expected: {expected}, Got: {actual}")
        return '\n\n'.join(formatted)

    def _format_discrepancies(self, cases: List[Dict[str, Any]]) -> str:
        """Summarize label discrepancies."""
        from collections import Counter
        discrepancies = Counter()
        for case in cases:
            expected = case.get('expected_label', 'unknown')
            actual = case.get('actual_label', 'unknown')
            if expected != actual:
                discrepancies[(actual, expected)] += 1

        formatted = []
        for (actual, expected), count in discrepancies.most_common(5):
            formatted.append(f"- '{actual}' was predicted but should be '{expected}' ({count} times)")
        return '\n'.join(formatted)

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON from response, handling markdown code blocks."""
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
            return {'prompt': content}

    def set_validation_accuracy(self, version: int, accuracy: float) -> None:
        """Set the validation accuracy for a prompt version."""
        with self._lock:
            if 0 < version <= len(self.prompts):
                self.prompts[version - 1]['validation_accuracy'] = accuracy
                self._save_state()

    def _save_state(self) -> None:
        """Save state to disk."""
        if not self.state_dir:
            return

        try:
            os.makedirs(self.state_dir, exist_ok=True)
            filepath = os.path.join(self.state_dir, self._prompt_file)

            state = {
                'task_description': self.task_description,
                'schema_info': self.schema_info,
                'prompts': self.prompts,
                'current_version': self.current_version,
                'revisions': [r.to_dict() for r in self.revisions],
            }

            temp_path = filepath + '.tmp'
            with open(temp_path, 'w') as f:
                json.dump(state, f, indent=2)
            os.replace(temp_path, filepath)

        except Exception as e:
            logger.error(f"Error saving prompt state: {e}")

    def load_state(self) -> bool:
        """Load state from disk."""
        if not self.state_dir:
            return False

        filepath = os.path.join(self.state_dir, self._prompt_file)

        if not os.path.exists(filepath):
            return False

        try:
            with open(filepath, 'r') as f:
                state = json.load(f)

            with self._lock:
                self.task_description = state.get('task_description', '')
                self.schema_info = state.get('schema_info', {})
                self.prompts = state.get('prompts', [])
                self.current_version = state.get('current_version', 0)

                self.revisions = []
                for r in state.get('revisions', []):
                    self.revisions.append(PromptRevision(
                        from_version=r['from_version'],
                        to_version=r['to_version'],
                        changes_made=r['changes_made'],
                        trigger=r['trigger'],
                        failed_cases=r.get('failed_cases', []),
                        timestamp=datetime.fromisoformat(r['timestamp']),
                    ))

            logger.info(f"Loaded prompt state: {len(self.prompts)} versions")
            return True

        except Exception as e:
            logger.error(f"Error loading prompt state: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get prompt manager status."""
        with self._lock:
            current = self.get_current_prompt()
            return {
                'has_task_description': bool(self.task_description),
                'current_version': self.current_version,
                'total_versions': len(self.prompts),
                'current_prompt_length': len(current) if current else 0,
                'revision_count': len(self.revisions),
            }
