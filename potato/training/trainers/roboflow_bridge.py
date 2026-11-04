"""Predictions from a Roboflow detection or segmentation model.

For ``image_annotation`` schemes. Nothing is trained here: each held-out or
unlabelled image is posted to Roboflow's hosted inference API
(``https://detect.roboflow.com``, or ``https://outline.roboflow.com`` for
instance segmentation) or to a self-hosted Roboflow Inference server
(``http://localhost:9001``), as ``<url>/<model_id>``. The predictions,
centre-and-size boxes in pixels with optional outline points, come back as
the image widget's boxes and polygons.

The API key is read from the environment variable ``api_key_env`` names, on
the server, so these runs are local only. It travels in the request's query
string, as Roboflow's API requires; Potato does not write that URL to the
run log or an error message, and scrubs the key from an error body that
echoes the request. The health check in ``fit`` is one real request with an 8 x 8 white
image, which counts against the account's usage.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple
from urllib.parse import urlencode

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainingSpec)
from potato.training.trainers import _bridge_common as bc


def objects_of(answer: Any, labels: List[str], label_map: Dict[str, Any], width: int,
               height: int, shapes: str, version: str) -> Tuple[List[Dict[str, Any]], int]:
    """``(objects, left out)`` from a Roboflow response's ``predictions``."""
    out, dropped = [], 0
    predictions = answer.get("predictions") if isinstance(answer, dict) else None
    for p in predictions if isinstance(predictions, list) else []:
        if not isinstance(p, dict):
            dropped += 1
            continue
        label = bc.label_for(p.get("class"), labels, label_map)
        if label is None:
            dropped += 1
            continue
        score = bc.number(p.get("confidence"))
        points = p.get("points")
        obj = None
        if shapes != "box" and isinstance(points, list) and len(points) >= 3:
            obj = bc.polygon(label, [(q.get("x"), q.get("y")) for q in points
                                     if isinstance(q, dict)], width, height, score, version)
        if obj is None and shapes != "polygon":
            try:
                x, y = float(p["x"]), float(p["y"])
                w, h = float(p["width"]), float(p["height"])
            except (KeyError, TypeError, ValueError):
                dropped += 1
                continue
            obj = bc.box(label, x - w / 2, y - h / 2, x + w / 2, y + h / 2, width, height,
                         score, version)
        if obj is None:
            dropped += 1
        else:
            out.append(obj)
    return out, dropped


class RoboflowTrainer(Trainer):
    name: ClassVar[str] = "roboflow"
    description: ClassVar[str] = (
        "Uses a Roboflow detection or segmentation model, hosted or on a "
        "self-hosted Inference server: no training here, but held-out scores, "
        "write-back and review like a detector.")
    kinds: ClassVar[Tuple[str, ...]] = ("geometry",)
    modalities: ClassVar[Tuple[str, ...]] = ("image",)
    annotation_types: ClassVar[Tuple[str, ...]] = ("image_annotation",)
    install_hint: ClassVar[str] = ""
    licence: ClassVar[str] = "depends on the model"
    commercial_use: ClassVar[Optional[bool]] = None
    predict_only: ClassVar[bool] = True
    local_only: ClassVar[bool] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        import importlib.util
        missing = [m for m in ("requests", "PIL") if importlib.util.find_spec(m) is None]
        return (False, "Not installed: %s" % ", ".join(missing)) if missing else (True, "")

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_id": "", "url": "https://detect.roboflow.com",
                "api_key_env": "ROBOFLOW_API_KEY", "confidence": 0.4, "overlap": 0.3,
                "shapes": "auto", "label_map": {}, "timeout_s": 60.0, "min_instances": 0}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        return {"type": "object", "additionalProperties": False, "properties": {
            "model_id": {"type": "string", "default": "",
                         "description": "The model as project/version, such as "
                                        "hard-hats/3. Required."},
            "url": {"type": "string", "default": "https://detect.roboflow.com",
                    "description": "https://detect.roboflow.com for detection, "
                                   "https://outline.roboflow.com for segmentation, or "
                                   "a self-hosted Inference server."},
            "api_key_env": {"type": "string", "default": "ROBOFLOW_API_KEY",
                            "description": "Name of the environment variable holding "
                                           "the Roboflow API key."},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.4,
                           "description": "Lowest confidence the API returns."},
            "overlap": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.3,
                        "description": "Overlap at which the API merges boxes."},
            "shapes": {"type": "string", "enum": ["auto", "box", "polygon"],
                       "default": "auto",
                       "description": "auto keeps an outline when the model gives one "
                                      "and a box otherwise; box and polygon keep one."},
            "label_map": {"type": "object", "default": {},
                          "description": "The model's class to the scheme's label; "
                                         "null drops it."},
            "timeout_s": {"type": "number", "minimum": 1, "default": 60.0},
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
        if "/" not in str(params.get("model_id") or "").strip("/"):
            problems.append("roboflow needs params.model_id, as project/version.")
        if not str(params.get("url") or "").startswith(("http://", "https://")):
            problems.append("roboflow's url must be an http(s) address.")
        if schema.kind not in self.kinds:
            problems.append("Schema %r is %s; this bridge draws image boxes and outlines."
                            % (schema.name, schema.kind))
        problems.extend(bc.env_problems(params, ("api_key_env",), required=("api_key_env",)))
        return problems

    def _endpoint(self, params) -> str:
        """The request URL. It carries the key: never log it."""
        query = urlencode({"api_key": bc.secret(params.get("api_key_env")),
                           "confidence": round(float(params["confidence"]) * 100),
                           "overlap": round(float(params["overlap"]) * 100)})
        return "%s/%s?%s" % (str(params["url"]).rstrip("/"),
                             str(params["model_id"]).strip("/"), query)

    def _post(self, params, raw: bytes) -> Any:
        return bc.post(self._endpoint(params), data=bc.b64(raw),
                       headers={"Content-Type": "application/x-www-form-urlencoded"},
                       secrets=[bc.secret(params.get("api_key_env"))],
                       timeout=float(params["timeout_s"]))

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        params = self._params(spec)
        schema = spec.primary_schema
        where = "%s/%s" % (str(params["url"]).rstrip("/"), params["model_id"])
        report.status("running", "checking %s" % where)
        self._post(params, bc.probe_image())
        scheme = params.get("_scheme") or {}
        shapes = params["shapes"]
        if shapes == "auto":
            # What the scheme's canvas can draw: an outline on a box-only
            # scheme would be a shape the annotator has no tool to edit.
            tools = scheme.get("tools") or ["bbox"]
            shapes = "box" if "polygon" not in tools else (
                "polygon" if "bbox" not in tools else "auto")
        labels = bc.scheme_labels(params, schema, bundle)
        report.log("info", "%s answers; Potato does not train it" % where)
        path = bc.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "model_id": params["model_id"], "url": str(params["url"]).rstrip("/"),
            "labels": labels, "shapes": shapes, "checked_at": time.time()})
        return FitResult(model_version="%s:%s" % (self.name, params["model_id"]),
                         artifact_paths=[path], metrics={"n_train": 0.0},
                         notes=["Predict-only: the model was not trained by this run."])

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        params = self._params(spec)
        card = bc.read_card(artifact_dir)
        version = "%s:%s" % (self.name, card["model_id"])
        items = [i for i in items if i.media and not str(i.media).startswith("http")]
        dropped = 0
        for n, item in enumerate(items):
            raw, _mime, width, height, _scale = bc.image_bytes(item.media)
            answer = self._post(params, raw)
            # The API reports the size it measured; boxes are in that space.
            image = answer.get("image") if isinstance(answer, dict) else None
            if isinstance(image, dict) and image.get("width") and image.get("height"):
                width, height = int(image["width"]), int(image["height"])
            objects, left = objects_of(answer, card["labels"], params.get("label_map") or {},
                                       width, height, card["shapes"], version)
            dropped += left
            report.progress("predict", n + 1, len(items))
            if objects:
                yield PredictionRecord(instance_id=item.instance_id, schema_name=card["schema"],
                                       payload=objects, confidence=bc.least_confident(objects))
            if report.should_stop():
                break
        if dropped:
            report.log("warning", "Not used: %d prediction(s) with a class the scheme lacks "
                                  "or no shape on the image" % dropped)
