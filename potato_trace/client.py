"""
Trace submission client.

POSTs a run tree to Potato's trace-ingestion webhook in a background thread (so
tracing never blocks the agent). ``flush()`` waits for pending sends — call it
before a short-lived script exits. Configuration comes from explicit args or the
``POTATO_TRACE_URL`` / ``POTATO_TRACE_API_KEY`` environment variables.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import List, Optional

from potato_trace.run_tree import Run, build_payload

logger = logging.getLogger("potato_trace")

DEFAULT_ENDPOINT = "/api/traces/webhook"


class PotatoTraceClient:
    def __init__(
        self,
        potato_url: Optional[str] = None,
        api_key: Optional[str] = None,
        endpoint: str = DEFAULT_ENDPOINT,
        project_name: str = "",
        send_timeout: float = 10.0,
        enabled: Optional[bool] = None,
    ):
        self.potato_url = (potato_url or os.environ.get("POTATO_TRACE_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("POTATO_TRACE_API_KEY", "")
        self.endpoint = endpoint
        self.project_name = project_name
        self.send_timeout = send_timeout
        # Auto-disable (no-op) when no URL is configured, so traced code runs
        # safely with tracing simply off.
        self.enabled = enabled if enabled is not None else bool(self.potato_url)
        self._pending: List[threading.Thread] = []
        self._lock = threading.Lock()

    def submit(self, runs: List[Run], root_id: Optional[str], project_name: str = "") -> None:
        if not self.enabled or not runs:
            return
        payload = build_payload(runs, root_id, project_name or self.project_name)

        def _do_send():
            try:
                import requests  # imported lazily so import-time stays light
                url = f"{self.potato_url}{self.endpoint}"
                headers = {"Content-Type": "application/json"}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                resp = requests.post(url, json=payload, headers=headers, timeout=self.send_timeout)
                if resp.status_code >= 300:
                    logger.warning("Potato trace webhook returned %s: %s",
                                   resp.status_code, resp.text[:200])
            except Exception as e:  # never let tracing crash the agent
                logger.error("Failed to send trace to Potato: %s", e)

        t = threading.Thread(target=_do_send, daemon=True)
        with self._lock:
            self._pending = [p for p in self._pending if p.is_alive()]
            self._pending.append(t)
        t.start()

    def flush(self, timeout: float = 30.0) -> None:
        """Block until pending sends complete (or timeout)."""
        with self._lock:
            pending = list(self._pending)
        for t in pending:
            t.join(timeout=timeout)
