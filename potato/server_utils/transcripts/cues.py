"""
Subtitle / caption cue formats.

These are the formats you get from subtitle files rather than from an ASR API:
SubRip, WebVTT, SubStation Alpha, TTML, and the JSON/XML caption formats YouTube
serves (which ``yt-dlp`` will happily hand you).

Every parser here returns a list of *segment dicts* in the loose intermediate
shape (``speaker``/``start``/``end``/``text``) that
:func:`potato.server_utils.transcripts.core.normalize_segment` consumes.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from .core import ARROW_RE, extract_cue_speaker, to_seconds

__all__ = [
    "parse_string_transcript",
    "parse_cues",
    "parse_ass",
    "parse_ttml",
    "parse_json3",
    "parse_srv1",
    "looks_like_ass",
    "looks_like_ttml",
]


def parse_string_transcript(text: str) -> List[Dict[str, Any]]:
    """Parse any string transcript into segment dicts.

    Sniffs the markup-bearing formats first (they are unambiguous), then falls
    back to cue-arrow parsing for SRT/VTT, then to a single untimed turn so a
    plain pasted paragraph still renders as one bubble.
    """
    stripped = text.strip()
    if not stripped:
        return []

    if looks_like_ass(stripped):
        return parse_ass(stripped)
    if looks_like_ttml(stripped):
        return parse_ttml(stripped)

    if not ARROW_RE.search(stripped):
        return [{"speaker": None, "start": 0.0, "end": 0.0, "text": stripped}]
    return parse_cues(stripped)


# ---------------------------------------------------------------------------
# SRT / WebVTT
# ---------------------------------------------------------------------------

def parse_cues(text: str) -> List[Dict[str, Any]]:
    """Parse VTT/SRT cue blocks (blank-line separated).

    The two formats differ only in the millisecond separator (``.`` vs ``,``)
    and the optional ``WEBVTT`` header, both of which are handled here, so there
    is no need to know which one you have.
    """
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
            if ARROW_RE.search(ln):
                arrow_idx = idx
                break
        if arrow_idx is None:
            continue

        arrow = ARROW_RE.search(lines[arrow_idx])
        start = to_seconds(arrow.group(1))
        end = to_seconds(arrow.group(2))
        raw_text = "\n".join(lines[arrow_idx + 1:]).strip()
        speaker, clean = extract_cue_speaker(raw_text)
        segments.append({"speaker": speaker, "start": start, "end": end, "text": clean})

    return segments


# ---------------------------------------------------------------------------
# SubStation Alpha (.ass / .ssa)
# ---------------------------------------------------------------------------

_ASS_TS_RE = re.compile(r"^\d+:\d{2}:\d{2}[.,]\d{1,3}$")
# ASS override blocks: {\an8}, {\i1}, ... and the \N / \h escapes.
_ASS_OVERRIDE_RE = re.compile(r"\{[^}]*\}")
_ASS_ESCAPE_RE = re.compile(r"\\[Nnh]")


def looks_like_ass(text: str) -> bool:
    head = text[:2000]
    return "[Script Info]" in head or "[V4+ Styles]" in head or bool(
        re.search(r"^Dialogue:\s", head, re.MULTILINE)
    )


def parse_ass(text: str) -> List[Dict[str, Any]]:
    """Parse SubStation Alpha ``Dialogue:`` events.

    The ``Format:`` line inside ``[Events]`` declares the field order, which is
    not fixed across files, so field positions are read from it rather than
    assumed. The ``Name`` field carries the speaker in most subtitle sets that
    bother to fill it in.
    """
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    fields: List[str] = []
    segments: List[Dict[str, Any]] = []

    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.lower().startswith("format:"):
            fields = [f.strip().lower() for f in stripped.split(":", 1)[1].split(",")]
            continue
        if not stripped.lower().startswith("dialogue:"):
            continue
        if not fields:
            # No Format: line seen — fall back to the near-universal default.
            fields = [
                "layer", "start", "end", "style", "name",
                "marginl", "marginr", "marginv", "effect", "text",
            ]

        # The text field is last and may itself contain commas, so split only
        # as many times as there are preceding fields.
        payload = stripped.split(":", 1)[1]
        parts = [p.strip() for p in payload.split(",", len(fields) - 1)]
        if len(parts) < len(fields):
            continue
        row = dict(zip(fields, parts))

        start = _ass_time(row.get("start"))
        end = _ass_time(row.get("end"))
        if start is None:
            continue

        raw_text = row.get("text", "")
        clean = _ASS_OVERRIDE_RE.sub("", raw_text)
        clean = _ASS_ESCAPE_RE.sub(" ", clean).strip()

        speaker = (row.get("name") or "").strip() or None
        if speaker is None:
            speaker, clean = extract_cue_speaker(clean)

        segments.append({
            "speaker": speaker,
            "start": start,
            "end": end if end is not None else start,
            "text": clean,
        })

    return segments


def _ass_time(value: Optional[str]) -> Optional[float]:
    """ASS timestamps are ``H:MM:SS.cc`` (centiseconds, single-digit hour)."""
    if not value:
        return None
    value = value.strip()
    if not _ASS_TS_RE.match(value):
        return None
    return to_seconds(value)


# ---------------------------------------------------------------------------
# TTML / DFXP
# ---------------------------------------------------------------------------

def looks_like_ttml(text: str) -> bool:
    head = text[:2000].lstrip()
    if not head.startswith("<"):
        return False
    return "<tt" in head or "ttml" in head.lower() or "<transcript" in head


# TTML clock times: "00:00:12.500", "12.5s", "1250ms", "00:00:12:15" (frames).
_TTML_OFFSET_RE = re.compile(r"^([\d.]+)(h|m|s|ms|f|t)$")


def parse_ttml(text: str) -> List[Dict[str, Any]]:
    """Parse TTML / DFXP captions, and YouTube's ``srv1``-style XML.

    YouTube's oldest caption endpoint returns ``<transcript><text start dur>``
    rather than real TTML; the two are close enough in structure that one walker
    handles both, distinguished by which timing attributes are present.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []

    segments: List[Dict[str, Any]] = []
    for elem in root.iter():
        tag = _localname(elem.tag)
        if tag not in ("p", "text"):
            continue

        begin = elem.get("begin") or elem.get("start")
        if begin is None:
            continue
        start = _ttml_time(begin)

        end_attr = elem.get("end")
        if end_attr is not None:
            end = _ttml_time(end_attr)
        else:
            dur = elem.get("dur") or elem.get("duration")
            end = start + _ttml_time(dur) if dur is not None else start

        content = _element_text(elem)
        if not content:
            continue

        speaker = elem.get("speaker") or elem.get("agent") or None
        if speaker is None:
            speaker, content = extract_cue_speaker(content)

        segments.append({
            "speaker": speaker,
            "start": start,
            "end": end,
            "text": content,
        })

    return segments


def _localname(tag: str) -> str:
    """Strip the XML namespace, which varies across TTML profiles."""
    return tag.rsplit("}", 1)[-1].lower() if "}" in tag else tag.lower()


def _element_text(elem: ET.Element) -> str:
    """Flatten an element's text, turning ``<br/>`` into a space."""
    parts: List[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if _localname(child.tag) == "br":
            parts.append(" ")
        else:
            parts.append(_element_text(child))
        if child.tail:
            parts.append(child.tail)
    return _unescape_ws(" ".join(p for p in parts if p))


def _unescape_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _ttml_time(value: Optional[str]) -> float:
    """Parse a TTML time expression (clock time or offset time)."""
    if value is None:
        return 0.0
    value = value.strip()
    if not value:
        return 0.0

    offset = _TTML_OFFSET_RE.match(value)
    if offset:
        amount = float(offset.group(1))
        unit = offset.group(2)
        if unit == "h":
            return amount * 3600
        if unit == "m":
            return amount * 60
        if unit == "ms":
            return amount / 1000.0
        # "s" — and "f"/"t" (frames/ticks) have no usable rate here, so treat
        # the bare number as seconds rather than silently producing nonsense.
        return amount

    # Clock time. ``HH:MM:SS:FF`` (frames) appears in broadcast profiles; the
    # frame field is dropped since the frame rate lives in the document header.
    parts = value.split(":")
    if len(parts) == 4:
        value = ":".join(parts[:3])
    return to_seconds(value)


# ---------------------------------------------------------------------------
# YouTube json3 / srv3
# ---------------------------------------------------------------------------

def parse_json3(data: Any) -> List[Dict[str, Any]]:
    """Parse YouTube's ``json3`` caption format.

    Shape: ``{"events": [{"tStartMs": 0, "dDurationMs": 1200,
    "segs": [{"utf8": "hello"}]}]}``. Events without ``segs`` are formatting or
    window-definition records and carry no text; auto-caption streams also emit
    rolling duplicate events whose segments have per-word ``tOffsetMs``, which
    are preserved as word timings.
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            return []
    if not isinstance(data, dict):
        return []

    events = data.get("events")
    if not isinstance(events, list):
        return []

    segments: List[Dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        segs = event.get("segs")
        if not isinstance(segs, list):
            continue

        start_ms = event.get("tStartMs")
        if start_ms is None:
            continue
        start = float(start_ms) / 1000.0
        dur_ms = event.get("dDurationMs")
        end = start + (float(dur_ms) / 1000.0 if dur_ms is not None else 0.0)

        words: List[Dict[str, Any]] = []
        pieces: List[str] = []
        for seg in segs:
            if not isinstance(seg, dict):
                continue
            piece = seg.get("utf8")
            if not isinstance(piece, str):
                continue
            pieces.append(piece)
            token = piece.strip()
            if not token:
                continue
            offset_ms = seg.get("tOffsetMs")
            word_start = start + (float(offset_ms) / 1000.0 if offset_ms is not None else 0.0)
            words.append({"word": token, "start": word_start, "end": end})

        text = "".join(pieces).strip()
        if not text:
            continue

        speaker, text = extract_cue_speaker(text)
        segment: Dict[str, Any] = {
            "speaker": speaker,
            "start": start,
            "end": end,
            "text": text,
        }
        # Only meaningful when the stream actually carried per-word offsets.
        if len(words) > 1:
            segment["words"] = words
        segments.append(segment)

    return segments


def parse_srv1(text: str) -> List[Dict[str, Any]]:
    """YouTube ``srv1``/``srv2`` XML — handled by the TTML walker."""
    return parse_ttml(text)
