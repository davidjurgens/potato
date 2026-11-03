"""volume-unet on synthetic NIfTI volumes: a bright sphere to segment, its
mask painted as the volume widget stores it."""

import json
import os

import pytest

from potato.training import registry
from potato.training.dataset import build_bundle
from potato.training.evaluation import HEADLINE, score_split
from potato.training.events import EXIT_OK
from tests.unit.test_training_trainers import _context, _predictions, _run, _spec

HAVE = __import__("importlib").util.find_spec
needs = pytest.mark.skipif(not all(HAVE(m) for m in ("numpy", "nibabel")),
                           reason="numpy/nibabel absent")
needs_torch = pytest.mark.skipif(not all(HAVE(m) for m in ("torch", "numpy", "nibabel")),
                                 reason="torch/numpy/nibabel absent")

SCHEME = {"annotation_type": "volume_annotation", "name": "seg", "description": "",
          "labels": [{"name": "Lesion"}]}


def sphere_volume(path, size=24, centre=(12, 12, 12), radius=5, seed=0):
    """A noisy volume with one bright sphere; returns the stored answer."""
    import nibabel as nib
    import numpy
    from potato.media.volume_masks import masks_from_volume
    rng = numpy.random.default_rng(seed)
    grid = numpy.indices((size, size, size))
    inside = sum((g - c) ** 2 for g, c in zip(grid, centre)) <= radius ** 2
    data = rng.normal(100, 10, (size, size, size)).astype("float32")
    data[inside] += 400
    os.makedirs(os.path.dirname(path), exist_ok=True)
    nib.save(nib.Nifti1Image(data, numpy.eye(4)), str(path))
    return {"volume": os.path.basename(str(path)), "shape": [size, size, size],
            "labels": ["Lesion"], "masks": {"Lesion": masks_from_volume(inside)}, "shapes": []}


def volume_project(tmp, n=6, size=24):
    items, annotations = {}, []
    for i in range(n):
        iid = "v%d" % i
        rel = "media/vol%d.nii.gz" % i
        answer = sphere_volume(tmp / rel, size=size, centre=(8 + i % 3 * 3, 12, 10 + i % 2 * 4),
                               seed=i)
        items[iid] = {"id": iid, "volume": rel}
        annotations.append({"instance_id": iid, "user_id": "a",
                            "labels": {"seg": {"_data": json.dumps(answer)}}})
    return _context(tmp, [SCHEME], items, annotations)


@needs
def test_volume_rows_carry_the_painted_masks(tmp_path):
    config, context = volume_project(tmp_path, n=3)
    bundle, stats, _ = build_bundle(context, str(tmp_path / "b"), ["seg"],
                                    split_spec={"train": 1.0})
    assert bundle.manifest["schemas"][0]["kind"] == "volume"
    assert bundle.manifest["modality"] == "volume" and not stats.warnings
    row = next(bundle.read_split("train"))
    assert row["targets"]["seg"]["shape"] == [24, 24, 24]
    assert set(row["targets"]["seg"]["masks"]) == {"Lesion"}
    assert os.path.exists(os.path.join(bundle.root, "media", row["media"]))
    assert bundle.manifest["labels"]["seg"] == ["Lesion"]
    assert [t.name for t in registry.trainers_for_schema(SCHEME, "volume")] == ["volume-unet"]


def test_a_box_only_answer_is_no_segmentation_target():
    from potato.training.dataset import _volume_target
    boxes = {"_data": json.dumps({"shape": [4, 4, 4], "labels": ["L"], "masks": {},
                                  "shapes": [{"type": "box", "label": "L"}]})}
    assert _volume_target(boxes) is None
    zeros = {"_data": json.dumps({"shape": [4, 4, 4], "labels": ["L"],
                                  "masks": {"L": {"0": [16]}}})}
    assert _volume_target(zeros) is None


@needs
def test_volumes_are_scored_by_dice_per_label():
    import numpy
    from potato.media.volume_masks import masks_from_volume
    truth = numpy.zeros((8, 8, 8), bool)
    truth[2:6, 2:6, 2:6] = True
    half = truth.copy()
    half[2:4] = False
    gold = {"shape": [8, 8, 8], "masks": {"L": masks_from_volume(truth)}}
    rows = [{"instance_id": "a", "targets": {"s": gold}}]
    exact, _ = score_split(rows, {("a", "s"): {"masks": {"L": masks_from_volume(truth)}}},
                           "s", "volume")
    assert exact[HEADLINE["volume"]] == 1.0
    partial, _ = score_split(rows, {("a", "s"): {"masks": {"L": masks_from_volume(half)}}},
                             "s", "volume")
    assert partial["mean_dice"] == pytest.approx(2 * 32 / (64 + 32))
    missed, _ = score_split(rows, {}, "s", "volume")
    assert missed["mean_dice"] == 0.0


def test_volume_prelabels_keep_only_slices_that_fit_the_volume():
    from potato.server_utils.prelabel_values import prelabel_values
    payload = {"shape": [4, 4, 3], "masks": {
        "Lesion": {"0": [16], "1": [5, 2, 9], "2": [1, 2], "9": [16]},
        "Other": {"0": [16]}}}
    (value,) = prelabel_values(SCHEME, payload).values()
    stored = json.loads(value)
    # Slice 2's runs cover 3 of 16 voxels, slice 9 is past the end, and
    # Other is no label of the scheme.
    assert stored["masks"] == {"Lesion": {"0": [16], "1": [5, 2, 9]}}
    assert stored["prefilled_from"] == "model" and stored["shape"] == [4, 4, 3]
    assert prelabel_values(SCHEME, {"shape": [0, 4, 4], "masks": {}}) is None


@needs_torch
def test_the_unet_learns_the_sphere_and_paints_it_back(tmp_path):
    config, context = volume_project(tmp_path, n=10)
    # Seed 0 puts 6 volumes in train, 1 in val and 3 in test.
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["seg"], split_seed=0)
    spec = _spec(tmp_path, config, bundle, "volume-unet", "seg",
                 {"epochs": 20, "patches_per_epoch": 32, "batch_size": 4, "patch": 16,
                  "levels": 2, "base_channels": 8, "learning_rate": 3e-3,
                  "warmup_ratio": 0.0, "min_instances": 2, "patience": 20})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    metrics = result["metrics"]
    assert metrics["heldout_metric"].endswith("mean_dice")
    assert metrics["heldout_score"] > 0.8, metrics
    record = next(r for r in _predictions(spec) if r["payload"]["masks"])
    payload = record["payload"]
    assert payload["shape"] == [24, 24, 24] and payload["prefilled_from"] == "model"
    assert set(payload["masks"]) == {"Lesion"}


@needs
def test_a_label_painted_where_nobody_did_scores_zero_and_ghost_labels_are_not_targets():
    """Audit 105 B1/B2: scored on the annotated labels alone, painting an
    extra label cost nothing; a mask under a label the scheme no longer has
    was scored as a sure miss."""
    import numpy
    from potato.media.volume_masks import masks_from_volume
    from potato.training.dataset import _volume_target
    block = numpy.zeros((8, 8, 8), bool)
    block[2:6, 2:6, 2:6] = True
    gold = {"shape": [8, 8, 8], "masks": {"A": masks_from_volume(block)}}
    rows = [{"instance_id": "a", "targets": {"s": gold}}]
    extra = {"masks": {"A": masks_from_volume(block), "B": masks_from_volume(block),
                       "A2": {"x": [512]}}}
    metrics, _ = score_split(rows, {("a", "s"): extra}, "s", "volume")
    assert metrics["dice_A"] == 1.0 and metrics["dice_B"] == 0.0
    # A2's one slice key does not decode: empty on both sides, not scored.
    assert metrics["mean_dice"] == pytest.approx(0.5)
    stored = {"_data": json.dumps({"shape": [8, 8, 8], "masks": {
        "A": masks_from_volume(block), "Ghost": masks_from_volume(block)}})}
    assert set(_volume_target(stored, ["A"])["masks"]) == {"A"}
