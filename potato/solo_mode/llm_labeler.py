"""
LLM Labeler for Solo Mode

This module provides background LLM labeling functionality for Solo Mode.
It manages a thread that continuously labels instances while the human
annotator works, enabling parallel annotation.
"""

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from queue import Queue, Empty

logger = logging.getLogger(__name__)


@dataclass
class LabelingResult:
    """Result of labeling a single instance."""
    instance_id: str
    schema_name: str
    label: Any
    confidence: float
    uncertainty: float
    reasoning: str
    prompt_version: int
    model_name: str
    timestamp: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'instance_id': self.instance_id,
            'schema_name': self.schema_name,
            'label': self.label,
            'confidence': self.confidence,
            'uncertainty': self.uncertainty,
            'reasoning': self.reasoning,
            'prompt_version': self.prompt_version,
            'model_name': self.model_name,
            'timestamp': self.timestamp.isoformat(),
            'error': self.error,
        }


class LLMLabelingThread(threading.Thread):
    """
    Background thread for LLM labeling.

    Continuously labels instances from a queue, respecting configured
    limits on parallel labeling and batch sizes.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        solo_config: Any,
        prompt_getter: callable,
        result_callback: callable,
    ):
        """
        Initialize the labeling thread.

        Args:
            config: Full application configuration
            solo_config: SoloModeConfig instance
            prompt_getter: Callable that returns the current prompt text
            result_callback: Callable to handle labeling results
        """
        super().__init__(name="LLMLabelingThread", daemon=True)

        self.config = config
        self.solo_config = solo_config
        self.prompt_getter = prompt_getter
        self.result_callback = result_callback

        # Threading control
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()

        # Instance queue
        self._queue: Queue = Queue()

        # State
        self._labeled_count = 0
        self._error_count = 0
        self._last_error: Optional[str] = None

        # AI endpoint (lazy init)
        self._endpoint = None
        self._uncertainty_estimator = None

    def _get_endpoint(self) -> Optional[Any]:
        """Get or create the labeling AI endpoint."""
        if self._endpoint is not None:
            return self._endpoint

        if not self.solo_config.labeling_models:
            logger.warning("No labeling models configured")
            return None

        try:
            from potato.ai.ai_endpoint import AIEndpointFactory

            for model_config in self.solo_config.labeling_models:
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
                        self._endpoint = endpoint
                        logger.info(
                            f"Using labeling endpoint: "
                            f"{model_config.endpoint_type}/{model_config.model}"
                        )
                        return endpoint
                except Exception as e:
                    logger.debug(f"Failed to create endpoint {model_config.model}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error creating labeling endpoint: {e}")

        return None

    def _get_uncertainty_estimator(self) -> Optional[Any]:
        """Get or create the uncertainty estimator."""
        if self._uncertainty_estimator is not None:
            return self._uncertainty_estimator

        try:
            from .uncertainty import create_uncertainty_estimator

            strategy = self.solo_config.uncertainty.strategy
            estimator_config = {}

            if strategy == 'sampling_diversity':
                estimator_config = {
                    'num_samples': self.solo_config.uncertainty.num_samples,
                    'temperature': self.solo_config.uncertainty.sampling_temperature,
                }

            self._uncertainty_estimator = create_uncertainty_estimator(
                strategy,
                estimator_config
            )
            return self._uncertainty_estimator

        except Exception as e:
            logger.warning(f"Could not create uncertainty estimator: {e}")
            return None

    def enqueue(self, instance_id: str, instance_text: str, schema_name: str) -> None:
        """Add an instance to the labeling queue."""
        self._queue.put({
            'instance_id': instance_id,
            'text': instance_text,
            'schema_name': schema_name,
        })

    def enqueue_batch(
        self,
        instances: List[Dict[str, Any]],
        schema_name: str
    ) -> int:
        """
        Add a batch of instances to the labeling queue.

        Args:
            instances: List of {'instance_id': str, 'text': str}
            schema_name: The schema to label for

        Returns:
            Number of instances enqueued
        """
        count = 0
        for inst in instances:
            self.enqueue(
                inst['instance_id'],
                inst['text'],
                schema_name
            )
            count += 1
        return count

    def stop(self) -> None:
        """Signal the thread to stop."""
        self._stop_event.set()
        # Put sentinel to unblock queue
        self._queue.put(None)

    def pause(self) -> None:
        """Pause labeling."""
        self._pause_event.set()

    def resume(self) -> None:
        """Resume labeling."""
        self._pause_event.clear()

    def is_paused(self) -> bool:
        """Check if labeling is paused."""
        return self._pause_event.is_set()

    def get_queue_size(self) -> int:
        """Get the current queue size."""
        return self._queue.qsize()

    def run(self) -> None:
        """Main thread loop."""
        logger.info("LLM labeling thread started")

        while not self._stop_event.is_set():
            # Check pause
            while self._pause_event.is_set() and not self._stop_event.is_set():
                time.sleep(1)

            try:
                # Get next item (with timeout to check stop event)
                item = self._queue.get(timeout=1.0)

                if item is None:  # Sentinel
                    continue

                # Process the item
                result = self._label_instance(
                    item['instance_id'],
                    item['text'],
                    item['schema_name']
                )

                if result:
                    self._labeled_count += 1
                    self.result_callback(result)
                else:
                    self._error_count += 1

            except Empty:
                continue
            except Exception as e:
                logger.error(f"Error in labeling thread: {e}")
                self._error_count += 1
                self._last_error = str(e)
                time.sleep(1)  # Back off on error

        logger.info("LLM labeling thread stopped")

    def _label_instance(
        self,
        instance_id: str,
        text: str,
        schema_name: str
    ) -> Optional[LabelingResult]:
        """Label a single instance."""
        endpoint = self._get_endpoint()
        if endpoint is None:
            return None

        prompt = self.prompt_getter()
        if not prompt:
            logger.warning("No prompt available for labeling")
            return None

        try:
            # Get schema info
            schemes = self.config.get('annotation_schemes', [])
            schema_info = next(
                (s for s in schemes if s.get('name') == schema_name),
                None
            )
            if not schema_info:
                logger.warning(f"Schema {schema_name} not found")
                return None

            # Build labeling prompt
            labels = self._extract_labels(schema_info)
            full_prompt = f"""{prompt}

Text to label:
{text}

Available labels: {labels}

Respond with JSON:
{{
    "label": "<your label>",
    "confidence": <0-100>,
    "reasoning": "<brief explanation>"
}}
"""

            # Query endpoint
            from pydantic import BaseModel

            class LabelResponse(BaseModel):
                label: str
                confidence: float = 50.0
                reasoning: str = ""

            response = endpoint.query(full_prompt, LabelResponse)

            # Parse response
            if isinstance(response, str):
                response_data = self._parse_json_response(response)
            elif hasattr(response, 'model_dump'):
                response_data = response.model_dump()
            else:
                response_data = response

            label = response_data.get('label', '')
            confidence = float(response_data.get('confidence', 50)) / 100.0
            reasoning = response_data.get('reasoning', '')

            # Validate label
            valid_labels = self._get_valid_labels(schema_info)
            if valid_labels and label not in valid_labels:
                label = self._fuzzy_match_label(label, valid_labels)
                if label is None:
                    return LabelingResult(
                        instance_id=instance_id,
                        schema_name=schema_name,
                        label=None,
                        confidence=0,
                        uncertainty=1,
                        reasoning="",
                        prompt_version=0,
                        model_name=getattr(endpoint, 'model', ''),
                        error="Invalid label returned"
                    )

            # Estimate uncertainty
            uncertainty = 1.0 - confidence
            estimator = self._get_uncertainty_estimator()
            if estimator:
                try:
                    estimate = estimator.estimate_uncertainty(
                        instance_id=instance_id,
                        text=text,
                        prompt=prompt,
                        predicted_label=label,
                        endpoint=endpoint,
                        schema_info=schema_info
                    )
                    uncertainty = estimate.uncertainty_score
                    confidence = estimate.confidence_score
                except Exception as e:
                    logger.debug(f"Uncertainty estimation failed: {e}")

            return LabelingResult(
                instance_id=instance_id,
                schema_name=schema_name,
                label=label,
                confidence=confidence,
                uncertainty=uncertainty,
                reasoning=reasoning,
                prompt_version=0,  # TODO: Get from prompt manager
                model_name=getattr(endpoint, 'model', ''),
            )

        except Exception as e:
            logger.error(f"Error labeling {instance_id}: {e}")
            return LabelingResult(
                instance_id=instance_id,
                schema_name=schema_name,
                label=None,
                confidence=0,
                uncertainty=1,
                reasoning="",
                prompt_version=0,
                model_name='',
                error=str(e)
            )

    def _extract_labels(self, schema_info: Dict[str, Any]) -> str:
        """Extract label names from schema."""
        labels = schema_info.get('labels', [])
        label_names = []
        for label in labels:
            if isinstance(label, str):
                label_names.append(label)
            elif isinstance(label, dict):
                label_names.append(label.get('name', str(label)))
        return ', '.join(label_names)

    def _get_valid_labels(self, schema_info: Dict[str, Any]) -> List[str]:
        """Get valid label list from schema."""
        labels = schema_info.get('labels', [])
        valid = []
        for label in labels:
            if isinstance(label, str):
                valid.append(label)
            elif isinstance(label, dict):
                valid.append(label.get('name', str(label)))
        return valid

    def _fuzzy_match_label(self, label: str, valid: List[str]) -> Optional[str]:
        """Try to match label to valid labels."""
        label_lower = label.lower().strip()
        for v in valid:
            if v.lower().strip() == label_lower:
                return v
        return None

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
            # Try to extract just the label
            return {'label': content}

    def get_stats(self) -> Dict[str, Any]:
        """Get labeling statistics."""
        return {
            'labeled_count': self._labeled_count,
            'error_count': self._error_count,
            'queue_size': self.get_queue_size(),
            'is_paused': self.is_paused(),
            'is_running': self.is_alive(),
            'last_error': self._last_error,
        }
