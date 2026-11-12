"""Interlinear glossing with a byte-level seq2seq model (ByT5).

For ``interlinear_gloss`` schemes, where annotators segment each word into
morphemes (``kitab-ım``) and gloss each morpheme (``book-1SG.POSS``).
Before this the scheme reached a bundle as a label named after its key.

Glossing data is small and the words are rare, which is the case ByT5 was
built for: it reads bytes, so an unseen word is still a sequence it can
process, and its smallest size is cheap to fine-tune. One model learns two
tasks, told apart by a prefix:

* ``gloss:`` a word's segmentation (and the word and its sentence) to its
  gloss line;
* ``segment:`` a word (and its sentence) to its segmentation, trained only
  when annotators segmented words.

A prediction starts from the words the page shows and any segmentation the
item pre-fills; a word with none is segmented first, then glossed. The
answer is the gloss widget's own record, ``{"words": [...], "translation"}``.
The held-out score is morpheme gloss accuracy, as in the gloss agreement
report.
"""

from __future__ import annotations

import math
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf

INSTALL_HINT = "pip install 'potato-annotation[train-text]'"
_NEEDS = ("torch", "transformers")
DEFAULT_MODEL = "google/byt5-small"


def _sentence(words: List[Dict[str, Any]]) -> str:
    return " ".join(str(w.get("word") or "") for w in words)


def gloss_prompt(word: Dict[str, Any], sentence: str) -> str:
    return "gloss: %s || word: %s || sentence: %s" % (
        word.get("morphemes") or word.get("word") or "", word.get("word") or "", sentence)


def segment_prompt(word: Dict[str, Any], sentence: str) -> str:
    return "segment: %s || sentence: %s" % (word.get("word") or "", sentence)


def pairs_of(target: Dict[str, Any], segment: bool) -> List[Tuple[str, str]]:
    """``(input, output)`` training pairs from one glossed sentence."""
    words = [w for w in (target or {}).get("words") or [] if isinstance(w, dict)]
    sentence = _sentence(words)
    out = []
    for word in words:
        gloss = (word.get("gloss") or "").strip()
        if gloss:
            out.append((gloss_prompt(word, sentence), gloss))
        morphemes = (word.get("morphemes") or "").strip()
        if segment and morphemes and gloss:
            out.append((segment_prompt(word, sentence), morphemes))
    return out


def segments_words(rows: Iterable[Dict[str, Any]], schema: str) -> bool:
    """Whether annotators split any word into morphemes."""
    for row in rows:
        for word in ((row.get("targets") or {}).get(schema) or {}).get("words") or []:
            morphemes = str(word.get("morphemes") or "")
            if morphemes and morphemes != str(word.get("word") or "") \
                    and any(c in morphemes for c in "-="):
                return True
    return False


class ByT5GlossTrainer(Trainer):
    name: ClassVar[str] = "byt5-gloss"
    description: ClassVar[str] = (
        "Interlinear glossing: fine-tunes ByT5 to segment words into "
        "morphemes and gloss them.")
    kinds: ClassVar[Tuple[str, ...]] = ("gloss",)
    modalities: ClassVar[Tuple[str, ...]] = ("text",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "Apache-2.0"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": DEFAULT_MODEL, "epochs": 20, "batch_size": 16,
                "gradient_accumulation": 1, "learning_rate": None,
                "weight_decay": 0.01, "warmup_ratio": 0.1, "patience": 3,
                "precision": "auto", "lora": None, "max_length": 256,
                "max_new_tokens": 64, "min_instances": 10}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = dict(hf.COMMON_PARAMS)
        props["learning_rate"] = dict(
            props["learning_rate"], default=None,
            description="Defaults to 3e-4, or 1e-3 with LoRA.")
        props["epochs"] = dict(props["epochs"], default=20)
        props["patience"] = dict(props["patience"], default=3)
        props.update({
            "model_name": {"type": "string", "default": DEFAULT_MODEL,
                           "description": "A seq2seq model id or local path; "
                                          "ByT5 by default."},
            "max_length": {"type": "integer", "minimum": 16, "default": 256,
                           "description": "Bytes of input per word (the word, "
                                          "its segmentation and sentence)."},
            "max_new_tokens": {"type": "integer", "minimum": 4, "default": 64,
                               "description": "Longest gloss or segmentation "
                                              "generated, in bytes."},
        })
        return {"type": "object", "properties": props,
                "additionalProperties": False}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        if schema.kind not in self.kinds:
            return ["Schema %r is %s; this trainer handles %s."
                    % (schema.name, schema.kind, ", ".join(self.kinds))]
        rows = hf.rows_with_target(bundle.read_split("train"), schema.name)
        problems = []
        if not any(pairs_of(r["targets"][schema.name], False) for r in rows):
            problems.append("No glossed words in the train split for %r." % schema.name)
        if len(rows) < int(params["min_instances"]):
            problems.append(
                "Only %d sentences in the train split; this trainer needs at "
                "least %d. Annotate more, or lower min_instances."
                % (len(rows), int(params["min_instances"])))
        problems.extend(hf.quantize_unsupported(params))
        return problems

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        params = hf.merged_params(self.default_params(), spec)
        if params.get("learning_rate") is None:
            params["learning_rate"] = 1e-3 if params["lora"] else 3e-4
        schema = spec.primary_schema
        train = hf.rows_with_target(bundle.read_split("train"), schema.name)
        val = hf.rows_with_target(bundle.read_split("val"), schema.name)
        segment = segments_words(train, schema.name)
        units = [p for r in train for p in pairs_of(r["targets"][schema.name], segment)]
        if not units:
            raise TrainerError("No glossed words in the train split for %r" % schema.name)
        report.log("info", "%d training pairs from %d sentences (segmentation %s)"
                   % (len(units), len(train), "learned" if segment else "not annotated"))

        hf.seed_everything(spec.seed)
        device = hf.pick_device(spec, report)
        report.status("running", "loading %s" % params["model_name"])
        tokenizer = AutoTokenizer.from_pretrained(params["model_name"])
        model = AutoModelForSeq2SeqLM.from_pretrained(params["model_name"])
        model = hf.apply_lora(model, params["lora"], "SEQ_2_SEQ_LM", report)
        model = hf.place(model, device)

        def loss_of(batch):
            enc = tokenizer([u[0] for u in batch], truncation=True,
                            max_length=int(params["max_length"]), padding=True,
                            return_tensors="pt").to(device)
            labels = tokenizer([u[1] for u in batch], truncation=True,
                               max_length=int(params["max_new_tokens"]), padding=True,
                               return_tensors="pt").input_ids.to(device)
            labels[labels == tokenizer.pad_token_id] = -100
            return model(**enc, labels=labels).loss

        card = {"trainer": self.name, "schema": schema.name, "kind": schema.kind,
                "base_model": params["model_name"], "lora": params["lora"],
                "segment": segment, "max_length": int(params["max_length"]),
                "max_new_tokens": int(params["max_new_tokens"])}
        selected = {"saved": False}

        def on_epoch_end(epoch):
            if not val:
                return None
            from potato.training.evaluation import score_split
            predictions = {(str(r.get("instance_id")), schema.name): p
                           for r, p, _ in self._predict_rows(model, tokenizer, val, card,
                                                             device)}
            metrics, _ = score_split(val, predictions, schema.name, schema.kind)
            score = metrics.get("morpheme_accuracy", 0.0)
            report.metric("val", "morpheme_accuracy", score, step=epoch + 1)
            if selected.get("best") is None or score > selected["best"]:
                selected["best"] = score
                hf.save_model(model, tokenizer, spec.workdir)
                selected["saved"] = True
            return score

        report.status("running", "fine-tuning")
        summary = hf.train_loop(model, units, params, loss_of, report, device=device,
                                seed=spec.seed, on_epoch_end=on_epoch_end)
        if not selected["saved"]:
            hf.save_model(model, tokenizer, spec.workdir)
        card.update({"device": device, "n_train": len(train), "n_pairs": len(units),
                     "bundle_digest": bundle.digest,
                     "selected_epoch": summary["best_epoch"]})
        hf.write_card(spec.workdir, card)
        metrics = {"n_train": float(len(train)), "n_pairs": float(len(units)),
                   "train_seconds": summary["train_seconds"],
                   "epochs_run": float(summary["epochs_run"])}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        return FitResult(model_version="%s-%s-%s" % (self.name, schema.name, spec.run_id),
                         artifact_paths=hf.artifact_files(spec.workdir), metrics=metrics,
                         selected_on="val" if val else "")

    def _generate(self, model, tokenizer, prompts: List[str], card, device):
        """``[(text, probability)]``: each prompt's output and the geometric
        mean of its tokens' probabilities."""
        import torch
        out = []
        for start in range(0, len(prompts), 32):
            chunk = prompts[start:start + 32]
            enc = tokenizer(chunk, truncation=True, max_length=int(card["max_length"]),
                            padding=True, return_tensors="pt").to(device)
            with torch.inference_mode():
                generated = model.generate(**enc, max_new_tokens=int(card["max_new_tokens"]),
                                           num_beams=1, do_sample=False,
                                           return_dict_in_generate=True, output_scores=True)
                scores = model.compute_transition_scores(
                    generated.sequences, generated.scores, normalize_logits=True)
            texts = tokenizer.batch_decode(generated.sequences, skip_special_tokens=True)
            for text, row in zip(texts, scores.cpu().tolist()):
                logs = [s for s in row if s > float("-inf") and s != 0.0] or [0.0]
                out.append((text.strip(), math.exp(sum(logs) / len(logs))))
        return out

    def _predict_rows(self, model, tokenizer, rows, card, device,
                      report: Optional[ProgressReporter] = None):
        model.eval()
        for done, row in enumerate(rows, 1):
            data = row if isinstance(row, dict) else (row.data or {})
            start = data.get("gloss_input") or {}
            words = [dict(w) for w in start.get("words") or [] if isinstance(w, dict)]
            if not words:
                continue
            sentence = _sentence(words)
            decisions = []
            if card.get("segment"):
                todo = [w for w in words if (w.get("morphemes") or "") in ("", w.get("word"))]
                for word, (text, p) in zip(todo, self._generate(
                        model, tokenizer, [segment_prompt(w, sentence) for w in todo],
                        card, device)):
                    if text:
                        word["morphemes"] = text
                        decisions.append(p)
            for word, (text, p) in zip(words, self._generate(
                    model, tokenizer, [gloss_prompt(w, sentence) for w in words],
                    card, device)):
                word["gloss"] = text
                decisions.append(p)
            payload = {"words": words, "translation": str(start.get("translation") or "")}
            yield row, payload, (min(decisions) if decisions else None)
            if report is not None:
                report.progress("predict", done, len(rows))
                if report.should_stop():
                    return

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        import os
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        card = hf.read_card(artifact_dir)
        device = hf.pick_device(spec, report)
        tokenizer = AutoTokenizer.from_pretrained(os.path.join(artifact_dir, hf.MODEL_DIR))
        model = hf.load_pretrained(AutoModelForSeq2SeqLM, artifact_dir, card, device)
        items = list(items)
        for item, payload, confidence in self._predict_rows(model, tokenizer, items, card,
                                                            device, report):
            yield PredictionRecord(
                instance_id=item.instance_id, schema_name=card["schema"], payload=payload,
                confidence=None if confidence is None else round(float(confidence), 4))
