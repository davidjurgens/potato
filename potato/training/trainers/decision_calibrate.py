"""Calibrate a decision model (Jev, OpenJev, laya-serve, Laya) to this study.

Nothing is trained. The run asks one of the project's decision models (a
``labeling_engine`` source with ``kind: decision``, or a ``laya`` or
``systemone`` model in ``solo_mode.labeling_models``) the scheme's question
for each labelled item, fits a calibration on the train split (see
``potato.ai.decision_calibration``), and scores the calibrated answers on
val and test. The result is ``calibration.json``; name it as ``calibration``
in the engine source's ``options`` or on the solo-mode model, and every
answer that model gives in this project is calibrated.

It runs on the local backend only: it calls the model service the server
uses, with the server's credentials, which are passed to the run's process
in its environment and never written to the run's files. Every item it
scores is one request to that service, so ``max_items`` caps a run against
a hosted model's bill.
"""

from __future__ import annotations

import json
import os
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _decision_common as dc

RAW_FILE = "raw_answers.jsonl"
CALIBRATION_FILE = "calibration.json"


def _make_endpoint(params: Dict[str, Any]):
    """The decision endpoint the run calls, uncalibrated."""
    from potato.ai.ai_endpoint import AIEndpointFactory

    endpoint = params.get("_endpoint")
    if not endpoint:
        raise TrainerError(
            "No decision model to calibrate. Configure one as a "
            "labeling_engine source with kind: decision, or in "
            "solo_mode.labeling_models.")
    ai_config = {k: v for k, v in (endpoint.get("ai_config") or {}).items()
                 if k != "calibration"}
    key = os.environ.get(dc.API_KEY_ENV)
    if key:
        ai_config["api_key"] = key
    return AIEndpointFactory.create_endpoint({"ai_support": {
        "enabled": True, "endpoint_type": endpoint["endpoint_type"],
        "ai_config": ai_config}})


class DecisionCalibrateTrainer(Trainer):
    name: ClassVar[str] = "decision-calibrate"
    description: ClassVar[str] = (
        "Calibrates the project's decision model (Jev, OpenJev, laya-serve, "
        "Laya) to the annotators' labels. Trains nothing; writes a "
        "calibration file the endpoint applies.")
    kinds: ClassVar[Tuple[str, ...]] = ("nominal", "ordinal", "continuous")
    annotation_types: ClassVar[Tuple[str, ...]] = ("radio", "select", "likert",
                                                   "slider")
    modalities: ClassVar[Tuple[str, ...]] = ("text",)
    install_hint: ClassVar[str] = ""
    licence: ClassVar[str] = "BSD-3-Clause"
    commercial_use: ClassVar[Optional[bool]] = True
    local_only: ClassVar[bool] = True

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"source": "auto", "method": "temperature", "l2": 0.01,
                "instructions": None, "batch_size": 16, "max_items": 2000,
                "min_instances": 20}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        from potato.ai.decision_calibration import METHODS
        return {"type": "object", "additionalProperties": False, "properties": {
            "source": {
                "type": "string", "default": "auto",
                "description": "Which decision model: the id of a "
                               "labeling_engine source with kind: decision, "
                               "solo_mode for the first decision model in "
                               "solo_mode.labeling_models, or auto for the "
                               "first one found."},
            "method": {"type": "string", "enum": list(METHODS),
                       "default": "temperature",
                       "description": "temperature changes confidence only; "
                                      "temperature+bias can also shift which "
                                      "option is picked."},
            "l2": {"type": "number", "minimum": 0, "default": 0.01,
                   "description": "Penalty on the option offsets."},
            "instructions": {"type": ["string", "null"], "default": None,
                             "description": "Put before the scheme's "
                                            "description in the question; "
                                            "null uses the engine source's "
                                            "prompt, as the engine does."},
            "batch_size": {"type": "integer", "minimum": 1, "default": 16},
            "max_items": {"type": "integer", "minimum": 1, "default": 2000,
                          "description": "Most items asked in one run, train "
                                         "first: each is one request."},
            "min_instances": {"type": "integer", "minimum": 2, "default": 20},
        }}

    @classmethod
    def server_params(cls, config, schema_names, params) -> Dict[str, Any]:
        out: Dict[str, Any] = {"_schemes": dc.schemes_for(config, schema_names)}
        entry = dc.pick_endpoint(config, params.get("source"))
        if entry:
            out["_endpoint"] = dc.spec_endpoint(entry)
        return out

    @classmethod
    def config_problem(cls, config) -> Optional[str]:
        if not dc.decision_endpoints(config):
            return "no decision model is configured"
        return None

    @classmethod
    def run_environment(cls, config, params) -> Dict[str, str]:
        entry = dc.pick_endpoint(config, params.get("source"))
        return {dc.API_KEY_ENV: entry["api_key"]} if entry and entry["api_key"] else {}

    def _params(self, spec: TrainingSpec) -> Dict[str, Any]:
        return {**self.default_params(), **(spec.params or {})}

    def _question(self, params, schema):
        scheme = (params.get("_schemes") or {}).get(schema.name)
        if not scheme:
            raise TrainerError("The run has no config for scheme %r"
                               % schema.name)
        endpoint = params.get("_endpoint") or {}
        instructions = params.get("instructions")
        if instructions is None:
            # The engine asks with its source's prompt, or the scheme's
            # description when the source has none.
            instructions = endpoint.get("prompt") or scheme.get("description") \
                if endpoint.get("source") != "solo_mode" else ""
        try:
            return dc.question_for(scheme, str(instructions or ""))
        except ValueError as exc:
            raise TrainerError(str(exc))

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = self._params(spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        problems = []
        if schema.kind not in self.kinds:
            problems.append("Schema %r is %s; a decision model answers "
                            "single-choice and rating questions."
                            % (schema.name, schema.kind))
        problem = dc.question_problem(params, schema.name)
        if problem:
            problems.append(problem)
        if not params.get("_endpoint"):
            problems.append(
                "No decision model %s is configured. Add a labeling_engine "
                "source with kind: decision, or a laya or systemone model to "
                "solo_mode.labeling_models." % (
                    "named %r" % params["source"]
                    if params.get("source") not in (None, "auto") else ""))
        if bundle.split_size("train") < int(params["min_instances"]):
            problems.append(
                "Only %d items in the train split; calibration needs at least "
                "%d. Annotate more, or lower min_instances."
                % (bundle.split_size("train"), int(params["min_instances"])))
        return problems

    # ------------------------------------------------------------------

    def _ask(self, endpoint, question, rows, params, report: ProgressReporter,
             what: str) -> List[Dict[str, float]]:
        size = max(1, int(params["batch_size"]))
        out: List[Dict[str, float]] = []
        for start in range(0, len(rows), size):
            chunk = rows[start:start + size]
            try:
                answers = endpoint.decide_batch(
                    [str(r.get("text", "")) for r in chunk], [question])
            except Exception as exc:  # noqa: BLE001 - the service's own error
                raise TrainerError("The decision model failed on %s items: %s"
                                   % (what, exc))
            out.extend(a[0].probabilities for a in answers)
            report.progress("ask " + what, start + len(chunk), len(rows))
            if report.should_stop():
                raise TrainerError("Cancelled while asking the model")
        return out

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        from potato.ai.decision_calibration import (CALIBRATION_VERSION,
                                                    expected_calibration_error,
                                                    fit_question,
                                                    negative_log_likelihood)

        params = self._params(spec)
        schema = spec.primary_schema
        question = self._question(params, schema)
        endpoint = _make_endpoint(params)
        report.status("running", "asking %s" % type(endpoint).__name__)

        budget = int(params["max_items"])
        splits: Dict[str, List[Dict[str, Any]]] = {}
        for split in ("train", "val", "test"):
            rows = [r for r in bundle.read_split(split)
                    if dc.option_for((r.get("targets") or {}).get(schema.name),
                                     question.options) is not None]
            splits[split] = rows[:budget]
            budget -= len(splits[split])
        if not splits["train"]:
            raise TrainerError("No train items whose label is one of the "
                               "question's options (%s)"
                               % ", ".join(question.options))

        os.makedirs(spec.workdir, exist_ok=True)
        pairs: Dict[str, List[Tuple[Dict[str, float], str]]] = {}
        with open(os.path.join(spec.workdir, RAW_FILE), "w") as fh:
            for split, rows in splits.items():
                if not rows:
                    continue
                distributions = self._ask(endpoint, question, rows, params,
                                          report, split)
                pairs[split] = []
                for row, probs in zip(rows, distributions):
                    gold = dc.option_for(row["targets"][schema.name],
                                         question.options)
                    pairs[split].append((probs, gold))
                    fh.write(json.dumps({"instance_id": row["instance_id"],
                                         "probabilities": probs}) + "\n")

        report.status("running", "fitting the calibration")
        entry = fit_question(pairs["train"], question.options,
                             str(params["method"]), float(params["l2"]))
        if not entry.get("fitted", True):
            report.log("warning", "Calibration not applied: %s. The file "
                                  "keeps the model's own probabilities."
                       % entry.get("note"))
        entry = {"kind": question.kind, "options": list(question.options),
                 **entry}
        metrics: Dict[str, float] = {"n_train": float(len(pairs["train"])),
                                     "temperature": entry["temperature"],
                                     "fitted": 1.0 if entry.get("fitted") else 0.0}
        for split, split_pairs in pairs.items():
            def accuracy(e):
                from potato.ai.decision_calibration import calibrate_distribution
                hits = 0
                for probs, gold in split_pairs:
                    p = calibrate_distribution(probs, e) if e else probs
                    hits += max(p, key=p.get) == gold
                return hits / len(split_pairs)
            for name, value in (
                    ("nll_before", negative_log_likelihood(split_pairs)),
                    ("nll_after", negative_log_likelihood(split_pairs, entry)),
                    ("ece_before", expected_calibration_error(split_pairs)),
                    ("ece_after", expected_calibration_error(split_pairs, entry)),
                    ("accuracy_before", accuracy(None)),
                    ("accuracy_after", accuracy(entry))):
                metrics["%s_%s" % (split, name)] = round(value, 4)
        report.log("info", "Temperature %.3f; ECE on %s %.3f -> %.3f"
                   % (entry["temperature"], "val" if "val" in pairs else "train",
                      metrics.get("val_ece_before", metrics["train_ece_before"]),
                      metrics.get("val_ece_after", metrics["train_ece_after"])))

        endpoint_cfg = params.get("_endpoint") or {}
        public = {k: v for k, v in (endpoint_cfg.get("ai_config") or {}).items()
                  if k in ("base_url", "model", "state_key", "device")}
        calibration = {
            "v": CALIBRATION_VERSION, "method": str(params["method"]),
            "questions": {question.id: entry},
            "n": {question.id: len(pairs["train"])},
            "endpoint": {"source": endpoint_cfg.get("source"),
                         "endpoint_type": endpoint_cfg.get("endpoint_type"),
                         **public},
            "metrics": metrics, "run_id": spec.run_id}
        with open(os.path.join(spec.workdir, CALIBRATION_FILE), "w") as fh:
            json.dump(calibration, fh, indent=2)
        with open(os.path.join(spec.workdir, "model_card.json"), "w") as fh:
            json.dump({"trainer": self.name, "schema": schema.name,
                       "kind": schema.kind, "question": question.id,
                       "options": list(question.options),
                       "endpoint": calibration["endpoint"],
                       "bundle_digest": bundle.digest}, fh, indent=2)
        return FitResult(
            model_version="%s-%s-%s" % (self.name, schema.name, spec.run_id),
            artifact_paths=[CALIBRATION_FILE, RAW_FILE, "model_card.json"],
            metrics=metrics, label_order=list(question.options))

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        from potato.ai.decision_calibration import (calibrate_distribution,
                                                    load_calibration)

        params = self._params(spec)
        schema = spec.primary_schema
        calibration = load_calibration(os.path.join(artifact_dir,
                                                    CALIBRATION_FILE))
        entry = calibration["questions"][next(iter(calibration["questions"]))]
        cached: Dict[str, Dict[str, float]] = {}
        raw = os.path.join(artifact_dir, RAW_FILE)
        if os.path.isfile(raw):
            with open(raw) as fh:
                for line in fh:
                    record = json.loads(line)
                    cached[str(record["instance_id"])] = record["probabilities"]

        items = list(items)
        missing = [i for i in items if str(i.instance_id) not in cached]
        if missing:
            question = self._question(params, schema)
            endpoint = _make_endpoint(params)
            rows = [{"text": i.text} for i in missing]
            for item, probs in zip(missing, self._ask(
                    endpoint, question, rows, params, report, "unlabelled")):
                cached[str(item.instance_id)] = probs

        for item in items:
            probs = cached.get(str(item.instance_id))
            if not probs:
                continue
            calibrated = calibrate_distribution(probs, entry)
            label = max(calibrated, key=calibrated.get)
            confidence = round(float(calibrated[label]), 4)
            yield PredictionRecord(instance_id=item.instance_id,
                                   schema_name=schema.name,
                                   payload={"label": label,
                                            "confidence": confidence},
                                   confidence=confidence)
