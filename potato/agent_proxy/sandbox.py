"""
Agent Proxy Safety Sandbox

Enforces limits on agent interactions: step counts, session timeouts,
rate limits, and request timeouts. Prevents runaway or abusive sessions.
"""

import time
import threading
import logging
from collections import defaultdict
from typing import Dict, List

logger = logging.getLogger(__name__)


class SandboxViolation(Exception):
    """Raised when a safety limit is exceeded."""
    pass


class SafetySandbox:
    """Enforces safety limits on agent interactions."""

    def __init__(self, config: dict):
        sandbox_config = config.get("sandbox", {})
        self.max_steps = sandbox_config.get("max_steps", 20)
        self.max_session_seconds = sandbox_config.get("max_session_seconds", 600)
        self.rate_limit_per_minute = sandbox_config.get("rate_limit_per_minute", 10)
        self.request_timeout = sandbox_config.get("request_timeout_seconds", 60)

        # Sliding window rate limit tracking: user_id -> list of timestamps
        self._rate_windows: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check_step_limit(self, current_steps: int):
        """Raise SandboxViolation if step limit reached."""
        if current_steps >= self.max_steps:
            raise SandboxViolation(
                f"Step limit reached ({self.max_steps}). "
                f"Please finish the conversation."
            )

    def check_session_timeout(self, session_start: float):
        """Raise SandboxViolation if session has timed out."""
        elapsed = time.time() - session_start
        if elapsed > self.max_session_seconds:
            raise SandboxViolation(
                f"Session timeout ({self.max_session_seconds}s). "
                f"Please finish the conversation."
            )

    def check_rate_limit(self, user_id: str):
        """Raise SandboxViolation if user is sending too fast."""
        now = time.time()
        window_start = now - 60.0

        with self._lock:
            # Remove old entries outside the 1-minute window
            timestamps = self._rate_windows[user_id]
            self._rate_windows[user_id] = [
                t for t in timestamps if t > window_start
            ]

            if len(self._rate_windows[user_id]) >= self.rate_limit_per_minute:
                raise SandboxViolation(
                    f"Rate limit exceeded ({self.rate_limit_per_minute}/min). "
                    f"Please wait before sending another message."
                )

            # Record this request
            self._rate_windows[user_id].append(now)

    def get_request_timeout(self) -> float:
        """Get the timeout in seconds for proxy HTTP requests."""
        return self.request_timeout
