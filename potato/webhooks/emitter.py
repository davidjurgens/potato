"""
Webhook Emitter

Singleton that reads endpoint configs, fan-outs events to matching endpoints,
and delegates delivery to WebhookDeliveryQueue.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .sender import WebhookDeliveryQueue

logger = logging.getLogger(__name__)


@dataclass
class WebhookEndpoint:
    """Configuration for a single webhook endpoint."""
    name: str
    url: str
    secret: str = ""
    events: List[str] = field(default_factory=list)
    active: bool = True
    timeout_seconds: int = 10


class WebhookEmitter:
    """Manages webhook endpoint configs and event fan-out.

    Reads the 'webhooks' section of the Potato config and dispatches
    matching events to registered endpoints via a background delivery queue.
    """

    def __init__(self, webhook_config: dict, full_config: dict = None):
        """Initialize from the webhooks config section.

        Args:
            webhook_config: The 'webhooks' section of the YAML config.
            full_config: Full Potato config (for output_dir resolution).
        """
        self.endpoints: List[WebhookEndpoint] = []
        self._delivery_queue = None
        self._stats = {"total_emitted": 0, "total_dropped": 0}

        # Parse endpoint configs
        for ep_dict in webhook_config.get("endpoints", []):
            ep = WebhookEndpoint(
                name=ep_dict.get("name", "unnamed"),
                url=ep_dict.get("url", ""),
                secret=ep_dict.get("secret", ""),
                events=ep_dict.get("events", []),
                active=ep_dict.get("active", True),
                timeout_seconds=ep_dict.get("timeout_seconds", 10),
            )
            if ep.url:
                self.endpoints.append(ep)
            else:
                logger.warning("Skipping webhook endpoint '%s' with no URL",
                               ep.name)

        # Resolve output dir for retry store
        output_dir = None
        if full_config:
            task_dir = full_config.get("task_dir", ".")
            output_dir_name = full_config.get("output_annotation_dir",
                                               "annotation_output")
            import os
            output_dir = os.path.join(task_dir, output_dir_name, ".webhooks")

        # Start delivery queue
        self._delivery_queue = WebhookDeliveryQueue(output_dir=output_dir)
        self._delivery_queue.start()

    def emit(self, event_type: str, payload: dict) -> int:
        """Emit an event to all matching endpoints.

        Args:
            event_type: Event type string (e.g., "annotation.created").
            payload: Event payload dict (will be JSON-serialized).

        Returns:
            Number of endpoints the event was dispatched to.
        """
        if not self.endpoints:
            return 0

        dispatched = 0
        payload_bytes = json.dumps(payload, ensure_ascii=False,
                                    default=str).encode("utf-8")

        for ep in self.endpoints:
            if not ep.active:
                continue

            # Match events: wildcard "*" matches all
            if "*" not in ep.events and event_type not in ep.events:
                continue

            success = self._delivery_queue.enqueue(
                url=ep.url,
                secret=ep.secret,
                payload_bytes=payload_bytes,
            )

            if success:
                dispatched += 1
                self._stats["total_emitted"] += 1
            else:
                self._stats["total_dropped"] += 1

        return dispatched

    def stop(self):
        """Stop the delivery queue."""
        if self._delivery_queue:
            self._delivery_queue.stop()

    def get_stats(self) -> dict:
        """Get delivery statistics (for admin API)."""
        retry_count = 0
        if self._delivery_queue:
            retry_count = self._delivery_queue.get_retry_count()
        return {
            "endpoints": len(self.endpoints),
            "active_endpoints": sum(1 for ep in self.endpoints if ep.active),
            "total_emitted": self._stats["total_emitted"],
            "total_dropped": self._stats["total_dropped"],
            "pending_retries": retry_count,
        }

    def get_endpoint_info(self) -> List[dict]:
        """Get endpoint info (for admin API, secrets redacted)."""
        return [
            {
                "name": ep.name,
                "url": ep.url,
                "events": ep.events,
                "active": ep.active,
                "timeout_seconds": ep.timeout_seconds,
                "has_secret": bool(ep.secret),
            }
            for ep in self.endpoints
        ]
