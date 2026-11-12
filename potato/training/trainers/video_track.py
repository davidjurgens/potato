"""Object tracking in video: a frame detector, then detections linked into tracks.

For ``video_annotation`` schemes in ``tracking`` or ``combined`` mode. The
annotated tracks are sampled at ``frame_fps`` frames per second: each
sampled frame is read from the video with OpenCV, and each track's box there
is interpolated between its keyframes, as the widget draws it. A torchvision
Faster R-CNN (``torchvision-detect``'s model and training) is fine-tuned on
those frames and boxes.

Prediction samples each video at ``predict_fps``, detects on every sampled
frame, and links the detections into tracks by box overlap from frame to
frame (``training.tracking.associate``: best one-to-one match on IoU within
a label; a track missed for more than ``max_age`` sampled frames ends; a
track of fewer than ``min_track_keyframes`` detections is dropped). Each
detection becomes a keyframe, so the widget interpolates between them as it
does between an annotator's.

Held-out scores are MOTA and IDF1 against the annotated tracks
(``training.tracking.score_tracks``). Needs torch, torchvision and OpenCV
(``cv2``) on the training host.
"""

from __future__ import annotations

import hashlib
import os
import random
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf
from potato.training.trainers.torchvision_detect import (WEIGHTS_FILE,
                                                         TorchvisionDetectTrainer)

_NEEDS = ("torch", "torchvision", "cv2")
INSTALL_HINT = "pip install 'potato-annotation[train-vision]' opencv-python"


def _local(path: Optional[str]) -> bool:
    return bool(path) and not str(path).startswith(("http://", "https://")) \
        and os.path.isfile(str(path))


def read_frames(path: str, times: List[float], dest: str) -> Tuple[List[Tuple[float, str]],
                                                                   Dict[str, Any]]:
    """Frames of the video at *times* (seconds), written as JPEGs under
    *dest*: ``([(time, jpg)], {fps, duration, width, height})``. A time past
    the end is skipped."""
    import cv2
    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        raise TrainerError("OpenCV could not open %s" % os.path.basename(path))
    fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
    count = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
    meta = {"fps": fps, "duration": count / fps if fps else 0.0,
            "width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
            "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)}
    os.makedirs(dest, exist_ok=True)
    out = []
    try:
        for t in times:
            if meta["duration"] and t > meta["duration"]:
                continue
            capture.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = capture.read()
            if not ok:
                continue
            name = os.path.join(dest, "%09.3f.jpg" % t)
            cv2.imwrite(name, frame)
            out.append((t, name))
    finally:
        capture.release()
    return out, meta


class VideoTrackTrainer(TorchvisionDetectTrainer):
    name: ClassVar[str] = "video-track"
    description: ClassVar[str] = (
        "Object tracking in video: fine-tunes a Faster R-CNN on frames sampled "
        "from the annotated tracks, then links detections across frames.")
    kinds: ClassVar[Tuple[str, ...]] = ("track",)
    modalities: ClassVar[Tuple[str, ...]] = ("video",)
    annotation_types: ClassVar[Tuple[str, ...]] = ("video_annotation",)
    install_hint: ClassVar[str] = INSTALL_HINT

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return dict(super().default_params(), frame_fps=2.0, predict_fps=None,
                    match_iou=0.3, max_age=2, new_track_score=0.5, min_track_keyframes=2,
                    min_instances=2)

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        schema = super().params_schema()
        props = dict(schema["properties"])
        props["min_instances"] = dict(props["min_instances"], default=2,
                                      description="Annotated videos needed in the train split.")
        props.update({
            "frame_fps": {"type": "number", "exclusiveMinimum": 0, "default": 2.0,
                          "description": "Frames per second sampled from each annotated "
                                         "video to train on."},
            "predict_fps": {"type": ["number", "null"], "default": None,
                            "description": "Frames per second detected on to predict "
                                           "(default: frame_fps)."},
            "match_iou": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.3,
                          "description": "Box overlap at which a detection continues a "
                                         "track."},
            "max_age": {"type": "integer", "minimum": 0, "default": 2,
                        "description": "Sampled frames a track may go undetected before "
                                       "it ends."},
            "new_track_score": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5,
                                "description": "Lowest score at which a detection no track "
                                               "takes starts a new one."},
            "min_track_keyframes": {"type": "integer", "minimum": 1, "default": 2,
                                    "description": "Detections a predicted track needs to be "
                                                   "written back. The widget holds a "
                                                   "one-keyframe track over the whole video."},
        })
        return dict(schema, properties=props)

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        problems = []
        if schema.kind not in self.kinds:
            problems.append("Schema %r is %s; this trainer handles video_annotation tracks "
                            "(mode: tracking or combined)." % (schema.name, schema.kind))
        n = len(hf.rows_with_target(bundle.read_split("train"), schema.name))
        if n < int(params["min_instances"]):
            problems.append("Only %d annotated videos in the train split; this trainer needs "
                            "at least %d." % (n, int(params["min_instances"])))
        return problems

    # ------------------------------------------------------------ frames

    def _frame_rows(self, bundle: BundleRef, split: str, schema: str, params: Dict[str, Any],
                    workdir: str, report: ProgressReporter) -> List[Dict[str, Any]]:
        """One row per sampled frame: its JPEG and the boxes there, as
        image-widget objects."""
        from potato.training.tracking import box_at
        rows, missing, unreadable = [], 0, []
        for row in hf.rows_with_target(bundle.read_split(split), schema):
            path = bundle.resolve_media(row["media"]) if row.get("media") else None
            if not _local(path):
                missing += 1
                continue
            target = row["targets"][schema]
            fps = float(target["fps"])
            last = max(k[0] for t in target["tracks"] for k in t["keyframes"])
            step = 1.0 / float(params["frame_fps"])
            times = [n * step for n in range(int((last / fps) / step) + 1)]
            dest = os.path.join(workdir, "frames",
                                hashlib.sha1(str(row["instance_id"]).encode()).hexdigest()[:12])
            try:
                frames, _ = read_frames(path, times, dest)
            except TrainerError as exc:
                # One video OpenCV cannot read is one item left out, not the run.
                unreadable.append("%s (%s)" % (row["instance_id"], exc))
                continue
            for t, jpg in frames:
                frame = int(round(t * fps))
                objects = []
                for track in target["tracks"]:
                    box = box_at(track, frame)
                    if box is not None:
                        objects.append({"type": "bbox", "label": track["label"],
                                        "coordinates": dict(zip(("x", "y", "width", "height"),
                                                                box))})
                rows.append({"instance_id": "%s@%d" % (row["instance_id"], frame),
                             "image_path": jpg, "targets": {schema: objects}})
        if missing:
            report.log("warning", "Left out %d %s video(s) with no local file" % (missing, split))
        if unreadable:
            report.log("warning", "Left out %d %s video(s) OpenCV could not read: %s"
                       % (len(unreadable), split, "; ".join(unreadable[:5])))
        return rows

    # ------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch
        params = {**self.default_params(), **(spec.params or {})}
        params["precision"] = "fp32"
        schema = spec.primary_schema
        labels = bundle.labels(schema.name)
        index = {label: i for i, label in enumerate(labels)}
        train = self._frame_rows(bundle, "train", schema.name, params, spec.workdir, report)
        val = self._frame_rows(bundle, "val", schema.name, params, spec.workdir, report)
        targets = {}
        for row in train:
            _, (w, h) = self._load(row["image_path"])
            targets[row["instance_id"]] = self._row_target(row["targets"][schema.name], w, h,
                                                           index)
        # A frame with nobody in it teaches "nothing here", as a negative tile does.
        if not any(t["boxes"] for t in targets.values()):
            raise TrainerError("No sampled frame of the train videos has a track box")
        hf.seed_everything(spec.seed)
        device = self._device(spec, report)
        model = self._build(params, len(labels) + 1, bool(params["pretrained"])).to(device)
        flip_rng = random.Random(spec.seed)
        report.log("info", "%d train frames (%d boxes), %d val frames, %d labels"
                   % (len(train), sum(len(t["boxes"]) for t in targets.values()), len(val),
                      len(labels)))

        def loss_of(batch):
            images, batch_targets = [], []
            for row in batch:
                image, (w, h) = self._load(row["image_path"])
                flip = bool(params["flip"]) and flip_rng.random() < 0.5
                if flip:
                    image = image.flip(-1)
                images.append(image.to(device))
                batch_targets.append(self._target_tensors(targets[row["instance_id"]], w, h,
                                                          flip, device))
            return sum(model(images, batch_targets).values())

        version = "%s-%s-%s" % (self.name, schema.name, spec.run_id)
        weights = os.path.join(spec.workdir, hf.MODEL_DIR, WEIGHTS_FILE)
        os.makedirs(os.path.dirname(weights), exist_ok=True)
        selected = {"best": None}

        def on_epoch_end(epoch):
            if not val:
                return None
            from potato.training.evaluation import score_split
            predictions = {(str(row["instance_id"]), schema.name): payload
                           for row, payload in self._detect(
                               model, [(r, r["image_path"]) for r in val], labels,
                               params, device, version)}
            metrics, _ = score_split(val, predictions, schema.name, "geometry")
            score = metrics.get("map_50", 0.0)
            report.metric("val", "frame_map_50", score, step=epoch + 1)
            if selected["best"] is None or score > selected["best"]:
                selected["best"] = score
                torch.save(model.state_dict(), weights)
            model.train()
            return score

        report.status("running", "fine-tuning")
        summary = hf.train_loop(model, train, params, loss_of, report, device=device,
                                seed=spec.seed, on_epoch_end=on_epoch_end)
        if selected["best"] is None:
            torch.save(model.state_dict(), weights)
        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "base_model": params["model_name"], "label_order": labels,
            "min_size": params.get("min_size"), "max_detections": int(params["max_detections"]),
            "score_threshold": float(params["score_threshold"]),
            "frame_fps": float(params["frame_fps"]),
            "predict_fps": float(params.get("predict_fps") or params["frame_fps"]),
            "match_iou": float(params["match_iou"]), "max_age": int(params["max_age"]),
            "new_track_score": float(params["new_track_score"]),
            "min_track_keyframes": int(params["min_track_keyframes"]),
            "model_version": version, "device": device, "n_train": len(train),
            "bundle_digest": bundle.digest, "selected_epoch": summary["best_epoch"]})
        metrics = {"n_train_frames": float(len(train)), "train_seconds": summary["train_seconds"],
                   "epochs_run": float(summary["epochs_run"])}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        return FitResult(model_version=version, artifact_paths=hf.artifact_files(spec.workdir),
                         metrics=metrics, label_order=labels,
                         selected_on="val" if val else "")

    # ------------------------------------------------------------ predict

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch
        from potato.training.tracking import associate, track_payload
        card = hf.read_card(artifact_dir)
        labels = list(card["label_order"])
        params = dict(self.default_params(), model_name=card["base_model"],
                      min_size=card.get("min_size"), max_detections=card["max_detections"],
                      score_threshold=card["score_threshold"])
        device = self._device(spec, report)
        model = self._build(params, len(labels) + 1, False)
        model.load_state_dict(torch.load(os.path.join(artifact_dir, hf.MODEL_DIR, WEIGHTS_FILE),
                                         map_location="cpu"))
        model.to(device)
        version = card.get("model_version", "")
        fps_out = float(card.get("predict_fps") or 2.0)
        scheme_fps = float((spec.params or {}).get("_video_fps") or 30.0)
        items = [item for item in items if _local(item.media)]
        for n, item in enumerate(items):
            dest = os.path.join(spec.workdir, "predict_frames",
                                hashlib.sha1(str(item.instance_id).encode()).hexdigest()[:12])
            try:
                _, meta = read_frames(item.media, [], dest)
                times = [k / fps_out for k in range(int(meta["duration"] * fps_out) + 1)]
                frames, meta = read_frames(item.media, times, dest)
            except TrainerError as exc:
                report.log("warning", "Left out %s: %s" % (item.instance_id, exc))
                continue
            detections = []
            for (t, _), (_, payload) in zip(frames, self._detect(
                    model, [(t, jpg) for t, jpg in frames], labels, params, device, version)):
                found = [{"label": obj["label"],
                          "box": [obj["coordinates"][k] for k in ("x", "y", "width", "height")],
                          "score": obj.get("confidence")} for obj in payload]
                detections.append((int(round(t * scheme_fps)), found))
            report.progress("predict", n + 1, len(items))
            tracks = associate(detections, float(card["match_iou"]), int(card["max_age"]),
                               float(card["new_track_score"]),
                               int(card.get("min_track_keyframes", 2)))
            if not tracks:
                continue
            scores = [k[5] for t in tracks for k in t["keyframes"] if k[5] is not None]
            yield PredictionRecord(
                instance_id=item.instance_id, schema_name=spec.primary_schema.name,
                payload=track_payload(tracks, scheme_fps, meta["duration"], meta["width"],
                                      meta["height"], version),
                confidence=round(sum(scores) / len(scores), 4) if scores else None)
            if report.should_stop():
                return

    @classmethod
    def server_params(cls, config: Dict[str, Any], schema_names, params) -> Dict[str, Any]:
        """The scheme's frame rate, which numbers its keyframes."""
        by_name = {s.get("name"): s for s in config.get("annotation_schemes") or []
                   if isinstance(s, dict)}
        scheme = by_name.get(schema_names[0]) if schema_names else None
        try:
            return {"_video_fps": float((scheme or {}).get("video_fps") or 30)}
        except (TypeError, ValueError):
            return {"_video_fps": 30.0}
