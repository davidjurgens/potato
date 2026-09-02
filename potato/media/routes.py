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
    # Deliberately no max-age here, unlike the transcoded branches below: this
    # is the user's own file at a stable path, and a researcher who swaps it
    # mid-study should see the new one. Flask still sends Last-Modified/ETag, so
    # a prefetched copy revalidates with a 304 instead of re-downloading.
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
        response = send_file(str(target), mimetype="image/webp")
        # Derived from an immutable (path, size, mtime, params) cache key, same
        # as the deep-zoom tiles below, so it can be cached hard. Without this a
        # prefetched image is re-validated on every Next click.
        response.headers["Cache-Control"] = "public, max-age=604800"
        return response

    if suffix in TRANSCODE_VIDEO_EXTENSIONS:
        target = cache.path_for(source, ".webm")
        with cache.lock_for(target):
            if not target.exists():
                try:
                    transcode_video(str(source), str(target))
                except VideoTranscodeError as exc:
                    return jsonify({"error": str(exc)}), 415
                cache.prune()
        response = send_file(str(target), mimetype="video/webm")
        # Immutable cache key, as above.
        response.headers["Cache-Control"] = "public, max-age=604800"
        return response

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


def _tile_spec(filepath: str, args):
    """
    ``(resolved_path, spec, settings, page, None)`` or ``(..., error_response)``.

    Shared by all four tile routes so the descriptor and the tiles are computed
    from the same arithmetic. A descriptor that disagreed with the tiles by one
    pixel renders correctly until the last column and then 404s across it.
    """
    from flask import jsonify

    from potato.media.tiles import DEFAULT_MAX_PIXELS, TileError, describe

    _media_dir, resolved = _resolve_media_path(_config(), filepath)
    if resolved is None:
        return None, None, None, 0, (jsonify({"error": "forbidden"}), 403)
    if not os.path.isfile(resolved):
        return None, None, None, 0, (
            jsonify({"error": f"{Path(filepath).name} not found"}), 404)

    def _int(name, default):
        try:
            return int(args.get(name) or default)
        except (TypeError, ValueError):
            return default

    settings = {
        "tile_size": _int("tile_size", 254),
        "overlap": _int("overlap", 1),
        "max_pixels": _int("max_pixels", DEFAULT_MAX_PIXELS),
    }
    page = _int("page", 0)
    try:
        spec = describe(resolved, tile_size=settings["tile_size"],
                        overlap=settings["overlap"], page=page)
    except TileError as exc:
        # 415, not 500: the request is well formed and the *source* cannot be
        # tiled, and the message names what to do about it.
        return None, None, None, 0, (jsonify({"error": str(exc)}), 415)
    return resolved, spec, settings, page, None


def tile_descriptor(filepath: str):
    """The DZI descriptor, plus the same geometry as JSON for the client."""
    from flask import Response, jsonify, request

    resolved, spec, _settings, _page, error = _tile_spec(filepath, request.args)
    if error is not None:
        return error

    if (request.args.get("format") or "dzi").lower() == "json":
        return jsonify(spec.to_json())
    return Response(spec.dzi(), mimetype="application/xml")


def tile_image(filepath: str, level: int, column: int, row: int):
    """
    One tile. Builds its whole level on first touch — see potato/media/tiles.py.

    The first request into a level is slow and the rest are not, which is the
    intended shape: zooming in costs one decode, panning around costs nothing.
    """
    from flask import jsonify, request, send_file

    from potato.media.cache import get_media_cache
    from potato.media.tiles import TileError, tile_file

    resolved, spec, settings, page, error = _tile_spec(filepath, request.args)
    if error is not None:
        return error

    cache = get_media_cache(_config().get("output_annotation_dir"))
    try:
        path = tile_file(cache.ensure_dir(), Path(resolved), spec, int(level),
                         int(column), int(row), page=page,
                         max_pixels=settings["max_pixels"])
    except TileError as exc:
        return jsonify({"error": str(exc)}), 415

    response = send_file(str(path))
    # A tile is derived from an immutable (path, size, mtime) key, so it can be
    # cached hard. Deep zoom fetches dozens per pan and re-validating each one
    # would put the network back in the interaction it exists to remove.
    response.headers["Cache-Control"] = "public, max-age=604800"
    return response


def iiif_info(filepath: str):
    """IIIF Image API 3.0 ``info.json`` over the same pyramid."""
    from flask import jsonify, request

    _resolved, spec, _settings, _page, error = _tile_spec(filepath, request.args)
    if error is not None:
        return error

    base = request.url_root.rstrip("/") + "/media/iiif"
    response = jsonify(spec.iiif_info(filepath, base))
    # The IIIF spec asks for this so a viewer on another origin can read it.
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


def iiif_image(filepath: str, region: str, size: str, rotation: str,
               quality_format: str):
    """A IIIF ``{region}/{size}/{rotation}/{quality}.{format}`` request."""
    from flask import Response, jsonify, request

    from potato.media.cache import get_media_cache
    from potato.media.tiles import TileError, iiif_region

    resolved, spec, settings, page, error = _tile_spec(filepath, request.args)
    if error is not None:
        return error

    quality, _dot, fmt = quality_format.partition(".")
    fmt = (fmt or "jpg").lower()
    if fmt not in ("jpg", "jpeg", "png"):
        return jsonify({"error": f"'{fmt}' is not a supported IIIF format; "
                                 f"use jpg or png."}), 400

    cache = get_media_cache(_config().get("output_annotation_dir"))
    try:
        payload, mimetype = iiif_region(
            cache.ensure_dir(), Path(resolved), spec, region, size, rotation,
            quality or "default", "png" if fmt == "png" else "jpg", page=page,
            max_pixels=settings["max_pixels"])
    except TileError as exc:
        return jsonify({"error": str(exc)}), 415

    response = Response(payload, mimetype=mimetype)
    response.headers["Cache-Control"] = "public, max-age=604800"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


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

    With ``?lod=1`` the same path serves an octree instead: the bare request
    returns the manifest, and ``?lod=1&node=r03`` returns one node's points.
    See :mod:`potato.media.octree`.
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

    if request.args.get("lod") in ("1", "true", "yes"):
        return _point_cloud_lod(Path(resolved), request)

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


def depth_map(filepath: str):
    """
    ``GET /media/depth/<path>`` — a depth map, in whichever form is asked for.

    Four representations of the same file, because they answer different
    questions and none of them substitutes for another:

    - no flag: a **colourised PNG**, so the browser has something to show;
    - ``?info=1``: the real value range, needed to set the window before the
      first render — a 16-bit depth map opened blind renders as a black
      rectangle;
    - ``?raw=1``: the **float metres**, because a colourmap is not injective at
      8 bits and the cursor readout cannot be recovered from the picture;
    - ``?pointcloud=1&fx=..``: the same data **unprojected**, so a depth item
      is annotatable in the 3D viewer rather than only lookable-at.
    """
    from flask import Response, jsonify, request, send_file

    from potato.media.cache import get_media_cache
    from potato.media.depth import (COLORMAPS, DEFAULT_COLORMAP, DepthError,
                                    describe, read_depth, to_png, to_wire)

    _media_dir, resolved = _resolve_media_path(_config(), filepath)
    if resolved is None:
        return jsonify({"error": "forbidden"}), 403
    if not os.path.isfile(resolved):
        return jsonify({"error": f"{Path(filepath).name} not found"}), 404

    source = Path(resolved)
    scale = _float_arg(request.args, "scale")
    try:
        depth = read_depth(str(source), scale=scale)
    except DepthError as exc:
        # 415, not 500: the file is fine and we cannot read it. The message
        # names the dependency or the conversion command.
        return jsonify({"error": str(exc)}), 415

    if request.args.get("info") in ("1", "true", "yes"):
        return jsonify({"kind": "depth", **describe(depth)})

    if request.args.get("raw") in ("1", "true", "yes"):
        return Response(to_wire(depth), mimetype="application/octet-stream")

    if request.args.get("pointcloud") in ("1", "true", "yes"):
        return _depth_pointcloud(depth, request)

    colormap = request.args.get("colormap") or DEFAULT_COLORMAP
    if colormap not in COLORMAPS:
        return jsonify({
            "error": f"'{colormap}' is not a colormap. Available: "
                     f"{', '.join(sorted(COLORMAPS))}."}), 400

    window_min = _float_arg(request.args, "window_min")
    window_max = _float_arg(request.args, "window_max")
    window = ((window_min, window_max)
              if window_min is not None and window_max is not None else None)
    invert = request.args.get("invert") in ("1", "true", "yes")

    output_dir = _config().get("output_annotation_dir") or _config().get(
        "task_dir", ".")
    cache = get_media_cache(str(output_dir))
    cache.ensure_dir()
    target = cache.path_for(source, ".depth.png", scale=scale,
                            colormap=colormap, invert=invert,
                            window_min=window_min, window_max=window_max)
    with cache.lock_for(target):
        if not target.exists():
            try:
                target.write_bytes(to_png(depth, window, colormap,
                                          invert=invert))
            except DepthError as exc:
                return jsonify({"error": str(exc)}), 415
            cache.prune()
    return send_file(str(target), mimetype="image/png")


def _depth_pointcloud(depth, request):
    """Unproject a depth map with intrinsics supplied by the caller."""
    from flask import Response, jsonify

    from potato.media.depth import DepthError, unproject
    from potato.media.pointcloud import to_wire as cloud_to_wire

    needed = ("fx", "fy", "cx", "cy")
    values = [_float_arg(request.args, name) for name in needed]
    if any(v is None for v in values):
        missing = [n for n, v in zip(needed, values) if v is None]
        return jsonify({
            "error": f"unprojecting a depth map needs camera intrinsics; "
                     f"missing {', '.join(missing)}. They come from the item's "
                     f"calibration field."}), 400

    frame = request.args.get("frame") or "z_up"
    if frame not in ("z_up", "camera"):
        return jsonify({"error": f"'{frame}' is not a frame; use z_up or "
                                 f"camera."}), 400

    stride = _float_arg(request.args, "stride")
    max_points = _float_arg(request.args, "max_points")
    try:
        cloud = unproject(
            depth, values,
            stride=int(stride) if stride and stride > 0 else 1,
            max_points=int(max_points) if max_points and max_points > 0
            else 500_000,
            frame=frame)
    except DepthError as exc:
        return jsonify({"error": str(exc)}), 400

    return Response(cloud_to_wire(cloud, extra={"from_depth": True}),
                    mimetype="application/octet-stream")


def _point_cloud_lod(source: Path, request):
    """
    Serve the octree manifest, or one node of it.

    The octree is built from the **undecimated** cloud — its whole purpose is
    the density decimation throws away — and cached as one OCT1 file. Building
    is the expensive step and happens once per (file, parameters).

    A node request re-reads the manifest to find its byte range. That is one
    small read per node fetch rather than holding a parsed manifest in a
    process-global cache, which would be a second cache to invalidate and would
    not survive the multi-worker deployments Potato supports.
    """
    from flask import Response, jsonify

    from potato.media.cache import get_media_cache
    from potato.media.octree import (DEFAULT_GRID, DEFAULT_MAX_LEVEL,
                                     DEFAULT_MIN_POINTS, build_octree,
                                     manifest_for_client, node_key_is_safe,
                                     read_manifest, read_node, to_octree_bytes)
    from potato.media.pointcloud import PointCloudError, read_point_cloud

    def _int_arg(name, default):
        raw = _float_arg(request.args, name)
        return int(raw) if raw and raw > 0 else default

    grid = min(128, _int_arg("grid", DEFAULT_GRID))
    max_level = min(12, _int_arg("max_level", DEFAULT_MAX_LEVEL))
    min_points = _int_arg("min_points", DEFAULT_MIN_POINTS)

    node_key = request.args.get("node") or ""
    if node_key and not node_key_is_safe(node_key):
        return jsonify({"error": f"'{node_key}' is not an octree node key"}), 400

    output_dir = _config().get("output_annotation_dir") or _config().get(
        "task_dir", ".")
    cache = get_media_cache(str(output_dir))
    cache.ensure_dir()

    target = cache.path_for(source, ".oct", grid=grid, max_level=max_level,
                            min_points=min_points)
    with cache.lock_for(target):
        if not target.exists():
            try:
                # max_points=0: no decimation. Decimating first and then
                # building an octree over the result would produce a structure
                # that promises detail it discarded before it started.
                cloud = read_point_cloud(str(source), max_points=0)
                tree = build_octree(cloud, grid=grid, max_level=max_level,
                                    min_points=min_points)
            except PointCloudError as exc:
                return jsonify({"error": str(exc)}), 415
            target.write_bytes(to_octree_bytes(tree))
            cache.prune()

    try:
        if node_key:
            blob = read_node(target, node_key)
            return Response(blob, mimetype="application/octet-stream")
        return jsonify(manifest_for_client(read_manifest(target)))
    except PointCloudError as exc:
        return jsonify({"error": str(exc)}), 404


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
    # Depth maps: colourised, described, raw, or unprojected. See depth_map.
    app.add_url_rule("/media/depth/<path:filepath>", "media_depth",
                     depth_map, methods=["GET"])
    # Deep zoom. The descriptor is registered before the tile route because
    # Flask matches in registration order and `<path:filepath>` would otherwise
    # swallow `.../<level>/<col>_<row>.jpg` whole.
    app.add_url_rule("/media/tiles/<path:filepath>.dzi", "media_tile_descriptor",
                     tile_descriptor, methods=["GET"])
    app.add_url_rule(
        "/media/tiles/<path:filepath>_files/<int:level>/<int:column>_<int:row>.<ext>",
        "media_tile_image",
        lambda filepath, level, column, row, ext: tile_image(
            filepath, level, column, row),
        methods=["GET"])
    # IIIF over the same pyramid, for viewers that speak it (Mirador, and
    # OpenSeadragon's IIIF tile source).
    app.add_url_rule("/media/iiif/<path:filepath>/info.json", "media_iiif_info",
                     iiif_info, methods=["GET"])
    app.add_url_rule(
        "/media/iiif/<path:filepath>/<region>/<size>/<rotation>/<quality_format>",
        "media_iiif_image", iiif_image, methods=["GET"])
    # Segmentation weights and the ONNX runtime, downloaded per install.
    app.add_url_rule("/models/<path:filepath>", "serve_model_file",
                     serve_model_file, methods=["GET"])
