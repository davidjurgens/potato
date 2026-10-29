"""
Structure text, stored answers and answer keys for chemistry schemes.

Stored answer (``chemical_structure``), one JSON object in a hidden input::

    {"molfile": "<MDL molfile V3000>",
     "smiles": "<OpenChemLib canonical isomeric SMILES>",
     "idcode": "<OpenChemLib ID code>",
     "formula": "C9H8O4",
     "rdkit_smiles": "...", "inchi": "InChI=1S/...", "inchikey": "...",   # RDKit.js only
     "changed": true,             # false: the pre-filled structure, untouched
     "problems": ["..."],         # valence and sanitization problems found
     "toolkits": {"openchemlib": "9.25.0", "rdkit": "2026.03.6"}}

Answer keys are graded on the server (they never reach the page). A key is
either a SMILES string or a mapping::

    {"smiles": "CC(=O)Oc1ccccc1C(=O)O"}           # same structure (InChIKey)
    {"inchikey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"}
    {"molfile": "..."}
    {"smiles": "...", "ignore_stereo": true}      # InChIKey first block only
    {"substructure": "C(=O)[OH]"}                 # SMARTS that must match
    {"substructure": ["c1ccccc1", "C(=O)O"], "not_substructure": "[N+](=O)[O-]"}

Grading uses the ``rdkit`` Python package (``potato-annotation[chemistry]``).
One case works without it: a key given as ``inchikey`` against an answer that
carries an InChIKey computed by RDKit.js in the browser. That InChIKey comes
from the annotator's browser; when the package is installed the server
recomputes it from the stored molfile instead.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from . import MAX_STRUCTURE_BYTES, PY_EXTRA_HINT, rdkit_python

logger = logging.getLogger(__name__)

#: File extensions the molecule display and prefill read from the media directory.
STRUCTURE_EXTENSIONS = (".mol", ".sdf", ".smi", ".smiles")

ANSWER_KEY_KEYS = frozenset({"smiles", "molfile", "inchikey", "ignore_stereo",
                             "substructure", "not_substructure"})
_STRUCTURE_KEYS = ("smiles", "molfile", "inchikey")

_warned_missing = False


# ---------------------------------------------------------------------------
# Structure text
# ---------------------------------------------------------------------------

def looks_like_molfile(text: str) -> bool:
    return isinstance(text, str) and ("M  END" in text or "V2000" in text or "V3000" in text)


def detect_format(text: str, declared: str = "auto") -> str:
    """``smiles`` or ``molfile`` for a structure text."""
    if declared in ("smiles", "molfile"):
        return declared
    return "molfile" if looks_like_molfile(text) else "smiles"


def first_sdf_record(text: str) -> str:
    """The first molecule of an SD file (everything before the first ``$$$$``)."""
    head = text.split("$$$$", 1)[0]
    end = head.find("M  END")
    return head[:end + len("M  END")] + "\n" if end >= 0 else head


def is_structure_path(value: Any) -> bool:
    return (isinstance(value, str) and "\n" not in value and len(value) < 1024
            and value.strip().lower().endswith(STRUCTURE_EXTENSIONS))


def read_structure_file(path: str) -> str:
    """Text of a structure file, size-limited. ``.sdf``: the first record;
    ``.smi``: the first token of the first non-empty line."""
    size = os.path.getsize(path)
    if size > MAX_STRUCTURE_BYTES:
        raise ValueError(f"the structure file is {size} bytes, over the "
                         f"{MAX_STRUCTURE_BYTES}-byte limit")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    lower = path.lower()
    if lower.endswith(".sdf"):
        return first_sdf_record(text)
    if lower.endswith((".smi", ".smiles")):
        for line in text.splitlines():
            if line.strip():
                return line.split()[0]
        return ""
    return text


def check_structure_text(text: Any) -> Optional[str]:
    """A problem with structure text taken from item data, or None."""
    if not isinstance(text, str) or not text.strip():
        return "there is no structure"
    if len(text.encode("utf-8", errors="replace")) > MAX_STRUCTURE_BYTES:
        return f"the structure text is over the {MAX_STRUCTURE_BYTES}-byte limit"
    if not looks_like_molfile(text) and any(c.isspace() for c in text.strip()):
        return ("the value is neither a molfile nor a single SMILES string "
                "(a SMILES has no spaces)")
    return None


# ---------------------------------------------------------------------------
# Stored answers
# ---------------------------------------------------------------------------

def parse_stored(value: Any) -> Dict[str, Any]:
    """A stored chemical_structure answer as a dict ({} when empty or not JSON).

    Accepts the JSON text, the dict, or a ``{label_name: json}`` mapping as
    the export context holds it.
    """
    if isinstance(value, dict) and len(value) == 1 and not (
            set(value) & {"molfile", "smiles", "idcode"}):
        value = next(iter(value.values()))
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _mol_from(Chem, text: str, fmt: str = "auto"):
    if not isinstance(text, str) or not text.strip():
        return None
    if detect_format(text, fmt) == "molfile":
        return Chem.MolFromMolBlock(text)
    return Chem.MolFromSmiles(text.strip())


def answer_mol(Chem, answer: Dict[str, Any]):
    """An RDKit molecule for a stored answer (molfile first, then SMILES)."""
    for key, fmt in (("molfile", "molfile"), ("smiles", "smiles")):
        mol = _mol_from(Chem, answer.get(key) or "", fmt)
        if mol is not None:
            return mol
    return None


def server_identifiers(answer: Dict[str, Any]) -> Dict[str, str]:
    """``{rdkit_smiles, inchi, inchikey}`` computed with the RDKit Python
    package from the stored molfile, or ``{}`` (package missing, no
    structure, or RDKit cannot read it)."""
    Chem = rdkit_python()
    if Chem is None:
        return {}
    mol = answer_mol(Chem, answer)
    if mol is None or mol.GetNumAtoms() == 0:
        return {}
    out = {"rdkit_smiles": Chem.MolToSmiles(mol)}
    try:
        inchi = Chem.MolToInchi(mol)
        if inchi:
            out["inchi"] = inchi
            out["inchikey"] = Chem.InchiToInchiKey(inchi)
    except Exception:   # an RDKit build without InChI
        pass
    return out


# ---------------------------------------------------------------------------
# Answer keys
# ---------------------------------------------------------------------------

def is_answer_key(value: Any) -> bool:
    """Whether a gold or training answer is a chemical-structure key (a
    mapping with only answer-key fields and at least one structure or
    substructure field)."""
    return (isinstance(value, dict) and bool(value)
            and set(value) <= ANSWER_KEY_KEYS
            and bool(set(value) & (set(_STRUCTURE_KEYS) | {"substructure", "not_substructure"})))


def normalize_key(value: Any) -> Optional[Dict[str, Any]]:
    """An answer key as a mapping (a bare string is a SMILES or a molfile)."""
    if isinstance(value, str) and value.strip():
        return {"molfile": value} if looks_like_molfile(value) else {"smiles": value.strip()}
    if is_answer_key(value):
        return value
    return None


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def validate_answer_key(value: Any, where: str) -> List[str]:
    """Problems with one answer key (types only; no toolkit needed)."""
    key = normalize_key(value)
    if key is None:
        return [f"{where} must be a SMILES string or a mapping with smiles, molfile, "
                f"inchikey, substructure or not_substructure"]
    errors = []
    present = [k for k in _STRUCTURE_KEYS if k in key]
    if len(present) > 1:
        errors.append(f"{where} names the structure twice ({', '.join(present)}); give one")
    for k in present:
        if not isinstance(key[k], str) or not key[k].strip():
            errors.append(f"{where}.{k} must be text")
    if "inchikey" in key and isinstance(key["inchikey"], str) and len(key["inchikey"].strip()) != 27:
        errors.append(f"{where}.inchikey must be a 27-character InChIKey")
    for k in ("substructure", "not_substructure"):
        if k in key and (not _as_list(key[k]) or not all(
                isinstance(p, str) and p.strip() for p in _as_list(key[k]))):
            errors.append(f"{where}.{k} must be a SMARTS pattern or a list of them")
    if "ignore_stereo" in key and not isinstance(key["ignore_stereo"], bool):
        errors.append(f"{where}.ignore_stereo must be true or false")
    if "ignore_stereo" in key and not present:
        errors.append(f"{where}.ignore_stereo needs a smiles, molfile or inchikey to compare with")
    return errors


def _key_matches(given: str, expected: str, ignore_stereo: bool) -> bool:
    if not given or not expected:
        return False
    if ignore_stereo:
        return given[:14] == expected[:14]
    return given == expected


def _missing_rdkit(reason: str) -> None:
    global _warned_missing
    if not _warned_missing:
        logger.error("chemical structure answer keys: %s needs the rdkit Python package, "
                     "which is not installed; such answers are graded wrong. Install it "
                     "with `%s`.", reason, PY_EXTRA_HINT)
        _warned_missing = True


def grade(stored: Any, key_value: Any) -> Tuple[bool, str]:
    """``(correct, reason)`` for one stored answer against one answer key."""
    key = normalize_key(key_value)
    if key is None:
        return False, "the answer key is not a structure key"
    answer = parse_stored(stored)
    if isinstance(stored, str) and not answer and stored.strip():
        answer = {"molfile": stored} if looks_like_molfile(stored) else {"smiles": stored.strip()}
    if not answer or not (answer.get("molfile") or answer.get("smiles")):
        return False, "no structure was drawn"
    ignore = bool(key.get("ignore_stereo"))
    needs_substructure = bool(key.get("substructure") or key.get("not_substructure"))
    Chem = rdkit_python()

    if Chem is None:
        if needs_substructure or "inchikey" not in key:
            _missing_rdkit("a smiles, molfile or substructure key")
            return False, f"grading needs the rdkit package ({PY_EXTRA_HINT})"
        if not answer.get("inchikey"):
            _missing_rdkit("an answer without a browser InChIKey")
            return False, "the answer has no InChIKey (RDKit.js was not loaded)"
        ok = _key_matches(answer["inchikey"], key["inchikey"].strip(), ignore)
        return ok, "same InChIKey" if ok else "different InChIKey"

    mol = answer_mol(Chem, answer)
    if mol is None:
        return False, "RDKit cannot read the drawn structure"
    reasons = []
    if any(k in key for k in _STRUCTURE_KEYS):
        given = Chem.MolToInchiKey(mol)
        if "inchikey" in key:
            expected = key["inchikey"].strip()
        else:
            ref = _mol_from(Chem, key.get("smiles") or key.get("molfile") or "",
                            "smiles" if "smiles" in key else "molfile")
            if ref is None:
                return False, "RDKit cannot read the answer key's structure"
            expected = Chem.MolToInchiKey(ref)
        if not _key_matches(given, expected, ignore):
            return False, "a different structure" + (" (ignoring stereo)" if ignore else "")
        reasons.append("same structure")
    for pattern in _as_list(key.get("substructure")):
        query = Chem.MolFromSmarts(pattern)
        if query is None:
            return False, f"the answer key's substructure {pattern!r} is not valid SMARTS"
        if not mol.HasSubstructMatch(query):
            return False, f"missing the substructure {pattern}"
        reasons.append(f"contains {pattern}")
    for pattern in _as_list(key.get("not_substructure")):
        query = Chem.MolFromSmarts(pattern)
        if query is None:
            return False, f"the answer key's substructure {pattern!r} is not valid SMARTS"
        if mol.HasSubstructMatch(query):
            return False, f"contains the excluded substructure {pattern}"
        reasons.append(f"has no {pattern}")
    return True, "; ".join(reasons)


def answer_is_correct(stored: Any, key_value: Any) -> bool:
    return grade(stored, key_value)[0]


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def chemical_schemes(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [s for s in (config or {}).get("annotation_schemes") or []
            if isinstance(s, dict) and s.get("annotation_type") == "chemical_structure"]


def private_item_fields(config: Dict[str, Any]) -> List[str]:
    """Item fields holding answer keys; stripped from what the page receives."""
    return [str(s["answer_field"]) for s in chemical_schemes(config) if s.get("answer_field")]


def required_bundles(config: Dict[str, Any]) -> List[str]:
    """The RDKit.js bundle, when a scheme asks for it with ``rdkit: true``."""
    from . import RDKIT_BUNDLE
    return [RDKIT_BUNDLE] if any(s.get("rdkit") is True for s in chemical_schemes(config)) else []
