"""
The one shape every rollout reader produces.

## Time is shared, frames are what gets quoted

The panels are frame-locked, so there is exactly one clock and every stream is
seeked to it. A break-point is stored in **seconds**, because that is what the
video element exposes and what `iaa/rollouts.py` matches on, and displayed as
a frame index, because "the physics breaks at frame 47" is the sentence a
researcher writes down and checks against the tensor.

That conversion happens in one place, :meth:`RolloutSet.frame_at`, for the same
reason :class:`~potato.episodes.models.Episode` centralises its own: a boundary
converted in two places drifts against the data it describes.

## Streams of different lengths are a finding, not a detail

Rollouts of the same starting state should be the same length; when they are
not, it is usually the generation pipeline truncating on a failure — which is
precisely the signal the annotation is trying to capture, so it must not be
silently smoothed over. The set takes the longest duration as its timeline and
:meth:`RolloutSet.validate` says so.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


class RolloutError(RuntimeError):
    """A rollout set could not be read. The message names the next action."""


#: Roles a stream can play. `real` is the ground-truth recording; `model` is a
#: generated rollout; `counterfactual` is a rollout under an intervention.
#: Anything else is accepted and passed through — a benchmark with a
#: `retrieval` or `ablation` arm should not have to lie about it — but these
#: three drive behaviour: `real` is never a preference winner by default, and
#: `counterfactual` is what the counterfactual layer asks about.
KNOWN_ROLES = ("real", "model", "counterfactual")


@dataclass
class RolloutStream:
    """One video in the set: the recording, or one model's attempt at it."""

    #: Stable identity. **This is what annotations reference** — never the
    #: panel index, which is shuffled per annotator, and never the display
    #: name, which is hidden under blinding.
    stream_id: str
    url: str
    #: What a non-blinded annotator sees. Usually the generator's name.
    name: str = ""
    role: str = "model"
    fps: float = 0.0
    num_frames: int = 0
    duration: float = 0.0
    #: Free-form; a benchmark's checkpoint id, sampling settings, seed.
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "url": self.url,
            "name": self.name or self.stream_id,
            "role": self.role,
            "fps": self.fps,
            "num_frames": self.num_frames,
            "duration": self.duration,
            "metadata": self.metadata,
        }


@dataclass
class RolloutSet:
    """Several rollouts of one scenario, on one timeline."""

    set_id: str
    streams: List[RolloutStream] = field(default_factory=list)
    #: What the model was asked to continue or generate.
    prompt: str = ""
    #: For counterfactual pairs: what was changed partway through, and when.
    #: Without both, "is this divergence plausible?" is unanswerable — the
    #: annotator has to know what intervention they are judging against.
    intervention: str = ""
    intervention_t: Optional[float] = None
    fps: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    source_format: str = ""

    @property
    def duration(self) -> float:
        """
        The timeline's length: the longest stream.

        Not the shortest. Truncating to the shortest would hide the tail of a
        rollout that ran longer, and a rollout that keeps going after the real
        recording ends is exactly where drift and appearance collapse show up.
        """
        return max((s.duration for s in self.streams), default=0.0)

    @property
    def effective_fps(self) -> float:
        """
        The rate frame-stepping uses.

        The declared set rate wins; otherwise the streams' own, and when they
        disagree the *lowest*, so a step is always at least one frame in every
        panel. Stepping at the highest rate would leave the slower streams on
        the same frame for several presses, which reads as the control being
        broken.
        """
        if self.fps > 0:
            return self.fps
        rates = [s.fps for s in self.streams if s.fps > 0]
        return min(rates) if rates else 0.0

    def frame_at(self, seconds: float) -> int:
        """Nearest frame to a timestamp. The only place time becomes frames."""
        fps = self.effective_fps
        if fps <= 0:
            return 0
        return max(0, int(round(seconds * fps)))

    def stream(self, stream_id: str) -> Optional[RolloutStream]:
        for s in self.streams:
            if s.stream_id == stream_id:
                return s
        return None

    def validate(self) -> List[str]:
        """
        Problems worth telling the annotator about, rather than raising on.

        All three of these leave a usable interface, and all three change how
        the annotation should be read, so they belong on screen and not in a
        log nobody opens.
        """
        issues: List[str] = []
        if len(self.streams) < 2:
            issues.append(
                "a rollout set needs at least two streams to compare; this one "
                f"has {len(self.streams)}")

        durations = [s.duration for s in self.streams if s.duration > 0]
        if len(durations) >= 2:
            spread = max(durations) - min(durations)
            # One frame of slack: encoders round the last frame's duration and
            # a set flagged for a 33 ms difference would be flagged always.
            tolerance = (1.0 / self.effective_fps) if self.effective_fps else 0.05
            if spread > tolerance:
                issues.append(
                    f"streams differ in length by {spread:.2f} s "
                    f"({min(durations):.2f}–{max(durations):.2f} s). The "
                    f"timeline runs to the longest; a short rollout is often a "
                    f"generation that terminated early, which is itself worth "
                    f"annotating.")

        rates = {round(s.fps, 3) for s in self.streams if s.fps > 0}
        if len(rates) > 1:
            issues.append(
                f"streams report different frame rates ({sorted(rates)}); "
                f"frame numbers are quoted at {self.effective_fps:g} fps.")

        return issues

    def to_json(self, order: Optional[Sequence[str]] = None,
                blind: bool = False) -> Dict[str, Any]:
        """
        The manifest the browser receives.

        ``order`` is the per-annotator panel order — a list of stream ids. It
        is applied here rather than in the client so that the shuffle is
        computed once, server-side, from data the client cannot see; a client
        that shuffled for itself would reshuffle on every reload and the
        annotator's second look would disagree with their first.

        ``blind`` replaces the display name with a positional letter. The
        ``stream_id`` still travels, because that is what annotations
        reference — the blinding is of the *label*, not of the identity, and
        pretending otherwise would mean unblinding could not be undone at
        analysis time.
        """
        ordered = _apply_order(self.streams, order)
        payload = []
        for index, stream in enumerate(ordered):
            entry = stream.to_json()
            entry["position"] = index
            if blind:
                entry["name"] = _blind_label(index)
                # The role leaks the identity — "real" is the ground truth and
                # every annotator knows it — so under blinding it collapses to
                # the one distinction the interface still needs.
                entry["role"] = ("counterfactual"
                                 if stream.role == "counterfactual" else "hidden")
            payload.append(entry)

        return {
            "set_id": self.set_id,
            "prompt": self.prompt,
            "intervention": self.intervention,
            "intervention_t": self.intervention_t,
            "fps": self.effective_fps,
            "duration": self.duration,
            "num_frames": self.frame_at(self.duration),
            "blind": bool(blind),
            "source_format": self.source_format,
            "streams": payload,
            "metadata": self.metadata,
            "warnings": self.validate(),
        }


def _blind_label(index: int) -> str:
    """A, B, ... Z, AA, AB — so a 30-way comparison still has unique labels."""
    label = ""
    n = index
    while True:
        label = chr(ord("A") + (n % 26)) + label
        n = n // 26 - 1
        if n < 0:
            return label


def _apply_order(streams: Sequence[RolloutStream],
                 order: Optional[Sequence[str]]) -> List[RolloutStream]:
    """
    Reorder streams by id, keeping anything the order did not mention.

    An order computed against a stale set — a stream added since — must not
    drop the new stream. Silently showing three panels when the item has four
    is unrecoverable from the stored annotation, because nothing records that
    the fourth was never on screen.
    """
    if not order:
        return list(streams)
    by_id = {s.stream_id: s for s in streams}
    out = [by_id.pop(sid) for sid in order if sid in by_id]
    out.extend(s for s in streams if s.stream_id in by_id)
    return out


def stable_order(stream_ids: Sequence[str], key: str) -> List[str]:
    """
    A per-annotator panel order that is the same every time it is computed.

    Sorting by a keyed hash rather than seeding a shuffle, because the property
    that matters is reproducibility from ``(key, ids)`` alone — no PRNG state,
    no dependence on the language's shuffle implementation, and the same answer
    from the route, from a test, and from an analysis script months later.

    Adding a stream perturbs the order of the others, which is fine: the order
    only has to be stable for a given set, and a set does not gain streams
    mid-study.
    """
    def rank(stream_id: str) -> str:
        digest = hashlib.sha256(
            f"{key}\x00{stream_id}".encode("utf-8")).hexdigest()
        return digest
    return sorted(stream_ids, key=rank)


_SAFE_ID = re.compile(r"[^A-Za-z0-9_.:-]+")


def slugify_stream_id(raw: str) -> str:
    """
    A stream id safe to put in a DOM id and a JSON key.

    Ids come from config field names and manifest keys, so they are usually
    already tame; the ones that are not would otherwise break a CSS selector at
    render time rather than at load time, which is a much worse place to find
    out.
    """
    cleaned = _SAFE_ID.sub("-", str(raw)).strip("-")
    return cleaned or "stream"
