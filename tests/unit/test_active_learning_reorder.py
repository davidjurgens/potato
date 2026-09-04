"""Instance reordering, and the two defects that made it unsafe.

Both bugs here were live and neither was caught by the existing suite, because
every test asserted on what `_apply_reordering` *returned* to the item manager
rather than on the queue that came out the other side.
"""

import threading
import time

import pytest

from potato.active_learning_manager import (ActiveLearningConfig,
                                            ActiveLearningManager)


class FakeItem:
    def __init__(self, iid, text):
        self._id = iid
        self._text = text
        self.data = {"id": iid, "text": text}

    def get_text(self):
        return self._text


class FakeItemManager:
    """Just enough of ItemStateManager to exercise the reorder path."""

    def __init__(self, ids):
        self.instance_id_ordering = list(ids)
        self.remaining_instance_ids = list(ids)
        self.completed_instance_ids = set()
        self._items = {i: FakeItem(i, "text for %s" % i) for i in ids}
        self.reorder_calls = []

    def get_instance_ids(self):
        return list(self.instance_id_ordering)

    def get_remaining_instance_ids(self):
        return list(self.remaining_instance_ids)

    def get_item(self, iid):
        return self._items.get(iid)

    def get_annotators_for_item(self, iid):
        return []

    def reorder_instances(self, new_order):
        self.reorder_calls.append(list(new_order))
        # Mirror the real implementation's dedupe, so a test that passes here
        # is testing the same guarantee the real manager makes.
        new_order = list(dict.fromkeys(new_order))
        seen = set(new_order)
        self.instance_id_ordering = (
            [i for i in new_order if i in self._items]
            + [i for i in self.instance_id_ordering if i not in seen])
        self.remaining_instance_ids = [
            i for i in self.instance_id_ordering
            if i not in self.completed_instance_ids]


def _manager(**overrides):
    cfg_kwargs = dict(enabled=False, schema_names=["s"])
    cfg_kwargs.update(overrides)
    return ActiveLearningManager(ActiveLearningConfig(**cfg_kwargs))


class TestNoDuplicates:
    """Defect A: the exploration sample was drawn from the list it interleaved."""

    @pytest.mark.parametrize("percent", [0.0, 0.1, 0.2, 0.5, 1.0])
    def test_reordering_never_emits_a_duplicate(self, percent):
        manager = _manager(random_sample_percent=percent)
        ids = ["i%02d" % i for i in range(20)]
        item_manager = FakeItemManager(ids)

        scored = [(iid, 1.0 - n / 20.0) for n, iid in enumerate(ids)]
        manager._apply_reordering(scored, item_manager)

        emitted = item_manager.reorder_calls[0]
        assert len(emitted) == len(set(emitted)), (
            "reordering emitted duplicates at random_sample_percent=%s: %s"
            % (percent, [i for i in emitted if emitted.count(i) > 1]))

    @pytest.mark.parametrize("percent", [0.0, 0.2, 0.5, 1.0])
    def test_every_instance_survives_exactly_once(self, percent):
        manager = _manager(random_sample_percent=percent)
        ids = ["i%02d" % i for i in range(20)]
        item_manager = FakeItemManager(ids)

        manager._apply_reordering(
            [(iid, 0.5) for iid in ids], item_manager)

        assert sorted(item_manager.reorder_calls[0]) == sorted(ids)

    def test_the_queue_does_not_grow(self):
        """The symptom users would see: a queue longer than the corpus."""
        manager = _manager(random_sample_percent=0.2)
        ids = ["i%02d" % i for i in range(50)]
        item_manager = FakeItemManager(ids)

        for _ in range(3):
            manager._apply_reordering(
                [(iid, 0.5) for iid in item_manager.get_remaining_instance_ids()],
                item_manager)

        assert len(item_manager.remaining_instance_ids) == 50
        assert len(set(item_manager.remaining_instance_ids)) == 50

    def test_exploration_still_happens(self):
        """The fix must not silently turn exploration off."""
        manager = _manager(random_sample_percent=0.5)
        ids = ["i%02d" % i for i in range(20)]
        item_manager = FakeItemManager(ids)

        # Feed a fixed ranking repeatedly; the tail should not always land in
        # the same place, or nothing is being explored.
        orders = set()
        for _ in range(12):
            item_manager.reorder_calls.clear()
            manager._apply_reordering(
                [(iid, 1.0 - n / 20.0) for n, iid in enumerate(ids)],
                item_manager)
            orders.add(tuple(item_manager.reorder_calls[0]))

        assert len(orders) > 1, "exploration sample never varied"


class TestReorderDedupeInRealManager:
    """The dedupe belongs in ItemStateManager, not only in its callers."""

    def test_reorder_instances_dedupes(self):
        from potato.item_state_management import ItemStateManager

        manager = ItemStateManager.__new__(ItemStateManager)
        manager._store = {"a": object(), "b": object(), "c": object()}
        manager.instance_id_ordering = ["a", "b", "c"]
        from collections import deque
        manager.remaining_instance_ids = deque()
        manager.completed_instance_ids = set()
        import logging
        manager.logger = logging.getLogger("test")

        manager.reorder_instances(["a", "b", "a", "c", "b"])

        assert manager.instance_id_ordering == ["a", "b", "c"]
        assert list(manager.remaining_instance_ids) == ["a", "b", "c"]


class TestCandidatePool:
    """Defects C and D: which items get ranked at all."""

    def test_ranking_covers_the_pool_that_is_actually_served(self):
        """
        Ranking used to select on "has no annotator at all", which is not the
        same set as remaining_instance_ids. With overlap configured, every
        partially-annotated item fell out of the ranking while still being
        served.
        """
        manager = _manager()
        manager._models["s"] = _ConstantModel()
        manager._vectorizers["s"] = None

        ids = ["i%d" % i for i in range(6)]
        item_manager = FakeItemManager(ids)

        # Half the items already have one annotator, but are still in the
        # queue because the project wants two.
        def one_annotator(iid):
            return ["alice"] if iid in {"i0", "i1", "i2"} else []
        item_manager.get_annotators_for_item = one_annotator

        manager._reorder_instances(item_manager, "s")

        ranked = set(item_manager.reorder_calls[0])
        assert ranked == set(ids), (
            "partially-annotated items were excluded from ranking: %s"
            % (set(ids) - ranked))

    def test_the_cap_samples_rather_than_taking_the_head(self):
        """
        Slicing the candidate list took the first N in store order, so with a
        cap set the tail of the corpus could never be surfaced however
        uncertain it was.
        """
        manager = _manager(max_instances_to_reorder=5)
        manager._models["s"] = _ConstantModel()
        manager._vectorizers["s"] = None

        ids = ["i%02d" % i for i in range(40)]

        seen = set()
        for _ in range(20):
            item_manager = FakeItemManager(ids)
            manager._reorder_instances(item_manager, "s")
            seen.update(item_manager.reorder_calls[0])

        # With head-slicing this would be exactly the first five ids forever.
        assert len(seen) > 10, (
            "the cap only ever considered %d distinct items" % len(seen))


class _ConstantModel:
    """A model whose confidence is the same everywhere, so order is the test."""

    def predict_proba(self, texts):
        return [[0.5, 0.5] for _ in texts]


class TestTriggerDoesNotBlockOnTraining:
    """Defect B: the request thread waited out every fit."""

    def test_check_and_trigger_returns_while_a_fit_is_in_flight(self,
                                                               monkeypatch):
        # enabled=False keeps the worker thread out of it; the trigger's own
        # gate is bypassed below. A live worker would pick the queued item up
        # and try to train against these fakes.
        manager = _manager(enabled=False, update_frequency=1)
        manager.config.enabled = True

        # Hold the training lock the way a slow fit would.
        holding = threading.Event()
        release = threading.Event()

        def hold_the_lock():
            with manager._lock:
                holding.set()
                release.wait(timeout=10)

        worker = threading.Thread(target=hold_the_lock, daemon=True)
        worker.start()
        assert holding.wait(timeout=5)

        class FakeUserState:
            def get_all_annotations(self):
                return {"a": 1, "b": 2}

        class FakeUserManager:
            def get_all_users(self):
                return [FakeUserState()]

        monkeypatch.setattr(
            "potato.active_learning_manager.get_user_state_manager",
            lambda: FakeUserManager())

        try:
            start = time.monotonic()
            manager.check_and_trigger_training()
            elapsed = time.monotonic() - start
        finally:
            release.set()
            worker.join(timeout=5)

        assert elapsed < 0.5, (
            "check_and_trigger_training blocked for %.2fs behind the training "
            "lock; it runs on the Flask request thread after every save"
            % elapsed)

    def test_the_delta_is_claimed_once(self, monkeypatch):
        """Two concurrent saves must not both queue a run for the same work."""
        # enabled=False so no worker thread drains the queue behind us; the
        # trigger's own `enabled` gate is bypassed below.
        manager = _manager(enabled=False, update_frequency=1)
        manager.config.enabled = True

        queued = []
        manager._training_queue.put = lambda item: queued.append(item)

        class FakeUserState:
            def get_all_annotations(self):
                return {"a": 1, "b": 2, "c": 3}

        class FakeUserManager:
            def get_all_users(self):
                return [FakeUserState()]

        monkeypatch.setattr(
            "potato.active_learning_manager.get_user_state_manager",
            lambda: FakeUserManager())

        threads = [threading.Thread(target=manager.check_and_trigger_training)
                   for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(queued) == 1, (
            "%d threads each queued a run for the same annotations" % len(queued))
