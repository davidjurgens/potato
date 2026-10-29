"""
``GET /api/spectrum/range?instance_id=<id>&field=<key>&x0=<a>&x1=<b>``

Full-resolution points of one item's spectrum between ``x0`` and ``x1``
(downsampled to the display's ``max_points`` if the range still holds more),
and the integral over that range computed on every original point::

    {"x": [...], "y": [...], "integral": 41.73, "points": 812, "from": a, "to": b}

The spectrum display calls it when the annotator zooms in and when a region
is dragged for integration. It needs a signed-in annotator, and the item must
be one assigned to them; the field must be a ``spectrum`` display in
``instance_display``. The file is resolved the same way the page resolved it,
so nothing outside the media directory is read.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

_config: dict = {}


def _live_config() -> dict:
    """The server's config as the page saw it (the display resolves files
    against the same one)."""
    try:
        from potato.server_utils.config_module import config as live
        if live:
            return live
    except ImportError:   # pragma: no cover
        pass
    return _config


def _field_config(key: str):
    fields = ((_live_config().get("instance_display") or {}).get("fields")) or []
    for f in fields:
        if isinstance(f, dict) and str(f.get("key")) == key and f.get("type") == "spectrum":
            return f
    return None


def _may_read(username: str, instance_id: str) -> bool:
    from potato.user_state_management import get_user_state_manager
    try:
        state = get_user_state_manager().get_user_state(username)
    except Exception:
        state = None
    if state is None:
        return False
    try:
        if instance_id in state.get_assigned_instance_ids():
            return True
    except Exception:
        pass
    try:
        return state.get_current_instance_id() == instance_id
    except Exception:
        return False


def spectrum_range():
    from flask import jsonify, request, session
    from potato.item_state_management import get_item_state_manager
    from potato.science.spectra import downsample, integrate, round_sig, window
    from potato.server_utils.displays.spectrum_display import SpectrumDisplay, load_spectrum
    from potato.server_utils.displays.viewer_display import ViewerDataError

    username = session.get("username")
    if not username:
        return jsonify({"error": "Sign in first."}), 401
    instance_id = request.args.get("instance_id", "")
    key = request.args.get("field", "")
    try:
        x0, x1 = float(request.args.get("x0", "")), float(request.args.get("x1", ""))
    except ValueError:
        return jsonify({"error": "x0 and x1 must be numbers."}), 400
    if not (math.isfinite(x0) and math.isfinite(x1)):
        return jsonify({"error": "x0 and x1 must be finite."}), 400
    field = _field_config(key)
    if field is None:
        return jsonify({"error": f"'{key}' is not a spectrum field."}), 404
    if not _may_read(username, instance_id):
        return jsonify({"error": "That item is not assigned to you."}), 403
    try:
        item = get_item_state_manager().get_item(instance_id)
    except Exception:
        item = None
    if item is None:
        return jsonify({"error": "No such item."}), 404
    data = item.get_data() if hasattr(item, "get_data") else dict(item)
    display = SpectrumDisplay()
    options = display.get_display_options(field)
    try:
        spectrum, _peaks, _source = load_spectrum((data or {}).get(key), options)
    except ViewerDataError as e:
        return jsonify({"error": str(e)}), 422
    a, b = window(spectrum, x0, x1)
    xs, ys = spectrum.x[a:b], spectrum.y[a:b]
    count = len(xs)
    mode = options.get("mode") or "auto"
    sticks = spectrum.sticks if mode == "auto" else mode == "sticks"
    xs, ys = downsample(xs, ys, int(options.get("max_points") or 4000), sticks=sticks)
    response = jsonify({
        "x": round_sig(xs), "y": round_sig(ys), "points": count,
        # Sticks have no area: their "integral" is the summed intensity.
        "integral": float(spectrum.y[a:b].sum()) if sticks else integrate(spectrum, x0, x1),
        "from": min(x0, x1), "to": max(x0, x1),
    })
    response.headers["Cache-Control"] = "private, no-store"
    return response


def register_spectrum_routes(app, config) -> None:
    global _config
    _config = config
    if "spectrum_range" in app.view_functions:
        return
    app.add_url_rule("/api/spectrum/range", "spectrum_range", spectrum_range, methods=["GET"])
