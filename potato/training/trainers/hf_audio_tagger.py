"""Tag labelled time segments in audio.

For ``audio_annotation`` schemes: speech, music, a bird call, a cough, a
speaker turn. Fine-tunes a self-supervised speech encoder that
``AutoModelForAudioFrameClassification`` loads (wav2vec 2.0, WavLM,
HuBERT-style UniSpeech-SAT, Data2Vec audio) to say, for every frame of about
20 ms, which labels are active. Frames are scored independently per label, so
overlapping segments of different labels are learned as they were annotated.

Recordings are cut into windows of ``window_s`` seconds. Predicted frame
probabilities are thresholded, runs shorter than ``min_gap_s`` between two
segments of the same label are closed, and segments shorter than
``min_duration_s`` are dropped. The prediction is the audio widget's own
value, ``{"segments": [{start_time, end_time, label}]}``, so write-back shows
it as editable regions on the waveform.

A stretch of the recording no annotator marked counts as "no label here".
That is right for a study that marks every event, and wrong for one where
annotators marked only some: there the model learns to miss what was skipped.
"""

from __future__ import annotations

import math
import os
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf

INSTALL_HINT = "pip install 'potato-annotation[train-audio]'"
_NEEDS = ("torch", "transformers", "soundfile", "scipy")
DEFAULT_MODEL = "facebook/wav2vec2-base"


def _local_file(path: Optional[str]) -> bool:
    return bool(path) and not str(path).startswith(("http://", "https://")) \
        and os.path.isfile(str(path))


def load_audio(path: str, rate: int):
    """Mono float32 samples at *rate*."""
    import numpy
    import soundfile
    from scipy.signal import resample_poly

    samples, source_rate = soundfile.read(path, dtype="float32",
                                          always_2d=True)
    samples = samples.mean(axis=1)
    if source_rate != rate:
        divisor = math.gcd(int(source_rate), int(rate))
        samples = resample_poly(samples, rate // divisor,
                                int(source_rate) // divisor).astype(numpy.float32)
    return samples


def frame_targets(segments: List[Dict[str, Any]], index: Dict[str, int],
                  n_frames: int, frame_s: float, offset_s: float) -> List[List[float]]:
    """Per frame, 1.0 for each label a segment covers at the frame's centre."""
    out = [[0.0] * len(index) for _ in range(n_frames)]
    for seg in segments or []:
        label = str(seg.get("label", ""))
        if label not in index:
            continue
        start, end = float(seg["start"]), float(seg["end"])
        first = max(0, int(math.ceil((start - offset_s) / frame_s - 0.5)))
        last = min(n_frames - 1, int(math.floor((end - offset_s) / frame_s - 0.5)))
        for frame in range(first, last + 1):
            out[frame][index[label]] = 1.0
    return out


def decode_segments(probs: List[List[float]], times: List[float],
                    labels: List[str], frame_s: float, threshold: float,
                    min_gap_s: float, min_duration_s: float,
                    model_version: str = "") -> List[Dict[str, Any]]:
    """Frame probabilities to ``{start_time, end_time, label, confidence}``.

    *times* holds each frame's start in seconds from the recording's start.
    """
    segments = []
    for column, label in enumerate(labels):
        runs: List[List[float]] = []
        for row, at in zip(probs, times):
            if row[column] < threshold:
                continue
            start, end = at, at + frame_s
            if runs and start - runs[-1][1] <= min_gap_s + 1e-9:
                runs[-1][1] = end
                runs[-1][2] += row[column]
                runs[-1][3] += 1
            else:
                runs.append([start, end, row[column], 1])
        for start, end, total, count in runs:
            if end - start < min_duration_s:
                continue
            # The provenance the audio widget carries, as image boxes do.
            segment = {"start_time": round(start, 3),
                       "end_time": round(end, 3), "label": label,
                       "source": "ai", "confidence": round(total / count, 4)}
            if model_version:
                segment["ai_model"] = model_version
            segments.append(segment)
    segments.sort(key=lambda s: (s["start_time"], s["label"]))
    for n, seg in enumerate(segments):
        seg["id"] = "model_%d" % n
    return segments


class HFAudioTaggerTrainer(Trainer):
    name: ClassVar[str] = "hf-audio-tagger"
    description: ClassVar[str] = (
        "Tags labelled time segments in audio with a fine-tuned speech "
        "encoder (wav2vec 2.0, WavLM).")
    kinds: ClassVar[Tuple[str, ...]] = ("temporal",)
    modalities: ClassVar[Tuple[str, ...]] = ("audio",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "Apache-2.0"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": DEFAULT_MODEL, "epochs": 10, "batch_size": 8,
                "gradient_accumulation": 1, "learning_rate": None,
                "weight_decay": 0.01, "warmup_ratio": 0.1, "patience": 3,
                "precision": "auto", "lora": None, "window_s": 10.0,
                "threshold": 0.5, "min_gap_s": 0.1, "min_duration_s": 0.1,
                "freeze_feature_encoder": True, "min_instances": 10}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = dict(hf.COMMON_PARAMS)
        props["epochs"] = dict(props["epochs"], default=10)
        props["batch_size"] = dict(props["batch_size"], default=8,
                                   description="Windows per step.")
        props["patience"] = dict(props["patience"], default=3)
        props["min_instances"] = dict(props["min_instances"], default=10)
        props["learning_rate"] = dict(
            props["learning_rate"], default=None,
            description="Defaults to 5e-5, or 5e-4 with LoRA.")
        props.update({
            "model_name": {"type": "string", "default": DEFAULT_MODEL,
                           "description": "A model "
                                          "AutoModelForAudioFrameClassification "
                                          "loads, or a local path."},
            "window_s": {"type": "number", "exclusiveMinimum": 0,
                         "default": 10.0,
                         "description": "Seconds of audio per training and "
                                        "prediction window."},
            "threshold": {"type": "number", "minimum": 0, "maximum": 1,
                          "default": 0.5,
                          "description": "Frame probability at which a label "
                                         "is active."},
            "min_gap_s": {"type": "number", "minimum": 0, "default": 0.1,
                          "description": "Gaps this short inside a segment "
                                         "are closed."},
            "min_duration_s": {"type": "number", "minimum": 0, "default": 0.1,
                               "description": "Shorter predicted segments "
                                              "are dropped."},
            "freeze_feature_encoder": {
                "type": "boolean", "default": True,
                "description": "Keep the convolutional feature encoder "
                               "fixed, as wav2vec 2.0 fine-tuning does."},
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
        if bundle.modality != "audio":
            problems.append("This bundle's items are %s, not audio."
                            % bundle.modality)
        if bundle.split_size("train") < int(params["min_instances"]):
            problems.append(
                "Only %d recordings in the train split; this trainer needs at "
                "least %d. Annotate more, or lower min_instances."
                % (bundle.split_size("train"), int(params["min_instances"])))
        if not bundle.labels(schema.name):
            problems.append("Schema %r has no labelled segments in the data."
                            % schema.name)
        return problems

    # ------------------------------------------------------------ data

    def _audio_rows(self, bundle: BundleRef, split: str, schema: str,
                    report: ProgressReporter) -> List[Dict[str, Any]]:
        rows, missing = [], 0
        for row in hf.rows_with_target(bundle.read_split(split), schema):
            path = bundle.resolve_media(row["media"]) if row.get("media") else None
            if not _local_file(path):
                missing += 1
                continue
            rows.append(dict(row, audio_path=path))
        if missing:
            report.log("warning", "Left out %d %s row(s) with no local audio "
                                  "file" % (missing, split))
        return rows

    @staticmethod
    def _windows(samples, rate: int, window_s: float) -> List[Tuple[int, int]]:
        size = max(1, int(round(window_s * rate)))
        return [(start, min(len(samples), start + size))
                for start in range(0, len(samples), size)]

    # ------------------------------------------------------------ model

    @staticmethod
    def _frame_seconds(model, rate: int) -> float:
        """The hop between frames: the encoder's total convolution stride."""
        ratio = getattr(model.config, "inputs_to_logits_ratio", None) or 320
        return float(ratio) / float(rate)

    @staticmethod
    def _frames_for(model, n_samples: int) -> int:
        """Frames the encoder produces for *n_samples*. Not n / stride: each
        convolution loses its kernel's overhang, 499 frames for 10 s rather
        than 500, which put every later window's segments a frame early."""
        # A peft wrapper forwards the attribute to the model it wraps.
        lengths = getattr(model, "_get_feat_extract_output_lengths", None)
        if lengths is not None:
            return int(lengths(n_samples))
        ratio = getattr(model.config, "inputs_to_logits_ratio", None) or 320
        return max(1, n_samples // ratio)

    def _logits(self, model, extractor, chunks, rate: int, device: str):
        """Frame logits for a batch of sample arrays, and frames per chunk."""
        features = extractor(list(chunks), sampling_rate=rate,
                             return_tensors="pt", padding=True)
        values = features["input_values"].to(device)
        logits = model(input_values=values).logits.float()
        valid = [max(1, min(logits.shape[1], self._frames_for(model, len(c))))
                 for c in chunks]
        return logits, valid

    # ------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch
        from transformers import (AutoFeatureExtractor,
                                  AutoModelForAudioFrameClassification)

        params = hf.merged_params(self.default_params(), spec)
        if params.get("learning_rate") is None:
            params["learning_rate"] = 5e-4 if params["lora"] else 5e-5
        schema = spec.primary_schema
        labels = bundle.labels(schema.name)
        index = {label: i for i, label in enumerate(labels)}

        train = self._audio_rows(bundle, "train", schema.name, report)
        val = self._audio_rows(bundle, "val", schema.name, report)
        if not train:
            raise TrainerError("No train rows with a local audio file for %r"
                               % schema.name)

        hf.seed_everything(spec.seed)
        device = hf.pick_device(spec, report)
        report.status("running", "loading %s" % params["model_name"])
        extractor = AutoFeatureExtractor.from_pretrained(params["model_name"])
        rate = int(getattr(extractor, "sampling_rate", 16000))
        model = AutoModelForAudioFrameClassification.from_pretrained(
            params["model_name"], **self._head_kwargs(labels))
        if params["freeze_feature_encoder"] and hasattr(model,
                                                        "freeze_feature_encoder"):
            model.freeze_feature_encoder()
        model = hf.apply_lora(model, params["lora"], None, report,
                              modules_to_save=["classifier"])
        model.to(device)
        frame_s = self._frame_seconds(model, rate)

        cache: Dict[str, Any] = {}

        def samples_of(path):
            if path not in cache:
                cache[path] = load_audio(path, rate)
            return cache[path]

        windows = []
        total_s = 0.0
        for row in train:
            samples = samples_of(row["audio_path"])
            if not len(samples):
                continue
            total_s += len(samples) / rate
            for start, end in self._windows(samples, rate,
                                            float(params["window_s"])):
                windows.append((row, start, end))
        report.log("info", "%d train recordings (%.0f s) in %d windows, %d "
                           "val recordings, %d labels"
                   % (len(train), total_s, len(windows), len(val), len(labels)))

        def loss_of(batch):
            chunks = [samples_of(r["audio_path"])[s:e] for r, s, e in batch]
            logits, valid = self._logits(model, extractor, chunks, rate, device)
            target = torch.zeros_like(logits)
            mask = torch.zeros(logits.shape[:2], device=logits.device)
            for i, (row, start, _end) in enumerate(batch):
                frames = frame_targets(row["targets"][schema.name], index,
                                       valid[i], frame_s, start / rate)
                target[i, :valid[i]] = torch.tensor(frames, device=logits.device)
                mask[i, :valid[i]] = 1.0
            per_frame = torch.nn.functional.binary_cross_entropy_with_logits(
                logits, target, reduction="none").mean(-1)
            return (per_frame * mask).sum() / mask.sum().clamp(min=1.0)

        selected = {"best": None, "saved": False}

        def save():
            hf.save_model(model, None, spec.workdir)
            extractor.save_pretrained(os.path.join(spec.workdir, hf.MODEL_DIR))

        def on_epoch_end(epoch):
            if not val:
                return None
            from potato.training.evaluation import HEADLINE, score_split
            predictions = {
                (str(row["instance_id"]), schema.name): payload
                for row, payload, _ in self._predict_rows(
                    model, extractor, ((r, samples_of(r["audio_path"]))
                                       for r in val), labels, params, rate,
                    device)}
            metrics, _ = score_split(val, predictions, schema.name, schema.kind)
            score = metrics.get(HEADLINE[schema.kind], 0.0)
            report.metric("val", HEADLINE[schema.kind], score, step=epoch + 1)
            if selected["best"] is None or score > selected["best"]:
                selected["best"] = score
                save()
                selected["saved"] = True
            return score

        report.status("running", "fine-tuning")
        summary = hf.train_loop(model, windows, params, loss_of, report,
                                device=device, seed=spec.seed,
                                on_epoch_end=on_epoch_end)
        if not selected["saved"]:
            save()

        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "base_model": params["model_name"], "lora": params["lora"],
            "label_order": labels, "sampling_rate": rate,
            "window_s": float(params["window_s"]),
            "threshold": float(params["threshold"]),
            "min_gap_s": float(params["min_gap_s"]),
            "min_duration_s": float(params["min_duration_s"]),
            "device": device, "n_train": len(train),
            "model_version": "%s-%s-%s" % (self.name, schema.name, spec.run_id),
            "bundle_digest": bundle.digest,
            "selected_epoch": summary["best_epoch"]})

        metrics = {"n_train": float(len(train)), "n_windows": float(len(windows)),
                   "train_audio_seconds": round(total_s, 1),
                   "train_seconds": summary["train_seconds"],
                   "epochs_run": float(summary["epochs_run"])}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        return FitResult(
            model_version="%s-%s-%s" % (self.name, schema.name, spec.run_id),
            artifact_paths=hf.artifact_files(spec.workdir), metrics=metrics,
            label_order=labels, selected_on="val" if val else "")

    @staticmethod
    def _head_kwargs(labels: List[str]) -> Dict[str, Any]:
        return {"num_labels": len(labels),
                "id2label": {i: label for i, label in enumerate(labels)},
                "label2id": {label: i for i, label in enumerate(labels)},
                "ignore_mismatched_sizes": True}

    # ------------------------------------------------------------ predict

    def _predict_rows(self, model, extractor, pairs, labels: List[str],
                      params: Dict[str, Any], rate: int, device: str,
                      report: Optional[ProgressReporter] = None,
                      total: Optional[int] = None):
        """``(key, payload, confidence)`` per recording; *pairs* yields
        ``(key, samples)``."""
        import torch

        frame_s = self._frame_seconds(model, rate)
        size = max(1, int(params.get("batch_size", 8)))
        model.eval()
        for n, (key, samples) in enumerate(pairs):
            spans = self._windows(samples, rate, float(params["window_s"]))
            probs: List[List[float]] = []
            times: List[float] = []
            for start in range(0, len(spans), size):
                batch = spans[start:start + size]
                chunks = [samples[s:e] for s, e in batch]
                with torch.inference_mode():
                    logits, valid = self._logits(model, extractor, chunks, rate,
                                                 device)
                p = torch.sigmoid(logits).cpu().tolist()
                for i, count in enumerate(valid):
                    probs.extend(p[i][:count])
                    offset = batch[i][0] / rate
                    times.extend(offset + f * frame_s for f in range(count))
            segments = decode_segments(
                probs, times, labels, frame_s, float(params["threshold"]),
                float(params["min_gap_s"]), float(params["min_duration_s"]),
                str(params.get("model_version") or ""))
            # Least sure frame-label decision, as the other multilabel
            # trainers report it: what the review queue sorts on.
            confidence = min((max(v, 1 - v) for row in probs for v in row),
                             default=0.0)
            yield key, {"segments": segments}, confidence
            if report is not None:
                report.progress("predict", n + 1, total or n + 1)
                if report.should_stop():
                    return

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        from transformers import (AutoFeatureExtractor,
                                  AutoModelForAudioFrameClassification)

        card = hf.read_card(artifact_dir)
        labels = card["label_order"]
        rate = int(card.get("sampling_rate", 16000))
        device = hf.pick_device(spec, report)
        extractor = AutoFeatureExtractor.from_pretrained(
            os.path.join(artifact_dir, hf.MODEL_DIR))
        model = hf.load_pretrained(AutoModelForAudioFrameClassification,
                                   artifact_dir, card, device,
                                   **self._head_kwargs(labels))
        params = {"batch_size": 8, "window_s": card.get("window_s", 10.0),
                  "threshold": card.get("threshold", 0.5),
                  "min_gap_s": card.get("min_gap_s", 0.1),
                  "min_duration_s": card.get("min_duration_s", 0.1),
                  "model_version": card.get("model_version", "")}

        # One recording in memory at a time. An item with no readable audio,
        # or an empty file, gets no prediction.
        usable = [item for item in items if _local_file(item.media)]
        pairs = ((item, samples) for item, samples in
                 ((item, load_audio(item.media, rate)) for item in usable)
                 if len(samples))

        for item, payload, confidence in self._predict_rows(
                model, extractor, pairs, labels, params, rate, device,
                report, total=len(usable)):
            yield PredictionRecord(instance_id=item.instance_id,
                                   schema_name=card["schema"], payload=payload,
                                   confidence=round(float(confidence), 4))
