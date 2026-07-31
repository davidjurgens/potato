"""
Shared primitives for transcript normalization.

Everything in here is format-agnostic: timestamp parsing, the speaker cascade,
word-level pass-through, and the segment -> canonical-turn conversion that every
format parser funnels into. Format-specific parsing lives in the sibling modules
(:mod:`cues`, :mod:`asr`, :mod:`align`).

The canonical turn model produced by :func:`normalize_segment`::

    {"turn_id": "t0", "speaker": "host" | None,
     "start": 12.0, "end": 19.4, "text": "...",
     "words": [{"word": "hi", "start": 12.0, "end": 12.2, "confidence": 0.98}],  # optional
     "confidence": 0.94}                                                        # optional

``words`` and ``confidence`` are **omitted entirely** when the source has no such
data, so output for the formats supported before word-level support was added is
byte-identical to what it was.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "TranscriptError",
    "normalize_segment",
    "to_seconds",
    "first_present",
    "coerce_audio",
    "audio_from_segments",
    "resolve_speaker",
    "group_words_into_turns",
    "ARROW_RE",
    "TS_RE",
]


class TranscriptError(ValueError):
    """Raised when a transcript payload cannot be interpreted at all."""


# ``[HH:]MM:SS[.,]mmm`` — hours optional, ``.`` or ``,`` before milliseconds.
TS_RE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
ARROW_RE = re.compile(
    r"((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})"
)
VOICE_TAG_RE = re.compile(r"<v\s+([^>]+)>(.*?)(?:</v>|$)", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
# "Name: text" — a short leading label (letters/digits/space/_/-) then a colon.
SPEAKER_PREFIX_RE = re.compile(r"^([A-Za-z0-9 _\-]{1,40}?):\s+(.*)$", re.DOTALL)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

def to_seconds(value: Any) -> float:
    """Parse a timestamp (number or ``[HH:]MM:SS[.,]mmm`` string) to seconds."""
    if value is None:
        return 0.0
    if isinstance(value, bool):  # guard: bools are ints in Python
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return 0.0
    m = TS_RE.fullmatch(s)
    if m:
        return _hms_to_seconds(m)
    try:
        return float(s)
    except ValueError:
        return 0.0


def _hms_to_seconds(match: "re.Match") -> float:
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    millis = match.group(4)
    frac = int(millis) / (10 ** len(millis))
    return hours * 3600 + minutes * 60 + seconds + frac


# ---------------------------------------------------------------------------
# Small value helpers
# ---------------------------------------------------------------------------

def first_present(seg: Dict[str, Any], keys: List[str]) -> Any:
    """First value among ``keys`` that is present and non-empty."""
    for k in keys:
        if k and k in seg and seg[k] not in (None, ""):
            return seg[k]
    return None


def coerce_audio(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def audio_from_segments(segments: List[Dict[str, Any]]) -> Optional[str]:
    """Derive a media source from the segments themselves.

    Some sources repeat the media URL on every row (SPoRC's ``mp3_url``) rather
    than carrying it on a container object.
    """
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        for key in ("mp3_url", "mp3url", "audio_url", "audio", "url", "media_url"):
            val = seg.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


# ---------------------------------------------------------------------------
# Speakers
# ---------------------------------------------------------------------------

# Speaker labels that mean "not a real speaker" and should read as undiarized
# (so the annotator assigns), e.g. SPoRC's ``inferredSpeakerRole: neither`` or
# ``inferredSpeakerName: NO_INFERRED_SPEAKER``.
NULL_SPEAKER_LABELS = {
    "neither", "unknown", "none", "", "no_inferred_speaker", "no_inferred_role",
}

# SPoRC inferred-speaker keys, snake_case (parquet) and camelCase (JSONL).
_NAME_KEYS = ("inferred_speaker_name", "inferredSpeakerName")
_ROLE_KEYS = ("inferred_speaker_role", "inferredSpeakerRole", "role")


def resolve_speaker(seg: Dict[str, Any], speaker_key: str) -> Optional[str]:
    """Resolve a single speaker label, handling list-valued speakers and the
    diarization/SPoRC fallback cascade.

    Order: the configured ``speaker_key`` (first element if it's a list) ->
    inferred speaker NAME (``inferred_speaker_name`` / ``inferredSpeakerName``)
    -> inferred speaker ROLE (unless it is a null-ish label like ``neither``)
    -> ``role``. Returns ``None`` when nothing usable is found (the turn renders
    as undiarized).
    """
    value = seg.get(speaker_key)
    if isinstance(value, (list, tuple)):
        value = next((str(x).strip() for x in value if str(x).strip()), None)

    if is_null_speaker(value):
        value = first_present(seg, list(_NAME_KEYS))

    if is_null_speaker(value):
        for k in _ROLE_KEYS:
            role = seg.get(k)
            if role is not None and str(role).strip().lower() not in NULL_SPEAKER_LABELS:
                value = role
                break

    if is_null_speaker(value):
        return None
    return str(value).strip()


def is_null_speaker(value: Any) -> bool:
    if value in (None, ""):
        return True
    return str(value).strip().lower() in NULL_SPEAKER_LABELS


# ---------------------------------------------------------------------------
# Word-level data
# ---------------------------------------------------------------------------

# Key aliases across vendors: Whisper/WhisperX use ``word``, Deepgram offers
# ``punctuated_word`` alongside the raw ``word``, AssemblyAI uses ``text``.
_WORD_TEXT_KEYS = ("punctuated_word", "word", "text", "value")
_WORD_CONF_KEYS = ("confidence", "score", "probability", "conf")


def normalize_words(value: Any) -> Optional[List[Dict[str, Any]]]:
    """Normalize a vendor word list to ``[{word, start, end, confidence?}]``.

    Returns ``None`` (not an empty list) when there is nothing usable, so callers
    can omit the key entirely rather than emitting ``"words": []``.
    """
    if not isinstance(value, (list, tuple)) or not value:
        return None

    words: List[Dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        text = first_present(raw, list(_WORD_TEXT_KEYS))
        if text is None:
            continue
        entry: Dict[str, Any] = {
            "word": str(text),
            "start": to_seconds(first_present(raw, ["start", "start_time", "startTime"])),
            "end": to_seconds(first_present(raw, ["end", "end_time", "endTime"])),
        }
        conf = first_present(raw, list(_WORD_CONF_KEYS))
        if isinstance(conf, (int, float)) and not isinstance(conf, bool):
            entry["confidence"] = float(conf)
        words.append(entry)

    return words or None


def group_words_into_turns(
    words: List[Dict[str, Any]],
    *,
    pause_threshold: float = 0.8,
) -> List[Dict[str, Any]]:
    """Group a flat word stream into segment dicts.

    Word-level formats (CTM, Deepgram, AssemblyAI without utterances) have no
    turn structure of their own. Start a new turn when the speaker changes or
    when the gap since the previous word exceeds ``pause_threshold`` seconds,
    which is roughly where a listener hears a turn boundary.

    Each word dict is expected in the normalized shape from :func:`normalize_words`
    plus an optional ``speaker``.
    """
    segments: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    for w in words:
        speaker = w.get("speaker")
        start = float(w.get("start") or 0.0)
        end = float(w.get("end") or start)

        boundary = (
            current is None
            or speaker != current["speaker"]
            or (start - current["end"]) > pause_threshold
        )

        if boundary:
            current = {
                "speaker": speaker,
                "start": start,
                "end": end,
                "text": str(w.get("word", "")),
                "words": [_word_only(w)],
            }
            segments.append(current)
        else:
            current["end"] = max(current["end"], end)
            current["text"] = f"{current['text']} {w.get('word', '')}".strip()
            current["words"].append(_word_only(w))

    return segments


def _word_only(w: Dict[str, Any]) -> Dict[str, Any]:
    """Strip the transient ``speaker`` marker off a grouped word."""
    return {k: v for k, v in w.items() if k != "speaker"}


# ---------------------------------------------------------------------------
# Segment -> canonical turn
# ---------------------------------------------------------------------------

def normalize_segment(
    seg: Dict[str, Any],
    index: int,
    *,
    speaker_key: str,
    text_key: str,
    start_key: str,
    end_key: str,
) -> Dict[str, Any]:
    """Convert one source segment into the canonical turn dict.

    ``turn_id`` must be deterministic across reloads — it is the persistence key
    for per-turn ratings and speaker assignments (see
    ``turn_annotations.turn_id_for``). Only a meaningful *string* id from the
    source is honored; anything else falls back to ``t{index}``.
    """
    explicit_id = seg.get("turn_id") or seg.get("step_id") or seg.get("id")
    # Whisper's numeric segment ``id`` is just the index; only honor a
    # meaningful *string* id, otherwise fall back to the deterministic t{index}
    # (matches turn_annotations.turn_id_for).
    if isinstance(explicit_id, str) and explicit_id.strip():
        turn_id = explicit_id.strip()
    else:
        turn_id = f"t{index}"

    speaker = resolve_speaker(seg, speaker_key)

    # Text: configured key, then SPoRC ``turn_text`` / ``turnText``, ``content``.
    text = first_present(seg, [text_key, "turn_text", "turnText", "content"])
    text = str(text).strip() if text is not None else ""

    # Times: configured key, then SPoRC ``start_time``/``startTime`` etc.
    start = first_present(seg, [start_key, "start_time", "startTime"])
    end = first_present(seg, [end_key, "end_time", "endTime"])
    if end is None:
        end = start

    turn: Dict[str, Any] = {
        "turn_id": turn_id,
        "speaker": speaker,
        "start": to_seconds(start),
        "end": to_seconds(end),
        "text": text,
    }

    # Optional enrichment — present only when the source actually carried it, so
    # formats without word timings produce exactly the output they always did.
    words = normalize_words(seg.get("words"))
    if words:
        turn["words"] = words
    confidence = first_present(seg, ["confidence", "score"])
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        turn["confidence"] = float(confidence)

    return turn


def extract_cue_speaker(raw_text: str) -> Tuple[Optional[str], str]:
    """Pull a speaker out of a cue: ``<v Name>`` tag or ``Name:`` prefix."""
    if not raw_text:
        return None, ""

    voice = VOICE_TAG_RE.search(raw_text)
    if voice:
        speaker = voice.group(1).strip()
        # Strip all tags for the visible text.
        clean = TAG_RE.sub("", raw_text).strip()
        return (speaker or None), clean

    # Strip any stray tags first.
    text = TAG_RE.sub("", raw_text).strip()
    prefix = SPEAKER_PREFIX_RE.match(text)
    if prefix:
        return prefix.group(1).strip(), prefix.group(2).strip()
    return None, text
