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


# DisagreementResolver was removed: its check_and_record() was never wired
# into any code path. The authoritative disagreement state lives on
# SoloModeManager.disagreement_ids and is read via
# SoloModeManager.get_pending_disagreements(). DisagreementDetector (above)
# is still used directly by integration tests for type-specific detection.
