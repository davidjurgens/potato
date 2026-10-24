"""
Reading and writing the time-frequency box tables bioacoustics tools exchange.

Three formats, one box shape. A box is a dict::

    {"start_s": 1.25, "end_s": 1.9, "low_hz": 2500.0, "high_hz": 6200.0,
     "label": "Turdus migratorius"}

``low_hz`` / ``high_hz`` are ``None`` when the source gives a time span only
(an Audacity label without a spectral line, a BirdNET CSV row); the
spectrogram scheme draws those as full-height bands. Optional keys are carried
through when the source has them: ``confidence``, ``channel`` and the
provenance keys of :data:`potato.export.cv_utils.PROVENANCE_KEYS`.

Raven selection tables
    Tab-separated with a header row. The columns this module reads are
    ``Selection``, ``View``, ``Channel``, ``Begin Time (s)``, ``End Time (s)``,
    ``Low Freq (Hz)``, ``High Freq (Hz)``, and for multi-file tables
    ``Begin File`` / ``Begin Path`` and ``File Offset (s)``. Raven writes one
    row per view (``Waveform 1``, ``Spectrogram 1``) for the same selection;
    those rows are merged by selection number. Any other column is an
    annotation column, and the label comes from one of them.

Audacity label tracks
    ``start<TAB>end<TAB>label`` per line. A label with a spectral selection is
    followed by a line ``\\<TAB>low<TAB>high``.

BirdNET-Analyzer output
    Either its Raven-format selection table (the columns above plus
    ``Common Name``, ``Species Code`` / ``Scientific Name`` and
    ``Confidence``) or its CSV (``Start (s)``, ``End (s)``, ``Scientific
    name``, ``Common name``, ``Confidence``, and in newer versions ``File``).
    Potato only reads these files; the BirdNET models are licensed
    CC BY-NC-SA and are not part of Potato.
"""

from __future__ import annotations

import csv
import io
import math
import os
import re
from typing import Any, Dict, Iterable, List, Optional

RAVEN_BEGIN = "Begin Time (s)"
RAVEN_END = "End Time (s)"
RAVEN_LOW = "Low Freq (Hz)"
RAVEN_HIGH = "High Freq (Hz)"

#: Raven's own columns: measurements and bookkeeping, never a label.
RAVEN_STANDARD_COLUMNS = frozenset({
    "Selection", "View", "Channel", RAVEN_BEGIN, RAVEN_END, RAVEN_LOW, RAVEN_HIGH,
    "Begin File", "End File", "Begin Path", "End Path", "File Offset (s)",
    "Begin Date", "End Date", "Begin Clock Time", "End Clock Time", "Begin Date Time",
    "Delta Time (s)", "Delta Freq (Hz)", "Confidence", "Rank", "Sound Files",
})

#: Annotation columns tried, in order, when no label column is named.
RAVEN_LABEL_COLUMNS = ("Annotation", "Species", "Label", "Class", "Scientific Name",
                       "Common Name", "Species Code", "Call Type", "Type", "Sound Type")

#: BirdNET's columns, in the order the label is taken from them.
BIRDNET_LABEL_COLUMNS = ("Scientific Name", "Scientific name", "Common Name",
                         "Common name", "Species Code")

_NUMBER = re.compile(r"^[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$")


def _float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or not _NUMBER.match(text):
        return None
    number = float(text)
    return number if math.isfinite(number) else None


def _freq(value: Any) -> Optional[float]:
    number = _float(value)
    return None if number is None or number < 0 else number


def _shown(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    return repr(text[:40]) if text else "empty"


def _times(begin_raw: Any, end_raw: Any, where: str,
           problems: Optional[List[str]]) -> Optional[tuple]:
    """``(start, end)`` in order, or None (with a problem noted) when either
    is not a number. Reversed times are swapped, as :func:`normalize_box`
    does for a stored box, rather than collapsed to a zero-length box."""
    begin, end = _float(begin_raw), _float(end_raw)
    if begin is None or end is None:
        if problems is not None:
            bad = begin_raw if begin is None else end_raw
            problems.append(f"{where}: time {_shown(bad)} is not a number (use a "
                            f"point for decimals, e.g. 3.5); row left out")
        return None
    if end < begin:
        if problems is not None:
            problems.append(f"{where}: end time {end} is before start {begin}; swapped")
        begin, end = end, begin
    return begin, end


def _freqs(low_raw: Any, high_raw: Any, where: str,
           problems: Optional[List[str]]) -> tuple:
    """``(low, high)`` Hz. A negative or unreadable frequency is refused with
    a problem noted, instead of turning into a null without a word."""
    out = []
    for raw, name in ((low_raw, "low"), (high_raw, "high")):
        text = str(raw if raw is not None else "").strip()
        value = _freq(raw)
        if value is None and text and problems is not None:
            number = _float(raw)
            reason = "is negative" if number is not None else "is not a number"
            problems.append(f"{where}: {name} frequency {_shown(raw)} {reason}; "
                            f"the value was refused and the box keeps its times only")
        out.append(value)
    low, high = out
    if low is not None and high is not None and high < low:
        low, high = high, low
    return low, high


def _header(text: str) -> List[str]:
    first = text.lstrip("﻿").splitlines()[0] if text.strip() else ""
    return [c.strip() for c in first.split("\t")]


# ---------------------------------------------------------------------------
# Raven
# ---------------------------------------------------------------------------

def looks_like_raven(text: str) -> bool:
    header = _header(text)
    return RAVEN_BEGIN in header and RAVEN_END in header and "Selection" in header


def looks_like_birdnet_raven(text: str) -> bool:
    header = set(_header(text))
    return (looks_like_raven(text) and "Confidence" in header
            and bool(header & {"Species Code", "Common Name", "Scientific Name"}))


def raven_label_column(columns: Iterable[str], preferred: Optional[str] = None) -> Optional[str]:
    """The column the label comes from: the one asked for, a known name, or
    the first column that is not one of Raven's measurements."""
    columns = list(columns)
    if preferred:
        return preferred if preferred in columns else None
    for name in RAVEN_LABEL_COLUMNS:
        if name in columns:
            return name
    for name in columns:
        if name and name not in RAVEN_STANDARD_COLUMNS and "(" not in name:
            return name
    return None


def parse_raven(text: str, label_column: Optional[str] = None,
                prefer: Iterable[str] = RAVEN_LABEL_COLUMNS,
                problems: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Rows of a selection table as boxes, one per selection.

    Each box may carry ``file`` (the base name of ``Begin File`` / ``Begin
    Path``), which a multi-file table needs to say which recording it is in.
    Times are then the offset within that file when ``File Offset (s)`` is
    present. Rows that cannot be read, and values that were changed, are
    described in ``problems`` when a list is given.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")), delimiter="\t")
    columns = [c.strip() for c in (reader.fieldnames or [])]
    reader.fieldnames = columns
    column = next((name for name in prefer if name in columns), None)
    if label_column or column is None:
        column = raven_label_column(columns, label_column)
    if label_column and column is None:
        raise ValueError(f"no column named {label_column!r} in the selection table "
                         f"(columns: {', '.join(columns)})")
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for index, row in enumerate(reader):
        row = {k: (v or "").strip() for k, v in row.items() if isinstance(k, str) and k}
        where = f"line {index + 2}" + (f" (selection {row['Selection']})" if row.get("Selection") else "")
        times = _times(row.get(RAVEN_BEGIN), row.get(RAVEN_END), where, problems)
        if times is None:
            continue
        begin, end = times
        key = row.get("Selection") or f"row{index}"
        view = row.get("View", "")
        box = merged.get(key)
        if box is not None and not view.lower().startswith("spectrogram"):
            continue          # a second view of a selection already read
        offset = _float(row.get("File Offset (s)"))
        source_file = row.get("Begin File") or os.path.basename(
            row.get("Begin Path", "").replace("\\", "/"))
        if offset is not None and source_file:
            begin, end = offset, offset + (end - begin)
        low, high = _freqs(row.get(RAVEN_LOW), row.get(RAVEN_HIGH), where, problems)
        box = {
            "start_s": round(begin, 6),
            "end_s": round(end, 6),
            "low_hz": low,
            "high_hz": high,
            "label": row.get(column, "") if column else "",
        }
        channel = _float(row.get("Channel"))
        if channel is not None and int(channel) != 1:
            box["channel"] = int(channel)
        confidence = _float(row.get("Confidence"))
        if confidence is not None:
            box["confidence"] = confidence
        if source_file:
            box["file"] = source_file
        for extra in ("Common Name", "Species Code"):
            if extra in row and extra != column and row[extra]:
                box.setdefault("attributes", {})[extra] = row[extra]
        if key not in merged:
            order.append(key)
        merged[key] = box
    return [merged[k] for k in order]


def _fmt(value: Optional[float]) -> str:
    if value is None:
        return ""
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def write_raven(boxes: Iterable[Dict[str, Any]], label_column: str = "Annotation",
                default_high_hz: Optional[float] = None) -> str:
    """A Raven selection table (one ``Spectrogram 1`` row per box).

    A box with no frequency extent gets 0 Hz and ``default_high_hz`` (the
    recording's Nyquist frequency when the caller knows it), so Raven draws it
    over the whole spectrogram.
    """
    boxes = list(boxes)
    with_conf = any(b.get("confidence") is not None for b in boxes)
    columns = ["Selection", "View", "Channel", RAVEN_BEGIN, RAVEN_END, RAVEN_LOW,
               RAVEN_HIGH, label_column] + (["Confidence"] if with_conf else [])
    lines = ["\t".join(columns)]
    for i, box in enumerate(sorted(boxes, key=lambda b: (float(b["start_s"]), float(b["end_s"]))),
                            start=1):
        low = box.get("low_hz")
        high = box.get("high_hz")
        if low is None and high is None:
            low, high = 0.0, default_high_hz
        cells = [str(i), "Spectrogram 1", str(int(box.get("channel") or 1)),
                 _fmt(box["start_s"]), _fmt(box["end_s"]), _fmt(low if low is not None else 0.0),
                 _fmt(high), _clean(box.get("label", ""))]
        if with_conf:
            cells.append(_fmt(box.get("confidence")))
        lines.append("\t".join(cells))
    return "\n".join(lines) + "\n"


def _clean(text: Any) -> str:
    return re.sub(r"[\t\r\n]+", " ", str(text or "")).strip()


# ---------------------------------------------------------------------------
# Audacity
# ---------------------------------------------------------------------------

def _is_spectral_line(parts: List[str]) -> bool:
    return len(parts) >= 3 and parts[0].strip() == "\\"


def looks_like_audacity(text: str) -> bool:
    """A label track: its first line is ``start<TAB>end[<TAB>label]`` and
    most of its lines are label or spectral lines. A few bad lines do not stop
    it being one; :func:`parse_audacity` reports them by line number."""
    lines = [l for l in text.lstrip("﻿").splitlines() if l.strip()]
    if not lines:
        return False
    first = lines[0].split("\t")
    if len(first) < 2 or _float(first[0]) is None or _float(first[1]) is None:
        return False
    good = 0
    sample = lines[:2000]
    for line in sample:
        parts = line.split("\t")
        if _is_spectral_line(parts) or (len(parts) >= 2 and _float(parts[0]) is not None
                                        and _float(parts[1]) is not None):
            good += 1
    return good * 2 >= len(sample)


def audacity_problem(text: str) -> Optional[str]:
    """The first line that keeps ``text`` from reading as a label track, as
    ``"line N: ..."``, when the file starts like one; else None."""
    lines = text.lstrip("\ufeff").splitlines()
    numbered = [(n, l) for n, l in enumerate(lines, start=1) if l.strip()]
    if not numbered:
        return None
    labelish = sum(1 for _, l in numbered[:2000] if len(l.split("\t")) >= 2)
    if labelish * 2 <= len(numbered[:2000]):
        return None       # not tab-separated pairs at all: some other file
    for number, line in numbered:
        parts = line.split("\t")
        if _is_spectral_line(parts):
            continue
        if len(parts) < 2:
            return f"line {number} is not start<TAB>end<TAB>label ({_shown(line)})"
        for value in parts[:2]:
            if _float(value) is None:
                return (f"line {number}: time {_shown(value)} is not a number "
                        f"(use a point for decimals, e.g. 3.5)")
    return None


def parse_audacity(text: str, problems: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Boxes of a label track. A line that is neither a label nor a spectral
    line is left out and described in ``problems`` (by line number) when a
    list is given; without one it raises ``ValueError``."""
    boxes: List[Dict[str, Any]] = []
    previous_ok = False
    for number, line in enumerate(text.lstrip("﻿").splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split("\t")
        where = f"line {number}"
        if _is_spectral_line(parts):
            if boxes and previous_ok:
                low, high = _freqs(parts[1], parts[2], where, problems)
                boxes[-1]["low_hz"], boxes[-1]["high_hz"] = low, high
            continue
        if len(parts) < 2:
            if problems is None:
                raise ValueError(f"not an Audacity label line: {line!r}")
            problems.append(f"{where}: not an Audacity label line ({_shown(line)}); left out")
            previous_ok = False
            continue
        if problems is None and (_float(parts[0]) is None or _float(parts[1]) is None):
            raise ValueError(f"not an Audacity label line: {line!r}")
        times = _times(parts[0], parts[1], where, problems)
        previous_ok = times is not None
        if times is None:
            continue
        start, end = times
        boxes.append({"start_s": round(start, 6), "end_s": round(end, 6),
                      "low_hz": None, "high_hz": None,
                      "label": "\t".join(parts[2:]).strip()})
    return boxes


def write_audacity(boxes: Iterable[Dict[str, Any]]) -> str:
    lines = []
    for box in sorted(boxes, key=lambda b: (float(b["start_s"]), float(b["end_s"]))):
        lines.append(f"{float(box['start_s']):.6f}\t{float(box['end_s']):.6f}\t"
                     f"{_clean(box.get('label', ''))}")
        low, high = box.get("low_hz"), box.get("high_hz")
        if low is not None or high is not None:
            lines.append(f"\\\t{float(low or 0.0):.6f}\t{float(high or 0.0):.6f}")
    return "\n".join(lines) + ("\n" if lines else "")


# ---------------------------------------------------------------------------
# BirdNET CSV
# ---------------------------------------------------------------------------

def looks_like_birdnet_csv(text: str) -> bool:
    first = text.lstrip("﻿").splitlines()[0] if text.strip() else ""
    columns = [c.strip() for c in next(csv.reader([first]), [])]
    return ("Start (s)" in columns and "End (s)" in columns and "Confidence" in columns
            and bool(set(columns) & {"Scientific name", "Common name"}))


def parse_birdnet_csv(text: str, label_column: Optional[str] = None,
                      problems: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    columns = [c.strip() for c in (reader.fieldnames or [])]
    reader.fieldnames = columns
    if label_column and label_column not in columns:
        raise ValueError(f"no column named {label_column!r} in the BirdNET CSV "
                         f"(columns: {', '.join(columns)})")
    column = label_column or next((c for c in BIRDNET_LABEL_COLUMNS if c in columns), None)
    boxes = []
    for index, row in enumerate(reader):
        times = _times(row.get("Start (s)"), row.get("End (s)"), f"line {index + 2}", problems)
        if times is None:
            continue
        start, end = times
        box: Dict[str, Any] = {"start_s": round(start, 6), "end_s": round(end, 6),
                               "low_hz": None, "high_hz": None,
                               "label": (row.get(column) or "").strip() if column else ""}
        confidence = _float(row.get("Confidence"))
        if confidence is not None:
            box["confidence"] = confidence
        source = (row.get("File") or "").strip()
        if source:
            box["file"] = os.path.basename(source.replace("\\", "/"))
        other = "Common name" if column != "Common name" else "Scientific name"
        if row.get(other):
            box.setdefault("attributes", {})[other] = row[other].strip()
        boxes.append(box)
    return boxes


# ---------------------------------------------------------------------------
# Stored answers
# ---------------------------------------------------------------------------

BOX_KEYS = ("start_s", "end_s", "low_hz", "high_hz", "label")


def normalize_box(raw: Any) -> Optional[Dict[str, Any]]:
    """One stored or imported box in canonical form, or None if unusable."""
    if not isinstance(raw, dict):
        return None
    start, end = _float(raw.get("start_s")), _float(raw.get("end_s"))
    if start is None or end is None:
        return None
    if end < start:
        start, end = end, start
    low, high = _freq(raw.get("low_hz")), _freq(raw.get("high_hz"))
    if low is not None and high is not None and high < low:
        low, high = high, low
    box = dict(raw)
    box.update({"start_s": start, "end_s": end, "low_hz": low, "high_hz": high,
                "label": str(raw.get("label") or "")})
    return box


def decode_boxes(stored: Any) -> Optional[List[Dict[str, Any]]]:
    """The box list from a stored answer: a JSON string, a list, or a label
    dict holding either under ``_data``. None when there is no answer."""
    import json
    if isinstance(stored, dict):
        if "_data" in stored:
            stored = stored["_data"]
        elif len(stored) == 1:
            stored = next(iter(stored.values()))
        else:
            return None
    if isinstance(stored, str):
        if not stored.strip():
            return None
        try:
            stored = json.loads(stored)
        except ValueError:
            return None
    if isinstance(stored, dict) and isinstance(stored.get("boxes"), list):
        stored = stored["boxes"]
    if not isinstance(stored, list):
        return None
    return [b for b in (normalize_box(x) for x in stored) if b is not None]


def clean_prefill(value: Any) -> tuple:
    """``(boxes, dropped)`` for a spectrogram pre-annotation: the entries that
    are boxes (a JSON string or a list; times swapped into order, negative
    frequencies refused), and a short description of each entry left out.
    Anything that is not a list of boxes comes back unchanged with nothing
    dropped, for the caller's own type check."""
    import json
    raw = value
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else []
        except ValueError:
            return value, [f"{_shown(value)} (not JSON)"]
    if isinstance(raw, dict) and isinstance(raw.get("boxes"), list):
        raw = raw["boxes"]
    if not isinstance(raw, list):
        return value, []
    boxes, dropped = [], []
    for index, entry in enumerate(raw):
        box = normalize_box(entry)
        if box is None:
            dropped.append(f"#{index + 1} {_shown(entry) if not isinstance(entry, dict) else 'an object without numeric times'}")
            continue
        if box["start_s"] < 0:
            dropped.append(f"#{index + 1} (negative start time)")
            continue
        boxes.append(box)
    return boxes, dropped


#: Suffixes tools add to a recording's name when they write its table.
_TABLE_SUFFIX = re.compile(
    r"(\.Table\.\d+\.selections|\.BirdNET\.selection\.table|\.BirdNET\.results"
    r"|\.BirdNET\.[A-Za-z_]+|\.selections?|\.labels?|_labels?)$", re.IGNORECASE)


def recording_stem(table_name: str) -> str:
    """``rec01.Table.1.selections.txt`` -> ``rec01``."""
    stem = os.path.splitext(os.path.basename(table_name))[0]
    previous = None
    while previous != stem:
        previous = stem
        stem = _TABLE_SUFFIX.sub("", stem)
    return stem
