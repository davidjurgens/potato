"""Supervised fine-tuning of an LLM on what annotators wrote.

For free-text schemes (``annotation_type: text``): a summary, a rewrite, a
rationale, a correction. Each labelled item becomes one example. The prompt
is the scheme's description (the question annotators were shown) followed by
the item's text, and the target is the agreed answer. The loss is computed on
the answer's tokens only, so the model learns to answer rather than to
reproduce prompts.

A LoRA adapter is trained by default, which is what lets a 0.5B–8B model
train on one GPU; ``lora: false`` trains every weight. Models with a chat
template (instruct models) are prompted through it, others with a plain
"instruction, text, answer" layout.

Model selection is on val loss, which costs one forward pass per val item.
The predictions the run publishes are generated, greedily, for the val, test
and unlabeled items, and the held-out score compares the generated text with
the annotators' (exact match and token F1). A prediction's confidence is the
model's mean probability for the tokens it generated, which is what the
review queue sorts by.
"""

from __future__ import annotations

import math
import os
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf

INSTALL_HINT = "pip install 'potato-annotation[train-llm]'"
_NEEDS = ("torch", "transformers", "peft")
DEFAULT_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"


def build_prompt(tokenizer, instruction: str, text: str, system: str,
                 chat: bool) -> str:
    """The prompt string, up to where the answer starts."""
    user = ("%s\n\n%s" % (instruction, text)).strip() if instruction else text
    if chat:
        messages = ([{"role": "system", "content": system}] if system else []) \
            + [{"role": "user", "content": user}]
        return tokenizer.apply_chat_template(messages, tokenize=False,
                                             add_generation_prompt=True)
    head = "%s\n\n" % system if system else ""
    return "%s%s\n\nAnswer: " % (head, user)


def encode_example(tokenizer, prompt: str, answer: Optional[str],
                   max_length: int) -> Dict[str, List[int]]:
    """Token ids and loss labels for one example.

    The prompt's labels are -100, so the loss covers the answer alone. When
    the pair is too long, the prompt loses tokens from the left, which keeps
    the instruction's end and the text nearest the answer. That beats losing
    the answer, which is the training signal.
    """
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    if answer is None:
        return {"input_ids": prompt_ids[-max_length:]}
    answer_ids = tokenizer(answer, add_special_tokens=False)["input_ids"]
    if tokenizer.eos_token_id is not None:
        answer_ids = answer_ids + [tokenizer.eos_token_id]
    # The answer may take everything but half the window, or what the prompt
    # needs if that is less.
    answer_ids = answer_ids[:max_length - min(len(prompt_ids), max_length // 2)]
    room = max_length - len(answer_ids)
    prompt_ids = prompt_ids[-room:] if room > 0 else []
    return {"input_ids": prompt_ids + answer_ids,
            "labels": [-100] * len(prompt_ids) + answer_ids}


def _dtype_keyword() -> str:
    """``dtype`` from transformers 4.56 on, ``torch_dtype`` before."""
    import transformers

    major, minor = (int(p) for p in transformers.__version__.split(".")[:2])
    return "dtype" if (major, minor) >= (4, 56) else "torch_dtype"


def _eos_ids(model, tokenizer) -> set:
    """Every token that ends an answer. An instruct model's generation config
    often lists more than the tokenizer's one (Qwen ends a turn with
    ``<|im_end|>`` and a document with ``<|endoftext|>``)."""
    ids = set()
    configured = getattr(getattr(model, "generation_config", None),
                         "eos_token_id", None)
    if isinstance(configured, int):
        ids.add(configured)
    elif configured:
        ids.update(int(i) for i in configured)
    if tokenizer.eos_token_id is not None:
        ids.add(int(tokenizer.eos_token_id))
    return ids


class LLMSFTTrainer(Trainer):
    name: ClassVar[str] = "llm-sft"
    description: ClassVar[str] = (
        "Fine-tunes an LLM, with a LoRA adapter by default, to write what "
        "annotators wrote in a text scheme.")
    kinds: ClassVar[Tuple[str, ...]] = ("text",)
    modalities: ClassVar[Tuple[str, ...]] = ("text",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "Apache-2.0"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": DEFAULT_MODEL, "epochs": 3, "batch_size": 4,
                "gradient_accumulation": 4, "learning_rate": None,
                "weight_decay": 0.0, "warmup_ratio": 0.05, "patience": 1,
                "precision": "auto", "lora": True, "max_length": 1024,
                "max_new_tokens": 256, "instruction": None,
                "system_prompt": "", "chat_template": "auto",
                "gradient_checkpointing": False, "min_instances": 20}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = dict(hf.COMMON_PARAMS)
        props["lora"] = dict(props["lora"], default=True)
        props["learning_rate"] = dict(
            props["learning_rate"], default=None,
            description="Defaults to 2e-4 with LoRA, 1e-5 without.")
        props.update({
            "model_name": {"type": "string", "default": DEFAULT_MODEL,
                           "description": "A causal LM on the Hugging Face "
                                          "hub, or a local path."},
            "max_length": {"type": "integer", "minimum": 32, "default": 1024,
                           "description": "Tokens per example, prompt and "
                                          "answer together."},
            "max_new_tokens": {"type": "integer", "minimum": 1,
                               "default": 256,
                               "description": "Longest generated answer."},
            "instruction": {
                "type": ["string", "null"], "default": None,
                "description": "Put before each item's text. Defaults to the "
                               "scheme's description, the question "
                               "annotators answered."},
            "system_prompt": {"type": "string", "default": ""},
            "chat_template": {
                "type": "string", "enum": ["auto", "always", "never"],
                "default": "auto",
                "description": "auto uses the tokenizer's chat template when "
                               "it has one."},
            "gradient_checkpointing": {
                "type": "boolean", "default": False,
                "description": "Recompute activations to save memory, at "
                               "about a third more time."},
        })
        return {"type": "object", "properties": props,
                "additionalProperties": False}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        problems = []
        if schema.kind != "text":
            problems.append("Schema %r is %s; this trainer learns free text."
                            % (schema.name, schema.kind))
        if bundle.split_size("train") < int(params["min_instances"]):
            problems.append(
                "Only %d items in the train split; this trainer needs at "
                "least %d. Annotate more, or lower min_instances."
                % (bundle.split_size("train"), int(params["min_instances"])))
        return problems

    # ------------------------------------------------------------- shared

    def _setup(self, params, spec, report, model_path: str,
               artifact_dir: Optional[str] = None, card=None):
        """Device, dtype, tokenizer, model and whether prompts are chat.

        *model_path* is where the tokenizer is (and the model, for a fresh
        fit). With a *card*, the fitted model is loaded from *artifact_dir*.
        """
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        device = hf.pick_device(spec, report)
        dtype = torch.float32
        if device.startswith("cuda") and params.get("precision") != "fp32" \
                and torch.cuda.is_bf16_supported():
            # Load in bf16: an 8B model is 32 GB in fp32 and 16 GB in bf16.
            dtype = torch.bfloat16
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        hf.ensure_pad_token(tokenizer)
        kwargs = {_dtype_keyword(): dtype}
        if card is None:
            model = AutoModelForCausalLM.from_pretrained(model_path, **kwargs)
        else:
            model = hf.load_pretrained(AutoModelForCausalLM, artifact_dir,
                                       card, device, **kwargs)
        if getattr(model.config, "pad_token_id", None) is None:
            model.config.pad_token_id = tokenizer.pad_token_id
        chat = {"always": True, "never": False}.get(
            params.get("chat_template", "auto"),
            bool(getattr(tokenizer, "chat_template", None)))
        return device, dtype, tokenizer, model, chat

    def _instruction(self, params, schema) -> str:
        instruction = params.get("instruction")
        return schema.description if instruction is None else str(instruction)

    # ----------------------------------------------------------------- fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch

        params = hf.merged_params(self.default_params(), spec)
        if params.get("learning_rate") is None:
            params["learning_rate"] = 2e-4 if params["lora"] else 1e-5
        schema = spec.primary_schema
        train = hf.rows_with_target(bundle.read_split("train"), schema.name)
        val = hf.rows_with_target(bundle.read_split("val"), schema.name)
        if not train:
            raise TrainerError("No written answers in the train split for %r"
                               % schema.name)

        hf.seed_everything(spec.seed)
        report.status("running", "loading %s" % params["model_name"])
        device, dtype, tokenizer, model, chat = self._setup(
            params, spec, report, params["model_name"])
        if params.get("gradient_checkpointing"):
            model.gradient_checkpointing_enable()
            if params["lora"]:
                model.enable_input_require_grads()
        model = hf.apply_lora(model, params["lora"], "CAUSAL_LM", report)
        model.to(device)

        instruction = self._instruction(params, schema)
        system = str(params.get("system_prompt") or "")
        max_length = int(params["max_length"])

        def examples(rows):
            return [encode_example(
                tokenizer, build_prompt(tokenizer, instruction,
                                        r.get("text", ""), system, chat),
                str(r["targets"][schema.name]), max_length) for r in rows]

        train_examples = examples(train)
        val_examples = examples(val)
        report.log("info", "%d train and %d val examples; prompts %s"
                   % (len(train_examples), len(val_examples),
                      "use the chat template" if chat else "are plain text"))

        pad = tokenizer.pad_token_id

        def collate(batch):
            width = max(len(e["input_ids"]) for e in batch)
            ids = torch.tensor([e["input_ids"] + [pad] * (width - len(e["input_ids"]))
                                for e in batch], device=device)
            mask = torch.tensor([[1] * len(e["input_ids"]) + [0] * (width - len(e["input_ids"]))
                                 for e in batch], device=device)
            labels = torch.tensor([e["labels"] + [-100] * (width - len(e["labels"]))
                                   for e in batch], device=device)
            return ids, mask, labels

        def loss_of(batch):
            ids, mask, labels = collate(batch)
            return model(input_ids=ids, attention_mask=mask,
                         labels=labels).loss

        selected = {"best": None, "saved": False}

        def val_loss() -> float:
            total, count = 0.0, 0
            import torch as _t
            for start in range(0, len(val_examples), int(params["batch_size"])):
                batch = val_examples[start:start + int(params["batch_size"])]
                ids, mask, labels = collate(batch)
                with _t.inference_mode():
                    loss = model(input_ids=ids, attention_mask=mask,
                                 labels=labels).loss
                n = int((labels != -100).sum())
                total += float(loss) * n
                count += n
            return total / max(count, 1)

        def on_epoch_end(epoch):
            if not val_examples:
                return None
            loss = val_loss()
            report.metric("val", "loss", loss, step=epoch + 1)
            report.log("info", "Val loss %.4f (perplexity %.2f)"
                       % (loss, math.exp(min(loss, 50))))
            if selected["best"] is None or -loss > selected["best"]:
                selected["best"] = -loss
                hf.save_model(model, tokenizer, spec.workdir)
                selected["saved"] = True
            return -loss

        report.status("running", "fine-tuning")
        summary = hf.train_loop(model, train_examples, params, loss_of, report,
                                device=device, seed=spec.seed,
                                on_epoch_end=on_epoch_end)
        if not selected["saved"]:
            hf.save_model(model, tokenizer, spec.workdir)

        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": "text",
            "base_model": params["model_name"], "lora": params["lora"],
            "instruction": instruction, "system_prompt": system, "chat": chat,
            "max_length": max_length,
            "max_new_tokens": int(params["max_new_tokens"]),
            "device": device, "n_train": len(train),
            "bundle_digest": bundle.digest,
            "selected_epoch": summary["best_epoch"]})

        metrics = {"n_train": float(len(train)),
                   "train_seconds": summary["train_seconds"],
                   "epochs_run": float(summary["epochs_run"])}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        if selected["best"] is not None:
            metrics["val_loss"] = round(-selected["best"], 4)
        return FitResult(
            model_version="%s-%s-%s" % (self.name, schema.name, spec.run_id),
            artifact_paths=hf.artifact_files(spec.workdir), metrics=metrics,
            selected_on="val" if val_examples else "")

    # ------------------------------------------------------------- predict

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch

        card = hf.read_card(artifact_dir)
        params = {"chat_template": "always" if card.get("chat") else "never",
                  "precision": "auto"}
        # The tokenizer saved beside the model or adapter is the one it was
        # trained with.
        device, _, tokenizer, model, chat = self._setup(
            params, spec, report, os.path.join(artifact_dir, hf.MODEL_DIR),
            artifact_dir=artifact_dir, card=card)
        model.to(device).eval()
        eos = _eos_ids(model, tokenizer)

        items = list(items)
        size = 8
        for start in range(0, len(items), size):
            chunk = items[start:start + size]
            prompts = [build_prompt(tokenizer, card.get("instruction", ""),
                                    item.text, card.get("system_prompt", ""),
                                    chat) for item in chunk]
            encoded = [encode_example(tokenizer, p, None,
                                      int(card.get("max_length", 1024)))
                       for p in prompts]
            width = max(len(e["input_ids"]) for e in encoded)
            pad = tokenizer.pad_token_id
            ids = torch.tensor([[pad] * (width - len(e["input_ids"])) + e["input_ids"]
                                for e in encoded], device=device)
            mask = torch.tensor([[0] * (width - len(e["input_ids"])) + [1] * len(e["input_ids"])
                                 for e in encoded], device=device)
            with torch.inference_mode():
                out = model.generate(
                    input_ids=ids, attention_mask=mask, do_sample=False,
                    max_new_tokens=int(card.get("max_new_tokens", 256)),
                    pad_token_id=pad, eos_token_id=sorted(eos),
                    output_scores=True, return_dict_in_generate=True)
            generated = out.sequences[:, width:]
            # Probability the model gave each token it chose.
            step_probs = torch.stack(
                [torch.softmax(s.float(), -1).gather(
                    1, generated[:, i:i + 1]).squeeze(1)
                 for i, s in enumerate(out.scores)], dim=1).cpu()
            for row, item in enumerate(chunk):
                tokens = generated[row].tolist()
                keep = next((i for i, t in enumerate(tokens) if t in eos),
                            len(tokens))
                text = tokenizer.decode(tokens[:keep],
                                        skip_special_tokens=True).strip()
                probs = step_probs[row, :max(keep, 1)]
                confidence = float(probs.mean()) if len(probs) else 0.0
                yield PredictionRecord(instance_id=item.instance_id,
                                       schema_name=card["schema"],
                                       payload=text,
                                       confidence=round(confidence, 4))
            report.progress("predict", start + len(chunk), len(items))
            if report.should_stop():
                return
