"""
Which reader handles a path, and the one entry point everything else calls.

Detection is by **content and layout**, not extension, for the same reason the
point cloud readers do it that way: `.h5` is claimed by half of scientific
computing, and a LeRobot dataset is a directory with no distinguishing suffix
at all.

The dispatch is deliberately small. Adding a format means a `detect` and a
`read` in a new module and one line here — the same shape as the importer,
exporter, schema and display registries, so someone who has added one of those
already knows how to add this.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from potato.episodes.models import Episode, EpisodeError

logger = logging.getLogger(__name__)

#: Name -> (detect, read). Order matters: the first match wins, and the
#: cheapest and most specific check goes first.
_FORMATS: List[str] = ["potato_episode", "lerobot_v2", "hdf5"]


def detect_format(path: str | Path) -> str:
    """
    The format of ``path``, or raise with what was actually looked for.

    RLDS is absent on purpose: it is addressed by dataset *name* through TFDS,
    not by a path on disk, so there is nothing here to sniff.
    """
    from potato.episodes import hdf5, lerobot, simple

    p = Path(path)
    if not p.exists():
        raise EpisodeError(f"{p} does not exist")

    if lerobot.detect(p):
        return "lerobot_v2"
    if simple.detect(p):
        return "potato_episode"
    if hdf5.detect(p):
        return "hdf5"

    # A manifest that exists but does not parse is a different problem from a
    # path we do not recognise, and it deserves the message that names it.
    # Otherwise a typo'd episode.json reports "cannot tell what kind of
    # episode this is" and the user goes looking for a format issue.
    manifest = simple.manifest_path(p)
    if manifest is not None:
        simple.read(manifest)          # raises with the real reason
        raise EpisodeError(
            f"{manifest.name} is valid JSON but has neither a 'streams' nor a "
            f"'series' key, so there is nothing to show. See "
            f"docs/annotation-types/embodied/episodes.md for the shape.")

    raise EpisodeError(
        f"cannot tell what kind of episode {p.name} is. Looked for: a "
        f"LeRobot v2 dataset (meta/info.json), a Potato episode manifest "
        f"(episode.json with streams or series), and an HDF5 file "
        f"(.h5/.hdf5). For RLDS/TFDS, pass the dataset name rather than a "
        f"path.")


def read_episode(path: str | Path, *, episode: Any = 0,
                 media_prefix: str = "", fps: float = 30.0) -> Episode:
    """
    Read one episode from any supported source.

    ``episode`` selects within a multi-episode source: an integer index for
    LeRobot, a demo key for RoboMimic HDF5. It is ignored for single-episode
    sources rather than rejected — a config that names an index is not wrong
    just because this particular item happens to hold one episode.
    """
    from potato.episodes import hdf5, lerobot, simple

    fmt = detect_format(path)
    if fmt == "lerobot_v2":
        return lerobot.read(path, episode_index=int(episode or 0),
                            media_prefix=media_prefix)
    if fmt == "potato_episode":
        return simple.read(path, media_prefix=media_prefix)
    if fmt == "hdf5":
        return hdf5.read(path, demo=str(episode or ""), fps=fps,
                         media_prefix=media_prefix)
    raise EpisodeError(f"no reader for format '{fmt}'")


def list_episodes(path: str | Path) -> List[Any]:
    """
    What is inside a multi-episode source.

    Returns `[0]` for a single-episode one, so a caller can loop without a
    special case.
    """
    from potato.episodes import hdf5, lerobot

    fmt = detect_format(path)
    if fmt == "lerobot_v2":
        return list(lerobot.list_episodes(path))
    if fmt == "hdf5":
        return list(hdf5.list_episodes(path))
    return [0]


def supported_formats() -> Dict[str, str]:
    """
    Format name -> what it needs, for the CLI's help and the docs.

    The dependency is part of the answer: "we support RLDS" and "we support
    RLDS if you install TensorFlow" are different claims, and only the second
    one is true.
    """
    from potato.episodes import rlds

    return {
        "potato_episode": "no extra dependency",
        "lerobot_v2": "pyarrow",
        "hdf5": "h5py",
        "rlds": ("tensorflow_datasets"
                 + ("" if rlds.available() else " (not installed)")),
    }
