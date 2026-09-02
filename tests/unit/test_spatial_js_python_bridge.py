"""
Cross-language check: the JS and the Python must agree on a box's corners.

Cuboid corner maths exists twice — in ``potato/export/spatial_utils.py`` for
exporters and agreement, and in ``potato/static/pointcloud/pc-viewer.js`` for
drawing the wireframe. That duplication is deliberate (the browser cannot call
Python and the exporter cannot call the browser), but duplication with no check
is how two implementations quietly diverge until an exported box does not match
the one the annotator drew.

Each side has its own unit tests against its own expectations, which is exactly
the situation where a *shared misreading* passes both. This runs the real
shipped JavaScript in Node and compares its numbers to the real Python, so a
divergence fails the build rather than shipping.

Skipped when Node is absent.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from potato.export.spatial_utils import cuboid_corners, yaw_to_quaternion

VIEWER = Path("potato/static/pointcloud/pc-viewer.js").resolve()

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def js_corners(center, size, rotation):
    """Corners as the shipped browser code computes them."""
    script = f"""
        const Manager = require({str(VIEWER)!r});
        const out = Manager.cuboidCorners(
            {json.dumps(center)}, {json.dumps(size)}, {json.dumps(rotation)});
        process.stdout.write(JSON.stringify(out));
    """
    result = subprocess.run(["node", "-e", script], capture_output=True,
                            text=True, timeout=60)
    if result.returncode != 0:
        raise AssertionError(f"node failed: {result.stderr}")
    return json.loads(result.stdout)


CASES = [
    ("axis aligned at the origin", [0, 0, 0], [2, 4, 6], [0, 0, 0, 1]),
    ("translated", [10.5, -3.25, 2.0], [4, 1.8, 1.5], [0, 0, 0, 1]),
    ("yaw 45 degrees", [0, 0, 0], [4, 2, 1.5],
     list(yaw_to_quaternion(math.pi / 4))),
    ("yaw 90 degrees", [1, 2, 3], [4, 2, 1.5],
     list(yaw_to_quaternion(math.pi / 2))),
    ("pitched out of plane", [0, 0, 0], [3, 3, 1],
     [0.3826834, 0.0, 0.0, 0.9238795]),
    ("tumbled on all three axes", [-5, 7, 1], [2, 3, 4],
     [0.2, 0.3, 0.4, 0.8386]),
]


@pytest.mark.parametrize("name,center,size,rotation", CASES,
                         ids=[c[0] for c in CASES])
def test_corners_agree(name, center, size, rotation):
    from_js = js_corners(center, size, rotation)
    from_py = cuboid_corners(center, size, rotation)

    assert len(from_js) == 8 == len(from_py)
    for i, (a, b) in enumerate(zip(from_js, from_py)):
        for axis in range(3):
            assert math.isclose(a[axis], b[axis], abs_tol=1e-6), (
                f"{name}: corner {i} axis {axis} differs — "
                f"JS {a[axis]} vs Python {b[axis]}")


def test_a_non_unit_quaternion_is_normalized_the_same_way():
    # Both sides must normalize, and to the same result: a non-unit quaternion
    # SCALES the box, so one side normalizing and the other not produces a
    # wireframe that does not match the exported extent.
    center, size, quat = [0, 0, 0], [2, 2, 2], [0, 0, 2, 2]
    for a, b in zip(js_corners(center, size, quat),
                    cuboid_corners(center, size, quat)):
        assert all(math.isclose(x, y, abs_tol=1e-6) for x, y in zip(a, b))


def test_an_unusable_rotation_falls_back_to_identity_on_both_sides():
    center, size = [0, 0, 0], [2, 2, 2]
    for bad in ([], [1, 2], [0, 0, 0, 0]):
        from_js = js_corners(center, size, bad)
        from_py = cuboid_corners(center, size, bad)
        for a, b in zip(from_js, from_py):
            assert all(math.isclose(x, y, abs_tol=1e-6) for x, y in zip(a, b))
        # Identity means an axis-aligned box.
        assert sorted({round(c[0], 6) for c in from_js}) == [-1.0, 1.0]


def test_the_corner_order_is_the_one_the_edge_list_assumes():
    """
    The wireframe draws twelve edges by index pair, so the order is part of the
    contract rather than an implementation detail.
    """
    script = f"""
        const Manager = require({str(VIEWER)!r});
        process.stdout.write(JSON.stringify({{
            edges: Manager.BOX_EDGES,
            corners: Manager.cuboidCorners([0,0,0], [2,2,2], [0,0,0,1]),
        }}));
    """
    result = subprocess.run(["node", "-e", script], capture_output=True,
                            text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)

    # First four corners are the -Z face, last four are +Z, in both languages.
    for corners in (data["corners"], cuboid_corners([0, 0, 0], [2, 2, 2],
                                                    [0, 0, 0, 1])):
        assert all(math.isclose(c[2], -1.0) for c in corners[:4])
        assert all(math.isclose(c[2], 1.0) for c in corners[4:])

    # Every edge joins corners that differ in exactly one axis, which is only
    # true if the winding is right.
    for a, b in data["edges"]:
        differing = sum(1 for axis in range(3)
                        if abs(data["corners"][a][axis]
                               - data["corners"][b][axis]) > 1e-9)
        assert differing == 1, f"edge {a}-{b} is a diagonal, not a box edge"
