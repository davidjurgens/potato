"""Labelling physiological signals (EEG, ECG, EMG, sensor logs) with a 1D CNN.

For ``interval_label`` schemes. Each annotated recording is read through
the same readers as the ``time_series`` display (EDF/BDF, WFDB, CSV,
Parquet, inline), the display's channels (or every channel, up to
``max_channels``) resampled to ``rate`` Hz and each standardized.

The scheme's mode decides the task:

* **epoch** (sleep staging and the like): every annotated epoch is one
  example, classified whole. Prediction labels every epoch of the recording.
* **free**: the recording is labelled sample by sample, with "no label"
  wherever no interval is, trained on random ``window_s``-second crops.
  Prediction slides over the recording, takes the most likely label per
  ``frame_s`` frame, and merges runs into intervals; runs shorter than
  ``min_duration`` are dropped. Point events are not predicted.

The network is a small InceptionTime (parallel convolutions of three widths,
residual every three blocks). Predicted intervals are for every channel
(``channel: null``), with ``source: model``, and the page shows them as
pre-annotations to accept or correct. Needs torch.
"""

from __future__ import annotations

import os
import random
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf
from potato.training.trainers import _science_common as sc

INSTALL_HINT = "pip install 'potato-annotation[train-vision,signals]'"
_NEEDS = ("torch", "numpy")


class SignalCNNTrainer(Trainer):
    name: ClassVar[str] = "signal-cnn"
    description: ClassVar[str] = (
        "Labels EEG, ECG and other signals: an InceptionTime CNN that stages "
        "epochs or finds labelled intervals, trained on interval_label answers.")
    kinds: ClassVar[Tuple[str, ...]] = ("intervals",)
    modalities: ClassVar[Tuple[str, ...]] = ("signal",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "BSD-3-Clause"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"epochs": 30, "batch_size": 32, "learning_rate": 1e-3, "weight_decay": 1e-4,
                "warmup_ratio": 0.05, "patience": 5, "precision": "auto",
                "rate": 100.0, "max_channels": 16, "width": 16, "depth": 6,
                "balanced": True, "window_s": 30.0, "windows_per_epoch": 400,
                "frame_s": 1.0, "min_duration": None, "min_instances": 3}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = {key: hf.COMMON_PARAMS[key] for key in
                 ("epochs", "batch_size", "weight_decay", "warmup_ratio", "patience",
                  "precision", "min_instances")}
        props["epochs"] = dict(props["epochs"], default=30)
        props["batch_size"] = dict(props["batch_size"], default=32)
        props["patience"] = dict(props["patience"], default=5)
        props["min_instances"] = dict(props["min_instances"], default=3,
                                      description="Annotated recordings needed in the "
                                                  "train split.")
        props.update({
            "learning_rate": {"type": "number", "exclusiveMinimum": 0, "default": 1e-3},
            "rate": {"type": "number", "exclusiveMinimum": 0, "default": 100.0,
                     "description": "Hz every channel is resampled to."},
            "max_channels": {"type": "integer", "minimum": 1, "default": 16,
                             "description": "Most channels read, when the display "
                                            "names none."},
            "width": {"type": "integer", "minimum": 4, "default": 16,
                      "description": "Filters per convolution branch."},
            "depth": {"type": "integer", "minimum": 3, "maximum": 12, "default": 6},
            "balanced": {"type": "boolean", "default": True,
                         "description": "Weight the loss by inverse label frequency "
                                        "(rare sleep stages, rare events)."},
            "window_s": {"type": "number", "exclusiveMinimum": 0, "default": 30.0,
                         "description": "Free mode: seconds per training crop and "
                                        "prediction window."},
            "windows_per_epoch": {"type": "integer", "minimum": 1, "default": 400,
                                  "description": "Free mode: crops per epoch."},
            "frame_s": {"type": "number", "exclusiveMinimum": 0, "default": 1.0,
                        "description": "Free mode: seconds per predicted frame."},
            "min_duration": {"type": ["number", "null"], "minimum": 0, "default": None,
                             "description": "Free mode: shortest predicted interval, in "
                                            "seconds. null is one frame."},
        })
        return {"type": "object", "properties": props, "additionalProperties": False}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        if schema.kind not in self.kinds:
            return ["Schema %r is %s; this trainer labels interval_label schemes."
                    % (schema.name, schema.kind)]
        rows = [r for r in hf.rows_with_target(bundle.read_split("train"), schema.name)
                if sc.has_input(r, bundle.resolve_media(r["media"]) if r.get("media")
                                else None)]
        problems = []
        if len(rows) < int(params["min_instances"]):
            problems.append("Only %d annotated recordings with a readable signal in the "
                            "train split; this trainer needs at least %d."
                            % (len(rows), int(params["min_instances"])))
        labels = bundle.labels(schema.name)
        epoch = any(r["targets"][schema.name].get("mode") == "epoch" for r in rows)
        if not labels or (epoch and len(labels) < 2):
            problems.append("Schema %r has %d interval label(s) in the data; a model "
                            "needs %s." % (schema.name, len(labels),
                                           "two" if epoch else "one"))
        return problems

    # ------------------------------------------------------------ data

    def _recording(self, row, media, card):
        rec = sc.signal_of(row, media)
        options = sc.science_of(row).get("options") or {}
        wanted = options.get("channels") if isinstance(options.get("channels"), list) else None
        channels = sc.signal_channels(rec, card.get("channel_names") or wanted,
                                      int(card["max_channels"]))
        if not channels:
            raise TrainerError("no readable channel")
        names = [rec.channels[c].name for c in channels]
        times, array = sc.signal_array(rec, channels, float(card["rate"]))
        out = {"row": row, "times": times, "array": array, "names": names,
               "t_start": float(rec.t_start)}
        return self._align(out, card["channel_names"]) if card.get("channel_names") else out

    @staticmethod
    def _align(rec, wanted: List[str]):
        """The channels the model was trained on, in that order; one this
        recording lacks is a flat zero."""
        import numpy
        if rec["names"] == list(wanted):
            return rec
        full = numpy.zeros((len(wanted), rec["array"].shape[1]), dtype="float32")
        for column, name in enumerate(rec["names"]):
            if name in wanted:
                full[wanted.index(name)] = rec["array"][column]
        return dict(rec, array=full, names=list(wanted))

    def _recordings(self, bundle, split, card, report):
        out, unreadable = [], []
        for row in hf.rows_with_target(bundle.read_split(split), self._schema):
            media = bundle.resolve_media(row["media"]) if row.get("media") else None
            if not sc.has_input(row, media):
                unreadable.append(row["instance_id"])
                continue
            try:
                out.append(self._recording(row, media, card))
            except Exception as exc:  # noqa: BLE001 - one bad file is one row
                unreadable.append("%s (%s)" % (row["instance_id"], exc))
        if unreadable:
            report.log("warning", "Left out %d %s recording(s): %s"
                       % (len(unreadable), split, ", ".join(unreadable[:5])))
        return out

    @staticmethod
    def _index(rec, t: float, rate: float) -> int:
        return int(round((t - float(rec["times"][0])) * rate)) if len(rec["times"]) else 0

    def _epochs(self, recs, labels, rate, length):
        """``(recording, first sample, label index)`` per annotated epoch."""
        size = int(round(length * rate))
        out = []
        for r, rec in enumerate(recs):
            target = rec["row"]["targets"][self._schema]
            for iv in target["intervals"]:
                if iv["label"] not in labels:
                    continue
                n = max(1, int(round((iv["end"] - iv["start"]) / length)))
                for k in range(n):
                    first = self._index(rec, iv["start"] + k * length, rate)
                    if 0 <= first and first + size <= rec["array"].shape[1]:
                        out.append((r, first, labels.index(iv["label"])))
        return out, size

    def _frame_labels(self, rec, labels, rate):
        """Per-sample label index (0 is no label) for a free-mode recording."""
        import numpy
        out = numpy.zeros(rec["array"].shape[1], dtype="int64")
        for iv in rec["row"]["targets"][self._schema]["intervals"]:
            if iv["label"] in labels:
                a = max(0, self._index(rec, iv["start"], rate))
                b = min(len(out), self._index(rec, iv["end"], rate))
                out[a:b] = labels.index(iv["label"]) + 1
        return out

    # ------------------------------------------------------------ predict

    def _predict_epochs(self, model, rec, labels, card, device):
        import numpy
        import torch
        rate, length = float(card["rate"]), float(card["epoch_length"])
        size = int(round(length * rate))
        n = int(rec["array"].shape[1] // size)
        if rec["array"].shape[1] - n * size >= size / 2:
            n += 1      # a last epoch at least half there
        out = []
        with torch.inference_mode():
            for start in range(0, n, 64):
                windows = []
                for k in range(start, min(n, start + 64)):
                    window = rec["array"][:, k * size:(k + 1) * size]
                    if window.shape[1] < size:
                        window = numpy.pad(window, ((0, 0), (0, size - window.shape[1])))
                    windows.append(window)
                logits = model(torch.from_numpy(numpy.stack(windows)).to(device)).float()
                probs = torch.softmax(logits.mean(-1), dim=-1).cpu().numpy()
                for k, row in zip(range(start, start + len(windows)), probs):
                    best = int(row.argmax())
                    t0 = rec["t_start"] + k * length
                    out.append({"start": round(t0, 6), "end": round(t0 + length, 6),
                                "label": labels[best], "channel": None, "source": "model",
                                "confidence": round(float(row[best]), 4)})
        return out

    def _predict_free(self, model, rec, labels, card, device):
        import numpy
        import torch
        rate = float(card["rate"])
        size = max(8, int(round(float(card["window_s"]) * rate)))
        total = rec["array"].shape[1]
        probs = numpy.zeros((len(labels) + 1, total), dtype="float32")
        with torch.inference_mode():
            for start in range(0, total, size):
                window = rec["array"][:, start:start + size]
                width = window.shape[1]
                if width < size:
                    window = numpy.pad(window, ((0, 0), (0, size - width)))
                logits = model(torch.from_numpy(window[None]).to(device)).float()
                probs[:, start:start + width] = torch.softmax(
                    logits, dim=1)[0].cpu().numpy()[:, :width]
        frame = max(1, int(round(float(card["frame_s"]) * rate)))
        frames = int(numpy.ceil(total / frame))
        names: List[Optional[str]] = []
        confidences = []
        for f in range(frames):
            mean = probs[:, f * frame:(f + 1) * frame].mean(1)
            best = int(mean.argmax())
            names.append(labels[best - 1] if best else None)
            confidences.append(float(mean[best]))
        times = [rec["t_start"] + f * frame / rate for f in range(frames)]
        shortest = card.get("min_duration")
        shortest = float(shortest) if shortest is not None else frame / rate
        intervals = sc.runs(names, times, frame / rate, confidences)
        end = rec["t_start"] + total / rate
        return [dict(iv, end=round(min(iv["end"], end), 6), channel=None, source="model")
                for iv in intervals if iv["end"] - iv["start"] >= shortest - 1e-9]

    def _predict(self, model, rec, labels, card, device):
        if card["mode"] == "epoch":
            return self._predict_epochs(model, rec, labels, card, device)
        return self._predict_free(model, rec, labels, card, device)

    # ------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        import numpy
        import torch
        import torch.nn.functional as F
        from potato.training.science_metrics import score_intervals
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        self._schema = schema.name
        labels = list(bundle.labels(schema.name))
        card: Dict[str, Any] = {"rate": float(params["rate"]),
                                "max_channels": int(params["max_channels"])}
        train = self._recordings(bundle, "train", card, report)
        if not train:
            raise TrainerError("No annotated recordings with a readable signal for %r"
                               % schema.name)
        # Every recording is read with the first one's channels, so the
        # network's inputs mean the same thing throughout.
        card["channel_names"] = train[0]["names"]
        train = [self._align(rec, card["channel_names"]) for rec in train]
        val = self._recordings(bundle, "val", card, report)
        first = train[0]["row"]["targets"][schema.name]
        card.update(mode=first["mode"], epoch_length=float(first["epoch_length"]),
                    window_s=float(params["window_s"]), frame_s=float(params["frame_s"]),
                    min_duration=params.get("min_duration"))
        rate = card["rate"]
        epoch_mode = card["mode"] == "epoch"
        classes = len(labels) if epoch_mode else len(labels) + 1
        hf.seed_everything(spec.seed)
        rng = random.Random(spec.seed)
        device = hf.pick_device(spec, report)
        model = sc.inception_net(len(card["channel_names"]), int(params["width"]),
                                 int(params["depth"]), classes).to(device)

        if epoch_mode:
            examples, size = self._epochs(train, labels, rate, card["epoch_length"])
            counts = numpy.bincount([e[2] for e in examples], minlength=classes)
        else:
            frame_truth = [self._frame_labels(rec, labels, rate) for rec in train]
            size = max(8, int(round(card["window_s"] * rate)))
            examples = list(range(int(params["windows_per_epoch"])))
            counts = numpy.sum([numpy.bincount(t, minlength=classes) for t in frame_truth],
                               axis=0)
        if not len(examples):
            raise TrainerError("No annotated epoch fits inside its recording")
        weight = None
        if params.get("balanced", True):
            share = counts / max(1, counts.sum())
            weight = torch.tensor(numpy.where(share > 0, 1.0 / numpy.maximum(share, 1e-6), 0.0)
                                  / max(1, (share > 0).sum()), dtype=torch.float32,
                                  device=device)
        report.log("info", "%d recordings (%d channels at %g Hz), %d val; %s mode; "
                   "%d label(s)%s" % (len(train), len(card["channel_names"]), rate, len(val),
                                      card["mode"], len(labels),
                                      "; %d epochs" % len(examples) if epoch_mode else ""))

        def loss_of(batch):
            if epoch_mode:
                x = numpy.stack([train[r]["array"][:, s:s + size] for r, s, _ in batch])
                y = torch.tensor([c for _r, _s, c in batch], device=device)
                logits = model(torch.from_numpy(x).to(device)).float().mean(-1)
                return F.cross_entropy(logits, y, weight=weight)
            xs, ys = [], []
            for _ in batch:
                r = rng.randrange(len(train))
                total = train[r]["array"].shape[1]
                s = rng.randint(0, max(0, total - size))
                x = train[r]["array"][:, s:s + size]
                y = frame_truth[r][s:s + size]
                if x.shape[1] < size:
                    x = numpy.pad(x, ((0, 0), (0, size - x.shape[1])))
                    y = numpy.pad(y, (0, size - len(y)), constant_values=-100)
                xs.append(x)
                ys.append(y)
            logits = model(torch.from_numpy(numpy.stack(xs)).to(device)).float()
            return F.cross_entropy(logits, torch.from_numpy(numpy.stack(ys)).to(device),
                                   weight=weight, ignore_index=-100)

        model_dir = os.path.join(spec.workdir, hf.MODEL_DIR)
        os.makedirs(model_dir, exist_ok=True)
        weights = os.path.join(model_dir, "signal.pt")
        selected = {"best": None}

        def on_epoch_end(epoch):
            if not val:
                return None
            metrics = score_intervals(
                [rec["row"]["targets"][schema.name] for rec in val],
                [{"intervals": self._predict(model, rec, labels, card, device)} for rec in val])
            name = "macro_f1" if epoch_mode else "interval_f1"
            score = metrics.get(name, 0.0)
            report.metric("val", name, score, step=epoch + 1)
            if selected["best"] is None or score > selected["best"]:
                selected["best"] = score
                torch.save(model.state_dict(), weights)
            return score

        report.status("running", "training")
        summary = hf.train_loop(model, examples, params, loss_of, report, device=device,
                                seed=spec.seed, on_epoch_end=on_epoch_end)
        if selected["best"] is None:
            torch.save(model.state_dict(), weights)
        version = "%s-%s-%s" % (self.name, schema.name, spec.run_id)
        card.update(trainer=self.name, schema=schema.name, kind=schema.kind,
                    label_order=labels, width=int(params["width"]),
                    depth=int(params["depth"]), model_version=version, device=device,
                    n_train=len(train), bundle_digest=bundle.digest,
                    selected_epoch=summary["best_epoch"])
        hf.write_card(spec.workdir, card)
        metrics = {"n_train": float(len(train)), "train_seconds": summary["train_seconds"],
                   "epochs_run": float(summary["epochs_run"])}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        return FitResult(model_version=version, artifact_paths=hf.artifact_files(spec.workdir),
                         metrics=metrics, label_order=labels,
                         selected_on="val" if val else "")

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch
        card = hf.read_card(artifact_dir)
        labels = list(card["label_order"])
        classes = len(labels) if card["mode"] == "epoch" else len(labels) + 1
        device = hf.pick_device(spec, report)
        model = sc.inception_net(len(card["channel_names"]), int(card["width"]),
                                 int(card["depth"]), classes)
        model.load_state_dict(torch.load(os.path.join(artifact_dir, hf.MODEL_DIR, "signal.pt"),
                                         map_location="cpu"))
        model.to(device).eval()
        self._schema = spec.primary_schema.name
        items = [item for item in items if sc.has_input(item.data, item.media)]
        for n, item in enumerate(items):
            try:
                rec = self._recording(item.data, item.media, card)
            except Exception as exc:  # noqa: BLE001
                report.log("warning", "%s: %s" % (item.instance_id, exc))
                continue
            intervals = self._predict(model, rec, labels, card, device)
            report.progress("predict", n + 1, len(items))
            payload = {"intervals": intervals, "events": [], "source": "model"}
            confidence = min((iv["confidence"] for iv in intervals), default=None)
            yield PredictionRecord(instance_id=item.instance_id,
                                   schema_name=spec.primary_schema.name, payload=payload,
                                   confidence=confidence)
            if report.should_stop():
                return
