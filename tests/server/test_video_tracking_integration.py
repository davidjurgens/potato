"""
Server integration tests for video object tracking.

Tests:
- Video annotation schema with tracking mode/options
- Schema generation includes tracking config
- Server startup with video tracking config
"""

import pytest
import json
import os
import sys
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.registry import schema_registry


class TestVideoAnnotationTrackingSchema:
    """Test video_annotation schema supports tracking options."""

    def test_video_annotation_registered(self):
        assert schema_registry.is_registered("video_annotation")

    def test_tracking_options_in_optional_fields(self):
        schema = schema_registry.get("video_annotation")
        assert schema is not None
        assert "tracking_options" in schema.optional_fields

    def test_generate_tracking_mode(self):
        scheme = {
            "annotation_type": "video_annotation",
            "name": "object_tracking",
            "description": "Track objects across frames",
            "mode": "tracking",
            "labels": [
                {"name": "person", "color": "#FF6B6B"},
                {"name": "vehicle", "color": "#4ECDC4"},
            ],
            "tracking_options": {
                "interpolation": "linear",
                "auto_advance_frames": 5,
            },
            "video_fps": 30,
            "show_timecode": True,
            "frame_stepping": True,
        }
        html, keybindings = schema_registry.generate(scheme)
        assert "object_tracking" in html
        assert len(html) > 0

    def test_generate_tracking_mode_with_cubic_interpolation(self):
        scheme = {
            "annotation_type": "video_annotation",
            "name": "smooth_tracking",
            "description": "Track with cubic interpolation",
            "mode": "tracking",
            "labels": [{"name": "ball", "color": "#FFD700"}],
            "tracking_options": {
                "interpolation": "cubic",
            },
        }
        html, keybindings = schema_registry.generate(scheme)
        assert "smooth_tracking" in html

    def test_generate_combined_mode_with_tracking(self):
        """Combined mode should also support tracking."""
        scheme = {
            "annotation_type": "video_annotation",
            "name": "combined_anno",
            "description": "Combined segments and tracking",
            "mode": "combined",
            "labels": [
                {"name": "action", "color": "#FF0000"},
            ],
        }
        html, keybindings = schema_registry.generate(scheme)
        assert "combined_anno" in html


class TestVideoTrackingInterpolationSpec:
    """Specification tests validating the interpolation logic.

    These are Python-equivalent tests that specify the expected behavior
    of the JavaScript TrackingInterpolationEngine.
    """

    def _interpolate(self, track_obj, frame):
        """Python equivalent of TrackingInterpolationEngine.interpolate."""
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
        return {
            "x": bbox1["x"] + (bbox2["x"] - bbox1["x"]) * t,
            "y": bbox1["y"] + (bbox2["y"] - bbox1["y"]) * t,
            "width": bbox1["width"] + (bbox2["width"] - bbox1["width"]) * t,
            "height": bbox1["height"] + (bbox2["height"] - bbox1["height"]) * t,
        }

    def test_linear_interpolation_midpoint(self):
        track = {
            "interpolation": "linear",
            "keyframes": {
                "0": {"frame": 0, "bbox": {"x": 0, "y": 0, "width": 100, "height": 50}},
                "30": {"frame": 30, "bbox": {"x": 300, "y": 150, "width": 200, "height": 100}},
            },
        }
        result = self._interpolate(track, 15)
        assert result is not None
        assert result["x"] == pytest.approx(150)
        assert result["y"] == pytest.approx(75)
        assert result["width"] == pytest.approx(150)
        assert result["height"] == pytest.approx(75)

    def test_constant_interpolation_holds(self):
        track = {
            "interpolation": "constant",
            "keyframes": {
                "0": {"frame": 0, "bbox": {"x": 10, "y": 20, "width": 100, "height": 50}},
                "30": {"frame": 30, "bbox": {"x": 200, "y": 300, "width": 400, "height": 200}},
            },
        }
        result = self._interpolate(track, 15)
        assert result["x"] == 10
        assert result["y"] == 20

    def test_out_of_range_returns_none(self):
        track = {
            "interpolation": "linear",
            "keyframes": {
                "10": {"frame": 10, "bbox": {"x": 0, "y": 0, "width": 50, "height": 50}},
                "20": {"frame": 20, "bbox": {"x": 100, "y": 100, "width": 50, "height": 50}},
            },
        }
        assert self._interpolate(track, 5) is None
        assert self._interpolate(track, 25) is None

    def test_exact_keyframe_returns_exact(self):
        track = {
            "interpolation": "linear",
            "keyframes": {
                "0": {"frame": 0, "bbox": {"x": 10, "y": 20, "width": 30, "height": 40}},
                "10": {"frame": 10, "bbox": {"x": 100, "y": 200, "width": 300, "height": 400}},
            },
        }
        result = self._interpolate(track, 0)
        assert result == {"x": 10, "y": 20, "width": 30, "height": 40}

    def test_multi_keyframe_interpolation(self):
        """Interpolation between non-adjacent keyframes."""
        track = {
            "interpolation": "linear",
            "keyframes": {
                "0": {"frame": 0, "bbox": {"x": 0, "y": 0, "width": 50, "height": 50}},
                "10": {"frame": 10, "bbox": {"x": 100, "y": 0, "width": 50, "height": 50}},
                "20": {"frame": 20, "bbox": {"x": 200, "y": 0, "width": 50, "height": 50}},
            },
        }
        # Frame 5 should interpolate between keyframe 0 and 10
        result = self._interpolate(track, 5)
        assert result["x"] == pytest.approx(50)
        # Frame 15 should interpolate between keyframe 10 and 20
        result = self._interpolate(track, 15)
        assert result["x"] == pytest.approx(150)
