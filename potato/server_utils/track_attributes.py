"""
An attribute's value at one frame of a track.

Attributes are one value per track unless their definition says
``per_keyframe: true`` (schemas/object_attributes.py). Then the value can
change along the track: a video track's keyframe carries
``"attributes": {name: value}`` for what changes there, and the value holds
until the next keyframe that sets it. Before the first such keyframe the
track's own ``attributes`` apply. Values are never interpolated.

Point-cloud sequence keyframes carry a full ``attributes`` dict each, so
there the value at a frame is simply the latest keyframe's.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

FrameOf = Callable[[Any, dict], Optional[int]]


def _default_frame(key: Any, keyframe: dict) -> Optional[int]:
    try:
        return int(keyframe.get("frame", key))
    except (TypeError, ValueError):
        return None


def keyframe_overrides(track: dict, frame_of: Optional[FrameOf] = None) -> List[Tuple[int, dict]]:
    """``[(frame, attributes set there)]`` for a video track, sorted by frame.

    ``frame_of(key, keyframe)`` maps a keyframe to the caller's frame
    numbering (an exporter working in the video's real frames passes one
    built from the keyframe's time); keyframe ``frame`` by default.
    """
    frame_of = frame_of or _default_frame
    out = []
    for key, keyframe in (track.get("keyframes") or {}).items():
        if not isinstance(keyframe, dict) or not isinstance(keyframe.get("attributes"), dict):
            continue
        frame = frame_of(key, keyframe)
        if frame is not None and keyframe["attributes"]:
            out.append((frame, keyframe["attributes"]))
    return sorted(out, key=lambda pair: pair[0])


def attributes_at(track: dict, frame: int, frame_of: Optional[FrameOf] = None) -> Dict[str, Any]:
    """Every attribute of a video track as it stands at ``frame``."""
    values = dict(track.get("attributes") or {})
    for at, overrides in keyframe_overrides(track, frame_of):
        if at > frame:
            break
        values.update(overrides)
    return values


def steps(track: dict, frame_of: Optional[FrameOf] = None) -> List[Tuple[int, Dict[str, Any]]]:
    """``[(frame, full attributes from that frame on)]``: where a video
    track's attributes change. The first entry is the track's own values at
    its first keyframe."""
    frame_of = frame_of or _default_frame
    frames = [f for f in (frame_of(k, kf) for k, kf in (track.get("keyframes") or {}).items()
                          if isinstance(kf, dict)) if f is not None]
    if not frames:
        return []
    out = [(min(frames), dict(track.get("attributes") or {}))]
    for at, overrides in keyframe_overrides(track, frame_of):
        merged = dict(out[-1][1])
        merged.update(overrides)
        if at <= out[-1][0]:
            out[-1] = (out[-1][0], merged)
        else:
            out.append((at, merged))
    return out


def value_at(steps_: List[Tuple[int, Dict[str, Any]]], name: str, frame: int) -> Any:
    """The value of ``name`` at ``frame`` from :func:`steps`-shaped data."""
    value = None
    for at, values in steps_:
        if at > frame:
            break
        value = values.get(name)
    return value
