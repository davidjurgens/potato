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

**Learning from disagreement.** With ``soft_targets: true``, an item two or
more annotators labelled trains toward their vote split (two of three said
positive: 0.67 positive, 0.33 negative) rather than the one label the vote
kept, by cross-entropy against that distribution; a multilabel item trains
each label toward the share of annotators who ticked it. Items with one
annotator train on their label as before. A ``soft_label`` scheme, where each
annotator gives a distribution, always trains this way, toward the
annotators' mean, and predicts a distribution. Predictions carry the model's
probabilities, so the held-out score reports how far they are from the
annotators' distribution (``soft_jsd``) and expected calibration error.

**Choosing what to ask next.** ``acquisition`` (margin, entropy, bald,
coreset) writes a score on each prediction that ``llm_confidence``
assignment orders by, highest first, instead of by confidence; see
``potato.training.acquisition``. Single-label schemes only.
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
DEFAULT_MODEL = "distilbert/distilroberta-base"


class HFTextClassificationTrainer(Trainer):
    name: ClassVar[str] = "hf-text-classification"
    description: ClassVar[str] = (
        "Fine-tunes a Hugging Face transformer (an encoder, or an LLM with "
        "LoRA) to classify text.")
    kinds: ClassVar[Tuple[str, ...]] = ("nominal", "ordinal", "multilabel",
                                        "distribution")
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
                "threshold": 0.5, "soft_targets": False,
                "acquisition": "least_confident", "mc_samples": 10,
                "min_instances": 20}

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
            "acquisition": {"type": "string",
                            "enum": ["least_confident", "margin", "entropy",
                                     "bald", "coreset"],
                            "default": "least_confident",
                            "description": "How llm_confidence assignment "
                                           "orders items: by confidence "
                                           "(least_confident), or by a score "
                                           "written on each prediction."},
            "mc_samples": {"type": "integer", "minimum": 2, "maximum": 100,
                           "default": 10,
                           "description": "acquisition: bald only. Forward "
                                          "passes with dropout on."},
            "soft_targets": {"type": "boolean", "default": False,
                             "description": "Train items with two or more "
                                            "annotators toward their vote "
                                            "split instead of the voted "
                                            "label. Always on for "
                                            "soft_label schemes."},
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
        if params.get("acquisition", "least_confident") != "least_confident" \
                and schema.kind in ("multilabel", "distribution"):
            problems.append("acquisition: %s needs a single-label scheme; %r is %s."
                            % (params["acquisition"], schema.name, schema.kind))
        problems.extend(hf.quantize_problems(params, spec))
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
        distribution = schema.kind == "distribution"
        soft = distribution or bool(params.get("soft_targets"))
        labels = bundle.labels(schema.name)
        index = {label: i for i, label in enumerate(labels)}

        train = hf.rows_with_target(bundle.read_split("train"), schema.name)
        val = hf.rows_with_target(bundle.read_split("val"), schema.name)
        if not train:
            raise TrainerError("No labelled rows in the train split for %r"
                               % schema.name)
        report.log("info", "%d train and %d val rows, %d labels"
                   % (len(train), len(val), len(labels)))
        if soft and not distribution:
            n_soft = sum(1 for r in train if schema.name in (r.get("soft_targets") or {}))
            report.log("info", "Soft targets: %d of %d train items have two or "
                               "more annotators" % (n_soft, len(train)))

        hf.seed_everything(spec.seed)
        device = hf.pick_device(spec, report)
        report.status("running", "loading %s" % params["model_name"])
        tokenizer = AutoTokenizer.from_pretrained(params["model_name"])
        model = AutoModelForSequenceClassification.from_pretrained(
            params["model_name"], **self._head_kwargs(labels, multilabel),
            **hf.quantization_kwargs(params["lora"]))
        hf.ensure_pad_token(tokenizer, model)
        model = hf.prepare_quantized(model, params, report)
        model = hf.apply_lora(model, params["lora"], "SEQ_CLS", report)
        model = hf.place(model, device)

        def encode(rows):
            return tokenizer([r.get("text", "") for r in rows],
                             truncation=True, max_length=int(params["max_length"]),
                             padding=True, return_tensors="pt").to(device)

        def target_tensor(rows):
            if multilabel:
                out = torch.zeros(len(rows), len(labels))
                for i, row in enumerate(rows):
                    shares = (row.get("soft_targets") or {}).get(schema.name) \
                        if soft else None
                    if shares:
                        for label, share in shares.items():
                            if str(label) in index:
                                out[i, index[str(label)]] = float(share)
                        continue
                    for label in row["targets"][schema.name]:
                        if str(label) in index:
                            out[i, index[str(label)]] = 1.0
                return out.to(device)
            return torch.tensor([index.get(str(r["targets"][schema.name]), 0)
                                 for r in rows], device=device)

        def soft_tensor(rows):
            """Each row's label distribution: its soft target, the scheme's
            own distribution, or its one label."""
            out = torch.zeros(len(rows), len(labels))
            for i, row in enumerate(rows):
                target = row["targets"][schema.name]
                shares = target if distribution else \
                    (row.get("soft_targets") or {}).get(schema.name)
                if shares:
                    for label, share in shares.items():
                        if str(label) in index:
                            out[i, index[str(label)]] = float(share)
                    out[i] /= out[i].sum().clamp(min=1e-9)
                else:
                    out[i, index.get(str(target), 0)] = 1.0
            return out.to(device)

        def loss_of(batch):
            if soft and not multilabel:
                logits = model(**encode(batch)).logits.float()
                return -(soft_tensor(batch)
                         * torch.log_softmax(logits, dim=-1)).sum(-1).mean()
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
                "multilabel": multilabel, "distribution": distribution,
                "soft_targets": soft, "threshold": float(params["threshold"]),
                "acquisition": params.get("acquisition", "least_confident"),
                "mc_samples": int(params.get("mc_samples", 10)),
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
                params, device, distribution=schema.kind == "distribution"):
            predictions[(str(row.get("instance_id", "")), schema.name)] = payload
        metrics, _ = score_split(rows, predictions, schema.name, schema.kind)
        return metrics.get(HEADLINE[schema.kind], 0.0)

    def _predict_rows(self, model, tokenizer, rows, labels, multilabel,
                      params, device, report: Optional[ProgressReporter] = None,
                      distribution: bool = False):
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
                    shares = {labels[i]: round(v, 4) for i, v in enumerate(p)}
                    payload = {"label": labels[best],
                               "confidence": round(p[best], 4),
                               # The whole distribution: what soft-target
                               # scoring compares, and a soft label's answer.
                               "probabilities": shares}
                    if distribution:
                        payload["distribution"] = shares
                    yield row, payload, p[best]
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
        results = list(self._predict_rows(
            model, tokenizer, items, labels, multilabel, params, device,
            report, distribution=bool(card.get("distribution"))))
        method = card.get("acquisition") or "least_confident"
        if method != "least_confident" and not multilabel:
            scores = self._acquisition(method, model, tokenizer, spec, card,
                                       [r[0] for r in results],
                                       [r[1] for r in results], params, device,
                                       report)
            for (_, payload, _), score in zip(results, scores):
                payload["acquisition"] = round(float(score), 6)
        for item, payload, confidence in results:
            yield PredictionRecord(instance_id=item.instance_id,
                                   schema_name=card["schema"], payload=payload,
                                   confidence=round(float(confidence), 4))

    def _acquisition(self, method, model, tokenizer, spec, card, items, payloads,
                     params, device, report=None) -> List[float]:
        """One acquisition score per predicted item."""
        import torch

        from potato.training import acquisition
        if method == "bald" and not acquisition.has_dropout(model):
            if report is not None:
                report.log("warning", "acquisition: bald needs dropout, and this "
                                      "model has none; scored by entropy instead")
            method = "entropy"

        texts = [getattr(i, "text", "") or "" for i in items]
        if method in ("margin", "entropy"):
            return acquisition.scores_for(
                method, probabilities=[list(p["probabilities"].values()) for p in payloads])

        def batches(values):
            size = max(1, int(params.get("batch_size", 32)))
            for start in range(0, len(values), size):
                yield tokenizer(values[start:start + size], truncation=True,
                                max_length=int(params["max_length"]), padding=True,
                                return_tensors="pt").to(device)

        if method == "bald":
            samples = acquisition.mc_dropout(
                model, lambda enc: torch.softmax(model(**enc).logits.float(), -1).cpu().tolist(),
                lambda: batches(texts), int(card.get("mc_samples", 10)))
            return acquisition.scores_for("bald", samples=samples)

        # coreset: the encoder's first-token state, for the predicted items
        # and for the items the model was trained on.
        def embed(values):
            out = []
            with torch.inference_mode():
                for enc in batches(values):
                    states = model(**enc, output_hidden_states=True).hidden_states[-1]
                    out.extend(states[:, 0].float().cpu().tolist())
            return out

        train = [r.get("text", "") for r in
                 BundleRef.load(spec.bundle_dir).read_split("train")] \
            if spec.bundle_dir and os.path.isdir(spec.bundle_dir) else []
        return acquisition.scores_for("coreset", embeddings=embed(texts),
                                      labelled=embed(train) if train else [])


def hf_metric(kind: str) -> str:
    from potato.training.evaluation import HEADLINE
    return HEADLINE.get(kind, "score")
