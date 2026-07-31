"""
Transcript ingestion / normalization.

Speech transcripts arrive in a lot of shapes depending on the toolchain that
produced them — an ASR API, a forced aligner, a subtitle file downloaded off
YouTube, or a hand-authored caption track. This package normalizes all of them
into one canonical turn model that the ``audio_dialogue`` display, the
``speech_transcript`` and ``voice_interaction`` schemas, and the turn-level
annotation framework all consume::

    {
        "audio": "<url or path> | None",
        "turns": [
            {"turn_id": "t0", "speaker": "host" | None,
             "start": 12.0, "end": 19.4, "text": "...",
             "words": [...],        # optional, only when the source had them
             "confidence": 0.94},   # optional, likewise
            ...
        ],
    }

Accepted inputs (auto-detected — never by file extension, so inline data and
sidecar files behave identically):

**Turn / segment JSON**

* **Native turn JSON** — ``{"audio": ..., "turns": [{"speaker","start","end","text"}]}``
  (or a bare list of such turn dicts). Passed through.
* **Plain Whisper JSON** — ``{"segments": [{"start","end","text"}]}`` with no
  speaker → each turn gets ``speaker: None`` (undiarized; the annotator assigns).
* **WhisperX / diarized JSON** — the same with a ``speaker`` diarization label
  (e.g. ``"SPEAKER_00"``). Per-word timings from ``word_timestamps`` are kept.
* **whisper.cpp JSON** — ``{"transcription": [{"offsets": {"from","to"}, "text"}]}``
  (offsets are milliseconds).
* **SPoRC** (Structured Podcast Research Corpus, ``blitt/SPoRC``) — the
  speaker-turn rows: ``turn_text`` / ``start_time`` / ``end_time``, a
  ``speaker`` *list* (e.g. ``["SPEAKER_03"]``), and ``inferred_speaker_name`` /
  ``inferred_speaker_role`` (``host``/``guest``/``neither``). These are handled
  as fallbacks, and ``mp3_url`` is used as the audio source, so a bare list of
  SPoRC turn rows normalizes with no extra config. Point ``speaker_key`` at
  ``inferred_speaker_name`` (or ``inferred_speaker_role``) for human-readable
  bubbles; ``neither``/empty roles fall through to ``None`` (undiarized), letting
  the annotator assign the speaker.

**Cloud ASR responses**

* **AWS Transcribe** — ``results.audio_segments`` when present, else the
  ``results.items`` word stream joined to ``results.speaker_labels``.
* **Deepgram** — ``results.utterances`` when present, else the first channel's
  word list grouped by speaker and pause.
* **AssemblyAI** — ``utterances`` when present, else ``words`` (milliseconds).
* **Rev.ai** — ``monologues[].elements[]``.

**Subtitle / caption files**

* **WebVTT** — a string beginning with ``WEBVTT``; ``<v Name>`` voice tags or a
  ``"Name: text"`` prefix become the speaker, else ``None``.
* **SRT** — a SubRip string (numbered cues, ``,mmm`` millisecond separators).
* **SubStation Alpha** (``.ass`` / ``.ssa``) — ``Dialogue:`` events; the ``Name``
  field becomes the speaker.
* **TTML / DFXP** and YouTube's **srv1/srv2/srv3** XML.
* **YouTube json3** — ``{"events": [{"tStartMs","dDurationMs","segs"}]}``, with
  per-word ``tOffsetMs`` preserved as word timings.
* **Whisper TSV** — the ``start\\tend\\ttext`` file from ``--output_format tsv``
  (milliseconds).

**Alignment / linguistic annotation**

* **NIST CTM** — word alignments grouped into turns by speaker and pause.
* **Praat TextGrid** — long and short serializations; one tier per speaker.
* **ELAN EAF** — ``ALIGNABLE_ANNOTATION`` and ``REF_ANNOTATION``, resolved
  against the ``TIME_ORDER`` table; ``PARTICIPANT`` becomes the speaker.

Plus, as a last resort, a plain untimed paragraph, which renders as one bubble.

**Sidecar files.** When ``base_dir`` is supplied, a field value that is a short
single-line path with a known transcript extension (``interview_01.srt``) is
read off disk through ``validate_path_security`` and parsed as content. See
:mod:`potato.server_utils.transcripts.loader`.

A **stable ``turn_id``** is assigned to every turn (explicit ``turn_id``/``step_id``
from the source when present, else ``t{index}``). Turn ids are the persistence key
for per-turn ratings and speaker assignments, so they must be deterministic across
reloads — the same input always yields the same ids. This mirrors
``turn_annotations.turn_id_for`` so the display and framework agree.

The parsing here is pure-stdlib (no ASR/pyannote runtime, no third-party deps);
transcription and diarization are expected to have run upstream of Potato.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .align import (
    looks_like_ctm,
    looks_like_eaf,
    looks_like_textgrid,
    parse_ctm,
    parse_eaf,
    parse_textgrid,
)
from .asr import (
    detect_asr,
    looks_like_whisper_tsv,
    parse_whisper_tsv,
)
from .core import (
    TranscriptError,
    audio_from_segments,
    coerce_audio,
    normalize_segment,
)
from .cues import (
    looks_like_ass,
    looks_like_ttml,
    parse_ass,
    parse_json3,
    parse_string_transcript,
    parse_ttml,
)
from .loader import (
    TRANSCRIPT_EXTENSIONS,
    is_transcript_path,
    read_transcript_file,
    resolve_transcript_source,
)

__all__ = [
    "normalize_transcript",
    "TranscriptError",
    "resolve_transcript_source",
    "is_transcript_path",
    "read_transcript_file",
    "TRANSCRIPT_EXTENSIONS",
    "detect_format",
]


def normalize_transcript(
    raw: Any,
    *,
    audio_key: str = "audio",
    turns_key: str = "turns",
    speaker_key: str = "speaker",
    text_key: str = "text",
    start_key: str = "start",
    end_key: str = "end",
    base_dir: Optional[str] = None,
    is_path: str = "auto",
) -> Dict[str, Any]:
    """Normalize any supported transcript payload to ``{"audio", "turns"}``.

    See the module docstring for the accepted input shapes. Never raises for
    empty/partial data — returns an empty turn list instead — so a
    misconfigured instance renders as "no dialogue" rather than crashing the
    page. ``TranscriptError`` is reserved for wholly uninterpretable types.

    Args:
        base_dir: When set, string values that look like transcript file paths
            are resolved against this directory and read. Omit to treat every
            string as inline content.
        is_path: ``"auto"`` | ``"true"`` | ``"false"`` — override the sidecar
            path heuristic.
    """
    audio: Optional[str] = None
    segments: List[Dict[str, Any]]

    if raw is None:
        return {"audio": None, "turns": []}

    if base_dir:
        raw = resolve_transcript_source(
            raw, base_dir, is_path=is_path
        )

    if isinstance(raw, str):
        segments = _parse_string(raw)
    elif isinstance(raw, list):
        segments = [s for s in raw if isinstance(s, dict)]
    elif isinstance(raw, dict):
        audio = coerce_audio(raw.get(audio_key))
        segments = _segments_from_dict(
            raw, turns_key=turns_key, base_dir=base_dir, is_path=is_path,
        )
    else:
        raise TranscriptError(
            f"Unsupported transcript type: {type(raw).__name__}. Expected a dict, "
            f"list of turns, or a VTT/SRT string."
        )

    turns = []
    for i, seg in enumerate(segments):
        turns.append(
            normalize_segment(
                seg, i,
                speaker_key=speaker_key, text_key=text_key,
                start_key=start_key, end_key=end_key,
            )
        )

    # Derive audio from the segments when the container didn't provide it — e.g.
    # a bare list of SPoRC turn rows, each carrying the same ``mp3_url``, or an
    # EAF whose media reference lives in the header.
    if audio is None:
        audio = audio_from_segments(segments)

    return {"audio": audio, "turns": turns}


def _segments_from_dict(
    raw: Dict[str, Any],
    *,
    turns_key: str,
    base_dir: Optional[str] = None,
    is_path: str = "auto",
) -> List[Dict[str, Any]]:
    """Pull segments out of a dict payload.

    Explicit container keys win, so a config that names its own ``turns_key``
    always takes precedence over vendor sniffing. Vendor probes only run once
    the generic shapes have been ruled out.

    A string ``transcript`` may itself be a sidecar path — this is the common
    layout, where the item pairs a media URL with a transcript file next to it::

        {"audio": "media/int_001.mp3", "transcript": "media/int_001.srt"}
    """
    if isinstance(raw.get(turns_key), list):
        return [s for s in raw[turns_key] if isinstance(s, dict)]
    if isinstance(raw.get("segments"), list):
        return [s for s in raw["segments"] if isinstance(s, dict)]
    if isinstance(raw.get("transcript"), str):
        content = raw["transcript"]
        if base_dir:
            content = resolve_transcript_source(content, base_dir, is_path=is_path)
        return _parse_string(content)
    if isinstance(raw.get("transcript"), list):
        return [s for s in raw["transcript"] if isinstance(s, dict)]

    # YouTube json3.
    if isinstance(raw.get("events"), list):
        return parse_json3(raw)

    # Vendor ASR responses (AWS / Deepgram / AssemblyAI / Rev.ai / whisper.cpp).
    vendor = detect_asr(raw)
    if vendor is not None:
        return vendor

    return []


def _parse_string(text: str) -> List[Dict[str, Any]]:
    """Parse a string transcript, sniffing the format from its content.

    Order matters. The self-identifying formats (XML documents, TextGrid's magic
    header, ASS section markers) are checked first because their signatures are
    unambiguous. JSON is unwrapped next and re-dispatched through the dict path.
    The looser line-shaped formats (TSV, CTM) come after, and cue parsing plus
    the single-paragraph fallback last.
    """
    stripped = text.strip()
    if not stripped:
        return []

    if looks_like_ass(stripped):
        return parse_ass(stripped)
    if looks_like_eaf(stripped):
        return parse_eaf(stripped)
    if looks_like_ttml(stripped):
        return parse_ttml(stripped)
    if looks_like_textgrid(stripped):
        return parse_textgrid(stripped)

    if stripped[0] in "{[":
        try:
            parsed = json.loads(stripped)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            return _segments_from_dict(parsed, turns_key="turns")
        if isinstance(parsed, list):
            return [s for s in parsed if isinstance(s, dict)]

    if looks_like_whisper_tsv(stripped):
        return parse_whisper_tsv(stripped)
    if looks_like_ctm(stripped):
        return parse_ctm(stripped)

    # SRT / WebVTT cues, or a plain paragraph.
    return parse_string_transcript(stripped)


def detect_format(raw: Any) -> str:
    """Best-effort name of the format ``raw`` was recognized as.

    Purely diagnostic — this is what ``potato transcripts --dry-run`` reports so
    a user can see whether their file was understood the way they expected. It
    mirrors the dispatch in :func:`normalize_transcript` but never parses.
    """
    if raw is None:
        return "empty"

    if isinstance(raw, dict):
        if isinstance(raw.get("turns"), list):
            return "native turn JSON"
        if isinstance(raw.get("segments"), list):
            first = next((s for s in raw["segments"] if isinstance(s, dict)), {})
            return "WhisperX / diarized JSON" if "speaker" in first else "Whisper JSON"
        if isinstance(raw.get("events"), list):
            return "YouTube json3"
        if isinstance(raw.get("transcription"), list):
            return "whisper.cpp JSON"
        if isinstance(raw.get("monologues"), list):
            return "Rev.ai JSON"
        if isinstance(raw.get("text"), str) and (
            isinstance(raw.get("words"), list) or isinstance(raw.get("utterances"), list)
        ):
            return "AssemblyAI JSON"
        results = raw.get("results")
        if isinstance(results, dict):
            if isinstance(results.get("items"), list) or isinstance(
                results.get("audio_segments"), list
            ):
                return "AWS Transcribe JSON"
            if isinstance(results.get("channels"), list) or isinstance(
                results.get("utterances"), list
            ):
                return "Deepgram JSON"
        if isinstance(raw.get("transcript"), (str, list)):
            return "transcript wrapper"
        return "unrecognized JSON object"

    if isinstance(raw, list):
        return "turn list"

    if not isinstance(raw, str):
        return "unsupported"

    stripped = raw.strip()
    if not stripped:
        return "empty"
    if looks_like_ass(stripped):
        return "SubStation Alpha"
    if looks_like_eaf(stripped):
        return "ELAN EAF"
    if looks_like_ttml(stripped):
        return "TTML / srv XML"
    if looks_like_textgrid(stripped):
        return "Praat TextGrid"
    if stripped[0] in "{[":
        try:
            return detect_format(json.loads(stripped))
        except ValueError:
            return "malformed JSON"
    if looks_like_whisper_tsv(stripped):
        return "Whisper TSV"
    if looks_like_ctm(stripped):
        return "NIST CTM"
    if stripped.upper().startswith("WEBVTT"):
        return "WebVTT"
    from .core import ARROW_RE
    if ARROW_RE.search(stripped):
        return "SRT"
    return "plain text"
