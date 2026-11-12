"""
Turning what a project actually has into a :class:`RolloutSet`.

## Why frame rate is declared and never guessed

HTML5 video exposes no frame rate. There is no `video.fps`, and deriving one by
timing `requestVideoFrameCallback` gives the *display* rate, not the encoded
one. So the frame numbers this package quotes come from a declaration — the
schema's ``fps``, or the manifest's — and when nothing declares one, frame
numbers are **omitted** rather than computed from a guess.

That matters more here than elsewhere. The output of this schema is "the
physics breaks at frame 47", checked against a tensor by someone who was not
in the room. A frame number off by a factor of 30/24 is worse than no frame
number, because it looks right.

Durations are the mirror image: the manifest may declare them, but the browser
learns the truth from `loadedmetadata` in under a second, so nothing here
shells out to ffprobe. A route that spawned four subprocesses per item would
make loading an item slower than watching one.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Sequence

from potato.rollouts.models import (
    RolloutError,
    RolloutSet,
    RolloutStream,
    slugify_stream_id,
)

logger = logging.getLogger(__name__)

#: Where a relative stream path is served from. Item fields and manifests both
#: name files relative to the project's media directory, and both reach the
#: browser through this route.
DEFAULT_MEDIA_PREFIX = "/media"


def read_rollout_set(item_data: Dict[str, Any],
                     spec: Dict[str, Any],
                     *,
                     set_id: str = "",
                     resolve_manifest=None) -> RolloutSet:
    """
    Build the set for one item.

    ``spec`` is the schema's configuration — ``streams``, ``manifest_field``,
    ``prompt_field``, ``fps`` and friends. ``resolve_manifest`` maps a
    project-relative manifest path to an absolute one; it is injected rather
    than imported so this module stays testable without a Flask config, and so
    the traversal guard lives in exactly one place (``media/paths.py``).
    """
    manifest_field = spec.get("manifest_field")
    if manifest_field:
        raw = item_data.get(manifest_field)
        if not raw:
            raise RolloutError(
                f"this item has no '{manifest_field}' field, so there is no "
                f"rollout manifest to read. Either add the field or drop "
                f"manifest_field from the schema to read streams from the item "
                f"itself.")
        if resolve_manifest is None:
            raise RolloutError("no manifest resolver was supplied")
        path = resolve_manifest(str(raw))
        if path is None:
            raise RolloutError(f"'{raw}' is outside the project media directory")
        return from_manifest(path, spec, set_id=set_id or str(raw))

    return from_item(item_data, spec, set_id=set_id)


def from_item(item_data: Dict[str, Any], spec: Dict[str, Any],
              *, set_id: str = "") -> RolloutSet:
    """
    Read streams straight off the item.

    The common case: a generated-video benchmark ships one row per scenario
    with a column per generator, and turning that into files on disk just to
    read it back would be work for nobody's benefit.

    A configured stream whose field is empty for this item is **skipped with a
    warning**, not treated as a broken video. Benchmarks are ragged — a model
    that failed to produce a rollout for one prompt is normal — and an empty
    panel that says "not found" reads as a Potato bug rather than as missing
    data.
    """
    configured = spec.get("streams") or []
    if not configured:
        raise RolloutError(
            "the schema lists no streams. Add a 'streams:' block naming the "
            "item fields that hold each rollout's video URL.")

    streams: List[RolloutStream] = []
    missing: List[str] = []
    fps = _float(spec.get("fps")) or 0.0

    for entry in configured:
        conf = entry if isinstance(entry, dict) else {"field": entry}
        field = conf.get("field")
        if not field:
            raise RolloutError(
                f"stream entry {conf!r} has no 'field'; each stream names the "
                f"item field holding its video URL.")
        url = item_data.get(field)
        if not url:
            missing.append(str(conf.get("name") or field))
            continue
        streams.append(RolloutStream(
            stream_id=slugify_stream_id(conf.get("id") or field),
            # Relative paths are relative to the media directory, exactly as
            # they are in a manifest. Passing them through verbatim makes the
            # browser resolve them against the page URL, and every panel 404s
            # -- with no error anywhere except the network tab, because a
            # <video> whose source is missing simply never reports a length and
            # the timeline sits at zero looking like it is still loading.
            url=_join_url(DEFAULT_MEDIA_PREFIX, str(url)),
            name=str(conf.get("name") or field),
            role=str(conf.get("role") or "model"),
            fps=_float(conf.get("fps")) or fps,
            metadata=dict(conf.get("metadata") or {}),
        ))

    rollout = RolloutSet(
        set_id=set_id or str(item_data.get("id") or "rollout"),
        streams=streams,
        prompt=_text(item_data, spec.get("prompt_field", "prompt")),
        intervention=_text(item_data, spec.get("intervention_field",
                                               "intervention")),
        intervention_t=_float(item_data.get(
            spec.get("intervention_time_field", "intervention_t"))),
        fps=fps,
        source_format="item",
    )
    if missing:
        rollout.metadata["missing_streams"] = missing
    return rollout


def from_manifest(path: str, spec: Dict[str, Any],
                  *, set_id: str = "") -> RolloutSet:
    """
    Read a JSON manifest sitting next to the videos.

    Stream URLs in a manifest are relative to the manifest, and are rewritten
    to ``/media/...`` here — the readers stay ignorant of how Potato serves
    files, which is the same split ``potato/episodes`` uses.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        raise RolloutError(f"{os.path.basename(path)} not found")
    except ValueError as exc:
        raise RolloutError(
            f"{os.path.basename(path)} is not valid JSON: {exc}")

    if not isinstance(raw, dict):
        raise RolloutError(
            f"{os.path.basename(path)} must be a JSON object with a 'streams' "
            f"list, not a {type(raw).__name__}.")

    entries = raw.get("streams")
    if not isinstance(entries, list) or not entries:
        raise RolloutError(
            f"{os.path.basename(path)} has no 'streams' list.")

    prefix = _media_prefix(spec.get("media_root"), path)
    fps = _float(raw.get("fps")) or _float(spec.get("fps")) or 0.0

    streams: List[RolloutStream] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise RolloutError(
                f"stream {index} in {os.path.basename(path)} is a "
                f"{type(entry).__name__}, not an object.")
        url = entry.get("url") or entry.get("path") or entry.get("video")
        if not url:
            raise RolloutError(
                f"stream {index} in {os.path.basename(path)} has no 'url'.")
        streams.append(RolloutStream(
            stream_id=slugify_stream_id(
                entry.get("id") or entry.get("name") or f"stream{index}"),
            url=_join_url(prefix, str(url)),
            name=str(entry.get("name") or entry.get("id") or f"stream{index}"),
            role=str(entry.get("role") or "model"),
            fps=_float(entry.get("fps")) or fps,
            num_frames=int(entry.get("num_frames") or 0),
            duration=_float(entry.get("duration")) or 0.0,
            metadata=dict(entry.get("metadata") or {}),
        ))

    return RolloutSet(
        set_id=set_id or str(raw.get("set_id") or os.path.basename(path)),
        streams=streams,
        prompt=str(raw.get("prompt") or ""),
        intervention=str(raw.get("intervention") or ""),
        intervention_t=_float(raw.get("intervention_t")),
        fps=fps,
        metadata=dict(raw.get("metadata") or {}),
        source_format="manifest",
    )


def _media_prefix(media_root: Optional[str], manifest_path: str) -> str:
    """
    The ``/media/...`` prefix a relative stream url hangs off.

    Without a known media root there is nothing to make relative *to*, so the
    urls are used verbatim — a manifest full of absolute URLs is a legitimate
    shape, and inventing a prefix for it would break it.
    """
    if not media_root:
        return ""
    try:
        rel = os.path.relpath(os.path.dirname(os.path.realpath(manifest_path)),
                              os.path.realpath(media_root))
    except ValueError:
        return ""
    if rel.startswith(".."):
        return ""
    rel = "" if rel == "." else rel
    return f"/media/{rel}".rstrip("/")


def _join_url(prefix: str, url: str) -> str:
    if not prefix:
        return url
    if url.startswith(("http://", "https://", "/")):
        return url
    return f"{prefix}/{url.lstrip('./')}"


def _text(data: Dict[str, Any], field: Optional[str]) -> str:
    if not field:
        return ""
    value = data.get(field)
    return "" if value is None else str(value)


def _float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None
