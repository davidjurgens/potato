"""Few-shot classification by the SetFit method.

SetFit (Tunstall et al., 2022, "Efficient Few-Shot Learning Without
Prompts") fine-tunes a sentence-transformer contrastively on pairs drawn from
the labelled examples -- two texts with the same label should embed close
together, two with different labels far apart -- and then fits a logistic
regression head on the tuned embeddings. Pairs grow quadratically with the
examples, which is why it works from eight or so per label: the regime a new
project is in on its first day.

This is an implementation of the method on sentence-transformers and
scikit-learn. It does not use the ``setfit`` package, which neither of the
hosts this was built against had installed, and whose releases have lagged
transformers majors.

Multilabel schemes pair texts by the Jaccard overlap of their label sets and
fit one logistic head per label.
"""

from __future__ import annotations

import os
import pickle
import random
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf

INSTALL_HINT = "pip install 'potato-annotation[embeddings]'"
_NEEDS = ("torch", "sentence_transformers", "sklearn")
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
HEAD_FILE = "head.pkl"


def make_pairs(texts: List[str], targets: List[Any], multilabel: bool,
               iterations: int, seed: int, limit: int
               ) -> List[Tuple[str, str, float]]:
    """``(text_a, text_b, similarity)`` pairs, SetFit's sampling.

    For each example and each iteration: one partner with the same label and
    one with a different label, when such partners exist. Multilabel targets
    are label sets, and a pair's similarity is their Jaccard overlap.
    """
    rng = random.Random(seed)
    n = len(texts)
    keys = [frozenset(t) if multilabel else t for t in targets]
    by_key: Dict[Any, List[int]] = {}
    for i, key in enumerate(keys):
        by_key.setdefault(key, []).append(i)

    def similarity(i: int, j: int) -> float:
        if not multilabel:
            return 1.0 if keys[i] == keys[j] else 0.0
        union = keys[i] | keys[j]
        return len(keys[i] & keys[j]) / len(union) if union else 1.0

    pairs = []
    for _ in range(iterations):
        for i in range(n):
            same = [j for j in by_key[keys[i]] if j != i]
            if same:
                j = rng.choice(same)
                pairs.append((texts[i], texts[j], similarity(i, j)))
            different = [j for j in range(n) if keys[j] != keys[i]]
            if different:
                j = rng.choice(different)
                pairs.append((texts[i], texts[j], similarity(i, j)))
    rng.shuffle(pairs)
    return pairs[:limit] if limit else pairs


class SetFitTrainer(Trainer):
    name: ClassVar[str] = "setfit"
    description: ClassVar[str] = (
        "Few-shot text classification by the SetFit method: contrastive "
        "fine-tuning of a sentence-transformer, then a logistic head. Works "
        "from about eight examples per label.")
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
        return {"model_name": DEFAULT_MODEL, "num_iterations": 20,
                "max_pairs": 20000, "epochs": 1, "batch_size": 16,
                "learning_rate": 2e-5, "weight_decay": 0.01,
                "warmup_ratio": 0.1, "precision": "auto", "threshold": 0.5,
                "min_instances": 8}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = {key: hf.COMMON_PARAMS[key] for key in
                 ("epochs", "batch_size", "weight_decay", "warmup_ratio",
                  "precision")}
        props["epochs"] = dict(props["epochs"], default=1,
                               description="Passes over the generated pairs.")
        props.update({
            "model_name": {"type": "string", "default": DEFAULT_MODEL,
                           "description": "A sentence-transformers model id "
                                          "or a local path."},
            "num_iterations": {
                "type": "integer", "minimum": 1, "default": 20,
                "description": "Pairs drawn per example: this many with the "
                               "same label and this many with another."},
            "max_pairs": {"type": "integer", "minimum": 0, "default": 20000,
                          "description": "Cap on pairs; 0 for none."},
            "learning_rate": {"type": "number", "exclusiveMinimum": 0,
                              "default": 2e-5},
            "threshold": {"type": "number", "minimum": 0, "maximum": 1,
                          "default": 0.5,
                          "description": "Multilabel only."},
            "min_instances": {"type": "integer", "minimum": 2, "default": 8},
        })
        return {"type": "object", "properties": props,
                "additionalProperties": False}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = {**self.default_params(), **(spec.params or {})}
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        problems = []
        if schema.kind not in self.kinds:
            problems.append("Schema %r is %s; this trainer handles %s."
                            % (schema.name, schema.kind, ", ".join(self.kinds)))
        if bundle.split_size("train") < int(params["min_instances"]):
            problems.append(
                "Only %d items in the train split; this trainer needs at "
                "least %d. Annotate more, or lower min_instances."
                % (bundle.split_size("train"), int(params["min_instances"])))
        if len(bundle.labels(schema.name)) < 2:
            problems.append("Schema %r has fewer than two labels in the data."
                            % schema.name)
        return problems

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch
        from sentence_transformers import SentenceTransformer

        params = {**self.default_params(), **(spec.params or {})}
        params["lora"] = None
        schema = spec.primary_schema
        multilabel = schema.kind == "multilabel"
        labels = bundle.labels(schema.name)

        train = hf.rows_with_target(bundle.read_split("train"), schema.name)
        if not train:
            raise TrainerError("No labelled rows in the train split for %r"
                               % schema.name)
        texts = [r.get("text", "") for r in train]
        targets = [([str(t) for t in r["targets"][schema.name]] if multilabel
                    else str(r["targets"][schema.name])) for r in train]

        hf.seed_everything(spec.seed)
        device = hf.pick_device(spec, report)
        report.status("running", "loading %s" % params["model_name"])
        body = SentenceTransformer(params["model_name"], device=device)

        pairs = make_pairs(texts, targets, multilabel,
                           int(params["num_iterations"]), spec.seed,
                           int(params["max_pairs"] or 0))
        report.log("info", "%d train rows, %d labels: %d contrastive pairs"
                   % (len(train), len(labels), len(pairs)))

        def embed(batch_texts):
            # `preprocess` from sentence-transformers 5.5, which deprecates
            # `tokenize`; 5.5 also adds a "modality" string to the features,
            # so only tensors are moved to the device.
            prepare = getattr(body, "preprocess", None) or body.tokenize
            features = {k: v.to(device) if hasattr(v, "to") else v
                        for k, v in prepare(batch_texts).items()}
            return body(features)["sentence_embedding"]

        def loss_of(batch):
            a = embed([p[0] for p in batch])
            b = embed([p[1] for p in batch])
            target = torch.tensor([p[2] for p in batch], device=device,
                                  dtype=a.dtype)
            cosine = torch.nn.functional.cosine_similarity(a, b)
            return torch.nn.functional.mse_loss(cosine, target)

        report.status("running", "contrastive fine-tuning")
        params["patience"] = None
        summary = hf.train_loop(body, pairs, params, loss_of, report,
                                device=device, seed=spec.seed)

        report.status("running", "fitting the head")
        embeddings = body.encode(texts, batch_size=32, convert_to_numpy=True,
                                 show_progress_bar=False)
        head = self._fit_head(embeddings, targets, labels, multilabel, spec.seed)

        os.makedirs(spec.workdir, exist_ok=True)
        body.save(os.path.join(spec.workdir, hf.MODEL_DIR))
        with open(os.path.join(spec.workdir, HEAD_FILE), "wb") as fh:
            pickle.dump(head, fh)
        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "base_model": params["model_name"], "label_order": labels,
            "multilabel": multilabel, "threshold": float(params["threshold"]),
            "n_train": len(train), "n_pairs": len(pairs), "device": device,
            "bundle_digest": bundle.digest})

        metrics = {"n_train": float(len(train)), "n_pairs": float(len(pairs)),
                   "train_seconds": summary["train_seconds"]}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        return FitResult(
            model_version="%s-%s-%s" % (self.name, schema.name, spec.run_id),
            artifact_paths=hf.artifact_files(spec.workdir), metrics=metrics,
            label_order=labels)

    @staticmethod
    def _fit_head(embeddings, targets, labels, multilabel: bool, seed: int):
        from sklearn.linear_model import LogisticRegression

        if not multilabel:
            head = LogisticRegression(max_iter=1000, random_state=seed)
            head.fit(embeddings, targets)
            return {"multilabel": False, "model": head}
        heads = {}
        for label in labels:
            y = [1 if label in t else 0 for t in targets]
            if len(set(y)) < 2:
                # Every example has it, or none does: a constant, not a model.
                heads[label] = float(y[0]) if y else 0.0
                continue
            model = LogisticRegression(max_iter=1000, random_state=seed)
            model.fit(embeddings, y)
            heads[label] = model
        return {"multilabel": True, "models": heads}

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        from sentence_transformers import SentenceTransformer

        card = hf.read_card(artifact_dir)
        device = hf.pick_device(spec, report)
        body = SentenceTransformer(os.path.join(artifact_dir, hf.MODEL_DIR),
                                   device=device)
        with open(os.path.join(artifact_dir, HEAD_FILE), "rb") as fh:
            head = pickle.load(fh)

        items = list(items)
        for start in range(0, len(items), 256):
            chunk = items[start:start + 256]
            embeddings = body.encode([i.text for i in chunk], batch_size=32,
                                     convert_to_numpy=True,
                                     show_progress_bar=False)
            for item, payload, confidence in self._apply_head(
                    head, embeddings, chunk, card):
                yield PredictionRecord(instance_id=item.instance_id,
                                       schema_name=card["schema"],
                                       payload=payload,
                                       confidence=round(float(confidence), 4))
            report.progress("predict", start + len(chunk), len(items))
            if report.should_stop():
                return

    @staticmethod
    def _apply_head(head, embeddings, chunk, card):
        if not head["multilabel"]:
            model = head["model"]
            classes = [str(c) for c in model.classes_]
            for item, row in zip(chunk, model.predict_proba(embeddings)):
                best = int(row.argmax())
                yield item, {"label": classes[best],
                             "confidence": round(float(row[best]), 4)}, row[best]
            return
        threshold = float(card.get("threshold", 0.5))
        columns = {}
        for label, model in head["models"].items():
            if isinstance(model, float):
                columns[label] = [model] * len(chunk)
            else:
                columns[label] = model.predict_proba(embeddings)[:, 1].tolist()
        for n, item in enumerate(chunk):
            probs = {label: col[n] for label, col in columns.items()}
            chosen = [{"label": label, "confidence": round(p, 4)}
                      for label, p in probs.items() if p >= threshold]
            confidence = min((max(p, 1 - p) for p in probs.values()),
                             default=0.0)
            yield item, chosen, confidence
