"""
In-Context Learning (ICL) Labeler Module

This module provides AI-assisted labeling using high-confidence human annotations
as in-context examples to prompt an LLM to label remaining data.

Key features:
- Identifies high-confidence examples where annotators agree
- Uses examples as in-context demonstrations for LLM labeling
- Tracks LLM confidence scores on predictions
- Routes subset of LLM labels to humans for verification
- Calculates and reports LLM accuracy based on verification
"""

import json
import logging
import os
import random
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Set

logger = logging.getLogger(__name__)


@dataclass
class HighConfidenceExample:
    """A human-annotated example suitable for in-context learning."""
    instance_id: str
    text: str
    schema_name: str
    label: str
    agreement_score: float  # Proportion of annotators who chose this label
    annotator_count: int
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'instance_id': self.instance_id,
            'text': self.text,
            'schema_name': self.schema_name,
            'label': self.label,
            'agreement_score': self.agreement_score,
            'annotator_count': self.annotator_count,
            'timestamp': self.timestamp.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'HighConfidenceExample':
        """Deserialize from dictionary."""
        timestamp = data.get('timestamp')
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        elif timestamp is None:
            timestamp = datetime.now()

        return cls(
            instance_id=data['instance_id'],
            text=data['text'],
            schema_name=data['schema_name'],
            label=data['label'],
            agreement_score=data['agreement_score'],
            annotator_count=data['annotator_count'],
            timestamp=timestamp
        )


@dataclass
class ICLPrediction:
    """Record of an LLM prediction using in-context learning."""
    instance_id: str
    schema_name: str
    predicted_label: str
    confidence_score: float  # 0.0-1.0
    timestamp: datetime = field(default_factory=datetime.now)

    # In-context examples used
    example_instance_ids: List[str] = field(default_factory=list)

    # Verification tracking
    verification_status: str = 'pending'  # 'pending', 'verified_correct', 'verified_incorrect'
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    human_label: Optional[str] = None  # Human's label if verified

    # LLM metadata
    model_name: str = ""
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'instance_id': self.instance_id,
            'schema_name': self.schema_name,
            'predicted_label': self.predicted_label,
            'confidence_score': self.confidence_score,
            'timestamp': self.timestamp.isoformat(),
            'example_instance_ids': self.example_instance_ids,
            'verification_status': self.verification_status,
            'verified_by': self.verified_by,
            'verified_at': self.verified_at.isoformat() if self.verified_at else None,
            'human_label': self.human_label,
            'model_name': self.model_name,
            'reasoning': self.reasoning
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ICLPrediction':
        """Deserialize from dictionary."""
        timestamp = data.get('timestamp')
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        elif timestamp is None:
            timestamp = datetime.now()

        verified_at = data.get('verified_at')
        if isinstance(verified_at, str):
            verified_at = datetime.fromisoformat(verified_at)

        return cls(
            instance_id=data['instance_id'],
            schema_name=data['schema_name'],
            predicted_label=data['predicted_label'],
            confidence_score=data['confidence_score'],
            timestamp=timestamp,
            example_instance_ids=data.get('example_instance_ids', []),
            verification_status=data.get('verification_status', 'pending'),
            verified_by=data.get('verified_by'),
            verified_at=verified_at,
            human_label=data.get('human_label'),
            model_name=data.get('model_name', ''),
            reasoning=data.get('reasoning', '')
        )


class ICLLabeler:
    """
    Manages in-context learning based labeling using high-confidence human annotations.

    Workflow:
    1. Monitors annotation progress for high-confidence examples
    2. Periodically refreshes pool of high-confidence examples
    3. Uses examples to prompt LLM for labeling unlabeled instances
    4. Routes some LLM-labeled instances for human verification (blind)
    5. Tracks accuracy metrics
    """

    _instance = None
    _lock = threading.RLock()

    def __new__(cls, *args, **kwargs):
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the ICLLabeler.

        Args:
            config: Configuration dictionary with settings
        """
        if self._initialized:
            return

        self.config = config or {}
        self._ai_endpoint = None

        # Get ICL labeling config
        icl_config = self.config.get('icl_labeling', {})

        # Example selection config
        example_config = icl_config.get('example_selection', {})
        self.min_agreement_threshold = example_config.get('min_agreement_threshold', 0.8)
        self.min_annotators_per_instance = example_config.get('min_annotators_per_instance', 2)
        self.max_examples_per_schema = example_config.get('max_examples_per_schema', 10)
        self.example_refresh_interval = example_config.get('refresh_interval_seconds', 300)

        # LLM labeling config
        llm_config = icl_config.get('llm_labeling', {})
        self.batch_size = llm_config.get('batch_size', 20)
        self.trigger_threshold = llm_config.get('trigger_threshold', 5)
        self.confidence_threshold = llm_config.get('confidence_threshold', 0.7)
        self.batch_interval = llm_config.get('batch_interval_seconds', 600)

        # Limits to prevent labeling entire dataset at once
        # This allows iterative improvement - verify accuracy before labeling more
        self.max_total_labels = llm_config.get('max_total_labels', None)  # Max instances to label total
        self.max_unlabeled_ratio = llm_config.get('max_unlabeled_ratio', 0.5)  # Max % of unlabeled to label
        self.pause_on_low_accuracy = llm_config.get('pause_on_low_accuracy', True)
        self.min_accuracy_threshold = llm_config.get('min_accuracy_threshold', 0.7)  # Pause if accuracy below

        # Verification config
        verification_config = icl_config.get('verification', {})
        self.verification_enabled = verification_config.get('enabled', True)
        self.verification_sample_rate = verification_config.get('sample_rate', 0.2)
        self.verification_strategy = verification_config.get('selection_strategy', 'low_confidence')

        # Persistence config
        persistence_config = icl_config.get('persistence', {})
        self.predictions_file = persistence_config.get('predictions_file', 'icl_predictions.json')

        # State
        self.schema_to_examples: Dict[str, List[HighConfidenceExample]] = {}
        self.predictions: Dict[str, Dict[str, ICLPrediction]] = {}  # instance_id -> schema -> prediction
        self.verification_queue: List[Tuple[str, str]] = []  # [(instance_id, schema_name), ...]
        self.labeled_instance_ids: Set[str] = set()  # Instances labeled by LLM

        self.last_example_refresh: Optional[datetime] = None
        self.last_batch_run: Optional[datetime] = None

        # Background worker
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_worker = threading.Event()

        self._initialized = True
        logger.info("ICLLabeler initialized")

    def _get_ai_endpoint(self):
        """Get or create AI endpoint from config (reuses ai_support config)."""
        if self._ai_endpoint is None:
            from potato.ai.ai_endpoint import AIEndpointFactory
            self._ai_endpoint = AIEndpointFactory.create_endpoint(self.config)
        return self._ai_endpoint

    def _get_annotation_schemes(self) -> List[Dict[str, Any]]:
        """Get annotation schemes from config."""
        return self.config.get('annotation_schemes', [])

    def _get_text_key(self) -> str:
        """Get the text key from item_properties."""
        return self.config.get('item_properties', {}).get('text_key', 'text')

    # === High-Confidence Example Collection ===

    def refresh_high_confidence_examples(self) -> Dict[str, List[HighConfidenceExample]]:
        """
        Scan annotations and identify high-confidence examples.

        Returns:
            Dictionary mapping schema name to list of high-confidence examples
        """
        from potato.flask_server import get_users, get_user_state, get_item_state_manager

        with self._lock:
            new_examples: Dict[str, List[HighConfidenceExample]] = defaultdict(list)

            try:
                ism = get_item_state_manager()
                if ism is None:
                    logger.warning("ItemStateManager not available")
                    return new_examples

                text_key = self._get_text_key()
                schemas = self._get_annotation_schemes()
                schema_names = [s.get('name') for s in schemas if s.get('name')]

                # Collect all annotations per instance
                instance_annotations: Dict[str, Dict[str, List[Tuple[str, Any]]]] = defaultdict(
                    lambda: defaultdict(list)
                )  # instance_id -> schema_name -> [(user_id, value), ...]

                for username in get_users():
                    user_state = get_user_state(username)
                    if not user_state:
                        continue

                    all_annotations = user_state.get_all_annotations()
                    for instance_id, instance_data in all_annotations.items():
                        if 'labels' not in instance_data:
                            continue

                        for label, value in instance_data['labels'].items():
                            schema_name = label.get_schema() if hasattr(label, 'get_schema') else str(label)
                            if schema_name in schema_names:
                                instance_annotations[instance_id][schema_name].append((username, value))

                # Find high-confidence examples
                for instance_id, schema_data in instance_annotations.items():
                    for schema_name, annotations in schema_data.items():
                        annotator_count = len(annotations)

                        if annotator_count < self.min_annotators_per_instance:
                            continue

                        # Count votes per label
                        label_counts = Counter(value for _, value in annotations)
                        most_common_label, most_common_count = label_counts.most_common(1)[0]

                        # Calculate agreement
                        agreement_score = most_common_count / annotator_count

                        if agreement_score >= self.min_agreement_threshold:
                            # Get instance text
                            item = ism.get_item(instance_id)
                            instance_data = item.get_data() if item else None
                            if instance_data is None:
                                continue

                            text = instance_data.get(text_key, '')
                            if not text:
                                continue

                            example = HighConfidenceExample(
                                instance_id=instance_id,
                                text=text,
                                schema_name=schema_name,
                                label=str(most_common_label),
                                agreement_score=agreement_score,
                                annotator_count=annotator_count
                            )
                            new_examples[schema_name].append(example)

                # Sort by agreement score and limit
                for schema_name in new_examples:
                    new_examples[schema_name].sort(key=lambda x: x.agreement_score, reverse=True)
                    new_examples[schema_name] = new_examples[schema_name][:self.max_examples_per_schema]

                self.schema_to_examples = dict(new_examples)
                self.last_example_refresh = datetime.now()

                total_examples = sum(len(examples) for examples in new_examples.values())
                logger.info(f"Refreshed high-confidence examples: {total_examples} examples across {len(new_examples)} schemas")

            except Exception as e:
                logger.error(f"Error refreshing examples: {e}")

            return self.schema_to_examples

    def get_examples_for_schema(self, schema_name: str) -> List[HighConfidenceExample]:
        """Get high-confidence examples for a specific schema."""
        return self.schema_to_examples.get(schema_name, [])

    def has_enough_examples(self, schema_name: str) -> bool:
        """Check if we have enough examples to start labeling."""
        return len(self.get_examples_for_schema(schema_name)) >= self.trigger_threshold

    # === LLM Labeling ===

    def label_instance(
        self,
        instance_id: str,
        schema_name: str,
        instance_text: str
    ) -> Optional[ICLPrediction]:
        """
        Label a single instance using in-context learning.

        Args:
            instance_id: The instance to label
            schema_name: The annotation schema to use
            instance_text: The text to label

        Returns:
            ICLPrediction if successful, None otherwise
        """
        from potato.ai.icl_prompt_builder import ICLPromptBuilder

        examples = self.get_examples_for_schema(schema_name)
        if not examples:
            logger.warning(f"No examples available for schema {schema_name}")
            return None

        # Get schema info
        schemas = self._get_annotation_schemes()
        schema_info = next((s for s in schemas if s.get('name') == schema_name), None)
        if not schema_info:
            logger.warning(f"Schema {schema_name} not found in config")
            return None

        endpoint = self._get_ai_endpoint()
        if endpoint is None:
            logger.warning("AI endpoint not available")
            return None

        try:
            # Build prompt
            prompt_builder = ICLPromptBuilder()
            prompt = prompt_builder.build_prompt(
                schema=schema_info,
                examples=examples,
                target_text=instance_text
            )

            # Query LLM
            from pydantic import BaseModel

            class ICLResponse(BaseModel):
                label: str
                confidence: float
                reasoning: str = ""

            response = endpoint.query(prompt, ICLResponse)

            # Parse response
            if isinstance(response, str):
                response_data = json.loads(response)
            elif hasattr(response, 'model_dump'):
                response_data = response.model_dump()
            else:
                response_data = response

            predicted_label = response_data.get('label', '')
            confidence = float(response_data.get('confidence', 0.5))
            reasoning = response_data.get('reasoning', '')

            # Validate label against schema
            valid_labels = self._get_valid_labels(schema_info)
            if valid_labels and predicted_label not in valid_labels:
                # Try fuzzy matching
                predicted_label = self._fuzzy_match_label(predicted_label, valid_labels)
                if predicted_label is None:
                    logger.warning(f"LLM returned invalid label for {instance_id}")
                    return None

            # Create prediction
            prediction = ICLPrediction(
                instance_id=instance_id,
                schema_name=schema_name,
                predicted_label=predicted_label,
                confidence_score=min(1.0, max(0.0, confidence)),
                example_instance_ids=[e.instance_id for e in examples],
                model_name=endpoint.model if hasattr(endpoint, 'model') else '',
                reasoning=reasoning
            )

            # Store prediction
            with self._lock:
                if instance_id not in self.predictions:
                    self.predictions[instance_id] = {}
                self.predictions[instance_id][schema_name] = prediction
                self.labeled_instance_ids.add(instance_id)

                # Maybe add to verification queue
                if self.verification_enabled and random.random() < self.verification_sample_rate:
                    self.verification_queue.append((instance_id, schema_name))

            logger.debug(f"Labeled {instance_id} with {predicted_label} (confidence: {confidence:.2f})")
            return prediction

        except Exception as e:
            logger.error(f"Error labeling instance {instance_id}: {e}")
            return None

    def _get_valid_labels(self, schema_info: Dict[str, Any]) -> List[str]:
        """Extract valid labels from schema info."""
        labels = schema_info.get('labels', [])
        valid_labels = []
        for label in labels:
            if isinstance(label, str):
                valid_labels.append(label)
            elif isinstance(label, dict):
                valid_labels.append(label.get('name', str(label)))
        return valid_labels

    def _fuzzy_match_label(self, predicted: str, valid_labels: List[str]) -> Optional[str]:
        """Try to match predicted label to a valid label."""
        predicted_lower = predicted.lower().strip()
        for label in valid_labels:
            if label.lower().strip() == predicted_lower:
                return label
        return None

    def should_pause_labeling(self) -> Tuple[bool, str]:
        """
        Check if labeling should be paused based on limits and accuracy.

        Returns:
            Tuple of (should_pause, reason)
        """
        # Check if max total labels reached
        if self.max_total_labels is not None:
            current_count = len(self.labeled_instance_ids)
            if current_count >= self.max_total_labels:
                return True, f"Reached max_total_labels limit ({self.max_total_labels})"

        # Check accuracy threshold
        if self.pause_on_low_accuracy:
            metrics = self.get_accuracy_metrics()
            total_verified = metrics.get('total_verified', 0)
            accuracy = metrics.get('accuracy')

            # Only check accuracy if we have enough verifications
            min_verifications = 10
            if total_verified >= min_verifications and accuracy is not None:
                if accuracy < self.min_accuracy_threshold:
                    return True, f"Accuracy ({accuracy:.1%}) below threshold ({self.min_accuracy_threshold:.1%})"

        return False, ""

    def get_remaining_label_capacity(self) -> int:
        """
        Get how many more instances can be labeled.

        Returns:
            Number of instances that can still be labeled, or -1 for unlimited
        """
        from potato.flask_server import get_item_state_manager, get_users, get_user_state

        ism = get_item_state_manager()
        if ism is None:
            return 0

        # Count unlabeled instances (not labeled by humans or LLM)
        unlabeled_count = 0
        for instance_id in ism.instance_id_ordering:
            if instance_id in self.labeled_instance_ids:
                continue

            has_human_annotation = False
            for username in get_users():
                user_state = get_user_state(username)
                if user_state:
                    all_annotations = user_state.get_all_annotations()
                    if instance_id in all_annotations:
                        has_human_annotation = True
                        break

            if not has_human_annotation:
                unlabeled_count += 1

        current_llm_labels = len(self.labeled_instance_ids)

        # Calculate max based on ratio
        max_from_ratio = int(unlabeled_count * self.max_unlabeled_ratio)

        # Calculate max based on total limit
        if self.max_total_labels is not None:
            max_from_total = self.max_total_labels - current_llm_labels
            return min(max_from_ratio, max_from_total)

        return max_from_ratio

    def batch_label_instances(self, schema_name: str) -> List[ICLPrediction]:
        """
        Label multiple unlabeled instances for a schema.

        Respects configured limits to prevent labeling entire dataset at once.

        Returns:
            List of successful predictions
        """
        from potato.flask_server import get_item_state_manager, get_users, get_user_state

        # Check if we should pause labeling
        should_pause, reason = self.should_pause_labeling()
        if should_pause:
            logger.info(f"Labeling paused: {reason}")
            return []

        if not self.has_enough_examples(schema_name):
            logger.info(f"Not enough examples for schema {schema_name}")
            return []

        ism = get_item_state_manager()
        if ism is None:
            return []

        # Check remaining capacity
        remaining_capacity = self.get_remaining_label_capacity()
        if remaining_capacity <= 0:
            logger.info("No remaining label capacity")
            return []

        # Limit batch size to remaining capacity
        effective_batch_size = min(self.batch_size, remaining_capacity)

        text_key = self._get_text_key()
        predictions = []

        # Find unlabeled instances
        unlabeled_ids = []
        for instance_id in ism.instance_id_ordering:
            # Skip if already labeled by LLM
            if instance_id in self.labeled_instance_ids:
                continue

            # Skip if already annotated by humans
            has_human_annotation = False
            for username in get_users():
                user_state = get_user_state(username)
                if user_state:
                    all_annotations = user_state.get_all_annotations()
                    if instance_id in all_annotations:
                        has_human_annotation = True
                        break

            if not has_human_annotation:
                unlabeled_ids.append(instance_id)

            if len(unlabeled_ids) >= effective_batch_size:
                break

        # Label instances
        for instance_id in unlabeled_ids:
            item = ism.get_item(instance_id)
            instance_data = item.get_data() if item else None
            if instance_data is None:
                continue

            text = instance_data.get(text_key, '')
            if not text:
                continue

            prediction = self.label_instance(instance_id, schema_name, text)
            if prediction and prediction.confidence_score >= self.confidence_threshold:
                predictions.append(prediction)

        self.last_batch_run = datetime.now()
        logger.info(f"Batch labeled {len(predictions)} instances for schema {schema_name}")

        return predictions

    # === Verification Workflow ===

    def get_pending_verifications(self, count: int = 1) -> List[Tuple[str, str]]:
        """
        Get instances pending human verification.

        Args:
            count: Number of verification tasks to return

        Returns:
            List of (instance_id, schema_name) tuples
        """
        with self._lock:
            if self.verification_strategy == 'low_confidence':
                # Sort by confidence ascending
                pending = [
                    (inst_id, schema)
                    for inst_id, schema in self.verification_queue
                    if (inst_id in self.predictions and
                        schema in self.predictions[inst_id] and
                        self.predictions[inst_id][schema].verification_status == 'pending')
                ]
                pending.sort(
                    key=lambda x: self.predictions[x[0]][x[1]].confidence_score
                )
                return pending[:count]

            elif self.verification_strategy == 'random':
                pending = [
                    (inst_id, schema)
                    for inst_id, schema in self.verification_queue
                    if (inst_id in self.predictions and
                        schema in self.predictions[inst_id] and
                        self.predictions[inst_id][schema].verification_status == 'pending')
                ]
                random.shuffle(pending)
                return pending[:count]

            else:  # mixed
                pending = [
                    (inst_id, schema)
                    for inst_id, schema in self.verification_queue
                    if (inst_id in self.predictions and
                        schema in self.predictions[inst_id] and
                        self.predictions[inst_id][schema].verification_status == 'pending')
                ]
                # 50% low confidence, 50% random
                pending.sort(
                    key=lambda x: self.predictions[x[0]][x[1]].confidence_score
                )
                half = count // 2
                low_conf = pending[:half]
                rest = pending[half:]
                random.shuffle(rest)
                return low_conf + rest[:count - half]

    def record_verification(
        self,
        instance_id: str,
        schema_name: str,
        human_label: str,
        verified_by: str
    ) -> bool:
        """
        Record human verification of an LLM prediction.

        Args:
            instance_id: The verified instance
            schema_name: The schema verified
            human_label: The human's label
            verified_by: Username of verifier

        Returns:
            True if verification recorded successfully
        """
        with self._lock:
            if instance_id not in self.predictions:
                logger.warning(f"No prediction found for instance {instance_id}")
                return False

            if schema_name not in self.predictions[instance_id]:
                logger.warning(f"No prediction found for schema {schema_name}")
                return False

            prediction = self.predictions[instance_id][schema_name]
            prediction.human_label = human_label
            prediction.verified_by = verified_by
            prediction.verified_at = datetime.now()

            if prediction.predicted_label == human_label:
                prediction.verification_status = 'verified_correct'
            else:
                prediction.verification_status = 'verified_incorrect'

            # Remove from verification queue
            try:
                self.verification_queue.remove((instance_id, schema_name))
            except ValueError:
                pass

            logger.info(
                f"Verification recorded for {instance_id}: "
                f"predicted={prediction.predicted_label}, human={human_label}, "
                f"status={prediction.verification_status}"
            )

            return True

    # === Accuracy Tracking ===

    def get_accuracy_metrics(self, schema_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Calculate accuracy metrics from verified predictions.

        Args:
            schema_name: Optional schema to filter by

        Returns:
            Dictionary with accuracy metrics
        """
        with self._lock:
            verified_correct = 0
            verified_incorrect = 0
            pending = 0
            total_predictions = 0

            confidence_correct = []
            confidence_incorrect = []

            for inst_id, schemas in self.predictions.items():
                for s_name, prediction in schemas.items():
                    if schema_name and s_name != schema_name:
                        continue

                    total_predictions += 1

                    if prediction.verification_status == 'verified_correct':
                        verified_correct += 1
                        confidence_correct.append(prediction.confidence_score)
                    elif prediction.verification_status == 'verified_incorrect':
                        verified_incorrect += 1
                        confidence_incorrect.append(prediction.confidence_score)
                    else:
                        pending += 1

            total_verified = verified_correct + verified_incorrect
            accuracy = verified_correct / total_verified if total_verified > 0 else None

            avg_confidence_correct = (
                sum(confidence_correct) / len(confidence_correct)
                if confidence_correct else None
            )
            avg_confidence_incorrect = (
                sum(confidence_incorrect) / len(confidence_incorrect)
                if confidence_incorrect else None
            )

            return {
                'total_predictions': total_predictions,
                'verified_correct': verified_correct,
                'verified_incorrect': verified_incorrect,
                'pending_verification': pending,
                'total_verified': total_verified,
                'accuracy': accuracy,
                'avg_confidence_correct': avg_confidence_correct,
                'avg_confidence_incorrect': avg_confidence_incorrect,
                'schema_name': schema_name
            }

    def get_status(self) -> Dict[str, Any]:
        """Get overall ICL labeler status."""
        with self._lock:
            total_examples = sum(len(ex) for ex in self.schema_to_examples.values())
            examples_by_schema = {
                schema: len(examples)
                for schema, examples in self.schema_to_examples.items()
            }

            # Check labeling status
            should_pause, pause_reason = self.should_pause_labeling()
            remaining_capacity = self.get_remaining_label_capacity()

            return {
                'enabled': self.config.get('icl_labeling', {}).get('enabled', False),
                'total_examples': total_examples,
                'examples_by_schema': examples_by_schema,
                'total_predictions': sum(
                    len(schemas) for schemas in self.predictions.values()
                ),
                'labeled_instances': len(self.labeled_instance_ids),
                'verification_queue_size': len(self.verification_queue),
                'last_example_refresh': (
                    self.last_example_refresh.isoformat()
                    if self.last_example_refresh else None
                ),
                'last_batch_run': (
                    self.last_batch_run.isoformat()
                    if self.last_batch_run else None
                ),
                'worker_running': (
                    self._worker_thread is not None and
                    self._worker_thread.is_alive()
                ),
                'accuracy_metrics': self.get_accuracy_metrics(),
                # Labeling limits status
                'labeling_paused': should_pause,
                'pause_reason': pause_reason,
                'remaining_label_capacity': remaining_capacity,
                'max_total_labels': self.max_total_labels,
                'max_unlabeled_ratio': self.max_unlabeled_ratio,
                'min_accuracy_threshold': self.min_accuracy_threshold
            }

    # === Background Worker ===

    def start_background_worker(self) -> None:
        """Start the background worker thread."""
        if self._worker_thread is not None and self._worker_thread.is_alive():
            logger.warning("Background worker already running")
            return

        self._stop_worker.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="ICLLabelerWorker",
            daemon=True
        )
        self._worker_thread.start()
        logger.info("Started ICL labeler background worker")

    def stop_background_worker(self) -> None:
        """Stop the background worker thread."""
        if self._worker_thread is None:
            return

        self._stop_worker.set()
        self._worker_thread.join(timeout=5.0)
        self._worker_thread = None
        logger.info("Stopped ICL labeler background worker")

    def _worker_loop(self) -> None:
        """Main loop for the background worker."""
        logger.info(
            f"ICL background worker started, "
            f"example_refresh={self.example_refresh_interval}s, "
            f"batch_interval={self.batch_interval}s"
        )

        last_example_refresh = 0
        last_batch = 0

        while not self._stop_worker.is_set():
            try:
                current_time = time.time()

                # Refresh examples periodically
                if current_time - last_example_refresh >= self.example_refresh_interval:
                    self.refresh_high_confidence_examples()
                    last_example_refresh = current_time

                # Run batch labeling periodically
                if current_time - last_batch >= self.batch_interval:
                    schemas = self._get_annotation_schemes()
                    for schema in schemas:
                        schema_name = schema.get('name')
                        if schema_name and self.has_enough_examples(schema_name):
                            predictions = self.batch_label_instances(schema_name)
                            if predictions:
                                self.save_state()
                    last_batch = current_time

            except Exception as e:
                logger.error(f"ICL background worker error: {e}")

            # Wait for next interval or stop signal
            self._stop_worker.wait(min(self.example_refresh_interval, self.batch_interval) / 2)

    # === Persistence ===

    def save_state(self) -> None:
        """Save current state to disk."""
        task_dir = self.config.get('output_annotation_dir', '')
        if not task_dir:
            return

        filepath = os.path.join(task_dir, self.predictions_file)

        try:
            with self._lock:
                state = {
                    'predictions': {
                        inst_id: {
                            schema: pred.to_dict()
                            for schema, pred in schemas.items()
                        }
                        for inst_id, schemas in self.predictions.items()
                    },
                    'examples': {
                        schema: [ex.to_dict() for ex in examples]
                        for schema, examples in self.schema_to_examples.items()
                    },
                    'verification_queue': self.verification_queue,
                    'labeled_instance_ids': list(self.labeled_instance_ids),
                    'last_example_refresh': (
                        self.last_example_refresh.isoformat()
                        if self.last_example_refresh else None
                    ),
                    'last_batch_run': (
                        self.last_batch_run.isoformat()
                        if self.last_batch_run else None
                    )
                }

            # Atomic write
            temp_path = filepath + '.tmp'
            with open(temp_path, 'w') as f:
                json.dump(state, f, indent=2)
            os.replace(temp_path, filepath)

            logger.debug(f"Saved ICL state to {filepath}")

        except Exception as e:
            logger.error(f"Error saving ICL state: {e}")

    def load_state(self) -> None:
        """Load state from disk."""
        task_dir = self.config.get('output_annotation_dir', '')
        if not task_dir:
            return

        filepath = os.path.join(task_dir, self.predictions_file)

        if not os.path.exists(filepath):
            return

        try:
            with open(filepath, 'r') as f:
                state = json.load(f)

            with self._lock:
                # Load predictions
                self.predictions = {}
                for inst_id, schemas in state.get('predictions', {}).items():
                    self.predictions[inst_id] = {
                        schema: ICLPrediction.from_dict(pred_data)
                        for schema, pred_data in schemas.items()
                    }

                # Load examples
                self.schema_to_examples = {}
                for schema, examples in state.get('examples', {}).items():
                    self.schema_to_examples[schema] = [
                        HighConfidenceExample.from_dict(ex) for ex in examples
                    ]

                # Load other state
                self.verification_queue = [
                    tuple(item) for item in state.get('verification_queue', [])
                ]
                self.labeled_instance_ids = set(state.get('labeled_instance_ids', []))

                if state.get('last_example_refresh'):
                    self.last_example_refresh = datetime.fromisoformat(
                        state['last_example_refresh']
                    )
                if state.get('last_batch_run'):
                    self.last_batch_run = datetime.fromisoformat(
                        state['last_batch_run']
                    )

            logger.info(f"Loaded ICL state from {filepath}")

        except Exception as e:
            logger.error(f"Error loading ICL state: {e}")


# Module-level singleton access
_icl_labeler: Optional[ICLLabeler] = None


def init_icl_labeler(config: Dict[str, Any]) -> ICLLabeler:
    """Initialize the global ICL labeler."""
    global _icl_labeler
    _icl_labeler = ICLLabeler(config)
    _icl_labeler.load_state()
    return _icl_labeler


def get_icl_labeler() -> Optional[ICLLabeler]:
    """Get the global ICL labeler instance."""
    return _icl_labeler


def clear_icl_labeler() -> None:
    """Clear the global ICL labeler (for testing)."""
    global _icl_labeler
    if _icl_labeler:
        _icl_labeler.stop_background_worker()
    _icl_labeler = None
    ICLLabeler._instance = None
