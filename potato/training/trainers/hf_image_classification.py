"""Fine-tune a vision transformer to classify images.

For classification schemes (radio, multiselect) over items that show an
image, and for any bundle whose modality is ``image``. Any model
``AutoModelForImageClassification`` loads works: ViT, DeiT, BEiT, ConvNeXt,
Swin, or a DINOv2 backbone. ``lora: true`` trains a LoRA adapter on the
attention projections and the classification head.

Images are read from disk. An item whose image is a remote URL, or a file
that is not there, is left out of training and gets no prediction, and the
run log counts them.

Augmentation is a random horizontal flip and nothing more. Several label sets
(left/right, text in the image) are changed by a flip, so ``flip: false``
turns it off.
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
DEFAULT_MODEL = "google/vit-base-patch16-224-in21k"


def _local_image(path: Optional[str]) -> bool:
    return bool(path) and not str(path).startswith(("http://", "https://")) \
        and os.path.isfile(str(path))


class HFImageClassificationTrainer(Trainer):
    name: ClassVar[str] = "hf-image-classification"
    description: ClassVar[str] = (
        "Fine-tunes a vision transformer (ViT, DeiT, ConvNeXt, DINOv2) to "
        "classify images, with optional LoRA.")
    kinds: ClassVar[Tuple[str, ...]] = ("nominal", "ordinal", "multilabel")
    modalities: ClassVar[Tuple[str, ...]] = ("image",)
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
                "precision": "auto", "lora": None, "threshold": 0.5,
                "flip": True, "min_instances": 20}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = dict(hf.COMMON_PARAMS)
        props["learning_rate"] = dict(
            props["learning_rate"], default=None,
            description="Defaults to 5e-5, or 5e-4 with LoRA.")
        props.update({
            "model_name": {"type": "string", "default": DEFAULT_MODEL,
                           "description": "A Hugging Face model id or a "
                                          "local path."},
            "threshold": {"type": "number", "minimum": 0, "maximum": 1,
                          "default": 0.5, "description": "Multilabel only."},
            "flip": {"type": "boolean", "default": True,
                     "description": "Random horizontal flips in training."},
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
        if bundle.modality != "image":
            problems.append(
                "This bundle's items are %s, not images. The trainer reads "
                "each item's image file." % bundle.modality)
        if bundle.split_size("train") < int(params["min_instances"]):
            problems.append(
                "Only %d items in the train split; this trainer needs at "
                "least %d. Annotate more, or lower min_instances."
                % (bundle.split_size("train"), int(params["min_instances"])))
        if len(bundle.labels(schema.name)) < 2:
            problems.append("Schema %r has fewer than two labels in the data."
                            % schema.name)
        return problems

    def _image_rows(self, bundle: BundleRef, split: str, schema: str,
                    report: ProgressReporter) -> List[Dict[str, Any]]:
        rows, missing = [], 0
        for row in hf.rows_with_target(bundle.read_split(split), schema):
            path = bundle.resolve_media(row["media"]) if row.get("media") else None
            if not _local_image(path):
                missing += 1
                continue
            rows.append(dict(row, image_path=path))
        if missing:
            report.log("warning", "Left out %d %s row(s) with no local image "
                                  "file" % (missing, split))
        return rows

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        import random

        import torch
        from transformers import (AutoImageProcessor,
                                  AutoModelForImageClassification)

        params = hf.merged_params(self.default_params(), spec)
        if params.get("learning_rate") is None:
            params["learning_rate"] = 5e-4 if params["lora"] else 5e-5
        schema = spec.primary_schema
        multilabel = schema.kind == "multilabel"
        labels = bundle.labels(schema.name)
        index = {label: i for i, label in enumerate(labels)}

        train = self._image_rows(bundle, "train", schema.name, report)
        val = self._image_rows(bundle, "val", schema.name, report)
        if not train:
            raise TrainerError("No train rows with a local image for %r"
                               % schema.name)
        report.log("info", "%d train and %d val images, %d labels"
                   % (len(train), len(val), len(labels)))

        hf.seed_everything(spec.seed)
        device = hf.pick_device(spec, report)
        report.status("running", "loading %s" % params["model_name"])
        processor = AutoImageProcessor.from_pretrained(params["model_name"])
        model = AutoModelForImageClassification.from_pretrained(
            params["model_name"], **self._head_kwargs(labels, multilabel))
        model = hf.apply_lora(model, params["lora"], None, report,
                              modules_to_save=self._head_modules(model))
        model.to(device)
        flip_rng = random.Random(spec.seed)

        def pixels(rows, augment):
            from PIL import Image, ImageOps

            images = []
            for row in rows:
                with Image.open(row["image_path"]) as img:
                    img = img.convert("RGB")
                    if augment and params["flip"] and flip_rng.random() < 0.5:
                        img = ImageOps.mirror(img)
                    images.append(img)
            return processor(images=images,
                             return_tensors="pt")["pixel_values"].to(device)

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
            return model(pixel_values=pixels(batch, True),
                         labels=target_tensor(batch)).loss

        selected = {"best": None, "saved": False}

        def save():
            hf.save_model(model, None, spec.workdir)
            processor.save_pretrained(os.path.join(spec.workdir, hf.MODEL_DIR))

        def on_epoch_end(epoch):
            if not val:
                return None
            from potato.training.evaluation import HEADLINE, score_split
            predictions = {}
            for row, payload, _ in self._predict_rows(
                    model, lambda rows: pixels(rows, False), val, labels,
                    multilabel, params):
                predictions[(str(row["instance_id"]), schema.name)] = payload
            metrics, _ = score_split(val, predictions, schema.name, schema.kind)
            score = metrics.get(HEADLINE[schema.kind], 0.0)
            report.metric("val", HEADLINE[schema.kind], score, step=epoch + 1)
            if selected["best"] is None or score > selected["best"]:
                selected["best"] = score
                save()
                selected["saved"] = True
            return score

        report.status("running", "fine-tuning")
        summary = hf.train_loop(model, train, params, loss_of, report,
                                device=device, seed=spec.seed,
                                on_epoch_end=on_epoch_end)
        if not selected["saved"]:
            save()

        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "base_model": params["model_name"], "lora": params["lora"],
            "label_order": labels, "multilabel": multilabel,
            "threshold": float(params["threshold"]), "device": device,
            "n_train": len(train), "bundle_digest": bundle.digest,
            "selected_epoch": summary["best_epoch"]})

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
                  "ignore_mismatched_sizes": True}
        if multilabel:
            kwargs["problem_type"] = "multi_label_classification"
        return kwargs

    @staticmethod
    def _head_modules(model) -> List[str]:
        """The classification head's module name, which varies by family
        (``classifier`` for ViT, ``head`` for some others)."""
        names = [n for n, _ in model.named_children()]
        return [n for n in ("classifier", "head", "fc") if n in names] \
            or ["classifier"]

    def _predict_rows(self, model, to_pixels, rows, labels, multilabel, params,
                      report: Optional[ProgressReporter] = None):
        import torch

        size = max(1, int(params.get("batch_size", 16)))
        for start in range(0, len(rows), size):
            chunk = rows[start:start + size]
            with torch.inference_mode():
                logits = model(pixel_values=to_pixels(chunk)).logits.float()
            if multilabel:
                threshold = float(params.get("threshold", 0.5))
                for row, p in zip(chunk, torch.sigmoid(logits).cpu().tolist()):
                    chosen = [{"label": labels[i], "confidence": round(v, 4)}
                              for i, v in enumerate(p) if v >= threshold]
                    yield row, chosen, min(max(v, 1 - v) for v in p)
            else:
                for row, p in zip(chunk,
                                  torch.softmax(logits, -1).cpu().tolist()):
                    best = max(range(len(p)), key=p.__getitem__)
                    yield row, {"label": labels[best],
                                "confidence": round(p[best], 4)}, p[best]
            if report is not None:
                report.progress("predict", start + len(chunk), len(rows))
                if report.should_stop():
                    return

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        from PIL import Image
        from transformers import (AutoImageProcessor,
                                  AutoModelForImageClassification)

        card = hf.read_card(artifact_dir)
        labels = card["label_order"]
        multilabel = bool(card.get("multilabel"))
        device = hf.pick_device(spec, report)
        processor = AutoImageProcessor.from_pretrained(
            os.path.join(artifact_dir, hf.MODEL_DIR))
        model = hf.load_pretrained(AutoModelForImageClassification,
                                   artifact_dir, card, device,
                                   **self._head_kwargs(labels, multilabel))

        def to_pixels(chunk):
            images = []
            for item in chunk:
                with Image.open(item.media) as img:
                    images.append(img.convert("RGB"))
            return processor(images=images,
                             return_tensors="pt")["pixel_values"].to(device)

        # An image model given no image would score nothing and still return
        # a confident-looking label; those items get no prediction.
        usable = [item for item in items if _local_image(item.media)]
        for item, payload, confidence in self._predict_rows(
                model, to_pixels, usable, labels, multilabel,
                {"batch_size": 32, "threshold": card.get("threshold", 0.5)},
                report):
            yield PredictionRecord(instance_id=item.instance_id,
                                   schema_name=card["schema"], payload=payload,
                                   confidence=round(float(confidence), 4))
