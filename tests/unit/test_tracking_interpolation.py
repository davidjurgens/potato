"""
Tests for tracking interpolation engine.

Since the interpolation engine is JavaScript, these tests validate the
equivalent Python logic that would be used server-side. They also serve
as specification tests for the JS implementation.
"""

import pytest
import math


def _linear_interpolate(bbox1, bbox2, t):
    """Python equivalent of TrackingInterpolationEngine._linearInterpolate"""
    return {
        "x": bbox1["x"] + (bbox2["x"] - bbox1["x"]) * t,
        "y": bbox1["y"] + (bbox2["y"] - bbox1["y"]) * t,
        "width": bbox1["width"] + (bbox2["width"] - bbox1["width"]) * t,
        "height": bbox1["height"] + (bbox2["height"] - bbox1["height"]) * t,
    }


def _catmull_rom(p0, p1, p2, p3, t):
    """Python equivalent of TrackingInterpolationEngine._catmullRom"""
    t2 = t * t
    t3 = t2 * t
    return 0.5 * (
        (2 * p1) +
        (-p0 + p2) * t +
        (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
        (-p0 + 3 * p1 - 3 * p2 + p3) * t3
    )


def _interpolate(track_obj, frame):
    """Python equivalent of TrackingInterpolationEngine.interpolate"""
    keyframes = track_obj.get("keyframes", {})
    interpolation = track_obj.get("interpolation", "linear")

    frames = sorted(int(f) for f in keyframes.keys())
    if not frames:
        return None
    if len(frames) == 1:
        return dict(keyframes[str(frames[0])]["bbox"])

    if str(frame) in keyframes:
        return dict(keyframes[str(frame)]["bbox"])

    start = track_obj.get("startFrame", frames[0])
    end = track_obj.get("endFrame", frames[-1])
    if frame < start or frame > end:
        return None

    prev_frame = None
    next_frame = None
    for f in frames:
        if f <= frame:
            prev_frame = f
        if f > frame and next_frame is None:
            next_frame = f

    if prev_frame is None or next_frame is None:
        if prev_frame is not None:
            return dict(keyframes[str(prev_frame)]["bbox"])
        if next_frame is not None:
            return dict(keyframes[str(next_frame)]["bbox"])
        return None

    t = (frame - prev_frame) / (next_frame - prev_frame)

    if interpolation == "constant":
        return dict(keyframes[str(prev_frame)]["bbox"])

    bbox1 = keyframes[str(prev_frame)]["bbox"]
    bbox2 = keyframes[str(next_frame)]["bbox"]
    return _linear_interpolate(bbox1, bbox2, t)


class TestLinearInterpolation:
    def test_at_start(self):
        bbox1 = {"x": 0, "y": 0, "width": 100, "height": 50}
        bbox2 = {"x": 100, "y": 100, "width": 200, "height": 100}
        result = _linear_interpolate(bbox1, bbox2, 0.0)
        assert result == bbox1

    def test_at_end(self):
        bbox1 = {"x": 0, "y": 0, "width": 100, "height": 50}
        bbox2 = {"x": 100, "y": 100, "width": 200, "height": 100}
        result = _linear_interpolate(bbox1, bbox2, 1.0)
        assert result == bbox2

    def test_midpoint(self):
        bbox1 = {"x": 0, "y": 0, "width": 100, "height": 50}
        bbox2 = {"x": 100, "y": 100, "width": 200, "height": 100}
        result = _linear_interpolate(bbox1, bbox2, 0.5)
        assert result["x"] == pytest.approx(50)
        assert result["y"] == pytest.approx(50)
        assert result["width"] == pytest.approx(150)
        assert result["height"] == pytest.approx(75)

    def test_quarter(self):
        bbox1 = {"x": 0, "y": 0, "width": 100, "height": 100}
        bbox2 = {"x": 200, "y": 400, "width": 300, "height": 200}
        result = _linear_interpolate(bbox1, bbox2, 0.25)
        assert result["x"] == pytest.approx(50)
        assert result["y"] == pytest.approx(100)


class TestCatmullRom:
    def test_midpoint_linear_equivalent(self):
        """With uniform spacing, Catmull-Rom at t=0 should equal p1."""
        result = _catmull_rom(0, 10, 20, 30, 0.0)
        assert result == pytest.approx(10)

    def test_midpoint_reaches_p2(self):
        """At t=1, should reach p2."""
        result = _catmull_rom(0, 10, 20, 30, 1.0)
        assert result == pytest.approx(20)

    def test_smooth_curve(self):
        """Catmull-Rom should produce smooth intermediate values."""
        result = _catmull_rom(0, 10, 20, 30, 0.5)
        # For linear data, should be close to linear interpolation
        assert result == pytest.approx(15, abs=1)


class TestInterpolateFunction:
    def _make_track(self, keyframes_dict, interpolation="linear"):
        kf = {}
        for frame, bbox in keyframes_dict.items():
            kf[str(frame)] = {"frame": frame, "bbox": bbox}
        return {"keyframes": kf, "interpolation": interpolation}

    def test_no_keyframes(self):
        track = {"keyframes": {}}
        assert _interpolate(track, 10) is None

    def test_single_keyframe(self):
        track = self._make_track({
            0: {"x": 10, "y": 20, "width": 100, "height": 50}
        })
        result = _interpolate(track, 0)
        assert result["x"] == 10

    def test_exact_keyframe(self):
        track = self._make_track({
            0: {"x": 0, "y": 0, "width": 100, "height": 50},
            30: {"x": 100, "y": 100, "width": 200, "height": 100},
        })
        result = _interpolate(track, 30)
        assert result["x"] == 100

    def test_linear_midpoint(self):
        track = self._make_track({
            0: {"x": 0, "y": 0, "width": 100, "height": 50},
            30: {"x": 300, "y": 300, "width": 400, "height": 200},
        })
        result = _interpolate(track, 15)
        assert result["x"] == pytest.approx(150)
        assert result["y"] == pytest.approx(150)

    def test_out_of_range(self):
        track = self._make_track({
            10: {"x": 0, "y": 0, "width": 100, "height": 50},
            20: {"x": 100, "y": 100, "width": 200, "height": 100},
        })
        assert _interpolate(track, 5) is None
        assert _interpolate(track, 25) is None

    def test_constant_interpolation(self):
        track = self._make_track({
            0: {"x": 0, "y": 0, "width": 100, "height": 50},
            30: {"x": 300, "y": 300, "width": 400, "height": 200},
        }, interpolation="constant")
        result = _interpolate(track, 15)
        assert result["x"] == 0  # Should hold at previous keyframe

    def test_custom_range(self):
        track = self._make_track({
            10: {"x": 0, "y": 0, "width": 100, "height": 50},
            20: {"x": 100, "y": 100, "width": 200, "height": 100},
        })
        track["startFrame"] = 5
        track["endFrame"] = 25
        # Frame 5 is before first keyframe but within range -> hold
        result = _interpolate(track, 5)
        assert result is not None
