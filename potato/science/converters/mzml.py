"""Mass spectra from mzML runs, through pyteomics (Apache-2.0).

Install with ``pip install 'potato-annotation[spectra]'``. One spectrum is
read per item, chosen by ``index`` (0-based position in the run) or ``scan``
(the ``scan=N`` part of the native id, as vendor software shows it). Without
either, the first spectrum is read.

A centroided scan is drawn as sticks, a profile scan as a line. The file is
refused before parsing if it declares a DOCTYPE or entities (mzML never
does), since lxml would otherwise expand them.
"""

from __future__ import annotations

import re
from typing import Optional

from potato.science.spectra import Spectrum, SpectrumError

_SCAN = re.compile(r"(?:^|\s)scan=(\d+)(?:\s|$)")


def _refuse_entities(path: str) -> None:
    with open(path, "rb") as f:
        head = f.read(65536)
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise SpectrumError("this mzML file declares a DOCTYPE or entities, which "
                            "mzML does not use; it is not read")


def _pyteomics_mzml():
    """pyteomics' mzML reader; pyteomics 5 also needs psims for PSI formats."""
    try:
        from pyteomics import mzml
        import psims  # noqa: F401
    except ImportError as e:
        from potato.science.converters import ConverterUnavailable
        raise ConverterUnavailable(
            f"Reading mzML needs pyteomics and psims, which are not installed ({e}). "
            f"Install them with: pip install 'potato-annotation[spectra]'") from e
    return mzml


def read_mzml(path: str, max_points: int = 2_000_000, index: Optional[int] = None,
              scan: Optional[int] = None, **_ignored) -> Spectrum:
    if index is not None and scan is not None:
        raise SpectrumError("give index or scan for an mzML spectrum, not both")
    _refuse_entities(path)
    mzml = _pyteomics_mzml()

    with mzml.MzML(path, use_index=True, read_schema=False) as reader:
        count = len(reader)
        if count == 0:
            raise SpectrumError("the mzML run has no spectra")
        if scan is not None:
            wanted = int(scan)
            spectrum = None
            try:
                ids = list(reader.index["spectrum"].keys())
            except (KeyError, TypeError):
                ids = []
            for sid in ids:
                m = _SCAN.search(" " + str(sid) + " ")
                if m and int(m.group(1)) == wanted:
                    spectrum = reader.get_by_id(sid)
                    break
            if spectrum is None:
                raise SpectrumError(f"scan {wanted} is not in this mzML run ({count} spectra)")
        else:
            i = 0 if index is None else int(index)
            if not 0 <= i < count:
                raise SpectrumError(f"spectrum index {i} is out of range; the run has "
                                    f"{count} spectra (numbered from 0)")
            spectrum = reader.get_by_index(i)

    mz = spectrum.get("m/z array")
    intensity = spectrum.get("intensity array")
    if mz is None or intensity is None:
        raise SpectrumError("the selected mzML spectrum has no m/z or intensity array")
    if len(mz) > max_points:
        raise SpectrumError(f"the spectrum has {len(mz)} points, over max_points ({max_points})")
    level = spectrum.get("ms level")
    sid = str(spectrum.get("id", ""))
    m = _SCAN.search(" " + sid + " ")
    title = ", ".join(filter(None, [f"scan {m.group(1)}" if m else sid,
                                    f"MS{level}" if level else ""]))
    return Spectrum(x=mz, y=intensity, x_units="M/Z", y_units="INTENSITY", kind="ms",
                    title=title, sticks="centroid spectrum" in spectrum,
                    meta={"id": sid, "ms_level": level, "spectra_in_run": count})
