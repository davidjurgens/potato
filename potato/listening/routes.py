"""
``GET /api/listening/plan?schema=<name>&instance_id=<id>``
    The page's view of the trial: method, slot names, audio URLs, scale.
``GET /api/listening/audio/<schema>/<instance_id>/<slot>``
    One stimulus (``ref`` is the open reference). Local media are sent from
    the media directory; a remote URL is redirected to, which puts that URL in
    the browser's network log (documented: blind tests should use local files).

Both need a signed-in participant. Neither names a condition; see
:mod:`potato.listening.blind` for the other channels that would.
"""

from __future__ import annotations

import logging
import os
import wave

logger = logging.getLogger(__name__)

_config: dict = {}


def _scheme(name: str):
    for scheme in _config.get("annotation_schemes") or []:
        if scheme.get("name") == name and scheme.get("annotation_type") == "listening_test":
            return scheme
    return None


def _context(schema: str, instance_id: str):
    from flask import abort, session
    from potato.item_state_management import get_item_state_manager
    from potato.listening.plan import build_plan
    username = session.get("username")
    if not username:
        abort(401)
    scheme = _scheme(schema)
    if scheme is None:
        abort(404)
    try:
        item = get_item_state_manager().get_item(instance_id)
    except Exception:
        item = None
    if item is None:
        abort(404)
    data = item.get_data() if hasattr(item, "get_data") else dict(item)
    return scheme, build_plan(scheme, data, username, instance_id)


def listening_plan():
    from flask import jsonify, request, url_for
    from potato.listening.plan import client_view
    schema = request.args.get("schema", "")
    instance_id = request.args.get("instance_id", "")
    scheme, plan = _context(schema, instance_id)

    def audio_url(slot):
        return url_for("listening_audio", schema=schema, instance_id=instance_id, slot=slot)
    response = jsonify(client_view(plan, scheme, audio_url))
    response.headers["Cache-Control"] = "no-store"
    return response


def listening_audio(schema: str, instance_id: str, slot: str):
    from flask import abort, redirect, send_file
    from potato.listening.plan import slot_source
    from potato.media.paths import resolve_media_url
    scheme, plan = _context(schema, instance_id)
    source = slot_source(plan, slot)
    if not source:
        abort(404)
    if isinstance(source, dict):
        ref_path = resolve_media_url(_config, source["of"], context="Listening test")
        if ref_path is None:
            abort(404)
        try:
            from potato.listening.anchors import anchor_path
            path = anchor_path(_config.get("task_dir") or ".", ref_path, int(source["anchor_hz"]))
        except (ValueError, OSError, wave.Error) as e:
            logger.error("Could not make the %s Hz anchor from %s: %s",
                         source["anchor_hz"], source["of"], e)
            abort(500)
    elif source.startswith(("http://", "https://")):
        return redirect(source, code=302)
    else:
        path = resolve_media_url(_config, source, context="Listening test")
        if path is None:
            # Not under media/: a path relative to the task directory.
            from potato.server_utils.config_module import ConfigSecurityError, validate_path_security
            task_dir = _config.get("task_dir") or "."
            try:
                path = validate_path_security(os.path.join(task_dir, source.lstrip("/")), task_dir)
            except ConfigSecurityError:
                abort(404)
            if not os.path.isfile(path):
                abort(404)
    import mimetypes
    from flask import Response
    from potato.listening.blind import padded_audio
    # No ETag, Last-Modified or file name, and padded bytes: any of them would
    # let a participant tell which slots hold the same file.
    response = Response(padded_audio(path),
                        mimetype=mimetypes.guess_type(path)[0] or "application/octet-stream")
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def register_listening_routes(app, config) -> None:
    global _config
    _config = config
    if "listening_plan" in app.view_functions:
        return
    app.add_url_rule("/api/listening/plan", "listening_plan", listening_plan)
    app.add_url_rule("/api/listening/audio/<schema>/<path:instance_id>/<slot>",
                     "listening_audio", listening_audio)
