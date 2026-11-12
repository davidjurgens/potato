"""
Judge Calibration phase state machine.

A minimal linear workflow (no branching loops, unlike solo mode):

    SETUP -> GENERATING -> HUMAN_CALIBRATION -> REPORT -> COMPLETED

State persists atomically to ``<state_dir>/phase_state.json`` so a run resumes
across server restarts.
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


class JCPhase(Enum):
    """Judge Calibration workflow phases."""
    SETUP = auto()              # Config loaded; nothing generated yet
    GENERATING = auto()         # LLMs labeling in the background
    HUMAN_CALIBRATION = auto()  # Human(s) blind-labeling the sample
    REPORT = auto()             # Metrics/report being built
    COMPLETED = auto()          # Report available

    @classmethod
    def from_str(cls, s: str) -> "JCPhase":
        return cls[s.upper().replace("-", "_")]

    def to_str(self) -> str:
        return self.name.lower().replace("_", "-")


PHASE_TRANSITIONS: Dict[JCPhase, Set[JCPhase]] = {
    JCPhase.SETUP: {JCPhase.GENERATING},
    JCPhase.GENERATING: {JCPhase.HUMAN_CALIBRATION, JCPhase.SETUP},
    JCPhase.HUMAN_CALIBRATION: {JCPhase.REPORT},
    JCPhase.REPORT: {JCPhase.COMPLETED, JCPhase.HUMAN_CALIBRATION},
    JCPhase.COMPLETED: {JCPhase.REPORT},  # allow re-running the report
}


@dataclass
class JCPhaseState:
    """Serializable phase state for a calibration run."""
    current_phase: JCPhase = JCPhase.SETUP
    phase_data: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, str]] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_phase": self.current_phase.to_str(),
            "phase_data": self.phase_data,
            "history": self.history,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JCPhaseState":
        return cls(
            current_phase=JCPhase.from_str(data.get("current_phase", "setup")),
            phase_data=data.get("phase_data", {}),
            history=data.get("history", []),
            started_at=(
                datetime.fromisoformat(data["started_at"])
                if data.get("started_at") else None
            ),
            completed_at=(
                datetime.fromisoformat(data["completed_at"])
                if data.get("completed_at") else None
            ),
        )


class JCPhaseController:
    """Phase state machine with atomic JSON persistence."""

    _STATE_FILE = "phase_state.json"

    def __init__(self, state_dir: Optional[str] = None):
        self._lock = threading.RLock()
        self.state = JCPhaseState()
        self.state_dir = state_dir

    def get_current_phase(self) -> JCPhase:
        with self._lock:
            return self.state.current_phase

    def is_phase(self, phase: JCPhase) -> bool:
        return self.get_current_phase() == phase

    def can_transition_to(self, target: JCPhase) -> bool:
        with self._lock:
            return target in PHASE_TRANSITIONS.get(self.state.current_phase, set())

    def transition_to(self, target: JCPhase, reason: str = "", force: bool = False) -> bool:
        with self._lock:
            current = self.state.current_phase
            if not force and not self.can_transition_to(target):
                raise ValueError(
                    f"Invalid phase transition: {current.to_str()} -> {target.to_str()}. "
                    f"Allowed: {[p.to_str() for p in PHASE_TRANSITIONS.get(current, set())]}"
                )
            self.state.history.append({
                "from": current.to_str(),
                "to": target.to_str(),
                "timestamp": datetime.now().isoformat(),
                "reason": reason,
            })
            self.state.current_phase = target
            if current == JCPhase.SETUP and self.state.started_at is None:
                self.state.started_at = datetime.now()
            if target == JCPhase.COMPLETED:
                self.state.completed_at = datetime.now()
            logger.info("JC phase: %s -> %s (%s)", current.to_str(), target.to_str(), reason or "none")
            self._save_state()
            return True

    def get_phase_data(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self.state.phase_data.get(key, default)

    def set_phase_data(self, key: str, value: Any) -> None:
        with self._lock:
            self.state.phase_data[key] = value
            self._save_state()

    def reset(self) -> None:
        with self._lock:
            self.state = JCPhaseState()
            self._save_state()

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "current_phase": self.state.current_phase.to_str(),
                "started_at": self.state.started_at.isoformat() if self.state.started_at else None,
                "completed_at": self.state.completed_at.isoformat() if self.state.completed_at else None,
                "history": self.state.history,
            }

    def _save_state(self) -> None:
        if not self.state_dir:
            return
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            path = os.path.join(self.state_dir, self._STATE_FILE)
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.state.to_dict(), f, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            logger.error("Error saving JC phase state: %s", e)

    def load_state(self) -> bool:
        if not self.state_dir:
            return False
        path = os.path.join(self.state_dir, self._STATE_FILE)
        if not os.path.exists(path):
            return False
        try:
            with open(path) as f:
                data = json.load(f)
            with self._lock:
                self.state = JCPhaseState.from_dict(data)
            logger.info("Loaded JC phase state: %s", self.state.current_phase.to_str())
            return True
        except Exception as e:
            logger.error("Error loading JC phase state: %s", e)
            return False
