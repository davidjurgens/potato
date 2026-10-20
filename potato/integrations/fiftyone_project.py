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
    keypoints        list[client obj]    {"type": "keypoint_set", "skeleton", "coordinates": [{x, y, v}, ...]}
                                         with a skeleton; {"type": "landmark", "coordinates": {x, y}} without
    segmentation     list[client obj]    {"type": "mask", "label", "rle": {counts, size: [h, w]}}, one per class
    frames.detections (video)
                     list[track]         video_annotation tracks: {"label", "attributes", "keyframes":
                                         {frame: {"frame", "time", "bboxNorm": {x, y, width, height}}}}

Any object can carry ``"attributes": {name: value}``.

Client objects use coordinates normalised to [0, 1] with the origin at the top
left, the same convention as FiftyOne's ``bounding_box``, polyline and keypoint
points, so no conversion through pixel sizes is needed in either direction.
Masks are in pixels: Potato's run-length encoding, row by row, starting with a
run of 0s.

Each field's Potato kind (``field_kind``) is decided once, when the project is
written, and stored in the manifest with the scheme name it was given.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import urllib.parse
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

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
    # Keypoints become a keypoint_set when the field has a skeleton
    # (field_kind); without one each point is its own landmark.
    "keypoint": "landmark",
    "keypoints": "landmark",
    "segmentation": "mask",
}
GEOMETRY_TOOLS = {"bbox", "polygon", "polyline", "landmark", "keypoint_set", "mask"}
#: Attribute types FiftyOne may ask for, and the Potato attribute type each becomes.
ATTRIBUTE_TYPES = {"select": "select", "radio": "select", "checkbox": "bool", "text": "text"}
VIDEO_KEY = "video_url"
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


def field_kind(info: Dict[str, Any]) -> str:
    """What Potato asks for one field: its manifest ``kind``, else derived.

    ``info`` is a label_schema entry: ``type``, and optionally ``frame_field``
    (a ``frames.*`` field of a video dataset) and ``skeleton``.
    """
    if info.get("kind"):
        return info["kind"]
    label_type = info["type"]
    if info.get("frame_field"):
        if label_type in ("detection", "detections"):
            return "track"
        raise ValueError(
            f"Potato's FiftyOne backend annotates video frame fields of type "
            f"detections only (as tracks), not {label_type!r}. Sample-level "
            f"classification fields on videos work.")
    if label_type in ("keypoint", "keypoints") and info.get("skeleton"):
        return "keypoint_set"
    return potato_kind(label_type)


def scheme_name(field: str) -> str:
    """A field name usable as a Potato scheme name: ``frames.detections``
    becomes ``frames__detections`` (a dot would break the page's selectors)."""
    return field.replace(".", "__")


def potato_attributes(attributes: Optional[Dict[str, dict]]) -> List[dict]:
    """FiftyOne attribute specs as Potato ``attributes`` (image/video schemas)."""
    out = []
    for name, spec in (attributes or {}).items():
        spec = spec or {}
        kind = ATTRIBUTE_TYPES.get(spec.get("type", "text"))
        if kind is None:
            raise ValueError(
                f"Attribute {name!r} has type {spec.get('type')!r}; Potato's FiftyOne "
                f"backend supports {', '.join(sorted(ATTRIBUTE_TYPES))}")
        entry: Dict[str, Any] = {"name": str(name), "type": kind}
        if kind == "select":
            values = [str(v) for v in spec.get("values") or []]
            if not values:
                raise ValueError(f"Attribute {name!r} is a {spec.get('type')} with no values")
            entry["options"] = values
        if spec.get("default") is not None:
            entry["default"] = (bool(spec["default"]) if kind == "bool" else str(spec["default"]))
        out.append(entry)
    return out


def build_scheme(field: str, label_type: str, classes: List[str],
                 info: Optional[Dict[str, Any]] = None) -> dict:
    """One Potato annotation scheme for one FiftyOne label field."""
    if not classes:
        raise ValueError(
            f"Field {field!r} has no classes. Pass classes=[...] to annotate(), "
            f"or annotate a field that already has labels.")
    info = {"type": label_type, **(info or {})}
    kind = field_kind(info)
    name = scheme_name(field)
    description = field.split(".")[-1].replace("_", " ").strip().capitalize() or field
    attributes = potato_attributes(info.get("attributes"))
    if kind in ("radio", "multiselect"):
        return {"annotation_type": kind, "name": name,
                "description": description, "labels": [str(c) for c in classes]}
    if kind == "track":
        scheme = {"annotation_type": "video_annotation", "name": name,
                  "description": description, "source_field": VIDEO_KEY,
                  "mode": "tracking", "labels": [{"name": str(c)} for c in classes]}
        if info.get("fps"):
            scheme["video_fps"] = float(info["fps"])
        if attributes:
            scheme["attributes"] = attributes
        return scheme
    tools = {"mask": ["brush", "eraser"]}.get(kind, [kind])
    scheme = {"annotation_type": "image_annotation", "name": name,
              "description": description, "source_field": IMAGE_KEY,
              "tools": tools, "labels": [{"name": str(c)} for c in classes]}
    if kind == "keypoint_set":
        skeleton = info["skeleton"]
        scheme["skeletons"] = {name: {"names": [str(n) for n in skeleton["names"]],
                                      "edges": [list(e) for e in skeleton.get("edges") or []]}}
    if attributes and kind != "mask":
        scheme["attributes"] = attributes
    return scheme


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
                  anno_key: str = "", dataset_name: str = "",
                  media_type: str = "image") -> Dict[str, Any]:
    """Write a Potato project for a FiftyOne view.

    Args:
        project_dir: created if missing.
        samples: ``[{"id", "filepath", "existing": {field: answer}}]``, answers
            in the shapes in the module docstring. Existing answers are shown
            as pre-annotations for the annotator to correct.
        label_schema: ``{field: {"type": label_type, "classes": [...]}}``,
            optionally with ``attributes``, ``skeleton`` (``{names, edges}``),
            ``mask_targets`` (``{value: class}``), ``frame_field`` and ``fps``.
        media_type: ``"image"`` or ``"video"``.
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

    if media_type not in ("image", "video"):
        raise ValueError(f"media_type must be 'image' or 'video', not {media_type!r}")
    media_key = VIDEO_KEY if media_type == "video" else IMAGE_KEY
    kinds = {field: field_kind(info) for field, info in label_schema.items()}
    for field, kind in kinds.items():
        if (kind == "track") != (media_type == "video" and bool(label_schema[field].get("frame_field"))):
            raise ValueError(f"Field {field!r} ({kind}) does not fit a {media_type} dataset")
        if media_type == "video" and kind not in ("track", "radio", "multiselect"):
            raise ValueError(
                f"Field {field!r}: on videos Potato annotates frame detections (as "
                f"tracks) and sample-level classifications, not {label_schema[field]['type']}")
    schemes = [build_scheme(field, info["type"], list(info.get("classes") or []), info)
               for field, info in label_schema.items()]
    result = ProjectImportResult(source_format="FiftyOne", schemes=schemes,
                                 text_key=media_key)
    if not any(s["annotation_type"] in ("image_annotation", "video_annotation") for s in schemes):
        # A radio or multiselect question does not show the media by itself.
        result.instance_display = {
            "fields": [{"key": media_key, "type": media_type,
                        "label": media_type.capitalize()}]}
    for sample in samples:
        item = ProjectItem(instance_id=str(sample["id"]), fields={
            media_key: _media_reference(str(sample["filepath"]), project, media,
                                        root, str(sample["id"]))})
        for field, answer in (sample.get("existing") or {}).items():
            if answer not in (None, [], "") and kinds.get(field) != "track":
                item.predictions[scheme_name(field)] = answer
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
        "media_type": media_type,
        "label_schema": {f: {"type": i["type"], "classes": list(i.get("classes") or []),
                             "kind": kinds[f], "scheme": scheme_name(f),
                             **{k: i[k] for k in ("attributes", "skeleton", "mask_targets",
                                                  "frame_field", "fps") if i.get(k)}}
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
            if kind == "track":
                from potato.server_utils.iaa.attribute_agreement import track_objects
                return track_objects(value)
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
    kinds = {f: field_kind(i) for f, i in manifest["label_schema"].items()}
    schemes = {f: i.get("scheme", f) for f, i in manifest["label_schema"].items()}
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
                if schemes[field] not in by_schema:
                    continue
                answer = _answer_from_entries(kind, by_schema[schemes[field]])
                if answer is not None:
                    out[field].setdefault(str(iid), {})[user] = answer
    return out


def read_adjudicated(project_dir: str) -> Dict[str, Dict[str, Any]]:
    """``{field: {sample_id: answer}}`` from the adjudication queue's decisions."""
    import yaml
    manifest = load_manifest(project_dir)
    kinds = {f: field_kind(i) for f, i in manifest["label_schema"].items()}
    fields_by_scheme = {i.get("scheme", f): f for f, i in manifest["label_schema"].items()}
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
        for scheme, value in (decision.get("label_decisions") or {}).items():
            field = fields_by_scheme.get(scheme)
            kind = kinds.get(field)
            if kind is None:
                continue
            if kind == "track":
                from potato.server_utils.iaa.attribute_agreement import track_objects
                answer = track_objects(value)
            elif kind in GEOMETRY_TOOLS:
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
        attributes = merge_attributes([obj for _u, obj in members])
        first = members[0][1]
        if first.get("type") == "bbox":
            coords = [obj["coordinates"] for _u, obj in members]
            box = {k: sum(c[k] for c in coords) / len(coords)
                   for k in ("x", "y", "width", "height")}
            merged.append({"type": "bbox", "label": label, "coordinates": box,
                           **({"attributes": attributes} if attributes else {})})
            continue
        canon_members = [cluster[u] for u, _o in members]
        best = max(range(len(members)), key=lambda i: sum(
            geometry.similarity(canon_members[i], other)
            for j, other in enumerate(canon_members) if j != i))
        chosen = dict(members[best][1])
        chosen["label"] = label
        if attributes:
            chosen["attributes"] = attributes
        else:
            chosen.pop("attributes", None)
        merged.append(chosen)
    if not merged and any(answers.values()):
        return None
    return merged


def merge_attributes(objects: List[dict]) -> Dict[str, Any]:
    """Each attribute's most common value among one cluster's objects.

    Ties go to the value of the earliest object (annotators in name order).
    An attribute nobody set is left out.
    """
    out: Dict[str, Any] = {}
    names = []
    for obj in objects:
        for name in (obj.get("attributes") or {}):
            if name not in names:
                names.append(name)
    for name in names:
        values = [(obj.get("attributes") or {}).get(name) for obj in objects]
        values = [v for v in values if v not in (None, "")]
        if not values:
            continue
        counts = Counter(json.dumps(v, sort_keys=True) for v in values)
        top = max(counts.values())
        winner = next(v for v in values if counts[json.dumps(v, sort_keys=True)] == top)
        out[name] = winner
    return out


def _track_clusters(answers: Dict[str, List[dict]], threshold: float):
    from potato.server_utils.iaa.attribute_agreement import track_canonical, track_similarity
    from potato.server_utils.iaa.geometry_agreement import _matched_clusters
    canon = {}
    for user, tracks in answers.items():
        canon[user] = []
        for index, track in enumerate(tracks or []):
            c = track_canonical(track)
            if c is not None:
                canon[user].append({**c, "_index": index})
    return _matched_clusters(canon, threshold, similarity=track_similarity), canon


def merge_tracks(answers: Dict[str, List[dict]],
                 threshold: Optional[float] = None) -> Optional[List[dict]]:
    """Video tracks found by more than half of the annotators.

    Tracks are matched across annotators by ``track_similarity`` (overlap in
    time times box IoU, the measure the agreement report uses for tracks). A
    cluster a majority found keeps its member that agrees most with the
    others, labelled with the cluster's most common class and attributes.
    ``[]`` when nobody drew a track; None when tracks were drawn and none was
    found by a majority.
    """
    from potato.server_utils.iaa.attribute_agreement import track_similarity
    from potato.server_utils.iaa.geometry_agreement import DEFAULT_MATCH_THRESHOLD
    threshold = DEFAULT_MATCH_THRESHOLD if threshold is None else threshold
    n = len(answers)
    if n == 0:
        return []
    clusters, _canon = _track_clusters(answers, threshold)
    merged = []
    for cluster in clusters:
        if len(cluster) * 2 <= n and n > 1:
            continue
        members = [(user, answers[user][c["_index"]], c) for user, c in sorted(cluster.items())]
        best = max(range(len(members)), key=lambda i: sum(
            track_similarity(members[i][2], other[2])
            for j, other in enumerate(members) if j != i))
        chosen = dict(members[best][1])
        chosen["label"] = Counter(t.get("label") for _u, t, _c in members).most_common(1)[0][0]
        attributes = merge_attributes([t for _u, t, _c in members])
        if attributes:
            chosen["attributes"] = attributes
        merged.append(chosen)
    if not merged and any(answers.values()):
        return None
    return merged


def merge_field(kind: str, answers: Dict[str, Any]) -> Any:
    if kind == "radio":
        return merge_classification(answers)
    if kind == "multiselect":
        return merge_classifications(answers)
    if kind == "track":
        return merge_tracks(answers)
    return merge_geometry(answers)


def track_agreement(shared: Dict[str, Dict[str, List[dict]]],
                    threshold: Optional[float] = None) -> Dict[str, Any]:
    """How often annotators drew the same tracks: of every track drawn on a
    sample with two or more annotators, the share matched by another
    annotator's track, and the mean ``track_similarity`` of matched pairs."""
    from potato.server_utils.iaa.attribute_agreement import track_similarity
    from potato.server_utils.iaa.geometry_agreement import DEFAULT_MATCH_THRESHOLD
    threshold = DEFAULT_MATCH_THRESHOLD if threshold is None else threshold
    drawn = matched = 0
    sims: List[float] = []
    for per_user in shared.values():
        clusters, canon = _track_clusters(per_user, threshold)
        drawn += sum(len(v) for v in canon.values())
        for cluster in clusters:
            if len(cluster) >= 2:
                matched += len(cluster)
                members = list(cluster.values())
                sims.extend(track_similarity(a, b) for i, a in enumerate(members)
                            for b in members[i + 1:])
    return {"tracks_drawn": drawn,
            "track_match_rate": (matched / drawn) if drawn else float("nan"),
            "mean_track_similarity": (sum(sims) / len(sims)) if sims else float("nan"),
            "match_threshold": threshold}


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
    if kind == "track":
        report.update(track_agreement(shared))
        return _clean(report)
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
        kind = field_kind(info)
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
