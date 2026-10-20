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


# ---------------------------------------------------------------------------
# per_keyframe attributes (D4)
# ---------------------------------------------------------------------------

PER_KF = normalize_attributes(
    [{"name": "occlusion", "type": "select", "options": ["none", "partial", "heavy"],
      "per_keyframe": True}],
    LABELS, "annotation_schemes[objs]", keyframes=True)


def kf_track(start, end, x=0.1, initial="none", changes=None):
    """A track with keyframes at start, end and each frame in `changes`,
    where `changes` = {frame: occlusion from then on}."""
    t = track(start, end, x=x, occlusion=initial)
    for frame, value in (changes or {}).items():
        t["keyframes"][str(frame)] = {"frame": frame, "bboxNorm": {"x": x, "y": 0.1, "width": 0.2, "height": 0.2},
                                      "attributes": {"occlusion": value}}
    return t


class TestPerKeyframe:
    def test_config_needs_a_scheme_with_keyframes(self):
        from potato.server_utils.schemas.object_attributes import AttributeConfigError
        raw = [{"name": "o", "type": "bool", "per_keyframe": True}]
        assert normalize_attributes(raw, LABELS, "s", keyframes=True)[0]["per_keyframe"] is True
        with pytest.raises(AttributeConfigError, match="only video tracks and point-cloud sequences"):
            normalize_attributes(raw, LABELS, "s")
        with pytest.raises(AttributeConfigError, match="true or false"):
            normalize_attributes([{"name": "o", "type": "bool", "per_keyframe": "yes"}], LABELS, "s",
                                 keyframes=True)

    def test_values_hold_from_keyframe_to_keyframe(self):
        from potato.server_utils.track_attributes import attributes_at, steps, value_at
        t = kf_track(0, 30, changes={10: "partial", 20: None})
        assert attributes_at(t, 5) == {"occlusion": "none"}
        assert attributes_at(t, 10) == {"occlusion": "partial"}
        assert attributes_at(t, 19) == {"occlusion": "partial"}
        assert attributes_at(t, 25) == {"occlusion": None}
        s = steps(t)
        assert [f for f, _v in s] == [0, 10, 20]
        assert value_at(s, "occlusion", 15) == "partial"

    def test_alpha_is_over_object_frames(self):
        """Two annotators, one matched track. a: none, partial from 10.
        b: none, partial from 20. The units are the frames where either
        value changes: 0, 10 and 20, with values none/none, partial/none and
        partial/partial. Six values, three of each. Nominal alpha:
        Do = (1/6) * 2 = 1/3 (one disagreeing unit, two ordered pairs);
        De = (2 * 3 * 3) / (6 * 5) = 3/5; alpha = 1 - (1/3)/(3/5) = 4/9."""
        rows = {"v1": {"a": stored_tracks(kf_track(0, 30, changes={10: "partial"})),
                       "b": stored_tracks(kf_track(0, 30, changes={20: "partial"}))}}
        rows = {iid: {u: aa.track_objects(v) for u, v in per.items()} for iid, per in rows.items()}
        report = aa.attribute_agreement(rows, PER_KF, 0.5, to_canonical=aa.track_canonical,
                                        similarity=aa.track_similarity,
                                        attribute_steps=aa.video_track_steps)
        entry = report["occlusion"]
        assert entry["unit"] == "object-frame"
        assert entry["n_objects"] == 3
        assert entry["percent_agreement"] == pytest.approx(2 / 3)
        assert entry["alpha"] == pytest.approx(4 / 9)

    def test_the_dispatcher_scores_per_frame(self):
        from potato.server_utils.iaa.dispatcher import _object_attribute_report
        scheme = {"annotation_type": "video_annotation", "name": "objs", "mode": "tracking",
                  "labels": LABELS, "attributes": [
                      {"name": "occlusion", "type": "select", "options": ["none", "partial", "heavy"],
                       "per_keyframe": True}]}
        rows = {"v1": {"a": stored_tracks(kf_track(0, 30, changes={10: "partial"})),
                       "b": stored_tracks(kf_track(0, 30, changes={20: "partial"}))}}
        assert _object_attribute_report(scheme, rows)["occlusion"]["n_objects"] == 3

    def test_point_cloud_keyframes_carry_their_own_values(self):
        def keyframe(frame, value):
            return {"type": "cuboid_3d", "label": "car", "track_id": "t1", "frame": frame,
                    "attributes": {"occlusion": value},
                    "coordinates": {"center": [0, 0, 0], "size": [4, 2, 1.5], "rotation": [0, 0, 0, 1]}}
        stored = [keyframe(0, "none"), keyframe(5, "heavy")]
        [obj] = aa.spatial_tracks_with_attributes(stored)
        assert aa.spatial_track_steps(obj) == [(0, {"occlusion": "none"}), (5, {"occlusion": "heavy"})]


    def test_keyframes_that_change_nothing_add_no_units(self):
        """A point-cloud track stores every keyframe's full attributes; three
        keyframes with the same value are one unit, not three."""
        def keyframe(frame, value, user_x=0):
            return {"type": "cuboid_3d", "label": "car", "track_id": "t1", "frame": frame,
                    "attributes": {"occlusion": value},
                    "coordinates": {"center": [user_x, 0, 0], "size": [4, 2, 1.5],
                                    "rotation": [0, 0, 0, 1]}}
        rows = {"c1": {"a": aa.spatial_tracks_with_attributes(
                           [keyframe(0, "none"), keyframe(5, "none"), keyframe(9, "none")]),
                       "b": aa.spatial_tracks_with_attributes(
                           [keyframe(0, "none"), keyframe(5, "none"), keyframe(9, "none")])}}
        from potato.server_utils.iaa.structured import SPATIAL_MATCH
        report = aa.attribute_agreement(rows, PER_KF, SPATIAL_MATCH,
                                        to_canonical=aa.spatial_track_canonical,
                                        similarity=aa.spatial_track_similarity,
                                        attribute_steps=aa.spatial_track_steps)
        assert report["occlusion"]["n_objects"] == 1


class TestMotPerKeyframe:
    def test_conf_follows_ignore_frame_by_frame(self, tmp_path):
        from potato.export.base import ExportContext
        from potato.export.mot_exporter import MOTExporter
        t = track(0, 4, ignore=False)
        for f in (0, 4):
            t["keyframes"][str(f)]["time"] = f / 10
        t["keyframes"]["2"] = {"frame": 2, "time": 0.2, "attributes": {"ignore": True},
                               "bboxNorm": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}}
        scheme = {"annotation_type": "video_annotation", "name": "objs", "mode": "tracking",
                  "labels": LABELS, "video_fps": 10}
        context = ExportContext(config={"annotation_schemes": [scheme]},
                                annotations=[{"instance_id": "v1", "user_id": "a",
                                              "labels": {"objs": stored_tracks(t)}}],
                                items={"v1": {"width": 100, "height": 100, "fps": 10}},
                                schemas=[scheme], output_dir=str(tmp_path))
        result = MOTExporter().export(context, str(tmp_path), {})
        gt = next(p for p in result.files_written if p.endswith("gt.txt"))
        rows = [line.split(",") for line in open(gt).read().split()]
        # Frames 1-5 (1-indexed); ignore from frame index 2 on: conf 1, 1, 0, 0, 0.
        assert [(int(r[0]), int(r[6])) for r in rows] == [(1, 1), (2, 1), (3, 0), (4, 0), (5, 0)]

