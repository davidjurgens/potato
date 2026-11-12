"""BIDS ``*_events.tsv`` files, read as pre-annotations and written as an export.

A BIDS events file is tab-separated with a header row. ``onset`` and
``duration`` (seconds) are required; ``n/a`` marks a missing value. Reading:

* the label is ``trial_type``, else ``value``, else ``event``;
* ``duration`` 0 or ``n/a`` makes a point event, anything larger an interval;
* a ``channel`` column, when present, names the channel (``n/a`` = all).

Writing produces ``onset``, ``duration``, ``trial_type`` and ``channel``
(point events have duration 0), sorted by onset, plus the JSON sidecar that
describes the columns.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
from typing import Any, Dict, List, Optional

from potato.science.signals import SignalError

#: Largest events file read.
MAX_BYTES = 20 * 1024 * 1024
NA = "n/a"


def _num(text: str, column: str, row: int) -> Optional[float]:
    text = (text or "").strip()
    if text in ("", NA):
        return None
    try:
        v = float(text)
    except ValueError:
        raise SignalError(f"events.tsv row {row}: {column} {text!r} is not a number")
    if not math.isfinite(v):
        raise SignalError(f"events.tsv row {row}: {column} must be finite")
    return v


def parse_bids_events(text: str) -> Dict[str, List[Dict[str, Any]]]:
    rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
    rows = [r for r in rows if r and any(c.strip() for c in r)]
    if not rows:
        return {"intervals": [], "events": []}
    header = [h.strip() for h in rows[0]]
    for required in ("onset", "duration"):
        if required not in header:
            raise SignalError(f"events.tsv has no '{required}' column (columns: {', '.join(header)})")
    col = {name: i for i, name in enumerate(header)}
    intervals, events = [], []
    for n, r in enumerate(rows[1:], start=2):
        r = r + [""] * (len(header) - len(r))
        onset = _num(r[col["onset"]], "onset", n)
        if onset is None:
            raise SignalError(f"events.tsv row {n}: onset is required")
        duration = _num(r[col["duration"]], "duration", n)
        label = ""
        for key in ("trial_type", "value"):
            if key in col and r[col[key]].strip() not in ("", NA):
                label = r[col[key]].strip()
                break
        label = label or "event"
        channel = None
        if "channel" in col and r[col["channel"]].strip() not in ("", NA):
            channel = r[col["channel"]].strip()
        if duration and duration > 0:
            intervals.append({"start": onset, "end": onset + duration, "label": label,
                              "channel": channel, "source": "file"})
        else:
            events.append({"time": onset, "label": label, "channel": channel, "source": "file"})
    intervals.sort(key=lambda x: (x["start"], x["end"]))
    events.sort(key=lambda x: x["time"])
    return {"intervals": intervals, "events": events}


def read_bids_events(path: str) -> Dict[str, List[Dict[str, Any]]]:
    """Read ``*_events.tsv`` into ``{"intervals": [...], "events": [...]}``."""
    size = os.path.getsize(path)
    if size > MAX_BYTES:
        raise SignalError(f"{os.path.basename(path)} is {size / 1e6:.1f} MB, over the "
                          f"{MAX_BYTES / 1e6:.0f} MB limit for events files")
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        return parse_bids_events(f.read())


def _fmt(v: float) -> str:
    text = f"{v:.6f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def events_rows(annotation: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    rows = []
    for iv in annotation.get("intervals") or []:
        rows.append((iv["start"], {"onset": _fmt(iv["start"]), "duration": _fmt(iv["end"] - iv["start"]),
                                   "trial_type": iv["label"], "channel": iv.get("channel") or NA}))
    for ev in annotation.get("events") or []:
        rows.append((ev["time"], {"onset": _fmt(ev["time"]), "duration": "0",
                                  "trial_type": ev["label"], "channel": ev.get("channel") or NA}))
    rows.sort(key=lambda x: x[0])
    return [r for _t, r in rows]


def write_bids_events(annotation: Dict[str, List[Dict[str, Any]]], path: str) -> None:
    """Write ``onset, duration, trial_type, channel`` rows."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["onset", "duration", "trial_type", "channel"],
                           delimiter="\t", lineterminator="\n")
        w.writeheader()
        for row in events_rows(annotation):
            w.writerow(row)


def events_sidecar(levels: Dict[str, str]) -> Dict[str, Any]:
    """The ``*_events.json`` describing the columns written above.
    ``levels`` maps each label to a description (the label itself if none)."""
    return {
        "onset": {"Description": "Onset of the event in seconds from the start of the recording",
                  "Units": "s"},
        "duration": {"Description": "Duration of the event in seconds; 0 for a point event",
                     "Units": "s"},
        "trial_type": {"Description": "Label given by the annotator",
                       "Levels": dict(levels)},
        "channel": {"Description": "Channel the label applies to; n/a when it applies to all"},
    }


def dumps_sidecar(levels: Dict[str, str]) -> str:
    return json.dumps(events_sidecar(levels), indent=2) + "\n"
