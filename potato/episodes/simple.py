"""
Potato's own episode manifest: a JSON file, and nothing else required.

Every other reader in this package needs an optional dependency — pyarrow, h5py,
tensorflow_datasets — and a real dataset laid out a particular way. This one
needs neither, which makes it what the bundled example uses, what the docs
recommend for "I have my own logs", and what the test fixtures are written in.

    {
      "episode_id": "pick_place_0007",
      "fps": 20,
      "num_frames": 240,
      "instruction": "pick up the red block and put it in the bowl",
      "streams": [
        {"name": "wrist", "url": "video/wrist.webm", "kind": "wrist"}
      ],
      "series": [
        {"name": "gripper", "unit": "m", "values": [0.0, 0.01, ...]}
      ]
    }

``num_frames`` may be omitted and is then taken from the longest series, because
the frame count is a property of the data and repeating it is one more thing to
get out of step.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from potato.episodes.models import Episode, EpisodeError, Series, Stream


def manifest_path(path: str | Path) -> Optional[Path]:
    """
    The manifest file a path refers to, if there is one on disk.

    Separate from :func:`detect` so the dispatcher can tell "there is no
    manifest here" from "there is one and it does not parse". Collapsing those
    produces "cannot tell what kind of episode this is" for a file that is
    obviously an episode with a typo in it, and sends the user looking for the
    wrong problem.
    """
    p = Path(path)
    if p.is_dir():
        p = p / "episode.json"
    if p.is_file() and p.suffix.lower() == ".json":
        return p
    return None


def detect(path: str | Path) -> bool:
    """True when this looks like a Potato episode manifest."""
    p = manifest_path(path)
    if p is None:
        return False
    try:
        with open(p, "r", encoding="utf-8") as fh:
            head = json.load(fh)
    except (OSError, ValueError):
        return False
    return isinstance(head, dict) and ("streams" in head or "series" in head)


def read(path: str | Path, media_prefix: str = "") -> Episode:
    """Read a manifest into an :class:`Episode`."""
    p = Path(path)
    if p.is_dir():
        p = p / "episode.json"
    try:
        with open(p, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except OSError as err:
        raise EpisodeError(f"cannot read {p}: {err}") from err
    except ValueError as err:
        raise EpisodeError(f"{p.name} is not valid JSON: {err}") from err

    if not isinstance(raw, dict):
        raise EpisodeError(
            f"{p.name} holds a {type(raw).__name__}, not an episode object")

    series = []
    for entry in raw.get("series", []) or []:
        if not isinstance(entry, dict) or "values" not in entry:
            continue
        series.append(Series(
            name=str(entry.get("name") or f"series_{len(series)}"),
            values=[_number(v) for v in entry["values"]],
            unit=str(entry.get("unit") or ""),
            group=str(entry.get("group") or ""),
            minimum=_optional_number(entry.get("min")),
            maximum=_optional_number(entry.get("max")),
        ))

    streams = []
    for entry in raw.get("streams", []) or []:
        if not isinstance(entry, dict) or not entry.get("url"):
            continue
        streams.append(Stream(
            name=str(entry.get("name") or f"stream_{len(streams)}"),
            url=_join(media_prefix, str(entry["url"])),
            kind=str(entry.get("kind") or ""),
            width=int(entry.get("width") or 0),
            height=int(entry.get("height") or 0),
        ))

    num_frames = int(raw.get("num_frames") or 0)
    if not num_frames:
        num_frames = max((len(s.values) for s in series), default=0)

    return Episode(
        episode_id=str(raw.get("episode_id") or p.stem),
        num_frames=num_frames,
        fps=float(raw.get("fps") or 30.0),
        streams=streams,
        series=series,
        instruction=str(raw.get("instruction") or ""),
        metadata=raw.get("metadata") or {},
        source_format="potato_episode",
    )


def _join(prefix: str, url: str) -> str:
    """
    Prefix a relative stream URL, leaving absolute ones alone.

    A manifest can name a path inside the media directory or a full URL; only
    the first needs a prefix, and prefixing the second produces a URL that
    404s in a way that looks like a missing file rather than a mangled path.
    """
    if not prefix or url.startswith(("http://", "https://", "/")):
        return url
    return f"{prefix.rstrip('/')}/{url.lstrip('/')}"


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        # NaN, not 0: a missing sample is not a measurement of zero, and the
        # lane draws a gap rather than a line through the origin.
        return float("nan")


def _optional_number(value: Any):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def write(episode: Episode, path: str | Path) -> Path:
    """
    Write an episode back out as a manifest.

    Used by the converters, so a LeRobot or HDF5 episode can be turned into
    something that opens without its original dependency.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {
        "episode_id": episode.episode_id,
        "fps": episode.fps,
        "num_frames": episode.num_frames,
        "instruction": episode.instruction,
        "streams": [s.to_json() for s in episode.streams],
        "series": [{"name": s.name, "unit": s.unit, "group": s.group,
                    "values": s.values} for s in episode.series],
        "metadata": episode.metadata,
    }
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return p
