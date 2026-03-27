"""
Coding Agent Runner

Manages the lifecycle of a coding agent session. Mirrors AgentRunner
but adapted for terminal-based coding agents (no Playwright).

State machine: IDLE → RUNNING → PAUSED → COMPLETED → ERROR
Communication: SSE listener pattern (same as AgentRunner)
"""

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .coding_agent_backend import (
    CodingAgentBackend,
    CodingAgentEvent,
    CodingAgentEventType,
    create_backend,
)
from .coding_agent_sandbox import SandboxManager

logger = logging.getLogger(__name__)


class CodingAgentState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class CodingAgentConfig:
    """Configuration for a coding agent session."""
    backend_type: str = "ollama_tool_use"
    ai_config: Dict[str, Any] = field(default_factory=dict)
    working_dir: str = "."
    max_turns: int = 50
    system_prompt: str = ""
    sandbox_mode: str = "worktree"

    @classmethod
    def from_config(cls, config: dict) -> "CodingAgentConfig":
        """Create from YAML config dict."""
        live_config = config.get("live_coding_agent", {})
        return cls(
            backend_type=live_config.get("backend_type", "ollama_tool_use"),
            ai_config=live_config.get("ai_config", {}),
            working_dir=live_config.get("working_dir", "."),
            max_turns=live_config.get("max_turns", 50),
            system_prompt=live_config.get("system_prompt", ""),
            sandbox_mode=live_config.get("sandbox_mode", "worktree"),
        )


class CodingAgentRunner:
    """Manages a coding agent session with SSE event broadcasting."""

    def __init__(self, session_id: str, config: CodingAgentConfig,
                 trace_dir: str = ""):
        self.session_id = session_id
        self.config = config
        self.trace_dir = trace_dir

        self._state = CodingAgentState.IDLE
        self._state_lock = threading.Lock()
        self._listeners: List[Callable] = []
        self._listener_lock = threading.Lock()

        self._backend: Optional[CodingAgentBackend] = None
        self._sandbox: Optional[SandboxManager] = None
        self._structured_turns: List[Dict] = []
        self._task_description = ""
        self._started_at = 0.0
        self._event_thread: Optional[threading.Thread] = None

    @property
    def state(self) -> CodingAgentState:
        with self._state_lock:
            return self._state

    def _set_state(self, new_state: CodingAgentState):
        with self._state_lock:
            old = self._state
            self._state = new_state
        self._emit_event("state_change", {"old_state": old.value, "new_state": new_state.value})

    # --- Listener/SSE pattern (mirrors AgentRunner) ---

    def add_listener(self, callback: Callable) -> None:
        with self._listener_lock:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable) -> None:
        with self._listener_lock:
            self._listeners = [l for l in self._listeners if l is not callback]

    def _emit_event(self, event_type: str, data: dict):
        with self._listener_lock:
            for listener in self._listeners:
                try:
                    listener(event_type, data)
                except Exception:
                    pass

    # --- Control methods ---

    def start(self, task_description: str) -> None:
        """Start the coding agent session."""
        if self.state != CodingAgentState.IDLE:
            raise RuntimeError(f"Cannot start in state {self.state}")

        self._task_description = task_description
        self._started_at = time.time()
        self._structured_turns = []

        # Create sandbox
        self._sandbox = SandboxManager(
            mode=self.config.sandbox_mode,
            base_dir=os.path.abspath(self.config.working_dir),
        )
        working_dir = self._sandbox.create(self.session_id)

        # Create backend
        backend_config = {
            "ai_config": self.config.ai_config,
            "max_turns": self.config.max_turns,
        }
        self._backend = create_backend(self.config.backend_type, backend_config)

        # Start the backend
        self._backend.start(task_description, working_dir, self.config.system_prompt)
        self._set_state(CodingAgentState.RUNNING)

        # Start event consumer thread
        self._event_thread = threading.Thread(target=self._consume_events, daemon=True)
        self._event_thread.start()

        self._emit_event("started", {
            "session_id": self.session_id,
            "task": task_description,
            "backend": self.config.backend_type,
        })

    def pause(self) -> None:
        if self._backend:
            self._backend.pause()
        self._set_state(CodingAgentState.PAUSED)

    def resume(self) -> None:
        if self._backend:
            self._backend.resume()
        self._set_state(CodingAgentState.RUNNING)

    def inject_instruction(self, instruction: str) -> None:
        if self._backend:
            self._backend.inject_instruction(instruction)
        self._emit_event("instruction_received", {"instruction": instruction})

    def stop(self) -> None:
        if self._backend:
            self._backend.stop()
        self._set_state(CodingAgentState.COMPLETED)
        self._save_trace()

    # --- Event consumption ---

    def _consume_events(self):
        """Consume events from the backend and broadcast via SSE."""
        if not self._backend:
            return

        current_turn: Optional[Dict] = None

        try:
            for event in self._backend.get_events():
                et = event.event_type
                data = event.data

                if et == CodingAgentEventType.THINKING:
                    self._emit_event("thinking", data)

                elif et == CodingAgentEventType.TOOL_CALL_START:
                    self._emit_event("tool_call_start", data)

                elif et == CodingAgentEventType.TOOL_CALL_END:
                    self._emit_event("tool_call", data)

                elif et == CodingAgentEventType.TURN_END:
                    # Accumulate into structured_turns
                    turn = {
                        "role": "assistant",
                        "content": data.get("content", ""),
                        "tool_calls": data.get("tool_calls", []),
                    }
                    self._structured_turns.append(turn)
                    self._emit_event("turn_end", {
                        "turn_index": data.get("turn_index", len(self._structured_turns) - 1),
                        **turn,
                    })

                elif et == CodingAgentEventType.ERROR:
                    self._set_state(CodingAgentState.ERROR)
                    self._emit_event("error", data)

                elif et == CodingAgentEventType.COMPLETE:
                    self._set_state(CodingAgentState.COMPLETED)
                    self._emit_event("complete", {
                        "total_turns": len(self._structured_turns),
                    })
                    self._save_trace()

        except Exception as e:
            logger.exception("Error consuming backend events")
            self._set_state(CodingAgentState.ERROR)
            self._emit_event("error", {"message": str(e)})

    # --- Trace export ---

    def get_trace(self) -> Dict[str, Any]:
        """Get the full trace in CodingTraceDisplay format."""
        return {
            "session_id": self.session_id,
            "task_description": self._task_description,
            "structured_turns": list(self._structured_turns),
            "backend": self.config.backend_type,
            "model": self.config.ai_config.get("model", ""),
            "started_at": self._started_at,
            "sandbox_mode": self.config.sandbox_mode,
        }

    def get_structured_turns(self) -> List[Dict]:
        return list(self._structured_turns)

    def get_state_summary(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "task": self._task_description,
            "turns": len(self._structured_turns),
            "backend": self.config.backend_type,
        }

    def _save_trace(self):
        """Save trace to disk."""
        if not self.trace_dir:
            return

        os.makedirs(self.trace_dir, exist_ok=True)
        trace_path = os.path.join(self.trace_dir, "trace.json")
        try:
            with open(trace_path, "w", encoding="utf-8") as f:
                json.dump(self.get_trace(), f, indent=2, ensure_ascii=False)
            logger.info(f"Saved coding agent trace to {trace_path}")
        except Exception as e:
            logger.error(f"Failed to save trace: {e}")

    # --- Cleanup ---

    def cleanup(self):
        """Clean up resources."""
        if self._backend:
            try:
                self._backend.stop()
            except Exception:
                pass
        if self._sandbox:
            try:
                self._sandbox.cleanup()
            except Exception:
                pass
