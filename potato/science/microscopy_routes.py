"""
Routes for the ``microscopy`` schema.

``GET /api/microscopy/info?schema=<name>&instance_id=<id>``
    The image's geometry (DZI levels over the full-resolution size), its
    pyramid, channels with colours and contrast limits, z / t sizes, physical
    pixel size and label images.
``GET /api/microscopy/tile/<level>/<col>_<row>.jpg?schema&instance_id&ch&z&t``
    One composited tile. ``ch`` lists the visible channels as
    ``index:rrggbb:start:end`` joined by ``;``.
``GET /api/microscopy/labels?schema&instance_id&name&z&t``
    The label image as gzipped little-endian integers, at most
    ``label_max_side`` pixels a side, for hit-testing clicks and drawing
    cells. Width, height, bytes per id and the full-resolution scale are in
    ``X-Label-*`` headers.
``GET /api/microscopy/cells?...``
    Every cell id in that raster with its centroid and area.

All need a signed-in user. The image is named by the item (the schema's
``image_key`` field), never by a path in the request, and the item's path is
resolved inside the project's media directory or task directory; anything
that resolves outside both is refused.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_config: Dict[str, Any] = {}


def _scheme(name: str) -> Optional[Dict[str, Any]]:
    for scheme in _config.get("annotation_schemes") or []:
        if (isinstance(scheme, dict) and scheme.get("name") == name
                and scheme.get("annotation_type") == "microscopy"):
            return scheme
    return None


def resolve_item_path(config: Dict[str, Any], reference: Any) -> Optional[str]:
    """
    A file or directory named by an item, inside the media directory or the
    task directory. Returns None for remote URLs and for anything outside both.
    """
    from potato.media.paths import resolve_media_path

    ref = str(reference or "").strip()
    if not ref or ref.startswith(("http://", "https://", "data:", "//")):
        return None
    for prefix in ("/media/", "media/"):
        if ref.startswith(prefix):
            ref = ref[len(prefix):]
            break
    if os.path.isabs(ref):
        return None
    _root, path = resolve_media_path(config, ref, context="Microscopy")
    if path and os.path.exists(path):
        return path
    task_dir = os.path.realpath(config.get("task_dir") or ".")
    candidate = os.path.realpath(os.path.join(task_dir, ref))
    if candidate.startswith(task_dir + os.sep) and os.path.exists(candidate):
        return candidate
    return None


def _open(schema: str, instance_id: str):
    """``(scheme, image)`` for a request, or aborts."""
    from flask import abort, session

    from potato.item_state_management import get_item_state_manager
    from potato.science.converters.ome import OmeError, open_ome

    if not session.get("username"):
        abort(401)
    scheme = _scheme(schema)
    if scheme is None:
        abort(404)
    try:
        item = get_item_state_manager().get_item(instance_id)
    except Exception:  # noqa: BLE001 - an unknown id is a 404
        item = None
    if item is None:
        abort(404)
    data = item.get_data() if hasattr(item, "get_data") else dict(item)
    key = scheme.get("image_key", "image")
    path = resolve_item_path(_config, (data or {}).get(key))
    if path is None:
        raise OmeError(f"Item {instance_id} has no microscopy image in its '{key}' field, "
                       "or it is not inside the project's media directory.")
    label_path = None
    labels_key = scheme.get("labels_key")
    if labels_key and (data or {}).get(labels_key):
        label_path = resolve_item_path(_config, data[labels_key])
        if label_path is None:
            raise OmeError(f"Item {instance_id} names a label image in '{labels_key}' that "
                           "is not inside the project's media directory.")
    image = open_ome(path, label_path=label_path,
                     max_pixels=int(scheme.get("max_pixels") or 64_000_000))
    return scheme, image


def _error(exc) -> Tuple[Any, int]:
    from flask import jsonify

    from potato.media.routes import _public_error

    return jsonify({"error": _public_error(exc)}), 415


def _plane(args, image) -> Tuple[int, int]:
    def _int(name):
        try:
            return int(args.get(name) or 0)
        except (TypeError, ValueError):
            return -1
    z, t = _int("z"), _int("t")
    image.check_plane(0, z, t)
    return z, t


def _spec(scheme, image):
    from potato.media.tiles import PyramidSpec

    return PyramidSpec(image.size_x, image.size_y,
                       tile_size=int(scheme.get("tile_size") or 254), overlap=1, fmt="jpg")


def _label_name(scheme, image, requested: Optional[str] = None) -> Optional[str]:
    if requested:
        return requested
    wanted = scheme.get("label_image")
    if wanted:
        return wanted if wanted in image.label_images else None
    return image.labels[0] if image.labels else None


def apply_channel_config(scheme: Dict[str, Any], channels: list) -> list:
    """Overlay the schema's ``channels`` entries (matched by index or name)
    onto the file's own channel defaults."""
    overrides = scheme.get("channels") or []
    for entry in overrides:
        if not isinstance(entry, dict):
            continue
        target = None
        for channel in channels:
            if ("index" in entry and entry["index"] == channel["index"]) or (
                    "name" in entry and str(entry["name"]) == channel["name"]):
                target = channel
                break
        if target is None:
            continue
        if entry.get("label"):
            target["name"] = str(entry["label"])
        if entry.get("color"):
            target["color"] = "#" + str(entry["color"]).lstrip("#").lower()
        if isinstance(entry.get("contrast"), list) and len(entry["contrast"]) == 2:
            target["start"], target["end"] = float(entry["contrast"][0]), float(entry["contrast"][1])
            target["min"] = min(target["min"], target["start"])
            target["max"] = max(target["max"], target["end"])
        if "visible" in entry:
            target["visible"] = bool(entry["visible"])
    return channels


def microscopy_info():
    from flask import jsonify, request

    from potato.science.converters.ome import OmeError, _stamp

    try:
        scheme, image = _open(request.args.get("schema", ""), request.args.get("instance_id", ""))
        spec = _spec(scheme, image)
        payload = image.describe()
        payload["channels"] = apply_channel_config(scheme, payload["channels"])
        payload["dzi"] = spec.to_json()
        payload["label_image"] = _label_name(scheme, image)
        payload["version"] = str(int(_stamp(image.path)))
    except OmeError as exc:
        return _error(exc)
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response


def microscopy_tile(level: int, column: int, row: int):
    from flask import Response, request

    from potato.media.tiles import TileError
    from potato.science.converters.ome import OmeError
    from potato.science.microscopy import parse_channel_spec, render_tile

    try:
        scheme, image = _open(request.args.get("schema", ""), request.args.get("instance_id", ""))
        z, t = _plane(request.args, image)
        channels = parse_channel_spec(request.args.get("ch", ""), image)
        body = render_tile(image, _spec(scheme, image), int(level), int(column), int(row),
                           channels, z=z, t=t)
    except (OmeError, TileError) as exc:
        return _error(exc)
    response = Response(body, mimetype="image/jpeg")
    # The URL carries every input of the rendering plus the file's stamp.
    response.headers["Cache-Control"] = "private, max-age=86400"
    return response


def _raster(scheme, image, args):
    from potato.science.converters.ome import OmeError
    from potato.science.microscopy import DEFAULT_LABEL_MAX_SIDE, label_raster

    name = _label_name(scheme, image, args.get("name") or None)
    if not name or name not in image.label_images:
        raise OmeError("This image has no label image, so cells cannot be selected.")
    z, t = _plane(args, image)
    max_side = int(scheme.get("label_max_side") or DEFAULT_LABEL_MAX_SIDE)
    raster, factor = label_raster(image, name, z=z, t=t, max_side=max_side)
    return name, raster, factor


def microscopy_labels():
    from flask import Response, request

    from potato.science.converters.ome import OmeError
    from potato.science.microscopy import encode_raster

    try:
        scheme, image = _open(request.args.get("schema", ""), request.args.get("instance_id", ""))
        name, raster, factor = _raster(scheme, image, request.args)
        body, width = encode_raster(raster)
    except OmeError as exc:
        return _error(exc)
    response = Response(body, mimetype="application/octet-stream")
    response.headers["Content-Encoding"] = "gzip"
    response.headers["X-Label-Name"] = name
    response.headers["X-Label-Width"] = str(raster.shape[1])
    response.headers["X-Label-Height"] = str(raster.shape[0])
    response.headers["X-Label-Bytes"] = str(width)
    response.headers["X-Label-Scale"] = repr(float(factor))
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


def microscopy_cells():
    from flask import jsonify, request

    from potato.science.converters.ome import OmeError
    from potato.science.microscopy import cell_table

    try:
        scheme, image = _open(request.args.get("schema", ""), request.args.get("instance_id", ""))
        name, raster, factor = _raster(scheme, image, request.args)
        cells = cell_table(raster, factor)
    except OmeError as exc:
        return _error(exc)
    return jsonify({"label_image": name, "cells": cells})


def register_microscopy_routes(app, config) -> None:
    global _config
    _config = config
    if "microscopy_info" in app.view_functions:
        return
    app.add_url_rule("/api/microscopy/info", "microscopy_info", microscopy_info)
    app.add_url_rule("/api/microscopy/tile/<int:level>/<int:column>_<int:row>.jpg",
                     "microscopy_tile", microscopy_tile)
    app.add_url_rule("/api/microscopy/labels", "microscopy_labels", microscopy_labels)
    app.add_url_rule("/api/microscopy/cells", "microscopy_cells", microscopy_cells)
