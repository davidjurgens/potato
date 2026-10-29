"""EDF, EDF+, BDF and BDF+ recordings, read natively (no third-party library).

The header is parsed and checked field by field; the data records are
memory-mapped, so opening an 8-hour polysomnogram reads 256 bytes per signal
and nothing else until a window is drawn.

* **EDF** (16-bit) and **BDF** (BioSemi, 24-bit) are told apart by the first
  header byte.
* **EDF+ / BDF+ annotation signals** ("EDF Annotations", "BDF Annotations")
  are not drawn. Their time-stamped annotation lists (TALs) become
  ``recording.annotations``: an annotation with a duration becomes an
  interval, one without becomes a point event; ``channel`` is null.
* **EDF+D** (discontinuous): each data record starts at the time its first,
  timekeeping TAL gives. Records that follow on are joined into one segment;
  the space between segments is a gap, which the display draws as a break in
  the line. Times stay real (seconds since the start of the recording), so a
  label made after a gap is stored at its true time.
* A file shorter than its header says is read up to the last complete
  record, with a warning; a header that does not parse, an impossible signal
  count or record size, or a file larger than ``max_bytes`` raises
  :class:`~potato.science.signals.SignalError`.

Physical value = (digital - digital_min) * (physical_max - physical_min)
/ (digital_max - digital_min) + physical_min, per signal.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from potato.science.signals import SignalError, SignalRecording

#: Default refusal size. Opening is cheap (memory-mapped), but the first
#: overview reads the whole file once to build the min/max pyramid.
DEFAULT_MAX_BYTES = 2 * 1024 ** 3
MAX_SIGNALS = 1024
_ANNOTATION_LABELS = ("EDF Annotations", "BDF Annotations")


def _ascii(raw: bytes, what: str) -> str:
    try:
        return raw.decode("ascii").strip()
    except UnicodeDecodeError:
        # The spec says ASCII; Latin-1 labels are common enough to accept.
        return raw.decode("latin-1").strip()


def _number(raw: bytes, what: str, integer: bool = False):
    text = _ascii(raw, what)
    try:
        value = float(text)
    except ValueError:
        raise SignalError(f"EDF header field '{what}' is not a number ({text!r}); "
                          f"the file is not EDF/BDF or its header is damaged")
    if integer:
        if value != int(value):
            raise SignalError(f"EDF header field '{what}' must be a whole number ({text!r})")
        return int(value)
    return value


def _start_time(date: str, time: str, recording_id: str) -> Optional[str]:
    m = re.match(r"^(\d\d)\.(\d\d)\.(\d\d)$", date)
    t = re.match(r"^(\d\d)\.(\d\d)\.(\d\d)$", time)
    if not m or not t:
        return None
    day, month, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    year = 1900 + yy if yy >= 85 else 2000 + yy
    # EDF+ writes the four-digit year in the recording field.
    r = re.search(r"Startdate \d\d-[A-Z]{3}-(\d{4})", recording_id or "")
    if r:
        year = int(r.group(1))
    return (f"{year:04d}-{month:02d}-{day:02d}T"
            f"{int(t.group(1)):02d}:{int(t.group(2)):02d}:{int(t.group(3)):02d}")


def parse_header(head: bytes, file_size: int) -> Dict[str, Any]:
    """The fixed and per-signal header fields, checked."""
    if len(head) < 256:
        raise SignalError("file is shorter than an EDF header (256 bytes)")
    bdf = head[0:1] == b"\xff"
    if bdf:
        if head[1:8] != b"BIOSEMI":
            raise SignalError("file starts like BDF (0xFF) but the version is not BIOSEMI")
    elif head[0:8].strip() != b"0":
        raise SignalError("not an EDF file: the version field must be '0' (EDF) "
                          "or 0xFF BIOSEMI (BDF)")
    h: Dict[str, Any] = {"bdf": bdf}
    h["patient"] = _ascii(head[8:88], "patient")
    h["recording"] = _ascii(head[88:168], "recording")
    h["start_time"] = _start_time(_ascii(head[168:176], "startdate"),
                                  _ascii(head[176:184], "starttime"), h["recording"])
    h["header_bytes"] = _number(head[184:192], "number of bytes in header", integer=True)
    h["reserved"] = _ascii(head[192:236], "reserved")
    h["n_records"] = _number(head[236:244], "number of data records", integer=True)
    h["record_duration"] = _number(head[244:252], "duration of a data record")
    ns = _number(head[252:256], "number of signals", integer=True)
    if not 1 <= ns <= MAX_SIGNALS:
        raise SignalError(f"EDF header says {ns} signals; expected 1 to {MAX_SIGNALS}")
    h["ns"] = ns
    if h["header_bytes"] != 256 * (ns + 1):
        raise SignalError(f"EDF header size field is {h['header_bytes']} bytes but {ns} "
                          f"signals need {256 * (ns + 1)}; the header is damaged")
    if len(head) < h["header_bytes"]:
        raise SignalError("file ends inside the EDF header")
    if h["record_duration"] < 0:
        raise SignalError("EDF data record duration is negative")

    def fields(offset: int, width: int) -> Tuple[List[bytes], int]:
        out = [head[offset + i * width: offset + (i + 1) * width] for i in range(ns)]
        return out, offset + ns * width

    off = 256
    labels, off = fields(off, 16)
    _transducer, off = fields(off, 80)
    dims, off = fields(off, 8)
    pmin, off = fields(off, 8)
    pmax, off = fields(off, 8)
    dmin, off = fields(off, 8)
    dmax, off = fields(off, 8)
    _prefilter, off = fields(off, 80)
    nsamp, off = fields(off, 8)
    signals = []
    for i in range(ns):
        label = _ascii(labels[i], f"label of signal {i + 1}")
        s = {
            "label": label,
            "unit": _ascii(dims[i], f"physical dimension of {label}"),
            "physical_min": _number(pmin[i], f"physical minimum of {label}"),
            "physical_max": _number(pmax[i], f"physical maximum of {label}"),
            "digital_min": _number(dmin[i], f"digital minimum of {label}", integer=True),
            "digital_max": _number(dmax[i], f"digital maximum of {label}", integer=True),
            "samples_per_record": _number(nsamp[i], f"samples per record of {label}", integer=True),
            "annotation": label in _ANNOTATION_LABELS,
        }
        if s["samples_per_record"] < 1:
            raise SignalError(f"signal '{label}' has {s['samples_per_record']} samples per record")
        if s["digital_max"] == s["digital_min"]:
            raise SignalError(f"signal '{label}': digital minimum equals digital maximum")
        signals.append(s)
    h["signals"] = signals
    width = 3 if bdf else 2
    h["sample_bytes"] = width
    h["record_bytes"] = sum(s["samples_per_record"] for s in signals) * width
    available = max(0, file_size - h["header_bytes"]) // h["record_bytes"]
    h["warnings"] = []
    if h["n_records"] == -1:
        h["n_records"] = available
    elif h["n_records"] < 0:
        raise SignalError(f"EDF header says {h['n_records']} data records")
    elif h["n_records"] > available:
        h["warnings"].append(
            f"The header says {h['n_records']} data records but the file holds "
            f"{available}; reading the {available} complete records.")
        h["n_records"] = available
    if h["n_records"] == 0:
        raise SignalError("the file holds no complete data record")
    if h["record_duration"] == 0 and any(not s["annotation"] for s in signals):
        raise SignalError("EDF data record duration is 0, which only annotation-only files may use")
    return h


# ---------------------------------------------------------------------------
# TALs
# ---------------------------------------------------------------------------

def parse_tals(raw: bytes) -> Tuple[Optional[float], List[Tuple[float, float, str]]]:
    """``(record onset, [(onset, duration, text), ...])`` from one record's
    annotation bytes. The first TAL of a record is its timekeeping TAL."""
    record_onset = None
    out: List[Tuple[float, float, str]] = []
    for tal in raw.split(b"\x00"):
        if not tal:
            continue
        parts = tal.split(b"\x14")
        head = parts[0]
        if b"\x15" in head:
            onset_b, dur_b = head.split(b"\x15", 1)
        else:
            onset_b, dur_b = head, b""
        try:
            onset = float(onset_b.decode("ascii"))
            duration = float(dur_b.decode("ascii")) if dur_b else 0.0
        except (UnicodeDecodeError, ValueError):
            continue        # not a TAL (padding or damaged): skip it
        texts = [p.decode("utf-8", errors="replace").strip() for p in parts[1:]]
        texts = [t for t in texts if t]
        if not texts:
            if record_onset is None:
                record_onset = onset
            continue
        for text in texts:
            out.append((onset, max(0.0, duration), text))
    return record_onset, out


class EDFRecording(SignalRecording):
    format = "edf"

    def __init__(self, path: str, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        super().__init__()
        import numpy as np
        size = os.path.getsize(path)
        if size > max_bytes:
            raise SignalError(f"{os.path.basename(path)} is {size / 1e6:.0f} MB, over the "
                              f"{max_bytes / 1e6:.0f} MB limit for signal files")
        with open(path, "rb") as f:
            head = f.read(256)
            if len(head) == 256:
                try:
                    ns = int(head[252:256].decode("ascii").strip())
                except ValueError:
                    ns = 0
                if 1 <= ns <= MAX_SIGNALS:
                    head += f.read(256 * ns)
        h = parse_header(head, size)
        self.header = h
        self.format = "bdf" if h["bdf"] else "edf"
        if h["reserved"].startswith(("EDF+", "BDF+")):
            self.format += "+"
        self.discontinuous = h["reserved"].startswith(("EDF+D", "BDF+D"))
        self.start_time = h["start_time"]
        self.warnings = list(h["warnings"])
        n_rec, width = h["n_records"], h["sample_bytes"]
        self._raw = np.memmap(path, dtype=np.uint8, mode="r", offset=h["header_bytes"],
                              shape=(n_rec, h["record_bytes"]))
        self._layout: List[Tuple[int, int, float, float]] = []   # (byte offset, n, gain, offset)
        ann_cols: List[Tuple[int, int]] = []
        col = 0
        for s in h["signals"]:
            nbytes = s["samples_per_record"] * width
            if s["annotation"]:
                ann_cols.append((col, nbytes))
            else:
                gain = (s["physical_max"] - s["physical_min"]) / (s["digital_max"] - s["digital_min"])
                offset = s["physical_min"] - s["digital_min"] * gain
                from potato.science.signals import Channel
                fs = s["samples_per_record"] / h["record_duration"]
                self.channels.append(Channel(name=s["label"] or f"signal {len(self.channels) + 1}",
                                             unit=s["unit"], sampling_rate=fs,
                                             n_samples=s["samples_per_record"] * n_rec))
                self._layout.append((col, s["samples_per_record"], gain, offset))
            col += nbytes
        names = [c.name for c in self.channels]
        for i, c in enumerate(self.channels):
            if names.count(c.name) > 1:
                c.name = f"{c.name} ({i + 1})"
        if not self.channels:
            raise SignalError("the file has annotation signals only; there is nothing to plot")

        onsets = self._read_annotations(ann_cols, n_rec, h["record_duration"])
        for ch, (_col, spr, _g, _o) in enumerate(self._layout):
            self.set_regular(ch, self._segments_for(onsets, spr, h["record_duration"]))

    def _read_annotations(self, cols, n_rec, record_duration) -> Optional[List[float]]:
        if not cols:
            return None
        onsets: List[Optional[float]] = []
        intervals, events = [], []
        seen = set()
        for r in range(n_rec):
            record_onset = None
            for col, nbytes in cols:
                raw = bytes(self._raw[r, col:col + nbytes])
                onset, anns = parse_tals(raw)
                if record_onset is None:
                    record_onset = onset
                for t, d, text in anns:
                    key = (round(t, 6), round(d, 6), text)
                    if key in seen:
                        continue
                    seen.add(key)
                    if d > 0:
                        intervals.append({"start": t, "end": t + d, "label": text,
                                          "channel": None, "source": "file"})
                    else:
                        events.append({"time": t, "label": text, "channel": None,
                                       "source": "file"})
            onsets.append(record_onset)
        intervals.sort(key=lambda x: (x["start"], x["end"]))
        events.sort(key=lambda x: x["time"])
        self.annotations = {"intervals": intervals, "events": events}
        if not self.discontinuous:
            return None
        if any(o is None for o in onsets):
            self.warnings.append("Some EDF+D records have no timekeeping annotation; "
                                 "they are placed directly after the record before them.")
        out, prev = [], None
        for o in onsets:
            if o is None:
                o = (prev + record_duration) if prev is not None else 0.0
            if prev is not None and o < prev + record_duration - 1e-6:
                raise SignalError("EDF+D record onsets overlap or go backwards; the file is damaged")
            out.append(o)
            prev = o
        return out

    @staticmethod
    def _segments_for(onsets, spr, record_duration):
        if onsets is None:
            return None
        segs, start_rec = [], 0
        for r in range(1, len(onsets) + 1):
            if r == len(onsets) or abs(onsets[r] - (onsets[r - 1] + record_duration)) > 1e-6:
                segs.append((float(onsets[start_rec]), start_rec * spr, (r - start_rec) * spr))
                start_rec = r
        return segs

    def set_regular(self, ch, segments):
        if segments is None:
            segments = [(0.0, 0, self.channels[ch].n_samples)]
        super().set_regular(ch, segments)

    def _read(self, ch, i0, i1):
        import numpy as np
        col, spr, gain, offset = self._layout[ch]
        r0, r1 = i0 // spr, (i1 - 1) // spr + 1
        width = self.header["sample_bytes"]
        block = np.asarray(self._raw[r0:r1, col:col + spr * width])
        if width == 2:
            digital = block.reshape(-1).view("<i2").astype(np.float64)
        else:
            b = block.reshape(-1, 3).astype(np.int32)
            digital = (b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16))
            digital = np.where(digital >= 1 << 23, digital - (1 << 24), digital).astype(np.float64)
        a = i0 - r0 * spr
        return digital[a:a + (i1 - i0)] * gain + offset


def read_edf(path: str, max_bytes: int = DEFAULT_MAX_BYTES) -> EDFRecording:
    """Open an EDF, EDF+, BDF or BDF+ file (``.edf``, ``.bdf``)."""
    return EDFRecording(path, max_bytes=max_bytes)


# ---------------------------------------------------------------------------
# Writing (used for the example and test fixtures; not by the server)
# ---------------------------------------------------------------------------

def write_edf(path: str, channels: List[Dict[str, Any]], record_duration: float = 1.0,
              start: str = "01.01.24", start_clock: str = "22.00.00",
              annotations: Optional[List[Tuple[float, float, str]]] = None,
              record_onsets: Optional[List[float]] = None) -> None:
    """Write a small EDF+ file.

    ``channels``: ``[{"label", "unit", "fs", "data", "physical_min", "physical_max"}]``.
    ``annotations``: ``[(onset, duration, text)]`` written into the first
    record's TAL signal. ``record_onsets`` makes an EDF+D file.
    """
    import numpy as np
    n_rec = None
    sigs = []
    for c in channels:
        spr = int(round(c["fs"] * record_duration))
        data = np.asarray(c["data"], dtype=np.float64)
        nr = len(data) // spr
        n_rec = nr if n_rec is None else min(n_rec, nr)
        sigs.append((c, spr, data))
    def tal_for(r):
        onset = record_onsets[r] if record_onsets else r * record_duration
        tal = f"+{onset:g}\x14\x14\x00".encode("ascii")
        if r == 0:
            for t, d, text in annotations or []:
                dur = f"\x15{d:g}" if d else ""
                tal += f"+{t:g}{dur}\x14{text}\x14\x00".encode("utf-8")
        return tal

    tal_spr = (max(len(tal_for(0)), 32) + 2) // 2
    ns = len(sigs) + 1

    def pad(text, width):
        b = str(text).encode("ascii")[:width]
        return b + b" " * (width - len(b))

    head = bytearray()
    head += pad("0", 8) + pad("X X X X", 80)
    head += pad(f"Startdate 01-JAN-2024 X X X", 80)
    head += pad(start, 8) + pad(start_clock, 8)
    head += pad(256 * (ns + 1), 8)
    head += pad("EDF+D" if record_onsets else "EDF+C", 44)
    head += pad(n_rec, 8) + pad(f"{record_duration:g}", 8) + pad(ns, 4)
    labels = [c["label"] for c, _s, _d in sigs] + ["EDF Annotations"]
    units = [c.get("unit", "") for c, _s, _d in sigs] + [""]
    pmins = [c["physical_min"] for c, _s, _d in sigs] + [-1]
    pmaxs = [c["physical_max"] for c, _s, _d in sigs] + [1]
    for v in labels:
        head += pad(v, 16)
    for _ in labels:
        head += pad("", 80)
    for v in units:
        head += pad(v, 8)
    for v in pmins:
        head += pad(f"{v:g}", 8)
    for v in pmaxs:
        head += pad(f"{v:g}", 8)
    for _ in labels:
        head += pad(-32768, 8)
    for _ in labels:
        head += pad(32767, 8)
    for _ in labels:
        head += pad("", 80)
    for _c, spr, _d in sigs:
        head += pad(spr, 8)
    head += pad(tal_spr, 8)
    for _ in labels:
        head += pad("", 32)
    with open(path, "wb") as f:
        f.write(bytes(head))
        for r in range(n_rec):
            for c, spr, data in sigs:
                seg = data[r * spr:(r + 1) * spr]
                gain = (c["physical_max"] - c["physical_min"]) / 65535.0
                dig = np.clip(np.round((seg - c["physical_min"]) / gain - 32768), -32768, 32767)
                f.write(dig.astype("<i2").tobytes())
            tal = tal_for(r)[:tal_spr * 2]
            f.write(tal + b"\x00" * (tal_spr * 2 - len(tal)))
