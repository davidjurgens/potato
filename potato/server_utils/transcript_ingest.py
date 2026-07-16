"""
Transcript ingestion / normalization for the ``audio_dialogue`` display.

Podcast / interview transcripts arrive in several shapes depending on the ASR +
diarization toolchain (Whisper, WhisperX, pyannote, or hand-authored captions).
This module normalizes all of them into one canonical turn model that the
``audio_dialogue`` display and the turn-level annotation framework both consume::

    {
        "audio": "<url or path> | None",
        "turns": [
            {"turn_id": "t0", "speaker": "host" | None,
             "start": 12.0, "end": 19.4, "text": "..."},
            ...
        ],
    }

Accepted inputs (auto-detected):

* **Native turn JSON** — ``{"audio": ..., "turns": [{"speaker","start","end","text"}]}``
  (or a bare list of such turn dicts). Passed through.
* **WhisperX / diarized JSON** — ``{"segments": [{"start","end","text","speaker"}]}``
  where ``speaker`` is a diarization label (e.g. ``"SPEAKER_00"``).
* **Plain Whisper JSON** — ``{"segments": [{"start","end","text"}]}`` with no
  speaker → each turn gets ``speaker: None`` (undiarized; the annotator assigns).
* **WebVTT** — a string beginning with ``WEBVTT``; ``<v Name>`` voice tags or a
  ``"Name: text"`` prefix become the speaker, else ``None``.
* **SRT** — a SubRip string (numbered cues, ``,mmm`` millisecond separators).
* **SPoRC** (Structured Podcast Research Corpus, ``blitt/SPoRC``) — the
  speaker-turn rows: ``turn_text`` / ``start_time`` / ``end_time``, a
  ``speaker`` *list* (e.g. ``["SPEAKER_03"]``), and ``inferred_speaker_name`` /
  ``inferred_speaker_role`` (``host``/``guest``/``neither``). These are handled
  as fallbacks, and ``mp3_url`` is used as the audio source, so a bare list of
  SPoRC turn rows normalizes with no extra config. Point ``speaker_key`` at
  ``inferred_speaker_name`` (or ``inferred_speaker_role``) for human-readable
  bubbles; ``neither``/empty roles fall through to ``None`` (undiarized), letting
  the annotator assign the speaker.

A **stable ``turn_id``** is assigned to every turn (explicit ``turn_id``/``step_id``
from the source when present, else ``t{index}``). Turn ids are the persistence key
for per-turn ratings and speaker assignments, so they must be deterministic across
reloads — the same input always yields the same ids. This mirrors
``turn_annotations.turn_id_for`` so the display and framework agree.

The parsing here is pure-stdlib (no ASR/pyannote runtime, no third-party deps);
diarization is expected to have run upstream of Potato.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

__all__ = ["normalize_transcript", "TranscriptError"]


class TranscriptError(ValueError):
    """Raised when a transcript payload cannot be interpreted at all."""


# ``[HH:]MM:SS[.,]mmm`` — hours optional, ``.`` or ``,`` before milliseconds.
_TS_RE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
_ARROW_RE = re.compile(
    r"((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})"
)
_VOICE_TAG_RE = re.compile(r"<v\s+([^>]+)>(.*?)(?:</v>|$)", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
# "Name: text" — a short leading label (letters/digits/space/_/-) then a colon.
_SPEAKER_PREFIX_RE = re.compile(r"^([A-Za-z0-9 _\-]{1,40}?):\s+(.*)$", re.DOTALL)


def normalize_transcript(
    raw: Any,
    *,
    audio_key: str = "audio",
    turns_key: str = "turns",
    speaker_key: str = "speaker",
    text_key: str = "text",
    start_key: str = "start",
    end_key: str = "end",
) -> Dict[str, Any]:
    """Normalize any supported transcript payload to ``{"audio", "turns"}``.

    See the module docstring for the accepted input shapes. Never raises for
    empty/partial data — returns an empty turn list instead — so a
    misconfigured instance renders as "no dialogue" rather than crashing the
    page. ``TranscriptError`` is reserved for wholly uninterpretable types.
    """
    audio: Optional[str] = None
    segments: List[Dict[str, Any]]

    if raw is None:
        return {"audio": None, "turns": []}

    if isinstance(raw, str):
        segments = _parse_string_transcript(raw)
    elif isinstance(raw, list):
        segments = [s for s in raw if isinstance(s, dict)]
    elif isinstance(raw, dict):
        audio = _coerce_audio(raw.get(audio_key))
        if isinstance(raw.get(turns_key), list):
            segments = [s for s in raw[turns_key] if isinstance(s, dict)]
        elif isinstance(raw.get("segments"), list):
            segments = [s for s in raw["segments"] if isinstance(s, dict)]
        elif isinstance(raw.get("transcript"), str):
            segments = _parse_string_transcript(raw["transcript"])
        elif isinstance(raw.get("transcript"), list):
            segments = [s for s in raw["transcript"] if isinstance(s, dict)]
        else:
            segments = []
    else:
        raise TranscriptError(
            f"Unsupported transcript type: {type(raw).__name__}. Expected a dict, "
            f"list of turns, or a VTT/SRT string."
        )

    turns = []
    for i, seg in enumerate(segments):
        turns.append(
            _normalize_segment(
                seg, i,
                speaker_key=speaker_key, text_key=text_key,
                start_key=start_key, end_key=end_key,
            )
        )

    # Derive audio from the segments when the container didn't provide it — e.g.
    # a bare list of SPoRC turn rows, each carrying the same ``mp3_url``.
    if audio is None:
        audio = _audio_from_segments(segments)

    return {"audio": audio, "turns": turns}


def _audio_from_segments(segments: List[Dict[str, Any]]) -> Optional[str]:
    for seg in segments:
        for key in ("mp3_url", "mp3url", "audio_url", "audio", "url"):
            val = seg.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def _first_present(seg: Dict[str, Any], keys: List[str]) -> Any:
    """First value among ``keys`` that is present and non-empty."""
    for k in keys:
        if k and k in seg and seg[k] not in (None, ""):
            return seg[k]
    return None


def _coerce_audio(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _normalize_segment(
    seg: Dict[str, Any],
    index: int,
    *,
    speaker_key: str,
    text_key: str,
    start_key: str,
    end_key: str,
) -> Dict[str, Any]:
    explicit_id = seg.get("turn_id") or seg.get("step_id") or seg.get("id")
    # Whisper's numeric segment ``id`` is just the index; only honor a
    # meaningful *string* id, otherwise fall back to the deterministic t{index}
    # (matches turn_annotations.turn_id_for).
    if isinstance(explicit_id, str) and explicit_id.strip():
        turn_id = explicit_id.strip()
    else:
        turn_id = f"t{index}"

    speaker = _resolve_speaker(seg, speaker_key)

    # Text: configured key, then SPoRC ``turn_text`` / ``turnText``, ``content``.
    text = _first_present(seg, [text_key, "turn_text", "turnText", "content"])
    text = str(text).strip() if text is not None else ""

    # Times: configured key, then SPoRC ``start_time``/``startTime`` etc.
    start = _first_present(seg, [start_key, "start_time", "startTime"])
    end = _first_present(seg, [end_key, "end_time", "endTime"])
    if end is None:
        end = start

    return {
        "turn_id": turn_id,
        "speaker": speaker,
        "start": _to_seconds(start),
        "end": _to_seconds(end),
        "text": text,
    }


# Speaker labels that mean "not a real speaker" and should read as undiarized
# (so the annotator assigns), e.g. SPoRC's ``inferredSpeakerRole: neither`` or
# ``inferredSpeakerName: NO_INFERRED_SPEAKER``.
_NULL_SPEAKER_LABELS = {
    "neither", "unknown", "none", "", "no_inferred_speaker", "no_inferred_role",
}

# SPoRC inferred-speaker keys, snake_case (parquet) and camelCase (JSONL).
_NAME_KEYS = ("inferred_speaker_name", "inferredSpeakerName")
_ROLE_KEYS = ("inferred_speaker_role", "inferredSpeakerRole", "role")


def _resolve_speaker(seg: Dict[str, Any], speaker_key: str) -> Optional[str]:
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

    if _is_null_speaker(value):
        value = _first_present(seg, list(_NAME_KEYS))

    if _is_null_speaker(value):
        for k in _ROLE_KEYS:
            role = seg.get(k)
            if role is not None and str(role).strip().lower() not in _NULL_SPEAKER_LABELS:
                value = role
                break

    if _is_null_speaker(value):
        return None
    return str(value).strip()


def _is_null_speaker(value: Any) -> bool:
    if value in (None, ""):
        return True
    return str(value).strip().lower() in _NULL_SPEAKER_LABELS


def _to_seconds(value: Any) -> float:
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
    m = _TS_RE.fullmatch(s)
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
# VTT / SRT parsing
# ---------------------------------------------------------------------------

def _parse_string_transcript(text: str) -> List[Dict[str, Any]]:
    """Parse a VTT or SRT string into segment dicts.

    Falls back to a single untimed turn if the string carries no cue arrows
    (so a plain paragraph still renders as one bubble).
    """
    stripped = text.strip()
    if not stripped:
        return []
    if not _ARROW_RE.search(stripped):
        return [{"speaker": None, "start": 0.0, "end": 0.0, "text": stripped}]
    return _parse_cues(stripped)


def _parse_cues(text: str) -> List[Dict[str, Any]]:
    """Parse VTT/SRT cue blocks (blank-line separated)."""
    # Normalize newlines, drop a WEBVTT header and NOTE/STYLE blocks.
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", body)
    segments: List[Dict[str, Any]] = []

    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if not lines:
            continue
        header = lines[0].strip()
        if header.upper().startswith("WEBVTT"):
            lines = lines[1:]
            if not lines:
                continue
        first = lines[0].strip()
        if first.upper().startswith(("NOTE", "STYLE", "REGION")):
            continue

        # Find the arrow line (may be preceded by a numeric SRT index or a VTT
        # cue identifier).
        arrow_idx = None
        for idx, ln in enumerate(lines):
            if _ARROW_RE.search(ln):
                arrow_idx = idx
                break
        if arrow_idx is None:
            continue

        arrow = _ARROW_RE.search(lines[arrow_idx])
        start = _to_seconds(arrow.group(1))
        end = _to_seconds(arrow.group(2))
        raw_text = "\n".join(lines[arrow_idx + 1:]).strip()
        speaker, clean = _extract_cue_speaker(raw_text)
        segments.append({"speaker": speaker, "start": start, "end": end, "text": clean})

    return segments


def _extract_cue_speaker(raw_text: str) -> "tuple[Optional[str], str]":
    """Pull a speaker out of a cue: ``<v Name>`` tag or ``Name:`` prefix."""
    if not raw_text:
        return None, ""

    voice = _VOICE_TAG_RE.search(raw_text)
    if voice:
        speaker = voice.group(1).strip()
        # Strip all tags for the visible text.
        clean = _TAG_RE.sub("", raw_text).strip()
        return (speaker or None), clean

    # Strip any stray tags first.
    text = _TAG_RE.sub("", raw_text).strip()
    prefix = _SPEAKER_PREFIX_RE.match(text)
    if prefix:
        return prefix.group(1).strip(), prefix.group(2).strip()
    return None, text
