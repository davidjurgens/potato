"""Fine-tune OpenJev on the study's labels.

OpenJev (``alanhuangya/OpenJev-8B``, Apache-2.0) is an open decision model:
Qwen3-8B with a pointer head that scores a question's options, served as
``/v1/systemone`` by the ``wev`` package (``pip install wev-ai``). ``wev
train`` trains a LoRA adapter and the head, and ``--init_from`` continues
from a training run. The Hub release is not a training run: its adapter is
merged into the backbone and its head is a separate file. So this trainer
first bridges the release into a run that starts exactly as the release
answers: the merged weights as the base, a new adapter whose output is zero,
and the released head. That bridge is cached per model revision.

The data is the scheme's question for each labelled item, asked as the
labeling engine asks it, with the annotators' answer; ``wev train`` runs in
its own process, and its progress and val accuracy come back as the run's.
The result in ``artifacts/model`` is a ``wev`` training run: serve it with
``wev serve --model <dir>`` and point a ``systemone`` labeling-engine source
at it.

It needs a GPU with about 16 GB free for the 8B model. OpenJev's card notes
that some of its training data is research-only; check those terms before
commercial use.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _decision_common as dc
from potato.training.trainers import _hf_common as hf

INSTALL_HINT = "pip install wev-ai"
_NEEDS = ("torch", "wev", "peft", "transformers")
DEFAULT_MODEL = "alanhuangya/OpenJev-8B"
STATE_KEY = "text"

#: Runs in its own process: loading the 8B release takes its memory, and the
#: training process that follows needs it back.
BRIDGE_SCRIPT = r'''
import json, sys
from pathlib import Path
import torch
from huggingface_hub import snapshot_download
from safetensors.torch import load_file
from transformers import AutoTokenizer
from wev.model import DecisionModel

source, out, device = sys.argv[1], sys.argv[2], sys.argv[3]
local = Path(source).is_dir()
snap = Path(source) if local else Path(snapshot_download(source))
info = json.loads((snap / "wev.json").read_text())
tok = AutoTokenizer.from_pretrained(snap)
model = DecisionModel(str(snap), tok, device,
                      lora=int((info.get("train_args") or {}).get("lora", 16)),
                      dtype=torch.bfloat16, head_dim=info.get("head_dim", 256),
                      head=info.get("head_type", "pointer"),
                      keep_layers=info.get("keep_layers"))
model.head.load_state_dict(load_file(str(snap / "head.safetensors")))
model.save(out, max_state=info.get("train_max_state"),
           max_branch=info.get("train_max_branch"),
           temperature=info.get("temperature"))
meta = torch.load(Path(out) / "head.pt", map_location="cpu", weights_only=False)
if not local:
    # The Hub id and the revision, not this machine's cache path, so the
    # trained run loads wherever wev can reach the Hub.
    meta["base"], meta["base_revision"] = source, snap.name
    torch.save(meta, Path(out) / "head.pt")
print(json.dumps({"bridged": str(snap)}))
'''

_STEP = re.compile(r"^ep (\d+) step (\d+) batch (\d+)/(\d+) loss ([0-9.eE+-]+)")
_DEV = re.compile(r"^== epoch (\d+) dev\[[^\]]*\]: (\{.*\})\s*$")


def wev_rows(rows: Iterable[Dict[str, Any]], schema: str, question,
             payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Labelled rows in ``wev``'s training format: the request as a client
    sends it, and the answer (a choice's option, a rating's level index)."""
    out = []
    for row in rows:
        option = dc.option_for((row.get("targets") or {}).get(schema),
                               question.options)
        if option is None or not str(row.get("text", "")).strip():
            continue
        label = (question.options.index(option) if question.kind == "score"
                 else option)
        out.append({"request": {"model": "openjev",
                                "state": {STATE_KEY: row["text"]},
                                "questions": payload},
                    "labels": {question.id: label}})
    return out


def parse_log_line(line: str) -> Optional[Dict[str, Any]]:
    """A ``wev train`` progress or dev line, as a dict; None otherwise."""
    line = line.strip()
    m = _STEP.match(line)
    if m:
        return {"kind": "step", "epoch": int(m.group(1)), "step": int(m.group(2)),
                "batch": int(m.group(3)), "batches": int(m.group(4)),
                "loss": float(m.group(5))}
    m = _DEV.match(line)
    if m:
        try:
            return {"kind": "dev", "epoch": int(m.group(1)),
                    "result": json.loads(m.group(2))}
        except ValueError:
            return None
    return None


def _cache_dir() -> str:
    root = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache")
    path = os.path.join(root, "potato", "openjev")
    os.makedirs(path, exist_ok=True)
    return path


class OpenJevFinetuneTrainer(Trainer):
    name: ClassVar[str] = "openjev-finetune"
    description: ClassVar[str] = (
        "Fine-tunes OpenJev (an 8B decision model) on the scheme's labels "
        "with wev's LoRA training; serve the result with wev serve.")
    kinds: ClassVar[Tuple[str, ...]] = ("nominal", "ordinal", "continuous")
    annotation_types: ClassVar[Tuple[str, ...]] = ("radio", "select", "likert",
                                                   "slider")
    modalities: ClassVar[Tuple[str, ...]] = ("text",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "Apache-2.0"
    commercial_use: ClassVar[Optional[bool]] = None

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": DEFAULT_MODEL, "epochs": 3, "batch_size": 8,
                "gradient_accumulation": 1, "learning_rate": 5e-5,
                "gradient_checkpointing": True, "max_state": 4096,
                "max_branch": 2048, "instructions": None, "min_instances": 20}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        return {"type": "object", "additionalProperties": False, "properties": {
            "model_name": {"type": "string", "default": DEFAULT_MODEL,
                           "description": "An OpenJev release on the Hub, a "
                                          "local export, or an earlier run's "
                                          "artifacts/model."},
            "epochs": dict(hf.COMMON_PARAMS["epochs"], default=3),
            "batch_size": {"type": "integer", "minimum": 1, "default": 8,
                           "description": "Items per step."},
            "gradient_accumulation": dict(hf.COMMON_PARAMS["gradient_accumulation"]),
            "learning_rate": {"type": "number", "exclusiveMinimum": 0,
                              "default": 5e-5,
                              "description": "wev's advice for 4B and up; "
                                             "2e-4 erodes what the model "
                                             "already knows."},
            "gradient_checkpointing": {"type": "boolean", "default": True},
            "max_state": {"type": "integer", "minimum": 64, "default": 4096,
                          "description": "Tokens of item text; longer items "
                                         "are left out of training."},
            "max_branch": {"type": "integer", "minimum": 64, "default": 2048,
                           "description": "Tokens per question."},
            "instructions": {"type": ["string", "null"], "default": None,
                             "description": "Put before the scheme's "
                                            "description in the question; "
                                            "null uses the first decision "
                                            "engine source's prompt."},
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
            problems.append("Schema %r is %s; OpenJev answers single-choice "
                            "and rating questions." % (schema.name, schema.kind))
        problem = dc.question_problem(params, schema.name)
        if problem:
            problems.append(problem)
        if bundle.split_size("train") < int(params["min_instances"]):
            problems.append(
                "Only %d items in the train split; this trainer needs at "
                "least %d. Annotate more, or lower min_instances."
                % (bundle.split_size("train"), int(params["min_instances"])))
        return problems

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _run(argv: List[str], report: ProgressReporter, what: str,
             on_line=None) -> None:
        """A child process, its output logged, stopped on cancel."""
        process = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True,
                                   bufsize=1, start_new_session=True)
        tail: List[str] = []
        try:
            for line in process.stdout:
                tail = (tail + [line.rstrip()])[-30:]
                if on_line is not None:
                    on_line(line)
                if report.should_stop():
                    process.terminate()
                    process.wait(timeout=60)
                    raise TrainerError("Cancelled during %s" % what)
            code = process.wait()
        finally:
            if process.poll() is None:
                process.kill()
        if code != 0:
            raise TrainerError("%s exited with code %d:\n%s"
                               % (what, code, "\n".join(tail[-12:])))

    def _bridged(self, model_name: str, device: str,
                 report: ProgressReporter) -> str:
        """A ``wev`` training run to start from: an earlier run as it is, or
        the release bridged (once per revision; cached)."""
        if os.path.isfile(os.path.join(model_name, "head.pt")):
            return model_name
        key = model_name
        if not os.path.isdir(model_name):
            try:
                from huggingface_hub import snapshot_download
                key = snapshot_download(model_name, allow_patterns=["wev.json"])
            except Exception:  # noqa: BLE001 - offline: bridge anyway
                key = model_name
        out = os.path.join(_cache_dir(), hashlib.sha256(
            key.encode()).hexdigest()[:16])
        if os.path.isfile(os.path.join(out, "head.pt")):
            report.log("info", "Starting from the cached bridge of %s"
                       % model_name)
            return out
        report.status("running", "preparing %s for training" % model_name)
        self._run([sys.executable, "-c", BRIDGE_SCRIPT, model_name, out + ".tmp",
                   device], report, "preparing the model")
        os.replace(out + ".tmp", out)
        return out

    # ------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        from potato.ai.decision_endpoint import build_systemone_questions

        params = self._params(spec)
        schema = spec.primary_schema
        question = self._question(params, schema)
        payload = build_systemone_questions([question])
        train = wev_rows(bundle.read_split("train"), schema.name, question, payload)
        val = wev_rows(bundle.read_split("val"), schema.name, question, payload)
        if not train:
            raise TrainerError("No train items whose label is one of the "
                               "question's options (%s)"
                               % ", ".join(question.options))

        data_dir = os.path.join(spec.workdir, "wev_data", schema.name)
        os.makedirs(data_dir, exist_ok=True)
        for name, rows in (("train", train), ("dev", val or train[:1])):
            with open(os.path.join(data_dir, name + ".jsonl"), "w") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")

        device = hf.pick_device(spec, report)
        start = self._bridged(str(params["model_name"]), device, report)
        out = os.path.join(spec.workdir, hf.MODEL_DIR)
        report.log("info", "%d train and %d val items; %s question with %d "
                           "options" % (len(train), len(val), question.kind,
                                        len(question.options)))

        epochs = int(params["epochs"])
        # Per epoch, the steps' losses: the last step alone is often a
        # remainder batch of one or two items, and read 0.0 on a real run.
        state: Dict[str, Any] = {"losses": {}}

        def on_line(line):
            event = parse_log_line(line)
            if event is None:
                return
            if event["kind"] == "step":
                done = event["epoch"] * event["batches"] + event["batch"]
                report.progress("train", done, epochs * event["batches"])
                state["losses"].setdefault(event["epoch"], []).append(event["loss"])
            elif event["kind"] == "dev":
                losses = state["losses"].get(event["epoch"]) or []
                if losses:
                    report.metric("train", "loss", sum(losses) / len(losses),
                                  step=event["epoch"] + 1)
                if not val:
                    return
                accuracy = (event["result"].get(question.id) or {}).get(
                    "accuracy", event["result"].get("step_success"))
                if accuracy is not None:
                    report.metric("val", "accuracy", float(accuracy),
                                  step=event["epoch"] + 1)
                    report.log("info", "Epoch %d: val accuracy %.3f"
                               % (event["epoch"] + 1, float(accuracy)))

        argv = [sys.executable, "-m", "wev.cli", "train", "--init_from", start,
                "--data", data_dir, "--out", out, "--epochs", str(epochs),
                "--lr", str(float(params["learning_rate"])),
                "--batch_tokens", "0", "--batch", str(int(params["batch_size"])),
                "--accum", str(int(params["gradient_accumulation"])),
                "--checkpointing", "1" if params["gradient_checkpointing"] else "0",
                "--max_state", str(int(params["max_state"])),
                "--max_branch", str(int(params["max_branch"])),
                "--eval_n", str(max(1, len(val))), "--log_every", "1",
                "--seed", str(int(spec.seed))]
        report.status("running", "fine-tuning (wev)")
        self._run(argv, report, "wev train", on_line)
        if not os.path.isfile(os.path.join(out, "head.pt")):
            raise TrainerError("wev train finished without writing a run "
                               "to %s" % out)
        import shutil
        # Resumable optimizer state, not part of the model.
        shutil.rmtree(os.path.join(out, "ckpt"), ignore_errors=True)
        shutil.rmtree(os.path.join(spec.workdir, "wev_data"), ignore_errors=True)

        version = "%s-%s-%s" % (self.name, schema.name, spec.run_id)
        import dataclasses
        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "base_model": params["model_name"], "model_version": version,
            "question": dataclasses.asdict(question), "device": device,
            "n_train": len(train), "bundle_digest": bundle.digest})
        metrics = {"n_train": float(len(train))}
        if state["losses"]:
            last = state["losses"][max(state["losses"])]
            metrics["train_loss"] = round(sum(last) / len(last), 4)
        return FitResult(model_version=version,
                         artifact_paths=hf.artifact_files(spec.workdir),
                         metrics=metrics, label_order=list(question.options))

    # ------------------------------------------------------------ predict

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        import wev

        from potato.ai.decision_endpoint import (DecisionQuestion,
                                                 build_systemone_questions,
                                                 parse_systemone_answers)

        card = hf.read_card(artifact_dir)
        question = DecisionQuestion(**card["question"])
        payload = build_systemone_questions([question])
        device = hf.pick_device(spec, report)
        model = wev.load(os.path.join(artifact_dir, hf.MODEL_DIR), device=device)
        items = [i for i in items if str(i.text or "").strip()]
        for n, item in enumerate(items):
            result = model.predict({STATE_KEY: item.text}, payload)
            answer = parse_systemone_answers(result, [question])[0]
            confidence = round(float(answer.confidence), 4)
            yield PredictionRecord(
                instance_id=item.instance_id, schema_name=card["schema"],
                payload={"label": answer.value, "confidence": confidence},
                confidence=confidence)
            if n % 20 == 19 or n + 1 == len(items):
                report.progress("predict", n + 1, len(items))
                if report.should_stop():
                    return
