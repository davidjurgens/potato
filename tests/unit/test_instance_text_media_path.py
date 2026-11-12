"""
Unit tests for the instance-text media-path detection used to decide whether the
top-of-page header should show the item text or hide it (because it's just the
media file path). See flask_server._compute_instance_text_is_media_path.
"""

import pytest

from potato.flask_server import (
    _looks_like_media_path,
    _compute_instance_text_is_media_path,
)


class TestLooksLikeMediaPath:
    @pytest.mark.parametrize("value", [
        "data/files/clip001.wav",
        "media/clip001.wav",
        "https://example.com/a.mp4",
        "http://host/x.webm",
        "/test-audio/test_audio_10s.mp3",
        "clip.mp3",
        "song.flac",
        "movie.mkv",
    ])
    def test_paths_detected(self, value):
        assert _looks_like_media_path(value) is True

    @pytest.mark.parametrize("value", [
        "Rate this clip's tone",
        "The quick brown fox jumps over the lazy dog.",
        "Speaker A greets Speaker B",
        "",
        "   ",
        None,
        42,
    ])
    def test_prose_and_junk_not_detected(self, value):
        assert _looks_like_media_path(value) is False


class TestComputeInstanceTextIsMediaPath:
    def _audio_scheme(self, **extra):
        base = {"annotation_type": "audio_annotation", "name": "a", "source_field": "audio_url"}
        base.update(extra)
        return [base]

    def test_no_media_scheme_returns_false(self):
        schemes = [{"annotation_type": "radio", "name": "r"}]
        assert _compute_instance_text_is_media_path(schemes, {"text": "hello"}, "hello") is False

    def test_displayed_text_equals_source_field_value(self):
        schemes = self._audio_scheme()
        item = {"audio_url": "clips/a001.mp3"}
        assert _compute_instance_text_is_media_path(schemes, item, "clips/a001.mp3") is True

    def test_displayed_text_looks_like_path(self):
        schemes = self._audio_scheme()
        item = {"audio_url": "clips/a001.mp3"}
        # displayed text differs from source but still a bare path
        assert _compute_instance_text_is_media_path(schemes, item, "other/dir/x.wav") is True

    def test_real_prompt_is_shown(self):
        schemes = self._audio_scheme()
        item = {"audio_url": "clips/a001.mp3"}
        assert _compute_instance_text_is_media_path(
            schemes, item, "Rate the emotional tone of this clip."
        ) is False

    def test_empty_text_hidden(self):
        schemes = self._audio_scheme()
        assert _compute_instance_text_is_media_path(schemes, {"audio_url": "x.mp3"}, "") is True

    def test_video_key_source_field(self):
        schemes = [{"annotation_type": "temporal_grounding", "name": "tg", "video_key": "vid"}]
        item = {"vid": "videos/clip.mp4"}
        assert _compute_instance_text_is_media_path(schemes, item, "videos/clip.mp4") is True

    def test_tiered_video_media(self):
        schemes = [{
            "annotation_type": "tiered_annotation", "name": "t",
            "media_type": "video", "source_field": "video_url",
        }]
        item = {"video_url": "v/a.webm"}
        assert _compute_instance_text_is_media_path(schemes, item, "v/a.webm") is True
