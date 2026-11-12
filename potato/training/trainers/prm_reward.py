"""A process reward model: rate each step of an agent trace.

For ``process_reward`` schemes, where annotators marked each step of a trace
correct, neutral or wrong (or clicked the first wrong step, which marks the
rest wrong). The trace is one input -- the task, then ``Step 1``, ``Step 2``
... -- and a transformer encoder with a three-way token classification head
is trained on one token per step, the step's last, so the label for a step is
read with everything before it in view. That is the PRM800K setup (Lightman
et al., 2023) with an encoder instead of a generator.

A trace longer than ``max_length`` tokens is cut from the end: the steps past
the cut get no label in training and no prediction, and the run log counts
them. ``max_length`` is lowered to what the model can hold (512 for most
BERT-class encoders), with a warning. Process supervision is mostly about the early steps, where the first
error is.

Predictions are ``{"steps": [{index, reward, confidence, source}]}``, the
shape the process_reward scheme's AI pre-label button reads, so written-back
predictions are offered there for verification instead of an LLM judge's.
The confidence of a trace is its least confident step.
"""

from __future__ import annotations

import os
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf

INSTALL_HINT = "pip install 'potato-annotation[train-text]'"
_NEEDS = ("torch", "transformers")
DEFAULT_MODEL = "answerdotai/ModernBERT-base"

#: Class order of the head. process_reward stores -1, 0 and 1.
REWARDS = (-1, 0, 1)
TAGS = ("wrong", "neutral", "correct")


def trace_text(trace: Dict[str, Any]) -> Tuple[str, List[Tuple[int, int]]]:
    """The model input and each step's ``(start, end)`` character span."""
    text = str(trace.get("task") or "").strip()
    spans = []
    for n, step in enumerate(trace.get("steps") or []):
        text += ("\n\n" if text else "") + "Step %d\n" % (n + 1)
        begin = len(text)
        text += str(step).rstrip()
        spans.append((begin, max(begin, len(text))))
    return text, spans


def step_tokens(offsets: List[Tuple[int, int]], special: List[bool],
                spans: List[Tuple[int, int]]) -> List[Optional[int]]:
    """For each step, the index of its last token; None when the step is
    empty or the input was cut before the step ended."""
    out: List[Optional[int]] = []
    for begin, end in spans:
        last = None
        for i, (start, stop) in enumerate(offsets):
            if special[i] or start == stop:
                continue
            if begin <= start < end:
                last = i
        out.append(last if last is not None and offsets[last][1] >= end
                   else None)
    return out


class PRMRewardTrainer(Trainer):
    name: ClassVar[str] = "prm-reward"
    description: ClassVar[str] = (
        "Process reward model: fine-tunes a transformer to rate each step of "
        "an agent trace correct, neutral or wrong.")
    kinds: ClassVar[Tuple[str, ...]] = ("trace",)
    modalities: ClassVar[Tuple[str, ...]] = ("text",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "Apache-2.0"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": DEFAULT_MODEL, "epochs": 6, "batch_size": 8,
                "gradient_accumulation": 1, "learning_rate": None,
                "weight_decay": 0.01, "warmup_ratio": 0.1, "patience": 2,
                "precision": "auto", "lora": None, "max_length": 1024,
                "min_instances": 20}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = dict(hf.COMMON_PARAMS)
        props["learning_rate"] = dict(
            props["learning_rate"], default=None,
            description="Defaults to 5e-5, or 3e-4 with LoRA.")
        props.update({
            "model_name": {"type": "string", "default": DEFAULT_MODEL,
                           "description": "A Hugging Face encoder id or a "
                                          "local path. Needs a fast "
                                          "tokenizer; a long context helps, "
                                          "since a whole trace is one input."},
            "max_length": {"type": "integer", "minimum": 32, "default": 1024,
                           "description": "Tokens per trace. Steps past it "
                                          "are neither trained nor rated."},
        })
        return {"type": "object", "properties": props,
                "additionalProperties": False}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        problems = []
        if schema.annotation_type != "process_reward":
            problems.append("Schema %r is %s; this trainer learns per-step "
                            "rewards from a process_reward scheme."
                            % (schema.name, schema.annotation_type))
        if bundle.split_size("train") < int(params["min_instances"]):
            problems.append(
                "Only %d items in the train split; this trainer needs at "
                "least %d. Annotate more, or lower min_instances."
                % (bundle.split_size("train"), int(params["min_instances"])))
        problems.extend(hf.quantize_unsupported(params))
        return problems

    # ------------------------------------------------------------- shared

    @staticmethod
    def _head_kwargs() -> Dict[str, Any]:
        return {"num_labels": len(TAGS),
                "id2label": dict(enumerate(TAGS)),
                "label2id": {t: i for i, t in enumerate(TAGS)},
                "ignore_mismatched_sizes": True}

    @staticmethod
    def _encode(tokenizer, trace: Dict[str, Any], max_length: int
                ) -> Dict[str, Any]:
        text, spans = trace_text(trace)
        enc = tokenizer(text, truncation=True, max_length=max_length,
                        return_offsets_mapping=True,
                        return_special_tokens_mask=True)
        offsets = [tuple(o) for o in enc["offset_mapping"]]
        special = [bool(s) for s in enc["special_tokens_mask"]]
        return {"input_ids": list(enc["input_ids"]),
                "positions": step_tokens(offsets, special, spans),
                "empty": [begin == end for begin, end in spans]}

    def _rate(self, model, tokenizer, trace, max_length, device):
        """``[(index, reward, confidence)]`` for the steps the input holds."""
        import torch

        encoded = self._encode(tokenizer, trace, max_length)
        if not any(p is not None for p in encoded["positions"]):
            return []
        ids = torch.tensor([encoded["input_ids"]], device=device)
        with torch.inference_mode():
            probs = torch.softmax(model(input_ids=ids).logits.float()[0], -1).cpu()
        out = []
        for index, position in enumerate(encoded["positions"]):
            if position is None:
                continue
            p = probs[position]
            best = int(p.argmax())
            out.append((index, REWARDS[best], round(float(p[best]), 4)))
        return out

    # ----------------------------------------------------------------- fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        params = hf.merged_params(self.default_params(), spec)
        if params.get("learning_rate") is None:
            params["learning_rate"] = 3e-4 if params["lora"] else 5e-5
        schema = spec.primary_schema
        max_length = int(params["max_length"])
        train = [r for r in hf.rows_with_target(bundle.read_split("train"),
                                                schema.name) if r.get("trace")]
        val = [r for r in hf.rows_with_target(bundle.read_split("val"),
                                              schema.name) if r.get("trace")]
        if not train:
            raise TrainerError("No rated traces in the train split for %r"
                               % schema.name)

        hf.seed_everything(spec.seed)
        device = hf.pick_device(spec, report)
        report.status("running", "loading %s" % params["model_name"])
        tokenizer = AutoTokenizer.from_pretrained(params["model_name"])
        if not getattr(tokenizer, "is_fast", False):
            raise TrainerError(
                "%s has no fast tokenizer, and finding each step's last token "
                "needs its character offsets. Choose another model."
                % params["model_name"])
        model = AutoModelForTokenClassification.from_pretrained(
            params["model_name"], **self._head_kwargs())
        hf.ensure_pad_token(tokenizer, model)
        limit = hf.context_limit(tokenizer, model)
        if limit is not None and max_length > limit:
            report.log("warning", "max_length=%d is more than %s holds; using %d"
                       % (max_length, params["model_name"], limit))
            max_length = limit
        model = hf.apply_lora(model, params["lora"], "TOKEN_CLS", report)
        model.to(device)

        examples, n_steps, n_cut, n_empty = [], 0, 0, 0
        for row in train:
            encoded = self._encode(tokenizer, row["trace"], max_length)
            labels = [-100] * len(encoded["input_ids"])
            for reward, position, empty in zip(row["targets"][schema.name],
                                               encoded["positions"],
                                               encoded["empty"]):
                if reward is None:
                    continue
                if position is None:
                    if empty:
                        n_empty += 1
                    else:
                        n_cut += 1
                    continue
                labels[position] = REWARDS.index(int(reward))
                n_steps += 1
            if any(l != -100 for l in labels):
                examples.append({"input_ids": encoded["input_ids"],
                                 "labels": labels})
        if n_cut:
            report.log("warning", "%d rated step(s) fell past max_length=%d "
                                  "and were not trained on"
                       % (n_cut, max_length))
        if n_empty:
            report.log("warning", "%d rated step(s) have no text and were not "
                                  "trained on" % n_empty)
        if not examples:
            raise TrainerError("No rated step fits in max_length=%d tokens"
                               % max_length)
        report.log("info", "%d train traces with %d rated steps, %d val traces"
                   % (len(examples), n_steps, len(val)))

        pad = tokenizer.pad_token_id or 0

        def loss_of(batch):
            width = max(len(e["input_ids"]) for e in batch)
            ids = torch.tensor([e["input_ids"] + [pad] * (width - len(e["input_ids"]))
                                for e in batch], device=device)
            mask = torch.tensor([[1] * len(e["input_ids"]) + [0] * (width - len(e["input_ids"]))
                                 for e in batch], device=device)
            target = torch.tensor([e["labels"] + [-100] * (width - len(e["labels"]))
                                   for e in batch], device=device)
            return model(input_ids=ids, attention_mask=mask, labels=target).loss

        selected = {"best": None, "saved": False}

        def on_epoch_end(epoch):
            if not val:
                return None
            from potato.training.evaluation import score_split
            model.eval()
            predictions = {
                (str(row.get("instance_id", "")), schema.name): {"steps": [
                    {"index": i, "reward": r} for i, r, _ in
                    self._rate(model, tokenizer, row["trace"], max_length, device)]}
                for row in val}
            model.train()
            metrics, _ = score_split(val, predictions, schema.name, "trace")
            score = metrics.get("step_macro_f1", 0.0)
            report.metric("val", "step_macro_f1", score, step=epoch + 1)
            if selected["best"] is None or score > selected["best"]:
                selected["best"] = score
                hf.save_model(model, tokenizer, spec.workdir)
                selected["saved"] = True
            return score

        report.status("running", "fine-tuning")
        summary = hf.train_loop(model, examples, params, loss_of, report,
                                device=device, seed=spec.seed,
                                on_epoch_end=on_epoch_end)
        if not selected["saved"]:
            hf.save_model(model, tokenizer, spec.workdir)

        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": "trace",
            "base_model": params["model_name"], "lora": params["lora"],
            "tags": list(TAGS), "max_length": max_length, "device": device,
            "n_train": len(examples), "bundle_digest": bundle.digest,
            "selected_epoch": summary["best_epoch"]})

        metrics = {"n_train": float(len(examples)), "n_steps": float(n_steps),
                   "train_seconds": summary["train_seconds"],
                   "epochs_run": float(summary["epochs_run"])}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        return FitResult(
            model_version="%s-%s-%s" % (self.name, schema.name, spec.run_id),
            artifact_paths=hf.artifact_files(spec.workdir), metrics=metrics,
            label_order=list(TAGS), selected_on="val" if val else "")

    # ------------------------------------------------------------- predict

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        card = hf.read_card(artifact_dir)
        device = hf.pick_device(spec, report)
        tokenizer = AutoTokenizer.from_pretrained(
            os.path.join(artifact_dir, hf.MODEL_DIR))
        model = hf.load_pretrained(AutoModelForTokenClassification,
                                   artifact_dir, card, device,
                                   **self._head_kwargs())
        model.eval()
        max_length = int(card.get("max_length", 1024))

        items = [item for item in items if (item.data or {}).get("trace")]
        for n, item in enumerate(items):
            rated = self._rate(model, tokenizer, item.data["trace"],
                               max_length, device)
            if rated:
                confidence = min(c for _, _, c in rated)
                yield PredictionRecord(
                    instance_id=item.instance_id, schema_name=card["schema"],
                    payload={"steps": [
                        {"index": i, "reward": r, "confidence": c,
                         "source": "model"} for i, r, c in rated]},
                    confidence=confidence)
            report.progress("predict", n + 1, len(items))
            if report.should_stop():
                return
