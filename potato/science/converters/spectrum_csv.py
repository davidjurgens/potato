"""Two-column spectra in plain text: CSV, TSV, or whitespace-separated (x, y).

One optional header row. A header such as ``shift (ppm),intensity`` sets the
x units from the parenthesised part; lines starting with ``#`` are comments.
Extra columns are ignored. Not registered in the shared converter table:
``.csv`` is too generic for every display to treat as a spectrum, so the
``spectrum`` display calls :func:`read_spectrum_csv` itself.
"""

from __future__ import annotations

import re
from typing import List, Optional

from potato.science.spectra import Spectrum, SpectrumError, infer_kind

_UNITS_IN_HEADER = re.compile(r"[\(\[]\s*([^\)\]]+?)\s*[\)\]]")

_UNIT_ALIASES = {
    "ppm": "PPM", "hz": "HZ", "cm-1": "1/CM", "cm^-1": "1/CM", "1/cm": "1/CM",
    "cm⁻¹": "1/CM", "m/z": "M/Z", "mz": "M/Z", "nm": "NANOMETERS", "um": "MICROMETERS",
    "µm": "MICROMETERS", "%t": "TRANSMITTANCE", "%": "TRANSMITTANCE", "a.u.": "ARBITRARY UNITS",
    "au": "ARBITRARY UNITS", "abs": "ABSORBANCE",
}


def _units_of(name: str) -> str:
    low = name.strip().lower()
    m = _UNITS_IN_HEADER.search(low)
    unit = m.group(1) if m else ""
    if unit in _UNIT_ALIASES:
        return _UNIT_ALIASES[unit]
    for word, value in (("ppm", "PPM"), ("wavenumber", "1/CM"), ("m/z", "M/Z"),
                        ("transmittance", "TRANSMITTANCE"), ("absorbance", "ABSORBANCE")):
        if word in low:
            return value
    return unit.upper()


def _split(line: str) -> List[str]:
    for sep in (",", "\t", ";"):
        if sep in line:
            return [p.strip() for p in line.split(sep)]
    return line.split()


def read_spectrum_csv(path: str, max_points: int = 2_000_000, kind: Optional[str] = None,
                      **_ignored) -> Spectrum:
    xs: List[float] = []
    ys: List[float] = []
    header = None
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for lineno, line in enumerate(f, start=1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            parts = _split(text)
            if len(parts) < 2:
                raise SpectrumError(f"{path}: line {lineno} has one column; write x,y")
            try:
                x, y = float(parts[0]), float(parts[1])
            except ValueError:
                if header is None and not xs:
                    header = parts
                    continue
                raise SpectrumError(f"line {lineno}: '{parts[0]}, {parts[1]}' is not two numbers")
            xs.append(x)
            ys.append(y)
            if len(xs) > max_points:
                raise SpectrumError(f"the spectrum has more than {max_points} points (max_points)")
    if not xs:
        raise SpectrumError("the file has no x,y rows")
    x_units = _units_of(header[0]) if header else ""
    y_units = _units_of(header[1]) if header else ""
    return Spectrum(x=xs, y=ys, x_units=x_units, y_units=y_units,
                    kind=kind or infer_kind("", x_units),
                    meta={"columns": header[:2] if header else []})
