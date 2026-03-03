"""
Agent Proxy Base Module

Provides the abstract base class and data structures for agent proxies,
plus a factory registry for creating proxy instances from configuration.

Agent proxies allow annotators to interact with AI agents live during
annotation tasks. Each proxy type (echo, http, openai) handles
communication with a specific kind of agent backend.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
import logging
import time

logger = logging.getLogger(__name__)


@dataclass
class AgentMessage:
    """A single message in an agent conversation."""
    role: str  # "user", "agent", "system", "error"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResponse:
    """Response from an agent proxy after sending a message."""
    message: AgentMessage
    done: bool = False
    error: Optional[str] = None


class BaseAgentProxy(ABC):
    """
    Abstract base class for agent proxies.

    Subclasses implement communication with specific agent backends
    (echo for testing, HTTP for generic REST APIs, OpenAI for chat completions).
    """

    proxy_type: str = ""

    def __init__(self, config: dict):
        self.config = config
        self._initialize()

    @abstractmethod
    def _initialize(self):
        """Set up connections, validate config. Called by __init__."""
        pass

    @abstractmethod
    def start_session(self, task_description: str) -> dict:
        """
        Start a new interaction session.

        Args:
            task_description: The task the annotator should accomplish with the agent.

        Returns:
            Proxy-specific session context dict (stored in AgentSession.proxy_context).
        """
        pass

    @abstractmethod
    def send_message(self, message: str, session_context: dict) -> AgentResponse:
        """
        Send a message to the agent and get a blocking response.

        Args:
            message: The user's message text.
            session_context: The proxy-specific context from start_session.

        Returns:
            AgentResponse with the agent's reply.
        """
        pass

    def end_session(self, session_context: dict):
        """
        Clean up session resources. Override if needed.

        Args:
            session_context: The proxy-specific context from start_session.
        """
        pass


class AgentProxyFactory:
    """Factory registry for creating agent proxy instances."""

    _proxies: Dict[str, type] = {}

    @classmethod
    def register(cls, proxy_type: str, proxy_class: type):
        """Register a proxy type."""
        cls._proxies[proxy_type] = proxy_class
        logger.debug(f"Registered agent proxy type: {proxy_type}")

    @classmethod
    def create(cls, config: dict) -> BaseAgentProxy:
        """
        Create an agent proxy from configuration.

        Args:
            config: The full config dict. Reads from config["agent_proxy"].

        Returns:
            Configured BaseAgentProxy instance.

        Raises:
            ValueError: If proxy type is unknown or missing.
        """
        agent_config = config.get("agent_proxy", {})
        proxy_type = agent_config.get("type")

        if not proxy_type:
            raise ValueError("agent_proxy.type is required")

        if proxy_type not in cls._proxies:
            supported = ", ".join(sorted(cls._proxies.keys()))
            raise ValueError(
                f"Unknown agent proxy type: '{proxy_type}'. "
                f"Supported types: {supported}"
            )

        proxy_class = cls._proxies[proxy_type]
        return proxy_class(agent_config)

    @classmethod
    def get_supported_types(cls) -> List[str]:
        """Get list of registered proxy type names."""
        return sorted(cls._proxies.keys())
