"""Fine-tune a Laya decision model on the study's labels.

Laya (Convai Innovations, Apache-2.0) is an open decision model: a
ModernBERT encoder with a head that scores a question's options in one
forward pass, and the in-process backend of Potato's ``laya`` endpoint.
This trainer runs Laya's own fine-tuning (``laya.train.finetune``) on the
scheme's labelled items, asked as the same question the endpoint asks
(``questions_for_scheme``), and Laya's own temperature calibration on a slice
of the train split. The result is a checkpoint directory that
``laya.load`` reads: set ``model`` of a ``laya`` labeling-engine source or
solo-mode labeling model to the run's ``artifacts/model``, and that model
labels with the fine-tuned checkpoint.

Laya's loop runs to the end once it starts: a cancel takes effect when the
grace period runs out and the run's process is stopped.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import sys
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _decision_common as dc
from potato.training.trainers import _hf_common as hf

INSTALL_HINT = "pip install 'potato-annotation[decision]'"
_NEEDS = ("torch", "laya")
DEFAULT_MODEL = "convaiinnovations/laya"
STATE_KEY = "text"


class LayaFinetuneTrainer(Trainer):
    name: ClassVar[str] = "laya-finetune"
    description: ClassVar[str] = (
        "Fine-tunes a Laya decision model (ModernBERT) on the scheme's labels, "
        "with Laya's own calibration; the checkpoint loads in the laya "
        "endpoint.")
    kinds: ClassVar[Tuple[str, ...]] = ("nominal", "ordinal", "continuous")
    annotation_types: ClassVar[Tuple[str, ...]] = ("radio", "select", "likert",
                                                   "slider")
    modalities: ClassVar[Tuple[str, ...]] = ("text",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "Apache-2.0"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": DEFAULT_MODEL, "epochs": 4, "micro_batch": 8,
                "grad_accum": 2, "encoder_lr": 2.5e-5, "head_lr": 1e-4,
                "loss": "soft-ce", "freeze_encoder": False,
                "shuffle_options": True, "instructions": None,
                "calib_frac": 0.1, "min_instances": 20}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        return {"type": "object", "additionalProperties": False, "properties": {
            "model_name": {"type": "string", "default": DEFAULT_MODEL,
                           "description": "A Laya checkpoint: a Hub id, an "
                                          "alias (multilingual), or a local "
                                          "directory such as an earlier "
                                          "run's artifacts/model."},
            "epochs": dict(hf.COMMON_PARAMS["epochs"], default=4),
            "micro_batch": {"type": "integer", "minimum": 1, "default": 8},
            "grad_accum": {"type": "integer", "minimum": 1, "default": 2},
            "encoder_lr": {"type": "number", "exclusiveMinimum": 0,
                           "default": 2.5e-5},
            "head_lr": {"type": "number", "exclusiveMinimum": 0,
                        "default": 1e-4},
            "loss": {"type": "string", "enum": ["soft-ce", "rlcd"],
                     "default": "soft-ce",
                     "description": "Laya's objectives; rlcd is its "
                                    "notebook's."},
            "freeze_encoder": {"type": "boolean", "default": False,
                               "description": "Train the head only."},
            "shuffle_options": {"type": "boolean", "default": True,
                                "description": "Present options in a random "
                                               "order each epoch, so the "
                                               "model cannot learn a "
                                               "position."},
            "instructions": {"type": ["string", "null"], "default": None,
                             "description": "Put before the scheme's "
                                            "description in the question; "
                                            "null uses the first decision "
                                            "engine source's prompt."},
            "calib_frac": {"type": "number", "minimum": 0, "maximum": 0.5,
                           "default": 0.1,
                           "description": "Share of the train split held "
                                          "back for Laya's calibration."},
            "min_instances": hf.COMMON_PARAMS["min_instances"],
        }}

    @classmethod
    def server_params(cls, config, schema_names, params) -> Dict[str, Any]:
        out: Dict[str, Any] = {"_schemes": dc.schemes_for(config, schema_names)}
        entry = dc.pick_endpoint(config, "auto")
        if entry and entry["source"] != "solo_mode" and entry.get("prompt"):
            out["_instructions"] = entry["prompt"]
        return out

    def _params(self, spec: TrainingSpec) -> Dict[str, Any]:
        return {**self.default_params(), **(spec.params or {})}

    def _question(self, params, schema):
        scheme = (params.get("_schemes") or {}).get(schema.name)
        if not scheme:
            raise TrainerError("The run has no config for scheme %r"
                               % schema.name)
        instructions = params.get("instructions")
        if instructions is None:
            instructions = params.get("_instructions", "")
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
            problems.append("Schema %r is %s; Laya answers single-choice and "
                            "rating questions." % (schema.name, schema.kind))
        problem = dc.question_problem(params, schema.name)
        if problem:
            problems.append(problem)
        if bundle.split_size("train") < int(params["min_instances"]):
            problems.append(
                "Only %d items in the train split; this trainer needs at "
                "least %d. Annotate more, or lower min_instances."
                % (bundle.split_size("train"), int(params["min_instances"])))
        return problems

    def _rows(self, bundle, split, schema, question) -> List[Dict[str, Any]]:
        from potato.ai.decision_endpoint import build_systemone_questions

        payload = build_systemone_questions([question])
        rows = []
        for row in bundle.read_split(split):
            option = dc.option_for((row.get("targets") or {}).get(schema.name),
                                   question.options)
            if option is None or not str(row.get("text", "")).strip():
                continue
            # A score question's answer is its level index; a choice
            # question's is the option's name.
            expected = (question.options.index(option)
                        if question.kind == "score" else option)
            rows.append({"state": {STATE_KEY: row["text"]},
                         "questions": payload,
                         "expected": {question.id: expected}})
        return rows

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        from laya import train as laya_train

        params = self._params(spec)
        schema = spec.primary_schema
        question = self._question(params, schema)
        train_rows = self._rows(bundle, "train", schema, question)
        val_rows = self._rows(bundle, "val", schema, question)
        if not train_rows:
            raise TrainerError("No train items whose label is one of the "
                               "question's options (%s)"
                               % ", ".join(question.options))

        os.makedirs(spec.workdir, exist_ok=True)
        data_dir = os.path.join(spec.workdir, "laya_data")
        os.makedirs(data_dir, exist_ok=True)
        paths = {}
        for name, rows in (("train", train_rows), ("val", val_rows)):
            paths[name] = os.path.join(data_dir, name + ".jsonl")
            with open(paths[name], "w") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")

        device = hf.pick_device(spec, report)
        wanted = {
            "epochs": int(params["epochs"]),
            "micro_batch": int(params["micro_batch"]),
            "grad_accum": int(params["grad_accum"]),
            "encoder_lr": float(params["encoder_lr"]),
            "head_lr": float(params["head_lr"]), "loss": str(params["loss"]),
            "freeze_encoder": bool(params["freeze_encoder"]),
            "shuffle_options": (question.kind,) if params["shuffle_options"] else (),
            "calib_frac": float(params["calib_frac"]), "seed": int(spec.seed),
            "eval_data": paths["val"] if val_rows else None}
        # Only the fields this laya version has: 0.4.6 and 0.4.7 differ.
        fields = {f.name for f in dataclasses.fields(laya_train.TrainConfig)}
        config = laya_train.TrainConfig(**{k: v for k, v in wanted.items()
                                           if k in fields})

        report.status("running", "loading %s" % params["model_name"])
        model_dir = laya_train.resolve_checkpoint_dir(str(params["model_name"]))
        output_dir = os.path.join(spec.workdir, hf.MODEL_DIR)
        report.log("info", "%d train and %d val items; %s question with %d "
                           "options" % (len(train_rows), len(val_rows),
                                        question.kind, len(question.options)))
        report.status("running", "fine-tuning (laya)")
        # Laya prints its progress; stdout is this process's event channel.
        with contextlib.redirect_stdout(sys.stderr):
            summary = laya_train.finetune(paths["train"], model_dir,
                                          output_dir, config=config,
                                          device=device)
        if report.should_stop():
            raise TrainerError("Cancelled during training")

        # Laya keeps a resumable copy of the last epoch beside the final
        # checkpoint: the same weights again, 800 MB for the default model,
        # and nothing loads it.
        import shutil
        shutil.rmtree(os.path.join(output_dir, "checkpoint_latest"),
                      ignore_errors=True)

        summary = summary or {}
        metrics: Dict[str, float] = {"n_train": float(len(train_rows))}
        for key, value in summary.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                metrics["laya_" + str(key)] = float(value)
        losses = summary.get("epoch_loss") or []
        if losses and isinstance(losses[-1], (int, float)):
            metrics["train_loss"] = round(float(losses[-1]), 4)
        temperature = summary.get("temperature")
        if isinstance(temperature, list) and temperature \
                and isinstance(temperature[0], (int, float)):
            metrics["laya_temperature"] = round(float(temperature[0]), 4)
        with open(os.path.join(spec.workdir, "laya_summary.json"), "w") as fh:
            json.dump(summary, fh, indent=2, default=str)
        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "base_model": params["model_name"],
            "question": dataclasses.asdict(question),
            "device": device, "n_train": len(train_rows),
            "bundle_digest": bundle.digest})
        shutil.rmtree(data_dir, ignore_errors=True)
        return FitResult(
            model_version="%s-%s-%s" % (self.name, schema.name, spec.run_id),
            artifact_paths=hf.artifact_files(spec.workdir), metrics=metrics,
            label_order=list(question.options))

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        import laya

        from potato.ai.decision_endpoint import (DecisionQuestion,
                                                 build_systemone_questions,
                                                 parse_systemone_answers)

        card = hf.read_card(artifact_dir)
        question = DecisionQuestion(**card["question"])
        device = hf.pick_device(spec, report)
        with contextlib.redirect_stdout(sys.stderr):
            agent = laya.load(os.path.join(artifact_dir, hf.MODEL_DIR),
                              device=device)
        payload = build_systemone_questions([question])
        items = [i for i in items if str(i.text or "").strip()]
        for start in range(0, len(items), 32):
            chunk = items[start:start + 32]
            with contextlib.redirect_stdout(sys.stderr):
                results = agent.predict_batch(
                    [{STATE_KEY: i.text} for i in chunk], payload)
            for item, result in zip(chunk, results):
                answer = parse_systemone_answers(result, [question])[0]
                confidence = round(float(answer.confidence), 4)
                yield PredictionRecord(
                    instance_id=item.instance_id, schema_name=card["schema"],
                    payload={"label": answer.value, "confidence": confidence},
                    confidence=confidence)
            report.progress("predict", start + len(chunk), len(items))
            if report.should_stop():
                return
