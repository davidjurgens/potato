"""
Writing episode annotations back out.

Two forms, because the common case and the tidy case are different cases.

**A JSONL sidecar** keyed by ``(episode_id, frame_index)`` is the default, and
the reason is practical: the dataset you annotated is usually read-only. It is
a public HuggingFace repo, or a shared scratch mount, or a 400 GB tree nobody
wants a second copy of. A sidecar sits beside it, is a few kilobytes, and can
be regenerated whenever the annotations change without touching the source.

**Appending columns to LeRobot parquet** is offered for the case where the
dataset really is yours and downstream tooling expects one file. It rewrites
the per-episode parquet, which is why it is not the default.

## Frames, not seconds

The timeline stores seconds because that is what an annotator reads. The export
converts to **frame indices**, because that is what a training pipeline joins
on: `dataset[i]` is a frame, and a phase label in seconds has to be rounded
against an fps the consumer has to go and find. Doing it once, here, with the
fps the manifest actually carried, removes that step and the chance of getting
it wrong.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from potato.episodes.models import Episode, EpisodeError

logger = logging.getLogger(__name__)


def phases_to_frames(phases: Sequence[Dict[str, Any]], fps: float,
                     num_frames: int) -> List[Optional[str]]:
    """
    One phase label per frame, or None where no phase covers it.

    None, not a "none" string or the previous label: a gap in the segmentation
    is a real state (the annotator did not label that stretch) and filling it
    forward invents a label they never gave.

    Boundaries are half-open — a segment covers `[start, end)` — so two
    adjacent phases do not both claim the frame between them. That single frame
    of double-labelling is invisible in a plot and produces a duplicated row in
    every join downstream.
    """
    labels: List[Optional[str]] = [None] * max(0, num_frames)
    if not fps or num_frames <= 0:
        return labels
    for phase in phases:
        try:
            start = int(round(float(phase["start"]) * fps))
            end = int(round(float(phase["end"]) * fps))
        except (KeyError, TypeError, ValueError):
            continue
        label = phase.get("label")
        for frame in range(max(0, start), min(num_frames, end)):
            labels[frame] = label
    return labels


def reward_to_frames(points: Sequence[Dict[str, Any]], fps: float,
                     num_frames: int) -> List[Optional[float]]:
    """
    The drawn reward curve resampled per frame, None outside its range.

    Uses the same linear interpolation the timeline drew and the agreement
    statistics score, so the exported numbers are the ones the annotator saw.
    """
    from potato.server_utils.iaa.episodes import reward_at

    ordered = sorted(
        ({"t": float(p["t"]), "value": float(p["value"])}
         for p in points if "t" in p and "value" in p),
        key=lambda p: p["t"])
    out: List[Optional[float]] = [None] * max(0, num_frames)
    if not ordered or not fps:
        return out
    for frame in range(num_frames):
        out[frame] = reward_at(ordered, frame / fps)
    return out


def annotation_rows(episode_id: str, annotation: Dict[str, Any],
                    fps: float, num_frames: int) -> List[Dict[str, Any]]:
    """
    One row per frame, ready for JSONL.

    Rows where nothing was annotated are still emitted, with nulls. A sidecar
    with holes forces every consumer to decide what a missing frame means, and
    they will not all decide the same thing.
    """
    phases = phases_to_frames(annotation.get("phases") or [], fps, num_frames)
    rewards = reward_to_frames(annotation.get("reward") or [], fps, num_frames)
    outcome = annotation.get("outcome") or {}

    rows = []
    for frame in range(num_frames):
        rows.append({
            "episode_id": episode_id,
            "frame_index": frame,
            "timestamp": round(frame / fps, 6) if fps else None,
            "phase": phases[frame],
            "progress_reward": rewards[frame],
            # Episode-level fields repeat on every row rather than living in a
            # second file: a sidecar that needs a join to be usable is a
            # sidecar people write their own script around.
            "outcome": outcome.get("result") or None,
            "failure_cause": outcome.get("cause") or None,
        })
    return rows


def write_jsonl(rows: Iterable[Dict[str, Any]], path: str | Path) -> Path:
    """Write rows as JSON Lines. The source dataset is not touched."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return p


def export_sidecar(annotations: Dict[str, Dict[str, Any]],
                   episodes: Dict[str, Episode],
                   path: str | Path) -> Path:
    """
    A JSONL sidecar for a whole project.

    ``annotations`` maps episode id to the parsed annotation blob;
    ``episodes`` maps the same ids to the episodes they were drawn on, which is
    where fps and frame count come from. An annotation whose episode is missing
    is **skipped with a warning** rather than exported against a guessed fps —
    a phase boundary converted with the wrong frame rate is wrong in a way
    nothing downstream can detect.
    """
    rows: List[Dict[str, Any]] = []
    skipped = []
    for episode_id, annotation in sorted(annotations.items()):
        episode = episodes.get(episode_id)
        if episode is None:
            skipped.append(episode_id)
            continue
        rows.extend(annotation_rows(episode_id, annotation,
                                    episode.fps, episode.num_frames))
    if skipped:
        logger.warning(
            "Skipped %d annotation(s) with no matching episode (%s). Their "
            "frame indices cannot be computed without the episode's fps.",
            len(skipped), ", ".join(skipped[:5]))
    return write_jsonl(rows, path)


def append_to_lerobot(root: str | Path, episode_index: int,
                      annotation: Dict[str, Any],
                      fps: float, num_frames: int) -> Path:
    """
    Rewrite a LeRobot episode's parquet with the annotation columns added.

    Offered rather than defaulted: this **modifies the dataset**, and the
    common case is a read-only public one. It refuses rather than truncating
    when the annotation and the table disagree about the frame count, because
    a silently short column is a misalignment that survives into training.
    """
    from potato.episodes.lerobot import _data_path, read_info

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as err:
        raise EpisodeError(
            "Writing LeRobot parquet needs pyarrow: `pip install pyarrow`. "
            "The JSONL sidecar needs no dependency and does not modify the "
            "dataset."
        ) from err

    root = Path(root)
    path = _data_path(root, read_info(root), episode_index)
    table = pq.read_table(path)

    if table.num_rows != num_frames:
        raise EpisodeError(
            f"{path.name} has {table.num_rows} rows but the annotation covers "
            f"{num_frames} frames. Refusing to write a misaligned column — "
            f"check that the episode index is the one that was annotated.")

    phases = phases_to_frames(annotation.get("phases") or [], fps, num_frames)
    rewards = reward_to_frames(annotation.get("reward") or [], fps, num_frames)
    outcome = (annotation.get("outcome") or {}).get("result") or None

    table = table.append_column(
        "annotation.phase", pa.array(phases, type=pa.string()))
    table = table.append_column(
        "annotation.progress_reward", pa.array(rewards, type=pa.float32()))
    table = table.append_column(
        "annotation.outcome", pa.array([outcome] * num_frames,
                                       type=pa.string()))
    pq.write_table(table, path)
    return path
