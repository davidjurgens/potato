"""Fine-tune a transformer to tag spans of text.

For ``span`` schemes. Each annotated span becomes BIO tags over the tokens it
covers, using the fast tokenizer's offset mapping, and a prediction is decoded
back into character offsets: the ``{start, end, label}`` dicts a span
prelabel renders from. Offsets are indexes into the item's text field, which
is what Potato's span annotations record for plain text.

A text longer than ``max_length`` tokens is cut into overlapping windows, in
training and in prediction, so a long document is tagged all the way through
rather than up to its first few hundred tokens. Where windows overlap, a
token's tag probabilities are averaged over them.

BIO cannot express two spans over the same characters. Where annotated spans
overlap, the longer one is kept and the run log counts the rest.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf

INSTALL_HINT = "pip install 'potato-annotation[train-text]'"
_NEEDS = ("torch", "transformers")
DEFAULT_MODEL = "distilbert/distilroberta-base"


def _span_label(span: Dict[str, Any]) -> str:
    return str(span.get("name") or span.get("label") or "")


def non_overlapping(spans: List[Dict[str, Any]]) -> Tuple[List[Tuple[int, int, str]], int]:
    """``(start, end, label)`` with overlaps removed, longest first; and how
    many were dropped."""
    parsed = []
    for span in spans or []:
        try:
            start, end = int(span["start"]), int(span["end"])
        except (KeyError, TypeError, ValueError):
            continue
        label = _span_label(span)
        if end > start and label:
            parsed.append((start, end, label))
    kept: List[Tuple[int, int, str]] = []
    for span in sorted(parsed, key=lambda s: (s[0] - s[1], s[0])):
        if all(span[1] <= k[0] or span[0] >= k[1] for k in kept):
            kept.append(span)
    return sorted(kept), len(parsed) - len(kept)


def bio_tags(offsets: List[Tuple[int, int]], spans: List[Tuple[int, int, str]],
             tag_index: Dict[str, int], special: List[bool]) -> List[int]:
    """One tag id per token; -100 for special tokens, which the loss skips."""
    tags = []
    previous_span = None
    for (a, b), is_special in zip(offsets, special):
        if is_special or a == b:
            tags.append(-100)
            previous_span = None
            continue
        inside = next((s for s in spans if s[0] <= a < s[1]), None)
        if inside is None:
            tags.append(tag_index["O"])
            previous_span = None
        else:
            prefix = "I" if inside == previous_span else "B"
            tags.append(tag_index["%s-%s" % (prefix, inside[2])])
            previous_span = inside
    return tags


def decode(token_offsets: List[Tuple[int, int]], token_probs: List[List[float]],
           tags: List[str]) -> List[Dict[str, Any]]:
    """BIO probabilities per token back into character spans.

    Lenient about a stray ``I-x`` with no ``B-x`` before it: it starts a span,
    as most taggers' decoders do, rather than being thrown away.
    """
    spans: List[Dict[str, Any]] = []
    current = None
    for (a, b), probs in zip(token_offsets, token_probs):
        best = max(range(len(probs)), key=probs.__getitem__)
        tag = tags[best]
        if tag == "O":
            current = None
            continue
        prefix, label = tag.split("-", 1)
        if prefix == "I" and current is not None and current["label"] == label:
            current["end"] = b
            current["_probs"].append(probs[best])
            continue
        current = {"start": a, "end": b, "label": label,
                   "_probs": [probs[best]]}
        spans.append(current)
    for span in spans:
        probs = span.pop("_probs")
        span["confidence"] = round(sum(probs) / len(probs), 4)
    return spans


class HFTokenClassificationTrainer(Trainer):
    name: ClassVar[str] = "hf-token-classification"
    description: ClassVar[str] = (
        "Fine-tunes a Hugging Face transformer to tag text spans (named "
        "entities, error spans, evidence).")
    kinds: ClassVar[Tuple[str, ...]] = ("span",)
    modalities: ClassVar[Tuple[str, ...]] = ("text",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "Apache-2.0"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": DEFAULT_MODEL, "epochs": 8, "batch_size": 8,
                "gradient_accumulation": 1, "learning_rate": None,
                "weight_decay": 0.01, "warmup_ratio": 0.1, "patience": 3,
                "precision": "auto", "lora": None, "max_length": 256,
                "stride": 64, "min_instances": 20}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = dict(hf.COMMON_PARAMS)
        props["learning_rate"] = dict(
            props["learning_rate"], default=None,
            description="Defaults to 5e-5, or 3e-4 with LoRA.")
        props.update({
            "model_name": {"type": "string", "default": DEFAULT_MODEL,
                           "description": "A Hugging Face model id or a "
                                          "local path. Needs a fast "
                                          "tokenizer."},
            "max_length": {"type": "integer", "minimum": 16, "default": 256,
                           "description": "Tokens per window."},
            "stride": {"type": "integer", "minimum": 0, "default": 64,
                       "description": "Tokens shared by neighbouring "
                                      "windows of a long text."},
        })
        return {"type": "object", "properties": props,
                "additionalProperties": False}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        problems = []
        if schema.kind != "span":
            problems.append("Schema %r is %s; this trainer tags spans."
                            % (schema.name, schema.kind))
        if bundle.split_size("train") < int(params["min_instances"]):
            problems.append(
                "Only %d items in the train split; this trainer needs at "
                "least %d. Annotate more, or lower min_instances."
                % (bundle.split_size("train"), int(params["min_instances"])))
        if not bundle.labels(schema.name):
            problems.append("Schema %r has no span labels in the data."
                            % schema.name)
        return problems

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
        labels = bundle.labels(schema.name)
        tags = ["O"] + ["%s-%s" % (p, label) for label in labels
                        for p in ("B", "I")]
        tag_index = {t: i for i, t in enumerate(tags)}

        train = hf.rows_with_target(bundle.read_split("train"), schema.name)
        val = hf.rows_with_target(bundle.read_split("val"), schema.name)
        if not train:
            raise TrainerError("No annotated spans in the train split for %r"
                               % schema.name)

        hf.seed_everything(spec.seed)
        device = hf.pick_device(spec, report)
        report.status("running", "loading %s" % params["model_name"])
        tokenizer = AutoTokenizer.from_pretrained(params["model_name"])
        if not getattr(tokenizer, "is_fast", False):
            raise TrainerError(
                "%s has no fast tokenizer, and span training needs one for "
                "its character offsets. Choose another model."
                % params["model_name"])
        model = AutoModelForTokenClassification.from_pretrained(
            params["model_name"], **self._head_kwargs(tags))
        hf.ensure_pad_token(tokenizer, model)
        model = hf.apply_lora(model, params["lora"], "TOKEN_CLS", report)
        model.to(device)

        windows, dropped = [], 0
        for row in train:
            spans, lost = non_overlapping(row["targets"][schema.name])
            dropped += lost
            for window in self._windows(tokenizer, row.get("text", ""), params):
                window["labels"] = bio_tags(window["offsets"], spans,
                                            tag_index, window["special"])
                windows.append(window)
        if dropped:
            report.log("warning", "Left out %d span(s) that overlap a longer "
                                  "one; BIO tags cannot hold both" % dropped)
        report.log("info", "%d train items in %d windows, %d val items, "
                           "%d span labels"
                   % (len(train), len(windows), len(val), len(labels)))

        def loss_of(batch):
            width = max(len(w["input_ids"]) for w in batch)
            pad = tokenizer.pad_token_id or 0
            ids = torch.tensor([w["input_ids"] + [pad] * (width - len(w["input_ids"]))
                                for w in batch], device=device)
            mask = torch.tensor([[1] * len(w["input_ids"]) + [0] * (width - len(w["input_ids"]))
                                 for w in batch], device=device)
            target = torch.tensor([w["labels"] + [-100] * (width - len(w["labels"]))
                                   for w in batch], device=device)
            return model(input_ids=ids, attention_mask=mask, labels=target).loss

        selected = {"best": None, "saved": False}

        def on_epoch_end(epoch):
            if not val:
                return None
            from potato.training.evaluation import score_split
            predictions = {
                (str(row.get("instance_id", "")), schema.name):
                    self._predict_text(model, tokenizer, row.get("text", ""),
                                       tags, params, device)[0]
                for row in val}
            metrics, _ = score_split(val, predictions, schema.name, "span")
            score = metrics.get("f1", 0.0)
            report.metric("val", "f1", score, step=epoch + 1)
            if selected["best"] is None or score > selected["best"]:
                selected["best"] = score
                hf.save_model(model, tokenizer, spec.workdir)
                selected["saved"] = True
            return score

        report.status("running", "fine-tuning")
        summary = hf.train_loop(model, windows, params, loss_of, report,
                                device=device, seed=spec.seed,
                                on_epoch_end=on_epoch_end)
        if not selected["saved"]:
            hf.save_model(model, tokenizer, spec.workdir)

        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": "span",
            "base_model": params["model_name"], "lora": params["lora"],
            "tags": tags, "label_order": labels,
            "max_length": int(params["max_length"]),
            "stride": int(params["stride"]), "device": device,
            "n_train": len(train), "bundle_digest": bundle.digest,
            "selected_epoch": summary["best_epoch"]})

        metrics = {"n_train": float(len(train)),
                   "n_windows": float(len(windows)),
                   "train_seconds": summary["train_seconds"],
                   "epochs_run": float(summary["epochs_run"])}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        return FitResult(
            model_version="%s-%s-%s" % (self.name, schema.name, spec.run_id),
            artifact_paths=hf.artifact_files(spec.workdir), metrics=metrics,
            label_order=labels, selected_on="val" if val else "")

    @staticmethod
    def _head_kwargs(tags: List[str]) -> Dict[str, Any]:
        return {"num_labels": len(tags),
                "id2label": {i: t for i, t in enumerate(tags)},
                "label2id": {t: i for i, t in enumerate(tags)},
                "ignore_mismatched_sizes": True}

    @staticmethod
    def _windows(tokenizer, text: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        enc = tokenizer(text, truncation=True, max_length=int(params["max_length"]),
                        stride=int(params["stride"]),
                        return_overflowing_tokens=True,
                        return_offsets_mapping=True,
                        return_special_tokens_mask=True)
        out = []
        for i in range(len(enc["input_ids"])):
            out.append({"input_ids": list(enc["input_ids"][i]),
                        "offsets": [tuple(o) for o in enc["offset_mapping"][i]],
                        "special": [bool(s) for s in
                                    enc["special_tokens_mask"][i]]})
        return out

    def _predict_text(self, model, tokenizer, text: str, tags: List[str],
                      params: Dict[str, Any], device: str):
        """``(spans, confidence)`` for one text."""
        import torch

        if not text:
            return [], None
        windows = self._windows(tokenizer, text, params)
        summed: Dict[Tuple[int, int], List[float]] = {}
        counts: Dict[Tuple[int, int], int] = defaultdict(int)
        for window in windows:
            ids = torch.tensor([window["input_ids"]], device=device)
            with torch.inference_mode():
                probs = torch.softmax(model(input_ids=ids).logits.float()[0],
                                      dim=-1).cpu().tolist()
            for offset, special, p in zip(window["offsets"], window["special"],
                                          probs):
                if special or offset[0] == offset[1]:
                    continue
                if offset in summed:
                    summed[offset] = [a + b for a, b in zip(summed[offset], p)]
                else:
                    summed[offset] = list(p)
                counts[offset] += 1
        order = sorted(summed)
        averaged = [[v / counts[o] for v in summed[o]] for o in order]
        spans = decode(order, averaged, tags)
        # The least certain token decides how much the item needs a look.
        confidence = min((max(p) for p in averaged), default=None)
        return spans, confidence

    # ------------------------------------------------------------- predict

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        import os

        from transformers import AutoModelForTokenClassification, AutoTokenizer

        card = hf.read_card(artifact_dir)
        tags = card["tags"]
        device = hf.pick_device(spec, report)
        tokenizer = AutoTokenizer.from_pretrained(
            os.path.join(artifact_dir, hf.MODEL_DIR))
        model = hf.load_pretrained(AutoModelForTokenClassification,
                                   artifact_dir, card, device,
                                   **self._head_kwargs(tags))
        params = {"max_length": card.get("max_length", 256),
                  "stride": card.get("stride", 64)}

        items = list(items)
        for n, item in enumerate(items):
            spans, confidence = self._predict_text(model, tokenizer, item.text,
                                                   tags, params, device)
            yield PredictionRecord(
                instance_id=item.instance_id, schema_name=card["schema"],
                payload=spans,
                confidence=None if confidence is None
                else round(float(confidence), 4))
            report.progress("predict", n + 1, len(items))
            if report.should_stop():
                return
