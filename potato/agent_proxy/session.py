"""
Agent Session Manager

Thread-safe singleton that tracks active agent interaction sessions.
Each session maps a (user_id, instance_id) pair to an AgentSession
containing the proxy, conversation history, and step count.

Follows the same singleton pattern as ItemStateManager and UserStateManager.
"""

import threading
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .base import AgentMessage, BaseAgentProxy

logger = logging.getLogger(__name__)


@dataclass
class AgentSession:
    """An active agent interaction session."""
    user_id: str
    instance_id: str
    proxy: BaseAgentProxy
    task_description: str
    proxy_context: dict = field(default_factory=dict)
    messages: List[AgentMessage] = field(default_factory=list)
    step_count: int = 0
    started_at: float = field(default_factory=time.time)
    finished: bool = False


class AgentSessionManager:
    """Thread-safe manager for active agent sessions."""

    def __init__(self, config: dict):
        self.config = config
        self._sessions: Dict[Tuple[str, str], AgentSession] = {}
        self._lock = threading.RLock()

    def create_session(
        self,
        user_id: str,
        instance_id: str,
        proxy: BaseAgentProxy,
        task_description: str,
    ) -> AgentSession:
        """Create a new session for a user/instance pair."""
        with self._lock:
            key = (user_id, instance_id)
            if key in self._sessions and not self._sessions[key].finished:
                logger.warning(
                    f"Session already exists for {key}, returning existing"
                )
                return self._sessions[key]

            proxy_context = proxy.start_session(task_description)
            session = AgentSession(
                user_id=user_id,
                instance_id=instance_id,
                proxy=proxy,
                task_description=task_description,
                proxy_context=proxy_context,
            )
            self._sessions[key] = session
            logger.debug(f"Created agent session for {key}")
            return session

    def get_session(
        self, user_id: str, instance_id: str
    ) -> Optional[AgentSession]:
        """Get an active session, or None if not found."""
        with self._lock:
            return self._sessions.get((user_id, instance_id))

    def remove_session(self, user_id: str, instance_id: str):
        """Remove a session and clean up proxy resources."""
        with self._lock:
            key = (user_id, instance_id)
            session = self._sessions.pop(key, None)
            if session:
                try:
                    session.proxy.end_session(session.proxy_context)
                except Exception as e:
                    logger.warning(f"Error ending proxy session for {key}: {e}")
                logger.debug(f"Removed agent session for {key}")


# Singleton management
_AGENT_SESSION_MANAGER: Optional[AgentSessionManager] = None
_AGENT_SESSION_MANAGER_LOCK = threading.Lock()


def init_agent_session_manager(config: dict) -> AgentSessionManager:
    """Initialize the singleton AgentSessionManager."""
    global _AGENT_SESSION_MANAGER
    if _AGENT_SESSION_MANAGER is None:
        with _AGENT_SESSION_MANAGER_LOCK:
            if _AGENT_SESSION_MANAGER is None:
                _AGENT_SESSION_MANAGER = AgentSessionManager(config)
    return _AGENT_SESSION_MANAGER


def get_agent_session_manager() -> AgentSessionManager:
    """Get the singleton AgentSessionManager."""
    global _AGENT_SESSION_MANAGER
    if _AGENT_SESSION_MANAGER is None:
        raise ValueError("AgentSessionManager has not been initialized yet!")
    return _AGENT_SESSION_MANAGER


def clear_agent_session_manager():
    """Clear the singleton instance (for testing)."""
    global _AGENT_SESSION_MANAGER
    with _AGENT_SESSION_MANAGER_LOCK:
        _AGENT_SESSION_MANAGER = None
