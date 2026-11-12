"""
`gallery` did not route bare filenames through `media_directory`; `image` did.

Audit 27. The same study, the same `media_directory`, the same bare filename:

    image display    "street1.png"            renders
    gallery display  {"url": "street1.png"}   <img src="street1.png"> -> 404

`/media/street1.png` serves; `/street1.png` does not. So the gallery showed the
right number of tiles with the right captions and two broken-image icons, which
an author reads as "my files are missing" rather than "this display type does
not use media_directory". The two types sit one row apart in the same
documentation table, and the docs tell authors to reference media by bare name.

`_resolve_media_references` is the chokepoint that turns bare names into
`/media/...`, and its own docstring said a gallery of dicts "is the display's
business, and each resolves its own nested references". No display can do that:
`render(field_config, data)` receives no project config, so `media_href` is not
reachable from one. The delegation described was not implementable, and neither
`gallery` nor `web_agent_trace` implemented it.

A gallery given a plain string, or a list of plain strings, was always resolved
-- the chokepoint handles those two shapes. Only the list-of-dicts form, which
is the one that carries captions, fell through.
"""

import os

import pytest

from potato.server_utils.instance_display import InstanceDisplayRenderer


@pytest.fixture
def study(tmp_path):
    """A project whose media directory holds real files.

    `media_href` rewrites a reference only when the file is actually there --
    inventing `/media/` for a name it cannot find would replace a working
    reference with a 404 -- so a fixture of bare names and no files resolves
    nothing and every assertion below would be vacuous.
    """
    media = tmp_path / "media"
    media.mkdir()
    for name in ("street1.png", "a.png", "b.png", "step_000.png"):
        (media / name).write_bytes(b"\x89PNG\r\n\x1a\n")
    config = {"task_dir": str(tmp_path), "media_directory": "media"}

    def resolve(field_type, data, field=None):
        renderer = InstanceDisplayRenderer(config)
        return renderer._resolve_media_references(
            field_type, data, field or {"key": "shots", "type": field_type})

    return resolve


class TestGalleryMediaPaths:

    def test_a_bare_filename_in_a_gallery_dict_is_routed(self, study):
        resolved = study("gallery", [{"url": "street1.png",
                                         "caption": "First"}])
        assert resolved[0]["url"] == "/media/street1.png", resolved
        assert resolved[0]["caption"] == "First", resolved

    def test_the_fallback_keys_are_routed_too(self, study):
        """`_normalize_items` reads `src` and `path` when `url` is absent, so
        resolving only `url` would leave those two shapes broken."""
        resolved = study("gallery", [{"src": "a.png"}, {"path": "b.png"}])
        assert resolved[0]["src"] == "/media/a.png", resolved
        assert resolved[1]["path"] == "/media/b.png", resolved

    def test_a_configured_url_key_is_routed(self, study):
        """`url_key` renames the field the display reads; the resolver has to
        read the same one or it resolves a key nothing renders."""
        field = {"key": "shots", "type": "gallery", "url_key": "u"}
        resolved = study("gallery", [{"u": "street1.png"}], field)
        assert resolved[0]["u"] == "/media/street1.png", resolved

    def test_the_shapes_that_already_worked_still_work(self, study):
        """Controls. A plain string and a list of strings were never broken."""
        assert study("gallery", "street1.png") == "/media/street1.png"
        assert study("gallery", ["a.png", "b.png"]) == [
            "/media/a.png", "/media/b.png"]

    def test_an_absolute_url_is_left_alone(self, study):
        """A gallery of remote images must not be rewritten into /media/."""
        resolved = study(
            "gallery", [{"url": "https://example.com/a.png"}])
        assert resolved[0]["url"] == "https://example.com/a.png", resolved

    def test_an_already_served_path_is_left_alone(self, study):
        resolved = study("gallery", [{"url": "/media/a.png"},
                                        {"url": "/static/b.png"}])
        assert resolved[0]["url"] == "/media/a.png", resolved
        assert resolved[1]["url"] == "/static/b.png", resolved

    def test_a_web_agent_trace_screenshot_is_routed(self, study):
        """The other type the docstring claimed resolved its own references.

        It reads `screenshot_url` off each step and emits it raw, so a trace
        whose screenshots live under `media_directory` showed broken images
        for exactly the same reason.
        """
        resolved = study("web_agent_trace",
                            [{"screenshot_url": "step_000.png", "action": "click"}])
        assert resolved[0]["screenshot_url"] == "/media/step_000.png", resolved
        assert resolved[0]["action"] == "click", resolved

    def test_a_type_that_is_not_a_media_reference_is_untouched(self, study):
        """The control that keeps this from resolving everything in sight."""
        assert study("text", [{"url": "street1.png"}]) == [
            {"url": "street1.png"}]
