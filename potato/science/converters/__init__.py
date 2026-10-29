"""Server-side converters for formats with no maintained browser reader.

A converter turns a file into something a display can draw (JSON arrays, PNG
cutouts, tiles) and is looked up by file extension. Entries name the module
and function as a string so that no format library is imported until a file
of that format is read; a missing library raises ``ConverterUnavailable`` with
the install extra that provides it.

To add a format, add one line to ``_BUILTIN``:

    ".edf": ("potato.science.converters.edf", "read_edf", "signals"),

(extension, then module, function, and the ``pip install potato-annotation[...]``
extra that supplies its dependencies, or ``None`` if it needs none).
"""

import importlib
import os
from typing import Callable, Dict, Optional, Tuple


class ConverterUnavailable(RuntimeError):
    """The format is known but its library is not installed."""


#: extension (lower case, with the dot) -> (module, function, install extra)
_BUILTIN: Dict[str, Tuple[str, str, Optional[str]]] = {
    ".jdx": ("potato.science.converters.jcamp", "read_jcamp", None),
    ".dx": ("potato.science.converters.jcamp", "read_jcamp", None),
    ".jcamp": ("potato.science.converters.jcamp", "read_jcamp", None),
    ".mzml": ("potato.science.converters.mzml", "read_mzml", "spectra"),
    ".ome.zarr": ("potato.science.converters.ome", "open_ome", "microscopy"),
    ".ome.tif": ("potato.science.converters.ome", "open_ome", "microscopy"),
    ".ome.tiff": ("potato.science.converters.ome", "open_ome", "microscopy"),
    ".fits": ("potato.science.converters.fits", "fits_cutout", "astro"),
    ".fit": ("potato.science.converters.fits", "fits_cutout", "astro"),
    ".fts": ("potato.science.converters.fits", "fits_cutout", "astro"),
    ".fits.gz": ("potato.science.converters.fits", "fits_cutout", "astro"),
    ".edf": ("potato.science.converters.edf", "read_edf", None),
    ".bdf": ("potato.science.converters.edf", "read_edf", None),
    ".hea": ("potato.science.converters.wfdb_record", "read_wfdb", "signals"),
    "_events.tsv": ("potato.science.converters.bids_events", "read_bids_events", None),
}


def known_extensions():
    return sorted(_BUILTIN)


def _extension(path: str) -> str:
    name = os.path.basename(str(path)).lower()
    # Two-part extensions first (".nii.gz", ".fits.gz").
    for ext in sorted(_BUILTIN, key=len, reverse=True):
        if name.endswith(ext):
            return ext
    return os.path.splitext(name)[1]


def converter_for(path: str) -> Optional[Callable]:
    """Return the converter function for ``path``, or None if no format matches."""
    entry = _BUILTIN.get(_extension(path))
    if entry is None:
        return None
    module_name, func_name, extra = entry
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        hint = f" Install it with: pip install 'potato-annotation[{extra}]'" if extra else ""
        raise ConverterUnavailable(
            f"Reading {_extension(path)} files needs a library that is not installed ({e}).{hint}"
        ) from e
    return getattr(module, func_name)
