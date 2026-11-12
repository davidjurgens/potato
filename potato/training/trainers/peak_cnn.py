"""Peak picking on spectra with a 1D CNN, from the peaks annotators kept.

For ``peak_picking`` schemes. Each annotated spectrum is one example: the
spectrum the scheme's ``viewer_field`` shows, read by the same readers as
the page (JCAMP-DX, mzML, CSV, inline), and the peaks the annotator
accepted or added. A rejected suggestion is a place with no peak, which the
target already says by having none there.

The spectrum is resampled to ``length`` evenly spaced points, scaled to 0..1
with peaks pointing up (a transmittance IR spectrum is flipped, as the
display flips it), and the network predicts each point's chance of being a
peak, trained against a Gaussian bump at each kept peak. Prediction keeps
the points above ``threshold`` that are the highest within ``min_separation``
points, snaps each to the spectrum's own extremum nearby, and maps it back
to x. Peak labels and assignments are not predicted.

Predictions are review suggestions on the page (``prepick.method: model``
or ``auto``), with ``source: model``. Needs torch.
"""

from __future__ import annotations

import os
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf
from potato.training.trainers import _science_common as sc

INSTALL_HINT = "pip install 'potato-annotation[train-vision]'"
_NEEDS = ("torch", "numpy")


def _build(width: int, depth: int):
    import torch
    from torch import nn

    class PeakNet(nn.Module):
        """Dilated residual convolutions: a wide view of the baseline at
        full resolution, which a peak's shape needs."""

        def __init__(self):
            super().__init__()
            self.stem = nn.Conv1d(2, width, 7, padding=3)
            self.layers = nn.ModuleList()
            for n in range(depth):
                dilation = 2 ** (n % 5)
                self.layers.append(nn.Sequential(
                    nn.Conv1d(width, width, 5, padding=2 * dilation, dilation=dilation),
                    nn.BatchNorm1d(width), nn.ReLU(inplace=True)))
            self.head = nn.Conv1d(width, 1, 1)

        def forward(self, x):
            x = torch.relu(self.stem(x))
            for layer in self.layers:
                x = x + layer(x)
            return self.head(x)[:, 0]

    return PeakNet()


def _inputs(values):
    """The scaled spectrum and its first difference, which makes a peak's
    apex (where the slope changes sign) easy to see."""
    import numpy
    slope = numpy.gradient(values)
    scale = float(numpy.abs(slope).max()) or 1.0
    return numpy.stack([values, slope / scale]).astype("float32")


def _heatmap(grid, peaks: List[float], sigma: float):
    import numpy
    step = (grid[-1] - grid[0]) / (len(grid) - 1) if len(grid) > 1 else 1.0
    out = numpy.zeros(len(grid), dtype="float32")
    index = numpy.arange(len(grid))
    for x in peaks:
        centre = (x - grid[0]) / step if step else 0.0
        out = numpy.maximum(out, numpy.exp(-0.5 * ((index - centre) / sigma) ** 2))
    return out


def pick(probabilities, values, threshold: float, separation: int, snap: int,
         max_peaks: int) -> List[Tuple[int, float]]:
    """``(index, probability)`` of each picked peak: above *threshold*, the
    highest within *separation* points, then moved to the spectrum's highest
    point within *snap* points."""
    import numpy
    order = numpy.argsort(-probabilities)
    taken = numpy.zeros(len(probabilities), dtype=bool)
    out, apexes = [], set()
    for i in order:
        p = float(probabilities[i])
        if p < threshold or len(out) >= max_peaks:
            break
        if taken[max(0, i - separation):i + separation + 1].any():
            continue
        taken[i] = True
        lo, hi = max(0, i - snap), min(len(values), i + snap + 1)
        apex = int(lo + int(numpy.argmax(values[lo:hi])))
        if apex in apexes:
            # Two picks that snap to one apex are one peak; the first,
            # likelier one is kept.
            continue
        apexes.add(apex)
        out.append((apex, p))
    return out


class PeakCNNTrainer(Trainer):
    name: ClassVar[str] = "peak-cnn"
    description: ClassVar[str] = (
        "Peak picking on NMR, IR, Raman, UV-Vis and mass spectra: a 1D CNN "
        "trained on the peaks annotators kept, suggesting peaks on the rest.")
    kinds: ClassVar[Tuple[str, ...]] = ("peaks",)
    modalities: ClassVar[Tuple[str, ...]] = ("spectrum",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "BSD-3-Clause"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"epochs": 60, "batch_size": 8, "learning_rate": 1e-3, "weight_decay": 1e-4,
                "warmup_ratio": 0.05, "patience": 10, "precision": "fp32",
                "length": 4096, "width": 32, "depth": 10, "sigma": 2.0,
                "threshold": 0.5, "min_separation": 4, "snap": 3, "max_peaks": 80,
                "tolerance": None, "min_instances": 5}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = {key: hf.COMMON_PARAMS[key] for key in
                 ("epochs", "batch_size", "weight_decay", "warmup_ratio", "patience",
                  "precision", "min_instances")}
        props["epochs"] = dict(props["epochs"], default=60)
        props["batch_size"] = dict(props["batch_size"], default=8)
        props["patience"] = dict(props["patience"], default=10)
        props["precision"] = dict(props["precision"], default="fp32")
        props["min_instances"] = dict(props["min_instances"], default=5,
                                      description="Annotated spectra needed in the "
                                                  "train split.")
        props.update({
            "learning_rate": {"type": "number", "exclusiveMinimum": 0, "default": 1e-3},
            "length": {"type": "integer", "minimum": 256, "default": 4096,
                       "description": "Points each spectrum is resampled to. Raise it "
                                      "for spectra whose peaks are narrower than "
                                      "1/length of the x range."},
            "width": {"type": "integer", "minimum": 8, "default": 32},
            "depth": {"type": "integer", "minimum": 2, "maximum": 30, "default": 10},
            "sigma": {"type": "number", "exclusiveMinimum": 0, "default": 2.0,
                      "description": "Width of the target bump at each peak, in points."},
            "threshold": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5,
                          "description": "Probability a point needs to be a peak."},
            "min_separation": {"type": "integer", "minimum": 1, "default": 4,
                               "description": "Points between two predicted peaks."},
            "snap": {"type": "integer", "minimum": 0, "default": 3,
                     "description": "Points a predicted peak may move to reach the "
                                    "spectrum's own extremum."},
            "max_peaks": {"type": "integer", "minimum": 1, "default": 80},
            "tolerance": {"type": ["number", "null"], "exclusiveMinimum": 0,
                          "default": None,
                          "description": "How far, in x units (ppm, 1/cm, m/z), a "
                                         "predicted peak may be from an annotated one "
                                         "and still match when scored. null is 0.5% "
                                         "of the spectrum's x range."},
        })
        return {"type": "object", "properties": props, "additionalProperties": False}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        if schema.kind not in self.kinds:
            return ["Schema %r is %s; this trainer picks peaks on peak_picking schemes."
                    % (schema.name, schema.kind)]
        rows = [r for r in hf.rows_with_target(bundle.read_split("train"), schema.name)
                if sc.has_input(r, bundle.resolve_media(r["media"]) if r.get("media")
                                else None)]
        if len(rows) < int(params["min_instances"]):
            return ["Only %d annotated spectra with a readable file in the train split; "
                    "this trainer needs at least %d."
                    % (len(rows), int(params["min_instances"]))]
        return []

    # ------------------------------------------------------------ data

    def _example(self, row, media, length: int, sigma: Optional[float]):
        spectrum = sc.spectrum_of(row, media)
        options = sc.science_of(row).get("options") or {}
        direction = sc.peak_direction(spectrum, options)
        grid, values = sc.resample_spectrum(spectrum, length, direction)
        example = {"row": row, "grid": grid, "values": values, "inputs": _inputs(values),
                   "x_range": [float(spectrum.x[0]), float(spectrum.x[-1])]}
        if sigma is not None:
            target = row["targets"][self._schema]
            example["truth"] = _heatmap(grid, [p["x"] for p in target["peaks"]], sigma)
        return example

    def _examples(self, bundle, split, length, sigma, report):
        out, unreadable = [], []
        for row in hf.rows_with_target(bundle.read_split(split), self._schema):
            media = bundle.resolve_media(row["media"]) if row.get("media") else None
            if not sc.has_input(row, media):
                unreadable.append(row["instance_id"])
                continue
            try:
                out.append(self._example(row, media, length, sigma))
            except Exception as exc:  # noqa: BLE001 - one bad file is one row
                unreadable.append("%s (%s)" % (row["instance_id"], exc))
        if unreadable:
            report.log("warning", "Left out %d %s spectra with no readable file: %s"
                       % (len(unreadable), split, ", ".join(unreadable[:5])))
        return out

    def _predict_peaks(self, model, examples, device, params):
        import numpy
        import torch
        out = []
        with torch.inference_mode():
            for start in range(0, len(examples), 16):
                chunk = examples[start:start + 16]
                x = torch.from_numpy(numpy.stack([e["inputs"] for e in chunk])).to(device)
                probabilities = torch.sigmoid(model(x).float()).cpu().numpy()
                for example, probs in zip(chunk, probabilities):
                    picked = pick(probs, example["values"], float(params["threshold"]),
                                  int(params["min_separation"]), int(params["snap"]),
                                  int(params["max_peaks"]))
                    peaks = sorted(({"x": round(float(example["grid"][i]), 6),
                                     "confidence": round(p, 4)} for i, p in picked),
                                   key=lambda e: e["x"])
                    payload = {"peaks": peaks, "x_range": example["x_range"],
                               "source": "model"}
                    if params.get("tolerance"):
                        payload["tolerance"] = float(params["tolerance"])
                    out.append(payload)
        return out

    # ------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        import numpy
        import torch
        import torch.nn.functional as F
        from potato.training.science_metrics import score_peaks
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        self._schema = schema.name
        length, sigma = int(params["length"]), float(params["sigma"])
        train = self._examples(bundle, "train", length, sigma, report)
        val = self._examples(bundle, "val", length, sigma, report)
        if not train:
            raise TrainerError("No annotated spectra with a readable file for %r"
                               % schema.name)
        hf.seed_everything(spec.seed)
        device = hf.pick_device(spec, report)
        model = _build(int(params["width"]), int(params["depth"])).to(device)
        positives = float(sum(float((e["truth"] > 0.5).sum()) for e in train))
        weight = torch.tensor(min(100.0, (len(train) * length - positives) /
                                  max(positives, 1.0)), device=device)
        report.log("info", "%d spectra, %d val; %d points each; %d peaks in train"
                   % (len(train), len(val), length,
                      sum(len(e["row"]["targets"][schema.name]["peaks"]) for e in train)))

        def loss_of(batch):
            x = torch.from_numpy(numpy.stack([e["inputs"] for e in batch])).to(device)
            y = torch.from_numpy(numpy.stack([e["truth"] for e in batch])).to(device)
            # Mirror the x axis half the time: a peak is a peak either way
            # (the slope channel changes sign with it).
            flip = torch.rand(len(batch), device=device) < 0.5
            x = torch.where(flip[:, None, None], x.flip(-1) * torch.tensor(
                [1.0, -1.0], device=device)[None, :, None], x)
            y = torch.where(flip[:, None], y.flip(-1), y)
            return F.binary_cross_entropy_with_logits(model(x).float(), y, pos_weight=weight)

        model_dir = os.path.join(spec.workdir, hf.MODEL_DIR)
        os.makedirs(model_dir, exist_ok=True)
        weights = os.path.join(model_dir, "peaks.pt")
        selected = {"best": None}

        def on_epoch_end(epoch):
            if not val:
                return None
            metrics = score_peaks([e["row"]["targets"][schema.name] for e in val],
                                  self._predict_peaks(model, val, device, params))
            score = metrics.get("f1", 0.0)
            report.metric("val", "f1", score, step=epoch + 1)
            if selected["best"] is None or score > selected["best"]:
                selected["best"] = score
                torch.save(model.state_dict(), weights)
            return score

        report.status("running", "training")
        summary = hf.train_loop(model, train, params, loss_of, report, device=device,
                                seed=spec.seed, on_epoch_end=on_epoch_end)
        if selected["best"] is None:
            torch.save(model.state_dict(), weights)
        version = "%s-%s-%s" % (self.name, schema.name, spec.run_id)
        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "length": length, "width": int(params["width"]), "depth": int(params["depth"]),
            "threshold": float(params["threshold"]),
            "min_separation": int(params["min_separation"]), "snap": int(params["snap"]),
            "max_peaks": int(params["max_peaks"]), "tolerance": params.get("tolerance"),
            "model_version": version, "device": device, "n_train": len(train),
            "bundle_digest": bundle.digest, "selected_epoch": summary["best_epoch"]})
        metrics = {"n_train": float(len(train)), "train_seconds": summary["train_seconds"],
                   "epochs_run": float(summary["epochs_run"])}
        if summary["final_loss"] is not None:
            metrics["train_loss"] = round(summary["final_loss"], 4)
        return FitResult(model_version=version, artifact_paths=hf.artifact_files(spec.workdir),
                         metrics=metrics, selected_on="val" if val else "")

    # ------------------------------------------------------------ predict

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch
        card = hf.read_card(artifact_dir)
        device = hf.pick_device(spec, report)
        model = _build(int(card["width"]), int(card["depth"]))
        model.load_state_dict(torch.load(os.path.join(artifact_dir, hf.MODEL_DIR, "peaks.pt"),
                                         map_location="cpu"))
        model.to(device).eval()
        self._schema = spec.primary_schema.name
        items = [item for item in items if sc.has_input(item.data, item.media)]
        for n, item in enumerate(items):
            try:
                example = self._example(item.data, item.media, int(card["length"]), None)
            except Exception as exc:  # noqa: BLE001
                report.log("warning", "%s: %s" % (item.instance_id, exc))
                continue
            payload = self._predict_peaks(model, [example], device, card)[0]
            report.progress("predict", n + 1, len(items))
            confidence = min((p["confidence"] for p in payload["peaks"]), default=None)
            yield PredictionRecord(instance_id=item.instance_id,
                                   schema_name=spec.primary_schema.name, payload=payload,
                                   confidence=confidence)
            if report.should_stop():
                return
