"""Point-cloud cuboids: targets, 3D AP, prelabel cleaning, and external-3d
run end to end with a stand-in detector script."""

import json
import math
import os
import sys
import textwrap

import pytest

from potato.training import registry
from potato.training.dataset import build_bundle
from potato.training.evaluation import HEADLINE, score_split
from potato.training.events import EXIT_OK
from tests.unit.test_training_trainers import _context, _predictions, _run, _spec

np = pytest.importorskip("numpy")

SCHEME = {"annotation_type": "spatial_annotation", "name": "objs", "description": "",
          "labels": [{"name": "Car"}], "tools": ["cuboid_3d"]}


def cuboid(label, center, size, yaw=0.0, **extra):
    return dict({"type": "cuboid_3d", "label": label, "coordinates": {
        "center": list(center), "size": list(size),
        "rotation": [0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2)]}}, **extra)


def scan(path, center, size, seed=0):
    """A KITTI .bin: ground points plus a box-shaped cluster at *center*."""
    rng = np.random.default_rng(seed)
    ground = np.column_stack([rng.uniform(-20, 20, 400), rng.uniform(-20, 20, 400),
                              np.zeros(400), np.full(400, 0.1)])
    box = np.column_stack([rng.uniform(c - s / 2, c + s / 2, 300) for c, s in zip(center, size)]
                          + [np.full(300, 0.9)])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    np.vstack([ground, box]).astype("float32").tofile(str(path))


def spatial_project(tmp, n=6):
    items, annotations = {}, []
    for i in range(n):
        iid = "s%d" % i
        center, size = (5.0 + i, -2.0, 1.0), (4.0, 2.0, 1.5)
        scan(tmp / "media" / ("s%d.bin" % i), center, size, seed=i)
        items[iid] = {"id": iid, "point_cloud": "media/s%d.bin" % i}
        annotations.append({"instance_id": iid, "user_id": "a", "labels": {"objs": {
            "_data": json.dumps([cuboid("Car", center, size),
                                 {"type": "point_3d", "label": "Car", "coordinates": [1, 1, 1]}])}}})
    return _context(tmp, [SCHEME], items, annotations)


#: Boxes the points well above the ground, the cluster: a detector in
#: miniature, so the run's plumbing is exercised without a CUDA build.
DETECTOR = textwrap.dedent('''
    import os, sys
    import numpy as np
    dataset, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    for key in open(os.path.join(dataset, "ImageSets", "predict.txt")).read().split():
        p = np.load(os.path.join(dataset, "points", key + ".npy"))
        top = p[p[:, 2] > 0.3][:, :3]
        lo, hi = top.min(0), top.max(0)
        c, s = (lo + hi) / 2, hi - lo
        with open(os.path.join(out, key + ".txt"), "w") as fh:
            fh.write("%f %f %f %f %f %f 0.0 Car 0.9\\n" % (*c, *s))
            fh.write("1 1 1 1 1 1 0 Bus 0.5\\nnot a box\\n")
''')


def test_cuboids_are_the_targets_and_the_trainer_is_offered(tmp_path):
    config, context = spatial_project(tmp_path, n=2)
    bundle, stats, _ = build_bundle(context, str(tmp_path / "b"), ["objs"],
                                    split_spec={"train": 1.0})
    assert bundle.manifest["schemas"][0]["kind"] == "spatial"
    assert bundle.manifest["modality"] == "point_cloud"
    row = next(bundle.read_split("train"))
    (target,) = row["targets"]["objs"]          # the point_3d is not a detection target
    assert target["label"] == "Car" and target["size"] == [4.0, 2.0, 1.5]
    assert [t.name for t in registry.trainers_for_schema(SCHEME, "point_cloud")] == ["external-3d"]


def test_3d_ap_matches_by_volume_and_label():
    truth = {"label": "Car", "center": [0, 0, 0], "size": [4, 2, 1.5], "rotation": [0, 0, 0, 1]}
    rows = [{"instance_id": "a", "targets": {"o": [truth]}}]
    exact = {("a", "o"): [cuboid("Car", [0, 0, 0], [4, 2, 1.5], confidence=0.9)]}
    metrics, _ = score_split(rows, exact, "o", "spatial")
    assert metrics[HEADLINE["spatial"]] == pytest.approx(1.0)
    # Half the volume overlaps: IoU 1/3, a hit at 0.25 and a miss at 0.5.
    shifted = {("a", "o"): [cuboid("Car", [2, 0, 0], [4, 2, 1.5], confidence=0.9)]}
    metrics, _ = score_split(rows, shifted, "o", "spatial")
    assert metrics["map_3d_25"] == pytest.approx(1.0) and metrics["map_3d_50"] == 0.0
    # Rotated a quarter turn about z: a 4x2 box on a 2x4 one.
    turned = {("a", "o"): [cuboid("Car", [0, 0, 0], [4, 2, 1.5], yaw=math.pi / 2)]}
    metrics, _ = score_split(rows, turned, "o", "spatial")
    assert metrics["map_3d_50"] == 0.0
    wrong_label = {("a", "o"): [cuboid("Bus", [0, 0, 0], [4, 2, 1.5])]}
    assert score_split(rows, wrong_label, "o", "spatial")[0]["f1"] == 0.0


def test_spatial_prelabels_drop_what_the_viewer_cannot_show():
    from potato.server_utils.prelabel_values import client_spatial
    kept, dropped = client_spatial([
        cuboid("Car", [0, 0, 0], [4, 2, 1]),
        cuboid("Bus", [0, 0, 0], [4, 2, 1]),
        cuboid("Car", [0, 0, 0], [4, 0, 1]),
        {"type": "cuboid_3d", "label": "Car", "coordinates": {"center": "x"}},
        "not an object"], ["Car"])
    assert len(kept) == 1 and dropped == 4


def test_external_3d_runs_the_commands_and_reads_boxes_back(tmp_path):
    script = tmp_path / "detector.py"
    script.write_text(DETECTOR)
    marker = tmp_path / "trained.txt"
    trainer = tmp_path / "train.py"
    trainer.write_text("import sys, os\n"
                       "open(sys.argv[2], 'w').write(str(len(os.listdir(os.path.join("
                       "sys.argv[1], 'labels')))))\n")
    config, context = spatial_project(tmp_path, n=8)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["objs"], split_seed=0)
    spec = _spec(tmp_path, config, bundle, "external-3d", "objs", {
        "train_command": "%s %s {dataset} %s" % (sys.executable, trainer, marker),
        "predict_command": "%s %s {dataset} {predictions}" % (sys.executable, script)})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    assert int(marker.read_text()) == bundle.split_size("train") + bundle.split_size("val")
    metrics = result["metrics"]
    assert metrics["heldout_metric"].endswith("map_3d_50")
    # The cluster's extent is close to the annotated box.
    assert metrics["heldout_score"] > 0.9, metrics
    records = _predictions(spec)
    assert records
    (obj,) = records[0]["payload"]      # Bus and the bad line are left out
    assert obj["type"] == "cuboid_3d" and obj["label"] == "Car" and obj["source"] == "model"
    # Two bad lines in each predicted file.
    assert any("Left out %d predicted line" % (2 * len(records)) in e.get("msg", "")
               for e in report.of_type("log"))


def test_a_failing_command_fails_the_run_with_its_output(tmp_path):
    config, context = spatial_project(tmp_path, n=4)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["objs"], split_seed=0)
    spec = _spec(tmp_path, config, bundle, "external-3d", "objs", {
        "train_command": "%s -c \"import sys; print('no GPU'); sys.exit(3)\"" % sys.executable,
        "predict_command": "true"})
    code, result, report = _run(spec)
    assert code != EXIT_OK
    assert any("exited 3" in e.get("message", "") and "no GPU" in e.get("message", "")
               for e in report.of_type("error"))


def test_commands_keep_other_braces_and_nan_boxes_are_left_out(tmp_path):
    """Audit 105 B3/B4: str.format read any brace in a command as a
    placeholder; a nan heading became a NaN rotation the viewer cannot read."""
    script = tmp_path / "nan.py"
    script.write_text(textwrap.dedent('''
        import os, sys
        dataset, out = sys.argv[1], sys.argv[2]
        print({'a': 1})
        os.makedirs(out, exist_ok=True)
        for key in open(os.path.join(dataset, "ImageSets", "predict.txt")).read().split():
            with open(os.path.join(out, key + ".txt"), "w") as fh:
                fh.write("1 1 1 4 2 1.5 nan Car 0.9\\n1 1 1 4 2 1.5 0.0 Car inf\\n"
                         "1 1 1 4 2 1.5 0.0 Car 0.8\\n")
    '''))
    config, context = spatial_project(tmp_path, n=4)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["objs"], split_seed=0)
    spec = _spec(tmp_path, config, bundle, "external-3d", "objs", {
        "predict_command": "%s %s {dataset} {predictions} {a:1}" % (sys.executable, script)})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    records = _predictions(spec)
    assert records and all(len(r["payload"]) == 1 for r in records)
    assert records[0]["payload"][0]["source"] == "model"


def test_a_failing_predict_command_fails_a_run_that_trained_nothing(tmp_path):
    """Audit 108: with no train_command the predictions are the run, so a
    predict command that fails is a failed run, not a success with no score."""
    config, context = spatial_project(tmp_path, n=4)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["objs"], split_seed=0)
    failing = "%s -c \"import sys; sys.exit(4)\"" % sys.executable
    spec = _spec(tmp_path, config, bundle, "external-3d", "objs", {"predict_command": failing})
    code, _, report = _run(spec)
    assert code != EXIT_OK
    assert any("Prediction pass failed" in e.get("message", "") for e in report.of_type("error"))

    trained = _spec(tmp_path / "t", config, bundle, "external-3d", "objs", {
        "train_command": "true", "predict_command": failing})
    code, result, report = _run(trained)
    assert code == EXIT_OK, report.of_type("error")
    assert any("Prediction pass failed" in e.get("msg", "") for e in report.of_type("log"))


def test_a_run_that_trained_is_scored_on_test_first(tmp_path):
    """The train command is handed the val split, so test is the unseen one."""
    script = tmp_path / "detector.py"
    script.write_text(DETECTOR)
    config, context = spatial_project(tmp_path, n=8)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["objs"], split_seed=0)
    assert bundle.split_size("val") and bundle.split_size("test")
    predict = "%s %s {dataset} {predictions}" % (sys.executable, script)
    trained = _spec(tmp_path, config, bundle, "external-3d", "objs",
                    {"train_command": "true", "predict_command": predict})
    assert _run(trained)[1]["metrics"]["heldout_metric"].startswith("test ")
    untrained = _spec(tmp_path / "u", config, bundle, "external-3d", "objs",
                      {"predict_command": predict})
    assert _run(untrained)[1]["metrics"]["heldout_metric"].startswith("val ")


BROKEN_DETECTOR = """
import os, sys
dataset, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
lines = sys.argv[3].replace("|", "\\n")
if lines:
    for key in open(os.path.join(dataset, "ImageSets", "predict.txt")).read().split():
        with open(os.path.join(out, key + ".txt"), "w") as fh:
            fh.write(lines)
"""


@pytest.mark.parametrize("lines, needle", [("", "wrote no"),
                                           ("garbage line|nan nan|", "could be used")])
def test_a_detector_that_writes_nothing_usable_fails_the_run(tmp_path, lines, needle):
    """Audit 108 V3: a predict command that wrote no file, or only lines that
    could not be read, scored 0.0 as if it were a model that found nothing."""
    script = tmp_path / "broken.py"
    script.write_text(BROKEN_DETECTOR)
    config, context = spatial_project(tmp_path, n=4)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["objs"], split_seed=0)
    spec = _spec(tmp_path, config, bundle, "external-3d", "objs", {
        "predict_command": "%s %s {dataset} {predictions} '%s'" % (sys.executable, script, lines)})
    code, _, report = _run(spec)
    assert code != EXIT_OK
    assert any(needle in e.get("message", "") for e in report.of_type("error")), \
        report.of_type("error")
