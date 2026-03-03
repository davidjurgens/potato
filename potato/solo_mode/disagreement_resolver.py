"""
Disagreement Resolver for Solo Mode

This module handles detection and resolution of disagreements between
human and LLM annotations. It provides type-specific disagreement detection
and workflows for resolving conflicts.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
import threading

logger = logging.getLogger(__name__)


class DisagreementType(Enum):
    """Types of disagreements between human and LLM."""
    EXACT_MISMATCH = "exact_mismatch"      # Categorical labels differ
    THRESHOLD_EXCEEDED = "threshold"        # Numeric difference > threshold
    LOW_OVERLAP = "low_overlap"            # Set/span overlap below threshold
    SEMANTIC_DIFFERENCE = "semantic"       # Text responses differ semantically


@dataclass
class Disagreement:
    """Record of a disagreement between human and LLM."""
    id: str
    instance_id: str
    schema_name: str
    human_label: Any
    llm_label: Any
    llm_confidence: float
    disagreement_type: DisagreementType
    detected_at: datetime = field(default_factory=datetime.now)

    # Resolution
    resolved: bool = False
    resolution_label: Optional[Any] = None
    resolution_source: Optional[str] = None  # 'human_wins', 'llm_wins', 'revised'
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None

    # For prompt revision
    triggered_revision: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'id': self.id,
            'instance_id': self.instance_id,
            'schema_name': self.schema_name,
            'human_label': self.human_label,
            'llm_label': self.llm_label,
            'llm_confidence': self.llm_confidence,
            'disagreement_type': self.disagreement_type.value,
            'detected_at': self.detected_at.isoformat(),
            'resolved': self.resolved,
            'resolution_label': self.resolution_label,
            'resolution_source': self.resolution_source,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'resolution_notes': self.resolution_notes,
            'triggered_revision': self.triggered_revision,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Disagreement':
        """Deserialize from dictionary."""
        return cls(
            id=data['id'],
            instance_id=data['instance_id'],
            schema_name=data['schema_name'],
            human_label=data['human_label'],
            llm_label=data['llm_label'],
            llm_confidence=data['llm_confidence'],
            disagreement_type=DisagreementType(data['disagreement_type']),
            detected_at=datetime.fromisoformat(data['detected_at']),
            resolved=data.get('resolved', False),
            resolution_label=data.get('resolution_label'),
            resolution_source=data.get('resolution_source'),
            resolved_at=(
                datetime.fromisoformat(data['resolved_at'])
                if data.get('resolved_at') else None
            ),
            resolution_notes=data.get('resolution_notes'),
            triggered_revision=data.get('triggered_revision', False),
        )


class DisagreementDetector:
    """
    Detects disagreements between human and LLM annotations.

    Uses type-specific comparison logic based on annotation type.
    """

    def __init__(self, thresholds: Optional[Dict[str, float]] = None):
        """
        Initialize the detector.

        Args:
            thresholds: Optional threshold configuration
        """
        self.thresholds = thresholds or {}

    def detect(
        self,
        annotation_type: str,
        human_label: Any,
        llm_label: Any,
        schema_info: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, DisagreementType]:
        """
        Check if human and LLM labels disagree.

        Args:
            annotation_type: The type of annotation
            human_label: The human's label
            llm_label: The LLM's label
            schema_info: Optional schema information

        Returns:
            Tuple of (is_disagreement, disagreement_type)
        """
        if annotation_type in ('radio', 'select'):
            return self._check_categorical(human_label, llm_label)

        elif annotation_type == 'likert':
            return self._check_likert(human_label, llm_label)

        elif annotation_type == 'multiselect':
            return self._check_multiselect(human_label, llm_label)

        elif annotation_type == 'textbox':
            return self._check_textbox(human_label, llm_label)

        elif annotation_type == 'span':
            return self._check_span(human_label, llm_label)

        elif annotation_type in ('slider', 'number'):
            return self._check_numeric(human_label, llm_label, schema_info)

        else:
            # Default to exact match
            return self._check_categorical(human_label, llm_label)

    def _check_categorical(
        self,
        human_label: Any,
        llm_label: Any
    ) -> Tuple[bool, DisagreementType]:
        """Check categorical (exact match) disagreement."""
        agrees = str(human_label) == str(llm_label)
        return (not agrees, DisagreementType.EXACT_MISMATCH)

    def _check_likert(
        self,
        human_label: Any,
        llm_label: Any
    ) -> Tuple[bool, DisagreementType]:
        """Check likert scale disagreement with tolerance."""
        tolerance = self.thresholds.get('likert_tolerance', 1)
        try:
            diff = abs(int(human_label) - int(llm_label))
            agrees = diff <= tolerance
            return (not agrees, DisagreementType.THRESHOLD_EXCEEDED)
        except (ValueError, TypeError):
            return self._check_categorical(human_label, llm_label)

    def _check_multiselect(
        self,
        human_label: Any,
        llm_label: Any
    ) -> Tuple[bool, DisagreementType]:
        """Check multiselect disagreement using Jaccard similarity."""
        threshold = self.thresholds.get('multiselect_jaccard_threshold', 0.5)

        human_set = set(human_label) if isinstance(human_label, (list, set)) else {human_label}
        llm_set = set(llm_label) if isinstance(llm_label, (list, set)) else {llm_label}

        if not human_set and not llm_set:
            return (False, DisagreementType.LOW_OVERLAP)

        intersection = len(human_set & llm_set)
        union = len(human_set | llm_set)
        jaccard = intersection / union if union > 0 else 0

        agrees = jaccard >= threshold
        return (not agrees, DisagreementType.LOW_OVERLAP)

    def _check_textbox(
        self,
        human_label: Any,
        llm_label: Any
    ) -> Tuple[bool, DisagreementType]:
        """
        Check textbox disagreement.

        Currently uses exact match; could be enhanced with
        embedding similarity.
        """
        human_text = str(human_label).strip().lower()
        llm_text = str(llm_label).strip().lower()
        agrees = human_text == llm_text
        return (not agrees, DisagreementType.SEMANTIC_DIFFERENCE)

    def _check_span(
        self,
        human_label: Any,
        llm_label: Any
    ) -> Tuple[bool, DisagreementType]:
        """
        Check span annotation disagreement.

        Compares span boundaries with overlap threshold.
        """
        threshold = self.thresholds.get('span_overlap_threshold', 0.5)

        # Extract span info (assuming dict format)
        human_spans = self._normalize_spans(human_label)
        llm_spans = self._normalize_spans(llm_label)

        if not human_spans and not llm_spans:
            return (False, DisagreementType.LOW_OVERLAP)

        if not human_spans or not llm_spans:
            return (True, DisagreementType.LOW_OVERLAP)

        # Calculate overlap
        total_overlap = 0
        total_human_length = 0

        for h_span in human_spans:
            h_start, h_end = h_span['start'], h_span['end']
            total_human_length += (h_end - h_start)

            for l_span in llm_spans:
                l_start, l_end = l_span['start'], l_span['end']
                overlap_start = max(h_start, l_start)
                overlap_end = min(h_end, l_end)
                if overlap_end > overlap_start:
                    total_overlap += (overlap_end - overlap_start)

        overlap_ratio = total_overlap / total_human_length if total_human_length > 0 else 0
        agrees = overlap_ratio >= threshold
        return (not agrees, DisagreementType.LOW_OVERLAP)

    def _normalize_spans(self, spans: Any) -> List[Dict[str, int]]:
        """Normalize span format to list of {start, end} dicts."""
        if not spans:
            return []

        if isinstance(spans, list):
            result = []
            for span in spans:
                if isinstance(span, dict) and 'start' in span and 'end' in span:
                    result.append({'start': span['start'], 'end': span['end']})
            return result

        if isinstance(spans, dict) and 'start' in spans and 'end' in spans:
            return [{'start': spans['start'], 'end': spans['end']}]

        return []

    def _check_numeric(
        self,
        human_label: Any,
        llm_label: Any,
        schema_info: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, DisagreementType]:
        """Check numeric value disagreement with relative tolerance."""
        try:
            human_val = float(human_label)
            llm_val = float(llm_label)

            # Use relative tolerance based on range
            if schema_info:
                min_val = schema_info.get('min_value', 0)
                max_val = schema_info.get('max_value', 100)
                value_range = max_val - min_val
                tolerance = value_range * 0.1  # 10% of range
            else:
                tolerance = abs(human_val) * 0.1 if human_val != 0 else 0.1

            agrees = abs(human_val - llm_val) <= tolerance
            return (not agrees, DisagreementType.THRESHOLD_EXCEEDED)

        except (ValueError, TypeError):
            return self._check_categorical(human_label, llm_label)


class DisagreementResolver:
    """
    Manages disagreement resolution workflow.

    Tracks disagreements, provides resolution UI support,
    and triggers prompt revision when patterns emerge.
    """

    def __init__(self, config: Dict[str, Any], solo_config: Any):
        """
        Initialize the resolver.

        Args:
            config: Full application configuration
            solo_config: SoloModeConfig instance
        """
        self.config = config
        self.solo_config = solo_config
        self._lock = threading.RLock()

        # Initialize detector with thresholds from config
        thresholds = {
            'likert_tolerance': solo_config.thresholds.likert_tolerance,
            'multiselect_jaccard_threshold': solo_config.thresholds.multiselect_jaccard_threshold,
            'span_overlap_threshold': solo_config.thresholds.span_overlap_threshold,
        }
        self.detector = DisagreementDetector(thresholds)

        # Disagreement storage
        self.disagreements: Dict[str, Disagreement] = {}  # id -> Disagreement
        self._id_counter = 0

        # Analytics
        self.total_comparisons = 0
        self.total_disagreements = 0

    def _generate_id(self) -> str:
        """Generate a unique disagreement ID."""
        self._id_counter += 1
        return f"dis_{self._id_counter:04d}"

    def check_and_record(
        self,
        instance_id: str,
        schema_name: str,
        human_label: Any,
        llm_label: Any,
        llm_confidence: float
    ) -> Optional[Disagreement]:
        """
        Check for disagreement and record if found.

        Args:
            instance_id: The instance ID
            schema_name: The annotation schema
            human_label: Human's label
            llm_label: LLM's label
            llm_confidence: LLM's confidence score

        Returns:
            Disagreement object if there is a disagreement, None otherwise
        """
        with self._lock:
            self.total_comparisons += 1

            # Get annotation type for this schema
            annotation_type = self._get_annotation_type(schema_name)

            # Get schema info for type-specific comparison
            schemes = self.config.get('annotation_schemes', [])
            schema_info = next(
                (s for s in schemes if s.get('name') == schema_name),
                None
            )

            # Check for disagreement
            is_disagreement, disagreement_type = self.detector.detect(
                annotation_type,
                human_label,
                llm_label,
                schema_info
            )

            if not is_disagreement:
                return None

            self.total_disagreements += 1

            # Record disagreement
            disagreement = Disagreement(
                id=self._generate_id(),
                instance_id=instance_id,
                schema_name=schema_name,
                human_label=human_label,
                llm_label=llm_label,
                llm_confidence=llm_confidence,
                disagreement_type=disagreement_type,
            )

            self.disagreements[disagreement.id] = disagreement

            logger.info(
                f"Recorded disagreement {disagreement.id}: "
                f"{instance_id}:{schema_name} - human={human_label}, llm={llm_label}"
            )

            return disagreement

    def _get_annotation_type(self, schema_name: str) -> str:
        """Get annotation type for a schema."""
        schemes = self.config.get('annotation_schemes', [])
        for scheme in schemes:
            if scheme.get('name') == schema_name:
                return scheme.get('annotation_type', 'radio')
        return 'radio'

    def resolve(
        self,
        disagreement_id: str,
        resolution_label: Any,
        resolution_source: str,
        notes: Optional[str] = None
    ) -> bool:
        """
        Resolve a disagreement.

        Args:
            disagreement_id: The disagreement ID
            resolution_label: The final label
            resolution_source: How it was resolved ('human_wins', 'llm_wins', 'revised')
            notes: Optional resolution notes

        Returns:
            True if resolved successfully
        """
        with self._lock:
            if disagreement_id not in self.disagreements:
                logger.warning(f"Unknown disagreement: {disagreement_id}")
                return False

            disagreement = self.disagreements[disagreement_id]
            disagreement.resolved = True
            disagreement.resolution_label = resolution_label
            disagreement.resolution_source = resolution_source
            disagreement.resolved_at = datetime.now()
            disagreement.resolution_notes = notes

            logger.info(
                f"Resolved disagreement {disagreement_id}: "
                f"source={resolution_source}, label={resolution_label}"
            )

            return True

    def get_pending_disagreements(self) -> List[Disagreement]:
        """Get unresolved disagreements."""
        with self._lock:
            return [d for d in self.disagreements.values() if not d.resolved]

    def get_disagreement(self, disagreement_id: str) -> Optional[Disagreement]:
        """Get a specific disagreement."""
        with self._lock:
            return self.disagreements.get(disagreement_id)

    def get_disagreements_for_instance(self, instance_id: str) -> List[Disagreement]:
        """Get all disagreements for an instance."""
        with self._lock:
            return [
                d for d in self.disagreements.values()
                if d.instance_id == instance_id
            ]

    def get_cases_for_prompt_revision(self) -> List[Dict[str, Any]]:
        """
        Get resolved disagreements formatted for prompt revision.

        Returns cases where the human was right (LLM was wrong).
        """
        with self._lock:
            cases = []
            for d in self.disagreements.values():
                if d.resolved and d.resolution_source == 'human_wins':
                    cases.append({
                        'text': '',  # Would need instance text
                        'expected_label': d.human_label,
                        'actual_label': d.llm_label,
                        'llm_confidence': d.llm_confidence,
                        'disagreement_type': d.disagreement_type.value,
                    })
            return cases

    def mark_revision_triggered(self, disagreement_ids: List[str]) -> None:
        """Mark that these disagreements triggered a prompt revision."""
        with self._lock:
            for did in disagreement_ids:
                if did in self.disagreements:
                    self.disagreements[did].triggered_revision = True

    def get_disagreement_rate(self) -> float:
        """Get the overall disagreement rate."""
        with self._lock:
            if self.total_comparisons == 0:
                return 0.0
            return self.total_disagreements / self.total_comparisons

    def get_stats(self) -> Dict[str, Any]:
        """Get disagreement statistics."""
        with self._lock:
            pending = len(self.get_pending_disagreements())
            resolved = len([d for d in self.disagreements.values() if d.resolved])

            # Resolution source breakdown
            from collections import Counter
            resolution_sources = Counter(
                d.resolution_source
                for d in self.disagreements.values()
                if d.resolved
            )

            return {
                'total_comparisons': self.total_comparisons,
                'total_disagreements': self.total_disagreements,
                'disagreement_rate': self.get_disagreement_rate(),
                'pending': pending,
                'resolved': resolved,
                'resolution_sources': dict(resolution_sources),
                'triggered_revisions': len([
                    d for d in self.disagreements.values()
                    if d.triggered_revision
                ]),
            }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for persistence."""
        with self._lock:
            return {
                'disagreements': {
                    did: d.to_dict()
                    for did, d in self.disagreements.items()
                },
                'id_counter': self._id_counter,
                'total_comparisons': self.total_comparisons,
                'total_disagreements': self.total_disagreements,
            }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load from dictionary."""
        with self._lock:
            self.disagreements = {
                did: Disagreement.from_dict(d_data)
                for did, d_data in data.get('disagreements', {}).items()
            }
            self._id_counter = data.get('id_counter', len(self.disagreements))
            self.total_comparisons = data.get('total_comparisons', 0)
            self.total_disagreements = data.get('total_disagreements', 0)
