"""Server-side waveforms accept the path the audio widget puts on the page.

`audiowaveform` was installed, the boot log said `audiowaveform_available=True`,
and twelve clips across WAV/MP3/FLAC/OGG/Opus/M4A all returned
`use_client_fallback: true` in 0.00 seconds with an empty cache directory. The
binary was never invoked. The only sign was one line per request:

    Refusing waveform request for /media/mono44.wav: outside the task directory

`/media/clip.wav` is a SERVER URL, not a filesystem path. It is what the audio
widget writes into the page and what `media_directory` documents. But
`os.path.isabs()` is true for it, so realpath resolved it against the host root
and the containment check refused it.

The containment rule was right. The path shape was never checked against it,
which is the class of thing a security fix introduces quietly -- so the
traversal cases are pinned here next to the working one, and a fix that opened
the door would fail this file rather than pass it.
"""

import math
import os
import struct
import wave

import pytest


@pytest.fixture
def media_project(tmp_path):
    """A task directory with a media/ folder and one real WAV in it."""
    media = tmp_path / "media"
    media.mkdir()
    clip = media / "clip.wav"
    with wave.open(str(clip), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"".join(
            struct.pack("<h", int(9000 * math.sin(i / 12.0)))
            for i in range(8000)))

    outside = tmp_path.parent / "outside.wav"
    outside.write_bytes(clip.read_bytes())

    from potato.server_utils import config_module

    saved = dict(config_module.config)
    config_module.config.clear()
    config_module.config.update({"task_dir": str(tmp_path),
                                 "media_directory": "media"})
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path, clip, outside
    finally:
        os.chdir(cwd)
        config_module.config.clear()
        config_module.config.update(saved)


def service(tmp_path):
    from potato.server_utils.waveform_service import WaveformService

    return WaveformService(cache_dir=str(tmp_path / "waveform_cache"),
                           task_dir=str(tmp_path))


class TestTheDocumentedPathShapeResolves:

    def test_a_media_url_resolves_to_the_file(self, media_project):
        tmp_path, clip, _outside = media_project
        resolved = service(tmp_path)._resolve_local_media("/media/clip.wav")
        assert resolved and os.path.realpath(resolved) == os.path.realpath(str(clip)), (
            "the one path shape the media system produces was refused, so "
            "every waveform request fell through to browser decoding")

    def test_the_relative_spelling_resolves_too(self, media_project):
        tmp_path, clip, _outside = media_project
        resolved = service(tmp_path)._resolve_local_media("media/clip.wav")
        assert resolved and os.path.realpath(resolved) == os.path.realpath(str(clip))

    def test_a_plain_relative_path_still_resolves(self, media_project):
        """The pre-existing behaviour for a path relative to the task dir."""
        tmp_path, clip, _outside = media_project
        assert service(tmp_path)._resolve_local_media("media/clip.wav") is not None


class TestContainmentIsUnchanged:
    """The refusal was correct for everything except the documented shape."""

    @pytest.mark.parametrize("path", [
        "/etc/passwd",
        "/media/../../etc/passwd",
        "../outside.wav",
        "media/../../outside.wav",
    ])
    def test_a_path_leaving_the_project_is_refused(self, media_project, path):
        tmp_path, _clip, _outside = media_project
        assert service(tmp_path)._resolve_local_media(path) is None, (
            f"{path!r} escaped the project; the media-URL branch must not "
            "widen what the containment rule accepts")

    def test_a_missing_file_inside_the_project_is_refused(self, media_project):
        tmp_path, _clip, _outside = media_project
        assert service(tmp_path)._resolve_local_media("/media/nope.wav") is None


class TestTheWaveformIsActuallyGenerated:
    """Resolving the path is not the same as producing a waveform.

    Skipped where `audiowaveform` is absent, because then the client fallback
    is the correct answer and there is nothing to measure.
    """

    def test_the_binary_runs_and_the_cache_fills(self, media_project):
        tmp_path, _clip, _outside = media_project
        svc = service(tmp_path)
        if not svc.is_available:
            pytest.skip("audiowaveform is not installed")

        path = svc.get_waveform_path("/media/clip.wav")
        assert path, "no waveform was produced for a resolvable local file"
        assert os.path.isfile(path)
        assert os.path.getsize(path) > 0, (
            "an empty waveform file is the same silence as no file")
        assert os.listdir(tmp_path / "waveform_cache"), (
            "the cache directory stayed empty, which is how this was measured "
            "in the first place")


class TestBothWaveformRoutesWorkForTheDocumentedLayout:
    """Audio and video waveforms are two routes over one service, and both
    were non-functional for a `media_directory` project by two unrelated
    causes: the audio one refused `/media/...` as a traversal attempt, the
    video one called a method that does not exist.
    """

    def test_the_service_has_no_generate_waveform(self):
        """The name the video route called. Asserted as absence rather than
        adding the method, because `get_waveform_url` is the one that works
        and two spellings would drift."""
        from potato.server_utils.waveform_service import WaveformService

        assert not hasattr(WaveformService, "generate_waveform")

    def test_the_video_route_calls_something_that_exists(self):
        """Driven through the route's own module so a rename is caught."""
        import inspect

        from potato import routes

        source = inspect.getsource(routes.generate_video_waveform)
        called = [name for name in ("get_waveform_url", "get_waveform_path",
                                    "generate_waveform")
                  if f"waveform_service.{name}(" in source]
        assert called, "the route calls no waveform method at all"
        from potato.server_utils.waveform_service import WaveformService

        for name in called:
            assert hasattr(WaveformService, name), (
                f"the video route calls waveform_service.{name}(), which does "
                "not exist, so every request 500s")

    def test_a_video_url_produces_a_waveform(self, media_project):
        """audiowaveform reads the audio track out of a container directly, so
        the video path is the audio path with a different extension."""
        tmp_path, _clip, _outside = media_project
        svc = service(tmp_path)
        if not svc.is_available:
            pytest.skip("audiowaveform is not installed")
        assert svc.get_waveform_url("/media/clip.wav") is not None

    def test_a_failure_is_not_dressed_as_a_fallback(self, monkeypatch):
        """`use_client_fallback: True` on a 500 reads as routine degradation,
        which is how a route that had never worked went unnoticed.

        Driven by making the service raise and reading the real response, not
        by grepping the handler.
        """
        import flask

        from potato import routes

        def boom():
            raise RuntimeError("audiowaveform exploded")

        monkeypatch.setattr(
            "potato.server_utils.waveform_service.get_waveform_service", boom)

        app = flask.Flask(__name__)
        handler = getattr(routes.generate_video_waveform, "__wrapped__",
                          routes.generate_video_waveform)
        with app.test_request_context(json={"video_url": "/media/clip.wav"}):
            response = handler()

        body, status = response if isinstance(response, tuple) else (response, 200)
        payload = body.get_json()
        assert status == 500, "a broken service answered as though it worked"
        assert payload.get("use_client_fallback") is not True, (
            "the 500 still tells the client this was a normal fallback")
        assert "exploded" in str(payload.get("error", "")), (
            "the body has to say what broke")
