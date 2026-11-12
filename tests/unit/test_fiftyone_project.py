"""
The FiftyOne backend's Potato side: writing the project, reading the saved
answers back, merging them, and the agreement report. None of it needs
FiftyOne; test_fiftyone_backend.py covers the FiftyOne side where it is
installed.

Saved answers are written here in the shape a live browser save produces
(see the label conventions in importers/projects/writer.py).
"""

import json
import os

import pytest
import yaml

from potato.integrations import fiftyone_project as fp
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory


@pytest.fixture
def workdir():
    path = create_test_directory("fiftyone_project")
    yield path
    cleanup_test_directory(path)


def _image(path):
    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n")  # contents are never read
    return path


def _box(label, x, y=0.3, w=0.2, h=0.2):
    return {"type": "bbox", "label": label, "color": "",
            "coordinates": {"x": x, "y": y, "width": w, "height": h}}


def _save(project, user, answers):
    """answers: {iid: [(schema, name, value), ...]}"""
    folder = os.path.join(project, "annotation_output", user)
    os.makedirs(folder, exist_ok=True)
    state = {"user_id": user, "instance_id_to_label_to_value": {
        iid: [[{"schema": s, "name": n}, v] for s, n, v in entries]
        for iid, entries in answers.items()}}
    with open(os.path.join(folder, "user_state.json"), "w") as handle:
        json.dump(state, handle)


def _project(workdir, schema, n=3, existing=None, **kwargs):
    images = [_image(os.path.join(workdir, f"img{i}.png")) for i in range(n)]
    samples = [{"id": f"s{i}", "filepath": p, "existing": (existing or {}).get(f"s{i}", {})}
               for i, p in enumerate(images)]
    project = os.path.join(workdir, "proj")
    fp.write_project(project, samples, schema, task_name="t", anno_key="r1", **kwargs)
    return project


class TestWriteProject:
    def test_one_scheme_per_field_with_the_right_tool(self):
        assert fp.build_scheme("animal", "classification", ["cat", "dog"])["annotation_type"] == "radio"
        assert fp.build_scheme("tags", "classifications", ["a"])["annotation_type"] == "multiselect"
        boxes = fp.build_scheme("gt", "detections", ["car"])
        assert (boxes["annotation_type"], boxes["tools"], boxes["source_field"]) == (
            "image_annotation", ["bbox"], "image_url")
        assert fp.build_scheme("roads", "polylines", ["lane"])["tools"] == ["polyline"]
        assert fp.build_scheme("areas", "polygons", ["lot"])["tools"] == ["polygon"]

    def test_unsupported_types_and_missing_classes_are_refused(self):
        with pytest.raises(ValueError, match="scalar"):
            fp.build_scheme("score", "scalar", ["a"])
        with pytest.raises(ValueError, match="frame fields of type detections only"):
            fp.build_scheme("frames.cls", "classification", ["a"], {"frame_field": True})
        with pytest.raises(ValueError, match="no classes"):
            fp.build_scheme("gt", "detections", [])

    def test_the_project_runs_with_copied_media_and_pre_annotations(self, workdir):
        project = _project(workdir, {"gt": {"type": "detections", "classes": ["car"]}},
                           existing={"s0": {"gt": [_box("car", 0.1)]}},
                           annotations_per_item=3)
        config = yaml.safe_load(open(os.path.join(project, "config.yaml")))
        assert config["max_annotations_per_item"] == 3
        assert config["pre_annotation"]["enabled"] is True
        assert "instance_display" not in config  # the image scheme shows the image
        assert sorted(os.listdir(os.path.join(project, "media"))) == ["s0.png", "s1.png", "s2.png"]
        rows = [json.loads(line) for line in open(os.path.join(project, "data", "samples.jsonl"))]
        assert rows[0]["image_url"] == "/media/s0.png"
        assert rows[0]["predictions"]["gt"] == [_box("car", 0.1)]
        assert "predictions" not in rows[1]
        assert json.load(open(os.path.join(project, fp.MANIFEST)))["sample_ids"] == ["s0", "s1", "s2"]

    def test_a_classification_project_shows_the_image(self, workdir):
        project = _project(workdir, {"animal": {"type": "classification", "classes": ["cat", "dog"]}})
        config = yaml.safe_load(open(os.path.join(project, "config.yaml")))
        assert config["instance_display"]["fields"] == [
            {"key": "image_url", "type": "image", "label": "Image"}]

    def test_reference_mode_serves_images_in_place(self, workdir):
        project = _project(workdir, {"gt": {"type": "detections", "classes": ["car"]}},
                           media="reference")
        config = yaml.safe_load(open(os.path.join(project, "config.yaml")))
        assert config["media_directory"] == os.path.abspath(workdir)
        assert os.listdir(os.path.join(project, "media")) == []
        row = json.loads(open(os.path.join(project, "data", "samples.jsonl")).readline())
        assert row["image_url"] == "/media/img0.png"

    def test_reference_mode_will_not_serve_the_filesystem_root(self):
        with pytest.raises(ValueError, match="would serve everything"):
            fp._common_root(["/a.png", "/usr/b.png"])


class TestReadAndMerge:
    def test_every_kind_of_saved_answer_reads_back(self, workdir):
        project = _project(workdir, {
            "animal": {"type": "classification", "classes": ["cat", "dog"]},
            "tags": {"type": "classifications", "classes": ["indoor", "night"]},
            "gt": {"type": "detections", "classes": ["car"]}})
        _save(project, "ann", {"s0": [
            ("animal", "dog", "dog"),
            ("tags", "indoor", "indoor"), ("tags", "night", "night"),
            ("gt", "_data", json.dumps([_box("car", 0.4)])),
            ("unrelated", "x", "x")]})
        answers = fp.read_answers(project)
        assert answers["animal"] == {"s0": {"ann": "dog"}}
        assert answers["tags"] == {"s0": {"ann": ["indoor", "night"]}}
        assert answers["gt"] == {"s0": {"ann": [_box("car", 0.4)]}}

    def test_classification_takes_the_majority_and_ties_give_nothing(self):
        assert fp.merge_classification({"a": "cat", "b": "cat", "c": "dog"}) == "cat"
        assert fp.merge_classification({"a": "cat", "b": "dog"}) is None

    def test_multilabel_keeps_classes_more_than_half_chose(self):
        assert fp.merge_classifications(
            {"a": ["x", "y"], "b": ["x"], "c": ["x", "z"]}) == ["x"]
        assert fp.merge_classifications({"a": [], "b": []}) == []

    def test_disagreement_is_not_agreement_on_nothing(self):
        """Found by the potato-skill agent: two people choosing different
        things merged to [], which erased the sample's existing labels."""
        assert fp.merge_classifications({"a": ["x"], "b": ["y"]}) is None
        assert fp.merge_geometry({"a": [_box("car", 0.1)], "b": [_box("car", 0.7)]}) is None
        assert fp.merge_geometry({"a": [], "b": []}) == []

    def test_boxes_found_by_a_majority_merge_to_the_mean_box(self):
        merged = fp.merge_geometry({
            "a": [_box("car", 0.30), _box("person", 0.80, w=0.1)],
            "b": [_box("car", 0.32)],
            "c": [_box("truck", 0.34)]})
        assert len(merged) == 1  # the person only one of three drew is dropped
        assert merged[0]["label"] == "car"  # car, car, truck
        assert merged[0]["coordinates"]["x"] == pytest.approx(0.32)

    def test_a_polygon_merges_to_the_member_that_overlaps_the_others_most(self):
        def square(label, x0, size):
            pts = [(x0, 0.1), (x0 + size, 0.1), (x0 + size, 0.1 + size), (x0, 0.1 + size)]
            return {"type": "polygon", "label": label, "color": "",
                    "coordinates": [{"x": x, "y": y} for x, y in pts]}
        middle = square("lot", 0.20, 0.30)
        merged = fp.merge_geometry({"a": [square("lot", 0.16, 0.30)], "b": [middle],
                                    "c": [square("lot", 0.24, 0.30)]})
        assert merged == [middle]

    def test_an_adjudicated_decision_replaces_the_vote(self, workdir):
        project = _project(workdir, {
            "animal": {"type": "classification", "classes": ["cat", "dog"]},
            "gt": {"type": "detections", "classes": ["car"]}})
        _save(project, "a", {"s0": [("animal", "cat", "cat")]})
        _save(project, "b", {"s0": [("animal", "dog", "dog")]})
        folder = os.path.join(project, "annotation_output", "adjudication")
        os.makedirs(folder)
        with open(os.path.join(folder, "decisions.json"), "w") as handle:
            json.dump({"decisions": [{"instance_id": "s0", "label_decisions": {
                "animal": {"dog": True},
                "gt": {"_data": json.dumps([_box("car", 0.5)])}}}]}, handle)
        fields = fp.collect(project)["fields"]
        assert fields["animal"]["ties"] == ["s0"]
        assert fields["animal"]["merged"] == {"s0": "dog"}
        assert fields["animal"]["adjudicated"] == ["s0"]
        assert fields["gt"]["merged"] == {"s0": [_box("car", 0.5)]}


class TestAgreement:
    def test_nominal_alpha_and_raw_agreement_match_a_hand_count(self):
        # Units (x,x) (x,y) (y,y) (y,y): D_o = 2/8, D_e = 2*3*5/(8*7) = 30/56,
        # alpha = 1 - (2/8)/(30/56) = 8/15. Three of four units agree.
        a, b = "xxyy", "xyyy"
        by_sample = {f"s{i}": {"a": a[i], "b": b[i]} for i in range(4)}
        report = fp.field_agreement("radio", by_sample)
        assert report["alpha"] == pytest.approx(8 / 15)
        assert report["percent_agreement"] == pytest.approx(0.75)
        assert report["annotators"] == ["a", "b"]

    def test_unanimous_answers_explain_the_missing_alpha(self):
        report = fp.field_agreement("radio", {"s0": {"a": "x", "b": "x"},
                                              "s1": {"a": "x", "b": "x"}})
        assert report["alpha"] is None
        assert "perfect agreement" in report["alpha_note"]

    def test_one_annotator_per_sample_says_so(self):
        report = fp.field_agreement("radio", {"s0": {"a": "x"}})
        assert "two or more annotators" in report["note"]

    def test_geometry_reports_detection_and_localization(self):
        report = fp.field_agreement("bbox", {
            "s0": {"a": [_box("car", 0.30)], "b": [_box("car", 0.31)]},
            "s1": {"a": [_box("car", 0.60)], "b": [_box("car", 0.61)]}})
        assert report["n_samples_with_two_or_more"] == 2
        assert report["localization"]["sigma"] > 0.5
        assert json.dumps(report)  # no NaN left in the report


SKELETON = {"names": ["head", "tail"], "edges": [[0, 1]]}


def _track(label, start, end, x=0.1, attrs=None):
    return {"id": f"t{start}", "label": label, "attributes": attrs or {},
            "keyframes": {str(f): {"frame": f, "time": f / 10,
                                   "bboxNorm": {"x": x, "y": 0.2, "width": 0.2, "height": 0.2}}
                          for f in (start, end)}}


class TestRoundTwoKinds:
    """Keypoints, masks, attributes and video tracks (D3)."""

    def test_schemes_for_each_new_kind(self):
        kp = fp.build_scheme("pose", "keypoints", ["fish"], {"skeleton": SKELETON})
        assert (kp["tools"], kp["skeletons"]) == (["keypoint_set"], {"pose": SKELETON})
        assert fp.build_scheme("pts", "keypoints", ["eye"])["tools"] == ["landmark"]
        mask = fp.build_scheme("seg", "segmentation", ["road", "sky"])
        assert mask["tools"] == ["brush", "eraser"] and [l["name"] for l in mask["labels"]] == ["road", "sky"]
        track = fp.build_scheme("frames.detections", "detections", ["car"],
                                {"frame_field": True, "fps": 25,
                                 "attributes": {"occluded": {"type": "checkbox"}}})
        assert (track["annotation_type"], track["mode"], track["name"], track["video_fps"]) == (
            "video_annotation", "tracking", "frames__detections", 25.0)
        assert track["attributes"] == [{"name": "occluded", "type": "bool"}]

    def test_attribute_types_map_and_unknown_ones_are_refused(self):
        assert fp.potato_attributes({
            "state": {"type": "select", "values": ["parked", "moving"], "default": "parked"},
            "note": {"type": "text"}}) == [
            {"name": "state", "type": "select", "options": ["parked", "moving"], "default": "parked"},
            {"name": "note", "type": "text"}]
        with pytest.raises(ValueError, match="occluded"):
            fp.potato_attributes({"o": {"type": "occluded"}})
        with pytest.raises(ValueError, match="no values"):
            fp.potato_attributes({"s": {"type": "select"}})

    def test_a_video_project_and_its_track_answers(self, workdir):
        project = _project(workdir, {"frames.detections": {
            "type": "detections", "classes": ["car"], "frame_field": True, "fps": 10}},
            media_type="video")
        config = yaml.safe_load(open(os.path.join(project, "config.yaml")))
        assert config["item_properties"]["text_key"] == "video_url"
        assert config["annotation_schemes"][0]["name"] == "frames__detections"
        tracks = [_track("car", 0, 10)]
        _save(project, "a", {"s0": [("frames__detections", "_data", json.dumps({"tracks": {"t0": tracks[0]}}))]})
        assert fp.read_answers(project)["frames.detections"] == {"s0": {"a": tracks}}

    def test_tracks_merge_by_majority_with_attributes(self):
        a = [_track("car", 0, 10, attrs={"occluded": True}), _track("car", 20, 30, x=0.6)]
        b = [_track("car", 0, 10, x=0.11, attrs={"occluded": True})]
        c = [_track("truck", 0, 10, x=0.12, attrs={"occluded": False})]
        merged = fp.merge_tracks({"a": a, "b": b, "c": c})
        # One track found by all three; the 20-30 track by one of three is dropped.
        assert len(merged) == 1
        assert merged[0]["label"] == "car" and merged[0]["attributes"] == {"occluded": True}
        assert fp.merge_tracks({"a": [_track("car", 0, 10)], "b": [_track("car", 50, 60)]}) is None
        assert fp.merge_tracks({"a": [], "b": []}) == []

    def test_track_agreement(self):
        report = fp.track_agreement({"s0": {"a": [_track("car", 0, 10)],
                                            "b": [_track("car", 0, 10), _track("car", 40, 50)]}})
        # 3 tracks drawn, 2 of them matched to each other, identical boxes.
        assert report["tracks_drawn"] == 3
        assert report["track_match_rate"] == pytest.approx(2 / 3)
        assert report["mean_track_similarity"] == pytest.approx(1.0)

    def test_box_attributes_merge_by_majority(self):
        def box(attrs):
            return {**_box("car", 0.1), "attributes": attrs}
        merged = fp.merge_geometry({"a": [box({"state": "parked"})], "b": [box({"state": "parked"})],
                                    "c": [box({"state": "moving"})]})
        assert merged[0]["attributes"] == {"state": "parked"}

    def test_keypoint_sets_and_masks_merge_and_score(self, workdir):
        project = _project(workdir, {
            "pose": {"type": "keypoints", "classes": ["fish"], "skeleton": SKELETON},
            "seg": {"type": "segmentation", "classes": ["road"], "mask_targets": {"1": "road"}}})
        pose = {"type": "keypoint_set", "label": "fish", "skeleton": "pose",
                "coordinates": [{"x": 0.2, "y": 0.2, "v": 2}, {"x": 0.4, "y": 0.3, "v": 2}]}
        mask = {"type": "mask", "label": "road", "rle": {"counts": [2, 3, 4], "size": [3, 3]}}
        for user in ("a", "b"):
            _save(project, user, {"s0": [("pose", "_data", json.dumps([pose])),
                                         ("seg", "_data", json.dumps([mask]))]})
        collected = fp.collect(project)
        assert collected["fields"]["pose"]["merged"]["s0"][0]["coordinates"] == pose["coordinates"]
        assert collected["fields"]["seg"]["merged"]["s0"][0]["rle"] == mask["rle"]
        manifest = json.load(open(os.path.join(project, fp.MANIFEST)))
        assert manifest["label_schema"]["pose"]["kind"] == "keypoint_set"
        assert manifest["label_schema"]["seg"]["kind"] == "mask"
