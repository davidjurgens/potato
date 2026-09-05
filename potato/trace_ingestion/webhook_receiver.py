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

    def __init__(
        self,
        api_key: str = "",
        allowed_formats: Optional[List[str]] = None,
        allow_unauthenticated: bool = False,
    ):
        self.api_key = api_key
        self.allowed_formats = allowed_formats or ["auto", "generic", "langsmith"]
        self.allow_unauthenticated = allow_unauthenticated

    def validate_auth(self, request_headers: Dict[str, str]) -> bool:
        """Validate webhook authentication.

        With no `trace_ingestion.api_key` configured this used to return True,
        so turning trace ingestion on without also setting a key left an open
        endpoint that writes into the annotation task. It now fails closed;
        an admin who genuinely wants an open receiver (a trusted private
        network, say) sets `trace_ingestion.allow_unauthenticated: true`.
        """
        if not self.api_key:
            return self.allow_unauthenticated

        # Case-insensitively, because HTTP header names are. The route hands
        # this `dict(request.headers)`, and Werkzeug title-cases the names on
        # the way out: "X-API-Key" arrives as "X-Api-Key" and a plain dict
        # lookup missed it. "Authorization" title-cases to itself, which is
        # why Bearer worked and the documented X-API-Key returned 401.
        headers = {str(k).lower(): v for k, v in (request_headers or {}).items()}

        auth = headers.get("authorization", "") or ""
        if auth.startswith("Bearer "):
            return hmac.compare_digest(auth[7:], self.api_key)

        api_key = headers.get("x-api-key", "") or ""
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

        normalized = {
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
        # Carry through everything else the sender supplied.
        #
        # This used to be an allowlist of four quality signals, so an ingested
        # trace reached the annotator as an envelope of five keys and every
        # field the task's own `instance_display` reads -- repo, judge_score,
        # reasoning, patch, eval_steps -- was silently dropped between the POST
        # and the page. The server diagnosed it precisely in the log ("ALL 4
        # non-lazy field(s) ... are absent from the instance data") while the
        # annotator was shown a blank item and asked to judge it.
        #
        # An allowlist cannot work here: `instance_display` names arbitrary
        # keys, and the receiver has no way to know which. The envelope's own
        # keys still win, so normalization is unchanged for anything that
        # collides.
        for key, value in payload.items():
            normalized.setdefault(key, value)
        return normalized

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
