"""3D segmentation of medical volumes with a U-Net, from painted label masks.

For ``volume_annotation`` schemes. Each annotated volume is one example: the
NIfTI file or DICOM series, read in the canonical RAS+ voxel order the
widget paints in, and its masks as one label per voxel (background, then the
scheme's labels in the bundle's order; where two labels overlap the later
one wins, as the NIfTI export does).

The network is a plain-torch 3D U-Net (three levels, instance norm), trained
with cross-entropy plus soft Dice on random patches, half of them centred on
a painted voxel so that small structures are seen. Intensities are clipped to
the 0.5 and 99.5 percentiles of each volume and standardized. Prediction
slides the patch over the whole volume with half-patch overlap and averages
the probabilities. Masks come back in the widget's stored shape (per label,
per axial slice, run-length encoded) with ``prefilled_from: "model"``.

No MONAI: the pieces it would supply here are a dozen lines each, and it is
one more install on the GPU host. Needs torch and nibabel (pydicom for
DICOM series). A GPU in practice: a 512 x 512 x 120 CT is a few hundred
patches to predict.
"""

from __future__ import annotations

import os
import random
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf

INSTALL_HINT = "pip install 'potato-annotation[train-vision,volumes]'"
_NEEDS = ("torch", "nibabel", "numpy")


def _local(path: Optional[str]) -> bool:
    return bool(path) and not str(path).startswith(("http://", "https://")) \
        and os.path.exists(str(path))


def _normalize(data):
    import numpy
    data = numpy.asarray(data, dtype="float32")
    low, high = numpy.percentile(data, (0.5, 99.5))
    data = numpy.clip(data, low, high)
    return ((data - data.mean()) / (data.std() or 1.0)).astype("float32")


def _build(levels: int, base: int, classes: int):
    import torch
    from torch import nn

    def block(cin, cout):
        return nn.Sequential(
            nn.Conv3d(cin, cout, 3, padding=1), nn.InstanceNorm3d(cout, affine=True),
            nn.LeakyReLU(0.01, inplace=True),
            nn.Conv3d(cout, cout, 3, padding=1), nn.InstanceNorm3d(cout, affine=True),
            nn.LeakyReLU(0.01, inplace=True))

    class UNet3D(nn.Module):
        def __init__(self):
            super().__init__()
            widths = [base * 2 ** n for n in range(levels)]
            self.down = nn.ModuleList()
            cin = 1
            for width in widths:
                self.down.append(block(cin, width))
                cin = width
            self.pool = nn.MaxPool3d(2)
            self.up = nn.ModuleList()
            self.merge = nn.ModuleList()
            for width in reversed(widths[:-1]):
                self.up.append(nn.ConvTranspose3d(cin, width, 2, stride=2))
                self.merge.append(block(width * 2, width))
                cin = width
            self.head = nn.Conv3d(cin, classes, 1)

        def forward(self, x):
            skips = []
            for n, layer in enumerate(self.down):
                x = layer(x)
                if n < len(self.down) - 1:
                    skips.append(x)
                    x = self.pool(x)
            for up, merge in zip(self.up, self.merge):
                x = up(x)
                x = merge(torch.cat([x, skips.pop()], dim=1))
            return self.head(x)

    return UNet3D()


class VolumeUNetTrainer(Trainer):
    name: ClassVar[str] = "volume-unet"
    description: ClassVar[str] = (
        "3D segmentation of CT/MR volumes: trains a U-Net on the painted label "
        "masks and paints masks on the rest.")
    kinds: ClassVar[Tuple[str, ...]] = ("volume",)
    modalities: ClassVar[Tuple[str, ...]] = ("volume",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "BSD-3-Clause"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"epochs": 50, "batch_size": 2, "patches_per_epoch": 100, "patch": 64,
                "levels": 3, "base_channels": 16, "learning_rate": 3e-4,
                "weight_decay": 1e-5, "warmup_ratio": 0.05, "patience": 10,
                "foreground_share": 0.5, "precision": "auto", "min_instances": 3}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        props = {key: hf.COMMON_PARAMS[key] for key in
                 ("epochs", "batch_size", "weight_decay", "warmup_ratio", "patience",
                  "precision", "min_instances")}
        props["epochs"] = dict(props["epochs"], default=50)
        props["batch_size"] = dict(props["batch_size"], default=2, description="Patches per step.")
        props["patience"] = dict(props["patience"], default=10)
        props["min_instances"] = dict(props["min_instances"], default=3,
                                      description="Annotated volumes needed in the train split.")
        props.update({
            "learning_rate": {"type": "number", "exclusiveMinimum": 0, "default": 3e-4},
            "patches_per_epoch": {"type": "integer", "minimum": 1, "default": 100,
                                  "description": "Random patches per epoch."},
            "patch": {"type": "integer", "minimum": 8, "default": 64,
                      "description": "Side of the cubic patch, in voxels (a multiple of "
                                     "2 to the levels - 1)."},
            "levels": {"type": "integer", "minimum": 2, "maximum": 5, "default": 3},
            "base_channels": {"type": "integer", "minimum": 4, "default": 16},
            "foreground_share": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5,
                                 "description": "Share of patches centred on a painted voxel."},
        })
        return {"type": "object", "properties": props, "additionalProperties": False}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        problems = []
        if schema.kind not in self.kinds:
            problems.append("Schema %r is %s; this trainer handles volume_annotation masks."
                            % (schema.name, schema.kind))
        step = 2 ** (int(params["levels"]) - 1)
        if int(params["patch"]) % step:
            problems.append("patch must be a multiple of %d for %d levels"
                            % (step, int(params["levels"])))
        n = len(hf.rows_with_target(bundle.read_split("train"), schema.name))
        if n < int(params["min_instances"]):
            problems.append("Only %d annotated volumes in the train split; this trainer needs "
                            "at least %d." % (n, int(params["min_instances"])))
        return problems

    # ------------------------------------------------------------ data

    @staticmethod
    def _read(path: str):
        from potato.media.volumes import read_volume
        return read_volume(path)

    def _examples(self, bundle: BundleRef, split: str, schema: str, labels: List[str],
                  report: ProgressReporter) -> List[Dict[str, Any]]:
        import numpy
        from potato.media.volume_masks import labelmap
        out, missing = [], 0
        for row in hf.rows_with_target(bundle.read_split(split), schema):
            path = bundle.resolve_media(row["media"]) if row.get("media") else None
            if not _local(path):
                missing += 1
                continue
            volume = self._read(path)
            target = row["targets"][schema]
            if [int(n) for n in target.get("shape") or volume.shape] != list(volume.shape):
                report.log("warning", "%s: painted on a %s volume, the file is %s; left out"
                           % (row["instance_id"], target.get("shape"), list(volume.shape)))
                continue
            truth = labelmap(target, volume.shape, labels).astype("int64")
            out.append({"row": row, "image": _normalize(volume.data), "truth": truth,
                        "foreground": numpy.argwhere(truth > 0)})
        if missing:
            report.log("warning", "Left out %d %s volume(s) with no local file" % (missing, split))
        return out

    @staticmethod
    def _patch(example, size: int, rng: random.Random, foreground_share: float):
        import numpy
        image, truth = example["image"], example["truth"]
        shape = image.shape
        if len(example["foreground"]) and rng.random() < foreground_share:
            centre = example["foreground"][rng.randrange(len(example["foreground"]))]
            start = [int(c) - size // 2 for c in centre]
        else:
            start = [rng.randint(0, max(0, n - size)) for n in shape]
        start = [min(max(0, s), max(0, n - size)) for s, n in zip(start, shape)]
        window = tuple(slice(s, s + size) for s in start)
        img, lab = image[window], truth[window]
        pad = [(0, size - n) for n in img.shape]
        if any(p[1] for p in pad):
            img = numpy.pad(img, pad, constant_values=float(image.min()))
            lab = numpy.pad(lab, pad)
        return img, lab

    # ------------------------------------------------------------ model

    def _predict_volume(self, model, image, classes: int, size: int, device: str):
        """Class probabilities over the whole volume, sliding a patch with
        half-patch overlap and averaging where windows overlap."""
        import numpy
        import torch
        shape = image.shape
        step = max(1, size // 2)

        def starts(n):
            if n <= size:
                return [0]
            out = list(range(0, n - size + 1, step))
            if out[-1] + size < n:
                out.append(n - size)
            return out

        total = numpy.zeros((classes,) + shape, dtype="float32")
        counts = numpy.zeros(shape, dtype="float32")
        model.eval()
        with torch.inference_mode():
            for i in starts(shape[0]):
                for j in starts(shape[1]):
                    for k in starts(shape[2]):
                        window = (slice(i, i + size), slice(j, j + size), slice(k, k + size))
                        block = image[window]
                        pad = [(0, size - n) for n in block.shape]
                        tensor = numpy.pad(block, pad, constant_values=float(image.min())
                                           ).astype("float32")
                        logits = model(torch.from_numpy(tensor[None, None]).to(device))
                        probs = torch.softmax(logits.float(), dim=1)[0].cpu().numpy()
                        probs = probs[(slice(None),) + tuple(slice(0, n) for n in block.shape)]
                        total[(slice(None),) + window] += probs
                        counts[window] += 1
        return total / numpy.maximum(counts, 1)

    @staticmethod
    def _dice(truth, guess, classes: int) -> float:
        scores = []
        for c in range(1, classes):
            a, b = truth == c, guess == c
            denominator = int(a.sum()) + int(b.sum())
            if denominator:
                scores.append(2.0 * int((a & b).sum()) / denominator)
        return sum(scores) / len(scores) if scores else 1.0

    # ------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        import torch
        import torch.nn.functional as F
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        labels = list(bundle.labels(schema.name))
        classes = len(labels) + 1
        size = int(params["patch"])
        train = self._examples(bundle, "train", schema.name, labels, report)
        val = self._examples(bundle, "val", schema.name, labels, report)
        if not train:
            raise TrainerError("No annotated volumes with a local file for %r" % schema.name)
        hf.seed_everything(spec.seed)
        rng = random.Random(spec.seed)
        device = hf.pick_device(spec, report)
        model = _build(int(params["levels"]), int(params["base_channels"]), classes).to(device)
        report.log("info", "%d volumes (%s), %d val; %d labels; %d-voxel patches"
                   % (len(train), ", ".join("x".join(str(n) for n in e["image"].shape)
                                            for e in train[:3]),
                      len(val), len(labels), size))
        # One entry per patch; loss_of draws the patch, so each epoch sees new ones.
        draws = [n % len(train) for n in range(int(params["patches_per_epoch"]))]

        def loss_of(batch):
            import numpy
            images, truths = zip(*(self._patch(train[n], size, rng,
                                               float(params["foreground_share"]))
                                   for n in batch))
            x = torch.from_numpy(numpy.stack(images)[:, None]).to(device)
            y = torch.from_numpy(numpy.stack(truths)).to(device)
            logits = model(x)
            probs = torch.softmax(logits.float(), dim=1)
            onehot = F.one_hot(y, classes).permute(0, 4, 1, 2, 3).float()
            dims = (0, 2, 3, 4)
            dice = (2 * (probs * onehot).sum(dims) + 1) / (probs.sum(dims) + onehot.sum(dims) + 1)
            return F.cross_entropy(logits.float(), y) + (1 - dice[1:].mean())

        model_dir = os.path.join(spec.workdir, hf.MODEL_DIR)
        os.makedirs(model_dir, exist_ok=True)
        weights = os.path.join(model_dir, "unet.pt")
        selected = {"best": None}

        def on_epoch_end(epoch):
            if not val:
                return None
            scores = [self._dice(e["truth"], self._predict_volume(
                model, e["image"], classes, size, device).argmax(0), classes) for e in val]
            score = sum(scores) / len(scores)
            report.metric("val", "mean_dice", score, step=epoch + 1)
            if selected["best"] is None or score > selected["best"]:
                selected["best"] = score
                torch.save(model.state_dict(), weights)
            model.train()
            return score

        report.status("running", "training")
        summary = hf.train_loop(model, draws, params, loss_of, report, device=device,
                                seed=spec.seed, on_epoch_end=on_epoch_end)
        if selected["best"] is None:
            torch.save(model.state_dict(), weights)
        version = "%s-%s-%s" % (self.name, schema.name, spec.run_id)
        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "label_order": labels, "levels": int(params["levels"]),
            "base_channels": int(params["base_channels"]), "patch": size,
            "model_version": version, "device": device, "n_train": len(train),
            "bundle_digest": bundle.digest, "selected_epoch": summary["best_epoch"]})
        metrics = {"n_train": float(len(train)), "train_seconds": summary["train_seconds"],
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
        from potato.media.volume_masks import masks_from_volume
        card = hf.read_card(artifact_dir)
        labels = list(card["label_order"])
        classes = len(labels) + 1
        device = hf.pick_device(spec, report)
        model = _build(int(card["levels"]), int(card["base_channels"]), classes)
        model.load_state_dict(torch.load(os.path.join(artifact_dir, hf.MODEL_DIR, "unet.pt"),
                                         map_location="cpu"))
        model.to(device)
        items = [item for item in items if _local(item.media)]
        for n, item in enumerate(items):
            volume = self._read(item.media)
            probs = self._predict_volume(model, _normalize(volume.data), classes,
                                         int(card["patch"]), device)
            guess = probs.argmax(0)
            report.progress("predict", n + 1, len(items))
            masks, confidences = {}, []
            for c, label in enumerate(labels, start=1):
                region = guess == c
                if region.any():
                    masks[label] = masks_from_volume(region)
                    confidences.append(float(probs[c][region].mean()))
            if not masks:
                continue
            payload = {"volume": item.data.get("media_source") or "",
                       "shape": [int(s) for s in volume.shape], "labels": labels,
                       "masks": masks, "shapes": [], "prefilled_from": "model"}
            yield PredictionRecord(instance_id=item.instance_id,
                                   schema_name=spec.primary_schema.name, payload=payload,
                                   confidence=round(min(confidences), 4))
            if report.should_stop():
                return
