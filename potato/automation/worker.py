"""
Background worker for heavy automation actions.

Heavy actions (``run_evaluator``, ``fire_webhook``) are dispatched here so they
never block the ingestion path. A single daemon thread drains a queue; outcomes
are written to the OutcomeStore. ``stop()`` is registered via atexit by the
manager.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger("potato.automation")

# Sentinel to unblock the worker on shutdown.
_STOP = object()


class AutomationWorker:
    def __init__(self, on_outcome: Callable[[str, str, Dict[str, Any]], None]):
        self._queue: "queue.Queue[Any]" = queue.Queue()
        self._on_outcome = on_outcome
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="automation-worker", daemon=True)
        self._thread.start()

    def enqueue(self, action: Dict[str, Any], ctx: Dict[str, Any]) -> None:
        self._queue.put((action, ctx))

    def _run(self) -> None:
        from potato.automation.actions import execute_action
        while self._running:
            try:
                task = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if task is _STOP:
                break
            action, ctx = task
            try:
                outcome = execute_action(action, ctx)
                self._on_outcome(ctx.get("item_id"), ctx.get("rule"), outcome)
            except Exception as e:  # never let the worker die
                logger.error("Automation worker task failed: %s", e)
            finally:
                self._queue.task_done()

    def stop(self, timeout: float = 5.0) -> None:
        if not self._running:
            return
        self._running = False
        self._queue.put(_STOP)
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def join_pending(self, timeout: Optional[float] = None) -> None:
        """Block until the queue is drained (used by tests)."""
        self._queue.join()
