"""
Langfuse Trace Poller

Background thread that polls the Langfuse API for new traces
and injects them as annotation items.
"""

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class LangfusePoller:
    """
    Polls Langfuse API for new traces and converts them to annotation items.

    Runs in a background daemon thread. Calls the on_trace callback
    with each new trace found.
    """

    def __init__(
        self,
        api_url: str,
        public_key: str,
        secret_key: str,
        poll_interval: float = 30.0,
        on_trace: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.api_url = api_url.rstrip("/")
        self.public_key = public_key
        self.secret_key = secret_key
        self.poll_interval = poll_interval
        self.on_trace = on_trace
        self._seen_ids = set()
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        """Start the polling thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Langfuse poller already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="langfuse-poller"
        )
        self._thread.start()
        logger.info(
            f"Langfuse poller started (interval={self.poll_interval}s, url={self.api_url})"
        )

    def stop(self):
        """Stop the polling thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self.poll_interval + 5)
        logger.info("Langfuse poller stopped")

    def _poll_loop(self):
        """Main polling loop."""
        while not self._stop_event.is_set():
            try:
                traces = self._fetch_traces()
                for trace in traces:
                    trace_id = trace.get("id", "")
                    if trace_id and trace_id not in self._seen_ids:
                        self._seen_ids.add(trace_id)
                        normalized = self._normalize_trace(trace)
                        if normalized and self.on_trace:
                            self.on_trace(normalized)
                            logger.info(f"Ingested Langfuse trace: {trace_id}")
            except Exception as e:
                logger.error(f"Langfuse poll error: {e}")

            self._stop_event.wait(self.poll_interval)

    def _fetch_traces(self) -> List[Dict[str, Any]]:
        """Fetch recent traces from Langfuse API."""
        try:
            import requests
        except ImportError:
            logger.error("requests package required for Langfuse polling")
            return []

        url = f"{self.api_url}/api/public/traces"
        params = {
            "limit": 50,
            "orderBy": "timestamp",
            "orderDirection": "desc",
        }

        try:
            response = requests.get(
                url,
                params=params,
                auth=(self.public_key, self.secret_key),
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except Exception as e:
            logger.error(f"Failed to fetch Langfuse traces: {e}")
            return []

    def _normalize_trace(self, trace: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert a Langfuse trace to Potato annotation format."""
        trace_id = trace.get("id", "")
        name = trace.get("name", "")
        observations = trace.get("observations", [])

        steps = []
        for i, obs in enumerate(observations):
            obs_type = obs.get("type", "SPAN")
            steps.append({
                "step_index": i,
                "action_type": self._obs_type_to_action(obs_type),
                "thought": obs.get("input", ""),
                "observation": str(obs.get("output", "")),
                "screenshot_url": "",
                "timestamp": i,
                "metadata": {
                    "observation_id": obs.get("id"),
                    "observation_type": obs_type,
                    "model": obs.get("model"),
                    "latency_ms": obs.get("completionStartTime"),
                },
            })

        return {
            "id": f"langfuse_{trace_id}",
            "task_description": name or trace.get("metadata", {}).get("task", ""),
            "site": "",
            "steps": steps,
            "metadata": {
                "source": "langfuse",
                "format": "langfuse",
                "received_at": time.time(),
                "original_id": trace_id,
                "session_id": trace.get("sessionId"),
                "user_id": trace.get("userId"),
                "tags": trace.get("tags", []),
            },
        }

    @staticmethod
    def _obs_type_to_action(obs_type: str) -> str:
        """Map Langfuse observation types to action types."""
        mapping = {
            "GENERATION": "type",
            "SPAN": "navigate",
            "EVENT": "click",
        }
        return mapping.get(obs_type, "wait")
