"""Predictions from a Hugging Face Inference Endpoint or the serverless API.

Nothing is trained here: held-out and unlabelled items go to a model already
deployed on Hugging Face (a dedicated Inference Endpoint's URL, or a model id
on the serverless Inference API), and its answers come back as prelabels
with a held-out score against this project's annotators.

The task follows the scheme:

* a radio or multiselect scheme is **text classification**; the top label,
  or for multiselect every label scoring at least ``threshold``;
* a span scheme is **token classification**, with the endpoint grouping
  word pieces into entities (``aggregation_strategy``);
* an image_annotation scheme is **object detection**, boxes scoring at least
  ``threshold``.

The model's label names are mapped to the scheme's through ``label_map``
(a model label mapped to null is dropped), then matched exactly or ignoring
case. The token is read from the environment variable ``token_env`` names,
on the server, so these runs are local only.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _bridge_common as bc

SERVERLESS = "https://router.huggingface.co/hf-inference/models/"
TASKS = {"nominal": "text-classification", "multilabel": "text-classification",
         "span": "token-classification", "geometry": "object-detection"}


def _count(left: Dict[str, int], why: str) -> None:
    left[why] = left.get(why, 0) + 1


def per_input(answer: Any, n: int) -> List[List[Dict[str, Any]]]:
    """Each input's ``[{label, score}]`` from a text-classification answer:
    a list per input, a bare list for a single input, or one top label per
    input."""
    if not isinstance(answer, list):
        return []
    if answer and all(isinstance(a, list) for a in answer):
        out = answer
    elif n == 1:
        out = [answer]
    elif len(answer) == n:
        out = [[a] for a in answer]
    else:
        return []
    return [[e for e in entry if isinstance(e, dict) and "label" in e] for entry in out]


class HFInferenceTrainer(Trainer):
    name: ClassVar[str] = "hf-inference"
    description: ClassVar[str] = (
        "Uses a model deployed on Hugging Face (an Inference Endpoint or the "
        "serverless API) for text classification, entity spans or object "
        "detection: no training here, but held-out scores, write-back and review.")
    kinds: ClassVar[Tuple[str, ...]] = ("nominal", "multilabel", "span", "geometry")
    modalities: ClassVar[Tuple[str, ...]] = ("text", "image")
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
        return {"endpoint_url": "", "model": "", "token_env": "HF_TOKEN",
                "threshold": 0.5, "aggregation_strategy": "simple", "label_map": {},
                "batch_size": 8, "timeout_s": 60.0, "wait_for_model": True,
                "min_instances": 0}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        return {"type": "object", "additionalProperties": False, "properties": {
            "endpoint_url": {"type": "string", "default": "",
                             "description": "A dedicated Inference Endpoint's URL. "
                                            "Give this or model."},
            "model": {"type": "string", "default": "",
                      "description": "A model id on the serverless Inference API, "
                                     "such as dslim/bert-base-NER."},
            "token_env": {"type": "string", "default": "HF_TOKEN",
                          "description": "Name of the environment variable holding "
                                         "the Hugging Face token."},
            "threshold": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5,
                          "description": "Lowest score kept for a multiselect label "
                                         "or a detected box."},
            "aggregation_strategy": {"type": "string",
                                     "enum": ["simple", "first", "average", "max"],
                                     "default": "simple",
                                     "description": "How the endpoint groups word "
                                                    "pieces into entities."},
            "label_map": {"type": "object", "default": {},
                          "description": "The model's label to the scheme's label; "
                                         "null drops it."},
            "batch_size": {"type": "integer", "minimum": 1, "default": 8,
                           "description": "Texts per text-classification request."},
            "timeout_s": {"type": "number", "minimum": 1, "default": 60.0},
            "wait_for_model": {"type": "boolean", "default": True,
                               "description": "Wait while a serverless model loads "
                                              "rather than fail with 503."},
            "min_instances": {"type": "integer", "minimum": 0, "default": 0},
        }}

    @classmethod
    def server_params(cls, config, schema_names, params) -> Dict[str, Any]:
        for scheme in (config or {}).get("annotation_schemes") or []:
            if schema_names and scheme.get("name") == schema_names[0]:
                return {"_scheme": {k: scheme[k] for k in ("name", "labels") if k in scheme}}
        return {}

    def _params(self, spec: TrainingSpec) -> Dict[str, Any]:
        return {**self.default_params(), **(spec.params or {})}

    @staticmethod
    def _url(params) -> str:
        if params.get("endpoint_url"):
            return str(params["endpoint_url"]).rstrip("/")
        return SERVERLESS + str(params.get("model") or "").strip("/")

    def _headers(self, params, content_type: Optional[str] = None) -> Dict[str, str]:
        headers = {}
        token = bc.secret(params.get("token_env"))
        if token:
            headers["Authorization"] = "Bearer %s" % token
        if params.get("wait_for_model", True):
            headers["X-Wait-For-Model"] = "true"
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = self._params(spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        problems = []
        url, model = params.get("endpoint_url"), params.get("model")
        if bool(url) == bool(model):
            problems.append("hf-inference needs endpoint_url (an Inference Endpoint) or "
                            "model (the serverless API), not both.")
        elif url and not str(url).startswith("https://"):
            problems.append("endpoint_url must be an https:// address.")
        if schema.kind not in TASKS:
            problems.append("Schema %r is %s; hf-inference answers choices, spans and "
                            "image boxes." % (schema.name, schema.kind))
        problems.extend(bc.env_problems(params, ("token_env",)))
        return problems

    # ------------------------------------------------------------ requests

    def _call(self, params, json_body=None, data=None, content_type=None) -> Any:
        return bc.post(self._url(params), json_body=json_body, data=data,
                       headers=self._headers(params, content_type),
                       secrets=[bc.secret(params.get("token_env"))],
                       timeout=float(params["timeout_s"]))

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        params = self._params(spec)
        schema = spec.primary_schema
        task = TASKS[schema.kind]
        url = self._url(params)
        report.status("running", "checking %s" % url)
        # One real request: the API has no health route that says the task.
        if task == "object-detection":
            self._call(params, data=bc.probe_image(), content_type="image/jpeg")
        elif task == "token-classification":
            self._call(params, json_body={"inputs": "Potato checks this endpoint.",
                                          "parameters": {"aggregation_strategy":
                                                         params["aggregation_strategy"]}})
        else:
            self._call(params, json_body={"inputs": ["Potato checks this endpoint."]})
        labels = bc.scheme_labels(params, schema, bundle)
        report.log("info", "%s answers %s; Potato does not train it" % (url, task))
        path = bc.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "task": task, "url": url, "labels": labels, "checked_at": time.time()})
        name = params.get("model") or url
        return FitResult(model_version="%s:%s" % (self.name, name), artifact_paths=[path],
                         metrics={"n_train": 0.0},
                         notes=["Predict-only: the model was not trained by this run."])

    def _classify(self, chunk, card, params, left) -> Iterator[PredictionRecord]:
        answer = self._call(params, json_body={"inputs": [i.text for i in chunk],
                                               "parameters": {"top_k": None}})
        labels, label_map = card["labels"], params.get("label_map") or {}
        threshold = float(params["threshold"])
        for item, entry in zip(chunk, per_input(answer, len(chunk))):
            scored = [(e.get("label"), bc.number(e.get("score"))) for e in entry]
            scored = [(name, score) for name, score in scored if score is not None]
            if not scored:
                continue
            if card["kind"] == "nominal":
                # The model's top answer, whatever it is: a class outside the
                # scheme is the model saying something the scheme cannot,
                # not a reason to promote its runner-up.
                name, score = max(scored, key=lambda t: t[1])
                label = bc.label_for(name, labels, label_map)
                if label is None:
                    _count(left, "top answers under a label the scheme lacks")
                    continue
                yield PredictionRecord(instance_id=item.instance_id, schema_name=card["schema"],
                                       payload={"label": label, "confidence": round(score, 4)},
                                       confidence=round(score, 4))
                continue
            kept = []
            for name, score in scored:
                if score < threshold:
                    continue
                label = bc.label_for(name, labels, label_map)
                if label is None:
                    _count(left, "labels the scheme lacks")
                    continue
                kept.append({"label": label, "confidence": round(score, 4)})
            if kept:
                yield PredictionRecord(instance_id=item.instance_id,
                                       schema_name=card["schema"], payload=kept,
                                       confidence=min(k["confidence"] for k in kept))

    def _spans(self, item, card, params, left) -> Optional[PredictionRecord]:
        answer = self._call(params, json_body={"inputs": item.text, "parameters": {
            "aggregation_strategy": params["aggregation_strategy"]}})
        if isinstance(answer, list) and answer and isinstance(answer[0], list):
            answer = answer[0]
        labels, label_map = card["labels"], params.get("label_map") or {}
        spans = []
        for e in answer if isinstance(answer, list) else []:
            if not isinstance(e, dict):
                _count(left, "entities that are not objects")
                continue
            label = bc.label_for(e.get("entity_group", e.get("entity")), labels, label_map,
                                 bio=True)
            try:
                start, end = int(e["start"]), int(e["end"])
            except (KeyError, TypeError, ValueError):
                _count(left, "entities with no character offsets")
                continue
            if label is None:
                _count(left, "entities under a label the scheme lacks")
                continue
            if not 0 <= start < end <= len(item.text):
                _count(left, "entities outside the text")
                continue
            score = bc.number(e.get("score"))
            spans.append({"start": start, "end": end, "label": label,
                          "confidence": round(score, 4) if score is not None else None})
        if not spans:
            return None
        scores = [s["confidence"] for s in spans if s["confidence"] is not None]
        return PredictionRecord(instance_id=item.instance_id, schema_name=card["schema"],
                                payload=spans, confidence=min(scores) if scores else None)

    def _detect(self, item, card, params, version, left) -> Optional[PredictionRecord]:
        raw, mime, width, height, _scale = bc.image_bytes(item.media)
        answer = self._call(params, data=raw, content_type=mime)
        labels, label_map = card["labels"], params.get("label_map") or {}
        objects = []
        for e in answer if isinstance(answer, list) else []:
            score = bc.number(e.get("score")) if isinstance(e, dict) else None
            if score is None:
                _count(left, "boxes with no numeric score")
                continue
            if score < float(params["threshold"]):
                continue
            label = bc.label_for(e.get("label"), labels, label_map)
            b = e.get("box") or {}
            if label is None:
                _count(left, "boxes under a label the scheme lacks")
                continue
            obj = bc.box(label, b.get("xmin"), b.get("ymin"), b.get("xmax"), b.get("ymax"),
                         width, height, score, version) if isinstance(b, dict) else None
            if obj is None:
                _count(left, "boxes with nothing on the image")
                continue
            objects.append(obj)
        if not objects:
            return None
        objects.sort(key=lambda o: -o["confidence"])
        return PredictionRecord(instance_id=item.instance_id, schema_name=card["schema"],
                                payload=objects, confidence=bc.least_confident(objects))

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        params = self._params(spec)
        card = bc.read_card(artifact_dir)
        version = "%s:%s" % (self.name, params.get("model") or card["url"])
        items = list(items)
        if card["task"] == "object-detection":
            items = [i for i in items if i.media and not str(i.media).startswith("http")]
        left: Dict[str, int] = {}
        try:
            if card["task"] == "text-classification":
                size = int(params["batch_size"])
                for start in range(0, len(items), size):
                    for record in self._classify(items[start:start + size], card, params, left):
                        yield record
                    report.progress("predict", min(start + size, len(items)), len(items))
                    if report.should_stop():
                        return
                return
            for n, item in enumerate(items):
                record = (self._spans(item, card, params, left)
                          if card["task"] == "token-classification"
                          else self._detect(item, card, params, version, left))
                if record is not None:
                    yield record
                report.progress("predict", n + 1, len(items))
                if report.should_stop():
                    return
        finally:
            if left:
                report.log("warning", "Not used: %s" % "; ".join(
                    "%d %s" % (n, why) for why, n in sorted(left.items())))
