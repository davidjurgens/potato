"""Predictions from an existing Label Studio ML backend.

A Label Studio ML backend is an HTTP service with ``GET /health`` and
``POST /predict``. Teams that already run one for Label Studio can point
Potato at it instead of training here: this trainer fits nothing, sends the
held-out (and, with ``writeback.include_unlabeled``, the unlabelled) items to
``/predict`` in batches, and translates the regions it returns into Potato
prelabels. The run then gets everything a trained model gets: a held-out
score against this project's annotators, write-back, the review queue and
the provenance line.

The labeling config sent with each request is generated from the scheme
(``Choices`` for radio and multiselect, ``Labels`` for spans,
``RectangleLabels`` or ``PolygonLabels`` for image boxes and polygons), or
taken verbatim from ``label_config``. Results are read with the Label Studio
project importer's converter, so offsets and percent coordinates are handled
the same way as an import.

Images are sent as the worker's local path to the file by default, which
works for a backend that opens the path itself. A backend built on the Label
Studio SDK reads the value as a URL (``get_local_path``), so it needs
``media_url_prefix``: the image is then sent as ``<prefix><path>``, with the
path relative to the task directory. On the same machine that is
``/data/local-files/?d=`` with ``LOCAL_FILES_DOCUMENT_ROOT`` set to the task
directory on the backend; elsewhere, the URL of a server for that directory.

A stock backend's only authentication is HTTP Basic (``BASIC_AUTH_USER`` and
``BASIC_AUTH_PASS`` on the backend): name the environment variables holding
them in ``basic_auth_user_env`` and ``basic_auth_pass_env``. ``api_key_env``
sends ``Authorization: Token``, for backends behind a proxy that expects
that.

The backend's own training (its ``/webhook`` ``fit``) stays the backend's
business: Potato does not send it annotation events.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple
from xml.sax.saxutils import quoteattr

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)

CARD = "label_studio_backend.json"
TEXT_OBJECT, IMAGE_OBJECT = "text", "image"


def _label_names(scheme: Dict[str, Any], labels: Iterable[str]) -> List[str]:
    names = []
    for label in scheme.get("labels") or labels or []:
        name = label.get("name") if isinstance(label, dict) else label
        if name not in (None, "") and str(name) not in names:
            names.append(str(name))
    return names


def label_config(scheme: Dict[str, Any], kind: str,
                 labels: Iterable[str] = ()) -> str:
    """A Label Studio labeling config with one question, for one scheme."""
    name = quoteattr(str(scheme.get("name") or "label"))
    children = "".join("<Label value=%s/>" % quoteattr(n)
                       for n in _label_names(scheme, labels))
    if kind == "geometry":
        tools = scheme.get("tools") or ["bbox"]
        tag = "PolygonLabels" if "polygon" in tools and "bbox" not in tools \
            else "RectangleLabels"
        return ('<View><Image name="%s" value="$%s"/>'
                '<%s name=%s toName="%s">%s</%s></View>'
                % (IMAGE_OBJECT, IMAGE_OBJECT, tag, name, IMAGE_OBJECT,
                   children, tag))
    if kind == "span":
        return ('<View><Labels name=%s toName="%s">%s</Labels>'
                '<Text name="%s" value="$%s"/></View>'
                % (name, TEXT_OBJECT, children, TEXT_OBJECT, TEXT_OBJECT))
    choice = "multiple" if kind == "multilabel" else "single"
    choices = children.replace("<Label ", "<Choice ")
    return ('<View><Text name="%s" value="$%s"/>'
            '<Choices name=%s toName="%s" choice="%s">%s</Choices></View>'
            % (TEXT_OBJECT, TEXT_OBJECT, name, TEXT_OBJECT, choice, choices))


def _post_json(url: str, body: Dict[str, Any], headers: Dict[str, str],
               timeout: float, secrets: Iterable[str] = ()) -> Any:
    import requests

    from potato.training.trainers._bridge_common import scrub
    response = requests.post(url, json=body, headers=headers, timeout=timeout)
    if response.status_code >= 400:
        # A backend that echoes the request echoes its Authorization header.
        raise TrainerError("%s answered %d: %s" % (url, response.status_code,
                                                   scrub(response.text, secrets)[:300]))
    return response.json()


def _number(value: Any) -> Optional[float]:
    """A finite score rounded to 4 places, or None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 4) if math.isfinite(number) else None


def _least_confident(payload: Any) -> Optional[float]:
    regions = payload if isinstance(payload, list) else [payload]
    scores = [r.get("confidence") for r in regions if isinstance(r, dict)
              and r.get("confidence") is not None]
    return min(scores) if scores else None


def predictions_of(response: Any) -> List[Dict[str, Any]]:
    """The per-task predictions in a ``/predict`` response.

    The label-studio-ml package has answered ``{"results": [...]}`` and,
    in older releases, a bare list; a task's entry is a prediction dict
    (``result``, ``score``, ``model_version``) or a list of them, of which
    the first is used.
    """
    if isinstance(response, dict):
        response = response.get("results", response.get("predictions", []))
    out = []
    for entry in response if isinstance(response, list) else []:
        if isinstance(entry, list):
            entry = entry[0] if entry else {}
        out.append(entry if isinstance(entry, dict) else {})
    return out


class LabelStudioMLTrainer(Trainer):
    name: ClassVar[str] = "label-studio-ml"
    description: ClassVar[str] = (
        "Uses an existing Label Studio ML backend's /predict: no training "
        "here, but held-out scores, write-back and review like a trained "
        "model.")
    kinds: ClassVar[Tuple[str, ...]] = ("nominal", "multilabel", "span",
                                        "geometry")
    modalities: ClassVar[Tuple[str, ...]] = ("text", "image")
    install_hint: ClassVar[str] = ""
    licence: ClassVar[str] = "Apache-2.0"
    commercial_use: ClassVar[Optional[bool]] = True
    predict_only: ClassVar[bool] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return True, ""

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"url": "", "api_key_env": "", "basic_auth_user_env": "",
                "basic_auth_pass_env": "", "label_config": "",
                "batch_size": 16, "timeout_s": 60.0, "media_url_prefix": "",
                "min_instances": 0}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        return {"type": "object", "additionalProperties": False, "properties": {
            "url": {"type": "string", "default": "",
                    "description": "The backend's base URL, such as "
                                   "http://localhost:9090. Required."},
            "api_key_env": {"type": "string", "default": "",
                            "description": "Name of an environment variable "
                                           "holding a token, sent as "
                                           "'Authorization: Token <value>'. "
                                           "The token itself never goes in "
                                           "the config. A stock "
                                           "label-studio-ml backend uses "
                                           "basic auth instead."},
            "basic_auth_user_env": {"type": "string", "default": "",
                                    "description": "Name of an environment "
                                                   "variable holding the "
                                                   "backend's BASIC_AUTH_USER."},
            "basic_auth_pass_env": {"type": "string", "default": "",
                                    "description": "Name of an environment "
                                                   "variable holding the "
                                                   "backend's BASIC_AUTH_PASS."},
            "label_config": {"type": "string", "default": "",
                             "description": "Labeling config XML to send. "
                                            "Generated from the scheme when "
                                            "empty."},
            "batch_size": {"type": "integer", "minimum": 1, "default": 16},
            "timeout_s": {"type": "number", "minimum": 1, "default": 60.0},
            "media_url_prefix": {"type": "string", "default": "",
                                 "description": "Send images as <prefix> "
                                                "followed by their path "
                                                "relative to the task "
                                                "directory, such as "
                                                "/data/local-files/?d= for "
                                                "a backend on this machine, "
                                                "rather than as a local "
                                                "path."},
            "min_instances": {"type": "integer", "minimum": 0, "default": 0},
        }}

    @classmethod
    def server_params(cls, config, schema_names, params) -> Dict[str, Any]:
        # The scheme as configured: its labels, and for an image scheme its
        # tools, which decide RectangleLabels or PolygonLabels.
        for scheme in config.get("annotation_schemes") or []:
            if schema_names and scheme.get("name") == schema_names[0]:
                return {"_scheme": {k: scheme[k] for k in
                                    ("name", "labels", "tools") if k in scheme}}
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
            problems.append("label-studio-ml needs params.url, the backend's "
                            "http(s) address.")
        if schema.kind not in self.kinds:
            problems.append("Schema %r is %s; a Label Studio backend's results "
                            "are read for choices, spans and image regions."
                            % (schema.name, schema.kind))
        from potato.training.trainers._bridge_common import env_problems
        problems.extend(env_problems(
            params, ("api_key_env", "basic_auth_user_env", "basic_auth_pass_env")))
        if bool(params.get("basic_auth_user_env")) != bool(
                params.get("basic_auth_pass_env")):
            problems.append("basic_auth_user_env and basic_auth_pass_env go "
                            "together.")
        if params.get("api_key_env") and params.get("basic_auth_user_env"):
            problems.append("Use api_key_env or basic auth, not both: there "
                            "is one Authorization header.")
        return problems

    def _headers(self, params: Dict[str, Any]) -> Dict[str, str]:
        user_env, pass_env = (params.get("basic_auth_user_env"),
                              params.get("basic_auth_pass_env"))
        if user_env and pass_env:
            import base64
            pair = "%s:%s" % (os.environ.get(user_env, ""),
                              os.environ.get(pass_env, ""))
            return {"Authorization": "Basic %s"
                    % base64.b64encode(pair.encode()).decode("ascii")}
        env = params.get("api_key_env")
        token = os.environ.get(env, "") if env else ""
        return {"Authorization": "Token %s" % token} if token else {}

    @staticmethod
    def _secrets(params: Dict[str, Any]) -> List[str]:
        """The values of the named variables, to keep out of error text."""
        from potato.training.trainers._bridge_common import secret
        return [secret(params.get(key)) for key in
                ("api_key_env", "basic_auth_user_env", "basic_auth_pass_env")]

    def _scheme(self, spec: TrainingSpec, bundle: BundleRef) -> Dict[str, Any]:
        schema = spec.primary_schema
        scheme = dict((spec.params or {}).get("_scheme") or {})
        scheme.setdefault("name", schema.name)
        if not scheme.get("labels"):
            scheme["labels"] = list(schema.labels) or list(bundle.labels(schema.name))
        return scheme

    # ----------------------------------------------------------------- fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        import requests

        params = self._params(spec)
        schema = spec.primary_schema
        base = str(params["url"]).rstrip("/")
        scheme = self._scheme(spec, bundle)
        config_xml = params.get("label_config") or label_config(
            scheme, schema.kind, bundle.labels(schema.name))

        report.status("running", "checking %s" % base)
        try:
            health = requests.get(base + "/health", headers=self._headers(params),
                                  timeout=float(params["timeout_s"]))
        except requests.RequestException as exc:
            from potato.training.trainers._bridge_common import scrub
            raise TrainerError("Could not reach the Label Studio ML backend at "
                               "%s: %s" % (base, scrub(exc, self._secrets(params))))
        if health.status_code >= 400:
            hint = ""
            if health.status_code in (401, 403, 500) and params.get("api_key_env"):
                # The SDK raises on a non-Basic Authorization header: a 500.
                hint = (". A stock label-studio-ml backend accepts only HTTP "
                        "Basic auth: set basic_auth_user_env and "
                        "basic_auth_pass_env instead of api_key_env")
            elif health.status_code in (401, 403) and params.get("basic_auth_user_env"):
                hint = (". It refused the credentials in %s and %s; check "
                        "them against the backend's BASIC_AUTH_USER and "
                        "BASIC_AUTH_PASS" % (params["basic_auth_user_env"],
                                             params["basic_auth_pass_env"]))
            elif health.status_code == 401:
                hint = (". The backend wants credentials: set "
                        "basic_auth_user_env and basic_auth_pass_env")
            raise TrainerError("%s/health answered %d%s"
                               % (base, health.status_code, hint))
        try:
            info = health.json()
        except ValueError:
            info = {}
        version = str((info or {}).get("model_version")
                      or (info or {}).get("model_class") or "")
        report.log("info", "Backend %s is up%s; Potato does not train it"
                   % (base, " (%s)" % version if version else ""))

        os.makedirs(spec.workdir, exist_ok=True)
        with open(os.path.join(spec.workdir, CARD), "w") as fh:
            json.dump({"trainer": self.name, "schema": schema.name,
                       "kind": schema.kind, "url": base,
                       "label_config": config_xml,
                       "labels": _label_names(scheme, bundle.labels(schema.name)),
                       "backend_model_version": version,
                       "checked_at": time.time()}, fh, indent=2)
        return FitResult(
            model_version=version or "%s-%s" % (self.name, spec.run_id),
            artifact_paths=[os.path.join(spec.workdir, CARD)],
            metrics={"n_train": 0.0},
            notes=["Predict-only: the backend was not trained by this run."])

    # ------------------------------------------------------------- predict

    def _task(self, n: int, item: PredictItem, kind: str,
              params: Dict[str, Any]) -> Dict[str, Any]:
        if kind == "geometry":
            media = item.media or ""
            prefix = str(params.get("media_url_prefix") or "")
            if prefix:
                # The file's own path, not the bundle copy's name: two
                # images called img1.png in different folders stay apart.
                path = str((item.data or {}).get("media_source")
                           or os.path.basename(media)).lstrip("/")
                if not prefix.endswith(("=", "/")):
                    prefix += "/"
                media = prefix + path
            return {"id": n, "data": {IMAGE_OBJECT: media}}
        return {"id": n, "data": {TEXT_OBJECT: item.text}}

    @staticmethod
    def _controls(card: Dict[str, Any], sink) -> Dict[str, Any]:
        from potato.importers.projects.label_studio import parse_label_config

        controls, _ = parse_label_config(card["label_config"], sink)
        # The importer keys answers by a control's scheme; ours has one.
        for ctl in controls.values():
            ctl["scheme"] = card["schema"]
        return controls

    @staticmethod
    def _usable(res: Any, controls: Dict[str, Any], labels: List[str],
                sink) -> Optional[Dict[str, Any]]:
        """*res* if it answers the scheme, with labels outside the scheme
        removed; None, counted in ``sink.skipped``, if it does not."""
        from potato.importers.projects.label_studio import IMAGE_TOOLS

        if not isinstance(res, dict):
            sink.skipped["results that are not objects"] += 1
            return None
        ctl = controls.get(res.get("from_name"))
        if ctl is None:
            sink.skipped["results for from_name %r, which the label config "
                         "does not have" % res.get("from_name")] += 1
            return None
        kind = res.get("type")
        wanted = set(IMAGE_TOOLS) if ctl.get("kind") in IMAGE_TOOLS else {ctl.get("kind")}
        if kind not in wanted:
            sink.skipped["results of type %r" % kind] += 1
            return None
        value = res.get("value") or {}
        names = value.get(kind)
        if labels and isinstance(names, list):
            kept = [str(n) for n in names if str(n) in labels]
            if len(kept) < len(names):
                sink.skipped["labels outside the scheme"] += len(names) - len(kept)
            if not kept:
                return None
            res = dict(res, value=dict(value, **{kind: kept}))
        return res

    def _payload(self, results: List[Any], card: Dict[str, Any],
                 controls: Dict[str, Any], text: str,
                 score: Optional[float], sink) -> Any:
        from potato.importers.projects.label_studio import LabelStudioImporter

        usable = [r for r in (self._usable(r, controls, card.get("labels") or [],
                                           sink) for r in results) if r]
        if not usable:
            return None
        importer, schema = LabelStudioImporter(), card["schema"]

        def answer(res):
            return importer._answers([res], controls, {TEXT_OBJECT: text},
                                     sink, {}).get(schema)

        def region_score(res):
            # A region's own score (YOLO-style backends give one per box)
            # before the prediction's.
            own = _number(res.get("score"))
            return own if own is not None else score

        kind = card["kind"]
        if kind == "nominal":
            if len(usable) > 1:
                sink.skipped["extra single-choice results (highest score "
                             "kept)"] += len(usable) - 1
            best = max(usable, key=lambda r: (region_score(r) is not None,
                                              region_score(r) or 0.0))
            label = answer(best)
            if label is None:
                return None
            payload = {"label": label}
            if region_score(best) is not None:
                payload["confidence"] = region_score(best)
            return payload
        if kind == "multilabel":
            out, seen = [], set()
            for res in usable:
                for label in answer(res) or []:
                    if label not in seen:
                        seen.add(label)
                        out.append({"label": label,
                                    "confidence": region_score(res)})
            return out or None
        regions = []
        for res in usable:
            for region in answer(res) or []:
                region["source"] = "model"
                if region_score(res) is not None:
                    region.setdefault("confidence", region_score(res))
                regions.append(region)
        return regions or None

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        from potato.importers.projects.base import ProjectImportResult

        with open(os.path.join(artifact_dir, CARD)) as fh:
            card = json.load(fh)
        sink = ProjectImportResult(source_format="label_studio")
        controls = self._controls(card, sink)
        n_out = 0
        params = self._params(spec)
        headers = self._headers(params)
        size = int(params["batch_size"])
        items = list(items)
        if card["kind"] == "geometry":
            # An item whose image is missing (or outside the project, which
            # the bundle leaves out) has nothing to send; sent, it went as an
            # empty image path, and a backend fails the whole batch on it.
            imageless = [i for i in items if not i.media]
            if imageless:
                items = [i for i in items if i.media]
                report.log("warning", "%d item(s) have no image file in the run's data, "
                                      "so they were not sent and have no prediction "
                                      "(first: %s)" % (len(imageless),
                                                      imageless[0].instance_id))
        if card["kind"] == "geometry" and params.get("media_url_prefix"):
            # A backend serving the task directory cannot find these, and
            # one missing file fails its whole batch with a 500: leave them
            # out (they score as unpredicted) rather than lose the batch.
            outside = [i for i in items if os.path.isabs(
                str((i.data or {}).get("media_source") or ""))]
            if outside:
                items = [i for i in items if i not in outside]
                report.log("warning", "%d image(s) are outside the task "
                                      "directory, which media_url_prefix "
                                      "paths are relative to, so they were "
                                      "not sent and have no prediction "
                                      "(first: %s). Move them under the task "
                                      "directory." % (len(outside),
                                                      outside[0].instance_id))
        for start in range(0, len(items), size):
            chunk = items[start:start + size]
            tasks = [self._task(start + n, item, card["kind"], params)
                     for n, item in enumerate(chunk)]
            response = _post_json(card["url"] + "/predict", {
                "tasks": tasks, "label_config": card["label_config"],
                "project": "potato", "params": {"context": None}},
                headers, float(params["timeout_s"]), self._secrets(params))
            results = predictions_of(response)
            if len(results) != len(chunk):
                report.log("warning", "The backend returned %d predictions for "
                                      "%d tasks; the batch was matched by "
                                      "position as far as it goes"
                           % (len(results), len(chunk)))
            for item, prediction in zip(chunk, results):
                score = _number(prediction.get("score"))
                result = prediction.get("result")
                payload = self._payload(result if isinstance(result, list)
                                        else [], card, controls, item.text,
                                        score, sink)
                if payload is None:
                    continue
                n_out += 1
                yield PredictionRecord(
                    instance_id=item.instance_id, schema_name=card["schema"],
                    payload=payload, confidence=score if score is not None
                    else _least_confident(payload))
            report.progress("predict", start + len(chunk), len(items))
            if report.should_stop():
                break
        skipped = "; ".join("%d %s" % (n, what) for what, n in
                            sorted(sink.skipped.items()))
        for message in sink.warnings[:5]:
            report.log("warning", message)
        if skipped:
            report.log("warning", "Not used from the backend: %s" % skipped)
        if items and not n_out and not report.should_stop():
            raise TrainerError(
                "The backend returned no usable prediction for any of %d "
                "items%s. Check that its labeling config names the control "
                "%r with this scheme's labels."
                % (len(items), " (%s)" % skipped if skipped else "",
                   card["schema"]))
