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
from .coding_agent_branch import BranchManager
from .coding_agent_checkpoint import CheckpointManager
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
        self._checkpoint_mgr: Optional[CheckpointManager] = None
        self._branch_mgr: Optional[BranchManager] = None
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

        # Initialize checkpoint and branch managers
        self._checkpoint_mgr = CheckpointManager(working_dir, self.session_id)
        self._checkpoint_mgr.init()
        self._branch_mgr = BranchManager(self.session_id, working_dir)

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

                    # Create checkpoint for file-modifying tools
                    tool_name = data.get("tool", "")
                    if tool_name.lower() in ("edit", "write", "bash", "create", "replace"):
                        turn_idx = data.get("turn_index", len(self._structured_turns))
                        if self._checkpoint_mgr:
                            cp_id = self._checkpoint_mgr.create_checkpoint(
                                turn_idx, tool_name,
                                f"{tool_name} at step {turn_idx}",
                            )
                            if cp_id:
                                self._emit_event("checkpoint", {
                                    "step_index": turn_idx,
                                    "checkpoint_id": cp_id,
                                    "tool": tool_name,
                                })

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

    # --- Checkpoint + Rollback ---

    def rollback_to_step(self, step_index: int) -> bool:
        """Rollback files and conversation to the given step.

        Pauses the agent, restores files, truncates history.
        Returns True on success.
        """
        if self._backend:
            self._backend.pause()
        self._set_state(CodingAgentState.PAUSED)

        # Rollback files
        if self._checkpoint_mgr:
            if not self._checkpoint_mgr.rollback_to(step_index):
                return False

        # Truncate structured turns
        self._structured_turns = self._structured_turns[:step_index + 1]

        # Truncate backend conversation history
        if self._backend:
            self._backend.truncate_history(step_index + 1)

        self._emit_event("rollback", {
            "step_index": step_index,
            "remaining_turns": len(self._structured_turns),
        })
        return True

    def get_checkpoints(self) -> List[dict]:
        """Return list of checkpoint metadata."""
        if self._checkpoint_mgr:
            return self._checkpoint_mgr.list_checkpoints()
        return []

    def replay_from_step(self, step_index: int,
                         instructions: Optional[str] = None,
                         edited_actions: Optional[List[Dict]] = None) -> Optional[str]:
        """Create a new branch from step_index and resume the agent.

        Args:
            step_index: Step to branch from
            instructions: Optional new instructions to inject
            edited_actions: Optional modified tool calls to execute first

        Returns:
            The new branch_id, or None on failure.
        """
        # Pause current execution
        if self._backend:
            self._backend.pause()
        self._set_state(CodingAgentState.PAUSED)

        # Create a new branch
        if not self._branch_mgr:
            return None

        active_id = self._branch_mgr.active_branch_id
        try:
            branch = self._branch_mgr.create_branch(
                active_id, step_index,
                instructions=instructions,
                edited_actions=edited_actions,
            )
        except Exception as e:
            logger.error(f"Failed to create branch: {e}")
            return None

        # Rollback files to the branch point
        if self._checkpoint_mgr:
            self._checkpoint_mgr.rollback_to(step_index)

        # Truncate structured turns and backend history
        self._structured_turns = list(branch.turns)
        if self._backend:
            self._backend.truncate_history(step_index + 1)

        # Execute edited actions if provided
        if edited_actions:
            from .coding_agent_backend import execute_tool
            working_dir = self._sandbox.working_dir if self._sandbox else self.config.working_dir
            for action in edited_actions:
                tool_name = action.get("tool", "")
                tool_input = action.get("input", {})
                output = execute_tool(tool_name, tool_input, working_dir)
                action["output"] = output

        # Inject instructions if provided
        if instructions and self._backend:
            self._backend.inject_instruction(instructions)

        # Resume the agent
        if self._backend:
            self._backend.resume()
        self._set_state(CodingAgentState.RUNNING)

        self._emit_event("branch_created", {
            "branch_id": branch.branch_id,
            "parent_branch": active_id,
            "branch_point": step_index,
            "instructions": instructions,
        })

        return branch.branch_id

    def get_branches(self) -> List[dict]:
        """List all branches."""
        if self._branch_mgr:
            return self._branch_mgr.list_branches()
        return []

    def switch_branch(self, branch_id: str) -> bool:
        """Switch to a different branch."""
        if not self._branch_mgr:
            return False
        if self._branch_mgr.switch_branch(branch_id):
            branch = self._branch_mgr.get_branch(branch_id)
            if branch:
                self._structured_turns = list(branch.turns)
            return True
        return False

    def get_diff_since_step(self, step_index: int) -> str:
        """Get diff from a step to current state."""
        if self._checkpoint_mgr:
            return self._checkpoint_mgr.get_diff_since(step_index)
        return ""

    # --- Trace export ---

    def get_trace(self) -> Dict[str, Any]:
        """Get the full trace in CodingTraceDisplay format."""
        trace = {
            "session_id": self.session_id,
            "task_description": self._task_description,
            "structured_turns": list(self._structured_turns),
            "backend": self.config.backend_type,
            "model": self.config.ai_config.get("model", ""),
            "started_at": self._started_at,
            "sandbox_mode": self.config.sandbox_mode,
        }
        # Include branches if any were created
        if self._branch_mgr and len(self._branch_mgr.list_branches()) > 1:
            trace["branches"] = self._branch_mgr.save_all()
        # Include checkpoints
        if self._checkpoint_mgr:
            trace["checkpoints"] = self._checkpoint_mgr.list_checkpoints()
        return trace

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
