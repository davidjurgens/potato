"""
Option-highlight prefetch makes no model calls for items the annotator will
see unassisted (ai_support.holdout or a blind engine request): the
/api/option_highlights/prefetch route passes a `skip` test, and those items
are passed over.
"""

import threading

import pytest

import potato.ai.ai_cache as ai_cache


class Executor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, instance_id, annotation_id):
        self.calls.append(instance_id)

        class Future:
            def add_done_callback(self, cb):
                pass
        return Future()


@pytest.fixture
def manager(monkeypatch):
    cls = next(v for v in vars(ai_cache).values()
               if isinstance(v, type) and hasattr(v, "start_option_highlight_prefetch"))
    m = cls.__new__(cls)
    m.option_highlighting_enabled = True
    m.disk_cache_enabled = True
    m.option_highlighting_prefetch_count = 10
    m.lock = threading.RLock()
    m.in_progress = {}
    m.executor = Executor()
    m.get_from_cache = lambda key: None
    m.is_option_highlighting_enabled_for_scheme = lambda annotation_id: True
    monkeypatch.setattr(ai_cache, "get_item_state_manager", lambda: None)
    monkeypatch.setitem(ai_cache.config, "annotation_schemes",
                        [{"name": "s", "annotation_type": "radio"}])
    return m


def test_held_out_items_get_no_prefetch(manager):
    manager.start_option_highlight_prefetch(0, 4, instance_ids=["a", "b", "c", "d"],
                                            skip=lambda iid: iid in {"b", "d"})
    assert manager.executor.calls == ["a", "c"]


def test_without_a_skip_every_item_is_prefetched(manager):
    manager.start_option_highlight_prefetch(0, 3, instance_ids=["a", "b", "c"])
    assert manager.executor.calls == ["a", "b", "c"]
