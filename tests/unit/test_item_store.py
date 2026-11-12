"""
The item store: the accessor seam, and the paged backend behind it.

Two of these classes are guards rather than behaviour tests. `ItemStateManager`
used to *be* a dict that ~60 call sites indexed by name, which meant no backend
could ever be put behind it; `TestNothingReachesIntoTheContainer` fails the
build when a new direct reference appears, and `TestMutationSurvivesEviction`
pins the one property a paged store could plausibly break silently.
"""

import json
import os
import pathlib
import re

import pytest

from potato.item_state_management import Item
from potato.item_store import (
    MemoryItemStore,
    PagedItemStore,
    build_store,
)

REPO = pathlib.Path(__file__).resolve().parents[2]


def make_item(item_id, **data):
    return Item(item_id, dict(data))


# ---------------------------------------------------------------------------
# The protocol, held to identically by both backends
# ---------------------------------------------------------------------------

@pytest.fixture(params=["memory", "paged"])
def store(request, tmp_path):
    if request.param == "memory":
        return MemoryItemStore()
    return PagedItemStore(str(tmp_path / "items.sqlite"), cache_size=4)


class TestTheProtocol:
    def test_put_get_len_contains(self, store):
        store.put("a", make_item("a", text="alpha"))
        assert len(store) == 1
        assert "a" in store
        assert "b" not in store
        assert store.get("a").get_id() == "a"
        assert store.get("b") is None

    def test_payload_survives_the_round_trip(self, store):
        store.put("a", make_item("a", text="alpha", n=3, tags=["x", "y"]))
        assert store.get("a").get_data() == {"text": "alpha", "n": 3,
                                             "tags": ["x", "y"]}

    def test_ids_keep_insertion_order(self, store):
        for name in ("c", "a", "b"):
            store.put(name, make_item(name))
        assert store.ids() == ["c", "a", "b"]

    def test_iter_items_yields_every_item_in_order(self, store):
        for index in range(7):
            store.put(f"i{index}", make_item(f"i{index}", text=f"t{index}"))
        seen = [(iid, item.get_data()["text"]) for iid, item in store.iter_items()]
        assert seen == [(f"i{i}", f"t{i}") for i in range(7)]

    def test_pop_removes_the_item_and_its_payload(self, store):
        store.put("a", make_item("a", text="alpha"))
        assert store.pop("a").get_id() == "a"
        assert "a" not in store
        assert store.pop("a") is None

    def test_clear_empties_it(self, store):
        store.put("a", make_item("a"))
        store.clear()
        assert len(store) == 0
        assert store.ids() == []

    def test_get_returns_the_same_object_every_time(self, store):
        """
        Identity, not equality. `overlap_sampler.py:82` calls add_metadata on
        an item it was handed and expects the write to be visible to the next
        reader; a store that returned rebuilt copies would drop it.
        """
        store.put("a", make_item("a", text="alpha"))
        assert store.get("a") is store.get("a")


# ---------------------------------------------------------------------------
# What the paged store must not break
# ---------------------------------------------------------------------------

class TestMutationSurvivesEviction:
    @pytest.fixture
    def paged(self, tmp_path):
        # Two payloads resident at a time, so a third put evicts the first.
        return PagedItemStore(str(tmp_path / "items.sqlite"), cache_size=2)

    def test_metadata_written_through_the_object_survives(self, paged):
        """
        The failure this design exists to prevent: metadata is mutated on the
        live object by the overlap sampler, the automation engine and adaptive
        boost. If eviction rebuilt items, those writes would vanish under
        memory pressure — intermittently, and only in production.
        """
        for index in range(5):
            paged.put(f"i{index}", make_item(f"i{index}", text="x" * 50))
        paged.get("i0").add_metadata("required_annotations", 5)

        # Push i0's payload out of the cache several times over.
        for index in range(5, 20):
            paged.put(f"i{index}", make_item(f"i{index}", text="y" * 50))

        assert paged.get("i0").get_metadata("required_annotations") == 5

    def test_the_payload_is_still_readable_after_eviction(self, paged):
        paged.put("i0", make_item("i0", text="the original"))
        for index in range(1, 20):
            paged.put(f"i{index}", make_item(f"i{index}", text="filler"))
        assert paged.get("i0").get_data() == {"text": "the original"}

    def test_only_the_cache_size_of_payloads_is_resident(self, paged):
        for index in range(20):
            paged.put(f"i{index}", make_item(f"i{index}", text="x" * 50))
        assert len(paged._payloads) <= 2
        assert len(paged._items) == 20     # the Item objects stay

    def test_updating_a_payload_writes_through(self, paged):
        paged.put("a", make_item("a", text="before"))
        paged.get("a").item_data = {"text": "after"}
        for index in range(10):
            paged.put(f"f{index}", make_item(f"f{index}", text="filler"))
        assert paged.get("a").get_data() == {"text": "after"}

    def test_dynamic_field_access_still_works_after_eviction(self, paged):
        """
        F-029: Jinja reaches data fields as attributes (`instance_obj.gifs[0]`).
        That path goes through __getattr__, which must fault the payload in.
        """
        paged.put("a", make_item("a", gifs=["one.gif", "two.gif"]))
        for index in range(10):
            paged.put(f"f{index}", make_item(f"f{index}", text="filler"))
        assert paged.get("a").gifs[0] == "one.gif"

    def test_an_absent_field_still_raises_attribute_error(self, paged):
        paged.put("a", make_item("a", text="x"))
        with pytest.raises(AttributeError):
            paged.get("a").not_a_field


class TestTheCacheFileIsACache:
    def test_a_stale_file_is_discarded_on_open(self, tmp_path):
        """
        The file describes a corpus that may no longer exist. Serving a payload
        belonging to a deleted item is worse than the cost of a rebuild.
        """
        path = str(tmp_path / "items.sqlite")
        first = PagedItemStore(path)
        first.put("gone", make_item("gone", text="from the last run"))
        assert os.path.exists(path)

        second = PagedItemStore(path)
        assert len(second) == 0
        assert second.get("gone") is None


class TestBuildStore:
    def test_memory_is_the_default(self):
        assert isinstance(build_store({}), MemoryItemStore)
        assert isinstance(build_store(None), MemoryItemStore)

    def test_paged_is_opt_in(self, tmp_path):
        store = build_store({"item_store": {
            "backend": "paged", "path": str(tmp_path / "c.sqlite"),
            "cache_size": 16}})
        assert isinstance(store, PagedItemStore)
        assert store.cache_size == 16

    def test_paged_defaults_its_path_into_the_output_dir(self, tmp_path):
        store = build_store({"item_store": {"backend": "paged"},
                             "output_annotation_dir": str(tmp_path)})
        assert store.path == os.path.join(str(tmp_path), ".item_cache.sqlite")

    def test_an_unknown_backend_falls_back_rather_than_refusing_to_start(self):
        """A performance setting must not be able to stop the server."""
        assert isinstance(build_store({"item_store": {"backend": "nonsense"}}),
                          MemoryItemStore)


# ---------------------------------------------------------------------------
# The manager's accessors
# ---------------------------------------------------------------------------

class TestManagerAccessors:
    @pytest.fixture
    def manager(self):
        from potato.item_state_management import ItemStateManager

        ism = ItemStateManager({})
        for index in range(4):
            ism.add_item(f"i{index}", {"text": f"item {index}"})
        return ism

    def test_get_instance_ids(self, manager):
        assert manager.get_instance_ids() == ["i0", "i1", "i2", "i3"]

    def test_get_item_raises_for_a_missing_id(self, manager):
        assert manager.get_item("i1").get_id() == "i1"
        with pytest.raises(KeyError):
            manager.get_item("nope")

    def test_find_item_returns_none_for_a_missing_id(self, manager):
        assert manager.find_item("i1").get_id() == "i1"
        assert manager.find_item("nope") is None

    def test_iter_items_is_lazy(self, manager):
        """A generator, not a list: that is what a paged store needs."""
        import types

        stream = manager.iter_items()
        assert isinstance(stream, types.GeneratorType)
        assert [iid for iid, _ in stream] == ["i0", "i1", "i2", "i3"]

    def test_item_count(self, manager):
        assert manager.item_count() == 4

    def test_has_item(self, manager):
        assert manager.has_item("i2")
        assert not manager.has_item("nope")

    def test_the_deprecated_mapping_is_a_live_view_not_a_copy(self, manager):
        """
        Third-party configs and forks index it. Returning a rebuilt copy would
        make writes through it disappear, which is worse than keeping it.
        """
        manager.instance_id_to_instance["i0"].add_metadata("k", "v")
        assert manager.get_item("i0").get_metadata("k") == "v"

    def test_iterating_while_items_are_added_does_not_raise(self, manager):
        """
        The directory watcher adds items from a poll thread while reports
        iterate. Iterating a plain dict during mutation raises RuntimeError.
        """
        seen = []
        for index, (iid, _item) in enumerate(manager.iter_items()):
            seen.append(iid)
            if index == 0:
                manager.add_item("late", {"text": "arrived mid-iteration"})
        assert "i0" in seen


class TestManagerWithAPagedStore:
    def test_the_manager_works_end_to_end(self, tmp_path):
        from potato.item_state_management import ItemStateManager

        ism = ItemStateManager({
            "item_store": {"backend": "paged", "cache_size": 2,
                           "path": str(tmp_path / "c.sqlite")}})
        for index in range(10):
            ism.add_item(f"i{index}", {"text": f"item {index}"})

        assert ism.item_count() == 10
        assert ism.get_item("i0").get_data() == {"text": "item 0"}
        assert [iid for iid, _ in ism.iter_items()] == [f"i{i}" for i in range(10)]
        assert ism.update_item("i0", {"text": "rewritten"})
        assert ism.get_item("i0").get_data() == {"text": "rewritten"}


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------

class TestItemStaysCheap:
    """
    Three unconditional empty dicts per Item were half the resident cost of an
    item whose payload had been paged out — measured, see
    ``scripts/benchmark_item_store.py``. They are now created on first use, and
    this is what stops that regressing.
    """

    def test_an_untouched_item_has_no_dicts(self):
        item = make_item("a", text="x")
        for slot in ("_metadata", "_labels", "_span_annotations"):
            assert item.__dict__[slot] is None, slot

    def test_get_metadata_does_not_create_the_dict(self):
        """
        Every assignment strategy calls this on every candidate on every
        request. If it materialized, the first pass would undo the laziness for
        the whole corpus.
        """
        item = make_item("a", text="x")
        assert item.get_metadata("anything") is None
        assert item.__dict__["_metadata"] is None

    def test_reading_metadata_gives_a_dict_that_accepts_writes(self):
        """
        `automation/actions.py:48` mutates what it is handed. A property that
        returned a fresh dict per call would accept the write and drop it.
        """
        item = make_item("a", text="x")
        item.metadata["triage_priority"] = 7
        assert item.get_metadata("triage_priority") == 7
        assert item.metadata is item.metadata

    def test_add_metadata_still_works(self):
        item = make_item("a", text="x")
        item.add_metadata("k", "v")
        assert item.get_metadata("k") == "v"

    def test_the_vestigial_dicts_still_behave_like_dicts(self):
        """Kept for forks: nothing in-tree reads them, but they must not error."""
        item = make_item("a", text="x")
        assert item.labels == {}
        assert item.span_annotations == {}
        item.labels["x"] = 1
        assert item.labels == {"x": 1}

    def test_str_does_not_materialize_metadata(self):
        item = make_item("a", text="x")
        assert "metadata:{}" in str(item)
        assert item.__dict__["_metadata"] is None


class TestNothingReachesIntoTheContainer:
    """
    `instance_id_to_instance` is deprecated. It still works, but a new direct
    reference re-creates the coupling that made a paged backend impossible in
    the first place, so it fails here rather than being noticed a year later.
    """

    #: Where the deprecated name may legitimately appear: the property that
    #: defines it, the store that backs it, and prose about it.
    ALLOWED = {
        "potato/item_state_management.py",
        "potato/item_store.py",
    }

    def test_no_production_module_indexes_the_mapping(self):
        pattern = re.compile(r"instance_id_to_instance")
        offenders = []
        for path in (REPO / "potato").rglob("*.py"):
            relative = str(path.relative_to(REPO))
            if relative in self.ALLOWED:
                continue
            for number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), start=1):
                if not pattern.search(line):
                    continue
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue  # a comment naming it is not a use of it
                offenders.append(f"{relative}:{number}: {stripped}")
        assert not offenders, (
            "use the accessors (get_item / find_item / iter_items / "
            "get_instance_ids / has_item) instead:\n  " + "\n  ".join(offenders))

    def test_the_guard_would_catch_a_real_use(self):
        """Proof it is not matching nothing: the allowed files do contain it."""
        source = (REPO / "potato/item_state_management.py").read_text(
            encoding="utf-8")
        assert "instance_id_to_instance" in source
