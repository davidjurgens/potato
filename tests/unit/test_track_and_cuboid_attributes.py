"""
Per-object attributes on video tracks and point-cloud objects, and agreement
over them.

The hand-computed case is B2's (tests/unit/test_object_attributes.py): three
matched objects with occlusion none/none, partial/heavy, heavy/heavy give
nominal alpha 12/22. Here the objects are tracks and cuboids, matched by
their own similarity.
"""

import json

import pytest

from potato.server_utils.iaa import attribute_agreement as aa
from potato.server_utils.schemas.object_attributes import normalize_attributes

LABELS = ["car", "person"]
OCCLUSION = normalize_attributes(
    [{"name": "occlusion", "type": "select", "options": ["none", "partial", "heavy"]}],
    LABELS, "annotation_schemes[objs]")


def track(start, end, x=0.1, label="car", **attributes):
    """A saved track with keyframes at start and end, normalized boxes at x."""
    box = {"x": x, "y": 0.1, "width": 0.2, "height": 0.2}
    keyframes = {str(f): {"frame": f, "bbox": {"x": 1, "y": 1, "width": 9, "height": 9},
                          "bboxNorm": dict(box)} for f in (start, end)}
    return {"id": f"t{start}", "label": label, "keyframes": keyframes, "attributes": attributes}


def stored_tracks(*tracks):
    """How a video_annotation answer is stored: a `_data` JSON string."""
    return {"_data": json.dumps({"segments": [], "tracks": {t["id"]: t for t in tracks}})}


def cuboid(cx, label="car", **attributes):
    return {"type": "cuboid_3d", "label": label, "attributes": attributes,
            "coordinates": {"center": [cx, 0, 0], "size": [4, 2, 1.5],
                            "rotation": [0, 0, 0, 1]}}


class TestTracks:
    def test_saved_tracks_parse_into_objects(self):
        objects = aa.track_objects(stored_tracks(track(0, 30, occlusion="none")))
        assert [o["attributes"] for o in objects] == [{"occlusion": "none"}]
        canonical = aa.track_canonical(objects[0])
        assert (canonical["start"], canonical["end"]) == (0, 30)

    def test_similarity_needs_time_and_place(self):
        a = aa.track_canonical(track(0, 30))
        assert aa.track_similarity(a, aa.track_canonical(track(0, 30))) == pytest.approx(1.0)
        assert aa.track_similarity(a, aa.track_canonical(track(40, 60))) == 0.0     # other frames
        assert aa.track_similarity(a, aa.track_canonical(track(0, 30, x=0.7))) == 0.0  # other place
        half = aa.track_similarity(a, aa.track_canonical(track(15, 45)))
        assert half == pytest.approx(16 / 46)                                       # temporal IoU

    def test_alpha_over_matched_tracks(self):
        rows = {
            "v1": {"a": stored_tracks(track(0, 30, occlusion="none")),
                   "b": stored_tracks(track(0, 30, occlusion="none"))},
            "v2": {"a": stored_tracks(track(0, 30, occlusion="partial")),
                   "b": stored_tracks(track(0, 30, occlusion="heavy"))},
            "v3": {"a": stored_tracks(track(0, 30, occlusion="heavy"),
                                      track(50, 80, x=0.6, occlusion="none")),
                   "b": stored_tracks(track(0, 30, occlusion="heavy"))},
        }
        from potato.server_utils.iaa.dispatcher import _object_attribute_report
        scheme = {"name": "objs", "annotation_type": "video_annotation", "mode": "tracking",
                  "labels": LABELS, "attributes": [{"name": "occlusion", "type": "select",
                                                    "options": ["none", "partial", "heavy"]}]}
        result = _object_attribute_report(scheme, rows)["occlusion"]
        assert result["alpha"] == pytest.approx(12 / 22, abs=1e-6)
        assert result["n_objects"] == 3   # the unmatched second track in v3 is not a unit

    @staticmethod
    def _unboxed(t):
        for kf in t["keyframes"].values():
            del kf["bboxNorm"]
        return t

    def test_tracks_without_normalized_boxes_are_never_matched(self):
        # A car and a person over the same frames: on time alone they would
        # score 1.0 and their attributes would be compared as one object.
        car = self._unboxed(track(0, 30, label="car"))
        person = track(0, 30, x=0.7, label="person")
        assert aa.track_similarity(aa.track_canonical(car), aa.track_canonical(person)) == 0.0
        assert aa.track_similarity(aa.track_canonical(car),
                                   aa.track_canonical(self._unboxed(track(0, 30)))) == 0.0

    def test_the_report_counts_tracks_it_could_not_compare(self):
        from potato.server_utils.iaa.dispatcher import _object_attribute_report
        scheme = {"name": "objs", "annotation_type": "video_annotation", "mode": "tracking",
                  "labels": LABELS, "attributes": [{"name": "occlusion", "type": "select",
                                                    "options": ["none", "partial", "heavy"]}]}
        rows = {"v1": {"a": stored_tracks(self._unboxed(track(0, 30, occlusion="none"))),
                       "b": stored_tracks(track(0, 30, occlusion="heavy"))}}
        result = _object_attribute_report(scheme, rows)["occlusion"]
        assert result["n_objects"] == 0
        assert result["n_tracks_without_normalized_boxes"] == 1
        boxed = {"v1": {"a": stored_tracks(track(0, 30)), "b": stored_tracks(track(0, 30))}}
        assert "n_tracks_without_normalized_boxes" not in _object_attribute_report(scheme, boxed)["occlusion"]


class TestCuboids:
    def test_alpha_over_matched_cuboids(self):
        rows = {
            "c1": {"a": json.dumps([cuboid(0, occlusion="none")]),
                   "b": json.dumps([cuboid(0.1, occlusion="none")])},
            "c2": {"a": json.dumps([cuboid(0, occlusion="partial")]),
                   "b": json.dumps([cuboid(0, occlusion="heavy")])},
            "c3": {"a": json.dumps([cuboid(0, occlusion="heavy"), cuboid(40, occlusion="none")]),
                   "b": json.dumps([cuboid(0, occlusion="heavy")])},
        }
        from potato.server_utils.iaa.dispatcher import _object_attribute_report
        scheme = {"name": "objs", "annotation_type": "spatial_annotation", "labels": LABELS,
                  "attributes": [{"name": "occlusion", "type": "select",
                                  "options": ["none", "partial", "heavy"]}]}
        result = _object_attribute_report(scheme, rows)["occlusion"]
        assert result["alpha"] == pytest.approx(12 / 22, abs=1e-6)
        assert result["n_objects"] == 3


class TestConfig:
    def _validate(self, scheme):
        from potato.server_utils.config_module import validate_single_annotation_scheme
        validate_single_annotation_scheme(scheme, "annotation_schemes[0]")

    ATTRS = [{"name": "occluded", "type": "bool"}]

    def test_tracking_video_and_point_clouds_take_attributes(self):
        self._validate({"annotation_type": "video_annotation", "name": "v", "description": "d",
                        "mode": "tracking", "labels": LABELS, "attributes": self.ATTRS})
        self._validate({"annotation_type": "spatial_annotation", "name": "p", "description": "d",
                        "labels": LABELS, "tools": ["cuboid_3d"], "attributes": self.ATTRS})

    def test_a_video_without_tracks_cannot_have_attributes(self):
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError, match="need mode 'tracking' or 'combined'"):
            self._validate({"annotation_type": "video_annotation", "name": "v", "description": "d",
                            "mode": "segment", "labels": LABELS, "attributes": self.ATTRS})

    def test_a_bad_definition_is_named(self):
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError, match="labels"):
            self._validate({"annotation_type": "spatial_annotation", "name": "p",
                            "description": "d", "labels": LABELS, "tools": ["cuboid_3d"],
                            "attributes": [{"name": "x", "type": "bool", "labels": ["boat"]}]})

    def test_the_generators_render_the_panel(self):
        from potato.server_utils.schemas.spatial_annotation import generate_spatial_annotation_layout
        from potato.server_utils.schemas.video_annotation import generate_video_annotation_layout
        video, _ = generate_video_annotation_layout({
            "annotation_type": "video_annotation", "name": "v", "description": "d",
            "mode": "tracking", "labels": LABELS, "attributes": self.ATTRS})
        cloud, _ = generate_spatial_annotation_layout({
            "annotation_type": "spatial_annotation", "name": "p", "description": "d",
            "labels": LABELS, "tools": ["cuboid_3d"], "attributes": self.ATTRS})
        for html in (video, cloud):
            assert 'class="object-attribute-panel"' in html and '"attributes": [{' in html

    def test_two_tracking_video_schemes_on_one_page_are_refused(self):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_annotation_schemes)

        def video(name, mode):
            return {"annotation_type": "video_annotation", "name": name, "description": "d",
                    "mode": mode, "labels": LABELS}
        with pytest.raises(ConfigValidationError, match="second video_annotation scheme"):
            validate_annotation_schemes({"annotation_schemes": [video("a", "tracking"),
                                                                video("b", "combined")]})
        validate_annotation_schemes({"annotation_schemes": [video("a", "tracking"),
                                                            video("b", "segment")]})
