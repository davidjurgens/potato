"""
Validation Tracker for Solo Mode

This module tracks agreement metrics between human and LLM annotations,
manages thresholds for phase transitions, and provides validation
sampling for final quality assurance.
"""

import logging
import random
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class AgreementMetrics:
    """Metrics for human-LLM agreement."""
    total_compared: int = 0
    agreements: int = 0
    disagreements: int = 0
    agreement_rate: float = 0.0

    # Per-label metrics
    label_agreements: Dict[str, int] = field(default_factory=dict)
    label_disagreements: Dict[str, int] = field(default_factory=dict)

    # Confusion tracking
    confusion_matrix: Dict[Tuple[str, str], int] = field(default_factory=dict)

    # Time-based tracking
    recent_agreement_rate: float = 0.0  # Last N comparisons
    trend: str = "stable"  # "improving", "declining", "stable"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'total_compared': self.total_compared,
            'agreements': self.agreements,
            'disagreements': self.disagreements,
            'agreement_rate': self.agreement_rate,
            'label_agreements': self.label_agreements,
            'label_disagreements': self.label_disagreements,
            'confusion_matrix': {
                f"{k[0]}|{k[1]}": v
                for k, v in self.confusion_matrix.items()
            },
            'recent_agreement_rate': self.recent_agreement_rate,
            'trend': self.trend,
        }


@dataclass
class ValidationSample:
    """A sample selected for final validation."""
    instance_id: str
    llm_label: Any
    llm_confidence: float
    selected_at: datetime = field(default_factory=datetime.now)

    # Human validation results
    human_label: Optional[Any] = None
    validated_at: Optional[datetime] = None
    agrees: Optional[bool] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'instance_id': self.instance_id,
            'llm_label': self.llm_label,
            'llm_confidence': self.llm_confidence,
            'selected_at': self.selected_at.isoformat(),
            'human_label': self.human_label,
            'validated_at': self.validated_at.isoformat() if self.validated_at else None,
            'agrees': self.agrees,
            'notes': self.notes,
        }


class ValidationTracker:
    """
    Tracks agreement metrics and manages validation sampling.

    This class monitors the agreement between human and LLM annotations,
    determines when thresholds are met for phase transitions, and
    manages sampling for final validation.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the validation tracker.

        Args:
            config: Configuration dictionary with threshold settings
        """
        self.config = config or {}
        self._lock = threading.RLock()

        # Load thresholds from config
        solo_config = self.config.get('solo_mode', {})
        thresholds = solo_config.get('thresholds', {})

        self.end_human_threshold = thresholds.get(
            'end_human_annotation_agreement', 0.90
        )
        self.minimum_validation_sample = thresholds.get(
            'minimum_validation_sample', 50
        )
        self.periodic_review_interval = thresholds.get(
            'periodic_review_interval', 100
        )

        # Metrics tracking
        self._metrics = AgreementMetrics()
        self._comparison_history: List[Dict[str, Any]] = []
        self._recent_window = 50  # Window for recent agreement rate

        # Validation samples
        self._validation_samples: Dict[str, ValidationSample] = {}
        self._validation_sample_size = self.minimum_validation_sample

        # Random state for reproducible sampling
        self._random = random.Random()

        # Tracking for periodic review
        self._llm_labels_since_review = 0

    def record_comparison(
        self,
        instance_id: str,
        human_label: Any,
        llm_label: Any,
        schema_name: str,
        agrees: bool
    ) -> None:
        """
        Record a comparison between human and LLM labels.

        Args:
            instance_id: The instance ID
            human_label: The human-assigned label
            llm_label: The LLM-predicted label
            schema_name: The annotation schema name
            agrees: Whether the labels agree
        """
        with self._lock:
            # Update overall metrics
            self._metrics.total_compared += 1
            if agrees:
                self._metrics.agreements += 1
            else:
                self._metrics.disagreements += 1

            # Calculate agreement rate
            if self._metrics.total_compared > 0:
                self._metrics.agreement_rate = (
                    self._metrics.agreements / self._metrics.total_compared
                )

            # Update per-label metrics
            human_str = str(human_label)
            llm_str = str(llm_label)

            if agrees:
                self._metrics.label_agreements[human_str] = (
                    self._metrics.label_agreements.get(human_str, 0) + 1
                )
            else:
                self._metrics.label_disagreements[human_str] = (
                    self._metrics.label_disagreements.get(human_str, 0) + 1
                )
                # Track confusion
                key = (llm_str, human_str)  # LLM predicted, human corrected
                self._metrics.confusion_matrix[key] = (
                    self._metrics.confusion_matrix.get(key, 0) + 1
                )

            # Record in history
            self._comparison_history.append({
                'instance_id': instance_id,
                'human_label': human_label,
                'llm_label': llm_label,
                'schema_name': schema_name,
                'agrees': agrees,
                'timestamp': datetime.now().isoformat(),
            })

            # Update recent agreement rate
            self._update_recent_metrics()

            logger.debug(
                f"Recorded comparison for {instance_id}: "
                f"agrees={agrees}, rate={self._metrics.agreement_rate:.2%}"
            )

    def _update_recent_metrics(self) -> None:
        """Update metrics based on recent comparisons."""
        if len(self._comparison_history) < 2:
            return

        # Calculate recent agreement rate
        recent = self._comparison_history[-self._recent_window:]
        recent_agreements = sum(1 for c in recent if c['agrees'])
        self._metrics.recent_agreement_rate = recent_agreements / len(recent)

        # Determine trend
        if len(self._comparison_history) >= self._recent_window * 2:
            older = self._comparison_history[
                -self._recent_window * 2:-self._recent_window
            ]
            older_rate = sum(1 for c in older if c['agrees']) / len(older)

            diff = self._metrics.recent_agreement_rate - older_rate
            if diff > 0.05:
                self._metrics.trend = "improving"
            elif diff < -0.05:
                self._metrics.trend = "declining"
            else:
                self._metrics.trend = "stable"

    def get_metrics(self) -> AgreementMetrics:
        """Get current agreement metrics."""
        with self._lock:
            return self._metrics

    def should_end_human_annotation(self) -> bool:
        """
        Check if agreement threshold is met for ending human annotation.

        Returns:
            True if the agreement rate meets the threshold
        """
        with self._lock:
            # Need minimum number of comparisons
            if self._metrics.total_compared < self.minimum_validation_sample:
                return False

            # Check if agreement rate meets threshold
            return self._metrics.agreement_rate >= self.end_human_threshold

    def should_trigger_periodic_review(self) -> bool:
        """
        Check if it's time for periodic review of LLM labels.

        Returns:
            True if periodic review should be triggered
        """
        with self._lock:
            return self._llm_labels_since_review >= self.periodic_review_interval

    def record_llm_label(self, instance_id: str) -> None:
        """Record that an LLM label was generated (for periodic review tracking)."""
        with self._lock:
            self._llm_labels_since_review += 1

    def reset_periodic_review_counter(self) -> None:
        """Reset the periodic review counter after a review."""
        with self._lock:
            self._llm_labels_since_review = 0

    def select_validation_sample(
        self,
        llm_labeled_instances: Dict[str, Dict[str, Any]],
        sample_size: Optional[int] = None
    ) -> List[str]:
        """
        Select a sample of LLM-labeled instances for final validation.

        Uses stratified sampling based on confidence levels.

        Args:
            llm_labeled_instances: Dict of instance_id -> {label, confidence}
            sample_size: Number of instances to sample (default: minimum_validation_sample)

        Returns:
            List of selected instance IDs
        """
        with self._lock:
            size = sample_size or self._validation_sample_size

            if len(llm_labeled_instances) <= size:
                # If we have fewer instances than sample size, use all
                selected_ids = list(llm_labeled_instances.keys())
            else:
                # Stratified sampling by confidence
                selected_ids = self._stratified_sample(
                    llm_labeled_instances, size
                )

            # Create validation samples
            for instance_id in selected_ids:
                pred = llm_labeled_instances[instance_id]
                self._validation_samples[instance_id] = ValidationSample(
                    instance_id=instance_id,
                    llm_label=pred.get('label'),
                    llm_confidence=pred.get('confidence', 0.5),
                )

            logger.info(f"Selected {len(selected_ids)} instances for validation")
            return selected_ids

    def _stratified_sample(
        self,
        instances: Dict[str, Dict[str, Any]],
        sample_size: int
    ) -> List[str]:
        """
        Perform stratified sampling based on confidence levels.

        Samples more from low-confidence instances to catch potential errors.
        """
        # Split into confidence strata
        low_conf = []  # < 0.5
        mid_conf = []  # 0.5 - 0.8
        high_conf = []  # >= 0.8

        for instance_id, pred in instances.items():
            conf = pred.get('confidence', 0.5)
            if conf < 0.5:
                low_conf.append(instance_id)
            elif conf < 0.8:
                mid_conf.append(instance_id)
            else:
                high_conf.append(instance_id)

        # Sample proportions: 40% low, 35% mid, 25% high
        # (oversamples low confidence)
        n_low = min(len(low_conf), int(sample_size * 0.4))
        n_mid = min(len(mid_conf), int(sample_size * 0.35))
        n_high = min(len(high_conf), sample_size - n_low - n_mid)

        # Adjust if strata are too small
        remaining = sample_size - n_low - n_mid - n_high
        if remaining > 0:
            # Redistribute remaining to available strata
            for stratum, current in [
                (high_conf, n_high),
                (mid_conf, n_mid),
                (low_conf, n_low)
            ]:
                available = len(stratum) - current
                take = min(available, remaining)
                if stratum is high_conf:
                    n_high += take
                elif stratum is mid_conf:
                    n_mid += take
                else:
                    n_low += take
                remaining -= take
                if remaining <= 0:
                    break

        # Perform random sampling from each stratum
        selected = []
        if low_conf and n_low > 0:
            selected.extend(self._random.sample(low_conf, n_low))
        if mid_conf and n_mid > 0:
            selected.extend(self._random.sample(mid_conf, n_mid))
        if high_conf and n_high > 0:
            selected.extend(self._random.sample(high_conf, n_high))

        return selected

    def record_validation_result(
        self,
        instance_id: str,
        human_label: Any,
        notes: Optional[str] = None
    ) -> bool:
        """
        Record the human validation result for a sample.

        Args:
            instance_id: The instance ID
            human_label: The human-assigned label
            notes: Optional validation notes

        Returns:
            True if the result was recorded
        """
        with self._lock:
            if instance_id not in self._validation_samples:
                logger.warning(f"Unknown validation sample: {instance_id}")
                return False

            sample = self._validation_samples[instance_id]
            sample.human_label = human_label
            sample.validated_at = datetime.now()
            sample.agrees = (sample.llm_label == human_label)
            sample.notes = notes

            logger.debug(
                f"Recorded validation for {instance_id}: "
                f"agrees={sample.agrees}"
            )
            return True

    def get_validation_progress(self) -> Dict[str, Any]:
        """Get progress on validation sample."""
        with self._lock:
            total = len(self._validation_samples)
            validated = sum(
                1 for s in self._validation_samples.values()
                if s.validated_at is not None
            )
            agreements = sum(
                1 for s in self._validation_samples.values()
                if s.agrees is True
            )

            return {
                'total_samples': total,
                'validated': validated,
                'remaining': total - validated,
                'agreements': agreements,
                'disagreements': validated - agreements,
                'validation_accuracy': (
                    agreements / validated if validated > 0 else 0.0
                ),
                'percent_complete': (
                    validated / total * 100 if total > 0 else 0.0
                ),
            }

    def get_unvalidated_samples(self) -> List[ValidationSample]:
        """Get validation samples that haven't been validated yet."""
        with self._lock:
            return [
                s for s in self._validation_samples.values()
                if s.validated_at is None
            ]

    def get_validation_samples(self) -> List[ValidationSample]:
        """Get all validation samples."""
        with self._lock:
            return list(self._validation_samples.values())

    def get_confusion_analysis(self) -> Dict[str, Any]:
        """
        Analyze confusion patterns between human and LLM labels.

        Returns:
            Analysis of common confusion patterns
        """
        with self._lock:
            if not self._metrics.confusion_matrix:
                return {'patterns': [], 'most_confused': None}

            # Sort by frequency
            sorted_confusion = sorted(
                self._metrics.confusion_matrix.items(),
                key=lambda x: x[1],
                reverse=True
            )

            patterns = []
            for (llm_label, human_label), count in sorted_confusion[:10]:
                patterns.append({
                    'llm_predicted': llm_label,
                    'human_corrected': human_label,
                    'count': count,
                    'percent': (
                        count / self._metrics.disagreements * 100
                        if self._metrics.disagreements > 0 else 0
                    ),
                })

            return {
                'patterns': patterns,
                'most_confused': patterns[0] if patterns else None,
                'total_disagreements': self._metrics.disagreements,
            }

    def get_label_accuracy(self) -> Dict[str, float]:
        """
        Get per-label accuracy rates.

        Returns:
            Dict of label -> accuracy rate
        """
        with self._lock:
            accuracies = {}
            all_labels = set(self._metrics.label_agreements.keys()) | set(
                self._metrics.label_disagreements.keys()
            )

            for label in all_labels:
                agreements = self._metrics.label_agreements.get(label, 0)
                disagreements = self._metrics.label_disagreements.get(label, 0)
                total = agreements + disagreements

                if total > 0:
                    accuracies[label] = agreements / total
                else:
                    accuracies[label] = 0.0

            return accuracies

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive tracker status."""
        with self._lock:
            return {
                'metrics': self._metrics.to_dict(),
                'thresholds': {
                    'end_human_annotation': self.end_human_threshold,
                    'minimum_validation_sample': self.minimum_validation_sample,
                    'periodic_review_interval': self.periodic_review_interval,
                },
                'should_end_human_annotation': self.should_end_human_annotation(),
                'should_trigger_review': self.should_trigger_periodic_review(),
                'llm_labels_since_review': self._llm_labels_since_review,
                'validation_progress': self.get_validation_progress(),
                'label_accuracy': self.get_label_accuracy(),
            }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for persistence."""
        with self._lock:
            return {
                'metrics': self._metrics.to_dict(),
                'comparison_history': self._comparison_history,
                'validation_samples': {
                    sid: sample.to_dict()
                    for sid, sample in self._validation_samples.items()
                },
                'llm_labels_since_review': self._llm_labels_since_review,
            }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load from dictionary."""
        with self._lock:
            # Restore metrics
            metrics_data = data.get('metrics', {})
            self._metrics = AgreementMetrics(
                total_compared=metrics_data.get('total_compared', 0),
                agreements=metrics_data.get('agreements', 0),
                disagreements=metrics_data.get('disagreements', 0),
                agreement_rate=metrics_data.get('agreement_rate', 0.0),
                label_agreements=metrics_data.get('label_agreements', {}),
                label_disagreements=metrics_data.get('label_disagreements', {}),
                recent_agreement_rate=metrics_data.get('recent_agreement_rate', 0.0),
                trend=metrics_data.get('trend', 'stable'),
            )

            # Restore confusion matrix
            confusion_data = metrics_data.get('confusion_matrix', {})
            for key_str, count in confusion_data.items():
                parts = key_str.split('|')
                if len(parts) == 2:
                    self._metrics.confusion_matrix[(parts[0], parts[1])] = count

            # Restore history
            self._comparison_history = data.get('comparison_history', [])

            # Restore validation samples
            samples_data = data.get('validation_samples', {})
            for sid, sample_data in samples_data.items():
                self._validation_samples[sid] = ValidationSample(
                    instance_id=sample_data['instance_id'],
                    llm_label=sample_data['llm_label'],
                    llm_confidence=sample_data['llm_confidence'],
                    selected_at=datetime.fromisoformat(sample_data['selected_at']),
                    human_label=sample_data.get('human_label'),
                    validated_at=(
                        datetime.fromisoformat(sample_data['validated_at'])
                        if sample_data.get('validated_at') else None
                    ),
                    agrees=sample_data.get('agrees'),
                    notes=sample_data.get('notes'),
                )

            self._llm_labels_since_review = data.get('llm_labels_since_review', 0)
