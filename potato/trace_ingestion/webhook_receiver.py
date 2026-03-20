"""
Webhook Receiver for Trace Ingestion

Accepts agent traces via HTTP webhooks from external platforms.
Supports generic JSON format and LangSmith-specific format.
Validates webhook authentication via API key.
"""

import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class WebhookReceiver:
    """Receives and normalizes agent traces from webhook POST requests."""

    def __init__(self, api_key: str = "", allowed_formats: Optional[List[str]] = None):
        self.api_key = api_key
        self.allowed_formats = allowed_formats or ["auto", "generic", "langsmith"]

    def validate_auth(self, request_headers: Dict[str, str]) -> bool:
        """Validate webhook authentication."""
        if not self.api_key:
            return True  # No auth required

        # Check Authorization header
        auth = request_headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return hmac.compare_digest(auth[7:], self.api_key)

        # Check X-API-Key header
        api_key = request_headers.get("X-API-Key", "")
        if api_key:
            return hmac.compare_digest(api_key, self.api_key)

        return False

    def process_webhook(
        self, payload: Dict[str, Any], format_hint: str = "auto"
    ) -> Optional[Dict[str, Any]]:
        """
        Process a webhook payload and normalize to Potato trace format.

        Args:
            payload: Raw webhook JSON payload
            format_hint: "auto", "generic", or "langsmith"

        Returns:
            Normalized trace dict or None on failure
        """
        if format_hint == "auto":
            format_hint = self._detect_format(payload)

        try:
            if format_hint == "langsmith":
                return self._normalize_langsmith(payload)
            else:
                return self._normalize_generic(payload)
        except Exception as e:
            logger.error(f"Failed to process webhook: {e}")
            return None

    def _detect_format(self, payload: Dict[str, Any]) -> str:
        """Auto-detect the payload format."""
        # LangSmith uses "runs" key and has run_type field
        if "runs" in payload or "run_type" in payload:
            return "langsmith"
        return "generic"

    def _normalize_generic(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a generic webhook payload."""
        trace_id = payload.get("id", str(uuid.uuid4())[:8])
        steps = payload.get("steps", [])

        # Normalize each step
        normalized_steps = []
        for i, step in enumerate(steps):
            normalized_steps.append({
                "step_index": step.get("step_index", i),
                "action_type": step.get("action_type", step.get("type", "unknown")),
                "thought": step.get("thought", ""),
                "observation": step.get("observation", step.get("output", "")),
                "screenshot_url": step.get("screenshot_url", ""),
                "timestamp": step.get("timestamp", i),
                "coordinates": step.get("coordinates"),
                "element": step.get("element"),
                "viewport": step.get("viewport"),
            })

        return {
            "id": f"webhook_{trace_id}",
            "task_description": payload.get(
                "task_description",
                payload.get("task", payload.get("description", "")),
            ),
            "site": payload.get("site", payload.get("url", "")),
            "steps": normalized_steps,
            "metadata": {
                "source": "webhook",
                "format": "generic",
                "received_at": time.time(),
                "original_id": trace_id,
            },
        }

    def _normalize_langsmith(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a LangSmith webhook payload."""
        runs = payload.get("runs", [payload] if "run_type" in payload else [])
        if not runs:
            return self._normalize_generic(payload)

        # Extract from the root/parent run
        root_run = runs[0]
        trace_id = root_run.get("id", str(uuid.uuid4())[:8])

        # Convert LangSmith runs to steps
        steps = []
        for i, run in enumerate(runs):
            run_type = run.get("run_type", "chain")
            inputs = run.get("inputs", {})
            outputs = run.get("outputs", {})

            steps.append({
                "step_index": i,
                "action_type": self._langsmith_type_to_action(run_type),
                "thought": inputs.get("input", inputs.get("prompt", "")),
                "observation": str(outputs.get("output", outputs.get("text", ""))),
                "screenshot_url": "",
                "timestamp": i,
                "metadata": {
                    "run_id": run.get("id"),
                    "run_type": run_type,
                    "latency": run.get("latency"),
                    "status": run.get("status"),
                },
            })

        return {
            "id": f"langsmith_{trace_id}",
            "task_description": root_run.get("name", ""),
            "site": "",
            "steps": steps,
            "metadata": {
                "source": "langsmith",
                "format": "langsmith",
                "received_at": time.time(),
                "original_id": trace_id,
                "project_name": root_run.get("project_name", ""),
            },
        }

    @staticmethod
    def _langsmith_type_to_action(run_type: str) -> str:
        """Map LangSmith run types to action types."""
        mapping = {
            "tool": "click",
            "llm": "type",
            "chain": "navigate",
            "retriever": "scroll",
        }
        return mapping.get(run_type, "wait")
