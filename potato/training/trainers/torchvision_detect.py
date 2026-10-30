"""Train an object detector on the boxes annotators drew.

For ``image_annotation`` schemes. Fine-tunes a torchvision Faster R-CNN,
starting from its COCO weights, with a new box head sized to the scheme's
labels. Every shape type becomes its bounding box for training: polygons,
ellipses, masks and freeform shapes all have one, so a polygon study trains
a box detector rather than being refused.

Predictions are boxes in the image widget's own object shape (normalized
coordinates, ``source: "ai"``, the detector's score as ``confidence``), so
write-back shows them as editable shapes and the held-out score is COCO mAP
against the annotators' boxes.

torchvision's code is BSD-3-Clause. Its COCO-pretrained weights are trained
on COCO, whose images carry their own licences; check the weights' terms
before shipping a model commercially.
"""

from __future__ import annotations

import os
import random
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf

INSTALL_HINT = "pip install 'potato-annotation[train-vision]'"
_NEEDS = ("torch", "torchvision", "PIL")
WEIGHTS_FILE = "detector.pt"

#: Builder name -> the weights enum torchvision publishes for it.
ARCHITECTURES = {
    "fasterrcnn_mobilenet_v3_large_fpn":
        "FasterRCNN_MobileNet_V3_Large_FPN_Weights",
    "fasterrcnn_mobilenet_v3_large_320_fpn":
        "FasterRCNN_MobileNet_V3_Large_320_FPN_Weights",
    "fasterrcnn_resnet50_fpn": "FasterRCNN_ResNet50_FPN_Weights",
    "fasterrcnn_resnet50_fpn_v2": "FasterRCNN_ResNet50_FPN_V2_Weights",
}
DEFAULT_ARCH = "fasterrcnn_mobilenet_v3_large_fpn"


def _local_image(path: Optional[str]) -> bool:
    return bool(path) and not str(path).startswith(("http://", "https://")) \
        and os.path.isfile(str(path))


def boxes_from_objects(objects: List[Dict[str, Any]], width: int, height: int,
                       index: Dict[str, int]) -> Tuple[List[List[float]], List[int]]:
    """``(xyxy pixel boxes, class ids)`` for one image's annotated objects.

    Class ids start at 1; torchvision's detectors reserve 0 for background.
    Objects with a label outside *index*, or a box under a pixel wide, are
    left out.
    """
    from potato.export.cv_utils import normalize_annotation_object

    boxes, classes = [], []
    for obj in objects or []:
        label = str(obj.get("label", ""))
        if label not in index:
            continue
        canonical = normalize_annotation_object(obj, width, height)
        if not canonical or not canonical.get("bbox"):
            continue
        x, y, w, h = (float(v) for v in canonical["bbox"][:4])
        x0, y0 = max(0.0, x), max(0.0, y)
        x1, y1 = min(float(width), x + w), min(float(height), y + h)
        if x1 - x0 < 1 or y1 - y0 < 1:
            continue
        boxes.append([x0, y0, x1, y1])
        classes.append(index[label] + 1)
    return boxes, classes


def client_boxes(boxes, scores, classes, labels: List[str], width: int,
                 height: int, model_version: str) -> List[Dict[str, Any]]:
    """Detections as image-widget objects, most confident first."""
    out = []
    for (x0, y0, x1, y1), score, cls in sorted(
            zip(boxes, scores, classes), key=lambda t: -t[1]):
        if not 1 <= int(cls) <= len(labels):
            continue
        out.append({
            "type": "bbox", "label": labels[int(cls) - 1], "color": "",
            "coordinates": {"x": round(x0 / width, 5), "y": round(y0 / height, 5),
                            "width": round((x1 - x0) / width, 5),
                            "height": round((y1 - y0) / height, 5)},
            "source": "ai", "ai_model": model_version,
            "confidence": round(float(score), 4)})
    return out


class TorchvisionDetectTrainer(Trainer):
    name: ClassVar[str] = "torchvision-detect"
    description: ClassVar[str] = (
        "Object detection: fine-tunes a torchvision Faster R-CNN on the "
        "annotated boxes (any shape trains as its bounding box).")
    kinds: ClassVar[Tuple[str, ...]] = ("geometry",)
    modalities: ClassVar[Tuple[str, ...]] = ("image",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "BSD-3-Clause"
    commercial_use: ClassVar[Optional[bool]] = True
    #: Builder name -> weights enum, and the default; a subclass swaps both.
    architectures: ClassVar[Dict[str, str]] = ARCHITECTURES
    default_arch: ClassVar[str] = DEFAULT_ARCH
    #: What one training target is, for the run log.
    unit: ClassVar[str] = "boxes"

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": cls.default_arch, "pretrained": True, "epochs": 15,
                "batch_size": 4, "gradient_accumulation": 1,
                "learning_rate": 1e-4, "weight_decay": 1e-4,
                "warmup_ratio": 0.1, "patience": 4, "flip": True,
                "min_size": None, "score_threshold": 0.25,
                "max_detections": 100, "min_instances": 20}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = {key: hf.COMMON_PARAMS[key] for key in
                 ("epochs", "batch_size", "gradient_accumulation",
                  "weight_decay", "warmup_ratio", "patience", "min_instances")}
        props["epochs"] = dict(props["epochs"], default=15)
        props["batch_size"] = dict(props["batch_size"], default=4)
        props["patience"] = dict(props["patience"], default=4)
        props["weight_decay"] = dict(props["weight_decay"], default=1e-4)
        props.update({
            "model_name": {"type": "string", "enum": sorted(cls.architectures),
                           "default": cls.default_arch,
                           "description": "The torchvision detector."},
            "pretrained": {"type": "boolean", "default": True,
                           "description": "Start from torchvision's COCO "
                                          "weights (downloaded once)."},
            "learning_rate": {"type": "number", "exclusiveMinimum": 0,
                              "default": 1e-4},
            "flip": {"type": "boolean", "default": True,
                     "description": "Random horizontal flips in training."},
            "min_size": {"type": ["integer", "null"], "minimum": 32,
                         "default": None,
                         "description": "Shorter image side the detector "
                                        "resizes to; null keeps the "
                                        "architecture's own."},
            "score_threshold": {"type": "number", "minimum": 0, "maximum": 1,
                                "default": 0.25,
                                "description": "Detections below this score "
                                               "are dropped."},
            "max_detections": {"type": "integer", "minimum": 1,
                               "default": 100},
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
        if params["model_name"] not in self.architectures:
            problems.append("Unknown model %r. Choose one of: %s."
                            % (params["model_name"],
                               ", ".join(sorted(self.architectures))))
        if bundle.split_size("train") < int(params["min_instances"]):
            problems.append(
                "Only %d annotated images in the train split; this trainer "
                "needs at least %d. Annotate more, or lower min_instances."
                % (bundle.split_size("train"), int(params["min_instances"])))
        if not bundle.labels(schema.name):
            problems.append("Schema %r has no labelled shapes in the data."
                            % schema.name)
        return problems

    # ------------------------------------------------------------ model

    def _build(self, params: Dict[str, Any], n_classes: int, pretrained: bool):
        from torchvision.models import detection
        from torchvision.models.detection.faster_rcnn import FastRCNNPredictor

        arch = params["model_name"]
        builder = getattr(detection, arch)
        kwargs: Dict[str, Any] = {}
        if params.get("min_size"):
            kwargs["min_size"] = int(params["min_size"])
            kwargs["max_size"] = max(int(params["min_size"]),
                                     int(int(params["min_size"]) * 1333 / 800))
        kwargs["box_detections_per_img"] = int(params.get("max_detections", 100))
        kwargs["box_score_thresh"] = 0.01
        if pretrained:
            weights = getattr(detection, self.architectures[arch]).DEFAULT
            model = builder(weights=weights, **kwargs)
        else:
            model = builder(weights=None, weights_backbone=None,
                            num_classes=n_classes, **kwargs)
        predictor = model.roi_heads.box_predictor
        if predictor.cls_score.out_features != n_classes:
            model.roi_heads.box_predictor = FastRCNNPredictor(
                predictor.cls_score.in_features, n_classes)
        self._replace_heads(model, n_classes)
        return model

    #: Whether the model trains on Apple's Metal (mps). Faster R-CNN does
    #: not, at a usable speed: at the default image size one step took 396 s
    #: there against 4.6 s per epoch on the CPU (audit 98), with torch 2.8.
    mps_ok: ClassVar[bool] = False

    def _device(self, spec: TrainingSpec, report: ProgressReporter) -> str:
        from potato.training.devices import describe_device, resolve_device

        device = resolve_device(spec.limits.device, log=report.log)
        if device.startswith("mps") and not self.mps_ok:
            report.log("warning", "%s does not run on Apple's Metal (mps) "
                                  "with this torch; using the CPU" % self.name)
            device = "cpu"
        # Said once, after the fallback: "Training on Apple Metal" followed
        # by a switch to the CPU read as two runs.
        report.log("info", "Training on %s" % describe_device(device))
        return device

    def _replace_heads(self, model, n_classes: int) -> None:
        """Size any further heads to the labels. Boxes need none."""

    def _row_target(self, objects, width: int, height: int,
                    index: Dict[str, int]) -> Dict[str, Any]:
        """One image's training target; ``boxes`` empty means skip it."""
        boxes, classes = boxes_from_objects(objects, width, height, index)
        return {"boxes": boxes, "classes": classes}

    def _target_tensors(self, target: Dict[str, Any], width: int, height: int,
                        flip: bool, device: str) -> Dict[str, Any]:
        import torch

        boxes = torch.tensor(target["boxes"], dtype=torch.float32)
        if flip:
            boxes = torch.stack([width - boxes[:, 2], boxes[:, 1],
                                 width - boxes[:, 0], boxes[:, 3]], dim=1)
        return {"boxes": boxes.to(device),
                "labels": torch.tensor(target["classes"], dtype=torch.int64,
                                       device=device)}

    def _payload(self, out, keep, labels: List[str], width: int, height: int,
                 version: str) -> List[Dict[str, Any]]:
        """One image's detections as image-widget objects."""
        return client_boxes(out["boxes"][keep].cpu().tolist(),
                            out["scores"][keep].cpu().tolist(),
                            out["labels"][keep].cpu().tolist(), labels,
                            width, height, version)

    # ------------------------------------------------------------ data

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

    @staticmethod
    def _load(path: str):
        from PIL import Image
        from torchvision.transforms.functional import to_tensor

        with Image.open(path) as img:
            img = img.convert("RGB")
            return to_tensor(img), img.size

    # ------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch

        params = {**self.default_params(), **(spec.params or {})}
        # Detection losses are not autocast-safe across torchvision ops.
        params["precision"] = "fp32"
        schema = spec.primary_schema
        labels = bundle.labels(schema.name)
        index = {label: i for i, label in enumerate(labels)}

        train = self._image_rows(bundle, "train", schema.name, report)
        val = self._image_rows(bundle, "val", schema.name, report)
        if not train:
            raise TrainerError("No train rows with a local image for %r"
                               % schema.name)

        hf.seed_everything(spec.seed)
        device = self._device(spec, report)
        report.status("running", "loading %s" % params["model_name"])
        model = self._build(params, len(labels) + 1, bool(params["pretrained"]))
        model.to(device)
        flip_rng = random.Random(spec.seed)

        targets: Dict[str, Dict[str, Any]] = {}
        n_boxes = 0
        for row in train:
            _, (w, h) = self._load(row["image_path"])
            target = self._row_target(row["targets"][schema.name], w, h, index)
            targets[row["instance_id"]] = target
            n_boxes += len(target["boxes"])
        train = [r for r in train if targets[r["instance_id"]]["boxes"]]
        if not train:
            raise TrainerError("None of the train images has usable %s for %r"
                               % (self.unit, schema.name))
        report.log("info", "%d train images with %d %s, %d val images, "
                           "%d labels" % (len(train), n_boxes, self.unit,
                                          len(val), len(labels)))

        def loss_of(batch):
            images, batch_targets = [], []
            for row in batch:
                image, (w, h) = self._load(row["image_path"])
                flip = bool(params["flip"]) and flip_rng.random() < 0.5
                if flip:
                    image = image.flip(-1)
                images.append(image.to(device))
                batch_targets.append(self._target_tensors(
                    targets[row["instance_id"]], w, h, flip, device))
            losses = model(images, batch_targets)
            return sum(losses.values())

        version = "%s-%s-%s" % (self.name, schema.name, spec.run_id)
        selected = {"best": None, "saved": False}

        def save():
            os.makedirs(os.path.join(spec.workdir, hf.MODEL_DIR), exist_ok=True)
            torch.save(model.state_dict(),
                       os.path.join(spec.workdir, hf.MODEL_DIR, WEIGHTS_FILE))

        def on_epoch_end(epoch):
            if not val:
                return None
            from potato.training.evaluation import HEADLINE, score_split
            predictions = {
                (str(row["instance_id"]), schema.name): payload
                for row, payload in self._detect(
                    model, [(r, r["image_path"]) for r in val], labels,
                    params, device, version)}
            metrics, _ = score_split(val, predictions, schema.name,
                                     schema.kind)
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
            "base_model": params["model_name"], "label_order": labels,
            "min_size": params.get("min_size"),
            "max_detections": int(params["max_detections"]),
            "score_threshold": float(params["score_threshold"]),
            "model_version": version, "device": device,
            "n_train": len(train), "n_boxes": n_boxes,
            "bundle_digest": bundle.digest,
            "selected_epoch": summary["best_epoch"]})

        metrics = {"n_train": float(len(train)), "n_boxes": float(n_boxes),
                   "train_seconds": summary["train_seconds"],
                   "epochs_run": float(summary["epochs_run"])}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        return FitResult(model_version=version,
                         artifact_paths=hf.artifact_files(spec.workdir),
                         metrics=metrics, label_order=labels,
                         selected_on="val" if val else "")

    # ------------------------------------------------------------ predict

    def _detect(self, model, pairs, labels: List[str], params: Dict[str, Any],
                device: str, version: str,
                report: Optional[ProgressReporter] = None):
        """``(key, payload)`` per image, where *pairs* is ``(key, path)``."""
        import torch

        threshold = float(params.get("score_threshold", 0.25))
        size = max(1, int(params.get("batch_size", 4)))
        model.eval()
        for start in range(0, len(pairs), size):
            chunk = pairs[start:start + size]
            loaded = [self._load(path) for _, path in chunk]
            with torch.inference_mode():
                outputs = model([image.to(device) for image, _ in loaded])
            for (key, _), (_, (w, h)), out in zip(chunk, loaded, outputs):
                keep = out["scores"] >= threshold
                yield key, self._payload(out, keep, labels, w, h, version)
            if report is not None:
                report.progress("predict", start + len(chunk), len(pairs))
                if report.should_stop():
                    return

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch

        card = hf.read_card(artifact_dir)
        labels = card["label_order"]
        params = {**self.default_params(), "model_name": card["base_model"],
                  "min_size": card.get("min_size"),
                  "max_detections": card.get("max_detections", 100),
                  "score_threshold": card.get("score_threshold", 0.25)}
        device = self._device(spec, report)
        model = self._build(params, len(labels) + 1, pretrained=False)
        state = torch.load(os.path.join(artifact_dir, hf.MODEL_DIR,
                                        WEIGHTS_FILE), map_location="cpu")
        model.load_state_dict(state)
        model.to(device)

        # An item with no readable image gets no prediction rather than a
        # confident empty one.
        usable = [(item, item.media) for item in items
                  if _local_image(item.media)]
        for item, payload in self._detect(model, usable, labels, params,
                                          device, card.get("model_version", ""),
                                          report):
            if not payload:
                continue
            confidence = sum(o["confidence"] for o in payload) / len(payload)
            yield PredictionRecord(instance_id=item.instance_id,
                                   schema_name=card["schema"], payload=payload,
                                   confidence=round(confidence, 4))
