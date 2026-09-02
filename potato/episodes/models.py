"""
The one shape every episode reader produces.

Frame index is the primary key, not time. Robot logs are recorded per control
step and the cameras are keyed to those steps; deriving a timestamp from
``frame / fps`` is exact, while deriving a frame from a timestamp is not, and a
phase boundary stored in seconds drifts against the data it describes.

Time is still what the annotator sees — a timeline in frames is unreadable —
so :meth:`Episode.seconds` does the conversion in one place.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


class EpisodeError(RuntimeError):
    """An episode could not be read. The message names the next action."""


@dataclass
class Stream:
    """One video stream: a camera on the robot, or a fixed view of the scene."""

    name: str
    url: str
    #: "wrist", "overhead", "third_person", or whatever the source called it.
    kind: str = ""
    width: int = 0
    height: int = 0

    def to_json(self) -> Dict[str, Any]:
        return {"name": self.name, "url": self.url, "kind": self.kind,
                "width": self.width, "height": self.height}


@dataclass
class Series:
    """
    One numeric channel, one value per frame.

    A multi-dimensional signal (seven joint positions) becomes seven Series
    rather than one Series of vectors. The timeline draws lanes, an annotator
    reads one line at a time, and the agreement statistics are per-channel —
    all three want the flat form, and flattening once here beats each of them
    doing it differently.
    """

    name: str
    values: List[float]
    #: What the source called the unit. NOT converted — see the package note.
    unit: str = ""
    group: str = ""
    #: Set when the source says so. Used only for the lane's default y-range.
    minimum: Optional[float] = None
    maximum: Optional[float] = None

    def range(self) -> "tuple[float, float]":
        """The y-range to draw, ignoring non-finite samples."""
        if self.minimum is not None and self.maximum is not None:
            return (float(self.minimum), float(self.maximum))
        finite = [v for v in self.values if _finite(v)]
        if not finite:
            return (0.0, 1.0)
        lo, hi = min(finite), max(finite)
        if hi <= lo:
            # A constant channel is a real and informative state — a gripper
            # that never opens. Drawing it as a flat line in the middle says
            # that; a zero-height lane says nothing.
            return (lo - 0.5, lo + 0.5)
        return (lo, hi)

    def to_json(self) -> Dict[str, Any]:
        lo, hi = self.range()
        return {"name": self.name, "unit": self.unit, "group": self.group,
                "values": self.values, "min": lo, "max": hi}


@dataclass
class Episode:
    """A demonstration: streams, series, and what the robot was asked to do."""

    episode_id: str
    num_frames: int
    fps: float = 30.0
    streams: List[Stream] = field(default_factory=list)
    series: List[Series] = field(default_factory=list)
    #: The language instruction, where the dataset carries one.
    instruction: str = ""
    #: Whatever the source recorded that does not fit above, verbatim.
    metadata: Dict[str, Any] = field(default_factory=dict)
    source_format: str = ""

    @property
    def duration(self) -> float:
        return self.num_frames / self.fps if self.fps else 0.0

    def seconds(self, frame: int) -> float:
        """Timestamp of a frame. The only place frames become time."""
        return frame / self.fps if self.fps else 0.0

    def frame_at(self, seconds: float) -> int:
        """
        Nearest frame to a timestamp, clamped into range.

        Rounds rather than truncates: a click at 1.999 s on a 1 fps episode
        means frame 2, and truncation would silently place every boundary one
        frame early.
        """
        if not self.fps or self.num_frames <= 0:
            return 0
        frame = int(round(seconds * self.fps))
        return max(0, min(self.num_frames - 1, frame))

    def series_named(self, name: str) -> Optional[Series]:
        for s in self.series:
            if s.name == name:
                return s
        return None

    def validate(self) -> List[str]:
        """
        Problems worth telling the user about, rather than raising on.

        A ragged series is the common real defect — a log that dropped samples,
        or a reader that mismatched a column — and it produces a timeline where
        the lanes disagree about where frame 400 is. Reporting it beats both
        raising (the episode is still mostly usable) and silence.
        """
        issues = []
        for s in self.series:
            if len(s.values) != self.num_frames:
                issues.append(
                    f"series '{s.name}' has {len(s.values)} samples but the "
                    f"episode has {self.num_frames} frames")
        if self.num_frames <= 0:
            issues.append("episode has no frames")
        if not self.fps:
            issues.append("fps is zero, so no timeline can be drawn")
        return issues

    def to_json(self, max_samples: int = 4000) -> Dict[str, Any]:
        """
        The manifest the browser receives.

        Series are downsampled to ``max_samples``: a ten-minute episode at
        50 Hz is 30,000 samples per channel, and a fourteen-channel arm is
        420,000 numbers to draw into lanes a few hundred pixels wide. The
        downsampling is min/max-preserving so a one-frame spike — which is
        exactly what a collision looks like — is not averaged away.
        """
        return {
            "episode_id": self.episode_id,
            "num_frames": self.num_frames,
            "fps": self.fps,
            "duration": self.duration,
            "instruction": self.instruction,
            "source_format": self.source_format,
            "streams": [s.to_json() for s in self.streams],
            "series": [_series_json(s, self.num_frames, max_samples)
                       for s in self.series],
            "metadata": self.metadata,
            "warnings": self.validate(),
        }


def _series_json(series: Series, num_frames: int,
                 max_samples: int) -> Dict[str, Any]:
    payload = series.to_json()
    payload["values"] = downsample(series.values, max_samples)
    payload["num_frames"] = num_frames
    return payload


def downsample(values: Sequence[float], target: int) -> List[float]:
    """
    Reduce a series to about ``target`` samples, keeping the extremes.

    Each output bucket contributes both its minimum and its maximum, in the
    order they occur. Plain striding drops the peak between two kept samples,
    and a one-frame force spike is the single most diagnostic event in a
    manipulation log — averaging or skipping it is how a collision becomes
    invisible in the very lane drawn to show it.
    """
    n = len(values)
    if target <= 0 or n <= target:
        return [float(v) for v in values]

    # Two samples per bucket, so aim for half as many buckets as the target.
    buckets = max(1, target // 2)
    out: List[float] = []
    for b in range(buckets):
        start = (b * n) // buckets
        end = max(start + 1, ((b + 1) * n) // buckets)
        chunk = values[start:end]
        finite = [v for v in chunk if _finite(v)]
        if not finite:
            out.append(float("nan"))
            continue
        lo, hi = min(finite), max(finite)
        first_extreme_is_min = chunk.index(lo) <= chunk.index(hi)
        out.append(float(lo if first_extreme_is_min else hi))
        if hi != lo:
            out.append(float(hi if first_extreme_is_min else lo))
    return out


def _finite(v: Any) -> bool:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return not (math.isnan(f) or math.isinf(f))


def flatten_vector_column(name: str, rows: Sequence[Sequence[float]],
                          names: Optional[Sequence[str]] = None,
                          unit: str = "") -> List[Series]:
    """
    A column of vectors into one Series per component.

    ``names`` supplies per-component labels where the dataset has them —
    ``joint_0`` tells an annotator nothing, ``shoulder_pan`` tells them where to
    look. Falls back to indices, which is honest about not knowing.
    """
    if not rows:
        return []
    width = max(len(r) for r in rows)
    out = []
    for i in range(width):
        label = (names[i] if names and i < len(names) and names[i]
                 else f"{name}[{i}]")
        values = [float(r[i]) if i < len(r) and _finite(r[i]) else float("nan")
                  for r in rows]
        out.append(Series(name=label, values=values, unit=unit, group=name))
    return out
