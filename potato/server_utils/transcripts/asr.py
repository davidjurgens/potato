"""
ASR / speech-to-text output formats.

Each vendor emits a differently-shaped JSON document for the same underlying
thing, and the shapes are distinctive enough to tell apart by key signature
alone — no filename or extension needed. :func:`detect_asr` runs the probes in
order and returns segment dicts for the first that matches, or ``None`` so the
caller can fall through to its generic key cascade.

A recurring trap worth knowing about: **time units are not consistent across
vendors.** Whisper and Deepgram use float seconds, whisper.cpp offsets and
AssemblyAI use integer milliseconds, and Whisper's ``.tsv`` writer uses integer
milliseconds too. Each parser converts to seconds at its boundary, so everything
downstream is uniformly in seconds.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Optional

from .core import group_words_into_turns, normalize_words, to_seconds

__all__ = [
    "detect_asr",
    "parse_whisper_cpp",
    "parse_whisper_tsv",
    "parse_aws_transcribe",
    "parse_deepgram",
    "parse_assemblyai",
    "parse_revai",
    "looks_like_whisper_tsv",
]


def detect_asr(data: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Return segments if ``data`` matches a known vendor shape, else ``None``."""
    for matches, parse in _PROBES:
        if matches(data):
            return parse(data)
    return None


# ---------------------------------------------------------------------------
# whisper.cpp
# ---------------------------------------------------------------------------

def _is_whisper_cpp(data: Dict[str, Any]) -> bool:
    transcription = data.get("transcription")
    if not isinstance(transcription, list) or not transcription:
        return False
    first = transcription[0]
    return isinstance(first, dict) and ("offsets" in first or "timestamps" in first)


def parse_whisper_cpp(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse whisper.cpp JSON output.

    Shape: ``{"transcription": [{"timestamps": {"from": "00:00:00,000", "to": ...},
    "offsets": {"from": 0, "to": 1200}, "text": " hello"}]}``. ``offsets`` are
    **milliseconds**; ``timestamps`` are SRT-style strings. Offsets are preferred
    because they avoid a string parse and keep sub-millisecond ordering stable.
    """
    segments: List[Dict[str, Any]] = []
    for row in data.get("transcription") or []:
        if not isinstance(row, dict):
            continue

        offsets = row.get("offsets")
        if isinstance(offsets, dict) and offsets.get("from") is not None:
            start = float(offsets["from"]) / 1000.0
            end = float(offsets.get("to", offsets["from"])) / 1000.0
        else:
            stamps = row.get("timestamps") or {}
            start = to_seconds(stamps.get("from"))
            end = to_seconds(stamps.get("to")) or start

        text = str(row.get("text") or "").strip()
        if not text:
            continue
        segments.append({"speaker": None, "start": start, "end": end, "text": text})

    return segments


# ---------------------------------------------------------------------------
# Whisper .tsv
# ---------------------------------------------------------------------------

def looks_like_whisper_tsv(text: str) -> bool:
    """Whisper's ``--output_format tsv`` writes a ``start\\tend\\ttext`` header."""
    first_line = text.lstrip().split("\n", 1)[0].strip().lower()
    return first_line.replace(" ", "") in ("start\tend\ttext", "start\tend\ttext\t")


def parse_whisper_tsv(text: str) -> List[Dict[str, Any]]:
    """Parse Whisper's TSV output. ``start``/``end`` columns are milliseconds."""
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    segments: List[Dict[str, Any]] = []

    for row in reader:
        if len(row) < 3:
            continue
        if row[0].strip().lower() == "start":  # header
            continue
        try:
            start = float(row[0]) / 1000.0
            end = float(row[1]) / 1000.0
        except (TypeError, ValueError):
            continue
        content = row[2].strip()
        if not content:
            continue
        segments.append({"speaker": None, "start": start, "end": end, "text": content})

    return segments


# ---------------------------------------------------------------------------
# AWS Transcribe
# ---------------------------------------------------------------------------

def _is_aws(data: Dict[str, Any]) -> bool:
    results = data.get("results")
    if not isinstance(results, dict):
        return False
    return isinstance(results.get("items"), list) or isinstance(
        results.get("audio_segments"), list
    )


def parse_aws_transcribe(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse Amazon Transcribe output.

    Newer jobs include a ready-made ``results.audio_segments`` array with speaker
    labels already attached, which is used when present. Older output only has
    the flat ``results.items`` word stream plus a separate
    ``results.speaker_labels`` index, so words are joined to speakers by time and
    then grouped into turns.
    """
    results = data.get("results") or {}

    audio_segments = results.get("audio_segments")
    if isinstance(audio_segments, list) and audio_segments:
        segments: List[Dict[str, Any]] = []
        for row in audio_segments:
            if not isinstance(row, dict):
                continue
            text = str(row.get("transcript") or "").strip()
            if not text:
                continue
            segments.append({
                "speaker": row.get("speaker_label"),
                "start": to_seconds(row.get("start_time")),
                "end": to_seconds(row.get("end_time")),
                "text": text,
            })
        return segments

    speaker_spans = _aws_speaker_spans(results.get("speaker_labels"))
    words: List[Dict[str, Any]] = []

    for item in results.get("items") or []:
        if not isinstance(item, dict):
            continue
        alternatives = item.get("alternatives") or []
        content = alternatives[0].get("content") if alternatives else None
        if not content:
            continue

        # Punctuation items have no timing; glue them onto the previous word so
        # the rendered text reads naturally.
        if item.get("type") == "punctuation":
            if words:
                words[-1]["word"] = f"{words[-1]['word']}{content}"
            continue

        start = to_seconds(item.get("start_time"))
        end = to_seconds(item.get("end_time")) or start
        word: Dict[str, Any] = {"word": content, "start": start, "end": end}

        confidence = alternatives[0].get("confidence")
        try:
            if confidence is not None:
                word["confidence"] = float(confidence)
        except (TypeError, ValueError):
            pass

        speaker = item.get("speaker_label") or _speaker_at(speaker_spans, start)
        if speaker:
            word["speaker"] = speaker
        words.append(word)

    return group_words_into_turns(words)


def _aws_speaker_spans(speaker_labels: Any) -> List[Dict[str, Any]]:
    """Flatten ``results.speaker_labels.segments`` into sortable time spans."""
    spans: List[Dict[str, Any]] = []
    if not isinstance(speaker_labels, dict):
        return spans
    for seg in speaker_labels.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        label = seg.get("speaker_label")
        if not label:
            continue
        spans.append({
            "start": to_seconds(seg.get("start_time")),
            "end": to_seconds(seg.get("end_time")),
            "speaker": label,
        })
    spans.sort(key=lambda s: s["start"])
    return spans


def _speaker_at(spans: List[Dict[str, Any]], time: float) -> Optional[str]:
    for span in spans:
        if span["start"] <= time <= span["end"]:
            return span["speaker"]
    return None


# ---------------------------------------------------------------------------
# Deepgram
# ---------------------------------------------------------------------------

def _is_deepgram(data: Dict[str, Any]) -> bool:
    results = data.get("results")
    if not isinstance(results, dict):
        return False
    if isinstance(results.get("utterances"), list):
        return True
    channels = results.get("channels")
    return isinstance(channels, list) and bool(channels)


def parse_deepgram(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse Deepgram's response.

    With ``utterances=true`` the API returns pre-segmented turns, which is the
    best source. Otherwise the first channel's top alternative carries a flat
    word list (with a ``speaker`` index per word when diarization ran), which is
    grouped into turns.
    """
    results = data.get("results") or {}

    utterances = results.get("utterances")
    if isinstance(utterances, list) and utterances:
        segments: List[Dict[str, Any]] = []
        for utt in utterances:
            if not isinstance(utt, dict):
                continue
            text = str(utt.get("transcript") or "").strip()
            if not text:
                continue
            segment: Dict[str, Any] = {
                "speaker": _speaker_label(utt.get("speaker")),
                "start": to_seconds(utt.get("start")),
                "end": to_seconds(utt.get("end")),
                "text": text,
            }
            words = normalize_words(utt.get("words"))
            if words:
                segment["words"] = words
            confidence = utt.get("confidence")
            if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
                segment["confidence"] = float(confidence)
            segments.append(segment)
        return segments

    channels = results.get("channels") or []
    if not channels or not isinstance(channels[0], dict):
        return []
    alternatives = channels[0].get("alternatives") or []
    if not alternatives or not isinstance(alternatives[0], dict):
        return []

    raw_words = alternatives[0].get("words") or []
    words: List[Dict[str, Any]] = []
    for raw in raw_words:
        if not isinstance(raw, dict):
            continue
        normalized = normalize_words([raw])
        if not normalized:
            continue
        word = normalized[0]
        speaker = _speaker_label(raw.get("speaker"))
        if speaker:
            word["speaker"] = speaker
        words.append(word)

    if words:
        return group_words_into_turns(words)

    # Diarization off and word timings absent — fall back to the flat transcript.
    text = str(alternatives[0].get("transcript") or "").strip()
    return [{"speaker": None, "start": 0.0, "end": 0.0, "text": text}] if text else []


def _speaker_label(value: Any) -> Optional[str]:
    """Deepgram/AssemblyAI speakers are ints or short letters; normalize to str."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return f"speaker_{value}"
    text = str(value).strip()
    return text or None


# ---------------------------------------------------------------------------
# AssemblyAI
# ---------------------------------------------------------------------------

def _is_assemblyai(data: Dict[str, Any]) -> bool:
    if not isinstance(data.get("text"), str):
        return False
    return isinstance(data.get("words"), list) or isinstance(data.get("utterances"), list)


def parse_assemblyai(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse AssemblyAI's transcript object. **All times are milliseconds.**"""
    utterances = data.get("utterances")
    if isinstance(utterances, list) and utterances:
        segments: List[Dict[str, Any]] = []
        for utt in utterances:
            if not isinstance(utt, dict):
                continue
            text = str(utt.get("text") or "").strip()
            if not text:
                continue
            segment: Dict[str, Any] = {
                "speaker": _speaker_label(utt.get("speaker")),
                "start": _ms(utt.get("start")),
                "end": _ms(utt.get("end")),
                "text": text,
            }
            words = _assemblyai_words(utt.get("words"))
            if words:
                segment["words"] = words
            confidence = utt.get("confidence")
            if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
                segment["confidence"] = float(confidence)
            segments.append(segment)
        return segments

    words = _assemblyai_words(data.get("words"), keep_speaker=True)
    if words:
        return group_words_into_turns(words)

    text = str(data.get("text") or "").strip()
    return [{"speaker": None, "start": 0.0, "end": 0.0, "text": text}] if text else []


def _assemblyai_words(
    raw_words: Any,
    *,
    keep_speaker: bool = False,
) -> List[Dict[str, Any]]:
    """Convert AssemblyAI words, rescaling milliseconds to seconds."""
    if not isinstance(raw_words, list):
        return []
    words: List[Dict[str, Any]] = []
    for raw in raw_words:
        if not isinstance(raw, dict):
            continue
        text = raw.get("text") or raw.get("word")
        if not text:
            continue
        word: Dict[str, Any] = {
            "word": str(text),
            "start": _ms(raw.get("start")),
            "end": _ms(raw.get("end")),
        }
        confidence = raw.get("confidence")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            word["confidence"] = float(confidence)
        if keep_speaker:
            speaker = _speaker_label(raw.get("speaker"))
            if speaker:
                word["speaker"] = speaker
        words.append(word)
    return words


def _ms(value: Any) -> float:
    """Milliseconds -> seconds."""
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Rev.ai
# ---------------------------------------------------------------------------

def _is_revai(data: Dict[str, Any]) -> bool:
    monologues = data.get("monologues")
    return isinstance(monologues, list) and bool(monologues)


def parse_revai(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse Rev.ai output.

    Each monologue is one speaker's stretch of speech, built from ``elements``
    of type ``text`` (words, with ``ts``/``end_ts``) interleaved with
    ``punct``/``unknown`` elements that carry spacing and punctuation.
    """
    segments: List[Dict[str, Any]] = []

    for monologue in data.get("monologues") or []:
        if not isinstance(monologue, dict):
            continue
        speaker = _speaker_label(monologue.get("speaker"))

        pieces: List[str] = []
        words: List[Dict[str, Any]] = []
        for element in monologue.get("elements") or []:
            if not isinstance(element, dict):
                continue
            value = element.get("value")
            if value is None:
                continue
            pieces.append(str(value))
            if element.get("type") != "text":
                continue
            word: Dict[str, Any] = {
                "word": str(value),
                "start": to_seconds(element.get("ts")),
                "end": to_seconds(element.get("end_ts")),
            }
            confidence = element.get("confidence")
            if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
                word["confidence"] = float(confidence)
            words.append(word)

        text = "".join(pieces).strip()
        if not text:
            continue

        segment: Dict[str, Any] = {
            "speaker": speaker,
            "start": words[0]["start"] if words else 0.0,
            "end": words[-1]["end"] if words else 0.0,
            "text": text,
        }
        if words:
            segment["words"] = words
        segments.append(segment)

    return segments


# Order matters: the more specific signatures are probed before the looser ones.
_PROBES = [
    (_is_whisper_cpp, parse_whisper_cpp),
    (_is_aws, parse_aws_transcribe),
    (_is_deepgram, parse_deepgram),
    (_is_assemblyai, parse_assemblyai),
    (_is_revai, parse_revai),
]


def parse_json_string(text: str) -> Optional[Any]:
    """Parse a JSON string, returning ``None`` rather than raising."""
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None
