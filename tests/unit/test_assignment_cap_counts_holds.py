"""
The per-item annotator cap counts outstanding assignments, not just submissions.

`num_annotators_per_item` was checked against `instance_annotators`, which is
populated when somebody *annotates*. Until then an item was free, so the
default strategy -- which walks the item list from the top -- handed the same
first item to every annotator who arrived, and a study with three items and
`num_annotators_per_item: 1` gave item_0 to five people while item_1 and item_2
sat untouched. Everyone past the first was working on an item that already had
its full complement, and the study pays for that.

The fix has to avoid the opposite failure. A hold is not a submission: an
annotator who takes items and closes the tab must not strand them, and
`instance_reclaim` -- the machinery that takes stale holds back -- is off by
default. So the cap counts holds, and is relaxed for a second pass when
enforcing it would have sent somebody away with nothing.
"""

import pytest

import potato.item_state_management
from potato.item_state_management import init_item_state_manager
from potato.user_state_management import InMemoryUserState


def manager(n_items=3, cap=1, reclaim=False):
    potato.item_state_management.ITEM_STATE_MANAGER = None
    config = {
        "num_annotators_per_item": cap,
        "annotation_schemes": [{"annotation_type": "radio", "name": "s",
                                "description": "d", "labels": ["a", "b"]}],
    }
    if reclaim:
        config["instance_reclaim"] = {"enabled": True, "timeout_hours": 24}
    ism = init_item_state_manager(config)
    ism.add_items({f"item_{i}": {"id": f"item_{i}", "text": f"s{i}"}
                   for i in range(n_items)})
    return ism


def user(ism, name, quota=1):
    """One item each, so who gets which item is the thing being measured."""
    return InMemoryUserState(name, max_assignments=quota)


def assigned(state):
    return sorted(state.get_assigned_instance_ids())


class TestHoldsSpreadAnnotatorsAcrossTheDataset:

    def test_three_annotators_get_three_different_items(self):
        # The defect: all three used to get item_0.
        ism = manager(n_items=3, cap=1)
        picks = []
        for name in ("a", "b", "c"):
            state = user(ism, name)
            ism.assign_instances_to_user(state)
            picks.append(assigned(state))
        assert sorted(p[0] for p in picks if p) == ["item_0", "item_1", "item_2"]

    def test_a_held_item_is_not_offered_again_while_work_remains(self):
        ism = manager(n_items=3, cap=1)
        first = user(ism, "a")
        ism.assign_instances_to_user(first)
        second = user(ism, "b")
        ism.assign_instances_to_user(second)
        assert assigned(first) != assigned(second)

    def test_a_submitted_item_is_not_offered_again_either(self):
        ism = manager(n_items=3, cap=1)
        first = user(ism, "a")
        ism.assign_instances_to_user(first)
        held = assigned(first)[0]
        ism.register_annotator(held, "a")

        second = user(ism, "b")
        ism.assign_instances_to_user(second)
        assert assigned(second) != [held]


class TestAHoldNeverStrandsAnItem:
    """
    The relaxation pass. Without it, an annotator who takes an item and walks
    away removes it from the study permanently whenever `instance_reclaim` is
    off -- which is the default.
    """

    def test_a_surplus_annotator_still_gets_work_when_nothing_was_submitted(self):
        ism = manager(n_items=2, cap=1)
        holders = []
        for name in ("a", "b"):
            state = user(ism, name)
            ism.assign_instances_to_user(state)
            holders.append(state)
        assert all(assigned(s) for s in holders), "setup: both items held"

        # Nobody submitted. The third annotator must still get something.
        third = user(ism, "c")
        assert ism.assign_instances_to_user(third) == 1
        assert assigned(third)

    def test_the_relaxed_pass_still_respects_submitted_annotations(self):
        # Once the annotations are actually in, the study IS finished, and the
        # relaxation must not hand the items out again.
        ism = manager(n_items=2, cap=1)
        for name in ("a", "b"):
            state = user(ism, name)
            ism.assign_instances_to_user(state)
            for iid in assigned(state):
                ism.register_annotator(iid, name)

        third = user(ism, "c")
        assert ism.assign_instances_to_user(third) == 0
        assert assigned(third) == []

    def test_a_held_item_stays_in_the_queue(self):
        # Retirement is driven by annotations, not by holds. Evicting a merely
        # held item from `remaining_instance_ids` is what made the relaxation
        # pass find nothing to relax.
        ism = manager(n_items=2, cap=1)
        state = user(ism, "a")
        ism.assign_instances_to_user(state)
        held = assigned(state)[0]
        assert held in ism.remaining_instance_ids

    def test_an_annotated_item_leaves_the_queue(self):
        ism = manager(n_items=2, cap=1)
        state = user(ism, "a")
        ism.assign_instances_to_user(state)
        done = assigned(state)[0]
        ism.register_annotator(done, "a")

        # Assigning to somebody else is what walks the queue and retires it.
        ism.assign_instances_to_user(user(ism, "b"))
        assert done not in ism.remaining_instance_ids


class TestReleasingAHold:

    def test_reclaiming_an_unannotated_assignment_frees_the_item(self):
        ism = manager(n_items=1, cap=1, reclaim=True)
        holder = user(ism, "a")
        ism.assign_instances_to_user(holder)
        held = assigned(holder)[0]
        assert ism._item_is_saturated(held)

        ism._reclaim_unannotated_assignment(holder, held, reason="test")
        assert not ism._item_is_saturated(held), (
            "the hold outlived the assignment, so the item was locked forever")

        other = user(ism, "b")
        assert ism.assign_instances_to_user(other) == 1

    def test_the_two_predicates_answer_different_questions(self):
        ism = manager(n_items=1, cap=1)
        state = user(ism, "a")
        ism.assign_instances_to_user(state)
        held = assigned(state)[0]

        assert ism._item_is_saturated(held) is True, "spoken for"
        assert ism._item_is_complete(held) is False, "but not finished"

        ism.register_annotator(held, "a")
        assert ism._item_is_complete(held) is True
