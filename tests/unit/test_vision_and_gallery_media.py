"""Two ways a media study looked fine and was not.

A VISION REQUEST THAT CARRIED NO IMAGE. A missing file, a moved media
directory or a mistyped `image_key` all produced a normal-shaped reply in the
normal time with the same JSON keys, because the code falls through to a
text-only request. Nothing said so: not the response, not the log.

The audit called this low severity because the model degraded gracefully -- a
missing image produced a generic hint rather than an invented shape -- and then
retracted the rating, correctly. That was one model at temperature 0 declining
to guess, a property of that model on that day. A different model would invent
a shape with the same confidence it invents everything else, and nothing
downstream could tell. The boolean is worth having precisely because the low
severity was an accident.

A GALLERY OF VIDEOS. `gallery` writes every url into an `<img>`. Measured on
one item holding three clips: three `<img>`, zero `<video>`, three broken
images, nothing in the log or on the page. It is the only display that takes a
LIST of urls, so it is where anyone with several media files per item starts --
and multi-camera robot demonstrations, side-by-side model rollouts and
frame-grid temporal segmentation are all lists of video.
"""

import re

import pytest

from potato.server_utils.displays.gallery_display import _is_video_url
from potato.server_utils.displays.registry import display_registry


def render_gallery(items, **options):
    field_config = {"type": "gallery", "key": "clips"}
    if options:
        field_config["display_options"] = options
    return display_registry.render("gallery", field_config, items)


class TestAGalleryOfVideos:

    CLIPS = [{"url": "/media/cam_front.mp4", "caption": "front"},
             {"url": "/media/cam_side.mp4"},
             {"url": "/media/cam_wrist.mp4"}]

    def test_videos_render_as_video_elements(self):
        html = render_gallery(self.CLIPS)
        assert len(re.findall(r"<video", html)) == 3, (
            "three clips rendered as three broken images, with nothing in the "
            "log and nothing on the page")

    def test_no_video_is_left_in_an_img(self):
        html = render_gallery(self.CLIPS)
        assert not re.search(r'<img[^>]*\.mp4', html)

    def test_every_source_survives(self):
        html = render_gallery(self.CLIPS)
        for clip in self.CLIPS:
            assert clip["url"] in html

    def test_captions_still_render(self):
        assert "front" in render_gallery(self.CLIPS)

    def test_the_player_has_controls(self):
        """A video with no controls is as unusable as a broken image."""
        assert "controls" in render_gallery(self.CLIPS)

    def test_images_are_unchanged(self):
        html = render_gallery([{"url": "/media/a.png"},
                               {"url": "/media/b.jpg"}])
        assert len(re.findall(r"<img", html)) == 2
        assert "<video" not in html

    def test_a_mixed_list_splits_correctly(self):
        html = render_gallery([{"url": "/media/clip.mp4"},
                               {"url": "/media/still.png"}])
        assert len(re.findall(r"<video", html)) == 1
        assert len(re.findall(r"<img", html)) == 1


class TestTheVideoTest:

    @pytest.mark.parametrize("url", [
        "/media/a.mp4", "/media/a.m4v", "/media/a.webm", "/media/a.ogv",
        "/media/a.MOV", "https://example.com/x.mp4",
        "/media/a.mp4?sig=abc", "/media/a.mp4#t=3",
    ])
    def test_it_recognises_a_video(self, url):
        assert _is_video_url(url) is True

    @pytest.mark.parametrize("url", [
        "/media/a.png", "/media/a.jpg", "/media/a.webp", "/media/a.svg",
        "/media/mp4.png", "", None, 3,
    ])
    def test_it_does_not_over_match(self, url):
        assert _is_video_url(url) is False


class TestTheVisionVerdict:

    def _manager(self, monkeypatch, supports_vision=True, loads=True):
        from potato.ai import ai_cache

        manager = ai_cache.AiCacheManager.__new__(ai_cache.AiCacheManager)
        manager.endpoint_supports_vision = supports_vision
        monkeypatch.setattr(
            ai_cache, "_get_image_data_from_url",
            lambda _url: (b"bytes" if loads else None))
        return manager

    def test_a_loadable_image_is_attached(self, monkeypatch):
        manager = self._manager(monkeypatch)
        data, attached = manager.resolve_vision_image("i1", "/media/a.png")
        assert data and attached is True
        assert manager.vision_verdict("i1") is True

    def test_a_missing_image_is_recorded_as_not_attached(self, monkeypatch):
        manager = self._manager(monkeypatch, loads=False)
        data, attached = manager.resolve_vision_image("i1", "/media/gone.png")
        assert data is None and attached is False
        assert manager.vision_verdict("i1") is False, (
            "a text-only fallback is indistinguishable from a vision answer "
            "in both shape and timing")

    def test_a_missing_image_says_so_in_the_log(self, monkeypatch, caplog):
        import logging

        manager = self._manager(monkeypatch, loads=False)
        with caplog.at_level(logging.WARNING):
            manager.resolve_vision_image("i1", "/media/gone.png")
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "TEXT ONLY" in message and "gone.png" in message

    def test_a_text_endpoint_records_nothing(self, monkeypatch):
        """Not a vision study; there is no verdict to give."""
        manager = self._manager(monkeypatch, supports_vision=False)
        data, attached = manager.resolve_vision_image("i1", "/media/a.png")
        assert data is None and attached is False
        assert manager.vision_verdict("i1") is None

    def test_an_item_with_no_image_records_nothing(self, monkeypatch):
        manager = self._manager(monkeypatch)
        assert manager.resolve_vision_image("i1", None) == (None, False)
        assert manager.vision_verdict("i1") is None

    def test_an_unseen_item_has_no_verdict(self, monkeypatch):
        assert self._manager(monkeypatch).vision_verdict("nope") is None

    def test_the_verdict_store_is_bounded(self, monkeypatch):
        manager = self._manager(monkeypatch)
        limit = manager._VISION_VERDICT_LIMIT
        for n in range(limit + 20):
            manager.resolve_vision_image(f"i{n}", "/media/a.png")
        assert len(manager._vision_verdicts) <= limit
        assert manager.vision_verdict(f"i{limit + 19}") is True

    def test_a_later_request_replaces_the_verdict(self, monkeypatch):
        """The image may be fixed between requests."""
        from potato.ai import ai_cache

        manager = self._manager(monkeypatch, loads=False)
        manager.resolve_vision_image("i1", "/media/gone.png")
        assert manager.vision_verdict("i1") is False
        monkeypatch.setattr(ai_cache, "_get_image_data_from_url",
                            lambda _url: b"bytes")
        manager.resolve_vision_image("i1", "/media/gone.png")
        assert manager.vision_verdict("i1") is True
