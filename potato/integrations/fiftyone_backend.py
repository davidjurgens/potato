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
import os
import re
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import fiftyone.core.labels as fol
import fiftyone.core.media as fom
import fiftyone.utils.annotations as foua

from potato.integrations import fiftyone_project as fp

logger = logging.getLogger(__name__)

_LIST_TYPES = {"classifications", "detections", "polylines", "polygons"}


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
        return [fom.IMAGE]

    @property
    def supported_label_types(self):
        return sorted(fp.LABEL_TYPES)

    @property
    def supported_scalar_types(self):
        return []

    @property
    def supported_attr_types(self):
        return []

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
        return {"type": "text"}

    def requires_attr_values(self, attr_type):
        return False

    def upload_annotations(self, samples, anno_key, launch_editor=False):
        config = self.config
        project_dir = os.path.abspath(config.project_dir or f"potato-{anno_key}")
        label_schema = {}
        id_map = {}
        existing = {}
        for field, info in config.label_schema.items():
            label_type = info["type"]
            fp.potato_kind(label_type)  # refuses unsupported types up front
            classes = [c for c in (info.get("classes") or []) if isinstance(c, str)]
            label_schema[field] = {"type": label_type, "classes": classes}
            if info.get("existing_field"):
                ids, values = samples.values(["id", field])
                existing[field] = {sid: _to_answer(label_type, v) for sid, v in zip(ids, values)}
                id_map[field] = {sid: _label_ids(v) for sid, v in zip(ids, values)}

        ids, paths = samples.values(["id", config.media_field])
        rows = [{"id": sid, "filepath": path,
                 "existing": {f: existing[f].get(sid) for f in existing}}
                for sid, path in zip(ids, paths)]
        dataset = getattr(samples, "_dataset", samples)
        fp.write_project(project_dir, rows, label_schema,
                         task_name=f"{dataset.name}: {anno_key}",
                         annotations_per_item=config.annotations_per_item,
                         media=config.media, anno_key=anno_key,
                         dataset_name=dataset.name)
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
        annotations = {}
        for field, info in results.config.label_schema.items():
            label_type = info["type"]
            data = collected["fields"][field]
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
                labels = _to_labels(label_type, answer)
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
            write_annotator_fields(dataset, results.config.label_schema, collected)
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
    return [value]


def _label_ids(value):
    labels = _label_list(value)
    if not labels:
        return None
    if isinstance(value, (fol.Classifications, fol.Detections, fol.Polylines)):
        return [label.id for label in labels]
    return labels[0].id


def _labels_by_id(value):
    return {label.id: label for label in _label_list(value)}


def _to_answer(label_type, value):
    """A sample's existing FiftyOne label(s) as a Potato answer."""
    labels = _label_list(value)
    if not labels:
        return None
    kind = fp.potato_kind(label_type)
    if kind == "radio":
        return labels[0].label
    if kind == "multiselect":
        return sorted({label.label for label in labels})
    objects = []
    for label in labels:
        if isinstance(label, fol.Detection) and label.bounding_box:
            x, y, w, h = label.bounding_box
            objects.append({"type": "bbox", "label": label.label, "color": "",
                            "coordinates": {"x": x, "y": y, "width": w, "height": h}})
        elif isinstance(label, fol.Polyline):
            # A FiftyOne polyline can hold several shapes; Potato draws one
            # shape per object, so each becomes its own object.
            for shape in label.points or []:
                if len(shape) < 2:
                    continue
                objects.append({
                    "type": "polygon" if label.closed else "polyline",
                    "label": label.label, "color": "",
                    "coordinates": [{"x": p[0], "y": p[1]} for p in shape],
                    **({} if label.closed else {"closed": False})})
    return objects


def _to_labels(label_type, answer):
    """A Potato answer as a list of FiftyOne labels."""
    kind = fp.potato_kind(label_type)
    if kind == "radio":
        return [fol.Classification(label=str(answer))]
    if kind == "multiselect":
        return [fol.Classification(label=str(c)) for c in answer]
    labels = []
    for obj in answer:
        coords = obj.get("coordinates")
        if obj.get("type") == "bbox" and isinstance(coords, dict):
            labels.append(fol.Detection(label=obj.get("label"), bounding_box=[
                coords["x"], coords["y"], coords["width"], coords["height"]]))
        elif obj.get("type") in ("polygon", "polyline") and isinstance(coords, list):
            closed = obj.get("type") == "polygon"
            labels.append(fol.Polyline(
                label=obj.get("label"), closed=closed, filled=closed,
                points=[[(p["x"], p["y"]) for p in coords]]))
    if label_type not in _LIST_TYPES:
        labels = labels[:1]
    return labels


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
    return labels[0]


def annotator_field(field, user):
    return f"{field}_{re.sub(r'[^A-Za-z0-9_]+', '_', user).strip('_') or 'annotator'}"


def write_annotator_fields(dataset, label_schema, collected):
    """Each annotator's own labels, into ``<label_field>_<username>``."""
    per_field = {}
    for field, user, sid, answer in fp.iter_annotator_answers(collected):
        label_type = label_schema[field]["type"]
        value = _container(label_type, _to_labels(label_type, answer))
        if value is not None:
            per_field.setdefault(annotator_field(field, user), {})[sid] = value
    for name, values in per_field.items():
        dataset.set_values(name, values, key_field="id")
    return sorted(per_field)
