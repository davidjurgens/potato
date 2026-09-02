"""
Typing dynamics: content-blind keystroke event streams and their summary features.

This module is the data model and feature extractor for keystroke logging on
free-text annotation fields. It is deliberately pure: no Flask, no I/O, no
database. That keeps ``summarize()`` unit-testable against hand-built synthetic
traces, and it means a feature added later can be recomputed from stored streams
rather than requiring re-collection.

Content-blind by construction
-----------------------------
An event records *that* a character was inserted, *when*, *where* in the field,
and what **class** of key produced it — never which character. A stream is enough
to reconstruct timing, pauses, bursts, revisions and paste sizes; it is not
enough to reconstruct the text. See ``docs/advanced/keystroke_logging.md``.

What the features are for
-------------------------
The feature families follow the writing-process literature, where composed and
transcribed/pasted text separate reliably:

- Crossley, Tian, Choi, Holmes & Morris (2024), "Plagiarism Detection Using
  Keystroke Logs", EDM 2024. doi:10.5281/zenodo.12729864 — pause times, insertion
  and deletion counts, product-to-process ratios, bursts, revision, and process
  variance classify authentic vs. transcribed essays at 99% (random forest).
  Authentic writing shows longer pauses, more insertions/deletions, and greater
  variance; transcription is linear and burst-oriented.
- Asher, Gold, Chen & Carvalho (2026), AMPPS 9(1). doi:10.1177/25152459261424723 —
  in crowdsourced samples, the operative signals are pasting into the response
  field and a keystroke count anomalously low relative to response length. That
  second one is ``silent_insert_ratio`` here.
- Chenoweth & Hayes (2001), Written Communication 18(1).
  doi:10.1177/0741088301018001004 — the burst construct.
- Leijten & Van Waes (2013), Written Communication 30(3).
  doi:10.1177/0741088313491692 — the standard keystroke-log measures (Inputlog).
- Conijn, Roeser & van Zaanen (2019), Reading and Writing 32(9).
  doi:10.1007/s11145-019-09953-8 — keystroke features vary by writing task, so
  thresholds cannot be universal.
- Roeser, De Maeyer, Leijten & Van Waes (2021), Reading and Writing.
  doi:10.1007/s11145-021-10203-z — inter-key intervals are a mixture process, so
  fixed pause thresholds and bare summary statistics give biased estimates.

The last two are why this module reports pause counts at *several* thresholds and
both fixed and per-writer burst boundaries, and why :mod:`potato.typing_detect`
calibrates against a project's own population instead of hardcoded constants.
"""

from __future__ import annotations

import base64
import json
import math
import zlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

# --------------------------------------------------------------------------
# Vocabularies
#
# Both are append-only. Codes are persisted inside packed event blobs, so
# reordering or reusing a code would silently reinterpret stored data.
# --------------------------------------------------------------------------

#: Key classes. The class of a keystroke is recorded; the key itself never is.
KEY_CLASSES: List[str] = [
    "unknown",
    "letter",
    "digit",
    "punct",
    "space",
    "enter",
    "bksp",
    "del",
    "nav",      # arrows, home/end, page up/down
    "mod",      # shift/ctrl/alt/meta pressed alone
    "func",     # F-keys, escape, tab
]

#: ``InputEvent.inputType`` values we distinguish. Anything unrecognised maps to
#: ``"other"`` rather than being dropped, so unexpected browser behaviour is
#: visible in the data instead of silently absent.
INPUT_TYPES: List[str] = [
    "other",
    "insertText",
    "insertReplacementText",   # spellcheck / autocorrect substitution
    "insertFromPaste",
    "insertFromDrop",
    "insertCompositionText",   # IME
    "insertLineBreak",
    "insertParagraph",
    "deleteContentBackward",
    "deleteContentForward",
    "deleteWordBackward",
    "deleteWordForward",
    "deleteByCut",
    "deleteByDrag",
    "historyUndo",
    "historyRedo",
    # Synthetic, emitted by the client rather than by the browser:
    "focus",
    "blur",
    "keydown",                 # physical keystroke with no text mutation
]

_KEY_CLASS_CODE = {name: i for i, name in enumerate(KEY_CLASSES)}
_INPUT_TYPE_CODE = {name: i for i, name in enumerate(INPUT_TYPES)}

#: inputTypes that add characters the user did not individually type. These are
#: what ``silent_insert_*`` counts.
EXTERNAL_INSERT_TYPES = frozenset({
    "insertFromPaste",
    "insertFromDrop",
    "insertReplacementText",
})

#: inputTypes that remove text.
DELETE_TYPES = frozenset({
    "deleteContentBackward",
    "deleteContentForward",
    "deleteWordBackward",
    "deleteWordForward",
    "deleteByCut",
    "deleteByDrag",
})

#: Paste sources that are ordinary annotator behaviour rather than evidence of
#: text arriving from off-screen: re-arranging your own draft, or quoting the
#: passage you are annotating. Classified client-side; see
#: ``classifyPasteSource`` in ``static/keystroke_tracker.js``.
LEGITIMATE_PASTE_SOURCES = frozenset({"self", "instance_text"})

#: Default pause thresholds in ms. 2000 ms is the long-standing convention in
#: writing research; the others bracket it so an analysis is not hostage to one
#: arbitrary cut (Roeser et al. 2021).
DEFAULT_PAUSE_THRESHOLDS_MS: List[int] = [500, 1000, 2000, 5000, 10000]

#: A burst ends at a pause longer than this multiple of the writer's own median
#: inter-key interval. Reported alongside the fixed-threshold counts so that
#: within-writer and cross-writer comparisons are both possible.
BURST_IKI_MULTIPLIER = 4.0

#: Inter-key intervals above this are treated as "away", not as typing rhythm,
#: and are excluded from the IKI distribution statistics. Without this a single
#: coffee break dominates the mean and the variance.
MAX_IKI_FOR_RHYTHM_MS = 30_000


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------


@dataclass
class TypingEvent:
    """A single content-blind edit or focus event within one typing session.

    Attributes:
        t_ms: Milliseconds since the start of the session. Relative rather than
            absolute so packed streams delta-encode tightly and so a stream
            carries no wall-clock fingerprint of its own.
        input_type: One of :data:`INPUT_TYPES`.
        key_class: One of :data:`KEY_CLASSES`. ``"unknown"`` for events with no
            originating physical key (paste, drop, IME commit).
        pos: Caret offset within the field when the event was applied. Used to
            tell appending (``pos`` at the end) from going back into the text.
        delta: Change in field length. Positive for insertion, negative for
            deletion, zero for pure navigation or a keystroke that produced no
            text.
        meta: Sparse extras — ``paste_source``, ``blur_ms``, ``dwell_ms``,
            ``is_trusted``, ``composing``. Kept out of the packed columnar arrays
            because it is present on a small minority of events.
    """

    t_ms: int
    input_type: str = "other"
    key_class: str = "unknown"
    pos: int = 0
    delta: int = 0
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "t_ms": self.t_ms,
            "input_type": self.input_type,
            "key_class": self.key_class,
            "pos": self.pos,
            "delta": self.delta,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TypingEvent":
        """Reconstruct from a serialized dictionary.

        Unrecognised ``input_type``/``key_class`` values are coerced to the
        catch-all members rather than raising, so a newer client talking to an
        older server degrades instead of dropping the whole session.
        """
        input_type = data.get("input_type", "other")
        key_class = data.get("key_class", "unknown")
        return cls(
            t_ms=int(data.get("t_ms", 0)),
            input_type=input_type if input_type in _INPUT_TYPE_CODE else "other",
            key_class=key_class if key_class in _KEY_CLASS_CODE else "unknown",
            pos=int(data.get("pos", 0)),
            delta=int(data.get("delta", 0)),
            meta=data.get("meta") or {},
        )


# --------------------------------------------------------------------------
# Packing
#
# One row per session holds the whole stream, so the on-disk shape matters. An
# array of JSON objects is ~10-20x larger than delta-encoded parallel arrays
# under zlib, and the stream is only ever read back wholesale.
# --------------------------------------------------------------------------

#: Bumped whenever the packed layout changes. ``unpack_events`` refuses versions
#: it does not know rather than silently misreading columns.
PACK_VERSION = 1


def pack_events(events: Sequence[TypingEvent]) -> bytes:
    """Pack a session's events into a compact zlib-compressed blob.

    Timestamps and caret positions are delta-encoded against the previous event,
    which is what makes the compression pay off: both are near-monotonic, so the
    deltas are small integers that zlib handles far better than absolute values.
    """
    if not events:
        return b""

    times: List[int] = []
    types: List[int] = []
    classes: List[int] = []
    positions: List[int] = []
    deltas: List[int] = []
    # Sparse: only events that actually carry extras, as [index, meta] pairs.
    metas: List[List[Any]] = []

    prev_t = 0
    prev_pos = 0
    for i, e in enumerate(events):
        times.append(e.t_ms - prev_t)
        prev_t = e.t_ms
        positions.append(e.pos - prev_pos)
        prev_pos = e.pos
        types.append(_INPUT_TYPE_CODE.get(e.input_type, 0))
        classes.append(_KEY_CLASS_CODE.get(e.key_class, 0))
        deltas.append(e.delta)
        if e.meta:
            metas.append([i, e.meta])

    payload = {
        "v": PACK_VERSION,
        "n": len(events),
        "t": times,
        "it": types,
        "kc": classes,
        "p": positions,
        "d": deltas,
        "m": metas,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return zlib.compress(raw, 6)


def unpack_events(blob: Optional[bytes]) -> List[TypingEvent]:
    """Reverse :func:`pack_events`. Returns ``[]`` for empty or absent blobs."""
    if not blob:
        return []

    payload = json.loads(zlib.decompress(blob).decode("utf-8"))
    version = payload.get("v")
    if version != PACK_VERSION:
        raise ValueError(
            f"Unsupported typing event pack version {version!r} "
            f"(this build reads version {PACK_VERSION})"
        )

    n = payload.get("n", 0)
    times = payload.get("t", [])
    types = payload.get("it", [])
    classes = payload.get("kc", [])
    positions = payload.get("p", [])
    deltas = payload.get("d", [])
    metas = {int(idx): meta for idx, meta in payload.get("m", [])}

    events: List[TypingEvent] = []
    t = 0
    pos = 0
    for i in range(n):
        t += times[i]
        pos += positions[i]
        events.append(TypingEvent(
            t_ms=t,
            input_type=INPUT_TYPES[types[i]] if types[i] < len(INPUT_TYPES) else "other",
            key_class=KEY_CLASSES[classes[i]] if classes[i] < len(KEY_CLASSES) else "unknown",
            pos=pos,
            delta=deltas[i],
            meta=metas.get(i, {}),
        ))
    return events


def pack_events_b64(events: Sequence[TypingEvent]) -> str:
    """Base64 form of :func:`pack_events`, for JSON transport and text columns."""
    return base64.b64encode(pack_events(events)).decode("ascii")


def unpack_events_b64(data: Optional[str]) -> List[TypingEvent]:
    """Reverse :func:`pack_events_b64`."""
    if not data:
        return []
    return unpack_events(base64.b64decode(data))


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------


@dataclass
class TypingSummary:
    """Quantitative sketch of one typing session on one field.

    Field groups mirror the feature families in Crossley et al. (2024). Every
    field is a plain number so the whole thing flattens into a CSV column set and
    into SQL columns without special-casing.
    """

    # --- identity -------------------------------------------------------
    schema_name: str = ""
    label_name: str = ""

    # --- volume / product-to-process ------------------------------------
    keystrokes: int = 0              # physical keydowns that produced text
    final_chars: int = 0             # length of the field at session end
    chars_typed: int = 0             # characters inserted by typing
    chars_inserted: int = 0          # characters inserted by any means
    chars_deleted: int = 0
    active_ms: int = 0               # wall time minus the long idle gaps
    wall_ms: int = 0
    chars_per_keystroke: float = 0.0

    # --- rhythm / process variance --------------------------------------
    iki_median_ms: float = 0.0
    iki_mean_ms: float = 0.0
    iki_p10_ms: float = 0.0
    iki_p25_ms: float = 0.0
    iki_p75_ms: float = 0.0
    iki_p90_ms: float = 0.0
    iki_log_sd: float = 0.0
    iki_log_cv: float = 0.0

    # --- pausing --------------------------------------------------------
    pause_counts: Dict[str, int] = field(default_factory=dict)
    pause_total_ms: int = 0
    pre_word_pause_mean_ms: float = 0.0
    pre_sentence_pause_mean_ms: float = 0.0
    intraword_iki_median_ms: float = 0.0

    # --- bursting -------------------------------------------------------
    bursts: int = 0
    burst_mean_chars: float = 0.0
    burst_max_chars: int = 0
    p_bursts: int = 0                # terminated by a pause
    r_bursts: int = 0                # terminated by a revision

    # --- revision -------------------------------------------------------
    backspaces: int = 0
    deletes: int = 0
    non_terminal_edits: int = 0      # edits made behind the end of the text
    caret_jumps: int = 0
    undo_events: int = 0
    revision_ratio: float = 0.0

    # --- external insertion (the AI tell) -------------------------------
    paste_events: int = 0
    pasted_chars: int = 0
    largest_paste_chars: int = 0
    pasted_fraction: float = 0.0
    drop_events: int = 0
    silent_insert_chars: int = 0
    silent_insert_ratio: float = 0.0
    paste_sources: Dict[str, int] = field(default_factory=dict)
    paste_chars_by_source: Dict[str, int] = field(default_factory=dict)
    # Silent insertions excluding pastes whose source was the annotator's own
    # text or the passage under annotation. Quoting the passage is normal
    # annotator behaviour and must not read the same as importing text from
    # somewhere off-screen.
    external_insert_chars: int = 0
    external_insert_ratio: float = 0.0

    # --- attention ------------------------------------------------------
    blur_events: int = 0
    blur_total_ms: int = 0
    max_blur_before_insert_ms: int = 0
    first_keystroke_latency_ms: int = 0

    # --- integrity ------------------------------------------------------
    untrusted_events: int = 0
    composition_events: int = 0
    virtual_keyboard: bool = False

    # --- provenance -----------------------------------------------------
    event_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "schema_name": self.schema_name,
            "label_name": self.label_name,
            "keystrokes": self.keystrokes,
            "final_chars": self.final_chars,
            "chars_typed": self.chars_typed,
            "chars_inserted": self.chars_inserted,
            "chars_deleted": self.chars_deleted,
            "active_ms": self.active_ms,
            "wall_ms": self.wall_ms,
            "chars_per_keystroke": self.chars_per_keystroke,
            "iki_median_ms": self.iki_median_ms,
            "iki_mean_ms": self.iki_mean_ms,
            "iki_p10_ms": self.iki_p10_ms,
            "iki_p25_ms": self.iki_p25_ms,
            "iki_p75_ms": self.iki_p75_ms,
            "iki_p90_ms": self.iki_p90_ms,
            "iki_log_sd": self.iki_log_sd,
            "iki_log_cv": self.iki_log_cv,
            "pause_counts": self.pause_counts,
            "pause_total_ms": self.pause_total_ms,
            "pre_word_pause_mean_ms": self.pre_word_pause_mean_ms,
            "pre_sentence_pause_mean_ms": self.pre_sentence_pause_mean_ms,
            "intraword_iki_median_ms": self.intraword_iki_median_ms,
            "bursts": self.bursts,
            "burst_mean_chars": self.burst_mean_chars,
            "burst_max_chars": self.burst_max_chars,
            "p_bursts": self.p_bursts,
            "r_bursts": self.r_bursts,
            "backspaces": self.backspaces,
            "deletes": self.deletes,
            "non_terminal_edits": self.non_terminal_edits,
            "caret_jumps": self.caret_jumps,
            "undo_events": self.undo_events,
            "revision_ratio": self.revision_ratio,
            "paste_events": self.paste_events,
            "pasted_chars": self.pasted_chars,
            "largest_paste_chars": self.largest_paste_chars,
            "pasted_fraction": self.pasted_fraction,
            "drop_events": self.drop_events,
            "silent_insert_chars": self.silent_insert_chars,
            "silent_insert_ratio": self.silent_insert_ratio,
            "paste_sources": self.paste_sources,
            "paste_chars_by_source": self.paste_chars_by_source,
            "external_insert_chars": self.external_insert_chars,
            "external_insert_ratio": self.external_insert_ratio,
            "blur_events": self.blur_events,
            "blur_total_ms": self.blur_total_ms,
            "max_blur_before_insert_ms": self.max_blur_before_insert_ms,
            "first_keystroke_latency_ms": self.first_keystroke_latency_ms,
            "untrusted_events": self.untrusted_events,
            "composition_events": self.composition_events,
            "virtual_keyboard": self.virtual_keyboard,
            "event_count": self.event_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TypingSummary":
        """Reconstruct from a serialized dictionary.

        Every field is read with ``.get()`` and a default, so summaries written
        by an older Potato deserialize unchanged after new features are added.
        """
        s = cls()
        for key, default in cls().to_dict().items():
            setattr(s, key, data.get(key, default))
        return s


def _percentile(sorted_values: Sequence[float], pct: float) -> float:
    """Linear-interpolated percentile over an already-sorted sequence."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    k = (len(sorted_values) - 1) * pct
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return float(sorted_values[int(k)])
    return float(sorted_values[lo] * (hi - k) + sorted_values[hi] * (k - lo))


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return _percentile(sorted(values), 0.5)


def summarize(
    events: Sequence[TypingEvent],
    *,
    schema_name: str = "",
    label_name: str = "",
    final_chars: Optional[int] = None,
    pause_thresholds_ms: Optional[Sequence[int]] = None,
    burst_iki_multiplier: float = BURST_IKI_MULTIPLIER,
    virtual_keyboard: bool = False,
) -> TypingSummary:
    """Compute the quantitative sketch for one session's event stream.

    Args:
        events: The session's events, assumed ordered by ``t_ms``. They are
            sorted defensively, since the client batches and a late flush can
            arrive out of order.
        schema_name / label_name: Field identity, copied onto the summary.
        final_chars: Field length at session end. Falls back to the running
            length derived from the deltas, which is only correct when the field
            started empty — pass it explicitly when restoring a saved draft.
        pause_thresholds_ms: Overrides :data:`DEFAULT_PAUSE_THRESHOLDS_MS`.
        burst_iki_multiplier: Burst boundary as a multiple of the writer's own
            median IKI.
        virtual_keyboard: Client reported a soft keyboard. Recorded so the
            detector can suppress keystroke-count heuristics, which are not
            meaningful when keydown is unreliable.

    Returns:
        A :class:`TypingSummary`. An empty stream yields an all-zero summary
        rather than raising.
    """
    thresholds = list(pause_thresholds_ms or DEFAULT_PAUSE_THRESHOLDS_MS)
    s = TypingSummary(schema_name=schema_name, label_name=label_name)
    s.pause_counts = {str(t): 0 for t in thresholds}

    if not events:
        s.final_chars = int(final_chars or 0)
        return s

    ev = sorted(events, key=lambda e: e.t_ms)
    s.event_count = len(ev)
    s.virtual_keyboard = virtual_keyboard
    s.wall_ms = max(0, ev[-1].t_ms - ev[0].t_ms)

    # Running length of the field, used to tell an append from an edit behind
    # the caret. Only meaningful when the field started empty; `final_chars`
    # overrides the end value.
    length = 0
    last_pos: Optional[int] = None

    # Inter-key intervals are measured between *text-producing* events only.
    # Including focus/blur/navigation would inject artificial gaps into the
    # rhythm distribution.
    ikis: List[float] = []
    intraword_ikis: List[float] = []
    pre_word_pauses: List[float] = []
    pre_sentence_pauses: List[float] = []
    prev_text_t: Optional[int] = None
    prev_key_class: Optional[str] = None

    # Burst accounting: a run of insertions ended by a long pause (P-burst) or
    # by a revision (R-burst) — Chenoweth & Hayes (2001).
    burst_lengths: List[int] = []
    current_burst = 0

    pending_blur_ms = 0     # blur duration not yet attributed to an insertion
    first_keystroke_t: Optional[int] = None

    for e in ev:
        meta = e.meta or {}

        if meta.get("is_trusted") is False:
            s.untrusted_events += 1

        if e.input_type == "blur":
            s.blur_events += 1
            blur_ms = int(meta.get("blur_ms", 0))
            s.blur_total_ms += blur_ms
            # Held until the next insertion so we can measure "was away, came
            # back, immediately produced a lot of text".
            pending_blur_ms = max(pending_blur_ms, blur_ms)
            continue

        if e.input_type == "focus":
            continue

        if meta.get("composing"):
            s.composition_events += 1

        is_insert = e.delta > 0
        is_delete = e.input_type in DELETE_TYPES or e.delta < 0
        is_external = e.input_type in EXTERNAL_INSERT_TYPES

        # --- keystroke accounting ---
        if e.key_class in ("letter", "digit", "punct", "space", "enter"):
            s.keystrokes += 1
            if first_keystroke_t is None:
                first_keystroke_t = e.t_ms
        elif e.key_class == "bksp":
            s.backspaces += 1
            s.keystrokes += 1
        elif e.key_class == "del":
            s.deletes += 1
            s.keystrokes += 1

        if e.input_type in ("historyUndo", "historyRedo"):
            s.undo_events += 1

        # --- caret movement ---
        if last_pos is not None and abs(e.pos - last_pos) > 1:
            s.caret_jumps += 1
        # An edit applied before the end of the text is a genuine revision
        # rather than continued composition.
        if (is_insert or is_delete) and length > 0 and e.pos < length:
            s.non_terminal_edits += 1
        last_pos = e.pos

        # --- insertion / deletion volume ---
        if is_insert:
            s.chars_inserted += e.delta
            length += e.delta
            if is_external:
                s.silent_insert_chars += e.delta
                if e.input_type == "insertFromPaste":
                    s.paste_events += 1
                    s.pasted_chars += e.delta
                    s.largest_paste_chars = max(s.largest_paste_chars, e.delta)
                    source = str(meta.get("paste_source", "unknown"))
                    s.paste_sources[source] = s.paste_sources.get(source, 0) + 1
                    s.paste_chars_by_source[source] = (
                        s.paste_chars_by_source.get(source, 0) + e.delta
                    )
                    if source not in LEGITIMATE_PASTE_SOURCES:
                        s.external_insert_chars += e.delta
                elif e.input_type == "insertFromDrop":
                    s.drop_events += 1
                    s.external_insert_chars += e.delta
                else:
                    # insertReplacementText: autocorrect/autofill, no known source
                    s.external_insert_chars += e.delta
                # A large insertion right after time away is the strongest
                # single behavioural signal for off-screen composition.
                if pending_blur_ms:
                    s.max_blur_before_insert_ms = max(
                        s.max_blur_before_insert_ms, pending_blur_ms
                    )
                    pending_blur_ms = 0
                # External insertion terminates the current burst.
                if current_burst:
                    burst_lengths.append(current_burst)
                    s.r_bursts += 1
                    current_burst = 0
            else:
                s.chars_typed += e.delta
                current_burst += e.delta
                if pending_blur_ms:
                    s.max_blur_before_insert_ms = max(
                        s.max_blur_before_insert_ms, pending_blur_ms
                    )
                    pending_blur_ms = 0
        elif is_delete:
            removed = abs(e.delta) if e.delta else 1
            s.chars_deleted += removed
            length = max(0, length - removed)
            if current_burst:
                burst_lengths.append(current_burst)
                s.r_bursts += 1
                current_burst = 0

        # --- rhythm ---
        # Only typed text advances the IKI clock. A paste is one event covering
        # hundreds of characters; counting it as an interval would fabricate a
        # rhythm that was never produced.
        produces_text = is_insert or is_delete
        if produces_text and not is_external:
            if prev_text_t is not None:
                gap = e.t_ms - prev_text_t
                if 0 <= gap <= MAX_IKI_FOR_RHYTHM_MS:
                    ikis.append(gap)
                    if prev_key_class == "letter" and e.key_class == "letter":
                        intraword_ikis.append(gap)
                    if e.key_class == "letter" and prev_key_class == "space":
                        pre_word_pauses.append(gap)
                    if e.key_class in ("letter", "space") and prev_key_class == "punct":
                        pre_sentence_pauses.append(gap)
                for t in thresholds:
                    if gap >= t:
                        s.pause_counts[str(t)] += 1
                if gap >= thresholds[0]:
                    s.pause_total_ms += gap
            prev_text_t = e.t_ms
            prev_key_class = e.key_class

    if current_burst:
        burst_lengths.append(current_burst)
        s.p_bursts += 1

    # --- derived rhythm statistics ---
    if ikis:
        ordered = sorted(ikis)
        s.iki_median_ms = _percentile(ordered, 0.5)
        s.iki_mean_ms = sum(ordered) / len(ordered)
        s.iki_p10_ms = _percentile(ordered, 0.10)
        s.iki_p25_ms = _percentile(ordered, 0.25)
        s.iki_p75_ms = _percentile(ordered, 0.75)
        s.iki_p90_ms = _percentile(ordered, 0.90)
        # Log scale because IKI distributions are heavily right-skewed; the
        # log-CV is the dispersion measure that actually separates natural
        # typing from the metronomic rhythm of transcription.
        logs = [math.log(v) for v in ordered if v > 0]
        if len(logs) > 1:
            mean_log = sum(logs) / len(logs)
            var = sum((v - mean_log) ** 2 for v in logs) / (len(logs) - 1)
            s.iki_log_sd = math.sqrt(var)
            if mean_log:
                s.iki_log_cv = s.iki_log_sd / abs(mean_log)

    s.intraword_iki_median_ms = _median(intraword_ikis)
    s.pre_word_pause_mean_ms = (
        sum(pre_word_pauses) / len(pre_word_pauses) if pre_word_pauses else 0.0
    )
    s.pre_sentence_pause_mean_ms = (
        sum(pre_sentence_pauses) / len(pre_sentence_pauses)
        if pre_sentence_pauses else 0.0
    )

    # --- bursts ---
    if burst_lengths:
        s.bursts = len(burst_lengths)
        s.burst_mean_chars = sum(burst_lengths) / len(burst_lengths)
        s.burst_max_chars = max(burst_lengths)
    # Bursts terminated by a long pause, using the writer's own median IKI as
    # the boundary (Roeser et al. 2021: a universal constant is not defensible).
    if s.iki_median_ms and ikis:
        boundary = s.iki_median_ms * burst_iki_multiplier
        s.p_bursts += sum(1 for gap in ikis if gap >= boundary)

    # --- totals and ratios ---
    s.final_chars = int(final_chars if final_chars is not None else length)
    s.active_ms = max(0, s.wall_ms - max(0, s.blur_total_ms))

    if s.keystrokes:
        s.chars_per_keystroke = s.chars_inserted / s.keystrokes
    if s.chars_inserted:
        s.silent_insert_ratio = s.silent_insert_chars / s.chars_inserted
        s.external_insert_ratio = s.external_insert_chars / s.chars_inserted
    if s.final_chars:
        s.pasted_fraction = min(1.0, s.pasted_chars / s.final_chars)
    if s.chars_typed:
        s.revision_ratio = s.chars_deleted / s.chars_typed

    if first_keystroke_t is not None:
        s.first_keystroke_latency_ms = max(0, first_keystroke_t - ev[0].t_ms)

    return s


def merge_summaries(summaries: Sequence[TypingSummary]) -> Optional[TypingSummary]:
    """Combine several sessions on the same field into one summary.

    An annotator typically focuses a field, types, leaves, and comes back — each
    visit is its own session. Reporting per-visit would understate totals and
    overstate how little was written in one sitting, so the endpoint merges by
    field before storing the sketch alongside the annotation.

    Counts and durations add. Distribution statistics (percentiles, log-CV)
    cannot be pooled correctly from summaries alone, so they are taken as a
    keystroke-weighted mean — an approximation, and the reason the raw streams
    are retained for anyone who needs the exact pooled distribution.
    """
    valid = [s for s in summaries if s is not None]
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]

    out = TypingSummary(
        schema_name=valid[0].schema_name,
        label_name=valid[0].label_name,
    )

    additive = [
        "keystrokes", "chars_typed", "chars_inserted", "chars_deleted",
        "active_ms", "wall_ms", "pause_total_ms", "bursts", "p_bursts",
        "r_bursts", "backspaces", "deletes", "non_terminal_edits",
        "caret_jumps", "undo_events", "paste_events", "pasted_chars",
        "drop_events", "silent_insert_chars", "external_insert_chars",
        "blur_events", "blur_total_ms",
        "untrusted_events", "composition_events", "event_count",
    ]
    for name in additive:
        setattr(out, name, sum(getattr(s, name) for s in valid))

    for name in ("largest_paste_chars", "burst_max_chars",
                 "max_blur_before_insert_ms"):
        setattr(out, name, max(getattr(s, name) for s in valid))

    # The last session's view of the field is the current one.
    out.final_chars = valid[-1].final_chars
    out.first_keystroke_latency_ms = valid[0].first_keystroke_latency_ms
    out.virtual_keyboard = any(s.virtual_keyboard for s in valid)

    for s in valid:
        for threshold, count in s.pause_counts.items():
            out.pause_counts[threshold] = out.pause_counts.get(threshold, 0) + count
        for source, count in s.paste_sources.items():
            out.paste_sources[source] = out.paste_sources.get(source, 0) + count
        for source, chars in s.paste_chars_by_source.items():
            out.paste_chars_by_source[source] = (
                out.paste_chars_by_source.get(source, 0) + chars
            )

    weights = [max(1, s.keystrokes) for s in valid]
    total_weight = sum(weights)
    weighted = [
        "iki_median_ms", "iki_mean_ms", "iki_p10_ms", "iki_p25_ms",
        "iki_p75_ms", "iki_p90_ms", "iki_log_sd", "iki_log_cv",
        "pre_word_pause_mean_ms", "pre_sentence_pause_mean_ms",
        "intraword_iki_median_ms", "burst_mean_chars",
    ]
    for name in weighted:
        setattr(out, name, sum(
            getattr(s, name) * w for s, w in zip(valid, weights)
        ) / total_weight)

    if out.keystrokes:
        out.chars_per_keystroke = out.chars_inserted / out.keystrokes
    if out.chars_inserted:
        out.silent_insert_ratio = out.silent_insert_chars / out.chars_inserted
        out.external_insert_ratio = out.external_insert_chars / out.chars_inserted
    if out.final_chars:
        out.pasted_fraction = min(1.0, out.pasted_chars / out.final_chars)
    if out.chars_typed:
        out.revision_ratio = out.chars_deleted / out.chars_typed

    return out
