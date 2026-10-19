"""
Label Studio project importer.

Reads Label Studio's full JSON export (Export -> JSON: a list of tasks, each
with `data`, `annotations` and `predictions`) and, optionally, the project's
labeling config XML (`--ls-config`). With the XML, the questions are
translated tag by tag. Without it, they are inferred from the results, which
recovers every label anyone used but not options nobody picked.

What maps:

    Choices            radio, or multiselect when choice="multiple"
    Labels             span
    RectangleLabels    image_annotation (bbox)
    PolygonLabels      image_annotation (polygon)
    KeyPointLabels     image_annotation (landmark)
    TextArea           text
    Rating             likert (size = maxRating)
    Number             number

Everything else (Pairwise, Ranker, Taxonomy, BrushLabels, relations, ...) is
reported, counted, and left out, rather than imported as something it is not.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from potato.export.cv_utils import to_client_object

from .base import ProjectImportResult, ProjectItem, humanize, utf16_to_code_points
from .writer import safe_username

#: Label Studio object tags, which show data rather than ask a question.
OBJECT_TAGS = {"Text", "HyperText", "Image", "Audio", "AudioPlus", "Video",
               "Paragraphs", "Table", "TimeSeries", "Markdown"}

#: Image tools by Label Studio result type.
IMAGE_TOOLS = {"rectanglelabels": "bbox", "polygonlabels": "polygon",
               "keypointlabels": "landmark"}
IMAGE_TAGS = {"RectangleLabels": "rectanglelabels",
              "PolygonLabels": "polygonlabels",
              "KeyPointLabels": "keypointlabels"}

#: Result types this importer converts. The rest are counted as skipped.
CONVERTED = {"choices", "labels", "textarea", "rating", "number",
             *IMAGE_TOOLS}


class LabelStudioImporter:
    format_name = "label_studio"
    description = ("Label Studio JSON export (tasks with annotations and "
                   "predictions), optionally with the labeling config XML")
    file_extensions = [".json"]

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if not path.is_file() or path.suffix.lower() != ".json":
            return False
        try:
            with path.open(encoding="utf-8-sig") as fh:
                head = fh.read(4096)
        except OSError:
            return False
        if not head.lstrip().startswith("["):
            return False
        try:
            tasks = json.loads(path.read_text(encoding="utf-8-sig"))
        except ValueError:
            return False
        return (isinstance(tasks, list) and bool(tasks)
                and isinstance(tasks[0], dict) and "data" in tasks[0]
                and any(k in tasks[0] for k in ("annotations", "predictions",
                                                "completions")))

    # ------------------------------------------------------------------ parse
    def parse_path(self, path: Path, options: Optional[dict] = None) -> ProjectImportResult:
        options = options or {}
        try:
            tasks = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except ValueError as exc:
            raise ValueError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(tasks, list) or not tasks:
            raise ValueError(f"{path} holds no Label Studio tasks")

        result = ProjectImportResult(source_format="Label Studio")
        if options.get("ls_config"):
            controls, objects = parse_label_config(
                Path(options["ls_config"]).read_text(encoding="utf-8"), result)
        else:
            controls, objects = infer_controls(tasks, result)
            result.warn("No --ls-config given, so the questions were inferred "
                        "from the answers. Options nobody chose are missing; "
                        "pass the project's labeling config XML to keep them.")

        self._build_schemes(controls, objects, tasks, result)
        self._emails = _emails_by_user_id(tasks)
        for index, task in enumerate(tasks):
            if isinstance(task, dict):
                self._task(task, index, controls, result)
        # Label Studio's overlap setting is not in the export; the most people
        # any task got is the closest the file comes to it.
        most = max((len(item.responses) for item in result.items), default=0)
        result.annotations_per_item = most or None
        return result

    def _build_schemes(self, controls, objects, tasks, result):
        image_scheme: Dict[str, dict] = {}
        for name, ctl in controls.items():
            kind = ctl["kind"]
            if kind in IMAGE_TOOLS:
                target = ctl["to_name"]
                scheme = image_scheme.get(target)
                if scheme is None:
                    scheme = {"annotation_type": "image_annotation", "name": target,
                              "description": ctl.get("description") or "Mark the objects",
                              "source_field": objects.get(target) or target,
                              "tools": [], "labels": []}
                    image_scheme[target] = scheme
                    result.schemes.append(scheme)
                if IMAGE_TOOLS[kind] not in scheme["tools"]:
                    scheme["tools"].append(IMAGE_TOOLS[kind])
                _merge_labels(scheme["labels"], ctl["labels"])
                ctl["scheme"] = target
                continue
            scheme = {"name": name,
                      "description": ctl.get("description") or humanize(name)}
            if kind == "choices":
                scheme["annotation_type"] = "multiselect" if ctl.get("multiple") else "radio"
                scheme["labels"] = [label["name"] for label in ctl["labels"]]
            elif kind == "labels":
                scheme["annotation_type"] = "span"
                scheme["labels"] = [dict(label) for label in ctl["labels"]]
            elif kind == "textarea":
                scheme["annotation_type"] = "text"
                if ctl.get("rows", 1) > 1:
                    scheme["multiline"] = True
            elif kind == "rating":
                scheme.update(annotation_type="likert", size=ctl.get("max", 5),
                              min_label="1", max_label=str(ctl.get("max", 5)))
            elif kind == "number":
                scheme["annotation_type"] = "number"
                for src, dst in (("min", "min_value"), ("max", "max_value")):
                    if src in ctl:
                        scheme[dst] = ctl[src]
            else:
                continue
            ctl["scheme"] = name
            result.schemes.append(scheme)

        # What the annotator reads. One text object is item_properties.text_key;
        # anything more is shown with instance_display.
        text_fields = [f for tag, f in objects.items()
                       if objects.get(f"__kind__{tag}") in ("Text", "HyperText", "Paragraphs", "Markdown")]
        image_fields = [s["source_field"] for s in image_scheme.values()]
        if text_fields:
            result.text_key = text_fields[0]
        elif image_fields:
            result.text_key = image_fields[0]
        else:
            sample = tasks[0].get("data", {}) if isinstance(tasks[0], dict) else {}
            result.text_key = next((k for k, v in sample.items() if isinstance(v, str)), "text")
        if len(text_fields) > 1:
            span_targets = {objects.get(c["to_name"]) for c in controls.values()
                            if c["kind"] == "labels"}
            result.instance_display = {"fields": [
                dict({"key": f, "type": "text", "label": humanize(f)},
                     **({"span_target": True} if f in span_targets else {}))
                for f in text_fields]}

    def _task(self, task, index, controls, result):
        data = task.get("data") or {}
        # A task without an id gets one that cannot collide with a real id: its
        # list index alone would clash with a task whose id is that number.
        instance_id = (str(task["id"]) if task.get("id") is not None
                       else f"ls_task_{index}")
        item = ProjectItem(instance_id=instance_id, fields=dict(data))

        annotations = task.get("annotations") or task.get("completions") or []
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            if annotation.get("was_cancelled"):
                result.skipped["cancelled annotations"] += 1
                continue
            user = self._user(annotation.get("completed_by"), result, self._emails)
            answers = self._answers(annotation.get("result") or [], controls,
                                    data, result, provenance={"source": "import",
                                                              "import_format": "label_studio"})
            if answers:
                if user in item.responses:
                    result.warn("Some tasks have two annotations by the same person; "
                                "the later one was kept.")
                item.responses[user] = answers

        predictions = [p for p in task.get("predictions") or [] if isinstance(p, dict)]
        if predictions:
            if len(predictions) > 1:
                result.skipped["extra predictions on one task (highest score kept)"] += len(predictions) - 1
            best = max(predictions, key=lambda p: (p.get("score") is not None, p.get("score") or 0))
            source = {"model": best.get("model_version"), "score": best.get("score")}
            answers = self._answers(best.get("result") or [], controls, data, result,
                                    provenance={"source": "ai", "ai_model": best.get("model_version"),
                                                "confidence": best.get("score")})
            for scheme_name, value in answers.items():
                item.predictions[scheme_name] = value
                item.prediction_sources[scheme_name] = {k: v for k, v in source.items()
                                                        if v is not None}
        result.items.append(item)

    @staticmethod
    def _user(completed_by, result, emails=None) -> str:
        """One Potato name per Label Studio user.

        An export can identify the same person as a bare id in one task and as
        {"id": 7, "email": ...} in another. Identity is the id; the email is
        the name wherever any task supplies it for that id.
        """
        emails = emails or {}
        if isinstance(completed_by, dict):
            user_id = completed_by.get("id")
            email = completed_by.get("email") or emails.get(str(user_id))
        else:
            user_id = completed_by
            email = emails.get(str(user_id)) if user_id is not None else None
        if email:
            name = safe_username(email)
            origin = f"{email} (id {user_id})" if user_id is not None else email
        elif user_id is not None:
            name = safe_username(f"ls_user_{user_id}")
            origin = f"id {user_id}"
        else:
            name, origin = "ls_user_unknown", "no completed_by"
        result.annotator_ids[name] = origin
        return name

    def _answers(self, results, controls, data, result, provenance) -> Dict[str, Any]:
        answers: Dict[str, Any] = {}
        for res in results:
            if not isinstance(res, dict):
                continue
            kind = res.get("type")
            ctl = controls.get(res.get("from_name"))
            if kind not in CONVERTED or ctl is None or "scheme" not in ctl:
                result.skipped[f"answers of type '{kind}'"] += 1
                continue
            value = res.get("value") or {}
            name = ctl["scheme"]
            if kind == "choices":
                choices = [str(c) for c in value.get("choices") or []]
                if ctl.get("multiple"):
                    answers[name] = choices
                elif choices:
                    answers[name] = choices[0]
            elif kind == "labels":
                span = self._span(value, data, ctl, result)
                if span:
                    answers.setdefault(name, []).append(span)
            elif kind == "textarea":
                texts = value.get("text") or []
                answers[name] = "\n".join(texts) if isinstance(texts, list) else str(texts)
            elif kind == "rating":
                if value.get("rating") is not None:
                    answers[name] = int(value["rating"])
            elif kind == "number":
                if value.get("number") is not None:
                    answers[name] = value["number"]
            else:
                obj = self._image_object(kind, value, res, provenance, result)
                if obj:
                    answers.setdefault(name, []).append(obj)
        return answers

    @staticmethod
    def _span(value, data, ctl, result) -> Optional[dict]:
        labels = value.get("labels") or []
        if not labels or value.get("start") is None or value.get("end") is None:
            return None
        if len(labels) > 1:
            result.skipped["extra labels on one span (first kept)"] += len(labels) - 1
        text = data.get(ctl.get("field") or "", "")
        start, end = int(value["start"]), int(value["end"])
        if isinstance(text, str) and text:
            start, end = utf16_to_code_points(text, start), utf16_to_code_points(text, end)
            quoted = value.get("text")
            if isinstance(quoted, str) and text[start:end] != quoted:
                result.warn(f"A span's text '{quoted}' does not match the item text at "
                            f"its offsets; it was imported at the offsets as given.")
        return {"start": start, "end": end, "label": str(labels[0])}

    @staticmethod
    def _image_object(kind, value, res, provenance, result) -> Optional[dict]:
        labels = value.get(kind) or []
        if not labels:
            return None
        label = str(labels[0])
        prov = {k: v for k, v in provenance.items() if v is not None}
        # Label Studio stores geometry as percentages of the image. Treating the
        # image as 100 x 100 makes to_client_object's normalization exact.
        if kind == "rectanglelabels":
            if value.get("rotation"):
                result.skipped["rotated boxes (imported without rotation)"] += 1
            return to_client_object("bbox", label, img_w=100, img_h=100, provenance=prov,
                                    bbox=[value.get("x", 0), value.get("y", 0),
                                          value.get("width", 0), value.get("height", 0)])
        if kind == "polygonlabels":
            return to_client_object("polygon", label, img_w=100, img_h=100, provenance=prov,
                                    points=[[p[0], p[1]] for p in value.get("points") or []])
        return to_client_object("landmark", label, img_w=100, img_h=100, provenance=prov,
                                points=[[value.get("x", 0), value.get("y", 0)]])


def _emails_by_user_id(tasks) -> Dict[str, str]:
    """Label Studio user id -> email, from any annotation that carries both."""
    emails: Dict[str, str] = {}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for annotation in task.get("annotations") or task.get("completions") or []:
            who = annotation.get("completed_by") if isinstance(annotation, dict) else None
            if isinstance(who, dict) and who.get("id") is not None and who.get("email"):
                emails.setdefault(str(who["id"]), who["email"])
    return emails


# ------------------------------------------------------------- config -------

def _merge_labels(target: List[dict], labels: List[dict]) -> None:
    seen = {label["name"] for label in target}
    for label in labels:
        if label["name"] not in seen:
            target.append(dict(label))
            seen.add(label["name"])


def _labels_of(node) -> List[dict]:
    labels = []
    for child in node:
        if child.tag in ("Label", "Choice") and child.get("value") is not None:
            label = {"name": child.get("value")}
            color = child.get("background")
            if color and color.startswith("#"):
                label["color"] = color
            labels.append(label)
    return labels


def parse_label_config(xml_text: str, result: ProjectImportResult) -> Tuple[dict, dict]:
    """Label Studio labeling config XML -> (controls by name, objects by name).

    `objects` maps each object tag's name to the data column it shows (its
    `value="$column"`), plus `__kind__<name>` for the tag type.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"The labeling config is not valid XML: {exc}") from exc

    objects: Dict[str, str] = {}
    controls: Dict[str, dict] = {}
    pending_header: Optional[str] = None
    for node in root.iter():
        tag = node.tag
        if tag == "Header":
            pending_header = node.get("value") or (node.text or "").strip() or None
            continue
        name = node.get("name")
        if tag in OBJECT_TAGS and name:
            value = node.get("value") or ""
            objects[name] = value[1:] if value.startswith("$") else value
            objects[f"__kind__{name}"] = tag
            continue
        if not name or not node.get("toName"):
            continue
        to_name = node.get("toName").split(",")[0]
        ctl: Dict[str, Any] = {"to_name": to_name}
        if pending_header:
            ctl["description"] = pending_header
            pending_header = None
        if tag == "Choices":
            ctl.update(kind="choices", labels=_labels_of(node),
                       multiple=node.get("choice") == "multiple")
        elif tag == "Labels":
            ctl.update(kind="labels", labels=_labels_of(node))
        elif tag in IMAGE_TAGS:
            ctl.update(kind=IMAGE_TAGS[tag], labels=_labels_of(node))
        elif tag == "TextArea":
            ctl.update(kind="textarea", rows=int(node.get("rows", 1) or 1))
        elif tag == "Rating":
            ctl.update(kind="rating", max=int(node.get("maxRating", 5) or 5))
        elif tag == "Number":
            ctl["kind"] = "number"
            for attr in ("min", "max"):
                if node.get(attr) is not None:
                    ctl[attr] = float(node.get(attr))
                    if ctl[attr].is_integer():
                        ctl[attr] = int(ctl[attr])
        else:
            result.skipped[f"<{tag}> questions"] += 1
            result.warn(f"<{tag} name=\"{name}\"> has no Potato equivalent in this "
                        "importer and was left out, along with its answers.")
            continue
        controls[name] = ctl

    for ctl in controls.values():
        ctl["field"] = objects.get(ctl["to_name"], ctl["to_name"])
    return controls, objects


def infer_controls(tasks: List[dict], result: ProjectImportResult) -> Tuple[dict, dict]:
    """Rebuild the questions from the answers when no XML is available."""
    controls: Dict[str, dict] = {}
    objects: Dict[str, str] = {}
    sample = next((t.get("data") or {} for t in tasks if isinstance(t, dict)), {})
    for task in tasks:
        if not isinstance(task, dict):
            continue
        groups = [a.get("result") or [] for a in (task.get("annotations") or [])
                  if isinstance(a, dict)]
        groups += [p.get("result") or [] for p in (task.get("predictions") or [])
                   if isinstance(p, dict)]
        for res in (r for group in groups for r in group if isinstance(r, dict)):
            kind, name, to_name = res.get("type"), res.get("from_name"), res.get("to_name")
            if kind not in CONVERTED or not name:
                continue
            ctl = controls.setdefault(name, {"kind": kind, "to_name": to_name, "labels": []})
            value = res.get("value") or {}
            names = value.get(kind) if kind in IMAGE_TOOLS or kind in ("labels", "choices") else None
            _merge_labels(ctl["labels"], [{"name": str(n)} for n in names or []])
            if kind == "choices" and len(value.get("choices") or []) > 1:
                ctl["multiple"] = True
            if kind == "rating" and value.get("rating") is not None:
                ctl["max"] = max(ctl.get("max", 5), int(value["rating"]))
            if to_name and to_name not in objects:
                field = to_name if to_name in sample else None
                if field is None:
                    want_image = kind in IMAGE_TOOLS
                    field = next((k for k, v in sample.items() if isinstance(v, str)
                                  and (want_image == v.startswith(("http", "/", "s3://", "gs://", "data:")))),
                                 next((k for k, v in sample.items() if isinstance(v, str)), to_name))
                objects[to_name] = field
                objects[f"__kind__{to_name}"] = "Image" if kind in IMAGE_TOOLS else "Text"
    for ctl in controls.values():
        ctl["field"] = objects.get(ctl["to_name"], ctl["to_name"])
    return controls, objects
