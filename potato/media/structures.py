"""
Macromolecular structure files: which residues they contain.

The ``protein_structure`` display needs the residue list on the server for two
reasons. The residue table is the keyboard and no-WebGL route to a selection,
so it has to render without the 3D library and without WebGL. And a stored
selection can be checked against the structure it was made on (a residue that
does not exist is a corrupt answer, not a preference): :func:`residue_index`
gives the lookup for that. The server does not run this check on save or
export; it is a helper for scripts that audit stored answers.

Only the atom records are read: chain, residue number, insertion code,
residue name, the B-factor of the residue's CA (or first) atom, and whether
the residue is a HETATM group. Coordinates are left to the viewer.

Formats:

* **mmCIF** (``.cif``, ``.mmcif``). PDB entries released from 2027-07-21 on
  get 12-character IDs and are distributed as mmCIF only, so this is the
  primary format. Chains are ``auth_asym_id`` and numbers ``auth_seq_id``,
  which is what 3Dmol.js and Mol* show; ``label_*`` is the fallback.
* **BinaryCIF** (``.bcif``), the msgpack encoding of mmCIF. Needs ``msgpack``;
  without it the residue table is filled by the viewer instead.
* **PDB** (``.pdb``, ``.ent``), fixed columns, for legacy and tool output.

Any of them may be gzip-compressed (``.gz``). Only the first model of a
multi-model file is read. Water is left out of the table.

A file is read up to :data:`MAX_STRUCTURE_BYTES` (200 MB) after
decompression. A gzip file is inflated as a stream and abandoned at the cap,
so a small file that expands without end costs at most that much memory, and
the display shows a message instead of the residue table.
"""

from __future__ import annotations

import gzip
import logging
import os
import re
import struct
import threading
from collections import OrderedDict
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Residue names treated as solvent and left out of the residue table.
WATER = frozenset({"HOH", "WAT", "DOD", "H2O", "SOL", "TIP", "TIP3", "SPC"})

#: Standard residues and their one-letter codes, for the residue table.
ONE_LETTER = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q",
    "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K",
    "MET": "M", "PHE": "F", "PRO": "P", "SER": "S", "THR": "T", "TRP": "W",
    "TYR": "Y", "VAL": "V", "SEC": "U", "PYL": "O", "MSE": "M",
    "DA": "A", "DC": "C", "DG": "G", "DT": "T", "DU": "U",
    "A": "A", "C": "C", "G": "G", "U": "U", "T": "T", "I": "I",
}

#: Recognised formats, by the extension that names them.
FORMATS = {".cif": "cif", ".mmcif": "cif", ".bcif": "bcif",
           ".pdb": "pdb", ".ent": "pdb"}

#: Largest structure read, in bytes after decompression; past this the
#: server reads no further. Raise it for larger structures.
MAX_STRUCTURE_BYTES = 200 * 1024 * 1024
_CHUNK = 1 << 20


class StructureError(ValueError):
    """The file cannot be read as a structure."""


@dataclass(frozen=True)
class Residue:
    chain: str
    resi: int
    resn: str
    icode: str = ""
    het: bool = False
    b: Optional[float] = None

    @property
    def code(self) -> str:
        """One-letter code, or ``X`` for anything non-standard."""
        return ONE_LETTER.get(self.resn.upper(), "X")

    def key(self) -> Tuple[str, int, str]:
        return (self.chain, self.resi, self.icode)

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        if not self.icode:
            out.pop("icode")
        return out


def detect_format(name: str) -> Tuple[Optional[str], bool]:
    """``(format, gzipped)`` from a file name or URL, or ``(None, gz)``."""
    base = str(name or "").split("?", 1)[0].split("#", 1)[0].lower()
    gz = base.endswith(".gz")
    if gz:
        base = base[:-3]
    return FORMATS.get(os.path.splitext(base)[1]), gz


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def read_residues(path: str, fmt: Optional[str] = None) -> List[Residue]:
    """Residues of the first model in ``path``, in file order."""
    detected, gz = detect_format(path)
    fmt = fmt or detected
    if fmt is None:
        raise StructureError(
            f"{os.path.basename(path)}: not a structure file Potato reads "
            f"(expected .cif, .bcif or .pdb, optionally .gz)")
    raw = _read_capped(path, gz, MAX_STRUCTURE_BYTES)
    if fmt == "bcif":
        return parse_bcif(raw)
    text = raw.decode("utf-8", errors="replace")
    if fmt == "pdb":
        return parse_pdb(text)
    return parse_mmcif(text)


def _too_big(path: str, limit: int) -> StructureError:
    return StructureError(
        f"{os.path.basename(path)}: larger than {limit // (1024 * 1024)} MB once "
        f"decompressed, so the server does not read it")


def _read_capped(path: str, gz: bool, limit: int) -> bytes:
    """The file's bytes, inflated if gzipped, refusing anything over ``limit``."""
    with open(path, "rb") as f:
        magic = f.read(2)
        f.seek(0)
        if not (gz or magic == b"\x1f\x8b"):
            raw = f.read(limit + 1)
            if len(raw) > limit:
                raise _too_big(path, limit)
            return raw
        parts: List[bytes] = []
        total = 0
        try:
            with gzip.GzipFile(fileobj=f, mode="rb") as stream:
                while True:
                    chunk = stream.read(min(_CHUNK, limit + 1 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > limit:
                        raise _too_big(path, limit)
                    parts.append(chunk)
        except (OSError, EOFError) as e:
            raise StructureError(f"{os.path.basename(path)}: bad gzip data ({e})")
        return b"".join(parts)


_CACHE: "OrderedDict[Tuple[str, float, int], Any]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_SIZE = 64


def cached_residues(path: str, fmt: Optional[str] = None) -> List[Residue]:
    """:func:`read_residues`, cached on (path, mtime, size)."""
    st = os.stat(path)
    key = (os.path.realpath(path), st.st_mtime, st.st_size)
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            cached = _CACHE[key]
            if isinstance(cached, StructureError):
                raise cached
            return cached
    try:
        residues = read_residues(path, fmt)
    except StructureError as e:
        # Remembered too: a file refused at the size cap is not inflated
        # again on every page render.
        residues = e
    with _CACHE_LOCK:
        _CACHE[key] = residues
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
    if isinstance(residues, StructureError):
        raise residues
    return residues


class _ResidueCollector:
    """Turns atom rows into residues: one per (chain, resi, icode)."""

    def __init__(self):
        self._order: "OrderedDict[Tuple[str, int, str], Dict[str, Any]]" = OrderedDict()

    def add(self, chain, resi, icode, resn, atom, het, b):
        resn = (resn or "").strip()
        if resn.upper() in WATER:
            return
        key = (chain, resi, icode)
        entry = self._order.get(key)
        if entry is None:
            self._order[key] = {"resn": resn, "het": het, "b": b,
                                "ca": atom == "CA"}
        elif atom == "CA" and not entry["ca"]:
            entry["b"], entry["ca"] = b, True

    def residues(self) -> List[Residue]:
        return [Residue(chain=k[0], resi=k[1], icode=k[2], resn=v["resn"],
                        het=v["het"], b=v["b"])
                for k, v in self._order.items()]


def _float(text) -> Optional[float]:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def parse_pdb(text: str) -> List[Residue]:
    out = _ResidueCollector()
    seen_atoms = False
    for line in text.splitlines():
        record = line[:6]
        if record.startswith("ENDMDL") and seen_atoms:
            break
        if record not in ("ATOM  ", "HETATM"):
            continue
        seen_atoms = True
        try:
            resi = int(line[22:26])
        except ValueError:
            continue
        out.add(chain=line[21:22].strip(), resi=resi, icode=line[26:27].strip(),
                resn=line[17:20], atom=line[12:16].strip(),
                het=record == "HETATM", b=_float(line[60:66]))
    residues = out.residues()
    if not residues:
        raise StructureError("no ATOM or HETATM records")
    return residues


# --- mmCIF -----------------------------------------------------------------

_TOKEN = re.compile(r"""
    '(?:[^']|'(?=\S))*'(?=\s|$)     # single-quoted; a quote not followed by space is literal
  | "(?:[^"]|"(?=\S))*"(?=\s|$)     # double-quoted
  | \S+
""", re.VERBOSE)


def _cif_tokens(text: str) -> Iterable[str]:
    """CIF tokens. Multi-line ``;`` fields come back as one token."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(";"):
            buf = [line[1:]]
            i += 1
            while i < len(lines) and not lines[i].startswith(";"):
                buf.append(lines[i])
                i += 1
            i += 1
            yield "\n".join(buf)
            continue
        for m in _TOKEN.finditer(line):
            tok = m.group(0)
            if tok.startswith("#"):
                break
            if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "'\"":
                tok = "\x00" + tok[1:-1]     # mark "quoted" so it is never a keyword
            yield tok
        i += 1


def _unquote(tok: str) -> str:
    return tok[1:] if tok.startswith("\x00") else tok


def _atom_site_table(text: str) -> Tuple[List[str], List[List[str]]]:
    """The ``_atom_site`` loop's column names and rows."""
    tokens = iter(_cif_tokens(text))
    for tok in tokens:
        if tok.lower() != "loop_":
            continue
        names: List[str] = []
        first_value = None
        for tok in tokens:
            if tok.startswith("_") and not tok.startswith("\x00"):
                names.append(tok)
                continue
            first_value = tok
            break
        if not names or not names[0].lower().startswith("_atom_site."):
            continue
        cols = [n.split(".", 1)[1].lower() for n in names]
        rows: List[List[str]] = []
        row: List[str] = []
        pending = first_value
        while pending is not None:
            low = pending.lower()
            if not pending.startswith("\x00") and (
                    pending.startswith("_") or low == "loop_"
                    or low.startswith("data_") or low.startswith("save_")):
                break
            row.append(_unquote(pending))
            if len(row) == len(cols):
                rows.append(row)
                row = []
            pending = next(tokens, None)
        return cols, rows
    return [], []


def parse_mmcif(text: str) -> List[Residue]:
    cols, rows = _atom_site_table(text)
    if not cols:
        raise StructureError("no _atom_site loop (is this an mmCIF coordinate file?)")
    return _residues_from_columns({c: [r[i] for r in rows] for i, c in enumerate(cols)},
                                  len(rows))


def _residues_from_columns(col: Dict[str, List[Any]], n: int) -> List[Residue]:
    def pick(*names):
        for name in names:
            if name in col:
                return col[name]
        return None

    chain = pick("auth_asym_id", "label_asym_id")
    seq = pick("auth_seq_id", "label_seq_id")
    comp = pick("auth_comp_id", "label_comp_id")
    atom = pick("auth_atom_id", "label_atom_id")
    group = pick("group_pdb")
    icode = pick("pdbx_pdb_ins_code")
    bfac = pick("b_iso_or_equiv")
    model = pick("pdbx_pdb_model_num")
    if chain is None or seq is None or comp is None:
        raise StructureError("_atom_site lacks chain, residue number or residue name columns")

    def val(column, i, default=""):
        if column is None:
            return default
        v = column[i]
        return default if v in (None, ".", "?") else v

    out = _ResidueCollector()
    first_model = val(model, 0, None) if n else None
    for i in range(n):
        if model is not None and val(model, i, None) != first_model:
            break
        try:
            resi = int(float(val(seq, i, "x")))
        except ValueError:
            continue
        out.add(chain=str(val(chain, i)), resi=resi, icode=str(val(icode, i)),
                resn=str(val(comp, i)), atom=str(val(atom, i)),
                het=str(val(group, i)).upper() == "HETATM",
                b=_float(val(bfac, i, None)))
    residues = out.residues()
    if not residues:
        raise StructureError("the _atom_site loop has no usable rows")
    return residues


# --- BinaryCIF ---------------------------------------------------------------

_BYTE_TYPES = {1: "b", 2: "h", 3: "i", 4: "B", 5: "H", 6: "I", 32: "f", 33: "d"}


def _decode(data: Any, encodings: List[Dict[str, Any]]) -> List[Any]:
    """Apply BinaryCIF encodings in reverse order."""
    for enc in reversed(encodings or []):
        kind = enc.get("kind")
        if kind == "ByteArray":
            code = _BYTE_TYPES.get(enc.get("type"))
            if code is None:
                raise StructureError(f"BinaryCIF ByteArray type {enc.get('type')} is not supported")
            size = struct.calcsize(code)
            data = list(struct.unpack(f"<{len(data) // size}{code}", bytes(data)))
        elif kind == "FixedPoint":
            factor = enc["factor"]
            data = [v / factor for v in data]
        elif kind == "IntervalQuantization":
            lo, hi, steps = enc["min"], enc["max"], enc["numSteps"]
            delta = (hi - lo) / (steps - 1) if steps > 1 else 0
            data = [lo + delta * v for v in data]
        elif kind == "RunLength":
            out: List[Any] = []
            for j in range(0, len(data), 2):
                out.extend([data[j]] * data[j + 1])
            data = out
        elif kind == "Delta":
            acc = enc.get("origin", 0)
            out = []
            for v in data:
                acc += v
                out.append(acc)
            data = out
        elif kind == "IntegerPacking":
            nbytes, unsigned = enc["byteCount"], enc["isUnsigned"]
            if unsigned:
                upper, lower = (0xFF, None) if nbytes == 1 else (0xFFFF, None)
            else:
                upper, lower = (0x7F, -0x80) if nbytes == 1 else (0x7FFF, -0x8000)
            out = []
            acc = 0
            for v in data:
                acc += v
                if v == upper or (lower is not None and v == lower):
                    continue
                out.append(acc)
                acc = 0
            data = out
        elif kind == "StringArray":
            strings = enc["stringData"]
            offsets = _decode(enc["offsets"], enc["offsetEncoding"])
            indices = _decode(data, enc["dataEncoding"])
            table = [strings[offsets[k]:offsets[k + 1]] for k in range(len(offsets) - 1)]
            data = [table[k] if k >= 0 else None for k in indices]
        else:
            raise StructureError(f"BinaryCIF encoding {kind!r} is not supported")
    return data


def parse_bcif(raw: bytes) -> List[Residue]:
    try:
        import msgpack
    except ImportError:
        raise StructureError("reading BinaryCIF needs the msgpack package (pip install msgpack)")
    try:
        doc = msgpack.unpackb(raw, raw=False)
    except Exception as e:  # noqa: BLE001 - any decode failure is "not BinaryCIF"
        raise StructureError(f"not a BinaryCIF file ({e})")
    for block in doc.get("dataBlocks") or []:
        for cat in block.get("categories") or []:
            if str(cat.get("name", "")).lower() != "_atom_site":
                continue
            n = cat.get("rowCount", 0)
            col: Dict[str, List[Any]] = {}
            for column in cat.get("columns") or []:
                values = _decode(column["data"]["data"], column["data"]["encoding"])
                mask = column.get("mask")
                if mask:
                    flags = _decode(mask["data"], mask["encoding"])
                    values = [None if f else v for v, f in zip(values, flags)]
                col[str(column["name"]).lower()] = [
                    (str(v) if isinstance(v, str) else v) for v in values]
            # Integer-valued columns decode as ints; the collector wants text
            # for the string columns and handles numbers for the rest.
            for name in ("auth_asym_id", "label_asym_id", "auth_comp_id",
                         "label_comp_id", "auth_atom_id", "label_atom_id",
                         "group_pdb", "pdbx_pdb_ins_code"):
                if name in col:
                    col[name] = [None if v is None else str(v) for v in col[name]]
            if "pdbx_pdb_model_num" in col:
                col["pdbx_pdb_model_num"] = [None if v is None else str(v)
                                             for v in col["pdbx_pdb_model_num"]]
            return _residues_from_columns(col, n)
    raise StructureError("no _atom_site category in the BinaryCIF file")


# ---------------------------------------------------------------------------
# Selections against a structure
# ---------------------------------------------------------------------------

def residue_index(residues: Iterable[Residue]) -> Dict[Tuple[str, int, str], Residue]:
    """Residues keyed by ``(chain, resi, icode)``, for checking a stored
    selection against its structure. Not called by the server."""
    return {r.key(): r for r in residues}


def chains(residues: Iterable[Residue]) -> "OrderedDict[str, List[Residue]]":
    """Residues grouped by chain, chains in file order."""
    out: "OrderedDict[str, List[Residue]]" = OrderedDict()
    for r in residues:
        out.setdefault(r.chain, []).append(r)
    return out


__all__ = ["Residue", "StructureError", "detect_format", "read_residues",
           "cached_residues", "parse_pdb", "parse_mmcif", "parse_bcif",
           "residue_index", "chains", "FORMATS", "WATER"]
