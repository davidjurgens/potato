"""
Cross-language check: the JS and the Python must project to the same pixels.

Projection exists twice on purpose. The server projects for exporters (KITTI's
2D box column is a projected 3D box) and the browser projects while the
annotator drags, sixty times a second, where a round trip per frame is not an
option. Duplication with no check is how the verification panel quietly stops
agreeing with the exported data -- and the panel exists precisely so the
annotator can trust what they see.

Each side has its own unit tests against its own expectations, which is the
situation where a *shared misreading* passes both. This runs the real shipped
JavaScript in Node against the real Python.

Skipped when Node is absent.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from potato.media.calibration import (NEAR_PLANE, parse_kitti_calib,
                                      project_cuboid, project_point,
                                      project_segment)
from potato.export.spatial_utils import cuboid_corners, yaw_to_quaternion
from tests.unit.test_calibration import KITTI_CALIB

CALIB_JS = Path("potato/static/pointcloud/pc-calibration.js").resolve()

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def run_js(body: str):
    script = f"""
        const calib = require({str(CALIB_JS)!r});
        {body}
    """
    result = subprocess.run(["node", "-e", script], capture_output=True,
                            text=True, timeout=60)
    if result.returncode != 0:
        raise AssertionError(f"node failed: {result.stderr}")
    return json.loads(result.stdout)


def camera_json(cam):
    return json.dumps(cam.to_dict())


KITTI = parse_kitti_calib(KITTI_CALIB).cameras[0]

#: A camera with real lens distortion, which KITTI does not have -- the
#: rectified rig would leave that whole code path unchecked on both sides.
DISTORTED = parse_kitti_calib(KITTI_CALIB).cameras[0]
DISTORTED.distortion = (-0.28, 0.11, 0.001, -0.002, -0.02)


POINTS = [
    (10.0, 0.0, -1.6),        # straight ahead on the road
    (25.0, 6.0, -1.4),        # off to the left, further away
    (6.0, -3.5, 0.4),         # near, right, above the sensor
    (60.0, 0.0, -1.6),        # far
    (0.6, 0.0, -1.6),         # very close, near the frustum edge
    (-9.0, 1.0, -1.5),        # behind: both sides must return "nothing"
]


@pytest.mark.parametrize("cam_name,cam", [("kitti", KITTI),
                                          ("distorted", DISTORTED)])
@pytest.mark.parametrize("point", POINTS, ids=[str(p) for p in POINTS])
def test_points_project_identically(cam_name, cam, point):
    from_js = run_js(f"""
        const uv = calib.projectPoint({camera_json(cam)}, {json.dumps(point)});
        process.stdout.write(JSON.stringify(uv));
    """)
    from_py = project_point(cam, point)

    if from_py is None:
        assert from_js is None, (
            f"{cam_name}: Python culled {point} but JS returned {from_js}; a "
            f"point behind the camera must project to nothing on both sides")
        return
    assert from_js is not None, f"{cam_name}: JS culled {point}, Python did not"
    assert math.isclose(from_js[0], from_py[0], abs_tol=1e-6)
    assert math.isclose(from_js[1], from_py[1], abs_tol=1e-6)


SEGMENTS = [
    ((10.0, -2.0, -1.6), (10.0, 2.0, -1.6)),      # wholly visible
    ((-5.0, 0.0, -1.5), (-9.0, 0.0, -1.5)),       # wholly behind
    ((3.0, 0.0, -1.5), (-3.0, 0.0, -1.5)),        # straddling the near plane
    ((-3.0, 0.0, -1.5), (3.0, 0.0, -1.5)),        # the same, reversed
]


@pytest.mark.parametrize("a,b", SEGMENTS, ids=[f"{a}->{b}" for a, b in SEGMENTS])
def test_segments_clip_identically(a, b):
    """
    The near-plane clip is the subtlest shared behaviour.

    A strict-versus-inclusive comparison at exactly the near plane -- a bug
    this module actually shipped -- makes one side draw the clipped edge and
    the other drop it, so the wireframe on the photograph has a missing line
    that the viewport does not.
    """
    from_js = run_js(f"""
        const seg = calib.projectSegment({camera_json(KITTI)},
            {json.dumps(a)}, {json.dumps(b)});
        process.stdout.write(JSON.stringify(seg));
    """)
    from_py = project_segment(KITTI, a, b)

    if from_py is None:
        assert from_js is None
        return
    assert from_js is not None, "Python kept this segment and JS dropped it"
    for js_pt, py_pt in zip(from_js, from_py):
        assert math.isclose(js_pt[0], py_pt[0], rel_tol=1e-9, abs_tol=1e-6)
        assert math.isclose(js_pt[1], py_pt[1], rel_tol=1e-9, abs_tol=1e-6)


CUBOIDS = [
    ("car ahead", [12.0, 0.5, -0.9], [4.2, 1.8, 1.5], [0, 0, 0, 1]),
    ("yawed 30 degrees", [15.0, -2.0, -0.8], [4.0, 1.8, 1.6],
     list(yaw_to_quaternion(math.pi / 6))),
    ("tilted out of plane", [9.0, 1.0, -0.6], [2.0, 2.0, 2.0],
     [0.13, 0.05, 0.2, 0.968]),
    ("straddling the camera", [0.2, 0.0, -1.0], [6.0, 2.0, 1.6], [0, 0, 0, 1]),
    ("behind the camera", [-14.0, 0.0, -1.0], [4.0, 2.0, 1.6], [0, 0, 0, 1]),
]


@pytest.mark.parametrize("name,center,size,rotation", CUBOIDS,
                         ids=[c[0] for c in CUBOIDS])
def test_cuboids_project_identically(name, center, size, rotation):
    corners = cuboid_corners(center, size, rotation)
    from_js = run_js(f"""
        const out = calib.projectCuboid({camera_json(KITTI)},
            {json.dumps(corners)});
        process.stdout.write(JSON.stringify(out));
    """)
    from_py = project_cuboid(KITTI, center, size, rotation)

    assert from_js["visible"] == from_py["visible"], name
    assert len(from_js["edges"]) == len(from_py["edges"]), (
        f"{name}: JS drew {len(from_js['edges'])} edges, Python "
        f"{len(from_py['edges'])} -- they disagree about what is visible")

    for i, (js_edge, py_edge) in enumerate(zip(from_js["edges"],
                                               from_py["edges"])):
        for js_pt, py_pt in zip(js_edge, py_edge):
            assert math.isclose(js_pt[0], py_pt[0], rel_tol=1e-9, abs_tol=1e-6), \
                f"{name}: edge {i}"
            assert math.isclose(js_pt[1], py_pt[1], rel_tol=1e-9, abs_tol=1e-6), \
                f"{name}: edge {i}"

    if from_py["bbox"] is None:
        assert from_js["bbox"] is None
    else:
        for js_v, py_v in zip(from_js["bbox"], from_py["bbox"]):
            assert math.isclose(js_v, py_v, rel_tol=1e-9, abs_tol=1e-6), name


def test_the_near_plane_constant_is_the_same_on_both_sides():
    """
    A constant duplicated across languages is the classic silent divergence:
    nothing errors, edges just get cut in different places.
    """
    from_js = run_js("process.stdout.write(JSON.stringify(calib.NEAR_PLANE));")
    assert from_js == NEAR_PLANE


def test_the_edge_list_is_the_same_on_both_sides():
    from potato.media.calibration import BOX_EDGES

    from_js = run_js("process.stdout.write(JSON.stringify(calib.BOX_EDGES));")
    assert [tuple(e) for e in from_js] == list(BOX_EDGES)
