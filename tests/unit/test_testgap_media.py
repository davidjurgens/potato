"""
Media coordinate maths against independent computations: a real nuScenes
calibration record against the devkit's projection, a 16-bit LAS file with a
dark point, a video longer than 20 seconds, and an image edited in place.

The earlier tests used an identity quaternion at the origin (which cannot
tell [w,x,y,z] from [x,y,z,w], or a pose from its inverse), one LAS colour
depth, and clips too short to reach the frame cap.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest

from tests.helpers.test_utils import create_test_directory


# ---------------------------------------------------------------------------
# Camera calibration
# ---------------------------------------------------------------------------

#: CAM_FRONT's calibrated_sensor record from nuScenes v1.0-mini.
NUSCENES_CAM_FRONT = {
    "channel": "CAM_FRONT",
    "translation": [1.70079118954, 0.0159456324149, 1.51095763913],
    "rotation": [0.4998015430569128, -0.5030316162024876,
                 0.4997798114386805, -0.49717015266149663],
    "camera_intrinsic": [[1266.417203046554, 0.0, 816.2670197447984],
                         [0.0, 1266.417203046554, 491.50706579294757],
                         [0.0, 0.0, 1.0]],
}


def _devkit_projection(record, point):
    """nuscenes-devkit: camera = R^T (p - t), R from the [w,x,y,z] quaternion."""
    q = np.array(record["rotation"]) / np.linalg.norm(record["rotation"])
    w, x, y, z = q
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                  [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                  [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])
    cam = r.T @ (np.asarray(point) - np.asarray(record["translation"]))
    uv = np.asarray(record["camera_intrinsic"]) @ cam
    return uv[:2] / uv[2]


class TestNuscenesCalibration:
    @pytest.mark.parametrize("point", [(11.7, 0.0, 1.5), (20.0, 3.0, 1.0), (8.0, -2.0, 2.5)])
    def test_projection_matches_the_devkit(self, point):
        from potato.media.calibration import parse_calibration, project_point
        camera = parse_calibration({"cameras": [NUSCENES_CAM_FRONT]}).cameras[0]
        assert project_point(camera, point) == pytest.approx(
            tuple(_devkit_projection(NUSCENES_CAM_FRONT, point)), abs=1e-6)

    def test_explicit_extrinsics_keep_their_documented_meaning(self):
        """`extrinsics` is sensor -> camera with an [x,y,z,w] quaternion."""
        from potato.media.calibration import parse_calibration, project_point
        camera = parse_calibration({"cameras": [{
            "intrinsics": {"fx": 100, "fy": 100, "cx": 50, "cy": 50},
            "extrinsics": {"rotation": [0, 0, 0, 1], "translation": [0, 0, 0]}}]}).cameras[0]
        assert project_point(camera, (1.0, 0.0, 10.0)) == pytest.approx((60.0, 50.0))


# ---------------------------------------------------------------------------
# LAS point clouds
# ---------------------------------------------------------------------------

def _las(points, path):
    """A minimal LAS 1.2, point format 2: (x, y, z, r, g, b) integers."""
    header = bytearray(227)
    header[0:4] = b"LASF"
    struct.pack_into("<H", header, 94, 227)
    struct.pack_into("<I", header, 96, 227)
    struct.pack_into("<B", header, 104, 2)
    struct.pack_into("<H", header, 105, 26)
    struct.pack_into("<I", header, 107, len(points))
    struct.pack_into("<3d", header, 131, 0.01, 0.01, 0.01)
    struct.pack_into("<3d", header, 155, 0.0, 0.0, 0.0)
    body = b""
    for x, y, z, r, g, b in points:
        record = bytearray(26)
        struct.pack_into("<3i", record, 0, x, y, z)
        struct.pack_into("<3H", record, 20, r, g, b)
        body += bytes(record)
    Path(path).write_bytes(bytes(header) + body)
    return path


class TestLasColour:
    def test_a_dark_point_in_a_16_bit_file_stays_dark(self):
        from potato.media.pointcloud import read_point_cloud
        path = _las([(0, 0, 0, 65535, 65535, 65535), (100, 0, 0, 200, 200, 200)],
                    os.path.join(create_test_directory("tg_las16"), "c.las"))
        colours = list(read_point_cloud(path).colors)
        assert colours[:3] == [255, 255, 255]
        assert max(colours[3:]) <= 1

    def test_an_8_bit_file_is_not_darkened(self):
        from potato.media.pointcloud import read_point_cloud
        path = _las([(0, 0, 0, 200, 100, 50)],
                    os.path.join(create_test_directory("tg_las8"), "c.las"))
        assert list(read_point_cloud(path).colors) == [200, 100, 50]


# ---------------------------------------------------------------------------
# Video frames
# ---------------------------------------------------------------------------

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg")


@pytest.fixture(scope="module")
def clip():
    """30 s at 30 fps, 900 frames, each a different solid grey level."""
    out = os.path.join(create_test_directory("tg_video"), "clip.mp4")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=32x32:r=30:d=30,geq=lum='mod(N\\,256)':cb=128:cr=128",
                    "-pix_fmt", "yuv420p", out], capture_output=True, check=True)
    return out


@needs_ffmpeg
class TestVideoFrames:
    def test_probe_reports_the_frame_rate(self, clip):
        from potato.media.video import probe_video
        assert probe_video(clip)["fps"] == pytest.approx(30.0)

    def test_frames_past_twenty_seconds_can_be_tracked(self, clip):
        from potato.video_tracking import _frame_paths
        window, temp = _frame_paths(Path(clip), 650, 10, 30.0)
        try:
            assert len(window) == 10
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    def test_the_window_starts_at_the_requested_frame(self, clip):
        from PIL import Image
        from potato.video_tracking import _frame_paths
        window, temp = _frame_paths(Path(clip), 300, 2, 30.0)
        try:
            # Frame N stores luma N mod 256 in limited range (16-235), which
            # reads as (Y - 16) * 255 / 219 in full range. Frame 300 is Y=44;
            # its neighbours, 43 and 45, are each about 1.2 away.
            level = np.asarray(Image.open(window[0]).convert("L")).mean()
            assert level == pytest.approx((300 % 256 - 16) * 255 / 219, abs=0.6)
        finally:
            shutil.rmtree(temp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Image embedding cache
# ---------------------------------------------------------------------------

class TestImageCacheKey:
    def test_editing_an_image_under_image_root_changes_its_key(self):
        from potato.vision_features import ImageEmbeddingVectorizer
        root = create_test_directory("tg_vision_key")
        os.makedirs(os.path.join(root, "media"), exist_ok=True)
        image = os.path.join(root, "media", "a.png")
        Path(image).write_bytes(b"first version")
        encoder = ImageEmbeddingVectorizer.__new__(ImageEmbeddingVectorizer)
        encoder.image_root = root
        before = encoder._key("/media/a.png")
        Path(image).write_bytes(b"second, different version")
        assert encoder._key("/media/a.png") != before
