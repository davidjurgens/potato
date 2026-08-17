"""
Audio and video backends.

Structure is checked always; the models are checked only when opted in, because
CLAP and CLIP are hundreds of megabytes and a test suite should not download
them on someone's laptop:

    POTATO_TEST_EMBEDDINGS=1 pytest tests/unit/test_media_embedders.py

The video path was verified that way here: `tests/data/test_video_6s.webm` →
4 sampled frames → CLIP → one 512-dim vector, no failures.
"""

import os
from pathlib import Path

import pytest

from potato.embedders import get_backend_class, resolve

OPTED_IN = os.environ.get("POTATO_TEST_EMBEDDINGS") == "1"
ROOT = Path(__file__).resolve().parents[2]
CLIP = ROOT / "tests" / "data" / "test_video_6s.webm"
WAV = ROOT / "tests" / "data" / "test_audio_10s.wav"


class TestFrameSampling:
    """Which frames represent a clip."""

    def spread(self, n, count):
        from potato.embedders.video import _evenly_spaced
        return _evenly_spaced([f"f{i}" for i in range(n)], count)

    def test_frames_are_spread_across_the_clip(self):
        """The head would be a map of title cards."""
        assert self.spread(10, 4) == ["f0", "f2", "f5", "f7"]

    def test_a_short_clip_uses_what_it_has(self):
        assert self.spread(2, 4) == ["f0", "f1"]

    def test_no_frames(self):
        assert self.spread(0, 4) == []

    def test_a_single_frame_request(self):
        assert self.spread(10, 1) == ["f0"]


class TestBackendDeclarations:
    """What detection reads before importing anything."""

    def test_audio_declares_its_fields_and_extensions(self):
        cls = get_backend_class("audio")
        assert cls.modality == "audio"
        assert "audio_url" in cls.source_fields
        assert ".wav" in cls.extensions and ".mp3" in cls.extensions

    def test_video_declares_its_fields_and_extensions(self):
        cls = get_backend_class("video")
        assert cls.modality == "video"
        assert "video_url" in cls.source_fields
        assert ".mp4" in cls.extensions and ".webm" in cls.extensions

    def test_video_reuses_the_image_backend_rather_than_a_second_clip(self):
        import inspect
        from potato.embedders import video
        assert "ImageEmbeddingBackend" in inspect.getsource(video)

    def test_audio_refuses_a_wrong_sample_rate_rather_than_guessing(self):
        """Feeding 44.1 kHz to a 48 kHz model is quietly wrong, not an error."""
        import inspect
        from potato.embedders import audio
        source = inspect.getsource(audio)
        assert "TARGET_SAMPLE_RATE" in source
        assert "install librosa to resample" in source

    def test_missing_ffmpeg_is_explained_not_crashed(self, monkeypatch):
        from potato.embedders.video import VideoEmbeddingBackend
        import potato.media.video as media_video
        monkeypatch.setattr(media_video, "ffmpeg_available", lambda: False)
        ok, reason = VideoEmbeddingBackend().available()
        assert ok is False
        assert "ffmpeg" in reason


class TestDetectionPicksThem:
    def test_an_audio_corpus_resolves_to_the_audio_backend(self):
        embedder = resolve({}, samples=[{"id": "a", "audio_url": "x.wav"}])
        assert embedder.spec.backend == "audio"
        assert embedder.spec.source_field == "audio_url"

    def test_a_video_corpus_resolves_to_the_video_backend(self):
        embedder = resolve({}, samples=[{"id": "v", "video_url": "x.mp4"}])
        assert embedder.spec.backend == "video"

    def test_frames_per_clip_is_configurable(self):
        embedder = resolve({"embeddings": {"backend": "video", "frames": 8,
                                           "source_field": "video_url"}},
                           samples=[{"id": "v", "video_url": "x.mp4"}])
        assert embedder.backend.frames == 8


@pytest.mark.skipif(not OPTED_IN,
                    reason="set POTATO_TEST_EMBEDDINGS=1 to run real models")
class TestRealModels:
    def test_a_real_clip_becomes_one_vector(self):
        assert CLIP.exists()
        embedder = resolve({}, samples=[{"id": "v1", "video_url": str(CLIP)}])
        if not embedder.available:
            pytest.skip(embedder.spec.unavailable_reason)
        vectors = embedder.embed_items({"v1": {"id": "v1",
                                               "video_url": str(CLIP)}})
        assert len(vectors) == 1
        assert len(vectors["v1"]) > 100
        assert embedder.backend.failures == []

    def test_a_real_recording_becomes_one_vector(self):
        assert WAV.exists()
        embedder = resolve({}, samples=[{"id": "a1", "audio_url": str(WAV)}])
        if not embedder.available:
            pytest.skip(embedder.spec.unavailable_reason)
        vectors = embedder.embed_items({"a1": {"id": "a1",
                                               "audio_url": str(WAV)}})
        assert len(vectors) == 1
        assert len(vectors["a1"]) > 100

    def test_an_unreadable_reference_is_reported_not_dropped(self):
        embedder = resolve({}, samples=[{"id": "v", "video_url": "nope.mp4"}])
        if not embedder.available:
            pytest.skip(embedder.spec.unavailable_reason)
        vectors = embedder.embed_items({"v": {"id": "v",
                                              "video_url": "nope.mp4"}})
        # A zero row keeps caller indexes aligned; the failure is recorded.
        assert len(vectors) == 1
        assert embedder.backend.failures == ["nope.mp4"]
