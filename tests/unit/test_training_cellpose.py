"""The Cellpose trainer, against a stand-in ``cellpose`` package.

Cellpose is not installed on any machine this was built on, so these tests
check what Potato owns: outlines become an instance label image, only the
arguments the installed Cellpose accepts are passed (version 3 takes
``model_type`` and ``channels``, version 4 neither), and predicted masks
come back as the image widget's polygons with a confidence. The stand-in
"predicts" the masks it was trained on, so the held-out score is exact.
"""

import importlib.machinery
import json
import os
import sys
import types

import numpy
import pytest

from potato.training import registry
from potato.training.dataset import build_bundle
from potato.training.events import EXIT_OK
from potato.training.trainers.cellpose_trainer import instance_labels
from tests.unit.test_training_detection_audio_dpo import _context, _predictions, _run, _spec

pytest.importorskip("PIL")


def cells(directory, n, size=64):
    """Images with two bright discs, and the discs as polygons."""
    from PIL import Image, ImageDraw
    os.makedirs(directory, exist_ok=True)
    out = []
    for i in range(n):
        img = Image.new("RGB", (size, size), (10, 10, 10))
        draw = ImageDraw.Draw(img)
        objects = []
        for cx, cy in ((16 + i % 5, 20), (44, 40 - i % 7)):
            draw.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(240, 240, 240))
            ring = [(cx + 8 * numpy.cos(a), cy + 8 * numpy.sin(a))
                    for a in numpy.linspace(0, 2 * numpy.pi, 16, endpoint=False)]
            objects.append({"type": "polygon", "label": "nucleus",
                            "coordinates": [{"x": x / size, "y": y / size} for x, y in ring]})
        path = os.path.join(directory, "cell%02d.png" % i)
        img.save(path)
        out.append((path, objects))
    return out


def fake_cellpose(version, calls):
    """A ``cellpose`` package with Cellpose 3's or 4's signatures."""
    package = types.ModuleType("cellpose")
    package.__spec__ = importlib.machinery.ModuleSpec("cellpose", None)
    models = types.ModuleType("cellpose.models")
    train = types.ModuleType("cellpose.train")

    class Net:
        pass

    def segment(x):
        # Threshold the bright discs into instances, as a trained model would.
        from scipy import ndimage
        gray = numpy.asarray(x).mean(axis=2)
        labelled, _ = ndimage.label(gray > 128)
        return labelled.astype("uint16")

    if version == 3:
        class CellposeModel:
            def __init__(self, gpu=False, pretrained_model=None, model_type=None, device=None):
                calls.append(("model", {"gpu": gpu, "pretrained_model": pretrained_model,
                                        "model_type": model_type}))
                self.net = Net()

            def eval(self, x, channels=None, diameter=None, normalize=True):
                calls.append(("eval", {"channels": channels}))
                masks = segment(x)
                cellprob = numpy.where(masks > 0, 4.0, -4.0)
                return masks, [None, None, cellprob], None

        def train_seg(net, train_data=None, train_labels=None, test_data=None,
                      test_labels=None, channels=None, normalize=True, n_epochs=1,
                      learning_rate=0.1, weight_decay=0.0, batch_size=8,
                      min_train_masks=5, save_path=None, model_name=None):
            calls.append(("train", {"channels": channels, "n": len(train_data),
                                    "labels": train_labels, "epochs": n_epochs}))
            path = os.path.join(save_path, "models", model_name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write("weights")
            return path, [0.9, 0.5], [0.8]
    else:
        class CellposeModel:
            def __init__(self, gpu=False, pretrained_model="cpsam", device=None):
                calls.append(("model", {"gpu": gpu, "pretrained_model": pretrained_model}))
                self.net = Net()

            def eval(self, x, diameter=None, normalize=True):
                calls.append(("eval", {}))
                return segment(x), [None, None, None], None

        def train_seg(net, train_data=None, train_labels=None, test_data=None,
                      test_labels=None, normalize=True, n_epochs=1,
                      learning_rate=0.1, weight_decay=0.0, batch_size=8,
                      min_train_masks=5, save_path=None, model_name=None):
            calls.append(("train", {"n": len(train_data), "labels": train_labels}))
            path = os.path.join(save_path, "models", model_name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").close()
            return path, [0.4]

    models.CellposeModel = CellposeModel
    train.train_seg = train_seg
    package.models, package.train = models, train
    return {"cellpose": package, "cellpose.models": models, "cellpose.train": train}


def cell_project(tmp, n=12):
    images = cells(str(tmp / "img"), n)
    items, annotations = {}, []
    for i, (path, objects) in enumerate(images):
        iid = "c%02d" % i
        items[iid] = {"id": iid, "image": os.path.relpath(path, tmp)}
        annotations.append({"instance_id": iid, "user_id": "a", "labels": {},
                            "image_annotations": {"nuclei": objects}})
    scheme = {"annotation_type": "image_annotation", "name": "nuclei",
              "description": "", "labels": ["nucleus"], "tools": ["polygon"]}
    config, context = _context(tmp, [scheme], items, annotations)
    config["item_properties"]["text_key"] = "image"
    return config, context


def test_outlines_become_one_id_per_cell():
    square = {"type": "polygon", "label": "c", "coordinates": [
        {"x": 0.1, "y": 0.1}, {"x": 0.4, "y": 0.1}, {"x": 0.4, "y": 0.4}, {"x": 0.1, "y": 0.4}]}
    box = {"type": "bbox", "label": "c", "coordinates": {"x": 0.6, "y": 0.6, "width": 0.2,
                                                       "height": 0.2}}
    other = dict(square, coordinates=[{"x": p["x"] + 0.5, "y": p["y"]}
                                      for p in square["coordinates"]])
    labels, n = instance_labels([square, box, other], 20, 20)
    assert n == 2 and labels.dtype == numpy.uint16
    assert set(numpy.unique(labels)) == {0, 1, 2}
    assert labels[5, 5] == 1 and labels[5, 15] == 2 and labels[15, 15] == 0


def test_offered_for_microscopy_and_images_only():
    for kind in ("image_annotation", "microscopy"):
        assert "cellpose" in [t.name for t in registry.trainers_for_schema(
            {"annotation_type": kind}, "image")]
    assert "cellpose" not in [t.name for t in registry.trainers_for_schema(
        {"annotation_type": "geo_annotation"}, "image")]


@pytest.mark.parametrize("version", [3, 4])
def test_fit_predict_and_score(tmp_path, monkeypatch, version):
    pytest.importorskip("scipy")
    calls = []
    for name, module in fake_cellpose(version, calls).items():
        monkeypatch.setitem(sys.modules, name, module)
    config, context = cell_project(tmp_path)
    bundle, _, _ = build_bundle(context, str(tmp_path / "b"), ["nuclei"], split_seed=2)
    spec = _spec(tmp_path, config, bundle, "cellpose", "nuclei",
                 {"epochs": 2, "min_instances": 2})
    code, result, report = _run(spec)
    assert code == EXIT_OK, report.of_type("error")
    trained = dict(calls)["train"]
    assert trained["n"] == bundle.split_size("train")
    assert all(m.max() == 2 for m in trained["labels"])
    if version == 3:
        built = [c for name, c in calls if name == "model"]
        # Fitting starts from the named model; predicting loads the saved one.
        assert built[0]["model_type"] == "cyto3"
        assert built[-1]["model_type"] is None and os.path.isfile(built[-1]["pretrained_model"])
        assert trained["channels"] == [0, 0]
    else:
        assert "channels" not in trained
    records = _predictions(spec)
    assert records
    shape = records[0]["payload"][0]
    assert shape["type"] == "polygon" and shape["label"] == "nucleus"
    assert shape["source"] == "ai" and 0 < shape["confidence"] <= 1
    # Version 3 reports a cell probability; version 4's stand-in does not.
    if version == 3:
        assert shape["confidence"] == pytest.approx(1 / (1 + numpy.exp(-4.0)), abs=1e-3)
    metrics = result["metrics"]
    assert metrics["heldout_metric"].endswith("map_50")
    assert metrics["heldout_score"] > 0.9
