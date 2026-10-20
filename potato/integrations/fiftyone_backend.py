"""
Potato as a FiftyOne annotation backend.

Register it once, then annotate any image view with ``backend="potato"``::

    import fiftyone as fo
    fo.annotation_config.backends["potato"] = {
        "config_cls": "potato.integrations.fiftyone_backend.PotatoBackendConfig",
    }
    view.annotate("round1", backend="potato", label_field="ground_truth",
                  label_type="detections", classes=["car", "person"],
                  project_dir="potato-round1", annotations_per_item=2)
    # ... people annotate in Potato ...
    dataset.load_annotations("round1")

``annotate`` writes a Potato project (see ``fiftyone_project``) and returns.
``load_annotations`` reads every annotator's answers back, merges them into one
label per sample (an adjudicator's decision wins where there is one), and
stores the agreement report in ``dataset.info["potato_agreement"][anno_key]``.
With ``annotator_fields=True`` each person's labels are also written to
``<label_field>_<username>``.

This module imports FiftyOne at the top, so only FiftyOne loads it, through
``config_cls``. Potato itself never imports it.
"""

from __future__ import annotations

import logging
import math
import os
import re
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict

import fiftyone.core.labels as fol
import fiftyone.core.media as fom
import fiftyone.utils.annotations as foua

from potato.integrations import fiftyone_project as fp

logger = logging.getLogger(__name__)

_LIST_TYPES = {"classifications", "detections", "polylines", "polygons", "keypoints"}


class PotatoBackendConfig(foua.AnnotationBackendConfig):
    """Settings for a Potato annotation run.

    Args:
        name: the backend name ("potato")
        label_schema: built by FiftyOne from ``annotate()``'s arguments
        media_field ("filepath"): the sample field holding each image's path
        project_dir (None): where to write the Potato project; defaults to
            ``./potato-<anno_key>``
        annotations_per_item (2): how many people label each sample
        media ("copy"): ``"copy"`` copies images into the project;
            ``"reference"`` serves them from their own folder, which makes
            everything under that folder reachable through the study's URL
        annotator_fields (False): also write each annotator's labels to
            ``<label_field>_<username>`` on load
        port (8000): the port ``launch_editor`` starts Potato on
    """

    def __init__(self, name, label_schema, media_field="filepath",
                 project_dir=None, annotations_per_item=2, media="copy",
                 annotator_fields=False, port=8000, **kwargs):
        super().__init__(name, label_schema, media_field=media_field, **kwargs)
        self.project_dir = project_dir
        self.annotations_per_item = int(annotations_per_item)
        self.media = media
        self.annotator_fields = bool(annotator_fields)
        self.port = int(port)


class PotatoBackend(foua.AnnotationBackend):
    """Writes a view out as a Potato project and reads the answers back."""

    @property
    def supported_media_types(self):
        return [fom.IMAGE, fom.VIDEO]

    @property
    def supported_label_types(self):
        return sorted(fp.LABEL_TYPES)

    @property
    def supported_scalar_types(self):
        return []

    @property
    def supported_attr_types(self):
        return sorted(fp.ATTRIBUTE_TYPES)

    @property
    def supports_keyframes(self):
        return False

    @property
    def supports_video_sample_fields(self):
        return False

    @property
    def requires_label_schema(self):
        return True

    def recommend_attr_tool(self, name, value):
        if isinstance(value, bool):
            return {"type": "checkbox"}
        return {"type": "text"}

    def requires_attr_values(self, attr_type):
        return attr_type in ("select", "radio")

    def upload_annotations(self, samples, anno_key, launch_editor=False):
        config = self.config
        project_dir = os.path.abspath(config.project_dir or f"potato-{anno_key}")
        dataset = getattr(samples, "_dataset", samples)
        video = samples.media_type == fom.VIDEO
        if video:
            samples.compute_metadata()
        label_schema = {}
        id_map = {}
        existing = {}
        for field, info in config.label_schema.items():
            label_type = info["type"]
            entry = {"type": label_type,
                     "classes": [c for c in (info.get("classes") or []) if isinstance(c, str)]}
            if samples._is_frame_field(field):
                entry["frame_field"] = True
                rates = [r for r in samples.values("metadata.frame_rate") if r]
                if rates:
                    entry["fps"] = max(set(rates), key=rates.count)
            if info.get("attributes"):
                entry["attributes"] = {name: dict(spec) for name, spec in info["attributes"].items()}
            if label_type in ("keypoint", "keypoints"):
                skeleton = dataset.skeletons.get(field) or dataset.default_skeleton
                if skeleton is not None:
                    names = list(skeleton.labels or []) or [
                        str(i) for i in range(1 + max((max(e) for e in skeleton.edges), default=0))]
                    entry["skeleton"] = {"names": names, "edges": [list(e) for e in skeleton.edges]}
            if label_type == "segmentation":
                entry["mask_targets"] = integer_mask_targets(field, info.get("mask_targets") or {})
                entry["classes"] = list(entry["mask_targets"].values())
            fp.field_kind(entry)  # refuses unsupported types up front
            label_schema[field] = entry
            if info.get("existing_field") and not entry.get("frame_field"):
                ids, values = samples.values(["id", field])
                existing[field] = {sid: _to_answer({**entry, "field": field}, v)
                                   for sid, v in zip(ids, values)}
                id_map[field] = {sid: _label_ids(v) for sid, v in zip(ids, values)}
            elif info.get("existing_field"):
                logger.warning(
                    "%s already has labels. Potato does not show existing video tracks to "
                    "annotators; new tracks are added beside them on load.", field)

        ids, paths = samples.values(["id", config.media_field])
        rows = [{"id": sid, "filepath": path,
                 "existing": {f: existing[f].get(sid) for f in existing}}
                for sid, path in zip(ids, paths)]
        fp.write_project(project_dir, rows, label_schema,
                         task_name=f"{dataset.name}: {anno_key}",
                         annotations_per_item=config.annotations_per_item,
                         media=config.media, anno_key=anno_key,
                         dataset_name=dataset.name,
                         media_type="video" if video else "image")
        logger.info("Wrote a Potato project for %d samples to %s", len(rows), project_dir)
        logger.info("Start it from %s with: potato start %s -p %d",
                    os.path.dirname(project_dir),
                    os.path.join(os.path.basename(project_dir), "config.yaml"),
                    config.port)

        results = PotatoAnnotationResults(samples, config, anno_key, id_map,
                                          project_dir=project_dir, backend=self)
        if launch_editor:
            results.launch_editor()
        return results

    def download_annotations(self, results):
        collected = fp.collect(results.project_dir)
        dataset = results.samples._dataset
        schema = collected["manifest"]["label_schema"]
        annotations = {}
        for field, info in results.config.label_schema.items():
            label_type = info["type"]
            data = collected["fields"][field]
            entry = schema[field]
            if entry.get("kind") == "track":
                annotations[field] = {"detections": _frame_annotations(
                    results.samples, data["merged"])}
                continue
            per_sample = {}
            current = {}
            if field in results.id_map:
                ids, values = results.samples.values(["id", field])
                current = dict(zip(ids, values))
            for sid in current:
                if data["merged"].get(sid) is None:
                    # Nobody answered, or the vote tied. FiftyOne deletes any
                    # listed label a download leaves out, so the sample's own
                    # labels go back unchanged, ids and all. An empty merge is
                    # different: annotators answered and agreed on nothing
                    # (they deleted a wrong pre-annotation), so it is left out
                    # and FiftyOne removes the old labels.
                    kept = _labels_by_id(current[sid])
                    if kept:
                        per_sample[sid] = kept
            for sid, answer in data["merged"].items():
                if answer in (None, []):
                    continue
                labels = _to_labels(entry, answer)
                if labels:
                    per_sample[sid] = {label.id: label for label in labels}
            annotations[field] = {foua._RETURN_TYPES_MAP[label_type]: per_sample}

        summary = fp.agreement_summary(collected)
        info = dict(dataset.info or {})
        runs = dict(info.get("potato_agreement") or {})
        runs[results.key] = summary
        info["potato_agreement"] = runs
        dataset.info = info
        dataset.save()

        if results.config.annotator_fields:
            write_annotator_fields(dataset, schema, collected)
        return annotations


class PotatoAnnotationResults(foua.AnnotationResults):
    """A Potato run waiting to be loaded back."""

    def __init__(self, samples, config, anno_key, id_map, project_dir=None,
                 backend=None):
        super().__init__(samples, config, anno_key, id_map, backend=backend)
        self.project_dir = project_dir

    def launch_editor(self):
        """Start Potato on the project in the background and open it."""
        # Potato refuses a config outside the directory it is started from, so
        # it starts from the project's parent with a relative path.
        project = os.path.abspath(self.project_dir)
        config_path = os.path.join(os.path.basename(project), "config.yaml")
        port = self.config.port
        log = open(os.path.join(project, "potato-server.log"), "a")
        subprocess.Popen([sys.executable, "-m", "potato", "start", config_path,
                          "-p", str(port)], cwd=os.path.dirname(project),
                         stdout=log, stderr=subprocess.STDOUT,
                         start_new_session=True)
        time.sleep(2)
        url = f"http://localhost:{port}/"
        logger.info("Potato is starting at %s (log: %s)", url, log.name)
        webbrowser.open_new_tab(url)

    def agreement(self):
        """The agreement report for this run, read fresh from the project."""
        return fp.agreement_summary(fp.collect(self.project_dir))

    def cleanup(self):
        # The project folder holds people's saved work; deleting it is not
        # something to do as a side effect of deleting a FiftyOne run.
        logger.info("Left the Potato project in place: %s. Delete the folder "
                    "yourself once you no longer need the annotations.", self.project_dir)

    @classmethod
    def _from_dict(cls, d, samples, config, anno_key):
        return cls(samples, config, anno_key, d["id_map"],
                   project_dir=d.get("project_dir"))


# ---------------------------------------------------------------------------
# FiftyOne labels <-> Potato answers
# ---------------------------------------------------------------------------

def _label_list(value):
    if value is None:
        return []
    if isinstance(value, fol.Classifications):
        return list(value.classifications)
    if isinstance(value, fol.Detections):
        return list(value.detections)
    if isinstance(value, fol.Polylines):
        return list(value.polylines)
    if isinstance(value, fol.Keypoints):
        return list(value.keypoints)
    return [value]


def _label_ids(value):
    labels = _label_list(value)
    if not labels:
        return None
    if isinstance(value, (fol.Classifications, fol.Detections, fol.Polylines, fol.Keypoints)):
        return [label.id for label in labels]
    return labels[0].id


def _labels_by_id(value):
    return {label.id: label for label in _label_list(value)}


def _entry(info):
    """A label_schema entry, or a bare label type from older callers."""
    return {"type": info} if isinstance(info, str) else info


def _attributes_of(label, entry):
    """The values of the schema's attributes set on a FiftyOne label."""
    out = {}
    for name in (entry.get("attributes") or {}):
        value = label.get_attribute_value(name, None) if hasattr(label, "get_attribute_value") \
            else getattr(label, name, None)
        if value is not None:
            out[name] = value
    return out


def _with_attributes(obj, label, entry):
    attributes = _attributes_of(label, entry)
    if attributes:
        obj["attributes"] = attributes
    return obj


def _set_attributes(label, obj, entry):
    for name, value in (obj.get("attributes") or {}).items():
        if name in (entry.get("attributes") or {}):
            label[name] = value
    return label


def integer_mask_targets(field: str, targets: Dict[Any, Any]) -> Dict[str, str]:
    """``{value: class}`` without background, or a refusal for RGB targets.

    FiftyOne also allows ``"#rrggbb"`` keys for RGB masks. Potato's masks are
    one class per integer value, so those are refused by name rather than
    failing on ``int("#ff0000")`` halfway through an upload.
    """
    out = {}
    for value, cls in targets.items():
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"{field}: mask target {value!r} is not an integer. Potato reads integer "
                f"mask targets (0 is background) and does not support RGB targets; give "
                f"this field integer targets to annotate it in Potato.") from None
        if number != 0:
            out[str(number)] = str(cls)
    return out


def _rle(bitmap):
    """A 2D 0/1 array as Potato's row-major RLE, starting with a run of 0s."""
    import numpy as np
    flat = np.asarray(bitmap, dtype=bool).ravel()
    counts, current, run = [], False, 0
    for value in flat:
        if value == current:
            run += 1
        else:
            counts.append(run)
            current, run = value, 1
    counts.append(run)
    return {"counts": [int(c) for c in counts], "size": [int(bitmap.shape[0]), int(bitmap.shape[1])]}


def _bitmap(rle):
    import numpy as np
    h, w = rle["size"]
    flat = np.zeros(h * w, dtype=bool)
    pos, value = 0, False
    for count in rle["counts"]:
        if value:
            flat[pos:pos + count] = True
        pos += count
        value = not value
    return flat.reshape(h, w)


def _to_answer(info, value):
    """A sample's existing FiftyOne label(s) as a Potato answer."""
    entry = _entry(info)
    label_type = entry["type"]
    labels = _label_list(value)
    if not labels:
        return None
    kind = fp.field_kind(entry)
    if kind == "radio":
        return labels[0].label
    if kind == "multiselect":
        return sorted({label.label for label in labels})
    if kind == "mask":
        import numpy as np
        mask = labels[0].get_mask() if hasattr(labels[0], "get_mask") else labels[0].mask
        if mask is None:
            return None
        mask = np.asarray(mask)
        if mask.ndim == 3:   # RGB targets are not supported; read the first channel
            mask = mask[..., 0]
        return [{"type": "mask", "label": cls, "color": "", "rle": _rle(mask == int(v))}
                for v, cls in (entry.get("mask_targets") or {}).items() if (mask == int(v)).any()]
    objects = []
    for label in labels:
        if isinstance(label, fol.Detection) and label.bounding_box:
            x, y, w, h = label.bounding_box
            objects.append(_with_attributes(
                {"type": "bbox", "label": label.label, "color": "",
                 "coordinates": {"x": x, "y": y, "width": w, "height": h}}, label, entry))
        elif isinstance(label, fol.Polyline):
            # A FiftyOne polyline can hold several shapes; Potato draws one
            # shape per object, so each becomes its own object.
            for shape in label.points or []:
                if len(shape) < 2:
                    continue
                objects.append(_with_attributes({
                    "type": "polygon" if label.closed else "polyline",
                    "label": label.label, "color": "",
                    "coordinates": [{"x": p[0], "y": p[1]} for p in shape],
                    **({} if label.closed else {"closed": False})}, label, entry))
        elif isinstance(label, fol.Keypoint):
            points = list(label.points or [])
            if kind == "keypoint_set":
                # Missing points are NaN in FiftyOne and visibility 0 in Potato.
                names = entry["skeleton"]["names"]
                coords = []
                for i in range(len(names)):
                    p = points[i] if i < len(points) else (math.nan, math.nan)
                    known = not (math.isnan(p[0]) or math.isnan(p[1]))
                    coords.append({"x": p[0] if known else 0.0, "y": p[1] if known else 0.0,
                                   "v": 2 if known else 0})
                objects.append(_with_attributes(
                    {"type": "keypoint_set", "label": label.label, "color": "",
                     "skeleton": fp.scheme_name(entry.get("field", "")) or "",
                     "coordinates": coords}, label, entry))
            else:
                for p in points:
                    if math.isnan(p[0]) or math.isnan(p[1]):
                        continue
                    objects.append(_with_attributes(
                        {"type": "landmark", "label": label.label, "color": "",
                         "coordinates": {"x": p[0], "y": p[1]}}, label, entry))
    return objects


def _to_labels(info, answer):
    """A Potato answer as a list of FiftyOne labels."""
    entry = _entry(info)
    label_type = entry["type"]
    kind = fp.field_kind(entry)
    if kind == "radio":
        return [fol.Classification(label=str(answer))]
    if kind == "multiselect":
        return [fol.Classification(label=str(c)) for c in answer]
    if kind == "mask":
        return _segmentation(entry, answer)
    labels = []
    for obj in answer:
        coords = obj.get("coordinates")
        if obj.get("type") == "bbox" and isinstance(coords, dict):
            labels.append(_set_attributes(fol.Detection(label=obj.get("label"), bounding_box=[
                coords["x"], coords["y"], coords["width"], coords["height"]]), obj, entry))
        elif obj.get("type") in ("polygon", "polyline") and isinstance(coords, list):
            closed = obj.get("type") == "polygon"
            labels.append(_set_attributes(fol.Polyline(
                label=obj.get("label"), closed=closed, filled=closed,
                points=[[(p["x"], p["y"]) for p in coords]]), obj, entry))
        elif obj.get("type") == "landmark" and isinstance(coords, dict):
            labels.append(_set_attributes(fol.Keypoint(
                label=obj.get("label"), points=[(coords["x"], coords["y"])]), obj, entry))
        elif obj.get("type") == "keypoint_set" and isinstance(coords, list):
            points = [(p["x"], p["y"]) if p.get("v", 2) else (math.nan, math.nan) for p in coords]
            labels.append(_set_attributes(fol.Keypoint(label=obj.get("label"), points=points),
                                          obj, entry))
    if label_type not in _LIST_TYPES:
        labels = labels[:1]
    return labels


def _segmentation(entry, objects):
    """Per-class masks as one Segmentation. Where two classes overlap, the
    one later in mask_targets wins."""
    import numpy as np
    values = {cls: int(v) for v, cls in (entry.get("mask_targets") or {}).items()}
    masks = [obj for obj in objects or [] if obj.get("type") == "mask" and obj.get("rle")]
    if not masks:
        return []
    h, w = masks[0]["rle"]["size"]
    out = np.zeros((h, w), dtype=np.uint8 if max(values.values(), default=0) < 256 else np.uint16)
    for cls, value in sorted(values.items(), key=lambda kv: kv[1]):
        for obj in masks:
            if obj.get("label") == cls and list(obj["rle"]["size"]) == [h, w]:
                out[_bitmap(obj["rle"])] = value
    return [fol.Segmentation(mask=out)]


def _frame_annotations(samples, merged):
    """Merged tracks as ``{sample_id: {frame_id: {label_id: Detection}}}``.

    Every frame from a track's first keyframe to its last gets a box,
    interpolated linearly between keyframes (held, for constant tracks), with
    ``index`` the track's number and ``keyframe`` set on keyframes. Frame
    numbers come from each keyframe's time at the video's own frame rate.
    """
    from potato.export.mot_exporter import _box_between, _normalized_keyframes, _real_frame
    from potato.server_utils.track_attributes import attributes_at
    samples.ensure_frames()
    ids, rates, numbers, frame_ids = samples.values(
        ["id", "metadata.frame_rate", "frames.frame_number", "frames.id"])
    out = {}
    for sid, fps, frame_numbers, fids in zip(ids, rates, numbers, frame_ids):
        tracks = merged.get(sid)
        if not tracks:
            continue
        by_number = dict(zip(frame_numbers, fids))
        fps = fps or 30.0
        per_frame = {}
        for index, track in enumerate(tracks, start=1):
            keyframes = _normalized_keyframes(track, page_fps=fps, fps=fps)
            if not keyframes:
                continue
            keys = {frame for frame, _box in keyframes}
            hold = (track.get("interpolation") or "linear") == "constant"
            for frame in range(keyframes[0][0], keyframes[-1][0] + 1):
                frame_id = by_number.get(frame + 1)   # FiftyOne numbers frames from 1
                if frame_id is None:
                    continue
                box = _box_between(keyframes, frame, hold=hold)
                label = fol.Detection(label=track.get("label"), index=index,
                                      bounding_box=[box["x"], box["y"], box["width"], box["height"]],
                                      keyframe=frame in keys)
                # per_keyframe attributes change along the track.
                for name, value in attributes_at(
                        track, frame, lambda key, kf: _real_frame(key, kf, fps, fps)).items():
                    label[name] = value
                per_frame.setdefault(frame_id, {})[label.id] = label
        out[sid] = per_frame
    return out


def _container(label_type, labels):
    """Labels for one sample as the value of a FiftyOne field of label_type."""
    if not labels:
        return None
    if label_type == "classifications":
        return fol.Classifications(classifications=labels)
    if label_type == "detections":
        return fol.Detections(detections=labels)
    if label_type in ("polylines", "polygons"):
        return fol.Polylines(polylines=labels)
    if label_type == "keypoints":
        return fol.Keypoints(keypoints=labels)
    return labels[0]


def annotator_field(field, user):
    return f"{field}_{re.sub(r'[^A-Za-z0-9_]+', '_', user).strip('_') or 'annotator'}"


def write_annotator_fields(dataset, label_schema, collected):
    """Each annotator's own labels, into ``<label_field>_<username>``.

    Video tracks are left out: they are frame fields, and one per-annotator
    copy of every frame is more than this option is for.
    """
    per_field = {}
    for field, user, sid, answer in fp.iter_annotator_answers(collected):
        entry = label_schema[field]
        if fp.field_kind(entry) == "track":
            continue
        label_type = entry["type"]
        value = _container(label_type, _to_labels(entry, answer))
        if value is not None:
            per_field.setdefault(annotator_field(field, user), {})[sid] = value
    for name, values in per_field.items():
        dataset.set_values(name, values, key_field="id")
    return sorted(per_field)
