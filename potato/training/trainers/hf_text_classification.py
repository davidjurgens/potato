"""Fine-tune a Hugging Face transformer to classify text.

Any model ``AutoModelForSequenceClassification`` can load works: an encoder
such as RoBERTa or ModernBERT, and also a decoder LLM such as Qwen or Llama,
which transformers gives a classification head. ``lora: true`` trains a LoRA
adapter through peft instead of every weight, which is what makes a
0.5B–8B LLM fit on one GPU.

Multilabel schemes get one sigmoid output per label and binary cross-entropy;
a label is predicted when its probability reaches ``threshold``. Nominal and
ordinal schemes get a softmax over the labels. An ordinal scheme is treated as
nominal: its labels are categories here, and the held-out score reports mean
absolute error beside accuracy when they are numbers.

The checkpoint kept is the one that scored best on val, so the run's headline
score is taken from the test split, which the loop never sees.
"""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf

INSTALL_HINT = "pip install 'potato-annotation[train-text]'"
_NEEDS = ("torch", "transformers")
DEFAULT_MODEL = "distilbert/distilroberta-base"


class HFTextClassificationTrainer(Trainer):
    name: ClassVar[str] = "hf-text-classification"
    description: ClassVar[str] = (
        "Fine-tunes a Hugging Face transformer (an encoder, or an LLM with "
        "LoRA) to classify text.")
    kinds: ClassVar[Tuple[str, ...]] = ("nominal", "ordinal", "multilabel")
    modalities: ClassVar[Tuple[str, ...]] = ("text",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "Apache-2.0"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": DEFAULT_MODEL, "epochs": 5, "batch_size": 16,
                "gradient_accumulation": 1, "learning_rate": None,
                "weight_decay": 0.01, "warmup_ratio": 0.1, "patience": 2,
                "precision": "auto", "lora": None, "max_length": 256,
                "threshold": 0.5, "min_instances": 20}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = dict(hf.COMMON_PARAMS)
        props["learning_rate"] = dict(
            props["learning_rate"], default=None,
            description="Defaults to 3e-5, or 2e-4 with LoRA.")
        props.update({
            "model_name": {
                "type": "string", "default": DEFAULT_MODEL,
                "description": "A Hugging Face model id or a local path."},
            "max_length": {"type": "integer", "minimum": 8, "default": 256,
                           "description": "Tokens kept per item; the rest "
                                          "is cut."},
            "threshold": {"type": "number", "minimum": 0, "maximum": 1,
                          "default": 0.5,
                          "description": "Multilabel only: the probability "
                                         "at which a label is predicted."},
        })
        return {"type": "object", "properties": props,
                "additionalProperties": False}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = hf.merged_params(self.default_params(), spec)
        problems = []
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        if schema.kind not in self.kinds:
            problems.append("Schema %r is %s; this trainer handles %s."
                            % (schema.name, schema.kind, ", ".join(self.kinds)))
        n_train = bundle.split_size("train")
        if n_train < int(params["min_instances"]):
            problems.append(
                "Only %d items in the train split; this trainer needs at "
                "least %d. Annotate more, or lower min_instances."
                % (n_train, int(params["min_instances"])))
        if len(bundle.labels(schema.name)) < 2:
            problems.append("Schema %r has fewer than two labels in the data."
                            % schema.name)
        return problems

    # ----------------------------------------------------------------- fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch
        from transformers import (AutoModelForSequenceClassification,
                                  AutoTokenizer)

        params = hf.merged_params(self.default_params(), spec)
        if params.get("learning_rate") is None:
            params["learning_rate"] = 2e-4 if params["lora"] else 3e-5
        schema = spec.primary_schema
        multilabel = schema.kind == "multilabel"
        labels = bundle.labels(schema.name)
        index = {label: i for i, label in enumerate(labels)}

        train = hf.rows_with_target(bundle.read_split("train"), schema.name)
        val = hf.rows_with_target(bundle.read_split("val"), schema.name)
        if not train:
            raise TrainerError("No labelled rows in the train split for %r"
                               % schema.name)
        report.log("info", "%d train and %d val rows, %d labels"
                   % (len(train), len(val), len(labels)))

        hf.seed_everything(spec.seed)
        device = hf.pick_device(spec, report)
        report.status("running", "loading %s" % params["model_name"])
        tokenizer = AutoTokenizer.from_pretrained(params["model_name"])
        model = AutoModelForSequenceClassification.from_pretrained(
            params["model_name"], **self._head_kwargs(labels, multilabel))
        hf.ensure_pad_token(tokenizer, model)
        model = hf.apply_lora(model, params["lora"], "SEQ_CLS", report)
        model.to(device)

        def encode(rows):
            return tokenizer([r.get("text", "") for r in rows],
                             truncation=True, max_length=int(params["max_length"]),
                             padding=True, return_tensors="pt").to(device)

        def target_tensor(rows):
            if multilabel:
                out = torch.zeros(len(rows), len(labels))
                for i, row in enumerate(rows):
                    for label in row["targets"][schema.name]:
                        if str(label) in index:
                            out[i, index[str(label)]] = 1.0
                return out.to(device)
            return torch.tensor([index.get(str(r["targets"][schema.name]), 0)
                                 for r in rows], device=device)

        def loss_of(batch):
            return model(**encode(batch), labels=target_tensor(batch)).loss

        selected = {"saved": False}

        def on_epoch_end(epoch):
            if not val:
                return None
            score = self._score(model, tokenizer, val, schema, labels, params,
                                device)
            report.metric("val", hf_metric(schema.kind), score, step=epoch + 1)
            if selected.get("best") is None or score > selected["best"]:
                selected["best"] = score
                hf.save_model(model, tokenizer, spec.workdir)
                selected["saved"] = True
            return score

        report.status("running", "fine-tuning")
        summary = hf.train_loop(model, train, params, loss_of, report,
                                device=device, seed=spec.seed,
                                on_epoch_end=on_epoch_end)
        if not selected["saved"]:
            hf.save_model(model, tokenizer, spec.workdir)

        card = {"trainer": self.name, "schema": schema.name,
                "kind": schema.kind, "base_model": params["model_name"],
                "lora": params["lora"], "label_order": labels,
                "multilabel": multilabel, "threshold": float(params["threshold"]),
                "max_length": int(params["max_length"]), "device": device,
                "n_train": len(train), "bundle_digest": bundle.digest,
                "selected_epoch": summary["best_epoch"]}
        hf.write_card(spec.workdir, card)

        metrics = {"n_train": float(len(train)),
                   "train_seconds": summary["train_seconds"],
                   "epochs_run": float(summary["epochs_run"])}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        return FitResult(
            model_version="%s-%s-%s" % (self.name, schema.name, spec.run_id),
            artifact_paths=hf.artifact_files(spec.workdir), metrics=metrics,
            label_order=labels, selected_on="val" if val else "")

    @staticmethod
    def _head_kwargs(labels: List[str], multilabel: bool) -> Dict[str, Any]:
        kwargs = {"num_labels": len(labels),
                  "id2label": {i: label for i, label in enumerate(labels)},
                  "label2id": {label: i for i, label in enumerate(labels)},
                  # A checkpoint that already has a head of another size.
                  "ignore_mismatched_sizes": True}
        if multilabel:
            kwargs["problem_type"] = "multi_label_classification"
        return kwargs

    def _score(self, model, tokenizer, rows, schema, labels, params, device):
        from potato.training.evaluation import HEADLINE, score_split

        predictions = {}
        for row, payload, _ in self._predict_rows(
                model, tokenizer, rows, labels, schema.kind == "multilabel",
                params, device):
            predictions[(str(row.get("instance_id", "")), schema.name)] = payload
        metrics, _ = score_split(rows, predictions, schema.name, schema.kind)
        return metrics.get(HEADLINE[schema.kind], 0.0)

    def _predict_rows(self, model, tokenizer, rows, labels, multilabel,
                      params, device, report: Optional[ProgressReporter] = None):
        import torch

        size = max(1, int(params.get("batch_size", 16)))
        done = 0
        for start in range(0, len(rows), size):
            chunk = rows[start:start + size]
            texts = [r.get("text", "") if isinstance(r, dict) else r.text
                     for r in chunk]
            enc = tokenizer(texts, truncation=True,
                            max_length=int(params["max_length"]), padding=True,
                            return_tensors="pt").to(device)
            with torch.inference_mode():
                logits = model(**enc).logits.float()
            if multilabel:
                probs = torch.sigmoid(logits).cpu().tolist()
                threshold = float(params["threshold"])
                for row, p in zip(chunk, probs):
                    chosen = [{"label": labels[i], "confidence": round(v, 4)}
                              for i, v in enumerate(p) if v >= threshold]
                    # How sure the model is of its least certain yes-or-no.
                    confidence = min(max(v, 1 - v) for v in p)
                    yield row, chosen, confidence
            else:
                probs = torch.softmax(logits, dim=-1).cpu().tolist()
                for row, p in zip(chunk, probs):
                    best = max(range(len(p)), key=p.__getitem__)
                    yield row, {"label": labels[best],
                                "confidence": round(p[best], 4)}, p[best]
            done += len(chunk)
            if report is not None:
                report.progress("predict", done, len(rows))
                if report.should_stop():
                    return

    # ------------------------------------------------------------- predict

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        import os

        from transformers import (AutoModelForSequenceClassification,
                                  AutoTokenizer)

        card = hf.read_card(artifact_dir)
        labels = card["label_order"]
        multilabel = bool(card.get("multilabel"))
        device = hf.pick_device(spec, report)
        tokenizer = AutoTokenizer.from_pretrained(
            os.path.join(artifact_dir, hf.MODEL_DIR))
        model = hf.load_pretrained(
            AutoModelForSequenceClassification, artifact_dir, card, device,
            **self._head_kwargs(labels, multilabel))
        hf.ensure_pad_token(tokenizer, model)
        params = {"batch_size": 32, "max_length": card.get("max_length", 256),
                  "threshold": card.get("threshold", 0.5)}

        items = list(items)
        for item, payload, confidence in self._predict_rows(
                model, tokenizer, items, labels, multilabel, params, device,
                report):
            yield PredictionRecord(instance_id=item.instance_id,
                                   schema_name=card["schema"], payload=payload,
                                   confidence=round(float(confidence), 4))


def hf_metric(kind: str) -> str:
    from potato.training.evaluation import HEADLINE
    return HEADLINE.get(kind, "score")
