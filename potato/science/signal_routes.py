"""Routes behind the ``time_series`` display and the ``interval_label`` scheme.

``GET /api/signals/window?instance_id=&field=&start=&end=&px=[&channels=a,b]``
    Min/max-decimated samples of ``[start, end)`` for ``px`` pixels (see
    :func:`potato.science.signals.window`), plus each channel's robust
    amplitude range. Cached on the server and, for five minutes, in the
    browser.
``GET /api/signals/preannotations?instance_id=&field=&schema=``
    The pre-annotations an ``interval_label`` scheme starts from.

Both need a signed-in annotator who has been assigned the instance. The
signal file is taken from the item's own field, never from the request, so a
request cannot name a path.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

_config: dict = {}


def _field_config(field: str):
    fields = ((_config.get("instance_display") or {}).get("fields")) or []
    for f in fields:
        if isinstance(f, dict) and f.get("key") == field and f.get("type") == "time_series":
            return f
    return None


def _context():
    """(field options, item data, cache key, recording) or an aborting response."""
    from flask import abort, request, session
    from potato.item_state_management import get_item_state_manager
    from potato.science.signal_store import open_signal
    from potato.science.signals import SignalError
    from potato.server_utils.displays.registry import display_registry
    username = session.get("username")
    if not username:
        abort(401)
    instance_id = request.args.get("instance_id", "")
    field = request.args.get("field", "")
    field_config = _field_config(field)
    if field_config is None:
        abort(404)
    try:
        from potato.user_state_management import get_user_state_manager
        user_state = get_user_state_manager().get_user_state(username)
    except Exception:
        user_state = None
    if user_state is None:
        abort(401)
    assigned = getattr(user_state, "get_assigned_instance_ids", None)
    if callable(assigned):
        try:
            ids = assigned()
        except Exception:
            ids = None
        if ids is not None and str(instance_id) not in {str(i) for i in ids}:
            abort(403)
    try:
        item = get_item_state_manager().get_item(instance_id)
    except Exception:
        item = None
    if item is None:
        abort(404)
    data = item.get_data() if hasattr(item, "get_data") else dict(item)
    display = display_registry.get("time_series")
    renderer = getattr(display, "renderer", display)
    options = renderer.get_display_options(field_config)
    try:
        key, rec = open_signal(_config, data.get(field), options)
    except SignalError as e:
        abort(_error(422, str(e)))
    return options, data, key, rec


def _error(status, message):
    from flask import jsonify
    response = jsonify({"error": message})
    response.status_code = status
    return response


def _float_arg(name, default=None):
    from flask import request
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def signal_window():
    from flask import abort, jsonify, request
    from potato.science.signal_store import cached_window, channel_indices, ranges
    from potato.science.signals import MAX_PX, SignalError
    options, _data, key, rec = _context()
    start, end = _float_arg("start", rec.t_start), _float_arg("end", rec.t_end)
    px = _float_arg("px", 1000)
    if start is None or end is None or px is None:
        abort(_error(400, "start, end and px must be numbers"))
    if not end > start:
        abort(_error(400, "end must be after start"))
    px = int(max(16, min(MAX_PX, px)))
    wanted = request.args.get("channels")
    names = [n for n in wanted.split(",") if n] if wanted else (options.get("channels") or None)
    names = [n["name"] if isinstance(n, dict) else n for n in names] if names else None
    try:
        chans = channel_indices(rec, names)
        out = dict(cached_window(key, rec, start, end, px, chans))
        out["ranges"] = ranges(rec, chans)
    except SignalError as e:
        abort(_error(422, str(e)))
    response = jsonify(out)
    response.headers["Cache-Control"] = "private, max-age=300"
    return response


def signal_preannotations():
    from flask import abort, jsonify, request
    from potato.science.signal_store import preannotations
    from potato.science.signals import SignalError
    _options, data, _key, rec = _context()
    name = request.args.get("schema", "")
    scheme = next((s for s in _config.get("annotation_schemes") or []
                   if s.get("name") == name and s.get("annotation_type") == "interval_label"), None)
    if scheme is None:
        abort(404)
    try:
        out = preannotations(_config, scheme, data, rec)
    except SignalError as e:
        abort(_error(422, str(e)))
    response = jsonify(out)
    response.headers["Cache-Control"] = "no-store"
    return response


def register_signal_routes(app, config) -> None:
    global _config
    _config = config
    if "signal_window" in app.view_functions:
        return
    app.add_url_rule("/api/signals/window", "signal_window", signal_window)
    app.add_url_rule("/api/signals/preannotations", "signal_preannotations", signal_preannotations)
    _check_bindings(config)


def _check_bindings(config) -> None:
    """Say at start-up when an interval_label scheme names no time_series field."""
    keys = {f.get("key") for f in ((config.get("instance_display") or {}).get("fields") or [])
            if isinstance(f, dict) and f.get("type") == "time_series"}
    for s in config.get("annotation_schemes") or []:
        if isinstance(s, dict) and s.get("annotation_type") == "interval_label":
            if s.get("signal_field") not in keys:
                logger.error("interval_label '%s': signal_field '%s' is not a time_series field "
                             "in instance_display (time_series fields: %s)", s.get("name"),
                             s.get("signal_field"), ", ".join(sorted(k for k in keys if k)) or "none")
