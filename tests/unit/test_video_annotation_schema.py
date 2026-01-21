#!/usr/bin/env python3
"""
Unit tests for video annotation schema.

Tests HTML generation, mode validation, label processing, and keybindings.
"""

import pytest
import json
from potato.server_utils.schemas.video_annotation import (
    generate_video_annotation_layout,
    _process_labels,
    _generate_keybindings,
    VALID_MODES,
    DEFAULT_COLORS,
)
from potato.server_utils.schemas.registry import schema_registry


class TestVideoAnnotationSchemaBasic:
    """Basic tests for video annotation schema generation."""

    def test_basic_segment_mode_generation(self):
        """Test that segment mode generates valid HTML."""
        scheme = {
            "name": "test_video",
            "description": "Test video annotation",
            "annotation_type": "video_annotation",
            "mode": "segment",
            "labels": ["intro", "content", "outro"]
        }

        html, keybindings = generate_video_annotation_layout(scheme)

        # Check basic structure
        assert 'class="annotation-form video-annotation"' in html
        assert 'data-schema="test_video"' in html
        assert 'data-mode="segment"' in html
        assert "Test video annotation" in html

        # Check video element
        assert '<video id="video-test_video"' in html

        # Check timeline elements
        assert 'id="zoomview-test_video"' in html
        assert 'id="overview-test_video"' in html

        # Check segment controls
        assert 'data-action="set-start"' in html
        assert 'data-action="set-end"' in html
        assert 'data-action="create-segment"' in html

    def test_frame_mode_generation(self):
        """Test frame classification mode generates correct controls."""
        scheme = {
            "name": "frame_test",
            "description": "Frame classification",
            "annotation_type": "video_annotation",
            "mode": "frame",
            "labels": ["scene_change", "action", "dialogue"]
        }

        html, keybindings = generate_video_annotation_layout(scheme)

        # Check frame-specific controls
        assert 'data-action="classify-frame"' in html
        assert "Classify Frame" in html

        # Check keybindings include frame classification
        key_actions = [k[1] for k in keybindings]
        assert any("Classify" in action for action in key_actions)

    def test_keyframe_mode_generation(self):
        """Test keyframe annotation mode generates correct controls."""
        scheme = {
            "name": "keyframe_test",
            "description": "Keyframe marking",
            "annotation_type": "video_annotation",
            "mode": "keyframe",
            "labels": ["important", "scene_change"]
        }

        html, keybindings = generate_video_annotation_layout(scheme)

        # Check keyframe-specific controls
        assert 'data-action="mark-keyframe"' in html
        assert "Mark Keyframe" in html

        # Check keybindings include keyframe marking
        keys = [k[0] for k in keybindings]
        assert "K" in keys

    def test_combined_mode_generation(self):
        """Test combined mode includes all controls."""
        scheme = {
            "name": "combined_test",
            "description": "Combined annotation",
            "annotation_type": "video_annotation",
            "mode": "combined",
            "labels": ["label1", "label2"]
        }

        html, keybindings = generate_video_annotation_layout(scheme)

        # Should have segment, frame, and keyframe controls
        assert 'data-action="create-segment"' in html
        assert 'data-action="classify-frame"' in html
        assert 'data-action="mark-keyframe"' in html

    def test_tracking_mode_generation(self):
        """Test tracking mode with labels generates canvas overlay."""
        scheme = {
            "name": "tracking_test",
            "description": "Object tracking",
            "annotation_type": "video_annotation",
            "mode": "tracking",
            "labels": ["object1", "object2"]  # Tracking mode can have labels
        }

        html, keybindings = generate_video_annotation_layout(scheme)

        # Should have tracking canvas
        assert 'tracking-canvas-tracking_test' in html
        assert 'data-mode="tracking"' in html


class TestVideoAnnotationModes:
    """Tests for mode validation."""

    def test_valid_modes(self):
        """Test that all valid modes are recognized."""
        assert "segment" in VALID_MODES
        assert "frame" in VALID_MODES
        assert "keyframe" in VALID_MODES
        assert "tracking" in VALID_MODES
        assert "combined" in VALID_MODES

    def test_invalid_mode_returns_error_html(self):
        """Test that invalid mode returns error HTML."""
        scheme = {
            "name": "invalid_mode_test",
            "description": "Invalid mode",
            "annotation_type": "video_annotation",
            "mode": "invalid_mode",
            "labels": ["label1"]
        }

        html, keybindings = generate_video_annotation_layout(scheme)

        # Error should be in HTML, not raised as exception
        assert "annotation-error" in html
        assert "Invalid mode" in html
        assert "invalid_mode" in html

    def test_default_mode_is_segment(self):
        """Test that default mode is segment."""
        scheme = {
            "name": "default_mode_test",
            "description": "Default mode test",
            "annotation_type": "video_annotation",
            "labels": ["label1"]
            # mode not specified, should default to "segment"
        }

        html, _ = generate_video_annotation_layout(scheme)
        assert 'data-mode="segment"' in html


class TestLabelProcessing:
    """Tests for label processing."""

    def test_string_labels(self):
        """Test processing string labels."""
        labels = ["intro", "content", "outro"]
        processed = _process_labels(labels)

        assert len(processed) == 3
        assert processed[0]["name"] == "intro"
        assert processed[1]["name"] == "content"
        assert processed[2]["name"] == "outro"

        # Check colors are assigned
        for label in processed:
            assert "color" in label
            assert label["color"].startswith("#")

    def test_dict_labels(self):
        """Test processing dict labels with custom colors."""
        labels = [
            {"name": "intro", "color": "#FF0000", "key_value": "1"},
            {"name": "outro", "color": "#00FF00", "key_value": "2"}
        ]
        processed = _process_labels(labels)

        assert len(processed) == 2
        assert processed[0]["name"] == "intro"
        assert processed[0]["color"] == "#FF0000"
        assert processed[0]["key_value"] == "1"
        assert processed[1]["name"] == "outro"
        assert processed[1]["color"] == "#00FF00"

    def test_mixed_labels(self):
        """Test processing mixed string and dict labels."""
        labels = [
            "simple_label",
            {"name": "custom_label", "color": "#AABBCC"}
        ]
        processed = _process_labels(labels)

        assert len(processed) == 2
        assert processed[0]["name"] == "simple_label"
        assert processed[1]["name"] == "custom_label"
        assert processed[1]["color"] == "#AABBCC"

    def test_color_cycling(self):
        """Test that colors cycle through defaults."""
        labels = [f"label_{i}" for i in range(len(DEFAULT_COLORS) + 2)]
        processed = _process_labels(labels)

        # Colors should cycle back after exhausting defaults
        assert processed[0]["color"] == processed[len(DEFAULT_COLORS)]["color"]


class TestKeybindings:
    """Tests for keybinding generation."""

    def test_segment_mode_keybindings(self):
        """Test keybindings for segment mode."""
        labels = [{"name": "intro", "key_value": "1"}]
        keybindings = _generate_keybindings(labels, "segment", frame_stepping=True)

        keys = [k[0] for k in keybindings]

        # Should have playback controls
        assert "Space" in keys

        # Should have frame stepping
        assert "," in keys
        assert "." in keys

        # Should have segment controls
        assert "[" in keys
        assert "]" in keys
        assert "Enter" in keys

        # Should have zoom
        assert "+/-" in keys

        # Should have label shortcut
        assert "1" in keys

    def test_keyframe_mode_keybindings(self):
        """Test keybindings include K for keyframe mode."""
        labels = []
        keybindings = _generate_keybindings(labels, "keyframe", frame_stepping=True)

        keys = [k[0] for k in keybindings]
        assert "K" in keys

    def test_frame_mode_keybindings(self):
        """Test keybindings include C for frame mode."""
        labels = []
        keybindings = _generate_keybindings(labels, "frame", frame_stepping=True)

        keys = [k[0] for k in keybindings]
        assert "C" in keys

    def test_no_frame_stepping_keybindings(self):
        """Test keybindings without frame stepping."""
        labels = []
        keybindings = _generate_keybindings(labels, "segment", frame_stepping=False)

        keys = [k[0] for k in keybindings]

        # Should not have frame stepping keys
        assert "," not in keys
        assert "." not in keys


class TestConfigOptions:
    """Tests for configuration options."""

    def test_timeline_height(self):
        """Test timeline height is applied."""
        scheme = {
            "name": "height_test",
            "description": "Height test",
            "annotation_type": "video_annotation",
            "mode": "segment",
            "labels": ["label1"],
            "timeline_height": 100
        }

        html, _ = generate_video_annotation_layout(scheme)
        assert 'style="height: 100px;"' in html

    def test_playback_rate_control(self):
        """Test playback rate control is included when enabled."""
        scheme = {
            "name": "rate_test",
            "description": "Rate test",
            "annotation_type": "video_annotation",
            "mode": "segment",
            "labels": ["label1"],
            "playback_rate_control": True
        }

        html, _ = generate_video_annotation_layout(scheme)
        assert "playback-rate-select" in html
        assert "0.1x" in html
        assert "2x" in html

    def test_playback_rate_control_disabled(self):
        """Test playback rate control is not included when disabled."""
        scheme = {
            "name": "rate_test_disabled",
            "description": "Rate test disabled",
            "annotation_type": "video_annotation",
            "mode": "segment",
            "labels": ["label1"],
            "playback_rate_control": False
        }

        html, _ = generate_video_annotation_layout(scheme)
        # The <select class="playback-rate-select"> should not appear
        assert '<select class="playback-rate-select">' not in html

    def test_frame_stepping_enabled(self):
        """Test frame stepping controls are included when enabled."""
        scheme = {
            "name": "step_test",
            "description": "Step test",
            "annotation_type": "video_annotation",
            "mode": "segment",
            "labels": ["label1"],
            "frame_stepping": True
        }

        html, _ = generate_video_annotation_layout(scheme)
        assert 'data-action="frame-back"' in html
        assert 'data-action="frame-forward"' in html

    def test_frame_stepping_disabled(self):
        """Test frame stepping controls are not included when disabled."""
        scheme = {
            "name": "step_test_disabled",
            "description": "Step test disabled",
            "annotation_type": "video_annotation",
            "mode": "segment",
            "labels": ["label1"],
            "frame_stepping": False
        }

        html, _ = generate_video_annotation_layout(scheme)
        assert 'data-action="frame-back"' not in html
        assert 'data-action="frame-forward"' not in html

    def test_timecode_display(self):
        """Test timecode display is included when enabled."""
        scheme = {
            "name": "timecode_test",
            "description": "Timecode test",
            "annotation_type": "video_annotation",
            "mode": "segment",
            "labels": ["label1"],
            "show_timecode": True
        }

        html, _ = generate_video_annotation_layout(scheme)
        assert "frame-number" in html
        assert "timecode" in html


class TestSchemaRegistry:
    """Tests for schema registry integration."""

    def test_video_annotation_is_registered(self):
        """Test that video_annotation is registered in the schema registry."""
        assert schema_registry.is_registered("video_annotation")

    def test_video_annotation_schema_definition(self):
        """Test that video_annotation schema definition is correct."""
        schema_def = schema_registry.get("video_annotation")

        assert schema_def is not None
        assert schema_def.name == "video_annotation"
        assert schema_def.supports_keybindings is True
        assert "mode" in schema_def.optional_fields
        assert "labels" in schema_def.optional_fields
        assert "timeline_height" in schema_def.optional_fields

    def test_generate_via_registry(self):
        """Test generating layout via registry."""
        scheme = {
            "name": "registry_test",
            "description": "Registry test",
            "annotation_type": "video_annotation",
            "mode": "segment",
            "labels": ["label1"]
        }

        html, keybindings = schema_registry.generate(scheme)

        assert "video-annotation" in html
        assert len(keybindings) > 0


class TestValidation:
    """Tests for validation."""

    def test_missing_labels_returns_error_html(self):
        """Test that missing labels returns error HTML for segment mode."""
        scheme = {
            "name": "no_labels_test",
            "description": "No labels",
            "annotation_type": "video_annotation",
            "mode": "segment"
            # labels missing
        }

        html, keybindings = generate_video_annotation_layout(scheme)

        # Error should be in HTML
        assert "annotation-error" in html
        assert "labels" in html.lower()

    def test_empty_labels_returns_error_html(self):
        """Test that empty labels returns error HTML."""
        scheme = {
            "name": "empty_labels_test",
            "description": "Empty labels",
            "annotation_type": "video_annotation",
            "mode": "segment",
            "labels": []
        }

        html, keybindings = generate_video_annotation_layout(scheme)

        # Error should be in HTML
        assert "annotation-error" in html
        assert "labels" in html.lower()


class TestJsConfigGeneration:
    """Tests for JavaScript config generation."""

    def test_js_config_in_html(self):
        """Test that JS config is embedded in HTML."""
        scheme = {
            "name": "js_config_test",
            "description": "JS config test",
            "annotation_type": "video_annotation",
            "mode": "segment",
            "labels": [{"name": "label1", "color": "#FF0000"}],
            "min_segments": 2,
            "max_segments": 10,
            "video_fps": 24
        }

        html, _ = generate_video_annotation_layout(scheme)

        # Check that config object is in the script
        assert '"schemaName":"js_config_test"' in html or '"schemaName": "js_config_test"' in html
        assert '"mode":"segment"' in html or '"mode": "segment"' in html
        assert '"minSegments":2' in html or '"minSegments": 2' in html
        assert '"videoFps":24' in html or '"videoFps": 24' in html


class TestHtmlEscaping:
    """Tests for HTML escaping (XSS prevention)."""

    def test_description_is_escaped(self):
        """Test that description is HTML escaped."""
        scheme = {
            "name": "xss_test",
            "description": "<script>alert('xss')</script>",
            "annotation_type": "video_annotation",
            "mode": "segment",
            "labels": ["label1"]
        }

        html, _ = generate_video_annotation_layout(scheme)

        # Script tag should be escaped
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html or "script" not in html.lower().replace("type=\"button\"", "")

    def test_label_names_are_escaped_in_buttons(self):
        """Test that label names are HTML escaped in button elements."""
        scheme = {
            "name": "label_xss_test",
            "description": "Test",
            "annotation_type": "video_annotation",
            "mode": "segment",
            "labels": ["<script>alert(1)</script>"]
        }

        html, _ = generate_video_annotation_layout(scheme)

        # The label button text should have escaped HTML
        # This should appear as &lt;script&gt; in the button content
        assert "&lt;script&gt;" in html
        # The unescaped script tag should NOT appear outside script elements
        # Find button elements and ensure they don't have unescaped content
        # The button content is the visible text, which should be escaped
        import re
        button_matches = re.findall(r'<button[^>]*class="label-btn"[^>]*>.*?</button>', html, re.DOTALL)
        for button in button_matches:
            # Button should not contain unescaped <script> tag as HTML
            # (it may contain it in data attributes as attribute-escaped text)
            assert '<script>alert' not in button.split('>')[-2]  # Check button text content
