"""PhysioNet WFDB records (``.hea`` header plus ``.dat`` signal files).

Read through the ``wfdb`` library (MIT), installed with
``pip install 'potato-annotation[signals]'``. The item names the header
file (``mitdb/100.hea``); the signal files it lists must sit in the same
directory, and a header that names a file anywhere else (a path with a
directory part) is refused before ``wfdb`` opens anything.

* Samples are read a window at a time (``wfdb.rdrecord`` with ``sampfrom`` /
  ``sampto``), so a long Holter record is never loaded whole.
* Channels with several samples per frame are read at the frame rate
  (``smooth_frames``), so every channel has the record's ``fs``.
* Multi-segment records (a header listing segments) are not supported; join
  them first, e.g. ``wfdb.rdrecord(name).wrsamp()``.
* Annotations: when ``<record>.<annotation_extension>`` exists (default
  ``atr``), each beat or event annotation becomes a point event labelled
  with its symbol (``N``, ``V``, ``A``, ...). Rhythm annotations (symbol
  ``+`` with an aux note such as ``(AFIB``) become intervals labelled with
  the rhythm (``AFIB``), from that annotation to the next rhythm change or
  the end of the record.
"""

from __future__ import annotations

import os
from typing import List, Optional

from potato.science.signals import Channel, SignalError, SignalRecording

#: Total size of a record's signal files above which it is refused.
DEFAULT_MAX_BYTES = 2 * 1024 ** 3


def _wfdb():
    try:
        import wfdb  # noqa: F401
    except ImportError as e:
        from potato.science.converters import ConverterUnavailable
        raise ConverterUnavailable(
            "Reading WFDB records needs the wfdb library, which is not installed. "
            "Install it with: pip install 'potato-annotation[signals]'") from e
    return wfdb


def _check_header_files(header_path: str) -> List[str]:
    """The signal file names a header lists, refused if any leaves its directory.

    Read from the text before ``wfdb`` is called: ``wfdb`` joins these names
    onto the directory, so ``../../x.dat`` would otherwise be opened.
    """
    names = []
    try:
        with open(header_path, "r", encoding="latin-1") as f:
            lines = [ln.strip() for ln in f.read(1_000_000).splitlines()]
    except OSError as e:
        raise SignalError(f"cannot read WFDB header: {e}")
    lines = [ln for ln in lines if ln and not ln.startswith("#")]
    if not lines:
        raise SignalError("WFDB header is empty")
    first = lines[0].split()
    if len(first) < 2:
        raise SignalError("WFDB header's record line needs a record name and a signal count")
    if "/" in first[0]:
        raise SignalError("this is a multi-segment WFDB record, which is not supported; "
                          "join the segments into one record first")
    try:
        n_sig = int(first[1])
    except ValueError:
        raise SignalError(f"WFDB header: signal count {first[1]!r} is not a number")
    if n_sig < 1 or n_sig > 1024:
        raise SignalError(f"WFDB header lists {n_sig} signals; expected 1 to 1024")
    if len(lines) < 1 + n_sig:
        raise SignalError(f"WFDB header lists {n_sig} signals but describes {len(lines) - 1}")
    for ln in lines[1:1 + n_sig]:
        fname = ln.split()[0]
        if fname in ("-", "~"):
            continue
        if os.path.basename(fname) != fname or fname in (".", ".."):
            raise SignalError(f"WFDB header names the signal file '{fname}', outside the "
                              f"record's directory; refused")
        names.append(fname)
    return names


class WFDBRecording(SignalRecording):
    format = "wfdb"

    def __init__(self, header_path: str, annotation_extension: Optional[str] = "atr",
                 max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        super().__init__()
        wfdb = _wfdb()
        if not header_path.lower().endswith(".hea"):
            raise SignalError("name the WFDB record by its .hea header file")
        directory = os.path.dirname(os.path.abspath(header_path))
        files = _check_header_files(header_path)
        total = 0
        for name in set(files):
            p = os.path.join(directory, name)
            if not os.path.isfile(p):
                raise SignalError(f"WFDB signal file '{name}' named by the header is missing")
            total += os.path.getsize(p)
        if total > max_bytes:
            raise SignalError(f"WFDB record is {total / 1e6:.0f} MB, over the "
                              f"{max_bytes / 1e6:.0f} MB limit for signal files")
        self._record = header_path[:-4]
        try:
            h = wfdb.rdheader(self._record)
        except Exception as e:     # wfdb raises many types for a bad header
            raise SignalError(f"WFDB header could not be read: {e}")
        if getattr(h, "seg_name", None):
            raise SignalError("multi-segment WFDB records are not supported")
        if not h.fs or h.fs <= 0:
            raise SignalError("WFDB header gives no sampling frequency")
        n = int(h.sig_len or 0)
        if n <= 0:
            raise SignalError("WFDB header gives no signal length")
        for i, name in enumerate(h.sig_name or []):
            unit = (h.units or [""] * h.n_sig)[i] if h.units else ""
            self.channels.append(Channel(name=name or f"signal {i + 1}", unit=unit or "",
                                         sampling_rate=float(h.fs), n_samples=n))
            self.set_regular(i, [(0.0, 0, n)])
        names = [c.name for c in self.channels]
        for i, c in enumerate(self.channels):
            if names.count(c.name) > 1:
                c.name = f"{c.name} ({i + 1})"
        if getattr(h, "base_date", None) and getattr(h, "base_time", None):
            self.start_time = f"{h.base_date.isoformat()}T{h.base_time.isoformat()}"
        if annotation_extension:
            ann = f"{self._record}.{annotation_extension}"
            if os.path.isfile(ann):
                self.annotations = self._annotations(wfdb, annotation_extension, float(h.fs), n)

    def _annotations(self, wfdb, ext, fs, n):
        try:
            a = wfdb.rdann(self._record, ext)
        except Exception as e:
            self.warnings.append(f"The .{ext} annotation file could not be read ({e}); "
                                 f"no pre-annotations from it.")
            return {"intervals": [], "events": []}
        events, intervals = [], []
        rhythm, rhythm_start = None, None
        aux = list(a.aux_note or [""] * len(a.sample))
        for s, sym, note in zip(a.sample, a.symbol, aux):
            t = float(s) / fs
            note = (note or "").strip().rstrip("\x00")
            if sym == "+" and note.startswith("("):
                if rhythm is not None and t > rhythm_start:
                    intervals.append({"start": rhythm_start, "end": t, "label": rhythm,
                                      "channel": None, "source": "file"})
                rhythm, rhythm_start = note[1:], t
            else:
                events.append({"time": t, "label": sym, "channel": None, "source": "file"})
        if rhythm is not None and n / fs > rhythm_start:
            intervals.append({"start": rhythm_start, "end": n / fs, "label": rhythm,
                              "channel": None, "source": "file"})
        return {"intervals": intervals, "events": events}

    def _read(self, ch, i0, i1):
        wfdb = _wfdb()
        try:
            r = wfdb.rdrecord(self._record, sampfrom=int(i0), sampto=int(i1), channels=[ch],
                              physical=True, smooth_frames=True)
        except Exception as e:
            raise SignalError(f"WFDB samples could not be read: {e}")
        return r.p_signal[:, 0]


def read_wfdb(path: str, annotation_extension: Optional[str] = "atr",
              max_bytes: int = DEFAULT_MAX_BYTES) -> WFDBRecording:
    """Open a WFDB record by its ``.hea`` header."""
    return WFDBRecording(path, annotation_extension=annotation_extension, max_bytes=max_bytes)
