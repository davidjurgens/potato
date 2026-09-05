"""
Coding Agent Runner Manager

Singleton manager for CodingAgentRunner sessions.
Mirrors AgentRunnerManager pattern.
"""

import atexit
import logging
import signal
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
        # The cleanup thread is a daemon, so it is killed without running when
        # the process exits -- and a container sandbox outlives the process
        # that started it. Without this, stopping Potato left every live
        # container up, and only the next boot's sweep would find them.
        atexit.register(self._release_all)
        self._install_termination_handler()

    @classmethod
    def get_instance(cls, **kwargs) -> "CodingAgentRunnerManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(**kwargs)
        return cls._instance

    def _install_termination_handler(self) -> None:
        """Make SIGTERM run the atexit hook, so a stopped server frees its containers.

        Python runs atexit handlers on a normal exit and on SIGINT (which
        raises KeyboardInterrupt), but not on a signal it has no handler for --
        and SIGTERM is what `systemctl stop`, `docker stop`, supervisord and a
        plain `kill` all send. So Ctrl-C released every container and every
        other way of stopping the server leaked them all.

        Raising SystemExit is the whole fix: the interpreter unwinds normally
        from there and atexit runs. The previous handler is chained rather than
        replaced, because a process manager or WSGI server may have installed
        its own and this must not be the thing that stops it running.

        Only from the main thread, where signal handlers can be installed at
        all; under a worker model the parent process owns the signal.
        """
        try:
            if threading.current_thread() is not threading.main_thread():
                # Whoever built the manager first decides whether this works,
                # so say when it did not. Built from a route handler, this
                # returns here every time and the leak is silent.
                logger.warning(
                    "Coding agent manager first built on %s, not the main "
                    "thread, so no SIGTERM handler was installed: a stopped "
                    "server will leak its sandbox containers. Build it at "
                    "boot instead.", threading.current_thread().name)
                return
            previous = signal.getsignal(signal.SIGTERM)

            def _terminate(signum, frame):
                logger.info("SIGTERM received; releasing coding agent sandboxes")
                try:
                    self._release_all()
                finally:
                    if callable(previous) and previous not in (
                            signal.SIG_DFL, signal.SIG_IGN):
                        previous(signum, frame)
                raise SystemExit(128 + signum)

            signal.signal(signal.SIGTERM, _terminate)
        except (ValueError, OSError, AttributeError) as e:
            # No SIGTERM on this platform, or not the main thread after all.
            logger.debug("Could not install a SIGTERM handler: %s", e)

    def _release_all(self) -> None:
        """Tear down every live sandbox. Registered with atexit."""
        for runner in list(self._sessions.values()):
            try:
                runner.cleanup()
            except Exception as e:  # noqa: BLE001 - shutdown must not raise
                logger.warning("Could not clean up session at exit: %s", e)

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
                    # Age from when it FINISHED. Measured from `_started_at`, a
                    # session that ran for most of the TTL was reaped moments
                    # after completing, and one that finished immediately held
                    # its container for the whole hour.
                    since = getattr(runner, "_finished_at", 0.0) or runner._started_at
                    if time.time() - since > self._session_ttl:
                        expired.append(sid)
            for sid in expired:
                self.remove_session(sid)
                logger.debug(f"Cleaned up expired session {sid}")
