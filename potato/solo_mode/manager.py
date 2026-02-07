"""
Solo Mode Manager

This module provides the central SoloModeManager class that orchestrates
all Solo Mode operations including prompt management, LLM labeling,
instance selection, and validation tracking.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
import json
import logging
import os
import threading

from .config import SoloModeConfig, ModelConfig, parse_solo_mode_config
from .phase_controller import SoloPhase, SoloPhaseController

logger = logging.getLogger(__name__)

# Singleton instance
_SOLO_MODE_MANAGER: Optional['SoloModeManager'] = None
_SOLO_MODE_LOCK = threading.Lock()


@dataclass
class PromptVersion:
    """A versioned prompt for LLM labeling."""
    version: int
    prompt_text: str
    created_at: datetime
    created_by: str  # 'user', 'llm_synthesis', 'llm_optimization'
    source_description: str = ""
    parent_version: Optional[int] = None
    validation_accuracy: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'version': self.version,
            'prompt_text': self.prompt_text,
            'created_at': self.created_at.isoformat(),
            'created_by': self.created_by,
            'source_description': self.source_description,
            'parent_version': self.parent_version,
            'validation_accuracy': self.validation_accuracy,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PromptVersion':
        """Deserialize from dictionary."""
        return cls(
            version=data['version'],
            prompt_text=data['prompt_text'],
            created_at=datetime.fromisoformat(data['created_at']),
            created_by=data['created_by'],
            source_description=data.get('source_description', ''),
            parent_version=data.get('parent_version'),
            validation_accuracy=data.get('validation_accuracy'),
        )


@dataclass
class LLMPrediction:
    """Record of an LLM prediction for an instance."""
    instance_id: str
    schema_name: str
    predicted_label: Any
    confidence_score: float
    uncertainty_score: float
    prompt_version: int
    timestamp: datetime = field(default_factory=datetime.now)
    model_name: str = ""
    reasoning: str = ""

    # Human comparison
    human_label: Optional[Any] = None
    agrees_with_human: Optional[bool] = None
    disagreement_resolved: bool = False
    resolution_label: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'instance_id': self.instance_id,
            'schema_name': self.schema_name,
            'predicted_label': self.predicted_label,
            'confidence_score': self.confidence_score,
            'uncertainty_score': self.uncertainty_score,
            'prompt_version': self.prompt_version,
            'timestamp': self.timestamp.isoformat(),
            'model_name': self.model_name,
            'reasoning': self.reasoning,
            'human_label': self.human_label,
            'agrees_with_human': self.agrees_with_human,
            'disagreement_resolved': self.disagreement_resolved,
            'resolution_label': self.resolution_label,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LLMPrediction':
        """Deserialize from dictionary."""
        return cls(
            instance_id=data['instance_id'],
            schema_name=data['schema_name'],
            predicted_label=data['predicted_label'],
            confidence_score=data['confidence_score'],
            uncertainty_score=data.get('uncertainty_score', 1.0 - data['confidence_score']),
            prompt_version=data['prompt_version'],
            timestamp=datetime.fromisoformat(data['timestamp']),
            model_name=data.get('model_name', ''),
            reasoning=data.get('reasoning', ''),
            human_label=data.get('human_label'),
            agrees_with_human=data.get('agrees_with_human'),
            disagreement_resolved=data.get('disagreement_resolved', False),
            resolution_label=data.get('resolution_label'),
        )


@dataclass
class AgreementMetrics:
    """Metrics tracking human-LLM agreement."""
    total_compared: int = 0
    agreements: int = 0
    disagreements: int = 0
    agreement_rate: float = 0.0

    def update_rate(self):
        """Update the agreement rate based on current counts."""
        if self.total_compared == 0:
            self.agreement_rate = 0.0
        else:
            self.agreement_rate = self.agreements / self.total_compared

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'total_compared': self.total_compared,
            'agreements': self.agreements,
            'disagreements': self.disagreements,
            'agreement_rate': self.agreement_rate,
        }


class SoloModeManager:
    """
    Central manager for Solo Mode operations.

    This class coordinates:
    - Phase transitions and state management
    - Prompt synthesis, versioning, and revision
    - LLM labeling with uncertainty estimation
    - Instance selection for human annotation
    - Human-LLM disagreement tracking
    - Validation metrics and thresholds
    """

    def __init__(self, config: SoloModeConfig, app_config: Dict[str, Any]):
        """
        Initialize the Solo Mode manager.

        Args:
            config: SoloModeConfig instance
            app_config: Full application configuration
        """
        self.config = config
        self.app_config = app_config
        self._lock = threading.RLock()

        # Initialize phase controller
        self.phase_controller = SoloPhaseController(config.state_dir)

        # Prompt management
        self.prompt_versions: List[PromptVersion] = []
        self.current_prompt_version: int = 0
        self.task_description: str = ""

        # LLM predictions
        self.predictions: Dict[str, Dict[str, LLMPrediction]] = {}  # instance_id -> schema -> prediction

        # Instance tracking
        self.human_labeled_ids: Set[str] = set()
        self.llm_labeled_ids: Set[str] = set()
        self.disagreement_ids: Set[str] = set()
        self.validation_sample_ids: Set[str] = set()

        # Edge cases
        self.edge_case_ids: Set[str] = set()
        self.edge_case_labels: Dict[str, Dict[str, Any]] = {}  # instance_id -> schema -> label

        # Agreement metrics
        self.agreement_metrics = AgreementMetrics()

        # AI endpoints (lazy initialization)
        self._labeling_endpoints: List[Any] = []
        self._revision_endpoints: List[Any] = []
        self._uncertainty_estimator = None

        # Background labeling
        self._labeling_thread: Optional[threading.Thread] = None
        self._stop_labeling = threading.Event()

        # Component instances (lazy initialization)
        self._edge_case_synthesizer = None
        self._prompt_manager = None
        self._instance_selector = None
        self._disagreement_resolver = None
        self._validation_tracker = None
        self._llm_labeling_thread = None
        self._prompt_optimizer = None

        # State persistence
        self._state_file = 'solo_mode_state.json'

        logger.info(f"SoloModeManager initialized (enabled={config.enabled})")

    # === Component Properties ===

    @property
    def edge_case_synthesizer(self):
        """Lazy-initialized edge case synthesizer."""
        if self._edge_case_synthesizer is None:
            from .edge_case_synthesizer import EdgeCaseSynthesizer
            self._edge_case_synthesizer = EdgeCaseSynthesizer(
                self.app_config, self.config
            )
        return self._edge_case_synthesizer

    @property
    def prompt_manager(self):
        """Lazy-initialized prompt manager."""
        if self._prompt_manager is None:
            from .prompt_manager import PromptManager
            self._prompt_manager = PromptManager(self.app_config, self.config)
        return self._prompt_manager

    @property
    def instance_selector(self):
        """Lazy-initialized instance selector."""
        if self._instance_selector is None:
            from .instance_selector import InstanceSelector, SelectionWeights
            weights = SelectionWeights(
                low_confidence=self.config.instance_selection.low_confidence_weight,
                diverse=self.config.instance_selection.diversity_weight,
                random=self.config.instance_selection.random_weight,
                disagreement=self.config.instance_selection.disagreement_weight,
            )
            self._instance_selector = InstanceSelector(weights, self.app_config)
        return self._instance_selector

    @property
    def disagreement_resolver(self):
        """Lazy-initialized disagreement resolver."""
        if self._disagreement_resolver is None:
            from .disagreement_resolver import DisagreementResolver
            self._disagreement_resolver = DisagreementResolver(
                self.app_config, self.config
            )
        return self._disagreement_resolver

    @property
    def validation_tracker(self):
        """Lazy-initialized validation tracker."""
        if self._validation_tracker is None:
            from .validation_tracker import ValidationTracker
            self._validation_tracker = ValidationTracker(self.app_config)
        return self._validation_tracker

    @property
    def llm_labeling_thread(self):
        """Lazy-initialized LLM labeling thread."""
        if self._llm_labeling_thread is None:
            from .llm_labeler import LLMLabelingThread
            self._llm_labeling_thread = LLMLabelingThread(
                config=self.app_config,
                solo_config=self.config,
                prompt_getter=self.get_current_prompt_text,
                result_callback=self._handle_labeling_result,
            )
        return self._llm_labeling_thread

    @property
    def prompt_optimizer(self):
        """Lazy-initialized prompt optimizer."""
        if not hasattr(self, '_prompt_optimizer') or self._prompt_optimizer is None:
            from .prompt_optimizer import PromptOptimizer
            self._prompt_optimizer = PromptOptimizer(
                config=self.app_config,
                solo_config=self.config,
                prompt_getter=self.get_current_prompt_text,
                prompt_setter=self.update_prompt,
                examples_getter=self._get_labeled_examples_for_optimization,
            )
        return self._prompt_optimizer

    def _get_labeled_examples_for_optimization(self) -> List[Dict[str, Any]]:
        """Get labeled examples for prompt optimization."""
        examples = []
        with self._lock:
            for instance_id in self.human_labeled_ids:
                if instance_id in self.predictions:
                    for schema_name, pred in self.predictions[instance_id].items():
                        examples.append({
                            'instance_id': instance_id,
                            'text': self._get_instance_text(instance_id),
                            'predicted_label': pred.predicted_label,
                            'human_label': pred.human_label,
                            'actual_label': pred.human_label,
                            'agrees': pred.agrees_with_human,
                        })
        return examples

    def _handle_labeling_result(self, result) -> None:
        """Handle a labeling result from the LLM labeling thread."""
        if result.error:
            logger.warning(f"LLM labeling error for {result.instance_id}: {result.error}")
            return

        prediction = LLMPrediction(
            instance_id=result.instance_id,
            schema_name=result.schema_name,
            predicted_label=result.label,
            confidence_score=result.confidence,
            uncertainty_score=result.uncertainty,
            prompt_version=result.prompt_version,
            model_name=result.model_name,
            reasoning=result.reasoning,
        )
        self.set_llm_prediction(result.instance_id, result.schema_name, prediction)

    # === Phase Control ===

    def get_current_phase(self) -> SoloPhase:
        """Get the current workflow phase."""
        return self.phase_controller.get_current_phase()

    def advance_to_phase(
        self,
        phase: SoloPhase,
        reason: str = "",
        force: bool = False
    ) -> bool:
        """
        Transition to a specific phase.

        Args:
            phase: Target phase
            reason: Reason for transition
            force: Allow invalid transitions

        Returns:
            True if transition successful
        """
        return self.phase_controller.transition_to(phase, reason=reason, force=force)

    def advance_to_next_phase(self, reason: str = "") -> bool:
        """Advance to the next logical phase."""
        return self.phase_controller.advance_to_next_phase(reason=reason)

    # === Prompt Management ===

    def get_current_prompt(self) -> Optional[PromptVersion]:
        """Get the current prompt version."""
        with self._lock:
            if not self.prompt_versions:
                return None
            return self.prompt_versions[self.current_prompt_version - 1]

    def get_prompt_version(self, version: int) -> Optional[PromptVersion]:
        """Get a specific prompt version."""
        with self._lock:
            if 0 < version <= len(self.prompt_versions):
                return self.prompt_versions[version - 1]
            return None

    def get_all_prompt_versions(self) -> List[PromptVersion]:
        """Get all prompt versions."""
        with self._lock:
            return self.prompt_versions.copy()

    def create_prompt_version(
        self,
        prompt_text: str,
        created_by: str,
        source_description: str = ""
    ) -> PromptVersion:
        """
        Create a new prompt version.

        Args:
            prompt_text: The prompt text
            created_by: Who created it ('user', 'llm_synthesis', 'llm_optimization')
            source_description: Description of how it was created

        Returns:
            The new PromptVersion
        """
        with self._lock:
            new_version = len(self.prompt_versions) + 1
            parent = self.current_prompt_version if self.current_prompt_version > 0 else None

            prompt = PromptVersion(
                version=new_version,
                prompt_text=prompt_text,
                created_at=datetime.now(),
                created_by=created_by,
                source_description=source_description,
                parent_version=parent,
            )

            self.prompt_versions.append(prompt)
            self.current_prompt_version = new_version
            self._save_state()

            logger.info(f"Created prompt version {new_version} by {created_by}")
            return prompt

    def update_prompt(
        self,
        prompt_text: str,
        source: str,
        source_description: str = ""
    ) -> PromptVersion:
        """
        Update the prompt by creating a new version.

        This is a convenience method that wraps create_prompt_version.
        """
        return self.create_prompt_version(prompt_text, source, source_description)

    def set_task_description(self, description: str) -> None:
        """Set the task description for prompt synthesis."""
        with self._lock:
            self.task_description = description
            self._save_state()

    def get_task_description(self) -> str:
        """Get the task description."""
        with self._lock:
            return self.task_description

    # === LLM Prediction Management ===

    def set_llm_prediction(
        self,
        instance_id: str,
        schema_name: str,
        prediction: LLMPrediction
    ) -> None:
        """
        Store an LLM prediction for an instance.

        Args:
            instance_id: The instance ID
            schema_name: The annotation schema name
            prediction: The LLM prediction
        """
        with self._lock:
            if instance_id not in self.predictions:
                self.predictions[instance_id] = {}
            self.predictions[instance_id][schema_name] = prediction
            self.llm_labeled_ids.add(instance_id)

    def get_llm_prediction(
        self,
        instance_id: str,
        schema_name: str
    ) -> Optional[LLMPrediction]:
        """Get the LLM prediction for an instance and schema."""
        with self._lock:
            if instance_id in self.predictions:
                return self.predictions[instance_id].get(schema_name)
            return None

    def get_all_llm_predictions(self) -> Dict[str, Dict[str, LLMPrediction]]:
        """Get all LLM predictions."""
        with self._lock:
            return {
                iid: {s: p for s, p in schemas.items()}
                for iid, schemas in self.predictions.items()
            }

    def get_predictions_by_confidence(
        self,
        min_confidence: Optional[float] = None,
        max_confidence: Optional[float] = None
    ) -> List[LLMPrediction]:
        """Get predictions filtered by confidence range."""
        with self._lock:
            results = []
            for schemas in self.predictions.values():
                for prediction in schemas.values():
                    conf = prediction.confidence_score
                    if min_confidence is not None and conf < min_confidence:
                        continue
                    if max_confidence is not None and conf > max_confidence:
                        continue
                    results.append(prediction)
            return results

    def get_low_confidence_predictions(self) -> List[LLMPrediction]:
        """Get predictions below the low confidence threshold."""
        return self.get_predictions_by_confidence(
            max_confidence=self.config.thresholds.confidence_low
        )

    # === Human Label Recording ===

    def record_human_label(
        self,
        instance_id: str,
        schema_name: str,
        label: Any,
        user_id: str
    ) -> Optional[bool]:
        """
        Record a human label and compare with LLM prediction.

        Args:
            instance_id: The instance ID
            schema_name: The annotation schema
            label: The human's label
            user_id: The annotator ID

        Returns:
            True if agrees with LLM, False if disagrees, None if no LLM prediction
        """
        with self._lock:
            self.human_labeled_ids.add(instance_id)

            prediction = self.get_llm_prediction(instance_id, schema_name)
            if prediction is None:
                return None

            prediction.human_label = label
            agrees = self._check_agreement(
                prediction.predicted_label,
                label,
                schema_name
            )
            prediction.agrees_with_human = agrees

            # Update metrics
            self.agreement_metrics.total_compared += 1
            if agrees:
                self.agreement_metrics.agreements += 1
            else:
                self.agreement_metrics.disagreements += 1
                self.disagreement_ids.add(instance_id)
            self.agreement_metrics.update_rate()

            self._save_state()
            return agrees

    def _check_agreement(
        self,
        llm_label: Any,
        human_label: Any,
        schema_name: str
    ) -> bool:
        """
        Check if LLM and human labels agree.

        The agreement check depends on the annotation type.
        """
        # Get annotation type for this schema
        annotation_type = self._get_annotation_type(schema_name)

        if annotation_type in ('radio', 'select'):
            # Exact match for categorical
            return str(llm_label) == str(human_label)

        elif annotation_type == 'likert':
            # Within tolerance for likert scales
            try:
                tolerance = self.config.thresholds.likert_tolerance
                return abs(int(llm_label) - int(human_label)) <= tolerance
            except (ValueError, TypeError):
                return str(llm_label) == str(human_label)

        elif annotation_type == 'multiselect':
            # Jaccard similarity for multiselect
            threshold = self.config.thresholds.multiselect_jaccard_threshold
            llm_set = set(llm_label) if isinstance(llm_label, (list, set)) else {llm_label}
            human_set = set(human_label) if isinstance(human_label, (list, set)) else {human_label}

            if not llm_set and not human_set:
                return True

            intersection = len(llm_set & human_set)
            union = len(llm_set | human_set)
            jaccard = intersection / union if union > 0 else 0
            return jaccard >= threshold

        elif annotation_type == 'textbox':
            # For now, exact match; could use embedding similarity
            return str(llm_label).strip().lower() == str(human_label).strip().lower()

        elif annotation_type == 'span':
            # Token overlap for spans
            threshold = self.config.thresholds.span_overlap_threshold
            # Simplified: check if spans overlap sufficiently
            # Full implementation would compare token ranges
            return str(llm_label) == str(human_label)

        else:
            # Default to exact match
            return str(llm_label) == str(human_label)

    def _get_annotation_type(self, schema_name: str) -> str:
        """Get the annotation type for a schema."""
        schemes = self.app_config.get('annotation_schemes', [])
        for scheme in schemes:
            if scheme.get('name') == schema_name:
                return scheme.get('annotation_type', 'radio')
        return 'radio'

    # === Disagreement Resolution ===

    def get_pending_disagreements(self) -> List[str]:
        """Get instance IDs with unresolved disagreements."""
        with self._lock:
            pending = []
            for instance_id in self.disagreement_ids:
                if instance_id in self.predictions:
                    for prediction in self.predictions[instance_id].values():
                        if not prediction.disagreement_resolved:
                            pending.append(instance_id)
                            break
            return pending

    def resolve_disagreement(
        self,
        instance_id: str,
        schema_name: str,
        resolution_label: Any,
        resolved_by: str
    ) -> bool:
        """
        Resolve a human-LLM disagreement.

        Args:
            instance_id: The instance ID
            schema_name: The annotation schema
            resolution_label: The final resolved label
            resolved_by: Who resolved it ('human', 'llm_revision')

        Returns:
            True if resolution was recorded
        """
        with self._lock:
            prediction = self.get_llm_prediction(instance_id, schema_name)
            if prediction is None:
                return False

            prediction.disagreement_resolved = True
            prediction.resolution_label = resolution_label

            self._save_state()
            logger.info(
                f"Resolved disagreement for {instance_id}:{schema_name} "
                f"(resolved_by={resolved_by})"
            )
            return True

    # === Instance Selection ===

    def get_next_instance_for_human(self, user_id: str) -> Optional[str]:
        """
        Get the next instance for human annotation.

        Uses weighted selection based on:
        - Low LLM confidence
        - Diversity (embedding clusters)
        - Random sampling
        - Prior disagreements

        Args:
            user_id: The annotator's ID

        Returns:
            Instance ID to annotate, or None if none available
        """
        # This is a placeholder - full implementation in instance_selector.py
        with self._lock:
            # Get available instances
            from potato.item_state_management import get_item_state_manager

            try:
                ism = get_item_state_manager()
            except ValueError:
                return None

            # Find instances not yet labeled by this human
            for instance_id in ism.instance_id_ordering:
                if instance_id not in self.human_labeled_ids:
                    return instance_id

            return None

    # === Agreement Metrics ===

    def get_agreement_metrics(self) -> AgreementMetrics:
        """Get current agreement metrics."""
        with self._lock:
            return self.agreement_metrics

    def should_end_human_annotation(self) -> bool:
        """
        Check if human annotation should end.

        Returns True when agreement threshold is reached and
        minimum validation sample size is met.
        """
        with self._lock:
            metrics = self.agreement_metrics
            threshold = self.config.thresholds.end_human_annotation_agreement
            min_sample = self.config.thresholds.minimum_validation_sample

            if metrics.total_compared < min_sample:
                return False

            return metrics.agreement_rate >= threshold

    def check_and_advance_to_autonomous(self) -> bool:
        """
        Atomically check if human annotation should end and advance phase if so.

        This prevents race conditions where multiple requests could both
        check should_end_human_annotation() as True and try to advance.

        Returns:
            True if phase was advanced to AUTONOMOUS_LABELING
        """
        with self._lock:
            metrics = self.agreement_metrics
            threshold = self.config.thresholds.end_human_annotation_agreement
            min_sample = self.config.thresholds.minimum_validation_sample

            if metrics.total_compared < min_sample:
                return False

            if metrics.agreement_rate < threshold:
                return False

            # Already in or past autonomous labeling phase
            current_phase = self.phase_controller.get_current_phase()
            if current_phase.value >= SoloPhase.AUTONOMOUS_LABELING.value:
                return False

            # Advance phase atomically
            return self.phase_controller.transition_to(
                SoloPhase.AUTONOMOUS_LABELING,
                reason="Agreement threshold reached"
            )

    def should_trigger_periodic_review(self) -> bool:
        """Check if periodic review should be triggered."""
        with self._lock:
            interval = self.config.thresholds.periodic_review_interval
            return len(self.llm_labeled_ids) % interval == 0

    # === Background Labeling ===

    def start_background_labeling(self) -> bool:
        """
        Start background LLM labeling thread.

        Returns:
            True if started, False if already running
        """
        with self._lock:
            if self._labeling_thread is not None and self._labeling_thread.is_alive():
                logger.warning("Background labeling already running")
                return False

            self._stop_labeling.clear()
            self._labeling_thread = threading.Thread(
                target=self._background_labeling_loop,
                name="SoloModeLabelingThread",
                daemon=True
            )
            self._labeling_thread.start()
            logger.info("Started background LLM labeling")
            return True

    def stop_background_labeling(self) -> None:
        """Stop background LLM labeling thread."""
        if self._labeling_thread is None:
            return

        self._stop_labeling.set()
        self._labeling_thread.join(timeout=5.0)
        self._labeling_thread = None
        logger.info("Stopped background LLM labeling")

    def pause_background_labeling(self) -> None:
        """Pause background labeling (alias for stop)."""
        self.stop_background_labeling()

    def is_background_labeling_running(self) -> bool:
        """Check if background labeling is running."""
        return (
            self._labeling_thread is not None and
            self._labeling_thread.is_alive()
        )

    def _background_labeling_loop(self) -> None:
        """Main loop for background labeling."""
        import time

        batch_size = self.config.batches.llm_labeling_batch
        max_labels = self.config.batches.max_parallel_labels

        logger.info(f"Background labeling started (batch={batch_size}, max={max_labels})")

        while not self._stop_labeling.is_set():
            try:
                # Check if we've hit the max parallel labels
                with self._lock:
                    current_count = len(self.llm_labeled_ids - self.human_labeled_ids)
                    if current_count >= max_labels:
                        logger.debug(f"Max parallel labels reached ({current_count})")
                        time.sleep(10)
                        continue

                # Label a batch of instances
                labeled_count = self._label_batch(batch_size)

                if labeled_count == 0:
                    # No more instances to label
                    time.sleep(30)
                else:
                    logger.info(f"Labeled {labeled_count} instances in background")
                    self._save_state()

            except Exception as e:
                logger.error(f"Error in background labeling: {e}")
                time.sleep(10)

            # Wait before next batch
            self._stop_labeling.wait(5)

    def _label_batch(self, batch_size: int) -> int:
        """Label a batch of instances. Returns number labeled."""
        # Placeholder - full implementation uses LLM endpoints
        return 0

    # === Validation ===

    def select_validation_sample(self, sample_size: int) -> List[str]:
        """
        Select a random sample of LLM-labeled instances for validation.

        Args:
            sample_size: Number of instances to select

        Returns:
            List of instance IDs for validation
        """
        import random

        with self._lock:
            # Get instances labeled only by LLM (not by human)
            llm_only = self.llm_labeled_ids - self.human_labeled_ids
            llm_only = llm_only - self.validation_sample_ids  # Exclude already validated

            available = list(llm_only)
            sample_size = min(sample_size, len(available))

            sample = random.sample(available, sample_size)
            self.validation_sample_ids.update(sample)

            logger.info(f"Selected {len(sample)} instances for validation")
            return sample

    # === State Persistence ===

    def _save_state(self) -> None:
        """Save manager state to disk."""
        if not self.config.state_dir:
            return

        try:
            os.makedirs(self.config.state_dir, exist_ok=True)
            filepath = os.path.join(self.config.state_dir, self._state_file)

            state = {
                'task_description': self.task_description,
                'current_prompt_version': self.current_prompt_version,
                'prompt_versions': [p.to_dict() for p in self.prompt_versions],
                'predictions': {
                    iid: {s: p.to_dict() for s, p in schemas.items()}
                    for iid, schemas in self.predictions.items()
                },
                'human_labeled_ids': list(self.human_labeled_ids),
                'llm_labeled_ids': list(self.llm_labeled_ids),
                'disagreement_ids': list(self.disagreement_ids),
                'validation_sample_ids': list(self.validation_sample_ids),
                'edge_case_ids': list(self.edge_case_ids),
                'edge_case_labels': self.edge_case_labels,
                'agreement_metrics': self.agreement_metrics.to_dict(),
            }

            # Atomic write
            temp_path = filepath + '.tmp'
            with open(temp_path, 'w') as f:
                json.dump(state, f, indent=2)
            os.replace(temp_path, filepath)

        except Exception as e:
            logger.error(f"Error saving Solo Mode state: {e}")

    def load_state(self) -> bool:
        """
        Load manager state from disk.

        Returns:
            True if state was loaded
        """
        if not self.config.state_dir:
            return False

        filepath = os.path.join(self.config.state_dir, self._state_file)

        if not os.path.exists(filepath):
            return False

        try:
            with open(filepath, 'r') as f:
                state = json.load(f)

            with self._lock:
                self.task_description = state.get('task_description', '')
                self.current_prompt_version = state.get('current_prompt_version', 0)

                self.prompt_versions = [
                    PromptVersion.from_dict(p)
                    for p in state.get('prompt_versions', [])
                ]

                self.predictions = {
                    iid: {
                        s: LLMPrediction.from_dict(p)
                        for s, p in schemas.items()
                    }
                    for iid, schemas in state.get('predictions', {}).items()
                }

                self.human_labeled_ids = set(state.get('human_labeled_ids', []))
                self.llm_labeled_ids = set(state.get('llm_labeled_ids', []))
                self.disagreement_ids = set(state.get('disagreement_ids', []))
                self.validation_sample_ids = set(state.get('validation_sample_ids', []))
                self.edge_case_ids = set(state.get('edge_case_ids', []))
                self.edge_case_labels = state.get('edge_case_labels', {})

                metrics = state.get('agreement_metrics', {})
                self.agreement_metrics = AgreementMetrics(
                    total_compared=metrics.get('total_compared', 0),
                    agreements=metrics.get('agreements', 0),
                    disagreements=metrics.get('disagreements', 0),
                    agreement_rate=metrics.get('agreement_rate', 0.0),
                )

            # Load phase state
            self.phase_controller.load_state()

            logger.info("Loaded Solo Mode state")
            return True

        except Exception as e:
            logger.error(f"Error loading Solo Mode state: {e}")
            return False

    # === Route Helper Methods ===
    # These methods provide simplified interfaces for the routes

    def get_current_prompt_text(self) -> str:
        """Get current prompt text as string (for routes)."""
        prompt = self.get_current_prompt()
        return prompt.prompt_text if prompt else ""

    def get_llm_prediction_for_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Get LLM prediction as dict for an instance (for routes)."""
        with self._lock:
            if instance_id not in self.predictions:
                return None
            # Return first schema's prediction
            for schema_name, pred in self.predictions[instance_id].items():
                return {
                    'label': pred.predicted_label,
                    'confidence': pred.confidence_score,
                    'reasoning': pred.reasoning,
                    'schema': schema_name,
                }
            return None

    def get_annotation_stats(self) -> Dict[str, Any]:
        """Get annotation statistics for the status display."""
        with self._lock:
            total = self._get_total_instance_count()
            return {
                'human_labeled': len(self.human_labeled_ids),
                'llm_labeled': len(self.llm_labeled_ids),
                'remaining': total - len(self.human_labeled_ids | self.llm_labeled_ids),
                'total': total,
                'agreement_rate': self.agreement_metrics.agreement_rate,
            }

    def _get_total_instance_count(self) -> int:
        """Get total number of instances."""
        try:
            from potato.item_state_management import get_item_state_manager
            ism = get_item_state_manager()
            return len(ism.instance_id_ordering)
        except Exception:
            return 0

    def get_available_labels(self) -> List[str]:
        """Get available labels from annotation schemes."""
        labels = []
        schemes = self.app_config.get('annotation_schemes', [])
        for scheme in schemes:
            scheme_labels = scheme.get('labels', [])
            for label in scheme_labels:
                if isinstance(label, str):
                    labels.append(label)
                elif isinstance(label, dict):
                    labels.append(label.get('name', str(label)))
        return labels

    def check_for_disagreement(self, instance_id: str, human_label: Any) -> bool:
        """Check if there's a disagreement between human and LLM."""
        with self._lock:
            if instance_id not in self.predictions:
                return False
            for schema_name, pred in self.predictions[instance_id].items():
                if pred.agrees_with_human is False:
                    return True
            return False

    def get_disagreement(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Get disagreement details for an instance."""
        with self._lock:
            if instance_id not in self.predictions:
                return None
            for schema_name, pred in self.predictions[instance_id].items():
                if pred.agrees_with_human is False and not pred.disagreement_resolved:
                    return {
                        'id': f"{instance_id}:{schema_name}",
                        'instance_id': instance_id,
                        'schema_name': schema_name,
                        'text': self._get_instance_text(instance_id),
                        'human_label': pred.human_label,
                        'llm_label': pred.predicted_label,
                        'llm_reasoning': pred.reasoning,
                        'pending_count': len(self.get_pending_disagreements()),
                    }
            return None

    def _get_instance_text(self, instance_id: str) -> str:
        """Get text for an instance."""
        try:
            from potato.item_state_management import get_item_state_manager
            ism = get_item_state_manager()
            item = ism.get_item_by_id(instance_id)
            if item:
                text_key = self.app_config.get('item_properties', {}).get('text_key', 'text')
                return item.get(text_key, str(item))
        except Exception:
            pass
        return ""

    def record_human_annotation(
        self,
        instance_id: str,
        annotation: Any,
        user_id: str
    ) -> None:
        """Record a human annotation (simplified interface for routes)."""
        # Get first schema name
        schemes = self.app_config.get('annotation_schemes', [])
        schema_name = schemes[0].get('name', 'default') if schemes else 'default'
        self.record_human_label(instance_id, schema_name, annotation, user_id)

    def get_llm_labeling_stats(self) -> Dict[str, Any]:
        """Get LLM labeling statistics."""
        with self._lock:
            return {
                'labeled_count': len(self.llm_labeled_ids),
                'queue_size': 0,  # Placeholder
                'error_count': 0,  # Placeholder
                'is_paused': not self.is_background_labeling_running(),
                'is_running': self.is_background_labeling_running(),
            }

    def get_validation_progress(self) -> Dict[str, Any]:
        """Get validation progress."""
        with self._lock:
            total = len(self.validation_sample_ids)
            # Count validated (those that have been human-labeled from the validation set)
            validated = len(self.validation_sample_ids & self.human_labeled_ids)
            return {
                'total_samples': total,
                'validated': validated,
                'remaining': total - validated,
                'percent_complete': (validated / total * 100) if total > 0 else 0,
                'validation_accuracy': 0.0,  # Placeholder
                'agreements': 0,  # Placeholder
            }

    def get_validation_samples(self) -> List[Dict[str, Any]]:
        """Get validation samples that need to be validated."""
        with self._lock:
            samples = []
            for instance_id in self.validation_sample_ids:
                if instance_id not in self.human_labeled_ids:
                    pred = self.get_llm_prediction_for_instance(instance_id)
                    if pred:
                        samples.append({
                            'instance_id': instance_id,
                            'text': self._get_instance_text(instance_id),
                            'llm_label': pred['label'],
                            'llm_confidence': pred['confidence'],
                        })
            return samples

    def record_validation(
        self,
        instance_id: str,
        human_label: Any,
        notes: str = ""
    ) -> None:
        """Record a validation result."""
        # Get first schema name
        schemes = self.app_config.get('annotation_schemes', [])
        schema_name = schemes[0].get('name', 'default') if schemes else 'default'
        self.record_human_label(instance_id, schema_name, human_label, 'validator')

    def approve_llm_label(self, instance_id: str) -> None:
        """Approve an LLM label during review."""
        # Mark as validated/approved
        with self._lock:
            self.human_labeled_ids.add(instance_id)

    def correct_llm_label(self, instance_id: str, corrected_label: Any) -> None:
        """Correct an LLM label during review."""
        schemes = self.app_config.get('annotation_schemes', [])
        schema_name = schemes[0].get('name', 'default') if schemes else 'default'
        self.record_human_label(instance_id, schema_name, corrected_label, 'reviewer')

    def get_instances_for_review(self) -> List[Dict[str, Any]]:
        """Get low-confidence instances for periodic review."""
        with self._lock:
            instances = []
            low_conf_preds = self.get_low_confidence_predictions()
            for pred in low_conf_preds[:10]:  # Limit to 10
                if pred.instance_id not in self.human_labeled_ids:
                    instances.append({
                        'id': pred.instance_id,
                        'text': self._get_instance_text(pred.instance_id),
                        'llm_label': pred.predicted_label,
                        'reasoning': pred.reasoning,
                        'confidence': pred.confidence_score,
                    })
            return instances

    def get_all_annotations(self) -> Dict[str, Any]:
        """Get all annotations for export."""
        with self._lock:
            return {
                'human_labels': list(self.human_labeled_ids),
                'llm_labels': {
                    iid: {s: p.to_dict() for s, p in schemas.items()}
                    for iid, schemas in self.predictions.items()
                },
            }

    def get_next_instance_data(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get full instance data for the next instance to annotate."""
        instance_id = self.get_next_instance_for_human(user_id)
        if not instance_id:
            return None
        return {
            'id': instance_id,
            'text': self._get_instance_text(instance_id),
        }

    # === Status ===

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive status information."""
        with self._lock:
            current_prompt = self.get_current_prompt()

            return {
                'enabled': self.config.enabled,
                'phase': self.phase_controller.get_status(),
                'prompt': {
                    'current_version': self.current_prompt_version,
                    'total_versions': len(self.prompt_versions),
                    'current_prompt_length': (
                        len(current_prompt.prompt_text) if current_prompt else 0
                    ),
                },
                'labeling': {
                    'human_labeled': len(self.human_labeled_ids),
                    'llm_labeled': len(self.llm_labeled_ids),
                    'overlap': len(self.human_labeled_ids & self.llm_labeled_ids),
                    'llm_only': len(self.llm_labeled_ids - self.human_labeled_ids),
                    'background_running': self.is_background_labeling_running(),
                },
                'agreement': self.agreement_metrics.to_dict(),
                'disagreements': {
                    'total': len(self.disagreement_ids),
                    'pending': len(self.get_pending_disagreements()),
                },
                'validation': {
                    'sample_size': len(self.validation_sample_ids),
                },
                'edge_cases': {
                    'count': len(self.edge_case_ids),
                },
                'thresholds': {
                    'end_human_annotation_agreement': self.config.thresholds.end_human_annotation_agreement,
                    'minimum_validation_sample': self.config.thresholds.minimum_validation_sample,
                    'should_end_human_annotation': self.should_end_human_annotation(),
                },
            }

    def shutdown(self) -> None:
        """Shutdown the manager, stopping background threads."""
        self.stop_background_labeling()
        self._save_state()
        logger.info("SoloModeManager shutdown complete")


# === Singleton Management ===

def init_solo_mode_manager(config_data: Dict[str, Any]) -> Optional[SoloModeManager]:
    """
    Initialize the singleton SoloModeManager.

    Args:
        config_data: Full application configuration

    Returns:
        SoloModeManager instance, or None if disabled
    """
    global _SOLO_MODE_MANAGER

    with _SOLO_MODE_LOCK:
        if _SOLO_MODE_MANAGER is None:
            solo_config = parse_solo_mode_config(config_data)

            if not solo_config.enabled:
                logger.info("Solo Mode disabled in config")
                return None

            # Validate config
            errors = solo_config.validate()
            if errors:
                for error in errors:
                    logger.error(f"Solo Mode config error: {error}")
                return None

            _SOLO_MODE_MANAGER = SoloModeManager(solo_config, config_data)
            _SOLO_MODE_MANAGER.load_state()

    return _SOLO_MODE_MANAGER


def get_solo_mode_manager() -> Optional[SoloModeManager]:
    """Get the singleton SoloModeManager instance."""
    return _SOLO_MODE_MANAGER


def clear_solo_mode_manager() -> None:
    """Clear the singleton (for testing)."""
    global _SOLO_MODE_MANAGER

    with _SOLO_MODE_LOCK:
        if _SOLO_MODE_MANAGER is not None:
            _SOLO_MODE_MANAGER.shutdown()
        _SOLO_MODE_MANAGER = None
