"""
KITTI tracking import: label_02/ + velodyne/ + calib/ into a point-cloud
sequence project.

The labels are written by the kitti_3d export's own line writer
(spatial_sequences.kitti_tracking_lines) from boxes in the lidar frame, so
the import is checked as the inverse of the export: the boxes come back where
they started, through a real KITTI calibration in the tracking benchmark's
layout (R_rect and Tr_velo_cam with no colon).
"""

import json
import math
import os

import pytest
import yaml

from potato.export import spatial_sequences as seq
from potato.importers.kitti_tracking_importer import KITTITrackingImporter
from potato.media.calibration import parse_kitti_calib
from tests.unit.test_calibration import KITTI_CALIB

TRACKING_CALIB = (KITTI_CALIB.replace("R0_rect:", "R_rect")
                  .replace("Tr_velo_to_cam:", "Tr_velo_cam")
                  .replace("Tr_imu_to_velo:", "Tr_imu_velo"))


def car(frame, track, x, y=2.0, yaw=0.3, label="Car"):
    return {"type": "cuboid_3d", "label": label, "frame": frame, "track_id": track,
            "attributes": {"occluded": "partly" if frame == 2 else "none"},
            "coordinates": {"center": [x, y, -0.9], "size": [4.0, 1.8, 1.5],
                            "rotation": [0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2)]}}


SOURCE = [car(f, "a", 10.0 + f) for f in range(4)] + \
         [car(f, "b", 20.0 - f, y=-3.0, label="Pedestrian") for f in range(4)]


def dataset(root, label_lines=None, scans=4, calib=TRACKING_CALIB):
    """A training/ split with one sequence, 0000."""
    split = root / "training"
    (split / "label_02").mkdir(parents=True)
    (split / "velodyne" / "0000").mkdir(parents=True)
    (split / "calib").mkdir()
    for i in range(scans):
        (split / "velodyne" / "0000" / f"{i:06d}.bin").write_bytes(b"\0" * 16)
    if calib is not None:
        (split / "calib" / "0000.txt").write_text(calib)
    if label_lines is None:
        reference = parse_kitti_calib(TRACKING_CALIB).reference_rt
        label_lines, _ids = seq.kitti_tracking_lines(SOURCE, 4, reference)
    (split / "label_02" / "0000.txt").write_text("\n".join(label_lines) + "\n")
    return split


class TestTheImportInvertsTheExport:
    def test_boxes_come_back_in_the_lidar_frame(self, tmp_path):
        split = dataset(tmp_path)
        result = KITTITrackingImporter().parse_directory(str(tmp_path))
        [item] = result.images
        assert item.instance_id == "0000"
        assert item.extra["point_cloud"] == [f"velodyne/0000/{i:06d}.bin" for i in range(4)]
        assert item.extra["calibration"] == {"file": "calib/0000.txt"}
        assert len(item.objects) == 8
        by_key = {(o["frame"], o["label"]): o for o in item.objects}
        for source in SOURCE:
            back = by_key[(source["frame"], source["label"])]
            # The format writes two decimals, so a centre is back to a centimetre.
            assert back["coordinates"]["center"] == pytest.approx(
                source["coordinates"]["center"], abs=0.01)
            assert back["coordinates"]["size"] == pytest.approx([4.0, 1.8, 1.5], abs=0.006)
            # The yaw survives; the camera's slight tilt to the lidar shows up
            # as a small pitch/roll in the quaternion, which is why the
            # comparison is on the heading rather than the raw quaternion.
            x, y, z, w = back["coordinates"]["rotation"]
            heading = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
            assert heading == pytest.approx(0.3, abs=0.02)
        assert {o["track_id"] for o in item.objects} == {"0", "1"}
        assert by_key[(2, "Car")]["attributes"]["occluded"] == "partly"
        assert by_key[(1, "Car")]["attributes"] == {"occluded": "none", "truncated": "none"}
        assert [label["name"] for label in result.labels] == ["Car", "Pedestrian"]
        assert result.stats["num_tracks"] == 2 and result.stats["num_frames"] == 4
        assert split.is_dir()

    def test_re_export_writes_the_same_numbers(self, tmp_path):
        dataset(tmp_path)
        result = KITTITrackingImporter().parse_directory(str(tmp_path))
        reference = parse_kitti_calib(TRACKING_CALIB).reference_rt
        original, _ = seq.kitti_tracking_lines(SOURCE, 4, reference)
        again, _ = seq.kitti_tracking_lines(result.images[0].objects, 4, reference)

        def numbers(line):
            fields = line.split()
            return fields[:5] + [round(float(v), 2) for v in fields[10:17]]
        assert [numbers(line) for line in again] == [numbers(line) for line in original]


class TestWhatIsLeftOutOrCounted:
    LINE = "{f} {t} {ty} 0 {occ} -1 -1 -1 -1 -1 1.5 1.8 4.0 2.0 1.6 15.0 0.1"

    def test_dont_care_gaps_and_missing_scans(self, tmp_path):
        lines = [self.LINE.format(f=f, t=0, ty="Car", occ=0) for f in (0, 1, 3)]   # gap at 2
        lines += [self.LINE.format(f=1, t=-1, ty="DontCare", occ=3),
                  self.LINE.format(f=9, t=0, ty="Car", occ=0)]                    # no scan 9
        dataset(tmp_path, label_lines=lines)
        result = KITTITrackingImporter().parse_directory(str(tmp_path))
        assert [o["frame"] for o in result.images[0].objects] == [0, 1, 3]
        warnings = " ".join(result.warnings)
        assert "1 DontCare row" in warnings
        assert "1 label row(s) name a frame with no scan" in warnings
        assert "1 gap(s)" in warnings

    def test_a_sequence_with_a_missing_scan_is_skipped_by_name(self, tmp_path):
        split = dataset(tmp_path, scans=6)
        os.remove(split / "velodyne" / "0000" / "000004.bin")
        with pytest.raises(ValueError, match="scans 000004 are missing"):
            KITTITrackingImporter().parse_directory(str(tmp_path))

    def test_a_sequence_without_calibration_is_skipped_by_name(self, tmp_path):
        dataset(tmp_path, calib=None)
        with pytest.raises(ValueError, match="calib/0000.txt"):
            KITTITrackingImporter().parse_directory(str(tmp_path))

    def test_no_velodyne_folder_says_what_to_download(self, tmp_path):
        (tmp_path / "label_02").mkdir()
        with pytest.raises(ValueError, match="velodyne"):
            KITTITrackingImporter().parse_directory(str(tmp_path))


class TestTheCommand:
    def test_potato_import_writes_a_runnable_point_cloud_project(self, tmp_path):
        from potato.importers import cli

        dataset(tmp_path / "kitti")
        out = tmp_path / "project"
        assert cli.main(["--input", str(tmp_path / "kitti"), "--output-dir", str(out),
                         "--schema-name", "objects"]) == 0
        config = yaml.safe_load((out / "config.yaml").read_text())
        [scheme] = config["annotation_schemes"]
        assert scheme["annotation_type"] == "spatial_annotation"
        assert scheme["tools"] == ["cuboid_3d"] and scheme["calibration_field"] == "calibration"
        assert [a["name"] for a in scheme["attributes"]] == ["occluded", "truncated"]
        assert config["pre_annotation"]["field"] == "predictions"
        media = (out / config["media_directory"]).resolve()
        assert media == (tmp_path / "kitti" / "training").resolve()
        row = json.loads((out / config["data_files"][0]).read_text().splitlines()[0])
        assert (media / row["point_cloud"][0]).is_file()
        assert (media / row["calibration"]["file"]).is_file()
        objects = row["predictions"]["objects"]
        assert len(objects) == 8 and all(o["source"] == "import" for o in objects)
        assert "image_width" not in row
        assert row["notes"] == "KITTI tracking sequence 0000: 4 frames, 2 tracks"
        assert config["item_properties"]["text_key"] == "notes"
        assert "kitti_3d" in (out / "README.md").read_text()

    def test_the_folder_is_detected(self, tmp_path):
        from potato.importers.cli import _detect_directory_format
        dataset(tmp_path)
        assert _detect_directory_format(str(tmp_path)) == "kitti_tracking"
        assert _detect_directory_format(str(tmp_path / "training")) == "kitti_tracking"
