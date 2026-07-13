"""Flask blueprint for Think-Aloud Mode.

Annotator endpoints (session auth):
- ``POST /thinkaloud/api/chunk`` — multipart audio chunk (complete blob) →
  transcript + label detection
- ``POST /thinkaloud/api/text``  — text chunk (no-audio path: tests, fallback)
- ``GET  /thinkaloud/api/state`` — session restore for an instance

Admin endpoints (RBAC):
- ``GET /thinkaloud/review``     — transcripts review page
- ``GET /thinkaloud/api/export`` — all sessions as JSON
"""

import logging
from functools import wraps

from flask import Blueprint, jsonify, render_template, request, session

from potato.server_utils.rbac import Permission, require_permission
from potato.thinkaloud.manager import get_thinkaloud_manager
from potato.thinkaloud.stt import STTError

logger = logging.getLogger(__name__)

thinkaloud_bp = Blueprint("thinkaloud", __name__, url_prefix="/thinkaloud")

admin_required = require_permission(Permission.VIEW_ADMIN_DASHBOARD)

MAX_CHUNK_BYTES = 10 * 1024 * 1024  # 10 MB per chunk is generous for <=30s opus


def api_login_required(f):
    """JSON 401 (rather than a login redirect) for JS-called endpoints."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "username" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)

    return decorated_function


def same_origin_required(f):
    """Lightweight CSRF defense for state-changing routes (Origin/Referer check)."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        origin = request.headers.get("Origin")
        referer = request.headers.get("Referer")
        host = request.host_url.rstrip("/")
        if not origin and not referer:
            return f(*args, **kwargs)
        if origin and not origin.startswith(host):
            return jsonify({"error": "Cross-origin request rejected"}), 403
        if referer and not referer.startswith(host):
            return jsonify({"error": "Cross-origin request rejected"}), 403
        return f(*args, **kwargs)

    return decorated_function


def thinkaloud_required(f):
    """404 when Think-Aloud isn't enabled for this task."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if get_thinkaloud_manager() is None:
            return jsonify({"error": "Think-Aloud not enabled"}), 404
        return f(*args, **kwargs)

    return decorated_function


@thinkaloud_bp.route("/api/chunk", methods=["POST"])
@thinkaloud_required
@api_login_required
@same_origin_required
def chunk():
    """Ingest one complete audio blob; returns transcript + detection."""
    manager = get_thinkaloud_manager()
    instance_id = request.form.get("instance_id", "")
    seq = request.form.get("seq", "")
    audio = request.files.get("audio")
    if not instance_id or not seq.isdigit() or audio is None:
        return jsonify({"error": "instance_id, numeric seq, and an audio file "
                                 "are required"}), 400
    audio_bytes = audio.read(MAX_CHUNK_BYTES + 1)
    if len(audio_bytes) > MAX_CHUNK_BYTES:
        return jsonify({"error": "Audio chunk too large"}), 413

    try:
        result = manager.ingest_chunk(
            session["username"], instance_id, int(seq),
            audio_bytes=audio_bytes,
            # mock backend echoes this; real backends ignore it
            mock_text=request.form.get("mock_text"),
        )
    except STTError as e:
        return jsonify({"error": str(e)}), 503
    except Exception:
        logger.exception("Think-Aloud chunk ingestion failed")
        return jsonify({"error": "Transcription failed"}), 500
    return jsonify(result)


@thinkaloud_bp.route("/api/text", methods=["POST"])
@thinkaloud_required
@api_login_required
@same_origin_required
def text_chunk():
    """Text-chunk path: no audio hardware needed (tests, degraded mode)."""
    manager = get_thinkaloud_manager()
    data = request.get_json(silent=True) or {}
    instance_id = str(data.get("instance_id") or "")
    seq = data.get("seq")
    text = data.get("text")
    if not instance_id or not isinstance(seq, int) or not isinstance(text, str):
        return jsonify({"error": "instance_id, integer seq, and text are required"}), 400
    if len(text) > 10000:
        return jsonify({"error": "Text chunk too long"}), 413
    result = manager.ingest_chunk(session["username"], instance_id, seq, text=text)
    return jsonify(result)


@thinkaloud_bp.route("/api/state", methods=["GET"])
@thinkaloud_required
@api_login_required
def state():
    manager = get_thinkaloud_manager()
    instance_id = str(request.args.get("instance_id") or "")
    if not instance_id:
        return jsonify({"error": "instance_id is required"}), 400
    return jsonify(manager.get_session(session["username"], instance_id))


@thinkaloud_bp.route("/review", methods=["GET"])
@thinkaloud_required
@admin_required
def review():
    manager = get_thinkaloud_manager()
    return render_template(
        "thinkaloud_review.html",
        task_name=manager.app_config.get("annotation_task_name", "Annotation Task"),
    )


@thinkaloud_bp.route("/api/export", methods=["GET"])
@thinkaloud_required
@admin_required
def export():
    return jsonify({"sessions": get_thinkaloud_manager().export_sessions()})
