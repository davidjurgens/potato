"""
LeRobot v2: HuggingFace parquet beside per-episode video.

The de-facto standard for open robot demonstration data, and the format most
new datasets ship in. A dataset directory looks like:

    meta/info.json                          fps, features, path templates
    meta/tasks.jsonl                        task_index -> language instruction
    data/chunk-000/episode_000000.parquet   one row per frame
    videos/chunk-000/observation.images.wrist/episode_000000.mp4

``info.json`` carries `data_path` and `video_path` **templates** with
`{episode_chunk}`, `{episode_index}` and `{video_key}` placeholders. Reading the
templates rather than assuming the layout matters: chunk size is configurable
and a dataset with more than 1000 episodes really does put episode 1000 in
`chunk-001`, so a hardcoded path silently reads the wrong file — or, worse, the
right file for episode 0 and nothing thereafter.

## Columns

Per-frame columns are declared in `info.json["features"]`. The conventional set:

| Column | Meaning |
|---|---|
| `observation.state` | Proprioception — joint positions, gripper |
| `action` | Commanded action, absolute or delta (the dataset does not say) |
| `next.reward` | Scalar reward |
| `next.done` / `next.success` | Termination flags |
| `timestamp`, `frame_index`, `episode_index`, `task_index` | Indices |

Vector columns are flattened to one series per component, named from
`features[col]["names"]` when the dataset provides them. `joint_0` tells an
annotator nothing; `shoulder_pan` tells them where to look.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from potato.episodes.models import (Episode, EpisodeError, Series, Stream,
                                    flatten_vector_column)

logger = logging.getLogger(__name__)

#: Columns that are bookkeeping rather than signal. Drawing a lane for
#: `frame_index` — a perfect straight line by construction — wastes the only
#: vertical space the annotator has.
INDEX_COLUMNS = {"frame_index", "episode_index", "index", "task_index",
                 "timestamp"}


def detect(path: str | Path) -> bool:
    """True for a directory that looks like a LeRobot v2 dataset."""
    p = Path(path)
    return (p / "meta" / "info.json").is_file()


def read_info(root: str | Path) -> Dict[str, Any]:
    p = Path(root) / "meta" / "info.json"
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as err:
        raise EpisodeError(f"cannot read {p}: {err}") from err
    except ValueError as err:
        raise EpisodeError(f"{p} is not valid JSON: {err}") from err


def list_episodes(root: str | Path) -> List[int]:
    """Episode indices present on disk, in order."""
    info = read_info(root)
    total = int(info.get("total_episodes") or 0)
    if total:
        return list(range(total))

    # No count in the metadata: fall back to what is actually there rather
    # than reporting an empty dataset, which reads as "nothing imported".
    found = sorted(
        int(p.stem.split("_")[-1])
        for p in Path(root).glob("data/**/episode_*.parquet"))
    return found


def read(root: str | Path, episode_index: int = 0,
         media_prefix: str = "") -> Episode:
    """Read one episode of a LeRobot v2 dataset."""
    root = Path(root)
    info = read_info(root)
    fps = float(info.get("fps") or 30.0)
    features = info.get("features") or {}

    table = _read_parquet(_data_path(root, info, episode_index))
    num_frames = len(next(iter(table.values()), []))

    series: List[Series] = []
    for column, values in table.items():
        if column in INDEX_COLUMNS:
            continue
        spec = features.get(column) or {}
        unit = str(spec.get("unit") or "")
        if values and isinstance(values[0], (list, tuple)):
            series.extend(flatten_vector_column(
                column, values, names=spec.get("names"), unit=unit))
        else:
            numeric = [_number(v) for v in values]
            if any(n == n for n in numeric):     # at least one finite value
                series.append(Series(name=column, values=numeric, unit=unit,
                                     group=column))

    streams = []
    for key, spec in features.items():
        if str(spec.get("dtype") or "") != "video" and "image" not in key:
            continue
        url = _video_path(root, info, episode_index, key)
        if url is None:
            continue
        shape = spec.get("shape") or []
        streams.append(Stream(
            name=key.split(".")[-1],
            url=_relative_url(root, url, media_prefix),
            kind=_kind_of(key),
            height=int(shape[0]) if len(shape) > 1 else 0,
            width=int(shape[1]) if len(shape) > 1 else 0,
        ))

    return Episode(
        episode_id=f"episode_{episode_index:06d}",
        num_frames=num_frames,
        fps=fps,
        streams=streams,
        series=series,
        instruction=_instruction(root, table),
        metadata={"robot_type": info.get("robot_type", ""),
                  "codebase_version": info.get("codebase_version", "")},
        source_format="lerobot_v2",
    )


def _data_path(root: Path, info: Dict[str, Any], index: int) -> Path:
    template = info.get("data_path") or (
        "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet")
    chunk_size = int(info.get("chunks_size") or 1000)
    path = root / template.format(episode_chunk=index // chunk_size,
                                  episode_index=index)
    if not path.is_file():
        raise EpisodeError(
            f"episode {index} is not in this dataset: expected {path}. "
            f"Check the episode index, or that the parquet files were "
            f"downloaded (a `git clone` of a HF dataset without git-lfs "
            f"leaves pointer files behind).")
    return path


def _video_path(root: Path, info: Dict[str, Any], index: int,
                key: str) -> Optional[Path]:
    template = info.get("video_path") or (
        "videos/chunk-{episode_chunk:03d}/{video_key}/"
        "episode_{episode_index:06d}.mp4")
    chunk_size = int(info.get("chunks_size") or 1000)
    path = root / template.format(episode_chunk=index // chunk_size,
                                  episode_index=index, video_key=key)
    if path.is_file():
        return path
    # Missing video is normal for a state-only dataset, and for one where the
    # frames were never downloaded. Neither is an error; the timeline draws
    # the series lanes and says there is no video.
    logger.info("LeRobot: no video for %s at %s", key, path)
    return None


def _relative_url(root: Path, path: Path, media_prefix: str) -> str:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = path.as_posix()
    if not media_prefix:
        return rel
    return f"{media_prefix.rstrip('/')}/{rel}"


def _kind_of(key: str) -> str:
    lowered = key.lower()
    for kind in ("wrist", "overhead", "top", "front", "side", "ego"):
        if kind in lowered:
            return kind
    return ""


def _instruction(root: Path, table: Dict[str, List[Any]]) -> str:
    """
    The language instruction for this episode.

    `meta/tasks.jsonl` maps a task index to text; the per-frame `task_index`
    column says which. An episode with several task indices is a multi-stage
    demonstration, and joining them is more informative than picking the first.
    """
    tasks_file = root / "meta" / "tasks.jsonl"
    if not tasks_file.is_file():
        return ""
    lookup: Dict[int, str] = {}
    try:
        for line in tasks_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            lookup[int(row.get("task_index", -1))] = str(row.get("task", ""))
    except (OSError, ValueError) as err:
        logger.info("LeRobot: could not read tasks.jsonl: %s", err)
        return ""

    indices = table.get("task_index") or []
    seen: List[str] = []
    for raw in indices:
        text = lookup.get(int(raw)) if raw is not None else None
        if text and text not in seen:
            seen.append(text)
    return " → ".join(seen)


def _read_parquet(path: Path) -> Dict[str, List[Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as err:
        raise EpisodeError(
            "Reading LeRobot datasets needs pyarrow: `pip install pyarrow`. "
            "Or convert the episode first with `potato episodes convert`."
        ) from err

    try:
        table = pq.read_table(path)
    except Exception as err:      # pyarrow raises several unrelated types
        raise EpisodeError(f"cannot read {path.name}: {err}") from err
    return {name: table.column(name).to_pylist() for name in table.schema.names}


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")
