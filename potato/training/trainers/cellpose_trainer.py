"""Fine-tune Cellpose on the cell and nucleus outlines annotators drew.

For ``image_annotation`` and ``microscopy`` schemes with outlines (polygon,
ellipse, freeform, brush mask). Cellpose segments instances without a
class, so a scheme with several labels trains one model on all its outlines
and every predicted cell gets the ``label`` parameter, or the scheme's most
common label. Train a model per label if the classes look different.

Each image's outlines become an instance label image (0 background, 1..n
one per outline, later outlines drawn over earlier ones where they
overlap), which is what ``cellpose.train.train_seg`` takes. Predicted masks
are traced back to the image widget's polygons, with each cell's mean
cell probability as its ``confidence``.

The call is made to fit Cellpose 3 (``model_type`` and ``channels``) and
Cellpose 4 (Cellpose-SAM, neither) by passing only the arguments the
installed version accepts. Cellpose is BSD-3-Clause; its pretrained weights
are distributed by the Cellpose authors under their own terms.
"""

from __future__ import annotations

import inspect
import os
from collections import Counter
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf
from potato.training.trainers import _segmentation as seg

INSTALL_HINT = "pip install cellpose"
_NEEDS = ("cellpose", "numpy", "PIL")
MODEL_NAME = "cellpose_model"


def _local_image(path: Optional[str]) -> bool:
    return bool(path) and not str(path).startswith(("http://", "https://")) \
        and os.path.isfile(str(path))


def instance_labels(objects: List[Dict[str, Any]], width: int, height: int):
    """A uint16 ``(height, width)`` image, 0 background and one id per
    outline. Boxes and points are not outlines and are left out."""
    import numpy
    from PIL import Image, ImageDraw
    canvas = Image.new("I;16", (width, height), 0)
    draw = ImageDraw.Draw(canvas)
    n = 0
    for obj in objects or []:
        rings = seg.outline_polygons(obj, width, height)
        if not rings:
            continue
        n += 1
        for ring in rings:
            draw.polygon([(float(x), float(y)) for x, y in ring], fill=n)
    return numpy.asarray(canvas, dtype="uint16"), n


def _call(function, **kwargs):
    """Call *function* with the keyword arguments it declares. Cellpose 4
    dropped ``channels`` and ``model_type``; passing them raises."""
    accepted = inspect.signature(function).parameters
    if any(p.kind == p.VAR_KEYWORD for p in accepted.values()):
        return function(**kwargs)
    return function(**{k: v for k, v in kwargs.items() if k in accepted})


class CellposeTrainer(Trainer):
    name: ClassVar[str] = "cellpose"
    description: ClassVar[str] = (
        "Cell and nucleus instance segmentation: fine-tunes Cellpose on the "
        "annotated outlines and predicts polygons.")
    kinds: ClassVar[Tuple[str, ...]] = ("geometry",)
    modalities: ClassVar[Tuple[str, ...]] = ("image",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "BSD-3-Clause"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"base_model": "cyto3", "epochs": 100, "learning_rate": 1e-5,
                "weight_decay": 0.1, "batch_size": 8, "diameter": None,
                "label": None, "min_instances": 5, "min_train_masks": 1}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        return {"type": "object", "additionalProperties": False, "properties": {
            "base_model": {"type": "string", "default": "cyto3",
                           "description": "Pretrained Cellpose model to start from: "
                                          "cyto3, nuclei, cyto2 (Cellpose 3) or cpsam "
                                          "(Cellpose 4), or a path to your own."},
            "epochs": {"type": "integer", "minimum": 1, "default": 100},
            "learning_rate": {"type": "number", "exclusiveMinimum": 0, "default": 1e-5},
            "weight_decay": {"type": "number", "minimum": 0, "default": 0.1},
            "batch_size": {"type": "integer", "minimum": 1, "default": 8},
            "diameter": {"type": ["number", "null"], "exclusiveMinimum": 0,
                         "default": None,
                         "description": "Typical cell diameter in pixels at "
                                        "prediction; null lets Cellpose estimate it."},
            "label": {"type": ["string", "null"], "default": None,
                      "description": "Label given to every predicted cell. Null: "
                                     "the scheme's most common label."},
            "min_instances": {"type": "integer", "minimum": 1, "default": 5,
                              "description": "Fewest annotated train images."},
            "min_train_masks": {"type": "integer", "minimum": 0, "default": 1,
                                "description": "Images with fewer outlines are "
                                               "skipped by Cellpose."},
        }}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = {**self.default_params(), **(spec.params or {})}
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        problems: List[str] = []
        if schema.kind not in self.kinds:
            problems.append("Schema %r is %s; this trainer handles %s."
                            % (schema.name, schema.kind, ", ".join(self.kinds)))
        if bundle.split_size("train") < int(params["min_instances"]):
            problems.append(
                "Only %d annotated images in the train split; this trainer needs at "
                "least %d. Annotate more, or lower min_instances."
                % (bundle.split_size("train"), int(params["min_instances"])))
        labels = bundle.labels(schema.name)
        if params.get("label") and labels and params["label"] not in labels:
            problems.append("label %r is not one of the scheme's labels (%s)."
                            % (params["label"], ", ".join(labels)))
        return problems

    # ------------------------------------------------------------ data

    def _rows(self, bundle: BundleRef, split: str, schema: str,
              report: ProgressReporter) -> List[Dict[str, Any]]:
        rows, missing = [], 0
        for row in hf.rows_with_target(bundle.read_split(split), schema,
                                       negative_tiles=split == "train"):
            path = bundle.resolve_media(row["media"]) if row.get("media") else None
            if not _local_image(path):
                missing += 1
                continue
            rows.append(dict(row, image_path=path))
        if missing:
            report.log("warning", "Left out %d %s row(s) with no local image file"
                                  % (missing, split))
        return rows

    @staticmethod
    def _image(path: str):
        import numpy
        from PIL import Image
        with Image.open(path) as img:
            return numpy.asarray(img.convert("RGB"))

    def _pairs(self, rows, schema: str):
        images, masks, n_cells = [], [], 0
        for row in rows:
            image = self._image(row["image_path"])
            height, width = image.shape[:2]
            labels, n = instance_labels(row["targets"].get(schema) or [], width, height)
            if not n and not hf.is_negative_tile(row, schema):
                continue
            images.append(image)
            masks.append(labels)
            n_cells += n
        return images, masks, n_cells

    def _device(self, spec: TrainingSpec, report: ProgressReporter) -> str:
        from potato.training.devices import describe_device, resolve_device
        device = resolve_device(spec.limits.device, log=report.log)
        report.log("info", "Training on %s" % describe_device(device))
        return device

    def _model(self, base: str, device: str):
        from cellpose import models
        gpu = device.startswith(("cuda", "mps"))
        kwargs: Dict[str, Any] = {"gpu": gpu}
        if os.path.exists(base) or base == "cpsam":
            kwargs["pretrained_model"] = base
        else:
            kwargs["model_type"] = base
            kwargs["pretrained_model"] = base
        try:
            import torch
            kwargs["device"] = torch.device(device)
        except Exception:  # noqa: BLE001
            pass
        return _call(models.CellposeModel, **kwargs)

    # ------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        from cellpose import train as cp_train

        params = {**self.default_params(), **(spec.params or {})}
        schema = spec.primary_schema
        labels = bundle.labels(schema.name)
        train_rows = self._rows(bundle, "train", schema.name, report)
        val_rows = self._rows(bundle, "val", schema.name, report)
        images, masks, n_cells = self._pairs(train_rows, schema.name)
        if not n_cells:
            raise TrainerError("None of the train images has an outline for %r "
                               "(boxes and points are not outlines)." % schema.name)
        val_images, val_masks, _ = self._pairs(val_rows, schema.name)
        counts = Counter(str(o.get("label")) for r in train_rows
                         for o in r["targets"].get(schema.name) or [])
        label = params.get("label") or (counts.most_common(1)[0][0] if counts else
                                        (labels[0] if labels else "cell"))
        if len(counts) > 1:
            report.log("warning", "Cellpose does not classify cells; all %d labels "
                                  "train one model and predictions are labelled %r"
                                  % (len(counts), label))
        device = self._device(spec, report)
        report.status("running", "loading %s" % params["base_model"])
        model = self._model(str(params["base_model"]), device)
        save_dir = os.path.join(spec.workdir, hf.MODEL_DIR)
        os.makedirs(save_dir, exist_ok=True)
        report.log("info", "%d train images with %d cells, %d val images"
                           % (len(images), n_cells, len(val_images)))
        report.status("running", "fine-tuning")
        result = _call(cp_train.train_seg, net=model.net, train_data=images,
                       train_labels=masks, test_data=val_images or None,
                       test_labels=val_masks or None, channels=[0, 0],
                       normalize=True, n_epochs=int(params["epochs"]),
                       learning_rate=float(params["learning_rate"]),
                       weight_decay=float(params["weight_decay"]),
                       batch_size=int(params["batch_size"]),
                       min_train_masks=int(params["min_train_masks"]),
                       save_path=save_dir, model_name=MODEL_NAME)
        model_path = result[0] if isinstance(result, (tuple, list)) else result
        model_path = str(model_path) if model_path else os.path.join(
            save_dir, "models", MODEL_NAME)
        train_losses = result[1] if isinstance(result, (tuple, list)) and len(result) > 1 else None

        version = "%s-%s-%s" % (self.name, schema.name, spec.run_id)
        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "base_model": params["base_model"], "label_order": labels,
            "label": label, "diameter": params.get("diameter"),
            "model_path": os.path.relpath(model_path, spec.workdir)
            if os.path.isabs(model_path) else model_path,
            "model_version": version, "device": device,
            "n_train": len(images), "n_cells": n_cells, "bundle_digest": bundle.digest})
        metrics = {"n_train": float(len(images)), "n_cells": float(n_cells)}
        try:
            metrics["train_loss"] = round(float(list(train_losses)[-1]), 4)
        except (TypeError, ValueError, IndexError):
            pass
        return FitResult(model_version=version,
                         artifact_paths=hf.artifact_files(spec.workdir),
                         metrics=metrics, label_order=labels, selected_on="")

    # ------------------------------------------------------------ predict

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        import numpy

        card = hf.read_card(artifact_dir)
        model_path = card["model_path"]
        if not os.path.isabs(model_path):
            model_path = os.path.join(artifact_dir, model_path)
        device = self._device(spec, report)
        model = self._model(model_path, device)
        version = card.get("model_version", "")
        usable = [item for item in items if _local_image(item.media)]
        for n, item in enumerate(usable):
            image = self._image(item.media)
            height, width = image.shape[:2]
            out = _call(model.eval, x=image, channels=[0, 0],
                        diameter=card.get("diameter"), normalize=True)
            masks = out[0]
            flows = out[1] if len(out) > 1 else None
            probability = None
            try:
                probability = 1.0 / (1.0 + numpy.exp(-numpy.asarray(flows[2], "float32")))
            except Exception:  # noqa: BLE001 - no cell probability map in this version
                probability = None
            shapes = []
            for cell in range(1, int(numpy.max(masks)) + 1 if numpy.size(masks) else 1):
                mask = masks == cell
                if not mask.any():
                    continue
                rings = seg.mask_polygons(mask)
                if not rings:
                    continue
                score = float(probability[mask].mean()) if probability is not None \
                    and probability.shape == mask.shape else 1.0
                ring = max(rings, key=lambda r: abs(sum(
                    x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(r, r[1:] + r[:1]))))
                shape = seg.client_polygon(ring, card["label"], score, width, height, version)
                if shape:
                    shapes.append(shape)
            report.progress("predict", n + 1, len(usable))
            if not shapes:
                continue
            shapes.sort(key=lambda s: -s["confidence"])
            yield PredictionRecord(
                instance_id=item.instance_id, schema_name=spec.primary_schema.name,
                payload=shapes,
                confidence=round(sum(s["confidence"] for s in shapes) / len(shapes), 4))
            if report.should_stop():
                return
