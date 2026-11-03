"""Fine-tune SAM to turn a box into the outline annotators would draw.

For ``image_annotation`` schemes with outlines (polygon, ellipse, freeform,
brush mask). Segment Anything takes a prompt and returns a mask; out of the
box it outlines whatever is most salient in the box, which on a pathology
slide or a satellite tile is often not the object the study means. This
trainer fine-tunes SAM's mask decoder on the study's own outlines, each
prompted with its bounding box, and keeps the image encoder frozen (its
image embeddings are computed once per image, so an epoch costs little).

Prediction refines boxes into outlines:

- on an item that already carries box prelabels (an earlier detection run's
  write-back, read from the item into the bundle as ``prior``), each box
  becomes a polygon prelabel;
- on a held-out item, the annotators' own boxes are the prompts, so the
  held-out score answers "given the right box, how close is the outline".
  Those predictions are marked ``heldout_only``: write-back neither stores
  nor publishes them, since they are made from another annotator's answer.

So the usual loop is a detector (``torchvision-detect`` or
``ultralytics-detect``) whose boxes are written back, then this trainer to
outline them. Weights: ``facebook/sam-vit-base`` and the other SAM
checkpoints are Apache-2.0.
"""

from __future__ import annotations

import os
import random
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf
from potato.training.trainers import _segmentation as seg

INSTALL_HINT = "pip install 'potato-annotation[train-vision]'"
_NEEDS = ("torch", "transformers", "PIL")
DEFAULT_MODEL = "facebook/sam-vit-base"


def _local_image(path: Optional[str]) -> bool:
    return bool(path) and not str(path).startswith(("http://", "https://")) \
        and os.path.isfile(str(path))


def _box(obj: Dict[str, Any], width: int, height: int) -> Optional[List[float]]:
    """``[x0, y0, x1, y1]`` pixels for any shape with an extent."""
    from potato.export.cv_utils import normalize_annotation_object
    canonical = normalize_annotation_object(obj, width, height)
    if not canonical or not canonical.get("bbox"):
        return None
    x, y, w, h = (float(v) for v in canonical["bbox"][:4])
    if w < 1 or h < 1:
        return None
    return [max(0.0, x), max(0.0, y), min(float(width), x + w), min(float(height), y + h)]


class SamFinetuneTrainer(Trainer):
    name: ClassVar[str] = "sam-finetune"
    description: ClassVar[str] = (
        "Box-to-outline refinement: fine-tunes SAM's mask decoder on the "
        "annotated outlines, then outlines the boxes an earlier detection run "
        "wrote back.")
    kinds: ClassVar[Tuple[str, ...]] = ("geometry",)
    modalities: ClassVar[Tuple[str, ...]] = ("image",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "Apache-2.0"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": DEFAULT_MODEL, "epochs": 10, "batch_size": 8,
                "learning_rate": 1e-4, "weight_decay": 0.0, "box_jitter": 0.05,
                "mask_threshold": 0.0, "min_instances": 10, "patience": 3}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        return {"type": "object", "additionalProperties": False, "properties": {
            "model_name": {"type": "string", "default": DEFAULT_MODEL,
                           "description": "A SAM checkpoint on the Hugging Face Hub "
                                          "(facebook/sam-vit-base, -large, -huge) "
                                          "or a local directory."},
            "epochs": {"type": "integer", "minimum": 1, "default": 10},
            "batch_size": {"type": "integer", "minimum": 1, "default": 8,
                           "description": "Boxes per optimizer step."},
            "learning_rate": {"type": "number", "exclusiveMinimum": 0, "default": 1e-4},
            "weight_decay": {"type": "number", "minimum": 0, "default": 0.0},
            "box_jitter": {"type": "number", "minimum": 0, "maximum": 0.5, "default": 0.05,
                           "description": "Training boxes are moved and resized by up "
                                          "to this share of their size, so the model "
                                          "learns from boxes as loose as a detector's."},
            "mask_threshold": {"type": "number", "default": 0.0,
                               "description": "Logit above which a pixel is inside."},
            "min_instances": {"type": "integer", "minimum": 1, "default": 10,
                              "description": "Fewest annotated outlines to train on."},
            "patience": {"type": ["integer", "null"], "minimum": 1, "default": 3},
        }}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = {**self.default_params(), **(spec.params or {})}
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        if schema.kind not in self.kinds:
            return ["Schema %r is %s; this trainer handles %s."
                    % (schema.name, schema.kind, ", ".join(self.kinds))]
        n = sum(1 for row in bundle.read_split("train")
                for obj in (row.get("targets") or {}).get(schema.name) or []
                if isinstance(obj, dict) and obj.get("type") in seg.OUTLINE_TYPES)
        if n < int(params["min_instances"]):
            return ["Only %d annotated outlines in the train split; this trainer needs "
                    "at least %d (boxes and points are not outlines). Annotate more, "
                    "or lower min_instances." % (n, int(params["min_instances"]))]
        return []

    # ------------------------------------------------------------ data

    def _examples(self, bundle: BundleRef, split: str, schema: str,
                  report: ProgressReporter) -> List[Dict[str, Any]]:
        """One entry per image: its path, size and ``(box, outline rings)``."""
        from PIL import Image
        out, missing = [], 0
        for row in hf.rows_with_target(bundle.read_split(split), schema):
            path = bundle.resolve_media(row["media"]) if row.get("media") else None
            if not _local_image(path):
                missing += 1
                continue
            with Image.open(path) as img:
                width, height = img.size
            shapes = []
            for obj in row["targets"][schema]:
                rings = seg.outline_polygons(obj, width, height) if isinstance(obj, dict) else []
                box = _box(obj, width, height) if rings else None
                if box:
                    shapes.append((box, rings, str(obj.get("label", ""))))
            if shapes:
                out.append({"row": row, "path": path, "size": (width, height),
                            "shapes": shapes})
        if missing:
            report.log("warning", "Left out %d %s row(s) with no local image file"
                                  % (missing, split))
        return out

    @staticmethod
    def _image(path: str):
        from PIL import Image
        with Image.open(path) as img:
            return img.convert("RGB")

    def _target(self, rings, width, height, reshaped, padded, low_res, torch):
        """The outline as a soft mask in the low-resolution frame SAM's
        decoder predicts: resized as the processor resizes the image,
        padded bottom-right, then scaled to the decoder's output."""
        import torch.nn.functional as F
        mask = torch.from_numpy(seg.rasterize(rings, width, height).copy()).float()[None, None]
        mask = F.interpolate(mask, size=reshaped, mode="bilinear", align_corners=False)
        mask = F.pad(mask, (0, padded[1] - reshaped[1], 0, padded[0] - reshaped[0]))
        return F.interpolate(mask, size=low_res, mode="bilinear", align_corners=False)[0, 0]

    # ------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch
        import torch.nn.functional as F
        from transformers import SamModel, SamProcessor

        params = {**self.default_params(), **(spec.params or {})}
        schema = spec.primary_schema
        train = self._examples(bundle, "train", schema.name, report)
        val = self._examples(bundle, "val", schema.name, report)
        if not train:
            raise TrainerError("No train image has an outline for %r" % schema.name)
        hf.seed_everything(spec.seed)
        from potato.training.devices import describe_device, resolve_device
        device = resolve_device(spec.limits.device, log=report.log)
        report.log("info", "Training on %s" % describe_device(device))

        report.status("running", "loading %s" % params["model_name"])
        processor = SamProcessor.from_pretrained(params["model_name"])
        model = SamModel.from_pretrained(params["model_name"]).to(device)
        for name, parameter in model.named_parameters():
            parameter.requires_grad = name.startswith("mask_decoder.")
        padded = (int(processor.image_processor.pad_size["height"]),
                  int(processor.image_processor.pad_size["width"]))

        def embed(examples):
            report.status("running", "embedding %d images" % len(examples))
            cache = []
            for n, example in enumerate(examples):
                inputs = processor(images=self._image(example["path"]), return_tensors="pt")
                with torch.no_grad():
                    embedding = model.get_image_embeddings(inputs["pixel_values"].to(device))
                reshaped = tuple(int(v) for v in inputs["reshaped_input_sizes"][0])
                cache.append((example, embedding, reshaped))
                report.progress("embed", n + 1, len(examples))
            return cache

        train_cache = embed(train)
        val_cache = embed(val) if val else []
        n_outlines = sum(len(e["shapes"]) for e in train)
        report.log("info", "%d train images with %d outlines, %d val images"
                           % (len(train), n_outlines, len(val)))

        rng = random.Random(spec.seed)
        jitter = float(params["box_jitter"])

        def jittered(box, width, height):
            x0, y0, x1, y1 = box
            w, h = x1 - x0, y1 - y0
            d = lambda size: (rng.random() * 2 - 1) * jitter * size
            return [max(0.0, x0 + d(w)), max(0.0, y0 + d(h)),
                    min(float(width), x1 + d(w)), min(float(height), y1 + d(h))]

        def scale_boxes(boxes, size, reshaped):
            sy, sx = reshaped[0] / float(size[1]), reshaped[1] / float(size[0])
            return torch.tensor([[b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy]
                                 for b in boxes], dtype=torch.float32, device=device)[None]

        def masks_for(embedding, boxes):
            out = model(image_embeddings=embedding, input_boxes=boxes,
                        multimask_output=False)
            return out.pred_masks[0, :, 0], out.iou_scores[0, :, 0]

        def mean_iou(cache):
            ious = []
            with torch.no_grad():
                for example, embedding, reshaped in cache:
                    boxes = [b for b, _, _ in example["shapes"]]
                    logits, _ = masks_for(embedding, scale_boxes(boxes, example["size"], reshaped))
                    for logit, (_, rings, _) in zip(logits, example["shapes"]):
                        target = self._target(rings, *example["size"], reshaped, padded,
                                              tuple(logit.shape), torch).to(device) > 0.5
                        guess = logit > float(params["mask_threshold"])
                        union = (target | guess).sum().item()
                        ious.append((target & guess).sum().item() / union if union else 1.0)
            return sum(ious) / len(ious) if ious else 0.0

        optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],
                                      lr=float(params["learning_rate"]),
                                      weight_decay=float(params["weight_decay"]))
        model_dir = os.path.join(spec.workdir, hf.MODEL_DIR)
        best, best_epoch, stale, last_loss = None, 0, 0, None
        report.status("running", "fine-tuning")
        epochs = int(params["epochs"])
        for epoch in range(epochs):
            model.train()
            order = list(range(len(train_cache)))
            rng.shuffle(order)
            losses = []
            for step, index in enumerate(order):
                example, embedding, reshaped = train_cache[index]
                shapes = list(example["shapes"])
                rng.shuffle(shapes)
                for start in range(0, len(shapes), int(params["batch_size"])):
                    chunk = shapes[start:start + int(params["batch_size"])]
                    boxes = scale_boxes([jittered(b, *example["size"]) for b, _, _ in chunk],
                                        example["size"], reshaped)
                    logits, _ = masks_for(embedding, boxes)
                    targets = torch.stack([self._target(rings, *example["size"], reshaped,
                                                        padded, tuple(logits.shape[-2:]), torch)
                                           for _, rings, _ in chunk]).to(device)
                    probabilities = torch.sigmoid(logits)
                    dice = 1 - (2 * (probabilities * targets).sum((1, 2)) + 1) / (
                        probabilities.sum((1, 2)) + targets.sum((1, 2)) + 1)
                    loss = F.binary_cross_entropy_with_logits(logits, targets) + dice.mean()
                    optimizer.zero_grad()
                    loss.backward()
                    optimizer.step()
                    losses.append(float(loss.item()))
                if report.should_stop():
                    raise TrainerError("Cancelled")
            last_loss = sum(losses) / len(losses) if losses else None
            score = mean_iou(val_cache) if val_cache else None
            if score is not None:
                report.metric("val", "mask_iou", score, step=epoch + 1)
            report.progress("epoch", epoch + 1, epochs)
            if score is None or best is None or score > best:
                best, best_epoch, stale = score, epoch + 1, 0
                model.save_pretrained(model_dir)
                processor.save_pretrained(model_dir)
            else:
                stale += 1
                if params.get("patience") and stale >= int(params["patience"]):
                    report.log("info", "Stopping: val mask IoU has not improved for "
                                       "%d epochs" % stale)
                    break

        labels = bundle.labels(schema.name)
        version = "%s-%s-%s" % (self.name, schema.name, spec.run_id)
        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "base_model": params["model_name"], "label_order": labels,
            "mask_threshold": float(params["mask_threshold"]),
            "model_version": version, "device": device,
            "n_train": len(train), "n_outlines": n_outlines,
            "bundle_digest": bundle.digest, "selected_epoch": best_epoch})
        metrics = {"n_train": float(len(train)), "n_outlines": float(n_outlines)}
        if best is not None:
            metrics["val_mask_iou"] = round(best, 4)
        if last_loss is not None:
            metrics["train_loss"] = round(last_loss, 4)
        return FitResult(model_version=version, artifact_paths=hf.artifact_files(spec.workdir),
                         metrics=metrics, label_order=labels,
                         selected_on="val" if val_cache else "")

    # ------------------------------------------------------------ predict

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch
        from transformers import SamModel, SamProcessor
        from potato.training.devices import resolve_device

        card = hf.read_card(artifact_dir)
        model_dir = os.path.join(artifact_dir, hf.MODEL_DIR)
        processor = SamProcessor.from_pretrained(model_dir)
        device = resolve_device(spec.limits.device, log=report.log)
        model = SamModel.from_pretrained(model_dir).to(device).eval()
        schema = spec.primary_schema.name
        version = card.get("model_version", "")
        threshold = float(card.get("mask_threshold", 0.0))
        items = [item for item in items if _local_image(item.media)]
        for n, item in enumerate(items):
            image = self._image(item.media)
            width, height = image.size
            prior = item.data.get("prior") or []
            # A box prelabel from an earlier run is a prompt to publish; the
            # annotators' own boxes are prompts to score with, never to show.
            prompts = [(o, False) for o in prior if isinstance(o, dict)]
            if not prompts:
                prompts = [(o, True) for o in (item.data.get("targets") or {}).get(schema) or []
                           if isinstance(o, dict)]
            boxes, labels, heldout = [], [], False
            for obj, from_answer in prompts:
                box = _box(obj, width, height)
                if box:
                    boxes.append(box)
                    labels.append(str(obj.get("label", "")))
                    heldout = heldout or from_answer
            report.progress("predict", n + 1, len(items))
            if not boxes:
                continue
            inputs = processor(images=image, input_boxes=[boxes], return_tensors="pt")
            with torch.no_grad():
                out = model(pixel_values=inputs["pixel_values"].to(device),
                            input_boxes=inputs["input_boxes"].to(device, torch.float32),
                            multimask_output=False)
            masks = processor.post_process_masks(
                out.pred_masks.cpu(), inputs["original_sizes"], inputs["reshaped_input_sizes"],
                mask_threshold=threshold, binarize=True)[0][:, 0].numpy()
            scores = out.iou_scores[0, :, 0].cpu().tolist()
            shapes = []
            for mask, score, label in zip(masks, scores, labels):
                rings = seg.mask_polygons(mask)
                if not rings:
                    continue
                ring = max(rings, key=lambda r: abs(sum(
                    x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(r, r[1:] + r[:1]))))
                shape = seg.client_polygon(ring, label, max(0.0, min(1.0, float(score))),
                                           width, height, version)
                if shape:
                    shapes.append(shape)
            if not shapes:
                continue
            shapes.sort(key=lambda s: -s["confidence"])
            yield PredictionRecord(
                instance_id=item.instance_id, schema_name=schema, payload=shapes,
                confidence=round(sum(s["confidence"] for s in shapes) / len(shapes), 4),
                heldout_only=heldout)
            if report.should_stop():
                return
