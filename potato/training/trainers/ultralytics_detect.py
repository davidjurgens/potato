"""Train a YOLO detector with Ultralytics.

For ``image_annotation`` schemes, like ``torchvision-detect``, and the faster
of the two to train and to run. The bundle's images and boxes are written out
as a YOLO dataset (one ``class cx cy w h`` line per box, normalized), and
``ultralytics.YOLO(...).train`` fits it from a COCO-pretrained checkpoint.
Every shape trains as its bounding box.

**Ultralytics is AGPL-3.0.** A model trained and served with it carries the
AGPL's terms, and Ultralytics sells a separate licence for closed use. The
trainer therefore needs an explicit acknowledgement before it runs: the
Training page asks, the API takes ``accept_licence: true``, and an automatic
retrain needs ``model_training.auto_retrain.accept_licence: true``.

Ultralytics phones home by default: usage analytics, and logging to any of
MLflow, Comet, ClearML, DVC or Neptune that happens to be installed. This
trainer switches all of those off for its own process, in memory, without
changing the user's Ultralytics settings file, and turns off its habit of
pip-installing packages it decides it needs.
"""

from __future__ import annotations

import os
import shutil
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf
from potato.training.trainers.torchvision_detect import (_local_image,
                                                         client_boxes)

INSTALL_HINT = "pip install ultralytics"
_NEEDS = ("torch", "ultralytics", "PIL")
DEFAULT_MODEL = "yolo11n.pt"
WEIGHTS_FILE = "best.pt"

#: Settings that send data somewhere, all off for a training run.
_OUTBOUND_SETTINGS = ("sync", "hub", "clearml", "comet", "dvc", "mlflow",
                      "neptune", "raytune", "wandb", "tensorboard")


def _quiet_ultralytics():
    """Import ultralytics with analytics, integrations and auto-install off."""
    os.environ["YOLO_AUTOINSTALL"] = "false"
    os.environ.setdefault("YOLO_VERBOSE", "false")
    import ultralytics
    from ultralytics.utils import SETTINGS

    for key in _OUTBOUND_SETTINGS:
        if key in SETTINGS:
            # dict's own setter: SettingsManager.__setitem__ would write the
            # change to the user's settings file.
            dict.__setitem__(SETTINGS, key, False)
    try:
        from ultralytics.utils.events import events
        events.enabled = False
    except Exception:  # noqa: BLE001 - older releases have no events module
        pass
    return ultralytics


def _checkpoint(name: str) -> str:
    """Where a named checkpoint lives. Ultralytics downloads a bare name such
    as ``yolo11n.pt`` into the current directory, which in a run is the
    project, or a job directory on a GPU host that is deleted afterwards."""
    if os.path.sep in name or os.path.isfile(name):
        return os.path.abspath(name)
    if not name.endswith(".pt"):
        # An architecture such as yolo11n.yaml: Ultralytics ships it, and
        # builds an untrained model from it with nothing to download.
        return name
    return os.path.join(_cache_dir(), name)


def _cache_dir() -> str:
    cache = os.path.join(os.environ.get("XDG_CACHE_HOME")
                         or os.path.join(os.path.expanduser("~"), ".cache"),
                         "potato", "ultralytics")
    os.makedirs(cache, exist_ok=True)
    return cache


def _yolo_device(device: str) -> str:
    """torch's ``cuda:1`` is ultralytics' ``1``."""
    if device.startswith("cuda"):
        return device.split(":", 1)[1] if ":" in device else "0"
    return device


def yolo_lines(objects: List[Dict[str, Any]], width: int, height: int,
               index: Dict[str, int]) -> List[str]:
    """YOLO label lines (``class cx cy w h``, normalized) for one image."""
    from potato.export.cv_utils import normalize_annotation_object

    lines = []
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
        lines.append("%d %.6f %.6f %.6f %.6f" % (
            index[label], (x0 + x1) / 2 / width, (y0 + y1) / 2 / height,
            (x1 - x0) / width, (y1 - y0) / height))
    return lines


class UltralyticsDetectTrainer(Trainer):
    name: ClassVar[str] = "ultralytics-detect"
    description: ClassVar[str] = (
        "Object detection with Ultralytics YOLO, fine-tuned from a COCO "
        "checkpoint. AGPL-3.0: confirm the licence before the first run.")
    kinds: ClassVar[Tuple[str, ...]] = ("geometry",)
    modalities: ClassVar[Tuple[str, ...]] = ("image",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "AGPL-3.0"
    commercial_use: ClassVar[Optional[bool]] = False
    licence_ack: ClassVar[bool] = True
    licence_url: ClassVar[str] = "https://www.ultralytics.com/license"
    default_model: ClassVar[str] = DEFAULT_MODEL
    #: Ultralytics' validation metrics for this task, and what they are called here.
    metric_keys: ClassVar[Tuple[Tuple[str, str], ...]] = (
        ("metrics/mAP50(B)", "map_50"), ("metrics/mAP50-95(B)", "map_50_95"))
    unit: ClassVar[str] = "boxes"

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": cls.default_model, "epochs": 50, "batch_size": 16,
                "image_size": 640, "learning_rate": None, "patience": 10,
                "flip": True, "mosaic": True, "score_threshold": 0.25,
                "max_detections": 100, "min_instances": 20}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        return {"type": "object", "additionalProperties": False, "properties": {
            "model_name": {"type": "string", "default": cls.default_model,
                           "description": "An Ultralytics checkpoint "
                                          "(yolo11n.pt, yolo11s.pt, "
                                          "yolov8m.pt, ...) or a local .pt."},
            "epochs": dict(hf.COMMON_PARAMS["epochs"], default=50),
            "batch_size": dict(hf.COMMON_PARAMS["batch_size"], default=16),
            "image_size": {"type": "integer", "minimum": 32, "default": 640,
                           "description": "Training and prediction size in "
                                          "pixels (a multiple of 32)."},
            "learning_rate": {"type": ["number", "null"], "default": None,
                              "description": "Initial learning rate; null "
                                             "keeps Ultralytics' default."},
            "patience": {"type": "integer", "minimum": 1, "default": 10,
                         "description": "Epochs without a better val mAP "
                                        "before stopping."},
            "flip": {"type": "boolean", "default": True,
                     "description": "Random horizontal flips in training."},
            "mosaic": {"type": "boolean", "default": True,
                       "description": "Ultralytics' mosaic augmentation."},
            "score_threshold": {"type": "number", "minimum": 0, "maximum": 1,
                                "default": 0.25},
            "max_detections": {"type": "integer", "minimum": 1,
                               "default": 100},
            "min_instances": hf.COMMON_PARAMS["min_instances"],
        }}

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
                "Only %d annotated images in the train split; this trainer "
                "needs at least %d. Annotate more, or lower min_instances."
                % (bundle.split_size("train"), int(params["min_instances"])))
        if not bundle.labels(schema.name):
            problems.append("Schema %r has no labelled shapes in the data."
                            % schema.name)
        return problems

    # ------------------------------------------------------------ data

    def _write_dataset(self, bundle: BundleRef, schema: str, labels: List[str],
                       root: str, report: ProgressReporter) -> Dict[str, int]:
        """The YOLO directory layout, images symlinked. Returns box counts."""
        from PIL import Image

        index = {label: i for i, label in enumerate(labels)}
        counts: Dict[str, int] = {}
        for split in ("train", "val"):
            image_dir = os.path.join(root, "images", split)
            label_dir = os.path.join(root, "labels", split)
            os.makedirs(image_dir, exist_ok=True)
            os.makedirs(label_dir, exist_ok=True)
            n_images = missing = 0
            for row in hf.rows_with_target(bundle.read_split(split), schema):
                path = bundle.resolve_media(row["media"]) if row.get("media") else None
                if not _local_image(path):
                    missing += 1
                    continue
                with Image.open(path) as img:
                    width, height = img.size
                lines = self._label_lines(row["targets"][schema], width, height,
                                          index)
                if not lines:
                    continue
                stem = "%06d" % n_images
                ext = os.path.splitext(path)[1].lower() or ".jpg"
                link = os.path.join(image_dir, stem + ext)
                try:
                    os.symlink(os.path.abspath(path), link)
                except OSError:
                    shutil.copy2(path, link)
                with open(os.path.join(label_dir, stem + ".txt"), "w") as fh:
                    fh.write("\n".join(lines) + "\n")
                n_images += 1
                counts[split + "_boxes"] = counts.get(split + "_boxes", 0) + len(lines)
            counts[split] = n_images
            if missing:
                report.log("warning", "Left out %d %s row(s) with no local "
                                      "image file" % (missing, split))
        with open(os.path.join(root, "data.yaml"), "w") as fh:
            # Without a val split, Ultralytics validates on train: the curve
            # is then a training curve, and the run says so.
            val = "images/val" if counts.get("val") else "images/train"
            fh.write("path: %s\ntrain: images/train\nval: %s\nnames:\n"
                     % (os.path.abspath(root), val))
            for i, label in enumerate(labels):
                fh.write("  %d: %s\n" % (i, _yaml_scalar(label)))
        return counts

    def _label_lines(self, objects, width: int, height: int,
                     index: Dict[str, int]) -> List[str]:
        return yolo_lines(objects, width, height, index)

    def _payload(self, result, labels: List[str], width: int, height: int,
                 version: str) -> List[Dict[str, Any]]:
        boxes = result.boxes
        return client_boxes(
            boxes.xyxy.cpu().tolist(), boxes.conf.cpu().tolist(),
            [int(c) + 1 for c in boxes.cls.cpu().tolist()], labels,
            width, height, version)

    # ------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        _quiet_ultralytics()
        from ultralytics import YOLO

        params = {**self.default_params(), **(spec.params or {})}
        schema = spec.primary_schema
        labels = bundle.labels(schema.name)
        workdir = os.path.abspath(spec.workdir)
        data_root = os.path.join(workdir, "yolo_data")
        counts = self._write_dataset(bundle, schema.name, labels, data_root,
                                     report)
        if not counts.get("train"):
            raise TrainerError("None of the train images has usable %s for %r"
                               % (self.unit, schema.name))
        report.log("info", "%d train images with %d %s, %d val images, "
                           "%d labels" % (counts["train"],
                                          counts.get("train_boxes", 0),
                                          self.unit, counts.get("val", 0),
                                          len(labels)))

        hf.seed_everything(spec.seed)
        device = hf.pick_device(spec, report)
        report.status("running", "loading %s" % params["model_name"])
        model = YOLO(_checkpoint(str(params["model_name"])))
        epochs = int(params["epochs"])

        def on_batch_end(trainer):
            if report.should_stop():
                raise TrainerError("Cancelled during training")

        def on_epoch_end(trainer):
            metrics = getattr(trainer, "metrics", {}) or {}
            for key, name in self.metric_keys:
                if key in metrics:
                    report.metric("val", name, float(metrics[key]),
                                  step=trainer.epoch + 1)
            report.progress("train", trainer.epoch + 1, epochs)

        model.add_callback("on_train_batch_end", on_batch_end)
        model.add_callback("on_fit_epoch_end", on_epoch_end)

        train_args = {
            "data": os.path.join(data_root, "data.yaml"), "epochs": epochs,
            "batch": int(params["batch_size"]), "imgsz": int(params["image_size"]),
            "device": _yolo_device(device), "project": workdir,
            "name": "yolo_run", "exist_ok": True, "seed": int(spec.seed),
            "deterministic": True, "patience": int(params["patience"]),
            "fliplr": 0.5 if params["flip"] else 0.0,
            "mosaic": 1.0 if params["mosaic"] else 0.0,
            # In-process loading: worker processes would outlive a cancel.
            "workers": 0, "plots": False, "verbose": False}
        if params.get("learning_rate"):
            train_args["lr0"] = float(params["learning_rate"])
        report.status("running", "fine-tuning")
        # Ultralytics' AMP check on CUDA loads yolo11n.pt by bare name, which
        # downloads it into the working directory; run from the cache.
        here = os.getcwd()
        os.chdir(_cache_dir())
        try:
            model.train(**train_args)
        finally:
            os.chdir(here)

        run_dir = os.path.join(workdir, "yolo_run")
        best = os.path.join(run_dir, "weights", "best.pt")
        if not os.path.isfile(best):
            best = os.path.join(run_dir, "weights", "last.pt")
        if not os.path.isfile(best):
            raise TrainerError("Ultralytics finished without writing weights "
                               "under %s" % run_dir)
        os.makedirs(os.path.join(spec.workdir, hf.MODEL_DIR), exist_ok=True)
        shutil.copy2(best, os.path.join(spec.workdir, hf.MODEL_DIR, WEIGHTS_FILE))
        results_csv = os.path.join(run_dir, "results.csv")
        if os.path.isfile(results_csv):
            shutil.copy2(results_csv, os.path.join(spec.workdir, "results.csv"))
        # The run directory holds last.pt and optimizer state, and the data
        # directory only symlinks: neither is worth copying back from a GPU host.
        shutil.rmtree(run_dir, ignore_errors=True)
        shutil.rmtree(data_root, ignore_errors=True)

        version = "%s-%s-%s" % (self.name, schema.name, spec.run_id)
        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "base_model": params["model_name"], "label_order": labels,
            "image_size": int(params["image_size"]),
            "score_threshold": float(params["score_threshold"]),
            "max_detections": int(params["max_detections"]),
            "model_version": version, "device": device,
            "n_train": counts["train"], "bundle_digest": bundle.digest,
            "licence": self.licence})
        return FitResult(
            model_version=version,
            artifact_paths=hf.artifact_files(spec.workdir),
            metrics={"n_train": float(counts["train"]),
                     "n_boxes": float(counts.get("train_boxes", 0))},
            label_order=labels, selected_on="val" if counts.get("val") else "")

    # ------------------------------------------------------------ predict

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        _quiet_ultralytics()
        from ultralytics import YOLO

        card = hf.read_card(artifact_dir)
        labels = card["label_order"]
        device = hf.pick_device(spec, report)
        model = YOLO(os.path.join(artifact_dir, hf.MODEL_DIR, WEIGHTS_FILE))
        usable = [item for item in items if _local_image(item.media)]
        for start in range(0, len(usable), 32):
            chunk = usable[start:start + 32]
            results = model.predict(
                source=[item.media for item in chunk],
                conf=float(card.get("score_threshold", 0.25)),
                max_det=int(card.get("max_detections", 100)),
                imgsz=int(card.get("image_size", 640)),
                device=_yolo_device(device), verbose=False)
            for item, result in zip(chunk, results):
                height, width = result.orig_shape[:2]
                payload = self._payload(result, labels, width, height,
                                        card.get("model_version", ""))
                if not payload:
                    continue
                confidence = sum(o["confidence"] for o in payload) / len(payload)
                yield PredictionRecord(instance_id=item.instance_id,
                                       schema_name=card["schema"],
                                       payload=payload,
                                       confidence=round(confidence, 4))
            report.progress("predict", start + len(chunk), len(usable))
            if report.should_stop():
                return


def _yaml_scalar(value: str) -> str:
    """A label as a YAML scalar that stays a string (``yes``, ``1``, ``a: b``)."""
    import json
    return json.dumps(str(value))
