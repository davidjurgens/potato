"""
HDF5 episodes: the RoboMimic and ALOHA conventions.

Two layouts dominate, and they disagree about almost everything:

**ALOHA / ACT** — one file per episode:

    /observations/qpos          (T, 14)   joint positions
    /observations/qvel          (T, 14)
    /observations/images/<cam>  (T, H, W, 3)  frames, in the file
    /action                     (T, 14)

**RoboMimic** — one file for a whole dataset:

    /data/demo_0/obs/<key>      (T, ...)
    /data/demo_0/actions        (T, A)
    /data/demo_0/rewards        (T,)
    /data/demo_0/dones          (T,)

So the reader detects which it is rather than requiring the caller to say. A
wrong guess does not error — it finds no arrays and reports an empty episode,
which reads as "the file is broken" when the file is fine.

## Images stay where they are

Neither layout stores video; ALOHA stores raw frames as an array. Potato does
**not** transcode them here. Extracting 500 frames of 480x640 RGB into an MP4
is an ffmpeg job with its own failure modes, and doing it inside a reader would
make opening an episode arbitrarily slow with no progress indication. The
episode reports which image datasets exist, and `potato episodes convert`
extracts them as a separate, visible step.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from potato.episodes.models import (Episode, EpisodeError, Series,
                                    flatten_vector_column)

logger = logging.getLogger(__name__)

#: Datasets that are flags rather than signals. Kept, because "the episode
#: terminated at frame 380" is exactly what a phase annotator wants to see.
FLAG_KEYS = {"dones", "done", "success", "terminated", "truncated"}


def detect(path: str | Path) -> bool:
    p = Path(path)
    return p.is_file() and p.suffix.lower() in (".hdf5", ".h5")


def _require_h5py():
    try:
        import h5py
    except ImportError as err:
        raise EpisodeError(
            "Reading HDF5 episodes needs h5py: `pip install h5py`."
        ) from err
    return h5py


def list_episodes(path: str | Path) -> List[str]:
    """
    The demo keys in a RoboMimic file, or a single entry for an ALOHA file.

    Returns strings rather than indices because RoboMimic keys are `demo_0`,
    `demo_12`, and are not necessarily contiguous — a filtered dataset has
    holes, and treating the key as an index reads the wrong demonstration.
    """
    h5py = _require_h5py()
    with h5py.File(str(path), "r") as fh:
        if "data" in fh and hasattr(fh["data"], "keys"):
            return sorted(fh["data"].keys(), key=_demo_sort_key)
        return [""]


def _demo_sort_key(key: str):
    tail = key.rsplit("_", 1)[-1]
    return (0, int(tail)) if tail.isdigit() else (1, key)


def read(path: str | Path, demo: str = "", fps: float = 30.0,
         media_prefix: str = "") -> Episode:
    """Read one demonstration out of an HDF5 file."""
    h5py = _require_h5py()
    p = Path(path)

    try:
        handle = h5py.File(str(p), "r")
    except OSError as err:
        raise EpisodeError(f"cannot open {p.name}: {err}") from err

    with handle as fh:
        if "data" in fh and hasattr(fh["data"], "keys"):
            keys = sorted(fh["data"].keys(), key=_demo_sort_key)
            if demo and demo not in keys:
                raise EpisodeError(
                    f"{p.name} has no demonstration '{demo}'. Present: "
                    f"{', '.join(keys[:8])}"
                    + (" …" if len(keys) > 8 else ""))
            chosen = demo or (keys[0] if keys else "")
            if not chosen:
                raise EpisodeError(f"{p.name} contains no demonstrations")
            group = fh["data"][chosen]
            episode_id = chosen
            layout = "robomimic"
        else:
            group = fh
            episode_id = p.stem
            layout = "aloha"

        series: List[Series] = []
        images: List[str] = []
        _walk(group, "", series, images)

        num_frames = max((len(s.values) for s in series), default=0)
        attrs = {k: _scalar(v) for k, v in dict(group.attrs).items()}
        fps_value = float(attrs.get("fps") or attrs.get("frame_rate") or fps)

    if images:
        logger.info(
            "%s carries %d image dataset(s) (%s). Frames stay in the file; "
            "run `potato episodes convert` to extract them as video.",
            p.name, len(images), ", ".join(images[:4]))

    return Episode(
        episode_id=episode_id,
        num_frames=num_frames,
        fps=fps_value,
        streams=[],
        series=series,
        instruction=str(attrs.get("language_instruction")
                        or attrs.get("instruction") or ""),
        metadata={"layout": layout, "image_datasets": images, **attrs},
        source_format=f"hdf5_{layout}",
    )


def _walk(group, prefix: str, series: List[Series], images: List[str],
          depth: int = 0) -> None:
    """
    Collect every per-frame numeric dataset, recursing into subgroups.

    Depth-limited: an HDF5 file can nest arbitrarily, and a pathological one
    would otherwise walk forever through a self-referential link.
    """
    if depth > 6:
        return
    for key in group.keys():
        item = group[key]
        name = f"{prefix}{key}" if not prefix else f"{prefix}/{key}"
        if hasattr(item, "keys"):
            _walk(item, name, series, images, depth + 1)
            continue

        shape = getattr(item, "shape", ())
        if not shape:
            continue
        if len(shape) >= 3:
            # (T, H, W) or (T, H, W, C): frames, not a signal.
            images.append(name)
            continue

        try:
            values = item[()]
        except Exception as err:                      # h5py raises broadly
            logger.info("skipping %s: %s", name, err)
            continue

        rows = [_row(v) for v in values]
        if rows and isinstance(rows[0], list):
            series.extend(flatten_vector_column(name, rows))
        else:
            series.append(Series(name=name,
                                 values=[_number(v) for v in rows],
                                 group=name.split("/")[0]))


def _row(value: Any):
    if hasattr(value, "tolist"):
        out = value.tolist()
        return out if isinstance(out, list) else out
    return value


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _scalar(value: Any) -> Any:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value
