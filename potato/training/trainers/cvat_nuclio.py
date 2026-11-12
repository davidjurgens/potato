"""Predictions from a CVAT serverless (Nuclio) detector.

For ``image_annotation`` schemes. CVAT's serverless models (YOLO, Detectron2,
Segment Anything and the rest of ``cvat/serverless``) are Nuclio functions
that take ``{"image": <base64>, "threshold": t}`` and answer a list of
shapes in pixels: ``rectangle`` with ``points: [x0, y0, x1, y1]``,
``polygon`` with ``points: [x, y, x, y, ...]``, and ``mask``. Teams that
already deployed one for CVAT can point Potato at the function's URL; nothing
is trained here, and the shapes come back as the image widget's boxes and
polygons with a held-out score against this project's annotators.

Masks are left out and counted (CVAT's mask encoding is its own), as are
shapes under a label the scheme does not have. ``label_map`` maps the
function's label names to the scheme's.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainingSpec)
from potato.training.trainers import _bridge_common as bc


def shapes_of(answer: Any, labels: List[str], label_map: Dict[str, Any], width: int,
              height: int, version: str, polygons: bool = True
              ) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """``(objects, {reason: count left out})`` from a function's answer.
    Without *polygons* (a scheme with no polygon tool) an outline becomes its
    bounding box."""
    out: List[Dict[str, Any]] = []
    left: Dict[str, int] = {}

    def skip(why):
        left[why] = left.get(why, 0) + 1

    if not isinstance(answer, list):
        skip("answers that were not a list of shapes")
        answer = []
    for shape in answer:
        if not isinstance(shape, dict):
            skip("not shapes")
            continue
        kind = shape.get("type", "rectangle")
        if kind == "mask":
            skip("masks")
            continue
        label = bc.label_for(shape.get("label"), labels, label_map)
        if label is None:
            skip("labels the scheme lacks")
            continue
        score = bc.number(shape.get("confidence"))
        points = shape.get("points") or []
        obj = None
        if kind == "rectangle" and len(points) >= 4:
            obj = bc.box(label, points[0], points[1], points[2], points[3], width, height,
                         score, version)
        elif kind == "polygon" and len(points) >= 6:
            ring = list(zip(points[0::2], points[1::2]))
            if polygons:
                obj = bc.polygon(label, ring, width, height, score, version)
            else:
                xs, ys = [x for x, _y in ring], [y for _x, y in ring]
                obj = bc.box(label, min(xs), min(ys), max(xs), max(ys), width, height,
                             score, version)
        else:
            skip("%s shapes" % kind)
            continue
        if obj is None:
            skip("shapes off the image")
        else:
            out.append(obj)
    return out, left


class CVATNuclioTrainer(Trainer):
    name: ClassVar[str] = "cvat-nuclio"
    description: ClassVar[str] = (
        "Uses a CVAT serverless (Nuclio) detector's function URL: no training "
        "here, but held-out scores, write-back and review like a detector.")
    kinds: ClassVar[Tuple[str, ...]] = ("geometry",)
    modalities: ClassVar[Tuple[str, ...]] = ("image",)
    annotation_types: ClassVar[Tuple[str, ...]] = ("image_annotation",)
    install_hint: ClassVar[str] = ""
    licence: ClassVar[str] = "depends on the model"
    commercial_use: ClassVar[Optional[bool]] = None
    predict_only: ClassVar[bool] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        import importlib.util
        missing = [m for m in ("requests", "PIL") if importlib.util.find_spec(m) is None]
        return (False, "Not installed: %s" % ", ".join(missing)) if missing else (True, "")

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"url": "", "threshold": 0.5, "label_map": {}, "timeout_s": 120.0,
                "min_instances": 0}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        return {"type": "object", "additionalProperties": False, "properties": {
            "url": {"type": "string", "default": "",
                    "description": "The Nuclio function's URL, such as "
                                   "http://localhost:32768 (nuctl get functions "
                                   "lists the port). Required."},
            "threshold": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5,
                          "description": "Sent to the function; it drops shapes "
                                         "scoring lower."},
            "label_map": {"type": "object", "default": {},
                          "description": "The function's label to the scheme's "
                                         "label; null drops it."},
            "timeout_s": {"type": "number", "minimum": 1, "default": 120.0},
            "min_instances": {"type": "integer", "minimum": 0, "default": 0},
        }}

    @classmethod
    def server_params(cls, config, schema_names, params) -> Dict[str, Any]:
        for scheme in (config or {}).get("annotation_schemes") or []:
            if schema_names and scheme.get("name") == schema_names[0]:
                return {"_scheme": {k: scheme[k] for k in ("name", "labels", "tools")
                                    if k in scheme}}
        return {}

    def _params(self, spec: TrainingSpec) -> Dict[str, Any]:
        return {**self.default_params(), **(spec.params or {})}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = self._params(spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        problems = []
        if not str(params.get("url") or "").startswith(("http://", "https://")):
            problems.append("cvat-nuclio needs params.url, the function's http(s) address.")
        if schema.kind not in self.kinds:
            problems.append("Schema %r is %s; this bridge draws image boxes and outlines."
                            % (schema.name, schema.kind))
        return problems

    def _post(self, params, raw: bytes) -> Any:
        return bc.post(str(params["url"]).rstrip("/"),
                       json_body={"image": bc.b64(raw), "threshold": float(params["threshold"])},
                       timeout=float(params["timeout_s"]))

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        params = self._params(spec)
        schema = spec.primary_schema
        url = str(params["url"]).rstrip("/")
        report.status("running", "checking %s" % url)
        self._post(params, bc.probe_image())
        labels = bc.scheme_labels(params, schema, bundle)
        report.log("info", "%s answers; Potato does not train it" % url)
        tools = (params.get("_scheme") or {}).get("tools") or ["bbox"]
        path = bc.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind, "url": url,
            "labels": labels, "polygons": "polygon" in tools, "checked_at": time.time()})
        return FitResult(model_version="%s:%s" % (self.name, url), artifact_paths=[path],
                         metrics={"n_train": 0.0},
                         notes=["Predict-only: the function was not trained by this run."])

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        params = self._params(spec)
        card = bc.read_card(artifact_dir)
        version = "%s:%s" % (self.name, card["url"])
        items = [i for i in items if i.media and not str(i.media).startswith("http")]
        left: Dict[str, int] = {}
        for n, item in enumerate(items):
            raw, _mime, width, height, _scale = bc.image_bytes(item.media)
            objects, skipped = shapes_of(self._post(params, raw), card["labels"],
                                         params.get("label_map") or {}, width, height, version,
                                         polygons=card.get("polygons", True))
            for why, count in skipped.items():
                left[why] = left.get(why, 0) + count
            report.progress("predict", n + 1, len(items))
            if objects:
                yield PredictionRecord(instance_id=item.instance_id, schema_name=card["schema"],
                                       payload=objects, confidence=bc.least_confident(objects))
            if report.should_stop():
                break
        if left:
            report.log("warning", "Not used: %s" % "; ".join(
                "%d %s" % (n, why) for why, n in sorted(left.items())))
