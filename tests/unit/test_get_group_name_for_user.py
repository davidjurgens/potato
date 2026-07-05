"""Unit tests for ItemStateManager.get_group_name_for_user (cohort lookup)."""

import pytest

from potato.item_state_management import init_item_state_manager
from potato.user_state_management import InMemoryUserState


def _reset():
    import potato.item_state_management
    potato.item_state_management.ITEM_STATE_MANAGER = None


def _manager(config, item_ids):
    _reset()
    ism = init_item_state_manager(config)
    ism.add_items({i: {"id": i, "text": f"item {i}"} for i in item_ids})
    return ism


def test_explicit_group_membership_returns_name():
    cfg = {
        "assignment_strategy": "batch",
        "max_annotations_per_item": -1,
        "batch_assignment": {
            "groups": [
                {"name": "cohortA", "annotators": ["alice", "bob"], "instances": ["a1"]},
                {"name": "cohortB", "annotators": ["carol"], "instances": ["b1"]},
            ]
        },
    }
    ism = _manager(cfg, ["a1", "b1"])
    assert ism.get_group_name_for_user("alice") == "cohortA"
    assert ism.get_group_name_for_user("bob") == "cohortA"
    assert ism.get_group_name_for_user("carol") == "cohortB"


def test_unknown_user_returns_none():
    cfg = {
        "assignment_strategy": "batch",
        "max_annotations_per_item": -1,
        "batch_assignment": {
            "groups": [{"name": "cohortA", "annotators": ["alice"], "instances": ["a1"]}]
        },
    }
    ism = _manager(cfg, ["a1"])
    assert ism.get_group_name_for_user("nobody") is None


def test_explicit_group_without_name_synthesizes_index():
    cfg = {
        "assignment_strategy": "batch",
        "max_annotations_per_item": -1,
        "batch_assignment": {
            "groups": [{"annotators": ["alice"], "instances": ["a1"]}]
        },
    }
    ism = _manager(cfg, ["a1"])
    assert ism.get_group_name_for_user("alice") == "group_0"


def test_auto_assigned_pin_returns_group_name():
    cfg = {
        "assignment_strategy": "batch",
        "max_annotations_per_item": -1,
        "batch_assignment": {
            "auto_assign_annotators": True,
            "groups": [
                {"name": "autoA", "instances": ["a1"], "max_annotators": 5},
                {"name": "autoB", "instances": ["b1"], "max_annotators": 5},
            ],
        },
    }
    ism = _manager(cfg, ["a1", "b1"])
    user = InMemoryUserState("zoe", max_assignments=10)
    # Assignment pins the user to the least-filled auto group.
    ism.assign_instances_to_user(user)
    name = ism.get_group_name_for_user("zoe")
    assert name in ("autoA", "autoB")


def test_no_batch_assignment_returns_none():
    ism = _manager({"max_annotations_per_item": -1}, ["a1"])
    assert ism.get_group_name_for_user("alice") is None
