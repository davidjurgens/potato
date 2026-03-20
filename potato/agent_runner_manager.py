"""
Agent Runner Session Manager

Singleton that manages active AgentRunner sessions.
Keyed by "{user_id}:{instance_id}" for per-user, per-instance isolation.
Includes TTL-based cleanup and max concurrent session limits.
"""

import atexit
import logging
import threading
import time
from typing import Dict, Optional

from potato.agent_runner import AgentConfig, AgentRunner, AgentState

logger = logging.getLogger(__name__)

# Default limits
DEFAULT_MAX_SESSIONS = 10
DEFAULT_SESSION_TTL = 3600  # 1 hour


class AgentRunnerManager:
    """
    Manages active AgentRunner sessions with lifecycle control.

    Thread-safe singleton. Sessions are keyed by "{user_id}:{instance_id}".
    """

    _instance = None
    _lock = threading.Lock()

    def __init__(
        self,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        session_ttl: int = DEFAULT_SESSION_TTL,
    ):
        self._sessions: Dict[str, AgentRunner] = {}
        self._session_created: Dict[str, float] = {}
        self._session_meta: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        self.max_sessions = max_sessions
        self.session_ttl = session_ttl

        # Start cleanup thread
        self._cleanup_stop = threading.Event()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True, name="agent-cleanup"
        )
        self._cleanup_thread.start()

    @classmethod
    def get_instance(cls, **kwargs) -> "AgentRunnerManager":
        """Get or create the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(**kwargs)
        return cls._instance

    @classmethod
    def clear_instance(cls):
        """Clear the singleton (for testing)."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.shutdown()
                cls._instance = None

    def create_session(
        self,
        user_id: str,
        instance_id: str,
        config: AgentConfig,
        screenshot_dir: str,
    ) -> AgentRunner:
        """
        Create a new agent session.

        Args:
            user_id: Annotator user ID
            instance_id: Annotation instance ID
            config: Agent configuration
            screenshot_dir: Directory to store screenshots

        Returns:
            AgentRunner instance

        Raises:
            RuntimeError: If max sessions reached or session already exists
        """
        session_key = f"{user_id}:{instance_id}"

        with self._lock:
            # Clean up expired sessions first
            self._cleanup_expired_locked()

            # Check for existing active session
            if session_key in self._sessions:
                existing = self._sessions[session_key]
                if existing.state in (AgentState.RUNNING, AgentState.PAUSED, AgentState.TAKEOVER):
                    raise RuntimeError(
                        f"Active session already exists for {session_key}. "
                        f"Stop it first."
                    )
                # Old completed/error session — remove it
                del self._sessions[session_key]
                del self._session_created[session_key]
                if session_key in self._session_meta:
                    del self._session_meta[session_key]

            # Check capacity
            active_count = sum(
                1
                for s in self._sessions.values()
                if s.state in (AgentState.RUNNING, AgentState.PAUSED, AgentState.TAKEOVER)
            )
            if active_count >= self.max_sessions:
                raise RuntimeError(
                    f"Maximum concurrent sessions ({self.max_sessions}) reached"
                )

            import uuid
            session_id = str(uuid.uuid4())[:12]
            runner = AgentRunner(session_id, config, screenshot_dir)

            self._sessions[session_key] = runner
            self._session_created[session_key] = time.time()
            self._session_meta[session_key] = {
                "user_id": user_id,
                "instance_id": instance_id,
                "session_id": session_id,
            }

            logger.info(
                f"Created agent session {session_id} for {session_key}"
            )
            return runner

    def get_session(self, session_id: str) -> Optional[AgentRunner]:
        """Get a session by its session_id."""
        with self._lock:
            for runner in self._sessions.values():
                if runner.session_id == session_id:
                    return runner
        return None

    def get_session_by_key(self, user_id: str, instance_id: str) -> Optional[AgentRunner]:
        """Get a session by user_id and instance_id."""
        session_key = f"{user_id}:{instance_id}"
        with self._lock:
            return self._sessions.get(session_key)

    def remove_session(self, session_id: str):
        """Remove a session by session_id."""
        with self._lock:
            key_to_remove = None
            for key, runner in self._sessions.items():
                if runner.session_id == session_id:
                    key_to_remove = key
                    break
            if key_to_remove:
                runner = self._sessions.pop(key_to_remove)
                self._session_created.pop(key_to_remove, None)
                self._session_meta.pop(key_to_remove, None)
                runner.stop()
                logger.info(f"Removed agent session {session_id}")

    def list_sessions(self) -> list:
        """List all active sessions."""
        with self._lock:
            result = []
            for key, runner in self._sessions.items():
                meta = self._session_meta.get(key, {})
                result.append({
                    "session_id": runner.session_id,
                    "user_id": meta.get("user_id"),
                    "instance_id": meta.get("instance_id"),
                    "state": runner.state.value,
                    "step_count": runner.step_count,
                    "created": self._session_created.get(key),
                })
            return result

    def _cleanup_expired_locked(self):
        """Remove expired sessions. Must be called with self._lock held."""
        now = time.time()
        expired_keys = []
        for key, created_at in self._session_created.items():
            if now - created_at > self.session_ttl:
                runner = self._sessions.get(key)
                if runner and runner.state in (AgentState.COMPLETED, AgentState.ERROR, AgentState.IDLE):
                    expired_keys.append(key)
                elif runner and now - created_at > self.session_ttl * 2:
                    # Force-stop sessions that have been running too long
                    runner.stop()
                    expired_keys.append(key)

        for key in expired_keys:
            self._sessions.pop(key, None)
            self._session_created.pop(key, None)
            self._session_meta.pop(key, None)
            logger.info(f"Cleaned up expired session: {key}")

    def _cleanup_loop(self):
        """Background cleanup thread."""
        while not self._cleanup_stop.is_set():
            self._cleanup_stop.wait(60)  # Check every 60 seconds
            if self._cleanup_stop.is_set():
                break
            with self._lock:
                self._cleanup_expired_locked()

    def shutdown(self):
        """Stop all sessions and cleanup thread."""
        self._cleanup_stop.set()
        with self._lock:
            for key, runner in self._sessions.items():
                try:
                    runner.stop()
                except Exception as e:
                    logger.warning(f"Error stopping session {key}: {e}")
            self._sessions.clear()
            self._session_created.clear()
            self._session_meta.clear()
        logger.info("AgentRunnerManager shut down")
