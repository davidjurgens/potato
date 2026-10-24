"""
Point-cloud sequences: keyframed 3D tracks, interpolation and KITTI tracking
export (potato/export/spatial_sequences.py).
"""

import math

import pytest

from potato.export import spatial_sequences as seq

IDENTITY_RT = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0]


def box(frame, track, cx, yaw=0.0, label="car", **attributes):
    half = yaw / 2
    return {"type": "cuboid_3d", "label": label, "frame": frame, "track_id": track,
            "attributes": attributes,
            "coordinates": {"center": [cx, 0.0, 0.0], "size": [4.0, 2.0, 1.5],
                            "rotation": [0.0, 0.0, math.sin(half), math.cos(half)]}}


class TestSequenceFrames:
    def test_a_list_or_a_frames_dict_is_a_sequence(self):
        assert seq.sequence_frames(["a.bin", "b.bin"]) == ["a.bin", "b.bin"]
        assert seq.sequence_frames({"frames": ["a.bin"], "fps": 10}) == ["a.bin"]

    def test_one_path_is_not(self):
        assert seq.sequence_frames("a.bin") is None
        assert seq.sequence_frames([]) is None


class TestInterpolation:
    def test_centre_moves_linearly_between_keyframes(self):
        keyframes = seq.tracks([box(0, "t1", 0.0), box(10, "t1", 10.0)])["t1"]
        mid = seq.object_at(keyframes, 4)
        assert mid["interpolated"] is True
        assert mid["center"][0] == pytest.approx(4.0)
        assert seq.object_at(keyframes, 10)["interpolated"] is False

    def test_a_track_is_absent_outside_its_keyframes(self):
        keyframes = seq.tracks([box(2, "t1", 0.0), box(5, "t1", 3.0)])["t1"]
        assert seq.object_at(keyframes, 1) is None
        assert seq.object_at(keyframes, 6) is None

    def test_rotation_takes_the_short_way_round(self):
        # +170 deg to -170 deg is 20 deg through 180, not 340 through 0.
        keyframes = seq.tracks([box(0, "t1", 0, yaw=math.radians(170)),
                                box(2, "t1", 0, yaw=math.radians(-170))])["t1"]
        x, y, z, w = seq.object_at(keyframes, 1)["rotation"]
        yaw = math.degrees(2 * math.atan2(z, w))
        assert abs(abs(yaw) - 180) == pytest.approx(0, abs=1e-6)

    def test_objects_without_a_track_or_frame_are_not_tracks(self):
        loose = box(0, "t1", 0)
        del loose["track_id"]
        nofr = box(0, "t2", 0)
        del nofr["frame"]
        assert seq.tracks([loose, nofr]) == {}


class TestDenseFrames:
    def test_every_frame_in_a_track_has_an_object(self):
        frames = seq.dense_frames([box(1, "a", 0), box(3, "a", 2), box(0, "b", 9)], 5)
        assert [len(frames[f]) for f in range(5)] == [1, 1, 1, 1, 0]
        assert {o["track_id"] for o in frames[1]} == {"a"}
        assert frames[2][0]["center"][0] == pytest.approx(1.0)

    def test_frames_past_the_sequence_are_dropped(self):
        frames = seq.dense_frames([box(0, "a", 0), box(9, "a", 9)], 3)
        assert sorted(frames) == [0, 1, 2]


class TestKittiTracking:
    def test_lines_are_dense_with_integer_track_ids(self):
        objects = [box(0, "car-x", 0.0, occluded="partly", truncated=True),
                   box(2, "car-x", 2.0, occluded="partly", truncated=True),
                   box(1, "ped", 5.0, label="pedestrian")]
        lines, ids = seq.kitti_tracking_lines(objects, 3, IDENTITY_RT)
        assert ids == {"car-x": 0, "ped": 1}
        assert [l.split()[:3] for l in lines] == [
            ["0", "0", "car"], ["1", "0", "car"], ["1", "1", "pedestrian"], ["2", "0", "car"]]
        fields = lines[0].split()
        assert fields[3] == "1"                                     # truncated: partly, an int
        assert int(fields[4]) == 1                                  # occluded: partly
        # 17 columns: frame, track id, then KITTI's fifteen.
        assert all(len(l.split()) == 17 for l in lines)

    def test_interpolated_location_reaches_the_file(self):
        lines, _ = seq.kitti_tracking_lines([box(0, "a", 0.0), box(2, "a", 2.0)], 3, IDENTITY_RT)
        # With an identity rig the sensor x is KITTI x; location is columns 13-15.
        xs = [float(l.split()[13]) for l in lines]
        assert xs == pytest.approx([0.0, 1.0, 2.0])


class TestSequenceAgreement:
    """Sequences are scored frame by frame; attributes over matched 3D tracks."""

    @staticmethod
    def stored(*objects):
        import json
        return json.dumps(list(objects))

    def test_frames_are_never_matched_across(self):
        from potato.server_utils.iaa.structured import spatial_report
        # Same box, but annotator a put it on frame 0 and b on frame 5:
        # mixing frames would call that perfect agreement.
        rows = {"s1": {"a": self.stored(box(0, "t1", 0.0)),
                       "b": self.stored(box(5, "t1", 0.0))}}
        report = spatial_report(rows)
        assert report["mean_agreement"] == 0.0
        assert report["n_frames"] == 2 and report["n_items"] == 1

    def test_interpolated_frames_count(self):
        from potato.server_utils.iaa.structured import spatial_report
        a = self.stored(box(0, "t1", 0.0), box(4, "t1", 4.0))
        b = self.stored(box(0, "x", 0.0), box(2, "x", 2.0), box(4, "x", 4.0))
        report = spatial_report({"s1": {"a": a, "b": b}})
        assert report["n_frames"] == 5
        assert report["mean_agreement"] == pytest.approx(1.0)

    def test_attribute_alpha_over_matched_3d_tracks(self):
        # B2's hand-computed case: none/none, partial/heavy, heavy/heavy -> 12/22.
        from potato.server_utils.iaa.dispatcher import _object_attribute_report
        scheme = {"name": "objs", "annotation_type": "spatial_annotation",
                  "labels": ["car"], "attributes": [{"name": "occlusion", "type": "select",
                                                     "options": ["none", "partial", "heavy"]}]}

        def track(tid, x, value, start=0, end=4):
            return [box(start, tid, x, occlusion=value), box(end, tid, x, occlusion=value)]
        rows = {
            "s1": {"a": self.stored(*track("a1", 0, "none")),
                   "b": self.stored(*track("b1", 0.1, "none"))},
            "s2": {"a": self.stored(*track("a1", 0, "partial")),
                   "b": self.stored(*track("b1", 0, "heavy"))},
            # b's second track is elsewhere in space and in time: not a unit.
            "s3": {"a": self.stored(*track("a1", 0, "heavy")),
                   "b": self.stored(*track("b1", 0, "heavy"), *track("b2", 40, "none", 6, 9))},
        }
        result = _object_attribute_report(scheme, rows)["occlusion"]
        assert result["alpha"] == pytest.approx(12 / 22, abs=1e-6)
        assert result["n_objects"] == 3


class TestKitti3DExporter:
    """The kitti_3d export format, through the registry."""

    @staticmethod
    def context(item, objects, tmp_path, users=("ann",)):
        import json
        from potato.export.base import ExportContext
        from tests.unit.test_calibration import KITTI_CALIB
        calib = {line.split(":")[0]: [float(v) for v in line.split(":")[1].split()]
                 for line in KITTI_CALIB.strip().splitlines()}
        item = dict(item, calibration=calib)
        scheme = {"annotation_type": "spatial_annotation", "name": "objects",
                  "source_field": "point_cloud"}
        return ExportContext(
            config={"task_dir": str(tmp_path)}, items={item["id"]: item}, schemas=[scheme],
            output_dir=str(tmp_path),
            annotations=[{"instance_id": item["id"], "user_id": u,
                          "labels": {"objects": {"_data": json.dumps(objects)}}} for u in users])

    def test_a_sequence_writes_dense_tracking_lines(self, tmp_path):
        from potato.export.registry import export_registry
        frames = ["seq/000000.bin", "seq/000001.bin", "seq/000002.bin"]
        ctx = self.context({"id": "drive_01", "point_cloud": frames},
                           [box(0, "t1", 10.0, occluded="partly"), box(2, "t1", 12.0, occluded="partly"),
                            {"type": "point_3d", "label": "car", "coordinates": [1, 2, 3]}], tmp_path)
        result = export_registry.export("kitti_3d", ctx, str(tmp_path / "out"))
        assert result.success
        [path] = result.files_written
        assert path.endswith("label_02/drive_01.txt")
        lines = open(path).read().splitlines()
        assert [l.split()[:4] for l in lines] == [["0", "0", "car", "0"],
                                                   ["1", "0", "car", "0"],
                                                   ["2", "0", "car", "0"]]
        assert {int(l.split()[4]) for l in lines} == {1}            # occluded: partly
        assert any("point_3d" in w for w in result.warnings)
        # Camera +Z is forward, as sensor +X: the interpolated frame is between.
        zs = [float(l.split()[15]) for l in lines]
        assert zs[0] < zs[1] < zs[2]

    def test_a_single_cloud_writes_object_labels(self, tmp_path):
        from potato.export.registry import export_registry
        obj = box(0, "t1", 10.0)
        del obj["frame"], obj["track_id"]
        ctx = self.context({"id": "s1", "point_cloud": "clouds/scene_0001.bin"}, [obj], tmp_path)
        result = export_registry.export("kitti_3d", ctx, str(tmp_path / "out"))
        [path] = result.files_written
        assert path.endswith("label_2/scene_0001.txt")
        assert len(open(path).read().split()) == 15

    def test_an_item_without_calibration_is_reported_not_guessed(self, tmp_path):
        from potato.export.registry import export_registry
        ctx = self.context({"id": "s1", "point_cloud": "a.bin"}, [box(0, "t1", 1.0)], tmp_path)
        ctx.items["s1"].pop("calibration")
        result = export_registry.export("kitti_3d", ctx, str(tmp_path / "out"))
        assert result.files_written == []
        assert any("no usable calibration" in w for w in result.warnings)


class TestVideoTracksToMot:
    """Video tracks reach MOT ground truth, interpolated and in pixels."""

    @staticmethod
    def context(tmp_path, tracks, item=None):
        import json
        from potato.export.base import ExportContext
        scheme = {"annotation_type": "video_annotation", "name": "objects", "mode": "tracking",
                  "video_fps": 25}
        item = item or {"id": "clip", "video_url": "https://example.org/clip.mp4"}
        blob = json.dumps({"segments": [], "tracks": {t["id"]: t for t in tracks}})
        return ExportContext(config={}, items={item["id"]: item}, schemas=[scheme],
                             output_dir=str(tmp_path),
                             annotations=[{"instance_id": item["id"], "user_id": "a",
                                           "labels": {"objects": {"_data": blob}}}])

    @staticmethod
    def track(tid, label="car", interpolation="linear", page_fps=25, **attributes):
        def kf(frame, x):
            return {"frame": frame, "time": frame / page_fps,
                    "bbox": {"x": 1, "y": 1, "width": 9, "height": 9},
                    "bboxNorm": {"x": x, "y": 0.5, "width": 0.1, "height": 0.2}}
        return {"id": tid, "label": label, "interpolation": interpolation,
                "attributes": attributes, "keyframes": {"0": kf(0, 0.0), "4": kf(4, 0.4)}}

    def test_rows_on_every_frame_in_pixels(self, tmp_path):
        from potato.export.registry import export_registry
        ctx = self.context(tmp_path, [self.track("track_1")])
        result = export_registry.export("mot", ctx, str(tmp_path / "out"),
                                        {"width": "1000", "height": "500"})
        gt = (tmp_path / "out" / "clip" / "gt" / "gt.txt").read_text().splitlines()
        assert [row.split(",")[:3] for row in gt] == [
            ["1", "1", "0.00"], ["2", "1", "100.00"], ["3", "1", "200.00"],
            ["4", "1", "300.00"], ["5", "1", "400.00"]]
        assert gt[0].split(",")[3:6] == ["250.00", "100.00", "100.00"]
        assert gt[0].split(",")[7] == "3"                       # car
        info = (tmp_path / "out" / "clip" / "seqinfo.ini").read_text()
        assert "imWidth=1000" in info and "frameRate=25" in info and "seqLength=5" in info
        # No file rate could be read, so the scheme's video_fps stood in, without a warning.
        assert not any("assume 30 fps" in w for w in result.warnings)
        assert not any("no image annotation" in w for w in result.warnings)

    def test_constant_interpolation_holds_the_box(self, tmp_path):
        from potato.export.registry import export_registry
        ctx = self.context(tmp_path, [self.track("track_1", interpolation="constant")])
        export_registry.export("mot", ctx, str(tmp_path / "out"), {"width": "1000", "height": "500"})
        gt = (tmp_path / "out" / "clip" / "gt" / "gt.txt").read_text().splitlines()
        assert [row.split(",")[2] for row in gt] == ["0.00"] * 4 + ["400.00"]

    def test_an_unknown_size_is_reported_not_guessed(self, tmp_path):
        from potato.export.registry import export_registry
        result = export_registry.export("mot", self.context(tmp_path, [self.track("t")]),
                                        str(tmp_path / "out"))
        assert result.files_written == []
        # Nothing written is a failure, not "Export successful" (potato-skill,
        # 2.12.0 pack notes P6: a remote video URL wrote 0 files).
        assert not result.success
        assert any("pixel size is unknown" in e for e in result.errors)

    def test_the_item_size_is_used(self, tmp_path):
        from potato.export.registry import export_registry
        item = {"id": "clip", "video_url": "x.mp4", "width": 640, "height": 480}
        result = export_registry.export("mot", self.context(tmp_path, [self.track("t")], item),
                                        str(tmp_path / "out"))
        assert "imWidth=640" in (tmp_path / "out" / "clip" / "seqinfo.ini").read_text()
        assert result.stats["num_sequences"] == 1


class TestKitti2DBoxes:
    """F1: the 2D columns are the projected box, or KITTI evaluation ignores the object."""

    @staticmethod
    def export(tmp_path, objects, item_extra=None, options=None):
        from potato.export.registry import export_registry
        ctx = TestKitti3DExporter.context(dict({"id": "s1", "point_cloud": "a.bin"},
                                               **(item_extra or {})), objects, tmp_path)
        result = export_registry.export("kitti_3d", ctx, str(tmp_path / "out"), options or {})
        lines = open(result.files_written[0]).read().splitlines()
        return result, lines

    @staticmethod
    def single(x, y=0.0):
        obj = box(0, "t1", x)
        obj["coordinates"]["center"][1] = y
        del obj["frame"], obj["track_id"]
        return obj

    def test_a_car_ahead_gets_a_tall_enough_box(self, tmp_path):
        result, [line] = self.export(tmp_path, [self.single(15.0)],
                                     options={"image_width": "1242", "image_height": "375"})
        x1, y1, x2, y2 = map(float, line.split()[4:8])
        assert 0 <= x1 < x2 <= 1242 and 0 <= y1 < y2 <= 375
        # A 1.5 m tall car 15 m ahead is about 72 px tall through KITTI's
        # 721 px focal length: well above the 25 px evaluation minimum.
        assert 50 < y2 - y1 < 100
        assert float(line.split()[1]) == 0.0
        assert not any("zero 2D box" in w for w in result.warnings)

    def test_a_box_cut_by_the_image_edge_is_clipped_and_truncated(self, tmp_path):
        _result, [line] = self.export(tmp_path, [self.single(6.0, y=5.0)],
                                      options={"image_width": "1242", "image_height": "375"})
        fields = line.split()
        assert float(fields[4]) == 0.0              # clipped at the left edge
        assert 0.0 < float(fields[1]) < 1.0         # truncation measured

    def test_a_box_behind_the_camera_is_reported(self, tmp_path):
        result, [line] = self.export(tmp_path, [self.single(-10.0)],
                                     options={"image_width": "1242", "image_height": "375"})
        assert line.split()[4:8] == ["0.00"] * 4
        assert any("zero 2D box" in w for w in result.warnings)

    def test_an_unknown_image_size_is_reported(self, tmp_path):
        result, [line] = self.export(tmp_path, [self.single(15.0)])
        assert float(line.split()[7]) > 0
        assert any("not clipped" in w for w in result.warnings)

    def test_tracking_lines_carry_the_box_too(self, tmp_path):
        from potato.export.registry import export_registry
        ctx = TestKitti3DExporter.context({"id": "d", "point_cloud": ["a.bin", "b.bin"]},
                                          [box(0, "t1", 15.0), box(1, "t1", 16.0)], tmp_path)
        result = export_registry.export("kitti_3d", ctx, str(tmp_path / "out"),
                                        {"image_width": "1242", "image_height": "375"})
        lines = open(result.files_written[0]).read().splitlines()
        heights = [float(l.split()[9]) - float(l.split()[7]) for l in lines]
        assert all(h > 25 for h in heights) and heights[0] > heights[1]

    def test_rows_are_in_the_files_frames_not_the_pages(self, tmp_path):
        # F2: the page numbered frames at 30 fps (no video_fps), the file is
        # 25 fps. A keyframe at page frame 30 is t = 1.0 s, real frame 25.
        from potato.export.registry import export_registry
        ctx = TestVideoTracksToMot.context(tmp_path, [TestVideoTracksToMot.track("t", page_fps=30)])
        ctx.schemas[0].pop("video_fps")
        def kf(frame, x):
            return {"frame": frame, "time": frame / 30,
                    "bboxNorm": {"x": x, "y": 0.5, "width": 0.1, "height": 0.2}}
        import json
        track = {"id": "t", "label": "car", "keyframes": {"0": kf(0, 0.0), "30": kf(30, 0.5)}}
        ctx.annotations[0]["labels"]["objects"]["_data"] = json.dumps({"tracks": {"t": track}})
        export_registry.export("mot", ctx, str(tmp_path / "out"),
                               {"width": "1000", "height": "500", "fps": "25"})
        gt = (tmp_path / "out" / "clip" / "gt" / "gt.txt").read_text().splitlines()
        assert [row.split(",")[0] for row in gt][-1] == "26"        # real frame 25, 1-indexed
        assert len(gt) == 26
        assert "frameRate=25" in (tmp_path / "out" / "clip" / "seqinfo.ini").read_text()

    def test_an_unknown_rate_is_reported(self, tmp_path):
        from potato.export.registry import export_registry
        ctx = TestVideoTracksToMot.context(tmp_path, [TestVideoTracksToMot.track("t", page_fps=30)])
        ctx.schemas[0].pop("video_fps")
        result = export_registry.export("mot", ctx, str(tmp_path / "out"),
                                        {"width": "1000", "height": "500"})
        assert any("assume 30 fps" in w for w in result.warnings)


class TestSequenceDistance:
    """Every caller of spatial_distance, including the labeling engine, sees frames."""

    def test_the_same_box_on_different_frames_is_a_disagreement(self):
        import json
        from potato.server_utils.iaa.structured import spatial_distance, spatial_objects
        a = spatial_objects(json.dumps([box(0, "t1", 0.0)]))
        b = spatial_objects(json.dumps([box(5, "t1", 0.0)]))
        assert spatial_distance(a, b) == 1.0
        assert spatial_distance(a, spatial_objects(json.dumps([box(0, "x", 0.0)]))) == 0.0

    def test_the_labeling_engine_loss_uses_frames(self):
        import json
        from potato.labeling_engine.families import Spatial
        family = Spatial.__new__(Spatial)
        human = family.human_value(json.dumps([box(0, "t1", 0.0), box(4, "t1", 4.0)]))
        same = family.human_value(json.dumps([box(0, "p", 0.0), box(2, "p", 2.0),
                                              box(4, "p", 4.0)]))
        moved = family.human_value(json.dumps([box(4, "p", 0.0)]))
        assert family.loss(same, human) == pytest.approx(0.0)
        assert family.loss(moved, human) == 1.0


class TestTruncationFloor:
    """The measured share outside the image is a floor an attribute can only raise."""

    def test_false_does_not_hide_a_clipped_box(self, tmp_path):
        obj = TestKitti2DBoxes.single(6.0, y=5.0)
        obj["attributes"] = {"truncated": False}
        _r, [line] = TestKitti2DBoxes.export(tmp_path, [obj], options={
            "image_width": "1242", "image_height": "375"})
        assert 0.0 < float(line.split()[1]) < 1.0

    def test_categorical_values_map_like_occlusion(self):
        from potato.export.spatial_sequences import _truncation, tracking_truncation
        assert tracking_truncation({"truncated": "partly"}) == 1
        assert tracking_truncation({"truncated": "fully"}) == 2
        assert tracking_truncation({"truncated": "none"}, measured=0.4) == 1
        assert tracking_truncation({"truncated": False}, measured=1.0) == 2
        assert _truncation({"truncated": "partly"}) == 0.5
        assert _truncation({"truncated": "partly"}, measured=0.7) == 0.7
        assert _truncation({"truncated": "fully"}) == 1.0
        assert _truncation({"truncated": 0.2}, measured=0.6) == 0.6

    def test_an_unrecognized_value_is_reported(self, tmp_path):
        obj = TestKitti2DBoxes.single(15.0)
        obj["attributes"] = {"truncated": "sort of"}
        result, [line] = TestKitti2DBoxes.export(tmp_path, [obj], options={
            "image_width": "1242", "image_height": "375"})
        assert float(line.split()[1]) == 0.0
        assert any("'sort of'" in w for w in result.warnings)
