"""Direct Preference Optimization on pairwise preferences.

For a binary ``pairwise`` scheme, where annotators chose which of two
responses is better: each item with a preference becomes one
(prompt, chosen, rejected) triple, and DPO (Rafailov et al., 2023) trains the
model to raise the chosen response's likelihood relative to the rejected one,
measured against a frozen reference copy of where it started. The loss is

    -log sigmoid(beta * ((log pi(chosen) - log ref(chosen))
                         - (log pi(rejected) - log ref(rejected))))

The prompt is the item's ``prompt`` field (or ``question``, ``instruction``,
``query``, ``input``, ``context``: the first one present). The responses are
the scheme's ``items_key`` list, in data order, so "A" is the first.
"No preference" answers are left out: they say nothing about which response
is better.

With LoRA, the default, the reference model is the same model with its
adapter switched off, so DPO needs no second copy in memory. Reference
log-probabilities are computed once, before training, since they never change.

Predictions are which response the trained model prefers: ``A`` when its
implicit reward for the first response is higher. The confidence is the
Bradley-Terry probability of that preference, ``sigmoid(beta * margin)``. The
held-out score is agreement with the annotators' choices, ties not counted.
The fitted model is also a policy: its adapter is saved and can be loaded with
peft to generate.

Plain torch, not trl's DPOTrainer: trl was on one of the two hosts this was
built against, and its trainer arguments change between releases.
"""

from __future__ import annotations

import math
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf
from potato.training.trainers.llm_sft import (LLMSFTTrainer, build_prompt,
                                              encode_example)

INSTALL_HINT = "pip install 'potato-annotation[train-llm]'"
_NEEDS = ("torch", "transformers", "peft")
DEFAULT_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
CHOICES = ("A", "B")


def preference_triples(rows: Iterable[Dict[str, Any]], schema: str
                       ) -> Tuple[List[Dict[str, Any]], int]:
    """``({row, prompt, chosen, rejected}, n_ties_or_unusable)``."""
    out, skipped = [], 0
    for row in rows:
        choice = str((row.get("targets") or {}).get(schema, "")).strip().upper()
        candidates = row.get("candidates") or []
        if choice not in CHOICES or len(candidates) < 2:
            skipped += 1
            continue
        first, second = str(candidates[0]), str(candidates[1])
        chosen, rejected = (first, second) if choice == "A" else (second, first)
        out.append({"row": row, "prompt": str(row.get("prompt") or ""),
                    "chosen": chosen, "rejected": rejected})
    return out, skipped


def dpo_loss(policy_chosen, policy_rejected, ref_chosen, ref_rejected,
             beta: float):
    """Mean DPO loss and the per-pair reward margin (a tensor each)."""
    import torch

    margin = beta * ((policy_chosen - ref_chosen)
                     - (policy_rejected - ref_rejected))
    return -torch.nn.functional.logsigmoid(margin).mean(), margin


class LLMDPOTrainer(Trainer):
    name: ClassVar[str] = "llm-dpo"
    description: ClassVar[str] = (
        "Direct Preference Optimization of an LLM (LoRA by default) on "
        "which of two responses annotators preferred.")
    kinds: ClassVar[Tuple[str, ...]] = ("preference",)
    modalities: ClassVar[Tuple[str, ...]] = ("text",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "Apache-2.0"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": DEFAULT_MODEL, "epochs": 2, "batch_size": 4,
                "gradient_accumulation": 4, "learning_rate": None,
                "weight_decay": 0.0, "warmup_ratio": 0.1, "patience": 1,
                "precision": "auto", "lora": True, "beta": 0.1,
                "max_length": 1024, "instruction": "", "system_prompt": "",
                "chat_template": "auto", "gradient_checkpointing": False,
                "min_instances": 20}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        sft = LLMSFTTrainer.params_schema()["properties"]
        props = dict(hf.COMMON_PARAMS)
        props["lora"] = dict(props["lora"], default=True,
                             description=props["lora"]["description"]
                             + " false trains every weight and keeps a "
                               "second, frozen copy as the reference.")
        props["epochs"] = dict(props["epochs"], default=2)
        props["batch_size"] = dict(props["batch_size"], default=4,
                                   description="Preference pairs per step.")
        props["patience"] = dict(props["patience"], default=1)
        props["learning_rate"] = dict(
            props["learning_rate"], default=None,
            description="Defaults to 5e-5 with LoRA, 5e-7 without.")
        props.update({
            "model_name": sft["model_name"],
            "beta": {"type": "number", "exclusiveMinimum": 0, "default": 0.1,
                     "description": "How far the model may move from the "
                                    "reference: lower lets it move further."},
            "max_length": dict(sft["max_length"],
                               description="Tokens per prompt and response."),
            "instruction": {"type": "string", "default": "",
                            "description": "Put before each item's prompt."},
            "system_prompt": sft["system_prompt"],
            "chat_template": sft["chat_template"],
            "gradient_checkpointing": sft["gradient_checkpointing"],
        })
        return {"type": "object", "properties": props,
                "additionalProperties": False}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        problems = []
        if schema.kind not in self.kinds:
            problems.append("Schema %r is %s; this trainer learns from binary "
                            "pairwise preferences." % (schema.name, schema.kind))
        if bundle.split_size("train") < int(params["min_instances"]):
            problems.append(
                "Only %d items in the train split; this trainer needs at "
                "least %d. Annotate more, or lower min_instances."
                % (bundle.split_size("train"), int(params["min_instances"])))
        return problems

    # ------------------------------------------------------------ shared

    def _encode(self, tokenizer, triple_or_pair: Dict[str, Any], response: str,
                params, chat: bool) -> Dict[str, List[int]]:
        prompt = build_prompt(tokenizer, str(params.get("instruction") or ""),
                              triple_or_pair["prompt"],
                              str(params.get("system_prompt") or ""), chat)
        return encode_example(tokenizer, prompt, response,
                              int(params["max_length"]))

    @staticmethod
    def _sequence_logps(model, examples, pad: int, device: str):
        """Summed log-probability of each example's labelled tokens."""
        import torch

        width = max(len(e["input_ids"]) for e in examples)
        ids = torch.tensor([e["input_ids"] + [pad] * (width - len(e["input_ids"]))
                            for e in examples], device=device)
        mask = torch.tensor([[1] * len(e["input_ids"])
                             + [0] * (width - len(e["input_ids"]))
                             for e in examples], device=device)
        labels = torch.tensor([e["labels"] + [-100] * (width - len(e["labels"]))
                               for e in examples], device=device)
        logits = model(input_ids=ids, attention_mask=mask).logits[:, :-1].float()
        targets = labels[:, 1:]
        keep = targets != -100
        logps = torch.log_softmax(logits, -1).gather(
            -1, targets.clamp(min=0).unsqueeze(-1)).squeeze(-1)
        return (logps * keep).sum(-1)

    def _reference_logps(self, model, reference, pairs, pad, device, size,
                         report: ProgressReporter, what: str) -> List[Tuple[float, float]]:
        import torch

        out: List[Tuple[float, float]] = []
        for start in range(0, len(pairs), size):
            batch = pairs[start:start + size]
            with torch.inference_mode():
                if reference is None:
                    with model.disable_adapter():
                        values = self._sequence_logps(
                            model, [e for p in batch for e in (p["c"], p["r"])],
                            pad, device)
                else:
                    values = self._sequence_logps(
                        reference, [e for p in batch for e in (p["c"], p["r"])],
                        pad, device)
            values = values.cpu().tolist()
            out.extend(zip(values[0::2], values[1::2]))
            if report.should_stop():
                raise TrainerError("Cancelled while scoring the reference")
        report.log("info", "Reference log-probabilities for %d %s pairs"
                   % (len(pairs), what))
        return out

    # ------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        import copy

        import torch

        params = hf.merged_params(self.default_params(), spec)
        if params.get("learning_rate") is None:
            params["learning_rate"] = 5e-5 if params["lora"] else 5e-7
        beta = float(params["beta"])
        schema = spec.primary_schema
        train, skipped = preference_triples(bundle.read_split("train"),
                                            schema.name)
        val, _ = preference_triples(bundle.read_split("val"), schema.name)
        if not train:
            raise TrainerError(
                "No A/B preferences with two responses in the train split "
                "for %r. The responses come from the scheme's items_key list."
                % schema.name)
        if skipped:
            report.log("info", "Left out %d train item(s) answered with no "
                               "preference or without two responses" % skipped)
        if not any(t["prompt"] for t in train):
            report.log("warning", "No item has a prompt field (%s); the model "
                                  "learns which response is better with "
                                  "nothing to say what it answers"
                       % ", ".join(("prompt", "question", "instruction")))

        hf.seed_everything(spec.seed)
        report.status("running", "loading %s" % params["model_name"])
        sft = LLMSFTTrainer()
        device, _dtype, tokenizer, model, chat = sft._setup(
            params, spec, report, params["model_name"])
        reference = None
        if not params["lora"]:
            # A full fine-tune moves the weights the reference must keep.
            reference = copy.deepcopy(model).to(device).eval()
            for p in reference.parameters():
                p.requires_grad_(False)
        if params.get("gradient_checkpointing"):
            model.gradient_checkpointing_enable()
            if params["lora"]:
                model.enable_input_require_grads()
        model = hf.apply_lora(model, params["lora"], "CAUSAL_LM", report)
        model.to(device)
        pad = tokenizer.pad_token_id
        size = int(params["batch_size"])

        def encode(triples):
            return [{"c": self._encode(tokenizer, t, t["chosen"], params, chat),
                     "r": self._encode(tokenizer, t, t["rejected"], params, chat)}
                    for t in triples]

        train_pairs, val_pairs = encode(train), encode(val)
        model.eval()
        for pair, (rc, rr) in zip(train_pairs, self._reference_logps(
                model, reference, train_pairs, pad, device, size, report,
                "train")):
            pair["ref"] = (rc, rr)
        for pair, (rc, rr) in zip(val_pairs, self._reference_logps(
                model, reference, val_pairs, pad, device, size, report, "val")):
            pair["ref"] = (rc, rr)

        def batch_loss(batch):
            values = self._sequence_logps(
                model, [e for p in batch for e in (p["c"], p["r"])], pad, device)
            ref = torch.tensor([p["ref"] for p in batch], device=values.device,
                               dtype=values.dtype)
            return dpo_loss(values[0::2], values[1::2], ref[:, 0], ref[:, 1],
                            beta)

        def loss_of(batch):
            return batch_loss(batch)[0]

        selected = {"best": None, "saved": False}

        def on_epoch_end(epoch):
            if not val_pairs:
                return None
            total, right = 0.0, 0
            for start in range(0, len(val_pairs), size):
                batch = val_pairs[start:start + size]
                with torch.inference_mode():
                    loss, margin = batch_loss(batch)
                total += float(loss) * len(batch)
                right += int((margin > 0).sum())
            loss, accuracy = total / len(val_pairs), right / len(val_pairs)
            report.metric("val", "dpo_loss", loss, step=epoch + 1)
            report.metric("val", "preference_accuracy", accuracy, step=epoch + 1)
            report.log("info", "Val DPO loss %.4f, prefers the annotators' "
                               "choice on %.1f%%" % (loss, 100 * accuracy))
            if selected["best"] is None or -loss > selected["best"]:
                selected["best"] = -loss
                hf.save_model(model, tokenizer, spec.workdir)
                selected["saved"] = True
            return -loss

        report.log("info", "%d train and %d val preference pairs; beta %.3g; "
                           "prompts %s" % (len(train_pairs), len(val_pairs), beta,
                                           "use the chat template" if chat
                                           else "are plain text"))
        report.status("running", "preference tuning")
        summary = hf.train_loop(model, train_pairs, params, loss_of, report,
                                device=device, seed=spec.seed,
                                on_epoch_end=on_epoch_end)
        if not selected["saved"]:
            hf.save_model(model, tokenizer, spec.workdir)

        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "base_model": params["model_name"], "lora": params["lora"],
            "beta": beta, "instruction": str(params.get("instruction") or ""),
            "system_prompt": str(params.get("system_prompt") or ""),
            "chat": chat, "max_length": int(params["max_length"]),
            "device": device, "n_train": len(train_pairs),
            "bundle_digest": bundle.digest,
            "selected_epoch": summary["best_epoch"]})

        metrics = {"n_train": float(len(train_pairs)),
                   "train_seconds": summary["train_seconds"],
                   "epochs_run": float(summary["epochs_run"])}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        return FitResult(
            model_version="%s-%s-%s" % (self.name, schema.name, spec.run_id),
            artifact_paths=hf.artifact_files(spec.workdir), metrics=metrics,
            label_order=list(CHOICES), selected_on="val" if val_pairs else "")

    # ------------------------------------------------------------ predict

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        import os

        import torch

        card = hf.read_card(artifact_dir)
        params = {**self.default_params(), **{k: card[k] for k in (
            "instruction", "system_prompt", "max_length") if k in card},
            "chat_template": "always" if card.get("chat") else "never"}
        beta = float(card.get("beta", 0.1))
        sft = LLMSFTTrainer()
        device, _dtype, tokenizer, model, chat = sft._setup(
            params, spec, report, os.path.join(artifact_dir, hf.MODEL_DIR),
            artifact_dir=artifact_dir, card=card)
        reference = None
        if not card.get("lora"):
            _, _, _, reference, _ = sft._setup(params, spec, report,
                                               card["base_model"])
            reference.to(device).eval()
        model.eval()
        pad = tokenizer.pad_token_id

        # Both responses are on the bundle row; an item without two gets no
        # prediction.
        usable = [(item, item.data) for item in items
                  if len((item.data or {}).get("candidates") or []) >= 2]

        size = 4
        for start in range(0, len(usable), size):
            chunk = usable[start:start + size]
            examples = []
            for _item, row in chunk:
                pair = {"prompt": str(row.get("prompt") or "")}
                for response in row["candidates"][:2]:
                    examples.append(self._encode(tokenizer, pair, str(response),
                                                 params, chat))
            with torch.inference_mode():
                policy = self._sequence_logps(model, examples, pad, device)
                if reference is None:
                    with model.disable_adapter():
                        ref = self._sequence_logps(model, examples, pad, device)
                else:
                    ref = self._sequence_logps(reference, examples, pad, device)
            rewards = (beta * (policy - ref)).cpu().tolist()
            for n, (item, _row) in enumerate(chunk):
                margin = rewards[2 * n] - rewards[2 * n + 1]
                p_first = 1.0 / (1.0 + math.exp(-max(-50.0, min(50.0, margin))))
                label = "A" if margin >= 0 else "B"
                confidence = p_first if label == "A" else 1.0 - p_first
                yield PredictionRecord(
                    instance_id=item.instance_id, schema_name=card["schema"],
                    payload={"label": label, "confidence": round(confidence, 4)},
                    confidence=round(confidence, 4))
            report.progress("predict", start + len(chunk), len(usable))
            if report.should_stop():
                return
