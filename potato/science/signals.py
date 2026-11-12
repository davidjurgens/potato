"""Multi-channel signals for the ``time_series`` display: recordings and windows.

A :class:`SignalRecording` is what every signal reader returns (EDF/BDF,
WFDB, CSV/Parquet, inline JSON). It knows its channels, how to turn a time
into a sample index, and how to read a run of samples; it does not hold the
whole recording in memory unless the source was small (EDF and BDF are
memory-mapped).

The browser never receives a recording. It asks for a *window*,
``[start, end)`` drawn ``px`` pixels wide, and :func:`window` answers with at
most two numbers per pixel per channel:

* when the window holds no more than ``2 * px`` samples of a channel, the
  samples themselves (``{"t": [...], "v": [...]}``);
* otherwise the minimum and maximum of each pixel's bucket
  (``{"t": [...centres], "lo": [...], "hi": [...]}``), taken from a min/max
  pyramid of blocks of 64, 1024 and 16384 samples built once per channel, so
  an 8-hour overview reads about 115,000 block extrema per channel rather than
  7.4 million samples.

Times are in the recording's own units: seconds for EDF, WFDB and inline data
with a ``sampling_rate``; the values of the time column for CSV and Parquet.
A recording starts at :attr:`SignalRecording.t_start` (0 for EDF and WFDB).

Gaps (EDF+D records that do not follow on, or inline segments) are reported
per channel as ``[from, to]`` pairs so the page breaks the line there.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Block sizes of the min/max pyramid, finest first.
PYRAMID_LEVELS = (64, 1024, 16384)
#: Largest ``px`` a window request may ask for.
MAX_PX = 4000
#: Inline JSON items: total samples across channels.
MAX_INLINE_SAMPLES = 500_000
#: Samples read per chunk while building a pyramid.
_CHUNK = 64 * 16384


class SignalError(ValueError):
    """A signal cannot be read: corrupt header, unsupported layout, bad inline
    data, or a file over the size limit. The message is shown as it is."""


@dataclass
class Channel:
    """One channel. ``sampling_rate`` is None for irregularly sampled data
    (the times are then given sample by sample)."""
    name: str
    unit: str = ""
    sampling_rate: Optional[float] = None
    n_samples: int = 0

    def describe(self) -> Dict[str, Any]:
        return {"name": self.name, "unit": self.unit,
                "sampling_rate": self.sampling_rate, "n_samples": self.n_samples}


class SignalRecording:
    """Base class. Subclasses fill :attr:`channels` and implement :meth:`_read`.

    Regular channels are described by *segments* ``(t0, first_index, count)``:
    one segment for a continuous recording, several for EDF+D. Irregular
    channels carry an ascending array of sample times instead.
    """

    format = "signal"

    def __init__(self) -> None:
        self.channels: List[Channel] = []
        #: ISO 8601 wall-clock time of t = 0, when the source gives one.
        self.start_time: Optional[str] = None
        #: Annotations found in the file, in the interval_label stored shape:
        #: ``{"intervals": [...], "events": [...]}``.
        self.annotations: Dict[str, List[Dict[str, Any]]] = {"intervals": [], "events": []}
        #: Problems that did not stop the read (e.g. a truncated last record).
        self.warnings: List[str] = []
        self._segments: Dict[int, Any] = {}     # ch -> (t0[], i0[], n[]) numpy arrays
        self._times: Dict[int, Any] = {}        # ch -> ascending times (irregular)
        self._pyramids: Dict[int, Dict[int, Tuple[Any, Any, Any]]] = {}
        self._ranges: Dict[int, Tuple[float, float]] = {}
        self._lock = threading.Lock()

    # -- what subclasses implement ------------------------------------------

    def _read(self, ch: int, i0: int, i1: int):
        """Samples ``[i0, i1)`` of channel ``ch`` in physical units (float64)."""
        raise NotImplementedError

    # -- layout ----------------------------------------------------------------

    def set_regular(self, ch: int, segments: Sequence[Tuple[float, int, int]]) -> None:
        import numpy as np
        segs = sorted(segments)
        self._segments[ch] = (np.array([s[0] for s in segs], dtype=np.float64),
                              np.array([s[1] for s in segs], dtype=np.int64),
                              np.array([s[2] for s in segs], dtype=np.int64))

    def set_irregular(self, ch: int, times) -> None:
        import numpy as np
        t = np.asarray(times, dtype=np.float64)
        if t.size > 1 and np.any(np.diff(t) < 0):
            raise SignalError(f"channel '{self.channels[ch].name}': times must be in ascending order")
        self._times[ch] = t

    def channel_index(self, name: str) -> int:
        for i, c in enumerate(self.channels):
            if c.name == name:
                return i
        raise KeyError(name)

    def t_bounds(self, ch: int) -> Tuple[float, float]:
        """Time of the first sample and just after the last one."""
        c = self.channels[ch]
        if c.n_samples == 0:
            return 0.0, 0.0
        if ch in self._times:
            t = self._times[ch]
            step = float(t[-1] - t[0]) / max(1, t.size - 1) if t.size > 1 else 0.0
            return float(t[0]), float(t[-1] + step)
        t0, _i0, n = self._segments[ch]
        return float(t0[0]), float(t0[-1] + n[-1] / c.sampling_rate)

    @property
    def t_start(self) -> float:
        bounds = [self.t_bounds(i) for i, c in enumerate(self.channels) if c.n_samples]
        return min(b[0] for b in bounds) if bounds else 0.0

    @property
    def t_end(self) -> float:
        bounds = [self.t_bounds(i) for i, c in enumerate(self.channels) if c.n_samples]
        return max(b[1] for b in bounds) if bounds else 0.0

    @property
    def duration(self) -> float:
        return self.t_end - self.t_start

    def describe(self) -> Dict[str, Any]:
        """What the page needs to set up the plot (no samples)."""
        return {
            "format": self.format,
            "channels": [c.describe() for c in self.channels],
            "t_start": self.t_start,
            "t_end": self.t_end,
            "duration": self.duration,
            "start_time": self.start_time,
            "warnings": list(self.warnings),
        }

    # -- time <-> index -----------------------------------------------------------

    def index_at(self, ch: int, t: float) -> int:
        """Index of the first sample at or after time ``t``."""
        import numpy as np
        if ch in self._times:
            return int(np.searchsorted(self._times[ch], t, side="left"))
        fs = self.channels[ch].sampling_rate
        t0, i0, n = self._segments[ch]
        k = int(np.searchsorted(t0, t, side="right")) - 1
        if k < 0:
            return 0
        local = math.ceil((t - t0[k]) * fs - 1e-9)
        if local >= n[k]:
            return int(i0[k] + n[k])
        return int(i0[k] + max(local, 0))

    def sample_times(self, ch: int, i0: int, i1: int):
        import numpy as np
        if ch in self._times:
            return self._times[ch][i0:i1]
        idx = np.arange(i0, i1, dtype=np.int64)
        return self._times_of(ch, idx)

    def _times_of(self, ch: int, idx):
        import numpy as np
        fs = self.channels[ch].sampling_rate
        t0, s0, _n = self._segments[ch]
        k = np.searchsorted(s0, idx, side="right") - 1
        k = np.clip(k, 0, len(s0) - 1)
        return t0[k] + (idx - s0[k]) / fs

    def gaps(self, ch: int, start: float, end: float) -> List[List[float]]:
        """``[from, to]`` for every break between segments inside the window."""
        if ch in self._times or ch not in self._segments:
            return []
        fs = self.channels[ch].sampling_rate
        t0, _i0, n = self._segments[ch]
        out = []
        for k in range(len(t0) - 1):
            a = float(t0[k] + n[k] / fs)
            b = float(t0[k + 1])
            if b - a > 1.5 / fs and b > start and a < end:
                out.append([round(a, 6), round(b, 6)])
        return out

    def read(self, ch: int, i0: int, i1: int):
        import numpy as np
        n = self.channels[ch].n_samples
        i0, i1 = max(0, int(i0)), min(n, int(i1))
        if i1 <= i0:
            return np.zeros(0, dtype=np.float64)
        return np.asarray(self._read(ch, i0, i1), dtype=np.float64)

    # -- pyramid -------------------------------------------------------------------

    def pyramid(self, ch: int) -> Dict[int, Tuple[Any, Any, Any]]:
        """``{block: (block start times, minima, maxima)}`` for channel ``ch``."""
        with self._lock:
            if ch in self._pyramids:
                return self._pyramids[ch]
        import numpy as np
        n = self.channels[ch].n_samples
        base = PYRAMID_LEVELS[0]
        nb = (n + base - 1) // base
        lo = np.empty(nb, dtype=np.float32)
        hi = np.empty(nb, dtype=np.float32)
        for c0 in range(0, n, _CHUNK):
            c1 = min(n, c0 + _CHUNK)
            v = self.read(ch, c0, c1)
            pad = (-v.size) % base
            if pad:
                v = np.concatenate([v, np.full(pad, np.nan)])
            v = v.reshape(-1, base)
            b0 = c0 // base
            with np.errstate(all="ignore"):
                lo[b0:b0 + v.shape[0]] = np.fmin.reduce(v, axis=1)
                hi[b0:b0 + v.shape[0]] = np.fmax.reduce(v, axis=1)
        levels = {}
        idx = np.arange(0, n, base, dtype=np.int64)
        times = self.sample_times(ch, 0, n)[::base] if ch in self._times else self._times_of(ch, idx)
        levels[base] = (np.asarray(times, dtype=np.float64), lo, hi)
        prev_b, prev = base, levels[base]
        for b in PYRAMID_LEVELS[1:]:
            f = b // prev_b
            t, l, h = prev
            m = (l.size + f - 1) // f
            pad = m * f - l.size
            lp = np.concatenate([l, np.full(pad, np.nan, dtype=np.float32)]).reshape(m, f)
            hp = np.concatenate([h, np.full(pad, np.nan, dtype=np.float32)]).reshape(m, f)
            with np.errstate(all="ignore"):
                levels[b] = (t[::f], np.fmin.reduce(lp, axis=1), np.fmax.reduce(hp, axis=1))
            prev_b, prev = b, levels[b]
        with self._lock:
            self._pyramids[ch] = levels
        return levels

    def value_range(self, ch: int) -> Tuple[float, float]:
        """A robust amplitude range for the whole channel: the 0.5th
        percentile of block minima to the 99.5th of block maxima, so one
        artefact does not flatten the rest of the night."""
        if ch in self._ranges:
            return self._ranges[ch]
        import numpy as np
        if self.channels[ch].n_samples == 0:
            return 0.0, 1.0
        _t, lo, hi = self.pyramid(ch)[PYRAMID_LEVELS[0]]
        lo, hi = lo[np.isfinite(lo)], hi[np.isfinite(hi)]
        if lo.size == 0:
            out = (0.0, 1.0)
        else:
            a, b = float(np.percentile(lo, 0.5)), float(np.percentile(hi, 99.5))
            if not b > a:
                a, b = a - 1.0, b + 1.0
            out = (a, b)
        self._ranges[ch] = out
        return out


class InMemoryRecording(SignalRecording):
    """Samples held in numpy arrays (inline JSON, CSV, Parquet, WFDB windows)."""

    format = "inline"

    def __init__(self, fmt: str = "inline") -> None:
        super().__init__()
        self.format = fmt
        self._values: Dict[int, Any] = {}

    def add_channel(self, name: str, values, unit: str = "", sampling_rate: Optional[float] = None,
                    times=None, t0: float = 0.0, segments=None) -> int:
        import numpy as np
        v = np.asarray(values, dtype=np.float64)
        if v.ndim != 1:
            raise SignalError(f"channel '{name}': data must be a flat list of numbers")
        ch = len(self.channels)
        self.channels.append(Channel(name=str(name), unit=str(unit or ""),
                                     sampling_rate=float(sampling_rate) if sampling_rate else None,
                                     n_samples=int(v.size)))
        self._values[ch] = v
        if sampling_rate:
            self.set_regular(ch, segments or [(float(t0), 0, int(v.size))])
        else:
            if times is None:
                raise SignalError(f"channel '{name}': give a sampling_rate or a time for every sample")
            t = np.asarray(times, dtype=np.float64)
            if t.size != v.size:
                raise SignalError(f"channel '{name}': {t.size} times for {v.size} samples")
            self.set_irregular(ch, t)
        return ch

    def _read(self, ch, i0, i1):
        return self._values[ch][i0:i1]


# ---------------------------------------------------------------------------
# Inline JSON
# ---------------------------------------------------------------------------

_INLINE_KEYS = {"sampling_rate", "start_time", "time", "channels", "annotations", "t0"}
_CHANNEL_KEYS = {"name", "unit", "data", "sampling_rate", "time", "t0"}


def from_inline(value: Dict[str, Any]) -> InMemoryRecording:
    """A recording from the inline item shape::

        {"sampling_rate": 100, "start_time": "2024-01-01T22:00:00",
         "channels": [{"name": "Fz", "unit": "uV", "data": [...]}, ...],
         "annotations": {"intervals": [...], "events": [...]}}

    ``sampling_rate`` (and ``t0``) may also be set per channel; a channel (or
    the top level) may give ``time`` instead: one time per sample, for
    irregularly sampled series such as light curves.
    """
    import numpy as np
    if not isinstance(value, dict):
        raise SignalError("inline signal data must be an object with a channels list")
    extra = sorted(set(value) - _INLINE_KEYS)
    if extra:
        raise SignalError(f"inline signal has unknown key(s) {', '.join(extra)}; "
                          f"accepted: {', '.join(sorted(_INLINE_KEYS))}")
    channels = value.get("channels")
    if not isinstance(channels, list) or not channels:
        raise SignalError("inline signal needs a non-empty channels list")
    rec = InMemoryRecording("inline")
    if value.get("start_time") is not None:
        rec.start_time = str(value["start_time"])
    total = 0
    for n, c in enumerate(channels):
        where = f"channels[{n}]"
        if not isinstance(c, dict):
            raise SignalError(f"{where} must be an object with name and data")
        bad = sorted(set(c) - _CHANNEL_KEYS)
        if bad:
            raise SignalError(f"{where} has unknown key(s) {', '.join(bad)}")
        data = c.get("data")
        if not isinstance(data, list):
            raise SignalError(f"{where}.data must be a list of numbers")
        total += len(data)
        if total > MAX_INLINE_SAMPLES:
            raise SignalError(f"inline signal holds more than {MAX_INLINE_SAMPLES:,} samples; "
                              f"put it in a file (EDF, CSV, Parquet) instead")
        try:
            values = np.array([np.nan if x is None else float(x) for x in data], dtype=np.float64)
        except (TypeError, ValueError):
            raise SignalError(f"{where}.data must hold numbers (or null for a missing sample)")
        fs = c.get("sampling_rate", value.get("sampling_rate"))
        times = c.get("time", value.get("time"))
        if fs is not None:
            if isinstance(fs, bool) or not isinstance(fs, (int, float)) or not fs > 0:
                raise SignalError(f"{where}: sampling_rate must be a positive number of samples per second")
            rec.add_channel(c.get("name") or f"ch{n + 1}", values, unit=c.get("unit", ""),
                            sampling_rate=float(fs), t0=float(c.get("t0", value.get("t0", 0.0)) or 0.0))
        elif isinstance(times, list):
            try:
                t = [float(x) for x in times]
            except (TypeError, ValueError):
                raise SignalError(f"{where}: time must be a list of numbers")
            rec.add_channel(c.get("name") or f"ch{n + 1}", values, unit=c.get("unit", ""), times=t)
        else:
            raise SignalError(f"{where}: give sampling_rate (regular samples) or time "
                              f"(one time per sample)")
    names = [c.name for c in rec.channels]
    if len(set(names)) != len(names):
        raise SignalError("inline signal: channel names must be unique")
    if value.get("annotations") is not None:
        rec.annotations = normalize_annotations(value["annotations"], where="annotations")
    return rec


# ---------------------------------------------------------------------------
# The stored shape (shared with the interval_label scheme)
# ---------------------------------------------------------------------------

def normalize_annotations(value: Any, where: str = "annotations",
                          strict: bool = True) -> Dict[str, List[Dict[str, Any]]]:
    """Check and tidy ``{"intervals": [...], "events": [...]}``.

    An interval is ``{start, end, label, channel}`` (``end > start``, seconds
    or the recording's time unit; ``channel`` a name or null); an event is
    ``{time, label, channel}``. A bare list is read as intervals and events
    mixed, told apart by their keys. ``strict=False`` drops bad entries
    instead of raising.
    """
    if value is None:
        return {"intervals": [], "events": []}
    if isinstance(value, list):
        value = {"intervals": [x for x in value if isinstance(x, dict) and "time" not in x],
                 "events": [x for x in value if isinstance(x, dict) and "time" in x]}
    if not isinstance(value, dict):
        raise SignalError(f"{where} must be an object with intervals and events lists")
    out: Dict[str, List[Dict[str, Any]]] = {"intervals": [], "events": []}

    def fail(msg):
        if strict:
            raise SignalError(msg)

    def num(x):
        return not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(x)

    for n, iv in enumerate(value.get("intervals") or []):
        w = f"{where}.intervals[{n}]"
        if not isinstance(iv, dict) or not num(iv.get("start")) or not num(iv.get("end")):
            fail(f"{w} needs numeric start and end")
            continue
        if not iv["end"] > iv["start"]:
            fail(f"{w}: end must be after start")
            continue
        if not isinstance(iv.get("label"), str) or not iv["label"]:
            fail(f"{w} needs a label")
            continue
        ch = iv.get("channel")
        entry = {"start": float(iv["start"]), "end": float(iv["end"]), "label": iv["label"],
                 "channel": ch if isinstance(ch, str) and ch else None}
        if isinstance(iv.get("source"), str):
            entry["source"] = iv["source"]
        out["intervals"].append(entry)
    for n, ev in enumerate(value.get("events") or []):
        w = f"{where}.events[{n}]"
        if not isinstance(ev, dict) or not num(ev.get("time")):
            fail(f"{w} needs a numeric time")
            continue
        if not isinstance(ev.get("label"), str) or not ev["label"]:
            fail(f"{w} needs a label")
            continue
        ch = ev.get("channel")
        entry = {"time": float(ev["time"]), "label": ev["label"],
                 "channel": ch if isinstance(ch, str) and ch else None}
        if isinstance(ev.get("source"), str):
            entry["source"] = ev["source"]
        out["events"].append(entry)
    out["intervals"].sort(key=lambda x: (x["start"], x["end"]))
    out["events"].sort(key=lambda x: x["time"])
    return out


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

def _fmt(values) -> List[Optional[float]]:
    """Six significant digits; NaN becomes null."""
    out = []
    for x in values:
        x = float(x)
        out.append(float(f"{x:.6g}") if math.isfinite(x) else None)
    return out


def channel_window(rec: SignalRecording, ch: int, start: float, end: float, px: int) -> Dict[str, Any]:
    """One channel of a window. See the module docstring for the shape."""
    import numpy as np
    c = rec.channels[ch]
    out: Dict[str, Any] = {"name": c.name}
    gaps = rec.gaps(ch, start, end)
    if gaps:
        out["gaps"] = gaps
    if c.n_samples == 0 or end <= start:
        out.update({"t": [], "v": []})
        return out
    i0 = rec.index_at(ch, start)
    i1 = rec.index_at(ch, end)
    n = i1 - i0
    if n <= 2 * px:
        # One sample beyond each edge, so the line reaches the plot's edges.
        a, b = max(0, i0 - 1), min(c.n_samples, i1 + 1)
        t = rec.sample_times(ch, a, b)
        v = rec.read(ch, a, b)
        out.update({"t": [round(float(x), 6) for x in t], "v": _fmt(v)})
        return out
    block = None
    for b in reversed(PYRAMID_LEVELS):
        if n / b >= 2 * px:
            block = b
            break
    if block is None:
        ts = rec.sample_times(ch, i0, i1)
        lo = hi = rec.read(ch, i0, i1)
    else:
        bt, blo, bhi = rec.pyramid(ch)[block]
        b0, b1 = i0 // block, (i1 + block - 1) // block
        ts, lo, hi = bt[b0:b1], blo[b0:b1], bhi[b0:b1]
    edges = start + (end - start) * np.arange(px + 1, dtype=np.float64) / px
    bidx = np.searchsorted(ts, edges, side="left")
    first, last = int(bidx[0]), int(bidx[-1])
    if last <= first:
        out.update({"t": [], "lo": [], "hi": []})
        return out
    starts, ends = bidx[:-1], bidx[1:]
    keep = ends > starts
    s = starts[keep] - first
    lo_s, hi_s = np.asarray(lo[first:last], dtype=np.float64), np.asarray(hi[first:last], dtype=np.float64)
    with np.errstate(all="ignore"):
        mins = np.fmin.reduceat(lo_s, s)
        maxs = np.fmax.reduceat(hi_s, s)
    centres = ((edges[:-1] + edges[1:]) / 2)[keep]
    out.update({"t": [round(float(x), 6) for x in centres], "lo": _fmt(mins), "hi": _fmt(maxs)})
    return out


def window(rec: SignalRecording, start: float, end: float, px: int,
           channels: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    """Every requested channel of ``[start, end)`` at ``px`` pixels."""
    px = max(16, min(MAX_PX, int(px)))
    chans = list(range(len(rec.channels))) if channels is None else list(channels)
    return {
        "start": start, "end": end, "px": px,
        "channels": [channel_window(rec, ch, start, end, px) for ch in chans],
    }


class LRU:
    """A small thread-safe LRU mapping."""

    def __init__(self, size: int) -> None:
        self.size = size
        self._d: "OrderedDict[Any, Any]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                return self._d[key]
        return None

    def put(self, key, value) -> None:
        with self._lock:
            self._d[key] = value
            self._d.move_to_end(key)
            while len(self._d) > self.size:
                self._d.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()

    def __len__(self) -> int:
        return len(self._d)
