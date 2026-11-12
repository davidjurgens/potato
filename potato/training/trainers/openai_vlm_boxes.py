"""Boxes from a vision-language model behind an OpenAI-compatible chat API.

For ``image_annotation`` schemes. Nothing is trained: each held-out or
unlabelled image is sent to ``/chat/completions`` (vLLM, Ollama, LM Studio,
llama.cpp's server, OpenAI) with the scheme's labels, and the model is asked
for a JSON list of ``{label, box: [x0, y0, x1, y1]}``. The boxes come back
as the image widget's objects, are scored against this project's
annotators, and are written back for review like a trained detector's.

Models disagree about coordinates, and most answer in their own convention
whatever the prompt asks for, so ``coordinate_format`` says what the numbers
are: ``fraction`` (0 to 1 of the image), ``per_mille`` (0 to 1000), or
``pixels`` of the image as sent (Qwen2.5-VL's). ``box_order`` says which
corner comes first: ``xyxy`` (x0, y0, x1, y1) or ``yxyx`` (y0, x0, y1, x1).
Gemma and Gemini answer ``yxyx`` per-mille, so under ``auto`` a model whose
name says Gemma or Gemini is read that way. For any other model ``auto``
reads values up to 1 as fractions, values past the sent image's size as
per-mille, and anything else as pixels, in ``xyxy`` order. A reply that is
not JSON, a label the scheme does not have and a box off the image are left
out and counted.

The model gives no score, so boxes have no confidence and are not ordered by
uncertainty. The key, when the server wants one, is named by
``api_key_env``.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _bridge_common as bc

FORMATS = ("auto", "fraction", "per_mille", "pixels")
ORDERS = ("auto", "xyxy", "yxyx")
#: Model names that answer per-mille boxes y first, whatever they are asked.
YXYX_MODELS = ("gemma", "gemini")


def conventions(model: str, fmt: str, order: str) -> Tuple[str, str]:
    """The coordinate format and corner order to read *model*'s boxes in."""
    native = any(name in (model or "").lower() for name in YXYX_MODELS)
    if order == "auto":
        order = "yxyx" if native else "xyxy"
    if fmt == "auto" and native:
        fmt = "per_mille"
    return fmt, order

DEFAULT_PROMPT = (
    "Find every object in this image that is one of these labels: {labels}.\n"
    "Answer with JSON only, in this form:\n"
    '{"objects": [{"label": "<one of the labels>", "box": [x0, y0, x1, y1]}]}\n'
    "where x0, y0 is the top-left corner and x1, y1 the bottom-right corner of "
    "the object's bounding box, as fractions of the image's width and height "
    "between 0 and 1. Use an empty list when there is none.")


def _schema(labels: List[str]) -> Dict[str, Any]:
    return {"type": "object", "properties": {"objects": {"type": "array", "items": {
        "type": "object", "properties": {
            "label": {"type": "string", "enum": labels},
            "box": {"type": "array", "items": {"type": "number"},
                    "minItems": 4, "maxItems": 4}},
        "required": ["label", "box"]}}}, "required": ["objects"]}


def read_boxes(reply: Any) -> List[Dict[str, Any]]:
    """The ``{label, box}`` entries of a parsed reply, which may be the
    object asked for, a bare list, or keyed ``boxes``/``detections``."""
    if isinstance(reply, dict):
        for key in ("objects", "boxes", "detections", "results"):
            if isinstance(reply.get(key), list):
                reply = reply[key]
                break
    out = []
    for entry in reply if isinstance(reply, list) else []:
        if not isinstance(entry, dict):
            continue
        label = entry.get("label", entry.get("name", entry.get("class")))
        coords = entry.get("box", entry.get("bbox", entry.get("box_2d")))
        if isinstance(coords, dict):
            if all(k in coords for k in ("x0", "y0", "x1", "y1")):
                coords = [coords["x0"], coords["y0"], coords["x1"], coords["y1"]]
            elif all(k in coords for k in ("x", "y", "width", "height")):
                coords = [coords["x"], coords["y"], coords["x"] + coords["width"],
                          coords["y"] + coords["height"]]
        if isinstance(coords, list) and len(coords) == 4:
            try:
                out.append({"label": label, "box": [float(v) for v in coords]})
            except (TypeError, ValueError):
                continue
    return out


#: How far past 1 a fraction may run (a box drawn to the edge, rounded up)
#: and still be read as one.
FRACTION_SLACK = 1.05


def reply_format(boxes: List[List[float]], sent_w: int, sent_h: int) -> str:
    """What ``auto`` reads one reply's numbers as, from all its boxes at
    once: a model answers in one convention per reply, and a box that runs a
    hair past the edge (1.02) is still a fraction."""
    values = [abs(v) for box in boxes for v in box]
    if not values or max(values) <= FRACTION_SLACK:
        return "fraction"
    past_image = any(max(b[0], b[2]) > sent_w or max(b[1], b[3]) > sent_h for b in boxes)
    return "per_mille" if past_image and max(values) <= 1000 else "pixels"


def to_pixels(box: List[float], fmt: str, sent_w: int, sent_h: int
              ) -> Tuple[float, float, float, float]:
    """A reply's box in pixels of the image as sent."""
    if fmt == "auto":
        fmt = reply_format([box], sent_w, sent_h)
    x0, y0, x1, y1 = box
    if fmt == "fraction":
        return x0 * sent_w, y0 * sent_h, x1 * sent_w, y1 * sent_h
    if fmt == "per_mille":
        return x0 / 1000 * sent_w, y0 / 1000 * sent_h, x1 / 1000 * sent_w, y1 / 1000 * sent_h
    return x0, y0, x1, y1


class OpenAIVLMBoxesTrainer(Trainer):
    name: ClassVar[str] = "openai-vlm-boxes"
    description: ClassVar[str] = (
        "Asks a vision-language model behind an OpenAI-compatible API (vLLM, "
        "Ollama, OpenAI) for boxes around the scheme's labels: no training "
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
        return {"url": "", "model": "", "api_key_env": "", "prompt": "",
                "coordinate_format": "auto", "box_order": "auto", "json_mode": "schema",
                "max_tokens": 1024,
                "temperature": 0.0, "max_image_side": 1280, "timeout_s": 120.0,
                "label_map": {}, "min_instances": 0}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        return {"type": "object", "additionalProperties": False, "properties": {
            "url": {"type": "string", "default": "",
                    "description": "The API's base URL, ending in /v1, such as "
                                   "http://localhost:8000/v1. Required."},
            "model": {"type": "string", "default": "",
                      "description": "Model name to ask. Empty uses the first one "
                                     "the server lists."},
            "api_key_env": {"type": "string", "default": "",
                            "description": "Name of an environment variable holding "
                                           "the API key, sent as a Bearer token. "
                                           "Empty sends none (a local server)."},
            "prompt": {"type": "string", "default": "",
                       "description": "Instructions sent with each image; {labels} "
                                      "is replaced by the scheme's labels. Empty "
                                      "asks for fractional [x0, y0, x1, y1] boxes."},
            "coordinate_format": {"type": "string", "enum": list(FORMATS),
                                  "default": "auto",
                                  "description": "What the model's numbers are: "
                                                 "fraction (0-1), per_mille "
                                                 "(0-1000), pixels of the image "
                                                 "as sent, or auto."},
            "box_order": {"type": "string", "enum": list(ORDERS), "default": "auto",
                          "description": "xyxy (x0, y0, x1, y1) or yxyx (y0, x0, y1, "
                                         "x1). auto is yxyx for Gemma and Gemini, "
                                         "xyxy otherwise."},
            "json_mode": {"type": "string", "enum": ["schema", "object", "none"],
                          "default": "schema",
                          "description": "schema sends response_format json_schema "
                                         "(vLLM, OpenAI), object sends json_object, "
                                         "none sends neither."},
            "max_tokens": {"type": "integer", "minimum": 64, "default": 1024},
            "temperature": {"type": "number", "minimum": 0, "default": 0.0},
            "max_image_side": {"type": "integer", "minimum": 64, "default": 1280,
                               "description": "Longest side the image is shrunk to "
                                              "before sending."},
            "timeout_s": {"type": "number", "minimum": 1, "default": 120.0},
            "label_map": {"type": "object", "default": {},
                          "description": "The model's label to the scheme's label; "
                                         "null drops it."},
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

    def _headers(self, params) -> Dict[str, str]:
        key = bc.secret(params.get("api_key_env"))
        return {"Authorization": "Bearer %s" % key} if key else {}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = self._params(spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        problems = []
        if not str(params.get("url") or "").startswith(("http://", "https://")):
            problems.append("openai-vlm-boxes needs params.url, the API's http(s) base "
                            "URL ending in /v1.")
        if schema.kind not in self.kinds:
            problems.append("Schema %r is %s; this bridge draws image boxes."
                            % (schema.name, schema.kind))
        if not bc.scheme_labels(params, schema, bundle):
            problems.append("Schema %r has no labels to ask for." % schema.name)
        problems.extend(bc.env_problems(params, ("api_key_env",)))
        return problems

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        import requests
        params = self._params(spec)
        schema = spec.primary_schema
        base = str(params["url"]).rstrip("/")
        report.status("running", "checking %s" % base)
        model = str(params.get("model") or "")
        try:
            response = requests.get(base + "/models", headers=self._headers(params),
                                    timeout=float(params["timeout_s"]))
        except requests.RequestException as exc:
            raise TrainerError("Could not reach %s: %s" % (
                base, bc.scrub(exc, [bc.secret(params.get("api_key_env"))])))
        if response.status_code >= 400:
            raise TrainerError("%s/models answered %d: %s" % (
                base, response.status_code,
                bc.scrub(response.text, [bc.secret(params.get("api_key_env"))])[:200]))
        try:
            listed = [str(m.get("id")) for m in (response.json() or {}).get("data") or []
                      if isinstance(m, dict) and m.get("id")]
        except ValueError:
            listed = []
        if not model:
            if not listed:
                raise TrainerError("%s lists no model; set params.model" % base)
            model = listed[0]
        elif listed and model not in listed:
            report.log("warning", "%s does not list %s (it lists %s); asking anyway"
                       % (base, model, ", ".join(listed[:5])))
        labels = bc.scheme_labels(params, schema, bundle)
        fmt, order = conventions(model, params["coordinate_format"], params["box_order"])
        report.log("info", "%s is up; asking %s for %s, reading its boxes as %s %s"
                   % (base, model, ", ".join(labels), order,
                      fmt if fmt != "auto" else "(fraction, per-mille or pixels by size)"))
        path = bc.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "url": base, "model": model, "labels": labels, "checked_at": time.time()})
        return FitResult(model_version="%s:%s" % (self.name, model), artifact_paths=[path],
                         metrics={"n_train": 0.0},
                         notes=["Predict-only: the model was not trained by this run."])

    def _ask(self, item: PredictItem, card, params, labels: List[str]) -> Tuple[Any, int, int, float]:
        raw, mime, width, height, scale = bc.image_bytes(
            item.media, int(params["max_image_side"]))
        prompt = (params.get("prompt") or DEFAULT_PROMPT).replace("{labels}", ", ".join(labels))
        body: Dict[str, Any] = {
            "model": card["model"], "temperature": float(params["temperature"]),
            "max_tokens": int(params["max_tokens"]),
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": "data:%s;base64,%s" % (mime, bc.b64(raw))}}]}]}
        if params.get("json_mode") == "schema":
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "boxes", "schema": _schema(labels)}}
        elif params.get("json_mode") == "object":
            body["response_format"] = {"type": "json_object"}
        reply = bc.post(card["url"] + "/chat/completions", json_body=body,
                        headers=self._headers(params), timeout=float(params["timeout_s"]),
                        secrets=[bc.secret(params.get("api_key_env"))])
        try:
            content = reply["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = None
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return bc.parse_json_text(content or ""), width, height, scale

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        params = self._params(spec)
        card = bc.read_card(artifact_dir)
        labels = list(card["labels"])
        label_map = params.get("label_map") or {}
        version = "%s:%s" % (self.name, card["model"])
        fmt, order = conventions(card["model"], params["coordinate_format"], params["box_order"])
        items = [i for i in items if i.media and not str(i.media).startswith("http")]
        not_json = off_label = off_image = 0
        for n, item in enumerate(items):
            reply, width, height, scale = self._ask(item, card, params, labels)
            if reply is None:
                not_json += 1
                continue
            sent_w, sent_h = max(1, round(width * scale)), max(1, round(height * scale))
            objects = []
            entries = read_boxes(reply)
            ordered = [[e["box"][1], e["box"][0], e["box"][3], e["box"][2]] if order == "yxyx"
                       else e["box"] for e in entries]
            this_fmt = reply_format(ordered, sent_w, sent_h) if fmt == "auto" else fmt
            for entry in entries:
                label = bc.label_for(entry["label"], labels, label_map)
                if label is None:
                    off_label += 1
                    continue
                box = entry["box"]
                if order == "yxyx":
                    box = [box[1], box[0], box[3], box[2]]
                x0, y0, x1, y1 = to_pixels(box, this_fmt, sent_w, sent_h)
                obj = bc.box(label, x0 / scale, y0 / scale, x1 / scale, y1 / scale,
                             width, height, None, version)
                if obj is None:
                    off_image += 1
                    continue
                objects.append(obj)
            report.progress("predict", n + 1, len(items))
            if objects:
                yield PredictionRecord(instance_id=item.instance_id,
                                       schema_name=card["schema"], payload=objects)
            if report.should_stop():
                break
        left = [("%d repl%s that were not JSON" % (not_json, "y" if not_json == 1 else "ies"),
                 not_json), ("%d box(es) under labels the scheme lacks" % off_label, off_label),
                ("%d box(es) off the image" % off_image, off_image)]
        if any(n for _what, n in left):
            report.log("warning", "Not used: %s" % "; ".join(w for w, n in left if n))
        if items and not_json == len(items):
            raise TrainerError("The model's reply was never JSON. Try json_mode: object, or "
                               "a prompt that asks for JSON more plainly.")
