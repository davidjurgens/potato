"""
Trace Ingestion API Routes

Provides endpoints for receiving agent traces from external platforms:
- POST /api/traces/webhook       - Generic webhook receiver
- POST /api/traces/langsmith     - LangSmith-specific webhook
- GET  /api/traces/stream        - SSE stream for new trace notifications
- GET  /api/traces/status        - Ingestion status and stats
"""

import json
import logging
import os
import time
from functools import wraps

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    request,
    session as flask_session,
    redirect,
    url_for,
)

from potato.trace_ingestion.webhook_receiver import WebhookReceiver
from potato.trace_ingestion.sse_notifier import SSENotifier

logger = logging.getLogger(__name__)

trace_ingestion_bp = Blueprint("trace_ingestion", __name__)

# Module-level state
_sse_notifier = SSENotifier()
_stats = {"received": 0, "processed": 0, "errors": 0, "last_received": None}


def _login_required(f):
    """Require user authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in flask_session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def _get_webhook_receiver():
    """Create a webhook receiver from the current app config.

    Always reads from current_app.config so that each Flask app instance
    uses its own trace_ingestion settings (important when multiple test
    servers run in the same process).
    """
    ingestion_config = current_app.config.get("trace_ingestion", {})
    api_key = ingestion_config.get("api_key", "")
    return WebhookReceiver(api_key=api_key)


def _inject_trace(trace: dict):
    """Inject a normalized trace as a new annotation item."""
    try:
        from potato.item_state_management import get_item_state_manager

        ism = get_item_state_manager()

        # Save trace data to disk
        task_dir = current_app.config.get("task_dir", ".")
        traces_dir = os.path.join(task_dir, "ingested_traces")
        os.makedirs(traces_dir, exist_ok=True)

        trace_id = trace.get("id", f"trace_{int(time.time())}")
        trace_path = os.path.join(traces_dir, f"{trace_id}.json")
        with open(trace_path, "w", encoding="utf-8") as f:
            json.dump(trace, f, indent=2)

        # Add as item to the annotation queue
        item_data = {
            "id": trace_id,
            "text": trace.get("task_description", "Ingested trace"),
            **trace,
        }
        ism.add_item(trace_id, item_data)

        _stats["processed"] += 1

        # Notify connected annotators
        ingestion_config = current_app.config.get("trace_ingestion", {})
        if ingestion_config.get("notify_annotators", True):
            _sse_notifier.notify_new_trace(
                trace_id=trace_id,
                task_description=trace.get("task_description", ""),
                source=trace.get("metadata", {}).get("source", "webhook"),
            )

        logger.info(f"Injected trace: {trace_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to inject trace: {e}")
        _stats["errors"] += 1
        return False


@trace_ingestion_bp.route("/api/traces/webhook", methods=["POST"])
def webhook_endpoint():
    """
    Generic webhook endpoint for receiving agent traces.

    Authentication: Bearer token or X-API-Key header.
    """
    receiver = _get_webhook_receiver()

    # Validate authentication
    if not receiver.validate_auth(dict(request.headers)):
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "Invalid JSON payload"}), 400

    _stats["received"] += 1
    _stats["last_received"] = time.time()

    format_hint = request.args.get("format", "auto")
    trace = receiver.process_webhook(payload, format_hint)

    if trace is None:
        _stats["errors"] += 1
        return jsonify({"error": "Failed to process payload"}), 422

    success = _inject_trace(trace)
    if not success:
        return jsonify({"error": "Failed to inject trace"}), 500

    return jsonify({
        "status": "accepted",
        "trace_id": trace.get("id"),
        "steps": len(trace.get("steps", [])),
    })


@trace_ingestion_bp.route("/api/traces/langsmith", methods=["POST"])
def langsmith_webhook():
    """LangSmith-specific webhook endpoint."""
    receiver = _get_webhook_receiver()

    if not receiver.validate_auth(dict(request.headers)):
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "Invalid JSON payload"}), 400

    _stats["received"] += 1
    _stats["last_received"] = time.time()

    trace = receiver.process_webhook(payload, format_hint="langsmith")
    if trace is None:
        _stats["errors"] += 1
        return jsonify({"error": "Failed to process LangSmith payload"}), 422

    success = _inject_trace(trace)
    if not success:
        return jsonify({"error": "Failed to inject trace"}), 500

    return jsonify({
        "status": "accepted",
        "trace_id": trace.get("id"),
        "steps": len(trace.get("steps", [])),
    })


@trace_ingestion_bp.route("/api/traces/stream")
@_login_required
def trace_stream():
    """SSE stream for real-time trace ingestion notifications."""
    client_queue = _sse_notifier.add_client()

    return Response(
        _sse_notifier.generate_sse_stream(client_queue),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@trace_ingestion_bp.route("/api/traces/status")
@_login_required
def ingestion_status():
    """Get trace ingestion status and statistics."""
    return jsonify({
        "enabled": True,
        "stats": _stats,
        "sse_clients": _sse_notifier.client_count,
    })
