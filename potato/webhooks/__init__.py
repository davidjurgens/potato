"""
Outgoing Webhook System

Non-blocking webhook delivery for annotation events. Uses a daemon thread
with a queue to ensure webhook calls never block annotation requests.

Usage:
    from potato.webhooks import init_webhook_emitter, get_webhook_emitter

    # Initialize (call once at startup)
    init_webhook_emitter(config)

    # Emit events
    emitter = get_webhook_emitter()
    if emitter:
        emitter.emit("annotation.created", payload)

    # Cleanup
    emitter.stop()
"""

import threading
import logging

logger = logging.getLogger(__name__)

_EMITTER = None
_LOCK = threading.Lock()


def init_webhook_emitter(config: dict):
    """Initialize the global webhook emitter from config.

    Args:
        config: Full Potato YAML config dict. Reads 'webhooks' section.

    Returns:
        WebhookEmitter or None if webhooks not enabled.
    """
    global _EMITTER
    with _LOCK:
        if _EMITTER is not None:
            return _EMITTER

        webhook_config = config.get("webhooks", {})
        if not webhook_config.get("enabled", False):
            logger.debug("Webhooks not enabled in config")
            return None

        from .emitter import WebhookEmitter
        _EMITTER = WebhookEmitter(webhook_config, config)
        logger.info("Webhook emitter initialized with %d endpoint(s)",
                     len(_EMITTER.endpoints))
        return _EMITTER


def get_webhook_emitter():
    """Get the global webhook emitter, or None if not initialized."""
    return _EMITTER


def clear_webhook_emitter():
    """Clear the global emitter (for testing)."""
    global _EMITTER
    with _LOCK:
        if _EMITTER is not None:
            _EMITTER.stop()
        _EMITTER = None
