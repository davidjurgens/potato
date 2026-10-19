"""
The FiftyOne annotation backend end to end, where FiftyOne is installed.

annotate() -> two annotators' saves (written in the browser's on-disk shape)
-> load_annotations(), against a real FiftyOne dataset.
"""

import json
import os

import pytest

fo = pytest.importorskip("fiftyone")

from tests.helpers.test_utils import cleanup_test_directory, create_test_directory  # noqa: E402

DATASET = "potato_backend_test"


@pytest.fixture
def run():
    from PIL import Image

    workdir = create_test_directory("fiftyone_backend")
    paths = []
    for i in range(3):
        path = os.path.join(workdir, f"im{i}.png")
        Image.new("RGB", (64, 48), (i * 60, 90, 40)).save(path)
        paths.append(path)
    if fo.dataset_exists(DATASET):
        fo.delete_dataset(DATASET)
    dataset = fo.Dataset(DATASET)
    dataset.add_samples([fo.Sample(filepath=p) for p in paths])
    fo.annotation_config.backends["potato"] = {
        "config_cls": "potato.integrations.fiftyone_backend.PotatoBackendConfig"}
    yield dataset, workdir
    fo.delete_dataset(DATASET)
    cleanup_test_directory(workdir)


def _box(label, x):
    return {"type": "bbox", "label": label, "color": "",
            "coordinates": {"x": x, "y": 0.3, "width": 0.2, "height": 0.2}}


def _save(project, user, answers):
    folder = os.path.join(project, "annotation_output", user)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "user_state.json"), "w") as handle:
        json.dump({"user_id": user, "instance_id_to_label_to_value": {
            iid: [[{"schema": s, "name": n}, v] for s, n, v in entries]
            for iid, entries in answers.items()}}, handle)


def test_detections_round_trip_with_agreement_and_annotator_fields(run):
    dataset, workdir = run
    first = dataset.first()
    first["gt"] = fo.Detections(detections=[fo.Detection(label="car", bounding_box=[0.1, 0.1, 0.2, 0.2])])
    first.save()
    original_id = first["gt"].detections[0].id
    project = os.path.join(workdir, "proj")

    dataset.annotate("r1", backend="potato", label_field="gt", label_type="detections",
                     classes=["car", "person"], project_dir=project, annotator_fields=True)

    row = json.loads(open(os.path.join(project, "data", "samples.jsonl")).readline())
    assert row["predictions"]["gt"][0]["coordinates"]["x"] == pytest.approx(0.1)

    ids = dataset.values("id")
    for user, x in (("ann_a", 0.30), ("ann_b", 0.32)):
        _save(project, user, {
            ids[1]: [("gt", "_data", json.dumps([_box("person", x)]))],
            ids[2]: [("gt", "_data", json.dumps([_box("car", 0.5)] if user == "ann_a" else []))]})

    dataset.load_annotations("r1")
    samples = list(dataset)
    # Nobody opened the first sample: its label comes back untouched, same id.
    assert [d.id for d in samples[0]["gt"].detections] == [original_id]
    merged = samples[1]["gt"].detections
    assert [d.label for d in merged] == ["person"]
    assert merged[0].bounding_box[0] == pytest.approx(0.31)
    # Only one of two annotators drew the car on the third sample.
    assert samples[2]["gt"] is None or samples[2]["gt"].detections == []
    assert samples[1]["gt_ann_a"].detections[0].bounding_box[0] == pytest.approx(0.30)
    assert samples[2]["gt_ann_b"] is None

    report = dataset.info["potato_agreement"]["r1"]["gt"]
    assert report["annotators"] == ["ann_a", "ann_b"]
    assert report["n_samples_with_two_or_more"] == 2
    assert report["detection"]["n_clusters"] == 2


def test_boxes_every_annotator_deleted_are_removed(run):
    """An empty answer is an answer: both people removed the pre-filled box."""
    dataset, workdir = run
    first = dataset.first()
    first["gt"] = fo.Detections(detections=[fo.Detection(label="car", bounding_box=[0.1, 0.1, 0.2, 0.2])])
    first.save()
    project = os.path.join(workdir, "proj")
    dataset.annotate("r4", backend="potato", label_field="gt", label_type="detections",
                     classes=["car"], project_dir=project)
    for user in ("a", "b"):
        _save(project, user, {first.id: [("gt", "_data", "[]")]})
    dataset.load_annotations("r4")
    gt = dataset.first()["gt"]
    assert gt is None or gt.detections == []


def test_disagreeing_annotators_keep_the_pre_annotation(run):
    """Each person drew a box in a different place: no majority, so the
    sample keeps its existing label rather than losing it."""
    dataset, workdir = run
    first = dataset.first()
    first["gt"] = fo.Detections(detections=[fo.Detection(label="car", bounding_box=[0.1, 0.1, 0.2, 0.2])])
    first.save()
    original_id = first["gt"].detections[0].id
    project = os.path.join(workdir, "proj")
    dataset.annotate("r5", backend="potato", label_field="gt", label_type="detections",
                     classes=["car"], project_dir=project)
    _save(project, "a", {first.id: [("gt", "_data", json.dumps([_box("car", 0.05)]))]})
    _save(project, "b", {first.id: [("gt", "_data", json.dumps([_box("car", 0.70)]))]})
    dataset.load_annotations("r5")
    assert [d.id for d in dataset.first()["gt"].detections] == [original_id]
    assert dataset.info["potato_agreement"]["r5"]["gt"]["n_ties"] == 1


def test_a_classification_tie_keeps_the_existing_label(run):
    dataset, workdir = run
    for sample, label in zip(dataset, ["cat", "cat", "dog"]):
        sample["animal"] = fo.Classification(label=label)
        sample.save()
    project = os.path.join(workdir, "proj")
    dataset.annotate("r2", backend="potato", label_field="animal",
                     label_type="classification", classes=["cat", "dog"],
                     project_dir=project)
    ids = dataset.values("id")
    _save(project, "a", {ids[0]: [("animal", "dog", "dog")], ids[1]: [("animal", "dog", "dog")]})
    _save(project, "b", {ids[0]: [("animal", "dog", "dog")], ids[1]: [("animal", "cat", "cat")]})

    dataset.load_annotations("r2")
    assert dataset.values("animal.label") == ["dog", "cat", "dog"]
    report = dataset.info["potato_agreement"]["r2"]["animal"]
    assert report["n_ties"] == 1
    assert report["percent_agreement"] == pytest.approx(0.5)


def test_unsupported_label_types_are_refused(run):
    dataset, workdir = run
    with pytest.raises(ValueError):
        dataset.annotate("r3", backend="potato", label_field="kp", label_type="keypoints",
                         classes=["nose"], project_dir=os.path.join(workdir, "p3"))
