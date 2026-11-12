"""Scientific annotation as training data: molecules, spectra, signals, episodes.

Four input families the vision and audio layers do not cover:

* a **molecule** shown by a ``molecule`` display, or drawn in a
  ``chemical_structure`` answer, as the input to a radio, select, likert or
  slider question about it (``rdkit-property``);
* a **spectrum** bound by a ``peak_picking`` scheme, whose answer is the
  peaks an annotator accepted or added (``peak-cnn``);
* a **signal** bound by an ``interval_label`` scheme, whose answer is
  labelled intervals or epochs (``signal-cnn``);
* a robot **episode** bound by an ``episode_annotation`` scheme, whose answer
  is phases, an outcome and a reward curve (``episode-model``).

The targets here are what those answers mean for training, read from the
stored blob. The inputs are what the bundle needs to find the data again on
another machine: a spectrum, signal or episode file is linked into the
bundle's media like an image, and a molecule's structure, which is a few
hundred bytes, is written into the row.

Standard library only; numpy and the file readers are the trainers' business.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["SCIENCE_KINDS", "SCIENCE_TYPES", "MOLECULE_TYPES", "peaks_target",
           "intervals_target", "episode_target", "science_input",
           "molecule_source", "molecule_text", "display_field", "wfdb_siblings"]

#: Training kinds of the three scheme types below.
SCIENCE_KINDS = ("peaks", "intervals", "episode")

#: Scheme types whose input is a file or value named by another field, which
#: the bundle links itself (never through the image-key scan).
SCIENCE_TYPES = frozenset({"peak_picking", "interval_label", "episode_annotation"})

#: Question types a molecule property model answers.
MOLECULE_TYPES = ("radio", "select", "likert", "slider")


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _blob(value_map: Any) -> Any:
    from potato.training.vision import blob
    return blob(value_map)


def _labels(scheme: Dict[str, Any], key: str = "labels") -> List[str]:
    return [str(l.get("name") if isinstance(l, dict) else l)
            for l in (scheme or {}).get(key) or []]


# ------------------------------------------------------------------ targets

def peaks_target(value_map: Any) -> Optional[Dict[str, Any]]:
    """The peaks a ``peak_picking`` answer kept, ``{peaks: [{x, label?}],
    rejected: [x]}``: accepted suggestions and added peaks alike, since both
    are peaks the annotator says are there. A rejected-only answer is a
    target too (no peaks here); an empty one is not."""
    answer = _blob(value_map)
    if not isinstance(answer, dict):
        return None
    peaks = []
    for item in answer.get("items") or []:
        if not isinstance(item, dict) or item.get("kind") != "peak":
            continue
        x = _number(item.get("x"))
        if x is None:
            continue
        entry: Dict[str, Any] = {"x": x}
        label = (item.get("fields") or {}).get("label") if isinstance(
            item.get("fields"), dict) else None
        label = label or item.get("label")
        if isinstance(label, str) and label.strip():
            entry["label"] = label.strip()
        peaks.append(entry)
    rejected = sorted(v for v in (_number(r) for r in answer.get("rejected") or [])
                      if v is not None)
    if not peaks and not rejected:
        return None
    return {"peaks": sorted(peaks, key=lambda p: p["x"]), "rejected": rejected}


def interval_labels(scheme: Dict[str, Any]) -> List[str]:
    """The scheme's interval labels (not its point events), in order."""
    from potato.server_utils.schemas.interval_label import labels_of
    return [lab["name"] for lab in labels_of(scheme or {}) if lab["kind"] != "event"]


def intervals_target(scheme: Dict[str, Any], value_map: Any) -> Optional[Dict[str, Any]]:
    """An ``interval_label`` answer's intervals under the scheme's interval
    labels, with the mode the scheme labels in. Point events are not a
    target: the model labels time, and a moment is not a stretch of it."""
    answer = _blob(value_map)
    if not isinstance(answer, dict):
        return None
    known = set(interval_labels(scheme))
    out = []
    for iv in answer.get("intervals") or []:
        if not isinstance(iv, dict) or str(iv.get("label")) not in known:
            continue
        start, end = _number(iv.get("start")), _number(iv.get("end"))
        if start is None or end is None or end <= start:
            continue
        out.append({"start": start, "end": end, "label": str(iv["label"])})
    if not out:
        return None
    mode = (scheme or {}).get("mode", "free")
    length = _number((scheme or {}).get("epoch_length", 30)) or 30.0
    return {"mode": "epoch" if mode == "epoch" else "free", "epoch_length": length,
            "intervals": sorted(out, key=lambda i: (i["start"], i["end"]))}


def episode_phases(scheme: Dict[str, Any]) -> List[str]:
    from potato.server_utils.schemas.episode_annotation import DEFAULT_PHASES
    phases = (scheme or {}).get("phases", DEFAULT_PHASES)
    return [str(p.get("name") if isinstance(p, dict) else p) for p in phases or []]


def episode_outcomes(scheme: Dict[str, Any]) -> List[str]:
    from potato.server_utils.schemas.episode_annotation import DEFAULT_OUTCOMES
    return [str(o) for o in (scheme or {}).get("outcomes", DEFAULT_OUTCOMES) or []]


def episode_target(scheme: Dict[str, Any], value_map: Any) -> Optional[Dict[str, Any]]:
    """An ``episode_annotation`` answer's three learnable layers: phases (in
    the scheme's taxonomy), the outcome, and the reward curve. Instructions
    are text, and not learned here."""
    answer = _blob(value_map)
    if not isinstance(answer, dict):
        return None
    known = set(episode_phases(scheme))
    phases = []
    for p in answer.get("phases") or []:
        if not isinstance(p, dict) or str(p.get("label")) not in known:
            continue
        start, end = _number(p.get("start")), _number(p.get("end"))
        if start is None or end is None or end <= start:
            continue
        phases.append({"start": start, "end": end, "label": str(p["label"])})
    outcome = answer.get("outcome")
    result = outcome.get("result") if isinstance(outcome, dict) else outcome
    result = str(result) if result not in (None, "") and str(result) in episode_outcomes(
        scheme) else None
    reward = []
    for point in answer.get("reward") or []:
        if isinstance(point, dict):
            t, v = _number(point.get("t")), _number(point.get("value"))
            if t is not None and v is not None:
                reward.append({"t": t, "value": v})
    reward.sort(key=lambda r: r["t"])
    if not phases and result is None and len(reward) < 2:
        return None
    return {"phases": sorted(phases, key=lambda p: p["start"]), "outcome": result,
            "reward": reward if len(reward) >= 2 else []}


# ------------------------------------------------------------------- inputs

def display_field(config: Dict[str, Any], key: Optional[str]) -> Dict[str, Any]:
    """The instance_display field with this key, or ``{}``."""
    for field in ((config or {}).get("instance_display") or {}).get("fields") or []:
        if isinstance(field, dict) and key and field.get("key") == key:
            return field
    return {}


def _options(field: Dict[str, Any]) -> Dict[str, Any]:
    """A display field's options, flat or under ``display_options``."""
    options = dict(field.get("display_options") or {})
    for key, value in field.items():
        if key not in ("key", "type", "label", "display_options"):
            options.setdefault(key, value)
    return options


_SPECTRUM_OPTIONS = ("scan", "index", "block", "peak_direction", "spectrum_type")
_SIGNAL_OPTIONS = ("channels", "time_column", "annotation_extension")


def science_input(config: Dict[str, Any], scheme: Dict[str, Any],
                  item_data: Dict[str, Any]) -> Dict[str, Any]:
    """Where a science scheme's input is: ``{"ref": file}`` to link into the
    bundle, or ``{"inline": value}`` for data written in the item, with the
    options a reader needs (a scan number, the channels to read).

    Empty when the item has nothing in the field.
    """
    atype = (scheme or {}).get("annotation_type")
    if atype == "peak_picking":
        key = scheme.get("viewer_field")
        options = {k: v for k, v in _options(display_field(config, key)).items()
                   if k in _SPECTRUM_OPTIONS and v is not None}
    elif atype == "interval_label":
        key = scheme.get("signal_field")
        options = {k: v for k, v in _options(display_field(config, key)).items()
                   if k in _SIGNAL_OPTIONS and v is not None}
    elif atype == "episode_annotation":
        key = scheme.get("source_field", "episode")
        options = {}
        episode = item_data.get(scheme.get("episode_field", "episode_index"))
        if episode not in (None, ""):
            options["episode"] = episode
    else:
        return {}
    value = item_data.get(key) if key else None
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        if atype == "peak_picking" and not ("x" in value or "y" in value):
            # {"file": ..., "scan": n}: the file, and the item's own selector.
            ref = value.get("file") or value.get("path")
            for k in ("scan", "index", "block"):
                if value.get(k) is not None:
                    options[k] = value[k]
            if value.get("peaks") is not None:
                options["item_peaks"] = True
            return {"ref": str(ref), "options": options} if ref else {}
        return {"inline": value, "options": options}
    return {"ref": str(value), "options": options}


def wfdb_siblings(source: str) -> List[str]:
    """The files a WFDB header names beside it (``100.dat``, ``100.atr``):
    a header linked alone reads as a record with no samples."""
    folder, name = os.path.split(source)
    stem = os.path.splitext(name)[0]
    try:
        return sorted(os.path.join(folder, f) for f in os.listdir(folder or ".")
                      if os.path.splitext(f)[0] == stem and f != name)
    except OSError:
        return []


def molecule_source(config: Dict[str, Any], scheme: Dict[str, Any]
                    ) -> Optional[Tuple[str, str]]:
    """Where a question's molecule comes from: ``("display", field)`` for a
    ``molecule`` display, or ``("answer", scheme)`` for a
    ``chemical_structure`` answer (whose ``prefill_field`` the bundle falls
    back on). None for a question that is not about a molecule."""
    if (scheme or {}).get("annotation_type") not in MOLECULE_TYPES:
        return None
    for field in ((config or {}).get("instance_display") or {}).get("fields") or []:
        if isinstance(field, dict) and field.get("type") == "molecule" and field.get("key"):
            return "display", str(field["key"])
    for other in (config or {}).get("annotation_schemes") or []:
        if isinstance(other, dict) and other.get("annotation_type") == "chemical_structure":
            return "answer", str(other.get("name"))
    return None


def chemical_prefill_field(config: Dict[str, Any], name: str) -> Optional[str]:
    for other in (config or {}).get("annotation_schemes") or []:
        if isinstance(other, dict) and other.get("name") == name:
            return other.get("prefill_field") or None
    return None


def molecule_text(value: Any, task_dir: str, media_directory: str = "media",
                  max_bytes: int = 2_000_000) -> Optional[str]:
    """A SMILES string or molfile from a display field's value: the text
    itself, or the file it names (``.mol``, first ``.sdf`` record, ``.smi``)
    inside the task or media directory. None when there is none."""
    from potato.chemistry import structures
    if not isinstance(value, str) or not value.strip():
        return None
    if not structures.is_structure_path(value):
        if structures.check_structure_text(value) is not None:
            return None
        # A molfile's first lines are its header, blank or not.
        return value if structures.looks_like_molfile(value) else value.strip()
    from potato.training.dataset import _media_file
    path = _media_file(value.strip(), task_dir, media_directory)
    real = os.path.realpath(path)
    base = (media_directory if os.path.isabs(media_directory)
            else os.path.join(task_dir, media_directory))
    roots = [os.path.realpath(task_dir), os.path.realpath(base)]
    if not any(real.startswith(root + os.sep) for root in roots) or not os.path.isfile(real):
        return None
    if os.path.getsize(real) > max_bytes:
        return None
    try:
        return structures.read_structure_file(real)
    except (OSError, ValueError, UnicodeError):
        return None


def answer_structure(value_map: Any) -> Optional[str]:
    """The structure a ``chemical_structure`` answer holds (molfile first,
    then SMILES), or None."""
    from potato.chemistry.structures import parse_stored
    values = value_map.values() if isinstance(value_map, dict) else [value_map]
    for value in values:
        answer = parse_stored(value)
        for key in ("molfile", "smiles"):
            if isinstance(answer.get(key), str) and answer[key].strip():
                return answer[key]
    return None


def stored_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value
