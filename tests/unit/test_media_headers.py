"""The content type Potato serves is Potato's decision, not the host's.

`send_from_directory` takes the type from the stdlib `mimetypes`, which reads
the host's `/etc/mime.types` at init. So the type served for the same file was a
property of the machine: a study working on a researcher's laptop could serve a
different type from the deployment host, and nothing recorded which was sent.

Two of the defaults on a common host are types Chrome declares unplayable.
Measured in a browser with `canPlayType`:

    audio/mp4a-latm   ""           <- was served for .m4a
    audio/mp4         "maybe"
    audio/x-flac      ""           <- was served for .flac
    audio/flac        "probably"

The bytes were always fine. `decodeAudioData` and `<audio src>` both sniff the
container and ignore the declared type, which is why playback worked and this
went unnoticed. What does not ignore it is anything that asks first: a
`<source type="...">` list, a capability check, a player choosing a fallback.

Separately, `Accept-Ranges` was absent from every 200. Range support existed
and worked -- a range request returned 206 with a correct `Content-Range` --
and was simply never advertised. Chrome's media element probes with a range
regardless, which is why seeking worked; anything that reads the header first
takes its absence at its word.
"""

import mimetypes

import pytest

from potato.media.mime import MEDIA_TYPES, register_media_mime_types


class TestTheTypesAreOurs:

    def setup_method(self):
        register_media_mime_types()

    @pytest.mark.parametrize("extension,expected", sorted(MEDIA_TYPES.items()))
    def test_the_registered_type_is_what_is_guessed(self, extension, expected):
        assert mimetypes.guess_type(f"clip{extension}")[0] == expected

    def test_m4a_is_not_the_type_chrome_refuses(self):
        assert mimetypes.guess_type("clip.m4a")[0] == "audio/mp4", (
            "audio/mp4a-latm is a type Chrome reports it cannot play")

    def test_flac_is_not_the_type_chrome_refuses(self):
        assert mimetypes.guess_type("clip.flac")[0] == "audio/flac", (
            "audio/x-flac is a type Chrome reports it cannot play")

    def test_opus_is_left_to_the_host(self):
        """`audio/ogg` is correct for Ogg-Opus and Chrome accepts it; pinning
        it would be churn."""
        assert ".opus" not in MEDIA_TYPES

    def test_registration_is_idempotent(self):
        register_media_mime_types()
        register_media_mime_types()
        assert mimetypes.guess_type("clip.m4a")[0] == "audio/mp4"

    def test_no_registered_type_is_an_x_prefixed_legacy(self):
        """`audio/x-flac` and friends are exactly the shape this fixes."""
        for extension, content_type in MEDIA_TYPES.items():
            assert "/x-" not in content_type, (
                f"{extension} is registered as {content_type}")

    def test_importing_the_package_registers_them(self):
        """Every path that serves a media file imports `potato.media`, and the
        type has to be pinned before the first response is built."""
        import importlib
        import sys

        mimetypes.add_type("audio/mp4a-latm", ".m4a", strict=True)
        assert mimetypes.guess_type("clip.m4a")[0] == "audio/mp4a-latm"

        for name in [n for n in sys.modules if n.startswith("potato.media")]:
            del sys.modules[name]
        importlib.import_module("potato.media")

        assert mimetypes.guess_type("clip.m4a")[0] == "audio/mp4", (
            "importing the media package did not pin the types, so whichever "
            "route answers first decides them")


class TestAcceptRangesIsAdvertised:
    """Driven through the real handler rather than by reading it."""

    def _serve(self, tmp_path, monkeypatch, name="clip.wav"):
        import flask

        from potato import routes

        media = tmp_path / "media"
        media.mkdir()
        (media / name).write_bytes(b"RIFF" + b"\0" * 512)

        monkeypatch.setattr(routes, "config",
                            {"task_dir": str(tmp_path),
                             "media_directory": "media"}, raising=False)
        app = flask.Flask(__name__)
        handler = getattr(routes.serve_media, "__wrapped__", routes.serve_media)
        with app.test_request_context(f"/media/{name}"):
            response = handler(name)
            # Read the body inside the context: a file-wrapper response is in
            # passthrough mode and cannot be read once it is gone.
            response.direct_passthrough = False
            response.body_bytes = response.get_data()
            return response

    def test_the_200_advertises_it(self, tmp_path, monkeypatch):
        response = self._serve(tmp_path, monkeypatch)
        assert response.status_code == 200
        assert response.headers.get("Accept-Ranges") == "bytes", (
            "range support existed, worked, and was never advertised, so a "
            "client that reads the header first is told there is none")

    def test_the_body_is_still_served(self, tmp_path, monkeypatch):
        """A header fix that broke the file would be its own bug."""
        response = self._serve(tmp_path, monkeypatch)
        assert response.body_bytes[:4] == b"RIFF"

    def test_an_m4a_gets_the_pinned_type(self, tmp_path, monkeypatch):
        response = self._serve(tmp_path, monkeypatch, name="clip.m4a")
        assert response.headers.get("Content-Type", "").startswith("audio/mp4")
