"""
The Potato side of the FiftyOne annotation backend, without FiftyOne.

`fiftyone_backend.py` is the class FiftyOne loads. It turns a view into plain
dicts and calls this module, which writes those dicts out as a runnable Potato
project and, after people have annotated it, reads every annotator's answers
back, merges them into one label per sample, and measures how far the
annotators agreed. Nothing here imports FiftyOne, so all of it is tested in
Potato's own environment.

Answers move in Potato's own shapes, which are close to FiftyOne's:

    classification   str                 the class name
    classifications  list[str]           class names
    detections       list[client obj]    {"type": "bbox", "coordinates": {x, y, width, height}}
    polylines        list[client obj]    {"type": "polygon" | "polyline", "coordinates": [{x, y}, ...]}

Client objects use coordinates normalised to [0, 1] with the origin at the top
left, the same convention as FiftyOne's ``bounding_box`` and polyline points, so
no conversion through pixel sizes is needed in either direction.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import urllib.parse
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

#: FiftyOne label type -> what Potato asks for it.
LABEL_TYPES = {
    "classification": "radio",
    "classifications": "multiselect",
    "detection": "bbox",
    "detections": "bbox",
    "polyline": "polyline",
    "polylines": "polyline",
    "polygon": "polygon",
    "polygons": "polygon",
}
GEOMETRY_TOOLS = {"bbox", "polygon", "polyline"}
#: Written beside config.yaml; the download reads it instead of trusting
#: FiftyOne's copy of the run, so a project moved between machines still loads.
MANIFEST = "fiftyone_run.json"
IMAGE_KEY = "image_url"


def potato_kind(label_type: str) -> str:
    try:
        return LABEL_TYPES[label_type]
    except KeyError:
        raise ValueError(
            f"Potato's FiftyOne backend does not support label type "
            f"{label_type!r}; supported: {', '.join(sorted(LABEL_TYPES))}")


def build_scheme(field: str, label_type: str, classes: List[str]) -> dict:
    """One Potato annotation scheme for one FiftyOne label field."""
    if not classes:
        raise ValueError(
            f"Field {field!r} has no classes. Pass classes=[...] to annotate(), "
            f"or annotate a field that already has labels.")
    kind = potato_kind(label_type)
    description = field.replace("_", " ").strip().capitalize() or field
    if kind in ("radio", "multiselect"):
        return {"annotation_type": kind, "name": field,
                "description": description, "labels": [str(c) for c in classes]}
    return {"annotation_type": "image_annotation", "name": field,
            "description": description, "source_field": IMAGE_KEY,
            "tools": [kind], "labels": [{"name": str(c)} for c in classes]}


# ---------------------------------------------------------------------------
# Writing the project
# ---------------------------------------------------------------------------

def _media_reference(filepath: str, project: Path, mode: str,
                     root: Optional[str], sample_id: str) -> str:
    if filepath.startswith(("http://", "https://")):
        return filepath
    if mode == "reference":
        rel = os.path.relpath(os.path.abspath(filepath), root)
        return "/media/" + urllib.parse.quote(rel.replace(os.sep, "/"))
    target = project / "media" / f"{sample_id}{Path(filepath).suffix.lower()}"
    if not target.exists():
        shutil.copy2(filepath, target)
    return "/media/" + urllib.parse.quote(target.name)


def _common_root(paths: List[str]) -> str:
    local = [os.path.abspath(p) for p in paths
             if not p.startswith(("http://", "https://"))]
    if not local:
        return ""
    root = os.path.commonpath([os.path.dirname(p) for p in local])
    if root in (os.sep, os.path.expanduser("~")) or os.path.dirname(root) == root:
        # Serving / or a whole home directory to anyone holding the study URL
        # is not a trade-off to make on someone's behalf.
        raise ValueError(
            f"media='reference' would serve everything under {root!r}. Move the "
            f"images under one project folder, or use media='copy'.")
    return root


def write_project(project_dir: str, samples: List[dict],
                  label_schema: Dict[str, dict], *, task_name: str,
                  annotations_per_item: int = 2, media: str = "copy",
                  anno_key: str = "", dataset_name: str = "") -> Dict[str, Any]:
    """Write a Potato project for a FiftyOne view.

    Args:
        project_dir: created if missing.
        samples: ``[{"id", "filepath", "existing": {field: answer}}]``, answers
            in the shapes in the module docstring. Existing answers are shown
            as pre-annotations for the annotator to correct.
        label_schema: ``{field: {"type": label_type, "classes": [...]}}``.
        annotations_per_item: how many people should label each sample.
        media: ``"copy"`` copies each image into ``<project>/media``;
            ``"reference"`` serves the images from their folder in place.

    Returns:
        The manifest, also written to ``<project>/fiftyone_run.json``.
    """
    from potato.importers.projects.base import ProjectImportResult, ProjectItem
    from potato.importers.projects.writer import write_project as write

    if media not in ("copy", "reference"):
        raise ValueError(f"media must be 'copy' or 'reference', not {media!r}")
    if annotations_per_item < 1:
        raise ValueError("annotations_per_item must be at least 1")
    project = Path(project_dir)
    (project / "media").mkdir(parents=True, exist_ok=True)
    root = _common_root([s["filepath"] for s in samples]) if media == "reference" else None

    schemes = [build_scheme(field, info["type"], list(info.get("classes") or []))
               for field, info in label_schema.items()]
    result = ProjectImportResult(source_format="FiftyOne", schemes=schemes,
                                 text_key=IMAGE_KEY)
    if not any(s["annotation_type"] == "image_annotation" for s in schemes):
        # A radio or multiselect question does not show the image by itself.
        result.instance_display = {
            "fields": [{"key": IMAGE_KEY, "type": "image", "label": "Image"}]}
    for sample in samples:
        item = ProjectItem(instance_id=str(sample["id"]), fields={
            IMAGE_KEY: _media_reference(str(sample["filepath"]), project, media,
                                        root, str(sample["id"]))})
        for field, answer in (sample.get("existing") or {}).items():
            if answer not in (None, [], ""):
                item.predictions[field] = answer
        result.items.append(item)

    extra: Dict[str, Any] = {"max_annotations_per_item": annotations_per_item}
    if media == "reference":
        extra["media_directory"] = root
    readme = project / "README.md"
    if not readme.exists():
        readme.write_text(_readme(task_name, project.resolve().name, len(samples),
                                  label_schema, annotations_per_item, anno_key),
                          encoding="utf-8")
    write(result, str(project), source="fiftyone", stem="samples",
          extra_config=extra, task_name=task_name)

    manifest = {
        "anno_key": anno_key,
        "dataset": dataset_name,
        "label_schema": {f: {"type": i["type"], "classes": list(i.get("classes") or [])}
                         for f, i in label_schema.items()},
        "sample_ids": [str(s["id"]) for s in samples],
        "annotations_per_item": annotations_per_item,
        "media": media,
    }
    (project / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _readme(task_name, folder, n, label_schema, per_item, anno_key) -> str:
    fields = "\n".join(f"- `{f}`: {i['type']}, classes {', '.join(map(str, i.get('classes') or []))}"
                       for f, i in label_schema.items())
    return f"""# {task_name}

Written by Potato's FiftyOne annotation backend for annotation run
`{anno_key}`: {n} samples, {per_item} annotator(s) per sample.

{fields}

Start it from this folder's parent:

```bash
potato start {folder}/config.yaml -p 8000
```

When the annotators have finished, load the labels back in FiftyOne with
`dataset.load_annotations("{anno_key}")`.
"""


def load_manifest(project_dir: str) -> Dict[str, Any]:
    path = Path(project_dir) / MANIFEST
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing; this folder was not written by Potato's "
            f"FiftyOne backend, or it has moved.")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Reading answers back
# ---------------------------------------------------------------------------

def _output_dir(project_dir: str) -> Path:
    import yaml
    config = yaml.safe_load((Path(project_dir) / "config.yaml").read_text(encoding="utf-8")) or {}
    return Path(project_dir) / str(config.get("output_annotation_dir") or "annotation_output")


def _answer_from_entries(kind: str, entries: List[Any]) -> Any:
    """One annotator's stored label entries for one scheme -> an answer."""
    if kind == "radio":
        names = [e[0].get("name") for e in entries if e[1] not in (None, False, "", "false")]
        return str(names[-1]) if names else None
    if kind == "multiselect":
        names = sorted({str(e[0].get("name")) for e in entries
                        if e[1] not in (None, False, "", "false")})
        return names or None
    for label, value in entries:
        if label.get("name") == "_data":
            return _objects(value)
    return None


def _objects(value: Any) -> Optional[List[dict]]:
    """A stored image answer (a JSON string, a list, or ``{"_data": ...}``)."""
    if isinstance(value, dict) and "_data" in value:
        value = value["_data"]
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else []
        except ValueError:
            return None
    if not isinstance(value, list):
        return None
    return [o for o in value if isinstance(o, dict) and o.get("type")]


def read_answers(project_dir: str) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """``{field: {sample_id: {annotator: answer}}}`` for every saved answer."""
    manifest = load_manifest(project_dir)
    kinds = {f: potato_kind(i["type"]) for f, i in manifest["label_schema"].items()}
    out: Dict[str, Dict[str, Dict[str, Any]]] = {f: {} for f in kinds}
    output = _output_dir(project_dir)
    if not output.is_dir():
        return out
    for state_path in sorted(output.glob("*/user_state.json")):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        user = str(state.get("user_id") or state_path.parent.name)
        for iid, entries in (state.get("instance_id_to_label_to_value") or {}).items():
            by_schema: Dict[str, list] = {}
            for entry in entries or []:
                if (isinstance(entry, (list, tuple)) and len(entry) == 2
                        and isinstance(entry[0], dict)):
                    by_schema.setdefault(entry[0].get("schema"), []).append(entry)
            for field, kind in kinds.items():
                if field not in by_schema:
                    continue
                answer = _answer_from_entries(kind, by_schema[field])
                if answer is not None:
                    out[field].setdefault(str(iid), {})[user] = answer
    return out


def read_adjudicated(project_dir: str) -> Dict[str, Dict[str, Any]]:
    """``{field: {sample_id: answer}}`` from the adjudication queue's decisions."""
    import yaml
    manifest = load_manifest(project_dir)
    kinds = {f: potato_kind(i["type"]) for f, i in manifest["label_schema"].items()}
    config = yaml.safe_load((Path(project_dir) / "config.yaml").read_text(encoding="utf-8")) or {}
    subdir = ((config.get("adjudication") or {}).get("output_subdir") or "adjudication")
    path = _output_dir(project_dir) / subdir / "decisions.json"
    out: Dict[str, Dict[str, Any]] = {f: {} for f in kinds}
    if not path.exists():
        return out
    try:
        decisions = json.loads(path.read_text(encoding="utf-8")).get("decisions") or []
    except (OSError, ValueError):
        return out
    for decision in decisions:
        iid = str(decision.get("instance_id"))
        for field, value in (decision.get("label_decisions") or {}).items():
            kind = kinds.get(field)
            if kind is None:
                continue
            if kind in GEOMETRY_TOOLS:
                answer = _objects(value)
            else:
                chosen = _chosen(value)
                answer = (sorted(chosen) or None) if kind == "multiselect" else (
                    next(iter(chosen)) if len(chosen) == 1 else None)
            if answer is not None:
                out[field][iid] = answer
    return out


def _chosen(value: Any) -> frozenset:
    if value is None or value in ("", [], {}):
        return frozenset()
    if isinstance(value, dict):
        return frozenset(str(k) for k, v in value.items() if v not in (False, None, "", 0, "false"))
    if isinstance(value, (list, tuple, set)):
        return frozenset(str(v) for v in value)
    return frozenset([str(value)])


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------

def merge_classification(answers: Dict[str, str]) -> Optional[str]:
    """The class most annotators chose; None on a tie for first place."""
    if not answers:
        return None
    counts = Counter(answers.values()).most_common()
    if len(counts) > 1 and counts[0][1] == counts[1][1]:
        return None
    return counts[0][0]


def merge_classifications(answers: Dict[str, List[str]]) -> Optional[List[str]]:
    """Every class chosen by more than half of the annotators.

    ``[]`` only when every annotator chose nothing. When people chose classes
    but none reached a majority the result is None, a disagreement like a tied
    vote, so the caller keeps what the sample had instead of erasing it.
    """
    n = len(answers)
    votes = Counter(c for classes in answers.values() for c in set(classes))
    merged = sorted(c for c, k in votes.items() if k * 2 > n)
    if not merged and votes:
        return None
    return merged


def _canonical(objects: List[dict]) -> List[dict]:
    from potato.server_utils.iaa.geometry_agreement import canonical_object
    out = []
    for index, obj in enumerate(objects):
        canon = canonical_object(obj)
        if canon is not None:
            out.append({**canon, "_index": index})
    return out


def merge_geometry(answers: Dict[str, List[dict]],
                   threshold: Optional[float] = None) -> Optional[List[dict]]:
    """Objects found by more than half of the annotators, one per object.

    Each annotator's objects are matched across annotators by overlap (the
    clustering the geometry agreement report uses). A cluster that a majority
    found is kept: boxes as the mean box, polygons and polylines as the member
    that overlaps the others most, labelled with the cluster's most common
    class (ties go to the first annotator's, in name order).

    ``[]`` only when nobody drew anything. When objects were drawn but none was
    found by a majority the result is None: a disagreement, not agreement that
    the image is empty.
    """
    from potato.server_utils.iaa import geometry
    from potato.server_utils.iaa.geometry_agreement import (
        DEFAULT_MATCH_THRESHOLD, _matched_clusters,
    )
    threshold = DEFAULT_MATCH_THRESHOLD if threshold is None else threshold
    n = len(answers)
    if n == 0:
        return []
    canon = {user: _canonical(objs) for user, objs in answers.items()}
    merged = []
    for cluster in _matched_clusters(canon, threshold):
        if len(cluster) * 2 <= n and n > 1:
            continue
        members = [(user, answers[user][c["_index"]]) for user, c in sorted(cluster.items())]
        labels = Counter(obj.get("label") for _u, obj in members).most_common()
        label = labels[0][0]
        first = members[0][1]
        if first.get("type") == "bbox":
            coords = [obj["coordinates"] for _u, obj in members]
            box = {k: sum(c[k] for c in coords) / len(coords)
                   for k in ("x", "y", "width", "height")}
            merged.append({"type": "bbox", "label": label, "coordinates": box})
            continue
        canon_members = [cluster[u] for u, _o in members]
        best = max(range(len(members)), key=lambda i: sum(
            geometry.similarity(canon_members[i], other)
            for j, other in enumerate(canon_members) if j != i))
        chosen = dict(members[best][1])
        chosen["label"] = label
        merged.append(chosen)
    if not merged and any(answers.values()):
        return None
    return merged


def merge_field(kind: str, answers: Dict[str, Any]) -> Any:
    if kind == "radio":
        return merge_classification(answers)
    if kind == "multiselect":
        return merge_classifications(answers)
    return merge_geometry(answers)


# ---------------------------------------------------------------------------
# Agreement
# ---------------------------------------------------------------------------

def _clean(value: Any) -> Any:
    """NaN -> None, recursively: an undefined number is not a number in JSON."""
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def field_agreement(kind: str, by_sample: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Agreement among the annotators of one field, over samples with 2+ of them."""
    shared = {sid: a for sid, a in by_sample.items() if len(a) >= 2}
    report: Dict[str, Any] = {
        "n_samples": len(by_sample),
        "n_samples_with_two_or_more": len(shared),
        "annotators": sorted({u for a in by_sample.values() for u in a}),
    }
    if not shared:
        report["note"] = ("No sample has two or more annotators yet, so "
                          "agreement is undefined.")
        return report
    if kind in GEOMETRY_TOOLS:
        from potato.server_utils.iaa.geometry_agreement import geometry_agreement
        result = geometry_agreement(shared)
        report.update({k: result.get(k) for k in
                       ("detection", "classification", "localization",
                        "match_threshold", "distance", "note") if k in result})
        return _clean(report)

    from potato.server_utils.iaa.alpha import krippendorff_alpha
    from potato.server_utils.iaa.nominal import mean_pairwise_agreement
    if kind == "radio":
        rows = [(u, sid, v) for sid, a in shared.items() for u, v in a.items()]
        alpha = krippendorff_alpha(rows, "nominal")
        level = "nominal"
        items = [dict(a) for a in shared.values()]
    else:
        rows = [(u, sid, frozenset(v)) for sid, a in shared.items() for u, v in a.items()]
        alpha = krippendorff_alpha(rows, "masi")
        level = "masi"
        items = [{u: frozenset(v) for u, v in a.items()} for a in shared.values()]
    report["alpha"] = alpha
    report["alpha_level"] = level
    report["percent_agreement"] = mean_pairwise_agreement(items)
    if isinstance(alpha, float) and math.isnan(alpha):
        distinct = {v for _u, _s, v in rows}
        report["alpha_note"] = (
            "every annotator gave the same answer on every shared sample, so "
            "alpha is undefined (perfect agreement, not a failed computation)"
            if len(distinct) < 2 else "alpha is undefined for these answers")
    return _clean(report)


def collect(project_dir: str) -> Dict[str, Any]:
    """Everything the download needs: merged labels, per-annotator answers, agreement.

    Returns ``{"fields": {field: {"kind", "merged": {sid: answer}, "answers":
    {sid: {user: answer}}, "adjudicated": [sid, ...], "ties": [sid, ...],
    "agreement": {...}}}}``. A merged value of None is a disagreement (listed
    in ``ties``); ``[]`` is agreement that the sample has nothing. An
    adjudicator's decision replaces the merge for its sample.
    """
    manifest = load_manifest(project_dir)
    answers = read_answers(project_dir)
    decided = read_adjudicated(project_dir)
    fields: Dict[str, Any] = {}
    for field, info in manifest["label_schema"].items():
        kind = potato_kind(info["type"])
        by_sample = answers.get(field, {})
        merged: Dict[str, Any] = {}
        ties: List[str] = []
        for sid, per_user in by_sample.items():
            value = merge_field(kind, per_user)
            if value is None:
                ties.append(sid)
            merged[sid] = value
        adjudicated = sorted(decided.get(field, {}))
        merged.update(decided.get(field, {}))
        fields[field] = {
            "kind": kind, "type": info["type"], "merged": merged,
            "answers": by_sample, "adjudicated": adjudicated, "ties": sorted(ties),
            "agreement": field_agreement(kind, by_sample),
        }
    return {"fields": fields, "manifest": manifest}


def agreement_summary(collected: Dict[str, Any]) -> Dict[str, Any]:
    """The part of :func:`collect` stored in ``dataset.info``: no labels."""
    return {field: {**data["agreement"],
                    "n_merged": sum(1 for v in data["merged"].values() if v not in (None, [])),
                    "n_ties": len(data["ties"]),
                    "n_adjudicated": len(data["adjudicated"])}
            for field, data in collected["fields"].items()}


def iter_annotator_answers(collected: Dict[str, Any]) -> Iterable[tuple]:
    """``(field, annotator, sample_id, answer)`` for every saved answer."""
    for field, data in collected["fields"].items():
        for sid, per_user in data["answers"].items():
            for user, answer in per_user.items():
                yield field, user, sid, answer
