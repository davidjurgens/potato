"""A watched directory feeds the annotators it already has, and is searchable.

Measured by the audit on a live server: `b1` annotated batch1, batch2 arrived
("Directory scan: 4 instances added"), `b1` returning got nothing and a
brand-new `b2` took all four. `b1` was not capped -- `max_assignments: -1` --
and their phase on disk was still `['annotation', None]`. Their ordering was
frozen and nothing topped it up, so what they saw was the Complete page with a
completion code, on a study that is by configuration still ingesting.

The one case that worked told us the rule: a user holding ZERO items does get
assigned on a later visit. So the condition was "assign when the user holds
nothing" rather than "assign when there is work and they have none left".

Alongside it, two things found while reproducing:

* `FTS5 indexed 0 instances` fires before the directory load, and the
  watcher's later additions did not index either, so /admin/api/search
  answered `{"count": 0}` on a corpus where every item matched -- and the
  curation catalog is built on that same index.
* the watcher's `.json` parser read line by line, so a pretty-printed JSON
  array (what everyone writes, and what `data_files` has always accepted)
  failed on line 1 and the study loaded zero instances from a directory of
  perfectly good files.
"""

import json
import os
import tempfile

import pytest


class TestTheWatcherReadsBothJsonShapes:
    """`data_files` accepts an array or JSONL. The watcher must not disagree
    with it about what a `.json` file is."""

    def _parse(self, body):
        from potato.directory_watcher import DirectoryWatcher

        with tempfile.TemporaryDirectory() as d:
            incoming = os.path.join(d, "incoming")
            os.makedirs(incoming)
            path = os.path.join(incoming, "batch.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
            watcher = DirectoryWatcher.__new__(DirectoryWatcher)
            watcher.encoding = "utf-8"
            return watcher._parse_json_file(path)

    def test_a_pretty_printed_array_loads(self):
        body = json.dumps(
            [{"id": "w0", "text": "alpha"}, {"id": "w1", "text": "bravo"}],
            indent=2)
        assert [i["id"] for i in self._parse(body)] == ["w0", "w1"], (
            "a pretty-printed array failed on line 1 and the study loaded "
            "zero instances from a directory of good files")

    def test_a_single_line_array_still_loads(self):
        body = '[{"id": "w0", "text": "alpha"}, {"id": "w1", "text": "bravo"}]'
        assert [i["id"] for i in self._parse(body)] == ["w0", "w1"]

    def test_jsonl_still_loads(self):
        body = '{"id": "w0", "text": "alpha"}\n{"id": "w1", "text": "bravo"}\n'
        assert [i["id"] for i in self._parse(body)] == ["w0", "w1"]

    def test_a_broken_array_still_raises_with_the_path(self):
        with pytest.raises(ValueError, match="batch.json"):
            self._parse('[{"id": "w0",')


class TestATopUpFiresWhenTheQueueIsDrained:
    """Holding items is not the same as having work.

    Driven through the helper the /annotate view actually calls, so a rename
    of the view does not quietly stop measuring this.
    """

    class StubUserState:
        def __init__(self, assigned, annotated):
            self._assigned = set(assigned)
            self._annotated = set(annotated)

        def get_assigned_instance_ids(self):
            return set(self._assigned)

        def get_annotated_instance_ids(self):
            return set(self._annotated)

    def _drained(self, assigned, annotated):
        from potato.routes import _has_annotated_all_assigned

        return _has_annotated_all_assigned(
            self.StubUserState(assigned, annotated))

    def test_a_drained_queue_asks_for_more(self):
        assert self._drained(["w0", "w1"], ["w0", "w1"]) is True, (
            "an annotator who finished everything they hold was read as busy "
            "forever, and shown a completion code while unassigned items sat "
            "in the pool")

    def test_an_unfinished_queue_does_not(self):
        assert self._drained(["w0", "w1"], ["w0"]) is False

    def test_holding_nothing_is_a_different_condition(self):
        """The view checks `has_assignments()` separately; this helper must
        not also claim a brand-new user is drained, or the log line lies about
        which branch ran."""
        assert self._drained([], []) is False

    def test_annotating_something_no_longer_held_does_not_block_a_top_up(self):
        """Reclaimed or reassigned items leave annotations behind."""
        assert self._drained(["w0"], ["w0", "old"]) is True

    def test_a_user_state_without_the_accessors_is_not_drained(self):
        class Bare:
            pass

        from potato.routes import _has_annotated_all_assigned

        assert _has_annotated_all_assigned(Bare()) is False


class TestSearchCoversWhatArrivedLater:

    def test_reindexing_is_reachable_from_the_search_package(self):
        """The watcher and the boot path both need it; a private helper on one
        of them would leave the other stale."""
        from potato import search

        assert hasattr(search, "reindex_from_item_state")

    def test_reindex_is_a_no_op_when_search_is_disabled(self):
        from potato.search import reindex_from_item_state

        assert reindex_from_item_state({"search": {"enabled": False}}) == 0

    def test_the_watcher_keeps_the_config_it_needs_to_reindex(self):
        """It took only the directory before, so it had nothing to reindex
        with."""
        from potato.directory_watcher import DirectoryWatcher

        with tempfile.TemporaryDirectory() as d:
            incoming = os.path.join(d, "incoming")
            os.makedirs(incoming)
            config = {"data_directory": incoming, "task_dir": d,
                      "item_properties": {"id_key": "id", "text_key": "text"}}
            watcher = DirectoryWatcher(config, item_state_manager=None)
            assert watcher.config is config

    def test_a_search_hit_carries_an_id(self):
        """Every other endpoint that returns items calls it `id`, so a caller
        reading `id` off a hit got a count with anonymous rows under it."""
        from potato.search.api import _serialize

        class Hit:
            instance_id = "w0"
            snippet = "alpha"
            score = -1.0

        row = _serialize([Hit()])[0]
        assert row["id"] == "w0"
        assert row["instance_id"] == "w0"
