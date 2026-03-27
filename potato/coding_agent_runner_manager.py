"""
Coding Agent Runner Manager

Singleton manager for CodingAgentRunner sessions.
Mirrors AgentRunnerManager pattern.
"""

import logging
import threading
import time
import uuid
from typing import Dict, List, Optional

from .coding_agent_runner import CodingAgentRunner, CodingAgentConfig, CodingAgentState

logger = logging.getLogger(__name__)


class CodingAgentRunnerManager:
    """Singleton manager for coding agent sessions."""

    _instance = None
    _lock = threading.Lock()

    def __init__(self, max_sessions: int = 10, session_ttl: int = 3600):
        self._sessions: Dict[str, CodingAgentRunner] = {}
        self._session_keys: Dict[str, str] = {}  # user:instance -> session_id
        self._max_sessions = max_sessions
        self._session_ttl = session_ttl
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    @classmethod
    def get_instance(cls, **kwargs) -> "CodingAgentRunnerManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(**kwargs)
        return cls._instance

    @classmethod
    def clear_instance(cls):
        with cls._lock:
            if cls._instance:
                for runner in cls._instance._sessions.values():
                    runner.cleanup()
                cls._instance = None

    def create_session(self, user_id: str, instance_id: str,
                       config: CodingAgentConfig, trace_dir: str = "") -> CodingAgentRunner:
        """Create a new coding agent session."""
        key = f"{user_id}:{instance_id}"

        # Check for existing active session
        if key in self._session_keys:
            existing = self._sessions.get(self._session_keys[key])
            if existing and existing.state in (CodingAgentState.RUNNING, CodingAgentState.PAUSED):
                return existing

        if len(self._sessions) >= self._max_sessions:
            self._evict_oldest()

        session_id = str(uuid.uuid4())
        runner = CodingAgentRunner(session_id, config, trace_dir)

        self._sessions[session_id] = runner
        self._session_keys[key] = session_id

        logger.info(f"Created coding agent session {session_id} for {key}")
        return runner

    def get_session(self, session_id: str) -> Optional[CodingAgentRunner]:
        return self._sessions.get(session_id)

    def get_session_by_key(self, user_id: str, instance_id: str) -> Optional[CodingAgentRunner]:
        key = f"{user_id}:{instance_id}"
        sid = self._session_keys.get(key)
        if sid:
            return self._sessions.get(sid)
        return None

    def remove_session(self, session_id: str) -> None:
        runner = self._sessions.pop(session_id, None)
        if runner:
            runner.cleanup()
            # Remove from keys
            self._session_keys = {
                k: v for k, v in self._session_keys.items() if v != session_id
            }

    def list_sessions(self) -> List[Dict]:
        return [r.get_state_summary() for r in self._sessions.values()]

    def _evict_oldest(self):
        """Remove the oldest completed/error session."""
        for sid, runner in sorted(self._sessions.items()):
            if runner.state in (CodingAgentState.COMPLETED, CodingAgentState.ERROR):
                self.remove_session(sid)
                return

    def _cleanup_loop(self):
        """Background cleanup of expired sessions."""
        while True:
            time.sleep(60)
            expired = []
            for sid, runner in list(self._sessions.items()):
                if runner.state in (CodingAgentState.COMPLETED, CodingAgentState.ERROR):
                    if time.time() - runner._started_at > self._session_ttl:
                        expired.append(sid)
            for sid in expired:
                self.remove_session(sid)
                logger.debug(f"Cleaned up expired session {sid}")
