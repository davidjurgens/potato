"""
Next-instance media prefetch.

Annotators leave tools over waiting for the next image to load. Potato had no
prefetch at all, and because navigation is a full page reload, a JS-held
prefetch would be discarded — the hint has to reach the HTTP cache.

These tests assert *which* URLs are emitted, not merely that some were: an
implementation that prefetched the instance already on screen would look
identical to a shape-only test and would be entirely useless.
"""

from types import SimpleNamespace

import pytest

from potato import flask_server
from potato.flask_server import _looks_prefetchable, _next_instance_prefetch_urls


class FakeItem:
    def __init__(self, data):
        self._data = data

    def get_data(self):
        return self._data


class FakeISM:
    def __init__(self, items):
        self.items = items

    def has_item(self, item_id):
        return item_id in self.items

    def get_item(self, item_id):
        return self.items[item_id]


@pytest.fixture
def three_instances(monkeypatch):
    items = {
        "a": FakeItem({"id": "a", "image": "/media/a.png", "text": "first"}),
        "b": FakeItem({"id": "b", "image": "/media/b.png", "text": "second"}),
        "c": FakeItem({"id": "c", "image": "/media/c.png", "text": "third"}),
    }
    monkeypatch.setattr(flask_server, "get_item_state_manager", lambda: FakeISM(items))
    return items


def _state(index, ordering=("a", "b", "c")):
    return SimpleNamespace(instance_id_ordering=list(ordering),
                           current_instance_index=index)


class TestPicksTheNextInstance:

    def test_prefetches_the_following_instance_not_the_current_one(self, three_instances):
        urls = _next_instance_prefetch_urls(_state(0))
        assert urls == ["/media/b.png"], (
            "On instance 'a' the prefetch must target 'b'. Returning '/media/a.png' "
            "would prefetch what the browser already has and save nothing."
        )

    def test_advances_with_the_cursor(self, three_instances):
        assert _next_instance_prefetch_urls(_state(1)) == ["/media/c.png"]

    def test_last_instance_prefetches_nothing(self, three_instances):
        assert _next_instance_prefetch_urls(_state(2)) == []

    def test_unstarted_cursor_prefetches_nothing(self, three_instances):
        assert _next_instance_prefetch_urls(_state(-1)) == []

    def test_missing_next_item_is_survivable(self, three_instances, monkeypatch):
        """A dynamically injected id can be in the ordering but not the store."""
        state = _state(0, ordering=("a", "ghost"))
        assert _next_instance_prefetch_urls(state) == []


class TestWhatCountsAsPrefetchable:

    @pytest.mark.parametrize("value", [
        "/media/x.png", "/media/x.PNG", "/media/clip.mp4", "/media/doc.pdf",
        "https://example.org/a.jpg", "/media/x.png?v=2",
    ])
    def test_media_urls_qualify(self, value):
        assert _looks_prefetchable(value)

    @pytest.mark.parametrize("value", [
        "just some annotation text", "", None, 42, {"nested": "dict"},
        "notaurl.png",                    # no scheme and not root-relative
        "/media/notes.txt",               # text arrives in the page already
        "/media/archive.zip",
    ])
    def test_everything_else_does_not(self, value):
        assert not _looks_prefetchable(value)

    def test_url_count_is_capped(self, monkeypatch):
        many = {f"f{i}": f"/media/{i}.png" for i in range(50)}
        items = {"a": FakeItem({}), "b": FakeItem(many)}
        monkeypatch.setattr(flask_server, "get_item_state_manager",
                            lambda: FakeISM(items))
        urls = _next_instance_prefetch_urls(_state(0, ordering=("a", "b")))
        assert len(urls) == flask_server._MAX_PREFETCH_URLS, (
            "A wide table must not queue 50 prefetches and starve the requests "
            "the annotator is actually waiting on."
        )

    def test_duplicates_are_collapsed(self, monkeypatch):
        items = {
            "a": FakeItem({}),
            "b": FakeItem({"one": "/media/same.png", "two": "/media/same.png"}),
        }
        monkeypatch.setattr(flask_server, "get_item_state_manager",
                            lambda: FakeISM(items))
        assert _next_instance_prefetch_urls(_state(0, ordering=("a", "b"))) == [
            "/media/same.png"
        ]
