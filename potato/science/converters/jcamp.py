"""JCAMP-DX spectra (``.jdx``, ``.dx``, ``.jcamp``), read natively.

What is read
------------

* ``##XYDATA=(X++(Y..Y))`` in every ASDF form: AFFN and PAC numbers, SQZ
  (``@A-Ia-i``), DIF (``%J-Rj-r``) and DUP (``S-Zs``) compression, with the
  DIF Y-check value at the start of each continuation line dropped.
* ``##XYPOINTS=(XY..XY)`` and ``##PEAK TABLE=(XY..XY)`` / ``(XYW..XYW)``.
  A file with only a peak table (most mass spectra) is drawn as sticks; a
  peak table next to XYDATA becomes the file's own peak list, which the
  display can offer as suggestions.
* ``##NTUPLES`` with a ``##DATA TABLE=(X++(R..R)), XYDATA`` page, the form
  Bruker and MestReNova write for NMR: the first real page is read.
* Compound files (``##BLOCKS=``): the first block that holds data, or the
  block numbered by ``block`` (0-based, counting only blocks with data).

NMR spectra in Hz with a ``.OBSERVE FREQUENCY`` are converted to ppm.

Not read: ``(R..R)`` / ``(I..I)`` FIDs without an abscissa, 2D NMR
(``(F2++(Y..Y))`` pages beyond the first), JCAMP-CS structures.

Limits: the file size is checked by the caller (``max_file_mb``); the number
of points is capped by ``max_points``.
"""

from __future__ import annotations

import io
import math
import re
from typing import Dict, List, Optional, Tuple

from potato.science.spectra import Spectrum, SpectrumError, infer_kind

_SQZ = {"@": 0, **{c: i + 1 for i, c in enumerate("ABCDEFGHI")},
        **{c: -(i + 1) for i, c in enumerate("abcdefghi")}}
_DIF = {"%": 0, **{c: i + 1 for i, c in enumerate("JKLMNOPQR")},
        **{c: -(i + 1) for i, c in enumerate("jklmnopqr")}}
_DUP = {**{c: i + 1 for i, c in enumerate("STUVWXYZ")}, "s": 9}

_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[Ee][+-]?\d+)?")


class JcampError(SpectrumError):
    pass


def normalize_label(label: str) -> str:
    """``##.OBSERVE FREQUENCY`` -> ``.OBSERVEFREQUENCY`` (spec section 4.1)."""
    return re.sub(r"[\s\-/_]", "", label.strip().upper())


# ---------------------------------------------------------------------------
# Labelled data records and blocks
# ---------------------------------------------------------------------------

class Block:
    """One ``##TITLE= ... ##END=`` block: its records, in file order."""

    def __init__(self):
        self.records: List[Tuple[str, str]] = []

    def get(self, label: str, default: Optional[str] = None) -> Optional[str]:
        for k, v in self.records:
            if k == label:
                return v
        return default

    def number(self, label: str, default: Optional[float] = None) -> Optional[float]:
        raw = self.get(label)
        if raw is None:
            return default
        m = _NUMBER.search(raw)
        return float(m.group(0)) if m else default

    def has_data(self) -> bool:
        return any(k in ("XYDATA", "XYPOINTS", "PEAKTABLE", "DATATABLE") for k, _ in self.records)


def parse_blocks(text: str) -> List[Block]:
    """Every block in the file, inner blocks of a compound file included."""
    blocks: List[Block] = []
    stack: List[Block] = []
    label, value_lines = None, []

    def flush():
        if label is None or not stack:
            return
        stack[-1].records.append((label, "\n".join(value_lines).strip()))

    for raw in io.StringIO(text):
        line = raw.rstrip("\r\n")
        cut = line.find("$$")
        if cut >= 0:
            line = line[:cut]
        if line.startswith("##"):
            flush()
            head, _, rest = line[2:].partition("=")
            label, value_lines = normalize_label(head), [rest.strip()]
            if label == "TITLE":
                block = Block()
                stack.append(block)
                blocks.append(block)
            elif label == "END":
                # The record list closes before END is appended.
                label = None
                if stack:
                    stack.pop()
        elif label is not None:
            value_lines.append(line)
    flush()
    if not blocks:
        raise JcampError("not a JCAMP-DX file: no ##TITLE= record")
    return blocks


# ---------------------------------------------------------------------------
# ASDF decoding
# ---------------------------------------------------------------------------

def _tokens(line: str, lineno: int) -> List[Tuple[str, float]]:
    """(kind, value) for one data line: kind is abs, dif or dup."""
    out: List[Tuple[str, float]] = []
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c in " \t,;":
            i += 1
            continue
        if c == "?":
            out.append(("abs", math.nan))
            i += 1
            continue
        if c in _SQZ or c in _DIF or c in _DUP:
            j = i + 1
            while j < n and (line[j].isdigit() or line[j] == "."):
                j += 1
            digits = line[i + 1:j]
            if c in _DUP:
                out.append(("dup", int(str(_DUP[c]) + digits)))
            else:
                lead = _SQZ[c] if c in _SQZ else _DIF[c]
                magnitude = float(str(abs(lead)) + digits)
                value = -magnitude if lead < 0 else magnitude
                out.append(("abs" if c in _SQZ else "dif", value))
            i = j
            continue
        if c in "+-." or c.isdigit():
            j = i + 1 if c in "+-" else i
            while j < n and (line[j].isdigit() or line[j] == "."):
                j += 1
            # An exponent only when signed ("1.0E+03"); a bare E is SQZ +5.
            if j < n - 2 and line[j] in "Ee" and line[j + 1] in "+-" and line[j + 2].isdigit():
                j += 2
                while j < n and line[j].isdigit():
                    j += 1
            text = line[i:j]
            try:
                out.append(("abs", float(text)))
            except ValueError:
                raise JcampError(f"data line {lineno}: cannot read '{text}'")
            i = j
            continue
        raise JcampError(f"data line {lineno}: unexpected character '{c}'")
    return out


def decode_xydata(lines: List[str], max_points: int) -> Tuple[List[float], List[List[float]]]:
    """Line abscissas (raw, before XFACTOR) and each line's raw Y values."""
    xs: List[float] = []
    rows: List[List[float]] = []
    prev_last: Optional[float] = None
    prev_dif = False
    total = 0
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        toks = _tokens(line, lineno)
        if not toks:
            continue
        kind, x = toks[0]
        if kind != "abs":
            raise JcampError(f"data line {lineno}: the line does not start with an X value")
        ys: List[float] = []
        last_kind, last_dif = "abs", 0.0
        for kind, v in toks[1:]:
            if kind == "abs":
                ys.append(v)
                last_kind = "abs"
            elif kind == "dif":
                base = ys[-1] if ys else prev_last
                if base is None:
                    raise JcampError(f"data line {lineno}: a DIF value with nothing before it")
                ys.append(base + v)
                last_kind, last_dif = "dif", v
            else:  # dup
                if not ys:
                    raise JcampError(f"data line {lineno}: a DUP count with nothing to repeat")
                for _ in range(int(v) - 1):
                    ys.append(ys[-1] + last_dif if last_kind == "dif" else ys[-1])
        # The first Y of a line after a DIF line repeats the previous last Y.
        if prev_dif and ys and prev_last is not None:
            if abs(ys[0] - prev_last) > 1e-6 * max(1.0, abs(prev_last)):
                raise JcampError(
                    f"data line {lineno}: Y-check failed ({ys[0]:g} after {prev_last:g}); "
                    f"the compressed data is corrupt")
            ys = ys[1:]
            x_shift = 1
        else:
            x_shift = 0
        if ys:
            prev_last = ys[-1]
        prev_dif = last_kind == "dif"
        xs.append((x, x_shift))
        rows.append(ys)
        total += len(ys)
        if total > max_points:
            raise JcampError(f"the spectrum has more than {max_points} points (max_points)")
    return xs, rows


def _xydata_spectrum(lines, firstx, lastx, npoints, xfactor, yfactor, deltax, max_points):
    import numpy as np
    line_x, rows = decode_xydata(lines, max_points)
    y = np.asarray([v for row in rows for v in row], dtype=float) * yfactor
    if not len(y):
        raise JcampError("the XYDATA record has no values")
    if firstx is not None and lastx is not None and npoints and abs(len(y) - npoints) == 0 and npoints > 1:
        x = np.linspace(firstx, lastx, int(npoints))
    else:
        # Rebuild x from each line's own abscissa.
        if deltax is None:
            if firstx is not None and lastx is not None and npoints and npoints > 1:
                deltax = (lastx - firstx) / (npoints - 1)
            elif len(line_x) > 1 and rows[0]:
                deltax = (line_x[1][0] - line_x[0][0]) * xfactor / max(1, len(rows[0]))
            else:
                deltax = 1.0
        parts = []
        for (lx, shift), row in zip(line_x, rows):
            start = lx * xfactor + shift * deltax
            parts.append(start + deltax * np.arange(len(row)))
        x = np.concatenate(parts) if parts else np.asarray([])
    return x, y


_TABLE_VALUE = re.compile(r"\?|[+-]?(?:\d+\.?\d*|\.\d+)(?:[Ee][+-]?\d+)?")


def _pairs(value: str, width: int) -> List[Tuple[float, float]]:
    """Values of a ``(XY..XY)`` table, grouped ``width`` at a time (x, y kept).
    A ``?`` is a missing value (NaN; the point is dropped later)."""
    head, _, body = value.partition("\n")
    # Some writers put the first pairs on the header line after the variable list.
    after = head.split(")", 1)[1] if ")" in head else ""
    nums = [math.nan if m.group(0) == "?" else float(m.group(0))
            for m in _TABLE_VALUE.finditer(after + "\n" + body)]
    if len(nums) % width:
        nums = nums[: len(nums) - len(nums) % width]
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums), width)]


def _table_width(value: str) -> int:
    m = re.match(r"\s*\(([A-Z]+)\.\.", value.upper())
    return max(2, len(m.group(1))) if m else 2


# ---------------------------------------------------------------------------
# Reading a block
# ---------------------------------------------------------------------------

def _units(raw: Optional[str]) -> str:
    return (raw or "").strip().upper()


def _spectrum_from_block(block: Block, max_points: int) -> Spectrum:
    data_type = block.get("DATATYPE", "") or ""
    x_units = _units(block.get("XUNITS"))
    y_units = _units(block.get("YUNITS"))
    xfactor = block.number("XFACTOR", 1.0) or 1.0
    yfactor = block.number("YFACTOR", 1.0) or 1.0
    firstx, lastx = block.number("FIRSTX"), block.number("LASTX")
    npoints, deltax = block.number("NPOINTS"), block.number("DELTAX")
    title = (block.get("TITLE") or "").strip()
    data_class = (block.get("DATACLASS") or "").upper()
    meta = {"data_type": data_type.strip(), "title": title}
    obs = block.number(".OBSERVEFREQUENCY")
    nucleus = (block.get(".OBSERVENUCLEUS") or "").strip()
    if obs:
        meta["observe_frequency_mhz"] = obs
    if nucleus:
        meta["nucleus"] = nucleus

    x = y = None
    sticks = False
    peaks: List[Tuple[float, float]] = []
    xy = block.get("XYDATA")
    if xy is not None:
        head, _, rest = xy.partition("\n")
        if "X++(Y..Y)" not in head.upper().replace(" ", ""):
            raise JcampError(f"XYDATA form '{head.strip()}' is not read; only (X++(Y..Y))")
        x, y = _xydata_spectrum(rest.split("\n"), firstx, lastx, npoints, xfactor,
                                yfactor, deltax, max_points)
    elif block.get("DATATABLE") is not None and block.get("NTUPLES") is not None:
        x, y, x_units, y_units = _ntuples(block, max_points)
    elif block.get("XYPOINTS") is not None:
        value = block.get("XYPOINTS")
        pts = _pairs(value, _table_width(value))
        x = [p[0] * xfactor for p in pts]
        y = [p[1] * yfactor for p in pts]
    pt = block.get("PEAKTABLE")
    if pt is not None:
        peaks = [(px * xfactor, py * yfactor) for px, py in _pairs(pt, _table_width(pt))]
        if x is None:
            x, y = [p[0] for p in peaks], [p[1] for p in peaks]
            sticks = True
    if x is None:
        raise JcampError("the block has no XYDATA, XYPOINTS, PEAK TABLE or NTUPLES data")
    if len(x) > max_points:
        raise JcampError(f"the spectrum has {len(x)} points, over max_points ({max_points})")
    if "PEAK" in data_class:
        sticks = True

    kind = infer_kind(data_type, x_units)
    if kind == "nmr" and x_units == "HZ" and obs:
        import numpy as np
        x = np.asarray(x, dtype=float) / obs
        peaks = [(px / obs, py) for px, py in peaks]
        x_units = "PPM"
    if kind == "ms" and "CONTINUOUS" not in data_class and xy is None:
        sticks = True
    return Spectrum(x=x, y=y, x_units=x_units, y_units=y_units, kind=kind, title=title,
                    sticks=sticks, peaks=peaks, meta=meta)


def _ntuples(block: Block, max_points: int):
    def column(label):
        raw = block.get(label) or ""
        return [p.strip() for p in raw.replace("\n", " ").split(",")]

    symbols = [s.upper() for s in column("SYMBOL")]
    units = column("UNITS")
    first, last, factor, dim = column("FIRST"), column("LAST"), column("FACTOR"), column("VARDIM")

    def num(values, i, default=None):
        try:
            m = _NUMBER.search(values[i])
            return float(m.group(0)) if m else default
        except IndexError:
            return default

    # The first page whose data table is (X++(R..R)) or (X++(Y..Y)).
    for label, value in block.records:
        if label != "DATATABLE":
            continue
        head, _, rest = value.partition("\n")
        m = re.match(r"\s*\(\s*([A-Z0-9]+)\s*\+\+\s*\(\s*([A-Z0-9]+)\s*\.\.", head.upper())
        if not m:
            continue
        xs_sym, ys_sym = m.group(1), m.group(2)
        if ys_sym not in ("R", "Y") or xs_sym not in symbols or ys_sym not in symbols:
            continue
        xi, yi = symbols.index(xs_sym), symbols.index(ys_sym)
        x, y = _xydata_spectrum(rest.split("\n"), num(first, xi), num(last, xi), num(dim, xi),
                                num(factor, xi, 1.0) or 1.0, num(factor, yi, 1.0) or 1.0,
                                None, max_points)
        return x, y, _units(units[xi] if xi < len(units) else ""), _units(units[yi] if yi < len(units) else "")
    raise JcampError("NTUPLES has no (X++(R..R)) data table; only real 1D pages are read")


def read_jcamp(path: str, max_points: int = 2_000_000, block: Optional[int] = None,
               **_ignored) -> Spectrum:
    """The spectrum in a JCAMP-DX file (see the module docstring)."""
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8", errors="replace") if b"\x00" not in raw[:4096] else None
    if text is None:
        raise JcampError("not a JCAMP-DX file: it is binary")
    return read_jcamp_text(text, max_points=max_points, block=block)


def read_jcamp_text(text: str, max_points: int = 2_000_000, block: Optional[int] = None) -> Spectrum:
    blocks = [b for b in parse_blocks(text) if b.has_data()]
    if not blocks:
        raise JcampError("the file has no spectrum data (no XYDATA, XYPOINTS, PEAK TABLE or NTUPLES)")
    index = 0 if block is None else int(block)
    if not 0 <= index < len(blocks):
        raise JcampError(f"block {index} does not exist; the file has {len(blocks)} "
                         f"block(s) with data (numbered from 0)")
    return _spectrum_from_block(blocks[index], max_points)
