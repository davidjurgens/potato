"""Speaker diarization, fine-tuned on the speaker turns annotators corrected.

For ``tiered_annotation`` speaker tiers and ``audio_annotation`` schemes
whose labels are speakers (an RTTM import makes one). Speaker names are
local to a recording: ``SPEAKER_00`` in one file is nobody in particular in
the next, so a classifier over the names would learn nothing. This trainer
follows the recipe pyannote's segmentation model uses, without pyannote or
its gated weights:

- A speech encoder (WavLM, wav2vec 2.0) with a frame head for up to
  ``max_speakers`` speakers at once, run on chunks of ``chunk_s`` seconds.
- Permutation-invariant training: each chunk's loss is the binary
  cross-entropy under the best matching of the model's speaker columns to
  the chunk's speakers, so the columns mean "a speaker", not a name.
- Prediction runs chunks that overlap by half. Each chunk's speakers are
  linked to the speakers found so far by their activity in the overlap
  (best one-to-one assignment), so a speaker keeps one name across the
  recording; one who is silent through an overlap and speaks again later is
  named anew, since there are no voice embeddings to recognise them.
  Thresholded activity becomes turns, with gaps under ``min_gap_s`` closed
  and turns under ``min_duration_s`` dropped.

Speakers come back as ``SPEAKER_00``, ``SPEAKER_01``, ... in order of first
speech, or as the scheme's own labels in that order when it lists them.
Held-out scores are diarization error rate against the annotated turns,
with the best mapping of predicted to annotated speakers.
"""

from __future__ import annotations

import itertools
import math
import os
import random
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf

INSTALL_HINT = "pip install 'potato-annotation[train-audio]'"
_NEEDS = ("torch", "transformers", "soundfile", "scipy")
DEFAULT_MODEL = "microsoft/wavlm-base-plus"
RATE = 16000


def _local_file(path: Optional[str]) -> bool:
    return bool(path) and not str(path).startswith(("http://", "https://")) \
        and os.path.isfile(str(path))


def speaker_turns_of(target: Any) -> List[Dict[str, Any]]:
    """``[{start, end, speaker}]`` from a segments target (tiered turns) or a
    temporal one (audio segments, label = speaker)."""
    out = []
    for entry in target or []:
        if not isinstance(entry, dict):
            continue
        speaker = entry.get("speaker", entry.get("label"))
        start = entry.get("start", entry.get("start_time"))
        end = entry.get("end", entry.get("end_time"))
        if speaker in (None, "") or start is None or end is None:
            continue
        out.append({"start": float(start), "end": float(end), "speaker": str(speaker)})
    return out


def chunk_targets(turns: List[Dict[str, Any]], start: float, n_frames: int,
                  frame_s: float, max_speakers: int) -> Tuple[List[List[float]], int]:
    """``(frames x max_speakers activity, speakers dropped)`` for the chunk
    starting at *start*: the chunk's speakers in order of first speech."""
    end = start + n_frames * frame_s
    inside = [t for t in turns if t["end"] > start and t["start"] < end]
    order: List[str] = []
    for turn in sorted(inside, key=lambda t: t["start"]):
        if turn["speaker"] not in order:
            order.append(turn["speaker"])
    grid = [[0.0] * max_speakers for _ in range(n_frames)]
    for turn in inside:
        column = order.index(turn["speaker"])
        if column >= max_speakers:
            continue
        first = max(0, int((turn["start"] - start) / frame_s))
        last = min(n_frames, int(math.ceil((turn["end"] - start) / frame_s)))
        for frame in range(first, last):
            grid[frame][column] = 1.0
    return grid, max(0, len(order) - max_speakers)


def link(previous, current, overlap: int):
    """The permutation of *current*'s columns that best matches *previous*
    over the last *overlap* frames of *previous* (the first of *current*):
    ``[column of previous for each current column, or None]``."""
    from potato.training.structured_metrics import hungarian
    k = len(current[0]) if current else 0
    width = len(previous[0]) if previous else 0
    size = max(k, width)
    cost = [[0.0] * size for _ in range(size)]
    tail = previous[len(previous) - overlap:] if overlap else []
    for c in range(k):
        for p in range(width):
            cost[c][p] = -sum(min(tail[f][p], current[f][c]) for f in range(min(overlap, len(tail))))
    out: List[Optional[int]] = [None] * k
    for c, p in hungarian(cost):
        if c < k and p < width and cost[c][p] < -0.5:
            out[c] = p
    return out


def activity_turns(activity: List[List[float]], frame_s: float, threshold: float,
                   min_gap_s: float, min_duration_s: float) -> List[Tuple[int, float, float, float]]:
    """``(speaker, start, end, mean activity)`` turns from frame activity."""
    out = []
    n_speakers = len(activity[0]) if activity else 0
    for speaker in range(n_speakers):
        runs, current = [], None
        for frame, row in enumerate(activity):
            if row[speaker] >= threshold:
                if current is None:
                    current = [frame, frame + 1, [row[speaker]]]
                else:
                    current[1] = frame + 1
                    current[2].append(row[speaker])
            elif current is not None:
                runs.append(current)
                current = None
        if current is not None:
            runs.append(current)
        merged: List[list] = []
        for run in runs:
            if merged and (run[0] - merged[-1][1]) * frame_s < min_gap_s:
                merged[-1][1] = run[1]
                merged[-1][2].extend(run[2])
            else:
                merged.append(run)
        for first, last, values in merged:
            if (last - first) * frame_s >= min_duration_s:
                out.append((speaker, first * frame_s, last * frame_s, sum(values) / len(values)))
    return sorted(out, key=lambda t: (t[1], t[0]))


class DiarizationTrainer(Trainer):
    name: ClassVar[str] = "diarization"
    description: ClassVar[str] = (
        "Speaker diarization: fine-tunes a speech encoder to find who speaks "
        "when, on the speaker turns annotators corrected (tiered speaker "
        "tiers, or audio segments labelled by speaker).")
    kinds: ClassVar[Tuple[str, ...]] = ("segments", "temporal")
    modalities: ClassVar[Tuple[str, ...]] = ("audio",)
    annotation_types: ClassVar[Tuple[str, ...]] = ("tiered_annotation", "audio_annotation")
    #: An audio scheme's labels are speakers here, and a speaker's name is
    #: local to its recording: scored by DER under the best speaker mapping,
    #: not by whether a segment's name matches.
    scored_as: ClassVar[Dict[str, str]] = {"temporal": "segments"}
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "MIT"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model_name": DEFAULT_MODEL, "epochs": 10, "batch_size": 8,
                "gradient_accumulation": 1, "learning_rate": 1e-4,
                "weight_decay": 0.01, "warmup_ratio": 0.1, "patience": 3,
                "precision": "auto", "lora": False, "chunk_s": 10.0,
                "max_speakers": 3, "threshold": 0.5, "min_gap_s": 0.2,
                "min_duration_s": 0.2, "min_instances": 4}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = {key: hf.COMMON_PARAMS[key] for key in
                 ("epochs", "batch_size", "gradient_accumulation", "weight_decay",
                  "warmup_ratio", "patience", "precision", "lora", "min_instances")}
        props["epochs"] = dict(props["epochs"], default=10)
        props["batch_size"] = dict(props["batch_size"], default=8,
                                   description="Chunks per step.")
        props["lora"] = dict(props["lora"], default=False)
        props["min_instances"] = dict(props["min_instances"], default=4,
                                      description="Fewest annotated recordings.")
        props.update({
            "model_name": {"type": "string", "default": DEFAULT_MODEL,
                           "description": "A speech encoder: microsoft/wavlm-base-plus, "
                                          "facebook/wav2vec2-base, or a local path."},
            "learning_rate": {"type": "number", "exclusiveMinimum": 0, "default": 1e-4},
            "chunk_s": {"type": "number", "minimum": 1, "default": 10.0,
                        "description": "Seconds the model sees at once."},
            "max_speakers": {"type": "integer", "minimum": 1, "maximum": 6, "default": 3,
                             "description": "Most speakers active within one chunk."},
            "threshold": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
            "min_gap_s": {"type": "number", "minimum": 0, "default": 0.2},
            "min_duration_s": {"type": "number", "minimum": 0, "default": 0.2},
        })
        return {"type": "object", "properties": props, "additionalProperties": False}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        problems = []
        if schema.kind not in self.kinds:
            problems.append("Schema %r is %s; this trainer handles speaker turns."
                            % (schema.name, schema.kind))
        if bundle.split_size("train") < int(params["min_instances"]):
            problems.append("Only %d annotated recordings in the train split; this trainer "
                            "needs at least %d." % (bundle.split_size("train"),
                                                    int(params["min_instances"])))
        problems.extend(hf.quantize_unsupported(params))
        return problems

    # ------------------------------------------------------------ model

    def _build(self, model_path: str, max_speakers: int):
        import torch
        from transformers import AutoModel

        class Segmenter(torch.nn.Module):
            def __init__(self, encoder, speakers):
                super().__init__()
                self.encoder = encoder
                self.head = torch.nn.Linear(encoder.config.hidden_size, speakers)

            def forward(self, input_values):
                hidden = self.encoder(input_values=input_values).last_hidden_state
                return self.head(hidden)

        encoder = AutoModel.from_pretrained(model_path)
        if hasattr(encoder, "freeze_feature_encoder"):
            encoder.freeze_feature_encoder()
        return Segmenter(encoder, max_speakers)

    @staticmethod
    def _frame_s(model, rate: int) -> float:
        ratio = 1
        for stride in getattr(model.encoder.config, "conv_stride", ()) or ():
            ratio *= int(stride)
        return ratio / float(rate) if ratio > 1 else 0.02

    def _recordings(self, bundle: BundleRef, split: str, schema: str,
                    report: ProgressReporter, with_targets: bool = True):
        from potato.training.trainers.hf_audio_tagger import load_audio
        out, missing = [], 0
        rows = hf.rows_with_target(bundle.read_split(split), schema) if with_targets \
            else list(bundle.read_split(split))
        for row in rows:
            path = bundle.resolve_media(row["media"]) if row.get("media") else None
            if not _local_file(path):
                missing += 1
                continue
            out.append({"row": row, "audio": load_audio(path, RATE),
                        "turns": speaker_turns_of((row.get("targets") or {}).get(schema))})
        if missing:
            report.log("warning", "Left out %d %s recording(s) with no local audio file"
                                  % (missing, split))
        return out

    # ------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch
        import torch.nn.functional as F
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        train = self._recordings(bundle, "train", schema.name, report)
        val = self._recordings(bundle, "val", schema.name, report)
        if not train:
            raise TrainerError("No annotated recordings with local audio for %r" % schema.name)
        hf.seed_everything(spec.seed)
        device = hf.pick_device(spec, report)
        k = int(params["max_speakers"])
        model = self._build(params["model_name"], k)
        if params.get("lora"):
            model.encoder = hf.apply_lora(model.encoder, params["lora"], None, report)
        model.to(device)
        frame_s = self._frame_s(model, RATE)
        chunk = int(float(params["chunk_s"]) * RATE)
        rng = random.Random(spec.seed)

        chunks, dropped = [], 0
        for recording in train:
            samples = recording["audio"]
            for offset in range(0, max(1, len(samples) - chunk // 2), chunk // 2):
                clip = samples[offset:offset + chunk]
                if len(clip) < chunk:
                    import numpy
                    clip = numpy.pad(clip, (0, chunk - len(clip)))
                chunks.append({"audio": clip, "start": offset / RATE,
                               "turns": recording["turns"]})
        report.log("info", "%d recordings in %d chunks of %.0f s, %d val recordings"
                   % (len(train), len(chunks), params["chunk_s"], len(val)))
        permutations = list(itertools.permutations(range(k)))

        def loss_of(batch):
            import numpy
            audio = torch.from_numpy(numpy.stack([c["audio"] for c in batch]).astype(
                "float32")).to(device)
            logits = model(audio)
            n_frames = logits.shape[1]
            losses = []
            for row, c in enumerate(batch):
                grid, extra = chunk_targets(c["turns"], c["start"], n_frames, frame_s, k)
                target = torch.tensor(grid, dtype=torch.float32, device=device)
                losses.append(min(F.binary_cross_entropy_with_logits(
                    logits[row][:, list(p)], target) for p in permutations))
            return torch.stack(losses).mean()

        model_dir = os.path.join(spec.workdir, hf.MODEL_DIR)
        selected = {"best": None, "saved": False}
        version = "%s-%s-%s" % (self.name, schema.name, spec.run_id)

        def save():
            os.makedirs(model_dir, exist_ok=True)
            torch.save(model.head.state_dict(), os.path.join(model_dir, "head.pt"))
            model.encoder.save_pretrained(os.path.join(model_dir, "encoder"))

        def on_epoch_end(epoch):
            if not val:
                return None
            from potato.training.audio_metrics import score_diarization
            gold = [r["turns"] for r in val]
            guesses = [self._diarize(model, r["audio"], params, device, frame_s) for r in val]
            metrics = score_diarization(gold, [[{"start": s, "end": e, "speaker": str(p)}
                                                for p, s, e, _ in g] for g in guesses])
            score = metrics.get("diarization_accuracy", 0.0)
            report.metric("val", "der", metrics.get("der", 1.0), step=epoch + 1)
            if selected["best"] is None or score > selected["best"]:
                selected["best"] = score
                save()
                selected["saved"] = True
            return score

        report.status("running", "fine-tuning")
        summary = hf.train_loop(model, chunks, params, loss_of, report, device=device,
                                seed=spec.seed, on_epoch_end=on_epoch_end)
        if not selected["saved"]:
            save()
        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "base_model": params["model_name"], "label_order": bundle.labels(schema.name),
            "annotation_type": schema.annotation_type,
            "tier": next((t.get("tier") for r in train for t in
                          (r["row"].get("targets") or {}).get(schema.name) or []
                          if isinstance(t, dict) and t.get("tier")), None),
            **{key: params[key] for key in ("max_speakers", "chunk_s", "threshold",
                                            "min_gap_s", "min_duration_s")},
            "model_version": version, "device": device, "n_train": len(train),
            "bundle_digest": bundle.digest, "selected_epoch": summary["best_epoch"]})
        metrics = {"n_train": float(len(train)), "n_chunks": float(len(chunks)),
                   "train_seconds": summary["train_seconds"]}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        return FitResult(model_version=version, artifact_paths=hf.artifact_files(spec.workdir),
                         metrics=metrics, label_order=bundle.labels(schema.name),
                         selected_on="val" if val else "")

    # ------------------------------------------------------------ predict

    def _diarize(self, model, samples, params, device, frame_s):
        """``(speaker, start, end, confidence)`` turns for one recording."""
        import numpy
        import torch
        chunk = int(float(params["chunk_s"]) * RATE)
        hop = chunk // 2
        model.eval()
        global_activity: List[List[float]] = []
        counts: List[int] = []
        n_global = 0
        offsets = list(range(0, max(1, len(samples) - hop), hop)) or [0]
        previous = None
        for offset in offsets:
            clip = samples[offset:offset + chunk]
            real = len(clip)
            if real < chunk:
                clip = numpy.pad(clip, (0, chunk - real))
            with torch.inference_mode():
                logits = model(torch.tensor(clip[None], dtype=torch.float32, device=device))[0]
            local = torch.sigmoid(logits).cpu().tolist()
            local = local[:max(1, int(math.ceil(real / RATE / frame_s)))]
            start_frame = int(round(offset / RATE / frame_s))
            overlap = max(0, len(global_activity) - start_frame) if previous is not None else 0
            if previous is not None and overlap:
                window = [row[:n_global] for row in global_activity[start_frame:start_frame + overlap]]
                mapping = link(window, local[:overlap], overlap) if n_global \
                    else [None] * len(local[0])
            else:
                mapping = [None] * len(local[0])
            for column, target in enumerate(mapping):
                if target is None and any(row[column] >= params["threshold"] for row in local):
                    mapping[column] = n_global
                    n_global += 1
                    for row in global_activity:
                        row.append(0.0)
            for f, row in enumerate(local):
                frame = start_frame + f
                while len(global_activity) <= frame:
                    global_activity.append([0.0] * n_global)
                    counts.append(0)
                for column, target in enumerate(mapping):
                    if target is not None:
                        current = global_activity[frame][target]
                        global_activity[frame][target] = max(current, row[column]) \
                            if counts[frame] else row[column]
                counts[frame] += 1
            previous = local
        if not n_global:
            return []
        return activity_turns(global_activity, frame_s, float(params["threshold"]),
                              float(params["min_gap_s"]), float(params["min_duration_s"]))

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch
        from potato.training.trainers.hf_audio_tagger import load_audio
        card = hf.read_card(artifact_dir)
        device = hf.pick_device(spec, report)
        model = self._build(os.path.join(artifact_dir, hf.MODEL_DIR, "encoder"),
                            int(card["max_speakers"]))
        model.head.load_state_dict(torch.load(
            os.path.join(artifact_dir, hf.MODEL_DIR, "head.pt"), map_location="cpu"))
        model.to(device)
        frame_s = self._frame_s(model, RATE)
        labels = list(card.get("label_order") or [])
        version = card.get("model_version", "")
        items = [item for item in items if _local_file(item.media)]
        for n, item in enumerate(items):
            turns = self._diarize(model, load_audio(item.media, RATE), card, device, frame_s)
            report.progress("predict", n + 1, len(items))
            if not turns:
                continue

            def name(speaker):
                return labels[speaker] if speaker < len(labels) else "SPEAKER_%02d" % speaker

            if card.get("annotation_type") == "tiered_annotation":
                tier = card.get("tier") or "speaker"
                payload = {"annotations": {tier: [
                    {"id": "model-%d" % i, "tier": tier, "start_time": round(s * 1000, 1),
                     "end_time": round(e * 1000, 1), "label": name(p), "value": "",
                     "parent_id": None, "source": "ai", "confidence": round(c, 4)}
                    for i, (p, s, e, c) in enumerate(turns)]}}
            else:
                payload = {"segments": [
                    {"id": "model_%d" % i, "start_time": round(s, 3), "end_time": round(e, 3),
                     "label": name(p), "source": "ai", "ai_model": version,
                     "confidence": round(c, 4)} for i, (p, s, e, c) in enumerate(turns)]}
            yield PredictionRecord(
                instance_id=item.instance_id, schema_name=spec.primary_schema.name,
                payload=payload, confidence=round(min(c for *_, c in turns), 4))
            if report.should_stop():
                return
