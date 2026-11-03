"""Document layout from words and their positions: fine-tune LayoutLMv3.

For ``image_annotation`` schemes over page images whose items carry the
page's words with boxes, ``words: [{"text": ..., "bbox": [x0, y0, x1, y1]}]``
(pixels of the page image, or 0-1). Potato runs no OCR: the words come from
the PDF's text layer, a PAGE-XML transcription (the importer fills
``words``), or whatever OCR the project ran before import.

Each word is labelled by the annotated region its centre falls in (the
smallest one, when regions nest), as BIO tags so two adjacent regions with
the same label stay two. Predicted words are merged back into regions, a
run of words with the same label starting at a ``B-`` tag, and each region
becomes a box prelabel spanning its words, with the words' mean
probability as its confidence. Held-out scores are box mAP against the
annotated regions.

Licence: the LayoutLMv3 weights Microsoft publishes are CC BY-NC-SA 4.0,
not for commercial use, so this trainer asks for the licence to be
confirmed before its first run, as the YOLO trainers do. The code is MIT.
"""

from __future__ import annotations

import os
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf

INSTALL_HINT = "pip install 'potato-annotation[train-vision]'"
_NEEDS = ("torch", "transformers", "PIL")
DEFAULT_MODEL = "microsoft/layoutlmv3-base"


def _local_image(path: Optional[str]) -> bool:
    return bool(path) and not str(path).startswith(("http://", "https://")) \
        and os.path.isfile(str(path))


def page_words(row: Dict[str, Any], width: int, height: int
               ) -> List[Tuple[str, Tuple[float, float, float, float]]]:
    """``(text, normalized box)`` per word with text and a box. Boxes in
    pixels are divided by the page size; a box already within 0-1 is kept."""
    out = []
    raw = [w for w in row.get("words") or [] if isinstance(w, dict)]
    pixels = any(float(v) > 1.0 for w in raw for v in (w.get("bbox") or [])
                 if isinstance(v, (int, float)))
    for word in raw:
        text = str(word.get("text") or "").strip()
        box = word.get("bbox")
        if not text or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            x0, y0, x1, y1 = (float(v) for v in box)
        except (TypeError, ValueError):
            continue
        if pixels:
            x0, x1, y0, y1 = x0 / width, x1 / width, y0 / height, y1 / height
        out.append((text, (max(0.0, min(x0, x1)), max(0.0, min(y0, y1)),
                           min(1.0, max(x0, x1)), min(1.0, max(y0, y1)))))
    return out


def word_tags(words, objects: List[Dict[str, Any]], labels: List[str]) -> List[str]:
    """BIO tags for *words* from the annotated *objects* (normalized)."""
    from potato.export.cv_utils import normalize_annotation_object
    from potato.grounding.metrics import point_in_region
    sized = []
    for index, obj in enumerate(objects or []):
        if str(obj.get("label")) not in labels:
            continue
        canonical = normalize_annotation_object(obj, 1.0, 1.0) or {}
        box = canonical.get("bbox") or [0, 0, 0, 0]
        sized.append((float(box[2]) * float(box[3]), index, obj))
    sized.sort(key=lambda s: s[0])
    tags, previous = [], None
    for _text, (x0, y0, x1, y1) in words:
        centre = {"x": (x0 + x1) / 2, "y": (y0 + y1) / 2}
        region = next(((index, obj) for _area, index, obj in sized
                       if point_in_region(centre, obj)), None)
        if region is None:
            tags.append("O")
            previous = None
            continue
        index, obj = region
        tags.append(("I-" if previous == index else "B-") + str(obj["label"]))
        previous = index
    return tags


def regions_from_tags(words, tags: List[str], scores: List[float], version: str
                      ) -> List[Dict[str, Any]]:
    """Runs of words as box prelabels: a run starts at ``B-x``, or at
    ``I-x`` after a word that was not ``x``, and ends before the next
    start or ``O``."""
    regions: List[Dict[str, Any]] = []
    current = None
    for (text, box), tag, score in zip(words, tags, scores):
        if tag == "O":
            current = None
            continue
        prefix, label = tag[:2], tag[2:]
        if current is None or prefix == "B-" or current["label"] != label:
            current = {"label": label, "boxes": [], "scores": []}
            regions.append(current)
        current["boxes"].append(box)
        current["scores"].append(score)
    out = []
    for region in regions:
        x0 = min(b[0] for b in region["boxes"])
        y0 = min(b[1] for b in region["boxes"])
        x1 = max(b[2] for b in region["boxes"])
        y1 = max(b[3] for b in region["boxes"])
        out.append({"type": "bbox", "label": region["label"], "color": "",
                    "coordinates": {"x": round(x0, 5), "y": round(y0, 5),
                                    "width": round(x1 - x0, 5), "height": round(y1 - y0, 5)},
                    "source": "ai", "ai_model": version,
                    "confidence": round(sum(region["scores"]) / len(region["scores"]), 4)})
    out.sort(key=lambda o: -o["confidence"])
    return out


class LayoutLMv3Trainer(Trainer):
    name: ClassVar[str] = "layoutlmv3"
    description: ClassVar[str] = (
        "Document layout: fine-tunes LayoutLMv3 on the page's words and their "
        "positions, labelled by the regions drawn around them. Items need a "
        "words field. Weights are CC BY-NC-SA 4.0: confirm the licence before "
        "the first run.")
    kinds: ClassVar[Tuple[str, ...]] = ("geometry",)
    modalities: ClassVar[Tuple[str, ...]] = ("image",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "CC-BY-NC-SA-4.0"
    commercial_use: ClassVar[Optional[bool]] = False
    licence_ack: ClassVar[bool] = True
    licence_url: ClassVar[str] = "https://huggingface.co/microsoft/layoutlmv3-base"

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": DEFAULT_MODEL, "epochs": 10, "batch_size": 2,
                "gradient_accumulation": 1, "learning_rate": 2e-5,
                "weight_decay": 0.01, "warmup_ratio": 0.1, "patience": 3,
                "max_length": 512, "min_instances": 10}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = {key: hf.COMMON_PARAMS[key] for key in
                 ("epochs", "batch_size", "gradient_accumulation", "weight_decay",
                  "warmup_ratio", "patience", "min_instances")}
        props["epochs"] = dict(props["epochs"], default=10)
        props["batch_size"] = dict(props["batch_size"], default=2)
        props["patience"] = dict(props["patience"], default=3)
        props["min_instances"] = dict(props["min_instances"], default=10)
        props.update({
            "model_name": {"type": "string", "default": DEFAULT_MODEL,
                           "description": "A LayoutLMv3 checkpoint, such as "
                                          "microsoft/layoutlmv3-base or -large."},
            "learning_rate": {"type": "number", "exclusiveMinimum": 0, "default": 2e-5},
            "max_length": {"type": "integer", "minimum": 16, "maximum": 512,
                           "default": 512,
                           "description": "Tokens per page; words past it are not "
                                          "trained on or predicted."},
        })
        return {"type": "object", "properties": props, "additionalProperties": False}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = {**self.default_params(), **(spec.params or {})}
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        if schema.kind not in self.kinds:
            return ["Schema %r is %s; this trainer handles %s."
                    % (schema.name, schema.kind, ", ".join(self.kinds))]
        with_words = sum(1 for row in bundle.read_split("train")
                         if row.get("words") and (row.get("targets") or {}).get(schema.name))
        if with_words < int(params["min_instances"]):
            return ["Only %d annotated pages in the train split carry words; this trainer "
                    "needs at least %d. Give each item a words field ([{text, bbox}]), "
                    "for example from the PDF text layer or a PAGE-XML import."
                    % (with_words, int(params["min_instances"]))]
        return []

    # ------------------------------------------------------------ data

    def _pages(self, bundle: BundleRef, split: str, schema: str, labels: List[str],
               report: ProgressReporter, need_target: bool = True) -> List[Dict[str, Any]]:
        from PIL import Image
        rows = hf.rows_with_target(bundle.read_split(split), schema) if need_target \
            else list(bundle.read_split(split))
        out, missing = [], 0
        for row in rows:
            path = bundle.resolve_media(row["media"]) if row.get("media") else None
            if not _local_image(path) or not row.get("words"):
                missing += 1
                continue
            with Image.open(path) as img:
                width, height = img.size
            words = page_words(row, width, height)
            if not words:
                missing += 1
                continue
            page = {"row": row, "path": path, "words": words}
            if need_target:
                page["tags"] = word_tags(words, row["targets"][schema], labels)
            out.append(page)
        if missing:
            report.log("warning", "Left out %d %s page(s) with no local image or no words"
                                  % (missing, split))
        return out

    def _encode(self, processor, pages, max_length, tag_index=None):
        from PIL import Image
        images = []
        for page in pages:
            with Image.open(page["path"]) as img:
                images.append(img.convert("RGB"))
        kwargs = {}
        if tag_index is not None:
            kwargs["word_labels"] = [[tag_index[t] for t in page["tags"]] for page in pages]
        return processor(images, [[w for w, _ in page["words"]] for page in pages],
                         boxes=[[[int(round(v * 1000)) for v in box] for _, box in page["words"]]
                                for page in pages],
                         truncation=True, padding="max_length", max_length=max_length,
                         return_tensors="pt", **kwargs)

    # ------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        from transformers import LayoutLMv3ForTokenClassification, LayoutLMv3Processor

        params = {**self.default_params(), **(spec.params or {})}
        schema = spec.primary_schema
        labels = bundle.labels(schema.name)
        tags = ["O"] + [p + label for label in labels for p in ("B-", "I-")]
        tag_index = {t: i for i, t in enumerate(tags)}
        train = self._pages(bundle, "train", schema.name, labels, report)
        val = self._pages(bundle, "val", schema.name, labels, report)
        if not train:
            raise TrainerError("No train page has both words and regions for %r" % schema.name)
        hf.seed_everything(spec.seed)
        from potato.training.devices import describe_device, resolve_device
        device = resolve_device(spec.limits.device, log=report.log)
        report.log("info", "Training on %s; %d train pages, %d val pages, %d words"
                           % (describe_device(device), len(train), len(val),
                              sum(len(p["words"]) for p in train)))
        report.status("running", "loading %s" % params["model_name"])
        processor = LayoutLMv3Processor.from_pretrained(params["model_name"], apply_ocr=False)
        model = LayoutLMv3ForTokenClassification.from_pretrained(
            params["model_name"], num_labels=len(tags),
            id2label=dict(enumerate(tags)), label2id=tag_index,
            ignore_mismatched_sizes=True).to(device)
        max_length = int(params["max_length"])
        version = "%s-%s-%s" % (self.name, schema.name, spec.run_id)
        model_dir = os.path.join(spec.workdir, hf.MODEL_DIR)
        selected = {"best": None, "saved": False}

        def loss_of(batch):
            encoded = self._encode(processor, batch, max_length, tag_index)
            return model(**{k: v.to(device) for k, v in encoded.items()}).loss

        def save():
            model.save_pretrained(model_dir)
            processor.save_pretrained(model_dir)

        def on_epoch_end(epoch):
            if not val:
                return None
            from potato.training.evaluation import HEADLINE, score_split
            predictions = {(str(p["row"]["instance_id"]), schema.name): payload
                           for p, payload in self._predict_pages(model, processor, val, tags,
                                                                 max_length, device, version)}
            metrics, _ = score_split([p["row"] for p in val], predictions,
                                     schema.name, schema.kind)
            score = metrics.get(HEADLINE[schema.kind], 0.0)
            report.metric("val", HEADLINE[schema.kind], score, step=epoch + 1)
            if selected["best"] is None or score > selected["best"]:
                selected["best"] = score
                save()
                selected["saved"] = True
            return score

        report.status("running", "fine-tuning")
        summary = hf.train_loop(model, train, params, loss_of, report, device=device,
                                seed=spec.seed, on_epoch_end=on_epoch_end)
        if not selected["saved"]:
            save()
        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "base_model": params["model_name"], "label_order": labels, "tags": tags,
            "max_length": max_length, "model_version": version, "device": device,
            "n_train": len(train), "bundle_digest": bundle.digest,
            "selected_epoch": summary["best_epoch"]})
        metrics = {"n_train": float(len(train)), "train_seconds": summary["train_seconds"],
                   "epochs_run": float(summary["epochs_run"])}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        return FitResult(model_version=version, artifact_paths=hf.artifact_files(spec.workdir),
                         metrics=metrics, label_order=labels,
                         selected_on="val" if val else "")

    # ------------------------------------------------------------ predict

    def _predict_pages(self, model, processor, pages, tags, max_length, device, version):
        import torch
        model.eval()
        for page in pages:
            encoded = self._encode(processor, [page], max_length)
            word_ids = encoded.word_ids(0)
            with torch.no_grad():
                logits = model(**{k: v.to(device) for k, v in encoded.items()}).logits[0]
            probabilities = torch.softmax(logits, dim=-1).cpu()
            word_tag: Dict[int, Tuple[str, float]] = {}
            for position, word in enumerate(word_ids):
                if word is None or word in word_tag:
                    continue
                best = int(probabilities[position].argmax())
                word_tag[word] = (tags[best], float(probabilities[position, best]))
            kept = [n for n in range(len(page["words"])) if n in word_tag]
            yield page, regions_from_tags([page["words"][n] for n in kept],
                                          [word_tag[n][0] for n in kept],
                                          [word_tag[n][1] for n in kept], version)

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        from PIL import Image
        from transformers import LayoutLMv3ForTokenClassification, LayoutLMv3Processor
        from potato.training.devices import resolve_device

        card = hf.read_card(artifact_dir)
        model_dir = os.path.join(artifact_dir, hf.MODEL_DIR)
        processor = LayoutLMv3Processor.from_pretrained(model_dir, apply_ocr=False)
        device = resolve_device(spec.limits.device, log=report.log)
        model = LayoutLMv3ForTokenClassification.from_pretrained(model_dir).to(device)
        pages = []
        for item in items:
            if not _local_image(item.media) or not item.data.get("words"):
                continue
            with Image.open(item.media) as img:
                width, height = img.size
            words = page_words(item.data, width, height)
            if words:
                pages.append({"row": item.data, "path": item.media, "words": words,
                              "item": item})
        for n, (page, payload) in enumerate(self._predict_pages(
                model, processor, pages, card["tags"], int(card.get("max_length", 512)),
                device, card.get("model_version", ""))):
            report.progress("predict", n + 1, len(pages))
            if not payload:
                continue
            yield PredictionRecord(
                instance_id=page["item"].instance_id, schema_name=spec.primary_schema.name,
                payload=payload,
                confidence=round(sum(o["confidence"] for o in payload) / len(payload), 4))
            if report.should_stop():
                return
