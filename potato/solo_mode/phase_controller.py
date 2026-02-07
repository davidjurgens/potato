"""
Solo Mode Phase Controller

This module defines the Solo Mode workflow phases and state machine.

Phase State Machine:
    SETUP → PROMPT_REVIEW → EDGE_CASE_SYNTHESIS → EDGE_CASE_LABELING
        → PROMPT_VALIDATION → PARALLEL_ANNOTATION ⟷ DISAGREEMENT_RESOLUTION
        → ACTIVE_ANNOTATION ⟷ PERIODIC_REVIEW → AUTONOMOUS_LABELING
        → FINAL_VALIDATION → COMPLETED
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set
import json
import logging
import os
import threading

logger = logging.getLogger(__name__)


class SoloPhase(Enum):
    """
    Enumeration of Solo Mode workflow phases.

    The phases represent the progression through the human-LLM
    collaborative annotation workflow.
    """
    # Initial setup
    SETUP = auto()                      # Task description, data upload
    PROMPT_REVIEW = auto()              # Review/edit synthesized prompt

    # Edge case refinement
    EDGE_CASE_SYNTHESIS = auto()        # LLM generates boundary examples
    EDGE_CASE_LABELING = auto()         # Human labels edge cases
    PROMPT_VALIDATION = auto()          # Verify prompt matches human labels

    # Parallel annotation
    PARALLEL_ANNOTATION = auto()        # Human and LLM annotate in parallel
    DISAGREEMENT_RESOLUTION = auto()    # Resolve human-LLM conflicts

    # Active annotation with periodic review
    ACTIVE_ANNOTATION = auto()          # Main annotation phase
    PERIODIC_REVIEW = auto()            # Review low-confidence LLM labels

    # Autonomous completion
    AUTONOMOUS_LABELING = auto()        # LLM labels remaining data
    FINAL_VALIDATION = auto()           # Human validates LLM-only labels
    COMPLETED = auto()                  # Workflow complete

    @classmethod
    def from_str(cls, s: str) -> 'SoloPhase':
        """Parse phase from string."""
        name = s.upper().replace('-', '_')
        return cls[name]

    def to_str(self) -> str:
        """Convert phase to string."""
        return self.name.lower().replace('_', '-')


# Phase transition rules: source -> allowed destinations
PHASE_TRANSITIONS: Dict[SoloPhase, Set[SoloPhase]] = {
    SoloPhase.SETUP: {SoloPhase.PROMPT_REVIEW},
    SoloPhase.PROMPT_REVIEW: {SoloPhase.EDGE_CASE_SYNTHESIS, SoloPhase.PARALLEL_ANNOTATION},
    SoloPhase.EDGE_CASE_SYNTHESIS: {SoloPhase.EDGE_CASE_LABELING},
    SoloPhase.EDGE_CASE_LABELING: {SoloPhase.PROMPT_VALIDATION, SoloPhase.PROMPT_REVIEW},
    SoloPhase.PROMPT_VALIDATION: {SoloPhase.PARALLEL_ANNOTATION, SoloPhase.PROMPT_REVIEW},
    SoloPhase.PARALLEL_ANNOTATION: {
        SoloPhase.DISAGREEMENT_RESOLUTION,
        SoloPhase.ACTIVE_ANNOTATION,
    },
    SoloPhase.DISAGREEMENT_RESOLUTION: {
        SoloPhase.PARALLEL_ANNOTATION,
        SoloPhase.PROMPT_REVIEW,  # If major prompt revision needed
    },
    SoloPhase.ACTIVE_ANNOTATION: {
        SoloPhase.PERIODIC_REVIEW,
        SoloPhase.AUTONOMOUS_LABELING,
    },
    SoloPhase.PERIODIC_REVIEW: {
        SoloPhase.ACTIVE_ANNOTATION,
        SoloPhase.PROMPT_REVIEW,  # If prompt needs revision
    },
    SoloPhase.AUTONOMOUS_LABELING: {SoloPhase.FINAL_VALIDATION},
    SoloPhase.FINAL_VALIDATION: {
        SoloPhase.COMPLETED,
        SoloPhase.ACTIVE_ANNOTATION,  # If validation fails
    },
    SoloPhase.COMPLETED: set(),  # Terminal state
}


@dataclass
class PhaseTransition:
    """Record of a phase transition."""
    from_phase: SoloPhase
    to_phase: SoloPhase
    timestamp: datetime
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'from_phase': self.from_phase.to_str(),
            'to_phase': self.to_phase.to_str(),
            'timestamp': self.timestamp.isoformat(),
            'reason': self.reason,
            'metadata': self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PhaseTransition':
        """Deserialize from dictionary."""
        return cls(
            from_phase=SoloPhase.from_str(data['from_phase']),
            to_phase=SoloPhase.from_str(data['to_phase']),
            timestamp=datetime.fromisoformat(data['timestamp']),
            reason=data.get('reason', ''),
            metadata=data.get('metadata', {}),
        )


@dataclass
class PhaseState:
    """State information for a Solo Mode session."""
    current_phase: SoloPhase = SoloPhase.SETUP
    transition_history: List[PhaseTransition] = field(default_factory=list)
    phase_data: Dict[str, Any] = field(default_factory=dict)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'current_phase': self.current_phase.to_str(),
            'transition_history': [t.to_dict() for t in self.transition_history],
            'phase_data': self.phase_data,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PhaseState':
        """Deserialize from dictionary."""
        return cls(
            current_phase=SoloPhase.from_str(data['current_phase']),
            transition_history=[
                PhaseTransition.from_dict(t)
                for t in data.get('transition_history', [])
            ],
            phase_data=data.get('phase_data', {}),
            started_at=(
                datetime.fromisoformat(data['started_at'])
                if data.get('started_at') else None
            ),
            completed_at=(
                datetime.fromisoformat(data['completed_at'])
                if data.get('completed_at') else None
            ),
        )


class SoloPhaseController:
    """
    Controller for Solo Mode phase state machine.

    Manages phase transitions, validates transitions against allowed
    transitions, and maintains transition history.
    """

    def __init__(self, state_dir: Optional[str] = None):
        """
        Initialize the phase controller.

        Args:
            state_dir: Directory for persisting state
        """
        self._lock = threading.RLock()
        self.state = PhaseState()
        self.state_dir = state_dir
        self._state_file = 'phase_state.json'

    def get_current_phase(self) -> SoloPhase:
        """Get the current phase."""
        with self._lock:
            return self.state.current_phase

    def is_phase(self, phase: SoloPhase) -> bool:
        """Check if currently in a specific phase."""
        return self.get_current_phase() == phase

    def is_completed(self) -> bool:
        """Check if the workflow is completed."""
        return self.is_phase(SoloPhase.COMPLETED)

    def get_allowed_transitions(self) -> Set[SoloPhase]:
        """Get phases that can be transitioned to from current phase."""
        with self._lock:
            return PHASE_TRANSITIONS.get(self.state.current_phase, set()).copy()

    def can_transition_to(self, target_phase: SoloPhase) -> bool:
        """Check if transition to target phase is allowed."""
        with self._lock:
            allowed = PHASE_TRANSITIONS.get(self.state.current_phase, set())
            return target_phase in allowed

    def transition_to(
        self,
        target_phase: SoloPhase,
        reason: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        force: bool = False
    ) -> bool:
        """
        Transition to a new phase.

        Args:
            target_phase: The phase to transition to
            reason: Reason for the transition
            metadata: Additional metadata for the transition
            force: If True, allow invalid transitions (for recovery)

        Returns:
            True if transition was successful

        Raises:
            ValueError: If transition is not allowed and force=False
        """
        with self._lock:
            current = self.state.current_phase

            if not force and not self.can_transition_to(target_phase):
                raise ValueError(
                    f"Invalid phase transition: {current.to_str()} -> {target_phase.to_str()}. "
                    f"Allowed transitions: {[p.to_str() for p in self.get_allowed_transitions()]}"
                )

            # Record transition
            transition = PhaseTransition(
                from_phase=current,
                to_phase=target_phase,
                timestamp=datetime.now(),
                reason=reason,
                metadata=metadata or {},
            )
            self.state.transition_history.append(transition)

            # Update state
            self.state.current_phase = target_phase

            # Update timestamps
            if current == SoloPhase.SETUP and self.state.started_at is None:
                self.state.started_at = datetime.now()

            if target_phase == SoloPhase.COMPLETED:
                self.state.completed_at = datetime.now()

            logger.info(
                f"Phase transition: {current.to_str()} -> {target_phase.to_str()} "
                f"(reason: {reason or 'none'})"
            )

            # Persist state
            self._save_state()

            return True

    def advance_to_next_phase(self, reason: str = "") -> bool:
        """
        Advance to the next logical phase in the workflow.

        For phases with multiple possible transitions, this selects
        the "primary" next phase (the first in the set).

        Returns:
            True if advanced, False if no valid transition
        """
        with self._lock:
            allowed = self.get_allowed_transitions()
            if not allowed:
                return False

            # Get the primary next phase (lowest enum value)
            next_phase = min(allowed, key=lambda p: p.value)
            return self.transition_to(next_phase, reason=reason)

    def get_phase_data(self, key: str, default: Any = None) -> Any:
        """Get phase-specific data."""
        with self._lock:
            return self.state.phase_data.get(key, default)

    def set_phase_data(self, key: str, value: Any) -> None:
        """Set phase-specific data."""
        with self._lock:
            self.state.phase_data[key] = value
            self._save_state()

    def get_transition_history(self) -> List[PhaseTransition]:
        """Get the full transition history."""
        with self._lock:
            return self.state.transition_history.copy()

    def get_time_in_phase(self) -> Optional[float]:
        """Get seconds spent in current phase."""
        with self._lock:
            if not self.state.transition_history:
                return None

            # Find last transition to current phase
            for transition in reversed(self.state.transition_history):
                if transition.to_phase == self.state.current_phase:
                    return (datetime.now() - transition.timestamp).total_seconds()

            return None

    def get_total_duration(self) -> Optional[float]:
        """Get total workflow duration in seconds."""
        with self._lock:
            if not self.state.started_at:
                return None

            end = self.state.completed_at or datetime.now()
            return (end - self.state.started_at).total_seconds()

    def reset(self) -> None:
        """Reset the controller to initial state."""
        with self._lock:
            self.state = PhaseState()
            self._save_state()
            logger.info("Phase controller reset to SETUP")

    def get_status(self) -> Dict[str, Any]:
        """Get current status information."""
        with self._lock:
            return {
                'current_phase': self.state.current_phase.to_str(),
                'allowed_transitions': [p.to_str() for p in self.get_allowed_transitions()],
                'transition_count': len(self.state.transition_history),
                'time_in_phase_seconds': self.get_time_in_phase(),
                'total_duration_seconds': self.get_total_duration(),
                'started_at': (
                    self.state.started_at.isoformat()
                    if self.state.started_at else None
                ),
                'completed_at': (
                    self.state.completed_at.isoformat()
                    if self.state.completed_at else None
                ),
                'is_completed': self.is_completed(),
            }

    def _save_state(self) -> None:
        """Save state to disk."""
        if not self.state_dir:
            return

        try:
            os.makedirs(self.state_dir, exist_ok=True)
            filepath = os.path.join(self.state_dir, self._state_file)

            # Atomic write
            temp_path = filepath + '.tmp'
            with open(temp_path, 'w') as f:
                json.dump(self.state.to_dict(), f, indent=2)
            os.replace(temp_path, filepath)

        except Exception as e:
            logger.error(f"Error saving phase state: {e}")

    def load_state(self) -> bool:
        """
        Load state from disk.

        Returns:
            True if state was loaded, False if no state file exists
        """
        if not self.state_dir:
            return False

        filepath = os.path.join(self.state_dir, self._state_file)

        if not os.path.exists(filepath):
            return False

        try:
            with open(filepath, 'r') as f:
                data = json.load(f)

            with self._lock:
                self.state = PhaseState.from_dict(data)

            logger.info(f"Loaded phase state: {self.state.current_phase.to_str()}")
            return True

        except Exception as e:
            logger.error(f"Error loading phase state: {e}")
            return False
