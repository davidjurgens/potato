"""
``GET /media/proxy/<path>`` — serve a browser-displayable rendering of a file
the browser cannot display.

Registered from ``configure_routes()`` (invariant 4: a bare ``@app.route``
decorator 404s under ``potato start``).

The route is deliberately thin. It resolves the path against the media
directory with the same traversal guard ``serve_media`` uses, decides whether a
transcode is needed, and serves from cache. All the format knowledge lives in
:mod:`potato.media.images` and :mod:`potato.media.video`.

Errors are returned as JSON with the actionable message from the transcoder —
"install pillow-heif", or the ffmpeg command to run — rather than a 500. A
broken image icon with a stack trace in the log is precisely the failure this
package exists to replace.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

#: Query parameters that change the rendering, and so the cache key.
WINDOW_PARAMS = ("window_min", "window_max", "gamma", "page")

#: The live config, captured at registration time.
#:
#: NOT re-imported per request. `from potato.routes import config` inside a
#: handler looks harmless, but under `python potato/flask_server.py` the routes
#: module is already loaded under a DIFFERENT name, so the import re-executes
#: it and its module-level @app.route decorators fire again against the running
#: app -- every media request then died with "View function mapping is
#: overwriting an existing endpoint function: home". Same __main__-vs-package
#: split that has bitten module-level state before.
_registered_config: dict = {}


def _config() -> dict:
    return _registered_config


def _resolve_media_path(config, filepath: str):
    """
    Resolve a request path inside the media directory.

    Delegates to :func:`potato.media.paths.resolve_media_path` so this route,
    ``routes.serve_media`` and the critique service share one traversal guard.
    This route hands the result to a decoder, so it must not be the one place
    the check is subtly weaker.
    """
    from potato.media.paths import resolve_media_path

    return resolve_media_path(config, filepath, context="Media proxy")


def _float_arg(args, name):
    raw = args.get(name)
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def media_proxy(filepath: str):
    """Serve a transcoded rendering of ``filepath``, caching the result."""
    from flask import jsonify, request, send_file

    from potato.media.cache import get_media_cache
    from potato.media.images import (IMAGE_PASSTHROUGH, ImageTranscodeError,
                                     TRANSCODE_IMAGE_EXTENSIONS,
                                     transcode_image)
    from potato.media.video import (TRANSCODE_VIDEO_EXTENSIONS,
                                    VIDEO_PASSTHROUGH, VideoTranscodeError,
                                    transcode_video)

    media_dir, resolved = _resolve_media_path(_config(), filepath)
    if resolved is None:
        return jsonify({"error": "forbidden"}), 403
    if not os.path.isfile(resolved):
        return jsonify({"error": f"{Path(filepath).name} not found"}), 404

    source = Path(resolved)
    suffix = source.suffix.lower()

    # Nothing to do: hand it straight back rather than re-encoding a JPEG.
    if suffix in IMAGE_PASSTHROUGH or suffix in VIDEO_PASSTHROUGH:
        return send_file(resolved)

    output_dir = _config().get("output_annotation_dir") or _config().get(
        "task_dir", ".")
    cache = get_media_cache(str(output_dir))
    cache.ensure_dir()

    if suffix in TRANSCODE_IMAGE_EXTENSIONS:
        params = {
            "page": int(_float_arg(request.args, "page") or 0),
            "window_min": _float_arg(request.args, "window_min"),
            "window_max": _float_arg(request.args, "window_max"),
            "gamma": _float_arg(request.args, "gamma") or 1.0,
        }
        target = cache.path_for(source, ".webp", **params)
        with cache.lock_for(target):
            if not target.exists():
                try:
                    transcode_image(str(source), str(target), **params)
                except ImageTranscodeError as exc:
                    # 415: the file is fine, we cannot render it. A 500 would
                    # suggest a bug and hide the actionable message.
                    return jsonify({"error": str(exc)}), 415
                cache.prune()
        return send_file(str(target), mimetype="image/webp")

    if suffix in TRANSCODE_VIDEO_EXTENSIONS:
        target = cache.path_for(source, ".webm")
        with cache.lock_for(target):
            if not target.exists():
                try:
                    transcode_video(str(source), str(target))
                except VideoTranscodeError as exc:
                    return jsonify({"error": str(exc)}), 415
                cache.prune()
        return send_file(str(target), mimetype="video/webm")

    return jsonify({
        "error": f"{suffix or 'This file'} is not a media format Potato knows "
                 f"how to convert. Supported: "
                 f"{', '.join(sorted(TRANSCODE_IMAGE_EXTENSIONS))} and "
                 f"{', '.join(sorted(TRANSCODE_VIDEO_EXTENSIONS))}."
    }), 415


def media_info(filepath: str):
    """
    Describe a source without rendering it.

    The windowing sliders need the real value range before the first render, so
    that a 16-bit scan opens with sensible bounds instead of 0-65535.
    """
    from flask import jsonify

    from potato.media.images import ImageTranscodeError, describe_image
    from potato.media.video import probe_video

    _media_dir, resolved = _resolve_media_path(_config(), filepath)
    if resolved is None:
        return jsonify({"error": "forbidden"}), 403
    if not os.path.isfile(resolved):
        return jsonify({"error": f"{Path(filepath).name} not found"}), 404

    suffix = Path(resolved).suffix.lower()
    from potato.media.video import TRANSCODE_VIDEO_EXTENSIONS, VIDEO_PASSTHROUGH

    if suffix in TRANSCODE_VIDEO_EXTENSIONS or suffix in VIDEO_PASSTHROUGH:
        return jsonify({"kind": "video", **probe_video(resolved)})

    try:
        return jsonify({"kind": "image", **describe_image(resolved)})
    except ImageTranscodeError as exc:
        return jsonify({"error": str(exc)}), 415


def serve_model_file(filepath: str):
    """
    Serve a downloaded segmentation model or the ONNX runtime.

    These live in ``potato/models/``, NOT in the static tree, because they are
    a per-install download rather than package source — gitignored, 45 MB for
    the weights and 13.5 MB for the runtime. Serving them from ``/models``
    keeps that distinction visible: a 404 here means "nobody ran
    download-models", which is a different problem from a missing asset.
    """
    from flask import jsonify, send_from_directory

    from potato.models_cli import DEFAULT_MODEL_DIR

    root = os.path.realpath(str(DEFAULT_MODEL_DIR))
    requested = os.path.realpath(os.path.join(root, filepath))
    # Same traversal guard as the media routes: this path comes from a config
    # value that an admin controls, but it still reaches the filesystem.
    if not requested.startswith(root + os.sep):
        return jsonify({"error": "forbidden"}), 403
    if not os.path.isfile(requested):
        return jsonify({
            "error": f"{filepath} is not installed. An administrator can add "
                     f"it with:  potato download-models"
        }), 404

    response = send_from_directory(root, filepath)
    # Weights are content-addressed by their pinned checksum and never change
    # in place, so a long cache is safe and saves a 28 MB re-fetch per item.
    response.headers["Cache-Control"] = "public, max-age=604800"
    return response


def point_cloud(filepath: str):
    """
    Serve a point cloud as the PNT1 buffer the 3D viewer fetches.

    Converted and cached exactly like a transcoded image, for the same reason:
    parsing PCD/PLY/LAS in JavaScript would mean four parsers, and re-parsing a
    two-million-point scan on every page load.

    ``max_points`` is part of the cache key, so lowering it for a slow machine
    does not serve the previous decimation from cache.
    """
    from flask import jsonify, request, send_file

    from potato.media.cache import get_media_cache
    from potato.media.pointcloud import (DEFAULT_MAX_POINTS, PointCloudError,
                                         read_point_cloud, to_wire)

    _media_dir, resolved = _resolve_media_path(_config(), filepath)
    if resolved is None:
        return jsonify({"error": "forbidden"}), 403
    if not os.path.isfile(resolved):
        return jsonify({"error": f"{Path(filepath).name} not found"}), 404

    raw_max = _float_arg(request.args, "max_points")
    max_points = int(raw_max) if raw_max and raw_max > 0 else DEFAULT_MAX_POINTS

    output_dir = _config().get("output_annotation_dir") or _config().get(
        "task_dir", ".")
    cache = get_media_cache(str(output_dir))
    cache.ensure_dir()

    source = Path(resolved)
    target = cache.path_for(source, ".pnt", max_points=max_points)
    with cache.lock_for(target):
        if not target.exists():
            try:
                cloud = read_point_cloud(str(source), max_points=max_points)
            except PointCloudError as exc:
                # 415, not 500: the file is fine, we cannot read it, and the
                # message names the conversion command to run.
                return jsonify({"error": str(exc)}), 415
            target.write_bytes(to_wire(cloud))
            cache.prune()

    response = send_file(str(target), mimetype="application/octet-stream")
    return response


def register_media_routes(app, config: dict) -> None:
    """
    Wire the proxy routes.

    Called from ``configure_routes``; a ``@app.route`` decorator alone is not
    enough, because the live server serves the app built by ``create_app()``.

    ``config`` is passed in rather than imported, so these handlers read the
    same object ``serve_media`` does without importing the routes module a
    second time -- see the note on ``_registered_config``.
    """
    global _registered_config
    _registered_config = config

    app.add_url_rule("/media/proxy/<path:filepath>", "media_proxy",
                     media_proxy, methods=["GET"])
    app.add_url_rule("/media/info/<path:filepath>", "media_info",
                     media_info, methods=["GET"])
    # Point clouds, converted server-side to one wire format (see
    # potato/media/pointcloud.py for why the browser is not handed the original).
    app.add_url_rule("/media/pointcloud/<path:filepath>", "media_point_cloud",
                     point_cloud, methods=["GET"])
    # Segmentation weights and the ONNX runtime, downloaded per install.
    app.add_url_rule("/models/<path:filepath>", "serve_model_file",
                     serve_model_file, methods=["GET"])
