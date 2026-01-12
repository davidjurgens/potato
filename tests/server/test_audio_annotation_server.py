"""
Server-side integration tests for audio annotation.

Tests the complete server-side functionality including:
- Configuration loading and validation
- Schema generation via Flask routes
- Waveform service functionality
- API endpoints for audio annotation
"""

import pytest
import json
import os
import sys
import tempfile
import shutil
from unittest.mock import patch, MagicMock

# Add potato to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.config_module import init_config, config, ConfigValidationError
from potato.server_utils.schemas import validate_schema_config
from potato.server_utils.schemas.registry import schema_registry
from potato.server_utils.waveform_service import WaveformService, init_waveform_service, get_waveform_service
from tests.helpers.test_utils import cleanup_test_directory


class TestAudioAnnotationServerConfig:
    """Test audio annotation configuration on server side."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        self.test_dirs = []
        self.original_cwd = os.getcwd()
        yield
        os.chdir(self.original_cwd)
        for test_dir in self.test_dirs:
            cleanup_test_directory(test_dir)

    def _create_test_config(self, config_content: dict) -> str:
        """Create a test config file and return its path."""
        # Use tests/output directory to comply with path security
        import uuid
        tests_dir = os.path.dirname(os.path.dirname(__file__))
        test_dir = os.path.join(tests_dir, "output", f"audio_test_{uuid.uuid4().hex[:8]}")
        os.makedirs(test_dir, exist_ok=True)
        self.test_dirs.append(test_dir)

        # Create data directory and file
        data_dir = os.path.join(test_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        data_file = os.path.join(data_dir, "test_audio.json")
        with open(data_file, "w") as f:
            f.write('{"id": "audio_001", "audio_url": "https://example.com/test.mp3"}\n')
            f.write('{"id": "audio_002", "audio_url": "https://example.com/test2.mp3"}\n')

        # Create output directory
        output_dir = os.path.join(test_dir, "annotation_output")
        os.makedirs(output_dir, exist_ok=True)

        # Update config with correct paths
        config_content["task_dir"] = test_dir
        config_content["data_files"] = ["data/test_audio.json"]
        config_content["output_annotation_dir"] = "annotation_output/"

        # Write config file
        config_file = os.path.join(test_dir, "config.yaml")
        import yaml
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        return config_file

    def _create_args(self, config_path):
        """Create args object for init_config."""
        class Args:
            pass
        args = Args()
        args.config_file = config_path
        args.verbose = False
        args.very_verbose = False
        args.debug = False
        args.customjs = None
        args.customjs_hostname = None
        args.persist_sessions = False
        return args

    def test_audio_annotation_config_loads(self):
        """Test that audio annotation config loads correctly."""
        config_content = {
            "server_name": "Audio Annotation Test",
            "annotation_task_name": "Test Task",
            "output_annotation_format": "json",
            "alert_time_each_instance": 0,
            "item_properties": {
                "id_key": "id",
                "text_key": "audio_url"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "annotation_schemes": [
                {
                    "annotation_type": "audio_annotation",
                    "name": "audio_segmentation",
                    "description": "Segment the audio",
                    "mode": "label",
                    "labels": [
                        {"name": "speech", "color": "#4ECDC4"},
                        {"name": "music", "color": "#FF6B6B"}
                    ]
                }
            ]
        }

        config_path = self._create_test_config(config_content)
        args = self._create_args(config_path)

        init_config(args)

        assert config is not None
        assert "annotation_schemes" in config
        schemes = config.get("annotation_schemes", [])
        assert len(schemes) == 1
        assert schemes[0]["annotation_type"] == "audio_annotation"

    def test_audio_annotation_schema_validation(self):
        """Test that audio annotation schema validates correctly."""
        config_content = {
            "server_name": "Audio Annotation Test",
            "annotation_task_name": "Test Task",
            "output_annotation_format": "json",
            "alert_time_each_instance": 0,
            "item_properties": {
                "id_key": "id",
                "text_key": "audio_url"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "annotation_schemes": [
                {
                    "annotation_type": "audio_annotation",
                    "name": "audio_segmentation",
                    "description": "Segment the audio",
                    "mode": "label",
                    "labels": [
                        {"name": "speech", "color": "#4ECDC4", "key_value": "1"},
                        {"name": "music", "color": "#FF6B6B", "key_value": "2"}
                    ],
                    "zoom_enabled": True,
                    "playback_rate_control": True,
                    "min_segments": 1,
                    "max_segments": 10
                }
            ]
        }

        config_path = self._create_test_config(config_content)
        args = self._create_args(config_path)

        init_config(args)

        # Validate each scheme
        for scheme in config.get("annotation_schemes", []):
            validate_schema_config(scheme)

    def test_audio_annotation_invalid_mode_rejected(self):
        """Test that invalid mode is rejected."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "audio_annotation",
            "name": "test",
            "description": "Test",
            "mode": "invalid_mode",
            "labels": [{"name": "speech"}]
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_scheme")
        assert "mode" in str(exc_info.value).lower()

    def test_audio_annotation_label_mode_missing_labels_rejected(self):
        """Test that label mode without labels is rejected."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "audio_annotation",
            "name": "test",
            "description": "Test",
            "mode": "label"
            # Missing labels
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_scheme")
        assert "labels" in str(exc_info.value).lower()

    def test_audio_annotation_questions_mode_missing_schemes_rejected(self):
        """Test that questions mode without segment_schemes is rejected."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "audio_annotation",
            "name": "test",
            "description": "Test",
            "mode": "questions"
            # Missing segment_schemes
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_scheme")
        assert "segment_schemes" in str(exc_info.value).lower()


class TestAudioAnnotationSchemaGeneration:
    """Test audio annotation schema generation."""

    def test_schema_generates_html_label_mode(self):
        """Test that schema generates valid HTML in label mode."""
        scheme = {
            "annotation_type": "audio_annotation",
            "name": "audio_segmentation",
            "description": "Segment the audio by content type",
            "mode": "label",
            "labels": [
                {"name": "speech", "color": "#4ECDC4"},
                {"name": "music", "color": "#FF6B6B"}
            ]
        }

        html, keybindings = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0
        assert "audio_segmentation" in html
        assert "audio-annotation-container" in html
        assert "waveform-container" in html
        assert "segment-list" in html

    def test_schema_generates_html_with_zoom(self):
        """Test that schema generates zoom controls when enabled."""
        scheme = {
            "annotation_type": "audio_annotation",
            "name": "test",
            "description": "Test",
            "mode": "label",
            "labels": [{"name": "speech"}],
            "zoom_enabled": True
        }

        html, keybindings = schema_registry.generate(scheme)

        assert 'data-action="zoom-in"' in html
        assert 'data-action="zoom-out"' in html
        assert 'data-action="zoom-fit"' in html

    def test_schema_generates_html_with_playback_rate(self):
        """Test that schema generates playback rate control when enabled."""
        scheme = {
            "annotation_type": "audio_annotation",
            "name": "test",
            "description": "Test",
            "mode": "label",
            "labels": [{"name": "speech"}],
            "playback_rate_control": True
        }

        html, keybindings = schema_registry.generate(scheme)

        assert "playback-rate-select" in html
        assert "0.5x" in html
        assert "1x" in html
        assert "2x" in html

    def test_schema_generates_label_buttons(self):
        """Test that schema generates label selection buttons."""
        scheme = {
            "annotation_type": "audio_annotation",
            "name": "test",
            "description": "Test",
            "mode": "label",
            "labels": [
                {"name": "speech", "color": "#4ECDC4"},
                {"name": "music", "color": "#FF6B6B"},
                {"name": "silence", "color": "#95A5A6"}
            ]
        }

        html, keybindings = schema_registry.generate(scheme)

        assert 'data-label="speech"' in html
        assert 'data-label="music"' in html
        assert 'data-label="silence"' in html
        assert "#4ECDC4" in html
        assert "#FF6B6B" in html
        assert "#95A5A6" in html

    def test_schema_generates_keybindings(self):
        """Test that schema generates keybindings."""
        scheme = {
            "annotation_type": "audio_annotation",
            "name": "test",
            "description": "Test",
            "mode": "label",
            "labels": [
                {"name": "speech", "key_value": "1"},
                {"name": "music", "key_value": "2"}
            ]
        }

        html, keybindings = schema_registry.generate(scheme)

        assert keybindings is not None
        keys = [k for k, _ in keybindings]
        assert "Space" in keys  # Play/pause
        assert "1" in keys  # speech
        assert "2" in keys  # music
        assert "Enter" in keys  # Create segment

    def test_schema_default_label_colors(self):
        """Test that labels without colors get default colors."""
        scheme = {
            "annotation_type": "audio_annotation",
            "name": "test",
            "description": "Test",
            "mode": "label",
            "labels": [
                {"name": "label1"},  # No color specified
                {"name": "label2"}   # No color specified
            ]
        }

        html, keybindings = schema_registry.generate(scheme)

        # Should have default colors assigned
        assert "label-color-dot" in html
        assert 'data-label="label1"' in html
        assert 'data-label="label2"' in html


class TestWaveformService:
    """Test WaveformService functionality."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        self.test_dirs = []
        yield
        for test_dir in self.test_dirs:
            cleanup_test_directory(test_dir)

    def _create_temp_dir(self):
        """Create a temporary directory."""
        test_dir = tempfile.mkdtemp(prefix="potato_waveform_test_")
        self.test_dirs.append(test_dir)
        return test_dir

    def test_service_initialization(self):
        """Test WaveformService initialization."""
        cache_dir = self._create_temp_dir()
        service = WaveformService(
            cache_dir=cache_dir,
            look_ahead=3,
            cache_max_size=50
        )

        assert service.cache_dir == cache_dir
        assert service.look_ahead == 3
        assert service.cache_max_size == 50
        assert os.path.exists(cache_dir)

    def test_cache_dir_creation(self):
        """Test that cache directory is created if it doesn't exist."""
        base_dir = self._create_temp_dir()
        cache_dir = os.path.join(base_dir, "waveform_cache")

        assert not os.path.exists(cache_dir)

        service = WaveformService(cache_dir=cache_dir)

        assert os.path.exists(cache_dir)

    def test_cache_key_generation(self):
        """Test that cache keys are generated consistently."""
        cache_dir = self._create_temp_dir()
        service = WaveformService(cache_dir=cache_dir)

        key1 = service._get_cache_key("https://example.com/audio.mp3")
        key2 = service._get_cache_key("https://example.com/audio.mp3")
        key3 = service._get_cache_key("https://example.com/other.mp3")

        assert key1 == key2  # Same URL should give same key
        assert key1 != key3  # Different URL should give different key

    def test_is_url_detection(self):
        """Test URL detection."""
        cache_dir = self._create_temp_dir()
        service = WaveformService(cache_dir=cache_dir)

        assert service._is_url("https://example.com/audio.mp3")
        assert service._is_url("http://example.com/audio.mp3")
        assert service._is_url("//example.com/audio.mp3")
        assert not service._is_url("/local/path/audio.mp3")
        assert not service._is_url("relative/path/audio.mp3")

    def test_waveform_cache_path_generation(self):
        """Test waveform cache path generation."""
        cache_dir = self._create_temp_dir()
        service = WaveformService(cache_dir=cache_dir)

        audio_path = "https://example.com/audio.mp3"
        cache_path = service._get_waveform_cache_path(audio_path)

        assert cache_path.startswith(cache_dir)
        assert cache_path.endswith(".dat")

    def test_cache_stats(self):
        """Test cache statistics retrieval."""
        cache_dir = self._create_temp_dir()
        service = WaveformService(
            cache_dir=cache_dir,
            cache_max_size=100
        )

        stats = service.get_cache_stats()

        assert 'cached_files' in stats
        assert 'max_files' in stats
        assert 'total_size_bytes' in stats
        assert 'total_size_mb' in stats
        assert 'cache_dir' in stats
        assert 'audiowaveform_available' in stats
        assert stats['max_files'] == 100
        assert stats['cache_dir'] == cache_dir

    def test_global_service_initialization(self):
        """Test global waveform service initialization."""
        cache_dir = self._create_temp_dir()

        service = init_waveform_service(
            cache_dir=cache_dir,
            look_ahead=5,
            cache_max_size=25
        )

        assert service is not None
        assert service.look_ahead == 5
        assert service.cache_max_size == 25

        # Should be accessible via getter
        retrieved = get_waveform_service()
        assert retrieved is service

    @patch('potato.server_utils.waveform_service.subprocess.run')
    def test_audiowaveform_check(self, mock_run):
        """Test audiowaveform availability check."""
        cache_dir = self._create_temp_dir()

        # Test when audiowaveform is available
        mock_run.return_value = MagicMock(returncode=0, stdout="audiowaveform 1.2.0")
        service = WaveformService(cache_dir=cache_dir)
        assert service._audiowaveform_available == True

        # Test when audiowaveform is not available
        mock_run.side_effect = FileNotFoundError()
        service2 = WaveformService(cache_dir=os.path.join(cache_dir, "sub"))
        assert service2._audiowaveform_available == False

    def test_clear_cache(self):
        """Test clearing the cache."""
        cache_dir = self._create_temp_dir()
        service = WaveformService(cache_dir=cache_dir)

        # Create some dummy cache files
        for i in range(3):
            dummy_path = os.path.join(cache_dir, f"dummy_{i}.dat")
            with open(dummy_path, 'w') as f:
                f.write("dummy data")
            service._cache_order[dummy_path] = True

        assert len(service._cache_order) == 3

        cleared = service.clear_cache()

        assert cleared == 3
        assert len(service._cache_order) == 0


class TestAudioAnnotationDataFormat:
    """Test audio annotation data format and persistence."""

    def test_segment_data_format(self):
        """Test expected segment data format."""
        segment_data = {
            "segments": [
                {
                    "id": "seg_1",
                    "start_time": 0.0,
                    "end_time": 12.5,
                    "label": "speech"
                },
                {
                    "id": "seg_2",
                    "start_time": 12.5,
                    "end_time": 30.0,
                    "label": "music"
                }
            ]
        }

        # Verify structure
        assert "segments" in segment_data
        assert len(segment_data["segments"]) == 2

        seg1 = segment_data["segments"][0]
        assert seg1["id"] == "seg_1"
        assert seg1["start_time"] == 0.0
        assert seg1["end_time"] == 12.5
        assert seg1["label"] == "speech"

    def test_segment_with_annotations_format(self):
        """Test segment data format with nested annotations (questions mode)."""
        segment_data = {
            "segments": [
                {
                    "id": "seg_1",
                    "start_time": 0.0,
                    "end_time": 12.5,
                    "label": "speech",
                    "annotations": {
                        "speaker_type": "host",
                        "audio_quality": "clear"
                    }
                }
            ]
        }

        seg = segment_data["segments"][0]
        assert "annotations" in seg
        assert seg["annotations"]["speaker_type"] == "host"
        assert seg["annotations"]["audio_quality"] == "clear"

    def test_segment_json_serialization(self):
        """Test that segment data can be serialized to JSON."""
        segment_data = {
            "segments": [
                {
                    "id": "seg_1",
                    "start_time": 0.0,
                    "end_time": 12.5,
                    "label": "speech"
                }
            ]
        }

        # Should serialize without error
        json_str = json.dumps(segment_data)
        assert len(json_str) > 0

        # Should deserialize back
        parsed = json.loads(json_str)
        assert parsed == segment_data

    def test_segment_time_precision(self):
        """Test that segment times can handle floating point precision."""
        segment_data = {
            "segments": [
                {
                    "id": "seg_1",
                    "start_time": 0.123456789,
                    "end_time": 12.987654321,
                    "label": "speech"
                }
            ]
        }

        json_str = json.dumps(segment_data)
        parsed = json.loads(json_str)

        # Python JSON preserves float precision
        assert parsed["segments"][0]["start_time"] == 0.123456789
        assert parsed["segments"][0]["end_time"] == 12.987654321


class TestAudioAnnotationModes:
    """Test different audio annotation modes."""

    def test_label_mode_schema_generation(self):
        """Test schema generation in label mode."""
        scheme = {
            "annotation_type": "audio_annotation",
            "name": "label_test",
            "description": "Test label mode",
            "mode": "label",
            "labels": [
                {"name": "speech"},
                {"name": "music"}
            ]
        }

        html, keybindings = schema_registry.generate(scheme)

        assert "label-group" in html
        assert "speech" in html
        assert "music" in html

    def test_both_mode_schema_generation(self):
        """Test schema generation in both mode."""
        scheme = {
            "annotation_type": "audio_annotation",
            "name": "both_test",
            "description": "Test both mode",
            "mode": "both",
            "labels": [
                {"name": "speech"},
                {"name": "music"}
            ],
            "segment_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "quality",
                    "labels": ["good", "bad"]
                }
            ]
        }

        html, keybindings = schema_registry.generate(scheme)

        assert "label-group" in html
        assert "speech" in html
        assert "segment-questions-panel" in html


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
