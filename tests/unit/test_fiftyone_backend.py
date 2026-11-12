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


def test_box_attributes_go_out_and_come_back(run):
    dataset, workdir = run
    first = dataset.first()
    first["gt"] = fo.Detections(detections=[
        fo.Detection(label="car", bounding_box=[0.1, 0.3, 0.2, 0.2], state="parked")])
    first.save()
    project = os.path.join(workdir, "proj")
    dataset.annotate("ra", backend="potato", label_field="gt", label_type="detections",
                     classes=["car"], project_dir=project,
                     attributes={"state": {"type": "select", "values": ["parked", "moving"]}})
    config = json.load(open(os.path.join(project, "fiftyone_run.json")))
    assert config["label_schema"]["gt"]["attributes"]["state"]["values"] == ["parked", "moving"]
    row = json.loads(open(os.path.join(project, "data", "samples.jsonl")).readline())
    assert row["predictions"]["gt"][0]["attributes"] == {"state": "parked"}
    box = {**_box("car", 0.1), "attributes": {"state": "moving"}}
    for user in ("a", "b"):
        _save(project, user, {first.id: [("gt", "_data", json.dumps([box]))]})
    dataset.load_annotations("ra")
    assert dataset.first()["gt"].detections[0]["state"] == "moving"


def test_keypoints_with_a_skeleton_keep_order_and_missing_points(run):
    import math
    dataset, workdir = run
    dataset.skeletons = {"pose": fo.KeypointSkeleton(labels=["head", "fin", "tail"],
                                                     edges=[[0, 1], [1, 2]])}
    first = dataset.first()
    first["pose"] = fo.Keypoints(keypoints=[
        fo.Keypoint(label="fish", points=[(0.2, 0.2), (float("nan"), float("nan")), (0.6, 0.4)])])
    first.save()
    project = os.path.join(workdir, "proj")
    dataset.annotate("rk", backend="potato", label_field="pose", label_type="keypoints",
                     classes=["fish"], project_dir=project)
    row = json.loads(open(os.path.join(project, "data", "samples.jsonl")).readline())
    [kp] = row["predictions"]["pose"]
    assert (kp["type"], kp["skeleton"]) == ("keypoint_set", "pose")
    assert [p["v"] for p in kp["coordinates"]] == [2, 0, 2]
    scheme = __import__("yaml").safe_load(open(os.path.join(project, "config.yaml")))["annotation_schemes"][0]
    assert scheme["skeletons"]["pose"]["names"] == ["head", "fin", "tail"]
    moved = {**kp, "coordinates": [{"x": 0.25, "y": 0.2, "v": 2}, {"x": 0.4, "y": 0.3, "v": 2},
                                   {"x": 0.6, "y": 0.4, "v": 0}]}
    for user in ("a", "b"):
        _save(project, user, {first.id: [("pose", "_data", json.dumps([moved]))]})
    dataset.load_annotations("rk")
    points = dataset.first()["pose"].keypoints[0].points
    assert points[0] == pytest.approx((0.25, 0.2)) and points[1] == pytest.approx((0.4, 0.3))
    assert math.isnan(points[2][0])


def test_keypoints_without_a_skeleton_are_landmarks(run):
    dataset, workdir = run
    project = os.path.join(workdir, "proj")
    dataset.annotate("rl", backend="potato", label_field="eyes", label_type="keypoints",
                     classes=["eye"], project_dir=project)
    scheme = __import__("yaml").safe_load(open(os.path.join(project, "config.yaml")))["annotation_schemes"][0]
    assert scheme["tools"] == ["landmark"]
    first = dataset.first()
    mark = {"type": "landmark", "label": "eye", "color": "", "coordinates": {"x": 0.3, "y": 0.4}}
    for user in ("a", "b"):
        _save(project, user, {first.id: [("eyes", "_data", json.dumps([mark]))]})
    dataset.load_annotations("rl")
    [point] = dataset.first()["eyes"].keypoints
    assert point.label == "eye" and point.points[0] == pytest.approx((0.3, 0.4))


def test_segmentation_masks_round_trip_per_class(run):
    import numpy as np
    dataset, workdir = run
    dataset.mask_targets = {"seg": {1: "road", 2: "sky"}}
    dataset.save()
    first = dataset.first()
    mask = np.zeros((48, 64), dtype=np.uint8)
    mask[30:, :] = 1
    mask[:10, :] = 2
    first["seg"] = fo.Segmentation(mask=mask)
    first.save()
    project = os.path.join(workdir, "proj")
    dataset.annotate("rs", backend="potato", label_field="seg", label_type="segmentation",
                     project_dir=project)
    row = json.loads(open(os.path.join(project, "data", "samples.jsonl")).readline())
    by_class = {m["label"]: m for m in row["predictions"]["seg"]}
    assert sorted(by_class) == ["road", "sky"] and by_class["road"]["rle"]["size"] == [48, 64]
    # The road starts at row 30: 30 * 64 zeros, then 18 * 64 ones.
    assert by_class["road"]["rle"]["counts"] == [30 * 64, 18 * 64]
    for user in ("a", "b"):
        _save(project, user, {first.id: [("seg", "_data", json.dumps(row["predictions"]["seg"]))]})
    dataset.load_annotations("rs")
    assert np.array_equal(dataset.first()["seg"].mask, mask)


def _video(path, frames=20, fps=10):
    import cv2
    import numpy as np
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 48))
    for i in range(frames):
        writer.write(np.full((48, 64, 3), i * 10 % 255, dtype=np.uint8))
    writer.release()
    return path


def test_video_tracks_become_frame_detections(run):
    _dataset, workdir = run
    name = DATASET + "_video"
    if fo.dataset_exists(name):
        fo.delete_dataset(name)
    video = fo.Dataset(name)
    try:
        video.add_sample(fo.Sample(filepath=_video(os.path.join(workdir, "clip.mp4"))))
        project = os.path.join(workdir, "vproj")
        video.annotate("rv", backend="potato", label_field="frames.cars", label_type="detections",
                       classes=["car"], project_dir=project,
                       attributes={"occluded": {"type": "checkbox"}})
        config = __import__("yaml").safe_load(open(os.path.join(project, "config.yaml")))
        scheme = config["annotation_schemes"][0]
        assert (scheme["annotation_type"], scheme["name"], scheme["video_fps"]) == (
            "video_annotation", "frames__cars", 10.0)
        track = {"id": "t1", "label": "car", "attributes": {"occluded": True},
                 "keyframes": {"2": {"frame": 2, "time": 0.2,
                                     "bboxNorm": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}},
                               "6": {"frame": 6, "time": 0.6,
                                     "bboxNorm": {"x": 0.5, "y": 0.1, "width": 0.2, "height": 0.2}}}}
        sid = video.first().id
        for user in ("a", "b"):
            _save(project, user, {sid: [("frames__cars", "_data",
                                         json.dumps({"tracks": {"t1": track}}))]})
        video.load_annotations("rv")
        frames = video.first().frames
        boxed = {n: frames[n]["cars"].detections[0] for n in range(1, 21)
                 if frames[n]["cars"] is not None and frames[n]["cars"].detections}
        # Keyframes 2 and 6 (0-based) are FiftyOne frames 3 and 7; 3 to 7 inclusive.
        assert sorted(boxed) == [3, 4, 5, 6, 7]
        assert boxed[5].bounding_box[0] == pytest.approx(0.3)   # halfway
        assert boxed[3].keyframe and not boxed[5].keyframe
        assert {d.index for d in boxed.values()} == {boxed[3].index}
        assert boxed[4]["occluded"] is True
        report = video.info["potato_agreement"]["rv"]["frames.cars"]
        assert report["track_match_rate"] == pytest.approx(1.0)
    finally:
        fo.delete_dataset(name)


def test_unsupported_label_types_are_refused(run):
    dataset, workdir = run
    with pytest.raises(ValueError):
        dataset.annotate("r3", backend="potato", label_field="score", label_type="scalar",
                         project_dir=os.path.join(workdir, "p3"))


def test_rgb_mask_targets_are_refused_by_name(run):
    dataset, workdir = run
    with pytest.raises(ValueError, match="does not support RGB targets"):
        dataset.annotate("rgb", backend="potato", label_field="seg", label_type="segmentation",
                         mask_targets={"#ff0000": "road", "#0000ff": "sky"},
                         project_dir=os.path.join(workdir, "prgb"))
    assert not os.path.exists(os.path.join(workdir, "prgb", "config.yaml"))
