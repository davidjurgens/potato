"""A scalar reward model, from which-is-better answers.

DPO (``llm-dpo``) trains a policy from preferences. Many projects want the
reward model itself: a function from a response to a number, for RLHF, for
best-of-n sampling, or to rank new outputs. This trainer fits one from every
kind of comparative answer Potato collects:

==================  =====================================================
pairwise (binary)   the chosen response beats the other; ties are skipped
pairwise (scale)    the side the slider leans to wins, weighted by how far
ranking             Plackett-Luce over the whole order (or its pairs)
bws                 the best item beats every other, every other beats the
                    worst
==================  =====================================================

The model is a transformer with a one-output head: an encoder, or an LLM
with ``lora``. The loss is Bradley-Terry, ``-log sigmoid(r_win - r_lose)``,
which is the reward-modelling loss of InstructGPT; Plackett-Luce is its
generalization to a full order. When an item carries a prompt
(``prompt``, ``question``, ...), the reward is of the response given the
prompt; a ranking's options are scored given the item's text.

Predictions answer the scheme's own question, so they are scored and written
back like any other: the preferred letter, the order, the best and worst, or
a point on the scale. Each also carries the rewards it came from.
"""

from __future__ import annotations

import math
import os
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf

INSTALL_HINT = "pip install 'potato-annotation[train-text]'"
_NEEDS = ("torch", "transformers")
DEFAULT_MODEL = "distilbert/distilroberta-base"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _letter(index: int) -> str:
    return LETTERS[index] if 0 <= index < len(LETTERS) else str(index)


def _index(letter: Any) -> Optional[int]:
    text = str(letter or "").strip().upper()
    return LETTERS.index(text) if len(text) == 1 and text in LETTERS else None


def options_of(kind: str, row: Dict[str, Any], labels: List[str]
               ) -> Tuple[str, List[str]]:
    """``(context, options)``: what each reward is conditioned on, and the
    texts being compared, in the order the answer's letters or names refer
    to."""
    if kind == "ranking":
        return str(row.get("text") or ""), list(labels)
    return str(row.get("prompt") or ""), [str(c) for c in row.get("candidates") or []]


def comparisons(kind: str, row: Dict[str, Any], schema: str, labels: List[str],
                scale_max: float = 3.0, listwise: bool = True) -> List[Dict[str, Any]]:
    """The training units one row yields.

    A unit is ``{"context", "order": [option texts, best first],
    "weight"}``: two options for a pair, the whole list for a Plackett-Luce
    ranking. An answer that says nothing about order (a tie, a scale at its
    midpoint) yields none.
    """
    target = (row.get("targets") or {}).get(schema)
    context, options = options_of(kind, row, labels)
    if target is None or not options:
        return []
    if kind == "preference":
        choice = str(target)
        if choice not in ("A", "B") or len(options) < 2:
            return []
        first, second = options[0], options[1]
        order = [first, second] if choice == "A" else [second, first]
        return [{"context": context, "order": order, "weight": 1.0}]
    if kind == "preference_scale":
        try:
            value = float(target)
        except (TypeError, ValueError):
            return []
        if value == 0 or len(options) < 2:
            return []
        order = [options[0], options[1]] if value < 0 else [options[1], options[0]]
        # A slider pushed all the way says more than one nudged off centre.
        weight = min(1.0, abs(value) / scale_max) if scale_max else 1.0
        return [{"context": context, "order": order, "weight": weight}]
    if kind == "ranking":
        from potato.server_utils.iaa.dispatcher import rank_tiers
        known = set(options)
        tiers = [[m for m in tier if m in known] for tier in rank_tiers(target)]
        tiers = [tier for tier in tiers if tier]
        if len(tiers) < 2:
            return []
        if listwise and all(len(tier) == 1 for tier in tiers):
            return [{"context": context, "order": [t[0] for t in tiers], "weight": 1.0}]
        # Plackett-Luce has no tie, so a ranking with one trains on its
        # pairs, and two tied items are not a pair.
        return [{"context": context, "order": [a, b], "weight": 1.0}
                for i in range(len(tiers)) for later in tiers[i + 1:]
                for a in tiers[i] for b in later]
    if kind == "bws":
        best, worst = _index(target.get("best")), _index(target.get("worst"))
        if best is None or worst is None or best == worst \
                or max(best, worst) >= len(options):
            return []
        units = []
        for n, option in enumerate(options):
            if n != best:
                units.append({"context": context, "order": [options[best], option],
                              "weight": 1.0})
            if n not in (best, worst):
                units.append({"context": context, "order": [option, options[worst]],
                              "weight": 1.0})
        return units
    return []


def answer_from_rewards(kind: str, rewards: List[float], options: List[str],
                        scale: Tuple[float, float] = (-3.0, 3.0)
                        ) -> Tuple[Any, float]:
    """The scheme's answer from the options' rewards, and a confidence.

    The confidence is the Bradley-Terry probability of the least certain
    comparison the answer makes: A over B for a pair, the top two for a
    ranking, best over runner-up and worst under the one above it for BWS.
    """
    def sigmoid(x):
        return 1.0 / (1.0 + math.exp(-x))

    rounded = [round(float(r), 4) for r in rewards]
    if kind in ("preference", "preference_scale"):
        gap = rewards[1] - rewards[0]        # positive: B is better
        if kind == "preference":
            label = "B" if gap > 0 else "A"
            return ({"label": label, "confidence": round(sigmoid(abs(gap)), 4),
                     "rewards": rounded}, sigmoid(abs(gap)))
        low, high = scale
        reach = max(abs(low), abs(high)) or 1.0
        value = max(low, min(high, round(reach * math.tanh(gap))))
        return ({"value": value, "rewards": rounded}, sigmoid(abs(gap)))
    ranked = sorted(range(len(rewards)), key=lambda i: rewards[i], reverse=True)
    if kind == "ranking":
        order = [options[i] for i in ranked]
        confidence = sigmoid(rewards[ranked[0]] - rewards[ranked[1]]) \
            if len(ranked) > 1 else 1.0
        return ({"order": order, "rewards": dict(zip(options, rounded))},
                confidence)
    # bws
    best, worst = ranked[0], ranked[-1]
    confidence = 1.0
    if len(ranked) > 1:
        confidence = min(sigmoid(rewards[best] - rewards[ranked[1]]),
                         sigmoid(rewards[ranked[-2]] - rewards[worst]))
    return ({"best": _letter(best), "worst": _letter(worst),
             "rewards": rounded}, confidence)


class RewardModelTrainer(Trainer):
    name: ClassVar[str] = "reward-model"
    description: ClassVar[str] = (
        "A scalar reward model (Bradley-Terry / Plackett-Luce) from pairwise, "
        "ranking and best-worst answers.")
    kinds: ClassVar[Tuple[str, ...]] = ("preference", "preference_scale",
                                        "ranking", "bws")
    modalities: ClassVar[Tuple[str, ...]] = ("text",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "Apache-2.0"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def server_params(cls, config, schema_names, params):
        # A scale prediction is a point on the scheme's own slider.
        for scheme in config.get("annotation_schemes", []) or []:
            if scheme.get("name") == (schema_names[0] if schema_names else None):
                scale = scheme.get("scale") or {}
                try:
                    return {"_scale": [float(scale.get("min", -3)),
                                       float(scale.get("max", 3))]}
                except (TypeError, ValueError):
                    return {}
        return {}

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": DEFAULT_MODEL, "epochs": 5, "batch_size": 8,
                "gradient_accumulation": 1, "learning_rate": None,
                "weight_decay": 0.01, "warmup_ratio": 0.1, "patience": 2,
                "precision": "auto", "lora": None, "max_length": 512,
                "ranking_loss": "plackett_luce", "min_instances": 20}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = dict(hf.COMMON_PARAMS)
        props["learning_rate"] = dict(
            props["learning_rate"], default=None,
            description="Defaults to 2e-5, or 2e-4 with LoRA.")
        props["batch_size"] = dict(props["batch_size"], default=8)
        props.update({
            "model_name": {"type": "string", "default": DEFAULT_MODEL,
                           "description": "A Hugging Face model id or a local "
                                          "path."},
            "max_length": {"type": "integer", "minimum": 8, "default": 512,
                           "description": "Tokens per scored text (prompt "
                                          "and response together)."},
            "ranking_loss": {"type": "string",
                             "enum": ["plackett_luce", "pairs"],
                             "default": "plackett_luce",
                             "description": "Ranking schemes: the listwise "
                                            "loss over the whole order, or "
                                            "Bradley-Terry over every pair "
                                            "in it."},
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
            problems.append("Schema %r is %s; this trainer handles %s."
                            % (schema.name, schema.kind, ", ".join(self.kinds)))
            return problems
        labels = bundle.labels(schema.name)
        units = [u for row in bundle.read_split("train")
                 for u in comparisons(schema.kind, row, schema.name, labels)]
        if not units:
            problems.append(
                "No usable comparisons in the train split for %r: every "
                "answer is a tie, or the items have no candidates."
                % schema.name)
        n_train = bundle.split_size("train")
        if n_train < int(params["min_instances"]):
            problems.append(
                "Only %d items in the train split; this trainer needs at "
                "least %d. Annotate more, or lower min_instances."
                % (n_train, int(params["min_instances"])))
        problems.extend(hf.quantize_problems(params, spec))
        return problems

    # ----------------------------------------------------------------- fit

    def _rewards(self, model, tokenizer, contexts: List[str], texts: List[str],
                 params: Dict[str, Any], device: str):
        """One reward per (context, text), as a 1-D tensor."""
        size = int(params["max_length"])
        if any(contexts):
            enc = tokenizer(contexts, texts, truncation="longest_first",
                            max_length=size, padding=True, return_tensors="pt")
        else:
            enc = tokenizer(texts, truncation=True, max_length=size,
                            padding=True, return_tensors="pt")
        return model(**enc.to(device)).logits.float().squeeze(-1)

    def _loss(self, model, tokenizer, batch, params, device):
        import torch
        import torch.nn.functional as F

        contexts, texts, spans = [], [], []
        for unit in batch:
            start = len(texts)
            for text in unit["order"]:
                contexts.append(unit["context"])
                texts.append(text)
            spans.append((start, len(texts), float(unit["weight"])))
        rewards = self._rewards(model, tokenizer, contexts, texts, params, device)
        losses = []
        for start, end, weight in spans:
            scores = rewards[start:end]
            if end - start == 2:
                losses.append(-weight * F.logsigmoid(scores[0] - scores[1]))
                continue
            # Plackett-Luce: each item in turn is chosen from those left.
            terms = [scores[i] - torch.logsumexp(scores[i:], dim=0)
                     for i in range(len(scores) - 1)]
            losses.append(-weight * torch.stack(terms).sum())
        return torch.stack(losses).mean()

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        params = hf.merged_params(self.default_params(), spec)
        if params.get("learning_rate") is None:
            params["learning_rate"] = 2e-4 if params["lora"] else 2e-5
        schema = spec.primary_schema
        labels = bundle.labels(schema.name)
        scale = tuple(params.get("_scale") or (-3.0, 3.0))
        reach = max(abs(scale[0]), abs(scale[1])) or 1.0
        listwise = params["ranking_loss"] == "plackett_luce"

        train_rows = list(bundle.read_split("train"))
        val = [r for r in bundle.read_split("val")
               if (r.get("targets") or {}).get(schema.name) is not None]
        units = [u for row in train_rows for u in comparisons(
            schema.kind, row, schema.name, labels, reach, listwise)]
        if not units:
            raise TrainerError("No usable comparisons in the train split for %r"
                               % schema.name)
        report.log("info", "%d comparisons from %d train items, %d val items"
                   % (len(units), len(train_rows), len(val)))

        hf.seed_everything(spec.seed)
        device = hf.pick_device(spec, report)
        report.status("running", "loading %s" % params["model_name"])
        tokenizer = AutoTokenizer.from_pretrained(params["model_name"])
        model = AutoModelForSequenceClassification.from_pretrained(
            params["model_name"], num_labels=1, ignore_mismatched_sizes=True,
            **hf.quantization_kwargs(params["lora"]))
        hf.ensure_pad_token(tokenizer, model)
        model = hf.prepare_quantized(model, params, report)
        model = hf.apply_lora(model, params["lora"], "SEQ_CLS", report)
        model = hf.place(model, device)

        selected = {"saved": False}

        def on_epoch_end(epoch):
            if not val:
                return None
            score = self._score(model, tokenizer, val, schema, labels, params,
                                device, scale)
            report.metric("val", _headline(schema.kind), score, step=epoch + 1)
            if selected.get("best") is None or score > selected["best"]:
                selected["best"] = score
                hf.save_model(model, tokenizer, spec.workdir)
                selected["saved"] = True
            return score

        report.status("running", "fitting the reward model")
        summary = hf.train_loop(
            model, units, params,
            lambda batch: self._loss(model, tokenizer, batch, params, device),
            report, device=device, seed=spec.seed, on_epoch_end=on_epoch_end)
        if not selected["saved"]:
            hf.save_model(model, tokenizer, spec.workdir)

        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "base_model": params["model_name"], "lora": params["lora"],
            "label_order": labels, "max_length": int(params["max_length"]),
            "scale": list(scale), "ranking_loss": params["ranking_loss"],
            "device": device, "n_train": len(train_rows),
            "n_comparisons": len(units), "bundle_digest": bundle.digest,
            "selected_epoch": summary["best_epoch"],
            # What a reward means, for whoever loads the model elsewhere.
            "reward": "logit of a one-output head; higher is better; only "
                      "differences are meaningful (Bradley-Terry)"})

        metrics = {"n_train": float(len(train_rows)),
                   "n_comparisons": float(len(units)),
                   "train_seconds": summary["train_seconds"],
                   "epochs_run": float(summary["epochs_run"])}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        return FitResult(
            model_version="%s-%s-%s" % (self.name, schema.name, spec.run_id),
            artifact_paths=hf.artifact_files(spec.workdir), metrics=metrics,
            label_order=labels, selected_on="val" if val else "")

    def _score(self, model, tokenizer, rows, schema, labels, params, device,
               scale):
        from potato.training.evaluation import score_split
        predictions = {}
        for row, payload, _ in self._predict_rows(
                model, tokenizer, rows, schema.kind, labels, params, device,
                scale):
            predictions[(str(row.get("instance_id", "")), schema.name)] = payload
        metrics, _ = score_split(rows, predictions, schema.name, schema.kind)
        return metrics.get(_headline(schema.kind), 0.0)

    def _predict_rows(self, model, tokenizer, rows, kind, labels, params,
                      device, scale, report: Optional[ProgressReporter] = None):
        import torch

        for done, row in enumerate(rows, 1):
            data = row if isinstance(row, dict) else (row.data or {
                "text": row.text})
            context, options = options_of(kind, data, labels)
            if len(options) < 2:
                continue
            with torch.inference_mode():
                rewards = self._rewards(model, tokenizer, [context] * len(options),
                                        options, params, device).cpu().tolist()
            payload, confidence = answer_from_rewards(kind, rewards, options,
                                                      scale)
            yield row, payload, confidence
            if report is not None:
                report.progress("predict", done, len(rows))
                if report.should_stop():
                    return

    # ------------------------------------------------------------- predict

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        card = hf.read_card(artifact_dir)
        device = hf.pick_device(spec, report)
        tokenizer = AutoTokenizer.from_pretrained(
            os.path.join(artifact_dir, hf.MODEL_DIR))
        model = hf.load_pretrained(AutoModelForSequenceClassification,
                                   artifact_dir, card, device, num_labels=1)
        hf.ensure_pad_token(tokenizer, model)
        params = {"max_length": card.get("max_length", 512)}
        scale = tuple(card.get("scale") or (-3.0, 3.0))
        items = list(items)
        for item, payload, confidence in self._predict_rows(
                model, tokenizer, items, card["kind"], card["label_order"],
                params, device, scale, report):
            yield PredictionRecord(instance_id=item.instance_id,
                                   schema_name=card["schema"], payload=payload,
                                   confidence=round(float(confidence), 4))


def _headline(kind: str) -> str:
    from potato.training.evaluation import HEADLINE
    return HEADLINE.get(kind, "score")
