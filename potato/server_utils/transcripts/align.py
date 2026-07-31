"""
Forced-alignment and linguistic annotation formats (import).

These come out of phonetics and language-documentation toolchains rather than
off a transcription API: NIST CTM from forced aligners and ASR scoring,
Praat TextGrid, and ELAN's EAF.

Potato already *exports* EAF and TextGrid (``potato/export/eaf_exporter.py``,
``potato/export/textgrid_exporter.py``). The parsers here close the loop so a
tiered annotation can round-trip out to ELAN or Praat, be corrected there, and
come back in.

One shared convention: a **tier is a speaker**. Both TextGrid and EAF organize
time-aligned text into named tiers, which in speech corpora almost always means
one tier per participant, so the tier name (or EAF's ``PARTICIPANT`` attribute)
becomes the turn's speaker and the tiers are merged into a single chronological
turn list.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from .core import group_words_into_turns, to_seconds

__all__ = [
    "parse_ctm",
    "parse_textgrid",
    "parse_eaf",
    "looks_like_ctm",
    "looks_like_textgrid",
    "looks_like_eaf",
]


# ---------------------------------------------------------------------------
# NIST CTM
# ---------------------------------------------------------------------------

# "<file> <channel> <start> <duration> <token> [confidence]"
_CTM_ROW_RE = re.compile(
    r"^(\S+)\s+(\S+)\s+([\d.]+)\s+([\d.]+)\s+(\S+)(?:\s+([\d.]+))?\s*$"
)


def looks_like_ctm(text: str) -> bool:
    """A CTM is whitespace-columned rows whose 3rd and 4th fields are numbers."""
    matched = 0
    for line in text.replace("\r\n", "\n").split("\n")[:20]:
        stripped = line.strip()
        if not stripped or stripped.startswith(";;"):
            continue
        if not _CTM_ROW_RE.match(stripped):
            return False
        matched += 1
        if matched >= 3:
            return True
    return matched > 0


def parse_ctm(text: str, *, pause_threshold: float = 0.8) -> List[Dict[str, Any]]:
    """Parse a CTM word-alignment file into turns.

    CTM is one token per line with a start and a *duration* (not an end time),
    and no turn structure at all, so words are grouped on speaker change or a
    pause. The channel field carries the speaker in multi-party CTMs; where it
    is just ``1`` or ``A`` for the whole file, everything lands in one speaker
    and the annotator can reassign.
    """
    words: List[Dict[str, Any]] = []
    channels = set()

    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith(";;"):
            continue
        match = _CTM_ROW_RE.match(stripped)
        if not match:
            continue

        _file, channel, start_s, dur_s, token, conf_s = match.groups()
        try:
            start = float(start_s)
            duration = float(dur_s)
        except ValueError:
            continue

        channels.add(channel)
        word: Dict[str, Any] = {
            "word": token,
            "start": start,
            "end": start + duration,
            "speaker": channel,
        }
        if conf_s:
            try:
                word["confidence"] = float(conf_s)
            except ValueError:
                pass
        words.append(word)

    # A single channel carries no speaker information — drop the marker so the
    # turns read as undiarized rather than all being "channel 1".
    if len(channels) <= 1:
        for word in words:
            word.pop("speaker", None)

    words.sort(key=lambda w: w["start"])
    return group_words_into_turns(words, pause_threshold=pause_threshold)


# ---------------------------------------------------------------------------
# Praat TextGrid
# ---------------------------------------------------------------------------

def looks_like_textgrid(text: str) -> bool:
    head = text[:400]
    return 'File type = "ooTextFile"' in head and "TextGrid" in head


_TG_NUMBER_RE = re.compile(r"^\s*(?:xmin|xmax|number)\s*=\s*([\d.eE+-]+)", re.IGNORECASE)
_TG_TEXT_RE = re.compile(r'^\s*(?:text|mark)\s*=\s*"(.*)"\s*$', re.IGNORECASE | re.DOTALL)
_TG_NAME_RE = re.compile(r'^\s*name\s*=\s*"(.*)"\s*$', re.IGNORECASE)
_TG_CLASS_RE = re.compile(r'^\s*class\s*=\s*"(.*)"\s*$', re.IGNORECASE)


def parse_textgrid(text: str) -> List[Dict[str, Any]]:
    """Parse a Praat TextGrid into turns, one per non-empty interval.

    Handles both the long (``xmin = 0.5``) and short (bare values on their own
    lines) serializations, since Praat writes either depending on how the file
    was saved. Point tiers are read as zero-length turns; empty intervals — the
    silences that make up most of a TextGrid — are skipped.
    """
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = body.split("\n")

    if any("=" in ln and _TG_CLASS_RE.match(ln) for ln in lines):
        segments = _parse_textgrid_long(lines)
    else:
        segments = _parse_textgrid_short(lines)

    segments.sort(key=lambda s: (s["start"], s["end"]))
    return segments


def _parse_textgrid_long(lines: List[str]) -> List[Dict[str, Any]]:
    segments: List[Dict[str, Any]] = []
    tier_name: Optional[str] = None
    in_tier_header = False
    start: Optional[float] = None
    end: Optional[float] = None

    for line in lines:
        class_match = _TG_CLASS_RE.match(line)
        if class_match:
            in_tier_header = True
            tier_name = None
            start = end = None
            continue

        name_match = _TG_NAME_RE.match(line)
        if name_match and in_tier_header:
            tier_name = name_match.group(1).strip() or None
            in_tier_header = False
            start = end = None
            continue

        number_match = _TG_NUMBER_RE.match(line)
        if number_match:
            try:
                value = float(number_match.group(1))
            except ValueError:
                continue
            # The first number after an interval marker is xmin, the second xmax.
            if start is None:
                start = value
            elif end is None:
                end = value
            else:
                start, end = value, None
            continue

        text_match = _TG_TEXT_RE.match(line)
        if text_match:
            content = _tg_unescape(text_match.group(1))
            if content and start is not None:
                segments.append({
                    "speaker": tier_name,
                    "start": start,
                    "end": end if end is not None else start,
                    "text": content,
                })
            start = end = None

    return segments


def _parse_textgrid_short(lines: List[str]) -> List[Dict[str, Any]]:
    """Short-format TextGrids are a bare token stream, read positionally."""
    tokens = [ln.strip() for ln in lines if ln.strip()]
    segments: List[Dict[str, Any]] = []

    i = 0
    # Skip the two header lines plus the file-level xmin/xmax/exists/size.
    while i < len(tokens) and not tokens[i].startswith('"IntervalTier"') \
            and not tokens[i].startswith('"TextTier"'):
        i += 1

    while i < len(tokens):
        tier_class = tokens[i].strip('"')
        i += 1
        if i >= len(tokens):
            break
        tier_name = tokens[i].strip('"') or None
        # Past the tier's own name, xmin and xmax, landing on the interval count.
        i += 3
        if i >= len(tokens):
            break
        try:
            count = int(float(tokens[i]))
        except (ValueError, IndexError):
            break
        i += 1

        is_point_tier = tier_class == "TextTier"
        for _ in range(count):
            if is_point_tier:
                if i + 1 >= len(tokens):
                    break
                start = _tg_float(tokens[i])
                end = start
                content = _tg_unescape(tokens[i + 1].strip('"'))
                i += 2
            else:
                if i + 2 >= len(tokens):
                    break
                start = _tg_float(tokens[i])
                end = _tg_float(tokens[i + 1])
                content = _tg_unescape(tokens[i + 2].strip('"'))
                i += 3

            if content and start is not None:
                segments.append({
                    "speaker": tier_name,
                    "start": start,
                    "end": end if end is not None else start,
                    "text": content,
                })

        # Next tier, if any.
        while i < len(tokens) and tokens[i] not in ('"IntervalTier"', '"TextTier"'):
            i += 1

    return segments


def _tg_float(token: str) -> Optional[float]:
    try:
        return float(token)
    except (TypeError, ValueError):
        return None


def _tg_unescape(value: str) -> str:
    """Praat escapes an embedded quote by doubling it."""
    return value.replace('""', '"').strip()


# ---------------------------------------------------------------------------
# ELAN EAF
# ---------------------------------------------------------------------------

def looks_like_eaf(text: str) -> bool:
    head = text[:2000]
    return "ANNOTATION_DOCUMENT" in head


def parse_eaf(text: str) -> List[Dict[str, Any]]:
    """Parse an ELAN EAF document into turns.

    EAF stores times once in a ``TIME_ORDER`` table and has annotations
    reference slots by id, so slots are resolved first. Two annotation kinds
    exist: ``ALIGNABLE_ANNOTATION`` carries its own slot refs, while
    ``REF_ANNOTATION`` on a dependent tier borrows the timing of the parent
    annotation it points at — those are resolved in a second pass, since a
    dependent annotation can appear before its parent in document order.

    Speaker comes from the tier's ``PARTICIPANT`` attribute when set, else the
    ``TIER_ID``. ``TIME_VALUE`` is milliseconds.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []

    # Time slots: id -> seconds.
    slots: Dict[str, float] = {}
    for slot in root.iter("TIME_SLOT"):
        slot_id = slot.get("TIME_SLOT_ID")
        value = slot.get("TIME_VALUE")
        if slot_id is None:
            continue
        try:
            slots[slot_id] = float(value) / 1000.0 if value is not None else 0.0
        except (TypeError, ValueError):
            slots[slot_id] = 0.0

    media = _eaf_media(root)

    # First pass: aligned annotations, indexed by id so refs can find them.
    by_id: Dict[str, Dict[str, Any]] = {}
    pending_refs: List[Dict[str, Any]] = []
    segments: List[Dict[str, Any]] = []

    for tier in root.iter("TIER"):
        speaker = tier.get("PARTICIPANT") or tier.get("TIER_ID") or None
        if speaker is not None:
            speaker = speaker.strip() or None

        for annotation in tier.iter("ANNOTATION"):
            aligned = annotation.find("ALIGNABLE_ANNOTATION")
            if aligned is not None:
                content = _eaf_value(aligned)
                if not content:
                    continue
                segment = {
                    "speaker": speaker,
                    "start": slots.get(aligned.get("TIME_SLOT_REF1", ""), 0.0),
                    "end": slots.get(aligned.get("TIME_SLOT_REF2", ""), 0.0),
                    "text": content,
                }
                if media:
                    segment["media_url"] = media
                annotation_id = aligned.get("ANNOTATION_ID")
                if annotation_id:
                    by_id[annotation_id] = segment
                segments.append(segment)
                continue

            ref = annotation.find("REF_ANNOTATION")
            if ref is not None:
                content = _eaf_value(ref)
                if not content:
                    continue
                pending_refs.append({
                    "speaker": speaker,
                    "text": content,
                    "ref": ref.get("ANNOTATION_REF"),
                    "id": ref.get("ANNOTATION_ID"),
                })

    # Second pass: borrow timing from the referenced parent annotation.
    for pending in pending_refs:
        parent = by_id.get(pending.get("ref") or "")
        segment = {
            "speaker": pending["speaker"],
            "start": parent["start"] if parent else 0.0,
            "end": parent["end"] if parent else 0.0,
            "text": pending["text"],
        }
        if media:
            segment["media_url"] = media
        if pending.get("id"):
            by_id[pending["id"]] = segment
        segments.append(segment)

    segments.sort(key=lambda s: (s["start"], s["end"]))
    return segments


def _eaf_value(element: ET.Element) -> str:
    value = element.find("ANNOTATION_VALUE")
    if value is None or value.text is None:
        return ""
    return value.text.strip()


def _eaf_media(root: ET.Element) -> Optional[str]:
    """Pull the first media reference out of the EAF header."""
    for descriptor in root.iter("MEDIA_DESCRIPTOR"):
        url = descriptor.get("RELATIVE_MEDIA_URL") or descriptor.get("MEDIA_URL")
        if url:
            return url.strip()
    header = root.find("HEADER")
    if header is not None:
        media_file = header.get("MEDIA_FILE")
        if media_file:
            return media_file.strip()
    return None
