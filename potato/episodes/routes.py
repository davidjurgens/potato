"""
``GET /api/episode/<path>`` — an episode manifest for the timeline.

## Why the browser is not handed the item

The obvious alternative is to put the whole episode in the item JSON. It does
not survive contact with real data: a ten-minute demonstration at 50 Hz with a
fourteen-joint arm is 420,000 numbers per episode, and `ItemStateManager` holds
every item in memory. A hundred episodes would be forty million floats resident
before anyone opened the first one.

So the item carries a *path*, and this route reads it on demand, downsamples the
series to something a few hundred pixels wide can actually show, and hands back
a manifest of a few tens of kilobytes.

Registered from ``configure_routes()`` — a bare ``@app.route`` decorator 404s
under ``potato start`` (invariant 4).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

#: Series samples sent to the browser per channel. See `Episode.to_json`.
DEFAULT_MAX_SAMPLES = 4000

#: The live config, captured at registration time. NOT re-imported per request:
#: see the note in potato/media/routes.py for what that breaks.
_registered_config: dict = {}


def _config() -> dict:
    return _registered_config


def episode_manifest(filepath: str):
    """Read an episode and return the manifest the timeline consumes."""
    from flask import jsonify, request

    from potato.episodes.models import EpisodeError
    from potato.episodes.registry import read_episode
    from potato.media.paths import resolve_media_path

    config = _config()
    media_dir, resolved = resolve_media_path(config, filepath,
                                             context="Episode")
    if resolved is None:
        return jsonify({"error": "forbidden"}), 403
    if not os.path.exists(resolved):
        return jsonify({"error": f"{Path(filepath).name} not found"}), 404

    # Streams are named relative to the episode, and the browser fetches them
    # through /media. Building the prefix here rather than in each reader keeps
    # every reader ignorant of how Potato serves files.
    prefix = _media_prefix(media_dir, Path(resolved))

    try:
        episode = read_episode(
            resolved,
            episode=request.args.get("episode") or 0,
            media_prefix=prefix,
            fps=_float_arg(request.args, "fps") or 30.0)
    except EpisodeError as exc:
        # 415, not 500: the file is fine and we cannot read it, and the message
        # names the missing dependency or the conversion command.
        return jsonify({"error": str(exc)}), 415

    max_samples = int(_float_arg(request.args, "max_samples")
                      or DEFAULT_MAX_SAMPLES)
    return jsonify(episode.to_json(max_samples=max_samples))


def episode_list(filepath: str):
    """What is inside a multi-episode source, without reading any of it."""
    from flask import jsonify

    from potato.episodes.models import EpisodeError
    from potato.episodes.registry import list_episodes
    from potato.media.paths import resolve_media_path

    _media_dir, resolved = resolve_media_path(_config(), filepath,
                                              context="Episode")
    if resolved is None:
        return jsonify({"error": "forbidden"}), 403
    if not os.path.exists(resolved):
        return jsonify({"error": f"{Path(filepath).name} not found"}), 404

    try:
        return jsonify({"episodes": list_episodes(resolved)})
    except EpisodeError as exc:
        return jsonify({"error": str(exc)}), 415


def _media_prefix(media_dir, resolved: Path) -> str:
    """
    The ``/media/...`` prefix that makes an episode-relative URL fetchable.

    A LeRobot episode names its video as `videos/chunk-000/...` relative to the
    dataset root, which is itself somewhere under the media directory. Without
    the prefix the browser resolves it against the page URL and gets a 404 that
    looks like a missing file rather than a mangled path.
    """
    if not media_dir:
        return "/media"
    root = resolved if resolved.is_dir() else resolved.parent
    try:
        rel = root.relative_to(Path(media_dir)).as_posix()
    except ValueError:
        return "/media"
    return "/media" if rel in ("", ".") else f"/media/{rel}"


def _float_arg(args, name):
    raw = args.get(name)
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def register_episode_routes(app, config: dict) -> None:
    """
    Wire the episode routes.

    Called from ``configure_routes``; ``config`` is passed in rather than
    imported so these handlers read the same object ``serve_media`` does.
    """
    global _registered_config
    _registered_config = config

    app.add_url_rule("/api/episode/<path:filepath>", "episode_manifest",
                     episode_manifest, methods=["GET"])
    app.add_url_rule("/api/episodes/<path:filepath>", "episode_list",
                     episode_list, methods=["GET"])
