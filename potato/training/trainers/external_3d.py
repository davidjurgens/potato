"""3D object detection in point clouds through an external detector.

For ``spatial_annotation`` cuboids. The detectors that work here (OpenPCDet,
MMDetection3D) need CUDA operators compiled for the GPU host, so Potato does
not vendor one. This trainer writes the annotated scans as a dataset those
tools read, runs the user's own train and predict commands on the training
host, and reads the predictions back as cuboids.

The dataset is OpenPCDet's custom format, in the scan's own frame (the
frame the viewer stores cuboids in; no camera calibration is needed):

- ``points/<id>.npy``: float32 ``(N, 4)``, x, y, z and intensity (0 when the
  file has none);
- ``labels/<id>.txt``: one line per cuboid, ``x y z dx dy dz heading label``,
  heading the rotation about +z in radians (pitch and roll are not kept);
- ``ImageSets/train.txt``, ``val.txt`` and ``predict.txt``: the ids.

A georeferenced scan whose coordinates are too large for float32 is written
relative to its origin, and its predictions are shifted back.

The commands are ``train_command`` and ``predict_command``, run with
``{dataset}``, ``{workdir}`` and ``{predictions}`` filled in, without a shell.
``predict_command`` writes ``<predictions>/<id>.txt``, one line per box:
``x y z dx dy dz heading label score``. Lines that do not parse, and labels
the scheme does not have, are left out and counted.
"""

from __future__ import annotations

import math
import os
import shlex
import subprocess
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf

_NEEDS = ("numpy",)
DATASET = "dataset"
PREDICTIONS = "predictions"


def _local(path: Optional[str]) -> bool:
    return bool(path) and not str(path).startswith(("http://", "https://")) \
        and os.path.isfile(str(path))


class External3DTrainer(Trainer):
    name: ClassVar[str] = "external-3d"
    description: ClassVar[str] = (
        "3D cuboid detection in point clouds with your own detector (OpenPCDet, "
        "MMDetection3D): writes the scans as a dataset, runs your train and "
        "predict commands, and reads the boxes back.")
    kinds: ClassVar[Tuple[str, ...]] = ("spatial",)
    modalities: ClassVar[Tuple[str, ...]] = ("point_cloud",)
    annotation_types: ClassVar[Tuple[str, ...]] = ("spatial_annotation",)
    install_hint: ClassVar[str] = "the detector itself is installed on the training host"
    licence: ClassVar[str] = "depends on the detector"
    commercial_use: ClassVar[Optional[bool]] = None

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"train_command": "", "predict_command": "", "timeout_s": 86400,
                "min_instances": 1}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        return {"type": "object", "additionalProperties": False, "properties": {
            "train_command": {"type": "string", "default": "",
                              "description": "Run once, in the run's folder, with {dataset} "
                                             "and {workdir} filled in. Empty: nothing is "
                                             "trained, and predict_command uses a model of "
                                             "your own."},
            "predict_command": {"type": "string", "default": "",
                                "description": "Writes {predictions}/<id>.txt for the ids in "
                                               "{dataset}/ImageSets/predict.txt."},
            "timeout_s": {"type": "integer", "minimum": 1, "default": 86400,
                          "description": "Seconds each command may run."},
            "min_instances": {"type": "integer", "minimum": 0, "default": 1,
                              "description": "Annotated scans needed in the train split."},
        }}

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        problems = []
        if schema.kind not in self.kinds:
            problems.append("Schema %r is %s; this trainer handles spatial_annotation "
                            "cuboids." % (schema.name, schema.kind))
        if not str(params.get("predict_command") or "").strip():
            problems.append("external-3d needs predict_command: the command that writes "
                            "{predictions}/<id>.txt.")
        n = len(hf.rows_with_target(bundle.read_split("train"), schema.name))
        if str(params.get("train_command") or "").strip() and n < int(params["min_instances"]):
            problems.append("Only %d annotated scans in the train split; train_command needs "
                            "at least %d." % (n, int(params["min_instances"])))
        return problems

    # ------------------------------------------------------------ dataset

    @staticmethod
    def _scan(path: str):
        """``(points float32 (N, 4), origin [x, y, z])``."""
        import numpy
        from potato.media.pointcloud import read_point_cloud
        cloud = read_point_cloud(path, max_points=0)
        xyz = numpy.frombuffer(cloud.positions, dtype="float32").reshape(-1, 3)
        intensity = (numpy.frombuffer(cloud.intensity, dtype="float32").reshape(-1, 1)
                     if cloud.intensity is not None else numpy.zeros((len(xyz), 1), "float32"))
        return (numpy.hstack([xyz, intensity]).astype("float32"),
                [float(v) for v in (cloud.origin or (0.0, 0.0, 0.0))])

    @staticmethod
    def _key(instance_id: str) -> str:
        """A file name for an item id; ids may hold any character."""
        import hashlib
        return hashlib.sha1(str(instance_id).encode()).hexdigest()[:16]

    def _write(self, folder: str, rows: Iterable[Dict[str, Any]], schema: Optional[str],
               resolve, report: ProgressReporter) -> Dict[str, Dict[str, Any]]:
        """Points (and labels when *schema* is given) for each row; returns
        ``{key: {instance_id, origin}}``."""
        import numpy
        from potato.export.spatial_utils import quaternion_to_yaw
        os.makedirs(os.path.join(folder, "points"), exist_ok=True)
        os.makedirs(os.path.join(folder, "labels"), exist_ok=True)
        written, missing = {}, 0
        for row in rows:
            path = resolve(row.get("media"))
            if not _local(path):
                missing += 1
                continue
            key = self._key(row["instance_id"])
            points, origin = self._scan(path)
            numpy.save(os.path.join(folder, "points", key + ".npy"), points)
            if schema is not None:
                lines = []
                for cuboid in (row.get("targets") or {}).get(schema) or []:
                    x, y, z = (c - o for c, o in zip(cuboid["center"], origin))
                    dx, dy, dz = cuboid["size"]
                    lines.append("%.4f %.4f %.4f %.4f %.4f %.4f %.6f %s" % (
                        x, y, z, dx, dy, dz, quaternion_to_yaw(cuboid["rotation"]),
                        cuboid["label"].replace(" ", "_")))
                with open(os.path.join(folder, "labels", key + ".txt"), "w") as fh:
                    fh.write("\n".join(lines) + ("\n" if lines else ""))
            written[key] = {"instance_id": row["instance_id"], "origin": origin}
        if missing:
            report.log("warning", "Left out %d scan(s) with no local file" % missing)
        return written

    @staticmethod
    def _ids(folder: str, name: str, keys: Iterable[str]) -> None:
        os.makedirs(os.path.join(folder, "ImageSets"), exist_ok=True)
        with open(os.path.join(folder, "ImageSets", name + ".txt"), "w") as fh:
            fh.write("".join(k + "\n" for k in keys))

    @staticmethod
    def _run(command: str, values: Dict[str, str], cwd: str, timeout: int,
             report: ProgressReporter, what: str) -> None:
        # Only these three are filled in, literally: str.format read any
        # other brace in a command, such as python -c "print({'a': 1})", as
        # a placeholder and failed with a KeyError.
        def fill(part):
            for key, value in values.items():
                part = part.replace("{%s}" % key, value)
            return part
        argv = [fill(part) for part in shlex.split(command)]
        report.log("info", "Running the %s command: %s" % (what, " ".join(argv)))
        try:
            done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                                  timeout=timeout)
        except FileNotFoundError as exc:
            raise TrainerError("The %s command could not start: %s" % (what, exc))
        except subprocess.TimeoutExpired:
            raise TrainerError("The %s command ran past timeout_s (%d s)" % (what, timeout))
        tail = (done.stdout + done.stderr).strip().splitlines()[-20:]
        if done.returncode:
            raise TrainerError("The %s command exited %d:\n%s"
                               % (what, done.returncode, "\n".join(tail)))
        for line in tail[-5:]:
            report.log("info", line[:300])

    # ------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, "pip install numpy")
        params = hf.merged_params(self.default_params(), spec)
        schema = spec.primary_schema
        folder = os.path.join(spec.workdir, DATASET)
        train = self._write(folder, hf.rows_with_target(bundle.read_split("train"), schema.name),
                            schema.name, bundle.resolve_media, report)
        val = self._write(folder, hf.rows_with_target(bundle.read_split("val"), schema.name),
                          schema.name, bundle.resolve_media, report)
        self._ids(folder, "train", train)
        self._ids(folder, "val", val)
        command = str(params.get("train_command") or "").strip()
        if command:
            if not train:
                raise TrainerError("No annotated scans with a local file for %r" % schema.name)
            report.status("running", "running the train command")
            self._run(command, {"dataset": folder, "workdir": spec.workdir,
                                "predictions": os.path.join(spec.workdir, PREDICTIONS)},
                      spec.workdir, int(params["timeout_s"]), report, "train")
        version = "%s-%s-%s" % (self.name, schema.name, spec.run_id)
        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "label_order": list(bundle.labels(schema.name)),
            "predict_command": str(params["predict_command"]),
            "timeout_s": int(params["timeout_s"]), "model_version": version,
            "n_train": len(train), "bundle_digest": bundle.digest})
        return FitResult(model_version=version, artifact_paths=hf.artifact_files(spec.workdir),
                         metrics={"n_train": float(len(train))},
                         label_order=list(bundle.labels(schema.name)),
                         selected_on="")

    # ------------------------------------------------------------ predict

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        from potato.training.spatial import client_cuboid
        card = hf.read_card(artifact_dir)
        labels = {str(l) for l in card.get("label_order") or []}
        by_file = {l.replace(" ", "_"): l for l in labels}
        folder = os.path.join(spec.workdir, DATASET)
        out_dir = os.path.join(spec.workdir, PREDICTIONS)
        os.makedirs(out_dir, exist_ok=True)
        rows = [{"instance_id": item.instance_id, "media": item.media} for item in items]
        written = self._write(folder, rows, None, lambda media: media, report)
        if not written:
            return
        self._ids(folder, "predict", written)
        report.status("running", "running the predict command")
        self._run(card["predict_command"], {"dataset": folder, "workdir": spec.workdir,
                                            "predictions": out_dir},
                  spec.workdir, int(card.get("timeout_s") or 86400), report, "predict")
        skipped = 0
        for n, (key, info) in enumerate(written.items()):
            report.progress("predict", n + 1, len(written))
            path = os.path.join(out_dir, key + ".txt")
            if not os.path.isfile(path):
                continue
            objects, scores = [], []
            with open(path) as fh:
                for line in fh:
                    fields = line.split()
                    if not fields:
                        continue
                    try:
                        x, y, z, dx, dy, dz, heading = (float(v) for v in fields[:7])
                        label = by_file.get(fields[7], fields[7])
                        score = float(fields[8]) if len(fields) > 8 else None
                    except (ValueError, IndexError):
                        skipped += 1
                        continue
                    numbers = [x, y, z, dx, dy, dz, heading] + ([score] if score is not None
                                                                else [])
                    if (label not in labels or min(dx, dy, dz) <= 0
                            or not all(math.isfinite(v) for v in numbers)):
                        skipped += 1
                        continue
                    origin = info["origin"]
                    obj = client_cuboid(label, [x + origin[0], y + origin[1], z + origin[2]],
                                        [dx, dy, dz], heading, score)
                    if obj is not None:
                        objects.append(obj)
                        if score is not None:
                            scores.append(score)
            if objects:
                yield PredictionRecord(instance_id=info["instance_id"],
                                       schema_name=spec.primary_schema.name, payload=objects,
                                       confidence=round(min(scores), 4) if scores else None)
        if skipped:
            report.log("warning", "Left out %d predicted line(s) that are not "
                                  "'x y z dx dy dz heading label [score]' with a scheme label "
                                  "and a positive size" % skipped)
