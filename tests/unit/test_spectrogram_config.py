"""
Unit tests for spectrogram visualization configuration in audio annotation schema.

Tests the spectrogram feature including:
- Spectrogram configuration options
- HTML canvas element generation when enabled
- Default values for spectrogram options
- Validation of spectrogram options
"""

import pytest
import json
import sys
import os

# Add the potato directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.audio_annotation import (
    generate_audio_annotation_layout,
    _process_spectrogram_options,
    DEFAULT_SPECTROGRAM_OPTIONS,
    VALID_COLOR_MAPS,
)


class TestSpectrogramConfig:
    """Tests for spectrogram configuration in audio annotation."""

    def test_spectrogram_disabled_by_default(self):
        """Test that spectrogram is disabled by default."""
        scheme = {
            "name": "test_audio",
            "description": "Test audio annotation",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [{"name": "speech"}],
        }

        html, keybindings = generate_audio_annotation_layout(scheme)

        # Should not have spectrogram HTML elements when not enabled
        # (JS may still reference spectrogram IDs conditionally)
        assert '<canvas id="spectrogram-canvas' not in html
        assert 'class="spectrogram-container"' not in html

    def test_spectrogram_enabled(self):
        """Test that spectrogram canvas is included when enabled."""
        scheme = {
            "name": "test_audio_spectrogram",
            "description": "Test audio with spectrogram",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [{"name": "speech"}],
            "spectrogram": True,
        }

        html, keybindings = generate_audio_annotation_layout(scheme)

        # Should have spectrogram elements
        assert "spectrogram-container" in html
        assert "spectrogram-canvas" in html
        assert "spectrogram-playhead" in html
        assert 'id="spectrogram-test_audio_spectrogram"' in html
        assert 'id="spectrogram-canvas-test_audio_spectrogram"' in html

    def test_spectrogram_options_in_config(self):
        """Test that spectrogram options are passed to JavaScript config."""
        scheme = {
            "name": "test_spectrogram_options",
            "description": "Test spectrogram options",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [{"name": "speech"}],
            "spectrogram": True,
            "spectrogram_options": {
                "fft_size": 4096,
                "hop_length": 256,
                "frequency_range": [100, 4000],
                "color_map": "magma",
            },
        }

        html, keybindings = generate_audio_annotation_layout(scheme)

        # Check that config is in the JavaScript initialization
        assert '"spectrogram": true' in html.lower() or '"spectrogram":true' in html.lower()
        # Verify spectrogram options are passed
        assert "spectrogramOptions" in html
        assert "4096" in html
        assert "magma" in html

    def test_spectrogram_with_waveform(self):
        """Test that both waveform and spectrogram can be displayed."""
        scheme = {
            "name": "test_both_display",
            "description": "Test waveform and spectrogram",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [{"name": "speech"}],
            "waveform": True,
            "spectrogram": True,
        }

        html, keybindings = generate_audio_annotation_layout(scheme)

        # Should have both waveform and spectrogram
        assert "waveform-container" in html
        assert "spectrogram-container" in html

    def test_waveform_false_spectrogram_true(self):
        """Test spectrogram only mode (waveform disabled)."""
        scheme = {
            "name": "test_spectrogram_only",
            "description": "Spectrogram only",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [{"name": "speech"}],
            "waveform": False,
            "spectrogram": True,
        }

        html, keybindings = generate_audio_annotation_layout(scheme)

        # Should still have waveform container (Peaks.js needs it)
        # but spectrogram should be present
        assert "spectrogram-container" in html


class TestSpectrogramOptionsProcessing:
    """Tests for spectrogram options processing and validation."""

    def test_default_options(self):
        """Test default spectrogram options are applied."""
        options = _process_spectrogram_options({}, "test_schema")

        assert options["fft_size"] == DEFAULT_SPECTROGRAM_OPTIONS["fft_size"]
        assert options["hop_length"] == DEFAULT_SPECTROGRAM_OPTIONS["hop_length"]
        assert options["frequency_range"] == DEFAULT_SPECTROGRAM_OPTIONS["frequency_range"]
        assert options["color_map"] == DEFAULT_SPECTROGRAM_OPTIONS["color_map"]

    def test_custom_fft_size(self):
        """Test custom FFT size is applied."""
        options = _process_spectrogram_options({"fft_size": 4096}, "test_schema")
        assert options["fft_size"] == 4096

    def test_invalid_fft_size_not_power_of_2(self):
        """Test that non-power-of-2 FFT size falls back to default."""
        # 3000 is not a power of 2
        options = _process_spectrogram_options({"fft_size": 3000}, "test_schema")
        assert options["fft_size"] == DEFAULT_SPECTROGRAM_OPTIONS["fft_size"]

    def test_custom_hop_length(self):
        """Test custom hop length is applied."""
        options = _process_spectrogram_options({"hop_length": 256}, "test_schema")
        assert options["hop_length"] == 256

    def test_custom_frequency_range(self):
        """Test custom frequency range is applied."""
        options = _process_spectrogram_options(
            {"frequency_range": [100, 4000]}, "test_schema"
        )
        assert options["frequency_range"] == [100, 4000]

    def test_invalid_frequency_range(self):
        """Test invalid frequency range falls back to default."""
        # Invalid: min > max
        options = _process_spectrogram_options(
            {"frequency_range": [8000, 100]}, "test_schema"
        )
        assert options["frequency_range"] == DEFAULT_SPECTROGRAM_OPTIONS["frequency_range"]

        # Invalid: not a list
        options = _process_spectrogram_options(
            {"frequency_range": 4000}, "test_schema"
        )
        assert options["frequency_range"] == DEFAULT_SPECTROGRAM_OPTIONS["frequency_range"]

        # Invalid: wrong length
        options = _process_spectrogram_options(
            {"frequency_range": [100, 200, 300]}, "test_schema"
        )
        assert options["frequency_range"] == DEFAULT_SPECTROGRAM_OPTIONS["frequency_range"]

    def test_valid_color_maps(self):
        """Test all valid color maps are accepted."""
        for color_map in VALID_COLOR_MAPS:
            options = _process_spectrogram_options({"color_map": color_map}, "test_schema")
            assert options["color_map"] == color_map

    def test_invalid_color_map(self):
        """Test invalid color map falls back to default."""
        options = _process_spectrogram_options(
            {"color_map": "rainbow"}, "test_schema"
        )
        assert options["color_map"] == DEFAULT_SPECTROGRAM_OPTIONS["color_map"]

    def test_partial_options_merged_with_defaults(self):
        """Test partial options are merged with defaults."""
        options = _process_spectrogram_options(
            {"fft_size": 4096, "color_map": "plasma"},
            "test_schema"
        )

        assert options["fft_size"] == 4096
        assert options["color_map"] == "plasma"
        # Others should be defaults
        assert options["hop_length"] == DEFAULT_SPECTROGRAM_OPTIONS["hop_length"]
        assert options["frequency_range"] == DEFAULT_SPECTROGRAM_OPTIONS["frequency_range"]

    def test_none_options_returns_defaults(self):
        """Test None options returns defaults."""
        options = _process_spectrogram_options(None, "test_schema")
        assert options == DEFAULT_SPECTROGRAM_OPTIONS


class TestSpectrogramJSConfig:
    """Tests for JavaScript configuration generation."""

    def test_js_config_includes_spectrogram_settings(self):
        """Test that JS config includes spectrogram settings."""
        scheme = {
            "name": "js_config_test",
            "description": "JS config test",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [{"name": "test"}],
            "spectrogram": True,
            "spectrogram_options": {
                "fft_size": 4096,
                "color_map": "inferno",
            },
        }

        html, _ = generate_audio_annotation_layout(scheme)

        # Extract the config JSON from the HTML (it's in a script tag)
        assert "spectrogramOptions" in html
        assert "fftSize" in html or "fft_size" in html

    def test_spectrogram_canvas_ids(self):
        """Test that spectrogram canvas IDs are correctly generated."""
        scheme = {
            "name": "canvas_id_test",
            "description": "Canvas ID test",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [{"name": "test"}],
            "spectrogram": True,
        }

        html, _ = generate_audio_annotation_layout(scheme)

        # Check canvas IDs are correctly formatted
        assert 'id="spectrogram-canvas_id_test"' in html
        assert 'id="spectrogram-canvas-canvas_id_test"' in html
        assert 'id="spectrogram-playhead-canvas_id_test"' in html


class TestSpectrogramIntegration:
    """Integration tests for spectrogram with audio annotation."""

    def test_spectrogram_with_all_modes(self):
        """Test spectrogram works with all annotation modes."""
        modes_and_config = [
            ("label", {"labels": [{"name": "speech"}]}),
            ("questions", {"segment_schemes": [{"annotation_type": "radio", "name": "q", "labels": ["a", "b"]}]}),
            ("both", {"labels": [{"name": "speech"}], "segment_schemes": [{"annotation_type": "radio", "name": "q", "labels": ["a"]}]}),
        ]

        for mode, extra_config in modes_and_config:
            scheme = {
                "name": f"mode_test_{mode}",
                "description": f"Test {mode} mode with spectrogram",
                "annotation_type": "audio_annotation",
                "mode": mode,
                "spectrogram": True,
                **extra_config,
            }

            html, _ = generate_audio_annotation_layout(scheme)

            assert "spectrogram-container" in html, f"Spectrogram missing in {mode} mode"
            assert f"mode_test_{mode}" in html

    def test_spectrogram_with_playback_controls(self):
        """Test spectrogram with playback rate control."""
        scheme = {
            "name": "playback_test",
            "description": "Test with playback controls",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [{"name": "test"}],
            "spectrogram": True,
            "playback_rate_control": True,
        }

        html, _ = generate_audio_annotation_layout(scheme)

        # Should have both spectrogram and playback controls
        assert "spectrogram-container" in html
        assert "playback-rate-select" in html


class TestSpectrogramDefaults:
    """Tests for default spectrogram configuration values."""

    def test_default_fft_size_is_2048(self):
        """Test default FFT size is 2048."""
        assert DEFAULT_SPECTROGRAM_OPTIONS["fft_size"] == 2048

    def test_default_hop_length_is_512(self):
        """Test default hop length is 512."""
        assert DEFAULT_SPECTROGRAM_OPTIONS["hop_length"] == 512

    def test_default_frequency_range(self):
        """Test default frequency range is [0, 8000]."""
        assert DEFAULT_SPECTROGRAM_OPTIONS["frequency_range"] == [0, 8000]

    def test_default_color_map_is_viridis(self):
        """Test default color map is viridis."""
        assert DEFAULT_SPECTROGRAM_OPTIONS["color_map"] == "viridis"

    def test_valid_color_maps_list(self):
        """Test valid color maps list includes expected values."""
        expected_maps = ["viridis", "magma", "plasma", "inferno", "grayscale"]
        for color_map in expected_maps:
            assert color_map in VALID_COLOR_MAPS


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
