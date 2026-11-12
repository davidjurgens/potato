"""The progress denominator is the participant's batch, not the shared pool."""

import pytest

from potato import flask_server
from potato.item_state_management import (
    Label, clear_item_state_manager, init_item_state_manager,
)
from potato.user_state_management import InMemoryUserState
from potato.phase import UserPhase


@pytest.fixture
def manager():
    clear_item_state_manager()
    config = {
        "assignment_strategy": "batch", "max_annotations_per_item": -1,
        "batch_assignment": {"groups": [
            {"annotators": ["alice"], "instances": ["a1", "a2"]},
            {"annotators": ["bob"], "instances": ["b1", "b2"]},
        ]},
    }
    mgr = init_item_state_manager(config)
    mgr.add_items({iid: {"id": iid, "text": iid}
                   for iid in ["a1", "a2", "b1", "b2", "open"]})
    yield mgr
    clear_item_state_manager()


@pytest.mark.parametrize("assigned", [False, True])
def test_only_own_cohort_counts_before_and_after_assignment(manager, assigned):
    user = InMemoryUserState("alice")
    if assigned:
        assert manager.assign_instances_to_user(user) == 2
    assert set(manager.get_progress_pending_ids_for_user(user)) == {"a1", "a2"}


def test_user_outside_every_cohort_has_no_progress_pool(manager):
    user = InMemoryUserState("outsider")
    assert manager.get_progress_pending_ids_for_user(user) == []


def test_per_item_roster_is_included_without_other_cohorts(manager):
    manager.add_items({"extra": {"id": "extra", "text": "extra",
                                  "assigned_annotators": ["alice"]}})
    assert set(manager.get_progress_pending_ids_for_user(
        InMemoryUserState("alice"))) == {"a1", "a2", "extra"}


def test_counting_an_auto_batch_does_not_pin_the_participant():
    clear_item_state_manager()
    mgr = init_item_state_manager({
        "assignment_strategy": "batch", "max_annotations_per_item": -1,
        "batch_assignment": {"auto_assign_annotators": True, "groups": [
            {"name": "a", "instances": ["a1", "a2"]},
            {"name": "b", "instances": ["b1", "b2"]},
        ]},
    })
    try:
        mgr.add_items({iid: {"id": iid, "text": iid}
                       for iid in ["a1", "a2", "b1", "b2"]})
        assert set(mgr.get_progress_pending_ids_for_user(
            InMemoryUserState("new"))) == {"a1", "a2"}
        assert mgr.batch_auto_user_to_group == {}
        assert all(not users for users in mgr.batch_auto_group_to_users.values())
    finally:
        clear_item_state_manager()


def test_an_annotators_own_saturated_holds_still_count(manager):
    manager.max_annotations_per_item = 1
    user = InMemoryUserState("alice")
    manager.assign_instances_to_user(user)
    assert all(manager._item_is_saturated(iid) for iid in ["a1", "a2"])
    assert set(manager.get_progress_pending_ids_for_user(user)) == {"a1", "a2"}


def test_finished_plus_pending_uses_the_eligible_batch(manager, monkeypatch):
    user = InMemoryUserState("alice", max_assignments=10)
    user.current_phase_and_page = (UserPhase.ANNOTATION, "annotation")
    manager.assign_instances_to_user(user)
    user.add_label_annotation("a1", Label("choice", "yes"), "yes")
    monkeypatch.setattr(flask_server, "get_user_state", lambda name: user)
    assert flask_server.progress_counts("alice") == (1, 2)


def test_non_batch_progress_keeps_the_shared_pool(manager):
    from potato.item_state_management import AssignmentStrategy
    manager.assignment_strategy = AssignmentStrategy.FIXED_ORDER
    assert set(manager.get_progress_pending_ids_for_user(
        InMemoryUserState("alice"))) == {"a1", "a2", "b1", "b2", "open"}
