"""Every strategy has to keep handing out items, not just the first three.

Assignment is incremental: the first call gives a user three items, and each
later call gives one more as they work through the queue. Five of the eleven
strategies built their candidate pool by asking "has this user *annotated* it?"
instead of "does this user already *have* it?". On a top-up call the pool still
contained the items already sitting in the user's queue, so the strategy could
re-pick one; ``assign_instance`` drops a duplicate without a word, the strategy
reports one item assigned anyway, and the queue stops growing.

Measured against a live server before the fix: a six-item task with
``assignment_strategy: random`` served each annotator three items and stopped.
Nothing warned. It shows up only as a progress counter that finishes early, or
as an agreement number quietly computed over half the corpus.

The controls matter as much as the cases: ``fixed_order`` and ``least_annotated``
were already filtering on assignment and must keep working unchanged.
"""

import pytest

from potato.item_state_management import init_item_state_manager
from potato.user_state_management import InMemoryUserState

ITEM_IDS = [f"n{i:03d}" for i in range(1, 7)]

# The five that had the bug, plus two that did not and must not regress.
REPAIRED = ["random", "max_diversity", "active_learning", "llm_confidence"]
CONTROLS = ["fixed_order", "least_annotated"]


def _manager(strategy):
    import potato.item_state_management as mod

    mod.ITEM_STATE_MANAGER = None
    ism = init_item_state_manager(
        {"assignment_strategy": strategy, "max_annotations_per_item": -1}
    )
    ism.add_items({iid: {"id": iid, "text": f"item {iid}"} for iid in ITEM_IDS})
    return ism


def _drain(ism, user_state, calls=25):
    """Call assignment the way the server does: once per page view."""
    for _ in range(calls):
        ism.assign_instances_to_user(user_state)
    return list(user_state.get_assigned_instance_ids())


@pytest.mark.parametrize("strategy", REPAIRED + CONTROLS)
def test_an_annotator_is_eventually_given_every_item(strategy):
    ism = _manager(strategy)
    user_state = InMemoryUserState("u1", max_assignments=len(ITEM_IDS))

    assigned = _drain(ism, user_state)

    assert sorted(assigned) == sorted(ITEM_IDS), (
        f"{strategy} stopped at {len(assigned)} of {len(ITEM_IDS)} items; "
        "an annotator would see a progress counter that ends early"
    )


@pytest.mark.parametrize("strategy", REPAIRED + CONTROLS)
def test_the_quota_is_still_a_cap(strategy):
    """The repair must not turn the per-user quota off."""
    ism = _manager(strategy)
    user_state = InMemoryUserState("u1", max_assignments=4)

    assigned = _drain(ism, user_state)

    assert len(assigned) == 4, f"{strategy} handed out {len(assigned)} against a cap of 4"


@pytest.mark.parametrize("strategy", REPAIRED)
def test_nothing_is_assigned_twice(strategy):
    """The duplicate was silent, so assert on the ordering rather than the set."""
    ism = _manager(strategy)
    user_state = InMemoryUserState("u1", max_assignments=len(ITEM_IDS))

    _drain(ism, user_state)

    ordering = user_state.instance_id_ordering
    assert len(ordering) == len(set(ordering)), f"{strategy} queued a duplicate: {ordering}"


def test_random_actually_varies_the_order():
    """Guard against 'fix it by making random behave like fixed_order'."""
    orders = set()
    for seed in (1, 2, 3, 4, 5):
        import potato.item_state_management as mod

        mod.ITEM_STATE_MANAGER = None
        ism = init_item_state_manager(
            {
                "assignment_strategy": "random",
                "max_annotations_per_item": -1,
                "random_seed": seed,
            }
        )
        ism.add_items({iid: {"id": iid, "text": iid} for iid in ITEM_IDS})
        user_state = InMemoryUserState(f"u{seed}", max_assignments=len(ITEM_IDS))
        _drain(ism, user_state)
        orders.add(tuple(user_state.instance_id_ordering))

    assert len(orders) > 1, "every seed produced the same order; this is not random"


@pytest.mark.parametrize("strategy", REPAIRED)
def test_the_returned_count_is_what_was_actually_assigned(strategy):
    """The count is a lie the caller cannot see through.

    ``assign_instance`` returns early on a duplicate, so a strategy that
    re-picks an item the user already holds still reports one item assigned.
    Callers use that number to decide whether there is more work; a
    permanently-optimistic 1 is why the queue stalls without an error. This is
    the check that catches the probabilistic strategies, where the
    end-to-end count test only fails on some seeds.
    """
    ism = _manager(strategy)
    user_state = InMemoryUserState("u1", max_assignments=len(ITEM_IDS))

    for _ in range(25):
        before = len(user_state.get_assigned_instance_ids())
        reported = ism.assign_instances_to_user(user_state)
        after = len(user_state.get_assigned_instance_ids())
        assert reported == after - before, (
            f"{strategy} reported {reported} assigned but the queue grew by "
            f"{after - before}"
        )


class TestQualityControlDoesNotEatTheQuota:
    """An injected check must not cost the annotator a real item.

    Attention checks and gold items are put into the queue by the platform
    rather than drawn from the pool, but they are stored in
    ``assigned_instance_ids`` like anything else. While the per-user quota
    counted them, every injected check displaced one dataset item: a six-item
    task with the default quota and two checks served four articles, and the
    only sign was a progress bar that stopped early.

    Measured against a live server, ``fixed_order`` hid this -- it claims the
    whole remaining capacity in one call, before any check exists, so checks
    ended up appended past the cap. The incremental strategies, including
    ``random``, lost items. The two now agree.
    """

    @pytest.fixture
    def qc(self, monkeypatch):
        class FakeQC:
            checks = {"check01", "check02"}

            def is_attention_check(self, iid):
                return iid in self.checks

            def is_gold_standard(self, iid):
                return False

        import potato.quality_control as qc_mod

        fake = FakeQC()
        monkeypatch.setattr(qc_mod, "get_quality_control_manager", lambda: fake)
        return fake

    @pytest.mark.parametrize("strategy", ["random", "fixed_order", "least_annotated"])
    def test_an_injected_check_does_not_displace_an_item(self, qc, strategy):
        ism = _manager(strategy)
        user_state = InMemoryUserState("u1", max_assignments=len(ITEM_IDS))

        # The platform injects a check the way routes.py does, mid-queue.
        ism.assign_instances_to_user(user_state)
        ism.add_items({"check01": {"id": "check01", "text": "an attention check"}})
        user_state.assign_instance_at_index(ism.get_item("check01"), 1)

        _drain(ism, user_state)

        real = [i for i in user_state.get_assigned_instance_ids() if i in ITEM_IDS]
        assert sorted(real) == sorted(ITEM_IDS), (
            f"{strategy} served {len(real)} of {len(ITEM_IDS)} articles; the "
            "attention check was charged against the annotator's quota"
        )

    def test_the_quota_still_caps_dataset_items(self, qc):
        """Excluding checks must not make the quota unenforceable."""
        ism = _manager("random")
        user_state = InMemoryUserState("u1", max_assignments=3)

        _drain(ism, user_state)

        real = [i for i in user_state.get_assigned_instance_ids() if i in ITEM_IDS]
        assert len(real) == 3


class TestCompletionAgreesWithAssignment:
    """The quota is compared against the queue twice, and both must discount.

    ``ItemStateManager`` decides how many more items to hand out;
    ``UserState.has_remaining_assignments`` decides whether the annotator is
    finished. While only the first discounted injected checks, the two
    disagreed: on a twelve-item task with one attention check, assignment
    correctly handed out all twelve articles and the completion check declared
    the annotator done after eleven of them plus the check. The twelfth was
    assigned, reachable in the ordering, and never shown -- found by walking the
    task in a browser, not by any test.
    """

    @pytest.fixture
    def qc(self, monkeypatch):
        class FakeQC:
            checks = {"check01"}

            def is_attention_check(self, iid):
                return iid in self.checks

            def is_gold_standard(self, iid):
                return False

        import potato.quality_control as qc_mod

        fake = FakeQC()
        monkeypatch.setattr(qc_mod, "get_quality_control_manager", lambda: fake)
        return fake

    def test_a_check_does_not_end_the_study_one_item_early(self, qc, monkeypatch):
        ism = _manager("random")
        user_state = InMemoryUserState("u1", max_assignments=len(ITEM_IDS))

        ism.assign_instances_to_user(user_state)
        ism.add_items({"check01": {"id": "check01", "text": "an attention check"}})
        user_state.assign_instance_at_index(ism.get_item("check01"), 1)
        _drain(ism, user_state)

        # Annotate everything except the last article, plus the check.
        for iid in user_state.get_assigned_instance_ids():
            if iid != ITEM_IDS[-1]:
                user_state.set_annotation(iid, {"label": {"a": "1"}}, {}, {})

        assert user_state.has_remaining_assignments(), (
            "the annotator was declared finished with an article still "
            "unannotated, because the attention check was counted against the "
            "quota here even though assignment does not count it"
        )

    def test_the_quota_still_ends_the_study(self, qc):
        """Discounting checks must not make the completion check unreachable."""
        ism = _manager("random")
        user_state = InMemoryUserState("u1", max_assignments=3)
        _drain(ism, user_state)

        for iid in user_state.get_assigned_instance_ids():
            user_state.set_annotation(iid, {"label": {"a": "1"}}, {}, {})

        assert not user_state.has_remaining_assignments()
