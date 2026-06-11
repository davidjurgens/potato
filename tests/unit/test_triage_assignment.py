"""Unit tests for the PRIORITY assignment strategy + triage metadata on items."""

import pytest

from potato.item_state_management import init_item_state_manager, AssignmentStrategy
from potato.user_state_management import InMemoryUserState


def _reset():
    import potato.item_state_management
    potato.item_state_management.ITEM_STATE_MANAGER = None


def _manager(config, items):
    _reset()
    ism = init_item_state_manager(config)
    ism.add_items(items)
    return ism


def _user(user_id, max_assignments=10):
    return InMemoryUserState(user_id, max_assignments=max_assignments)


PRIORITY_CFG = {
    "assignment_strategy": "priority",
    "max_annotations_per_item": -1,
    "triage": {"enabled": True},  # turnkey defaults
}

ITEMS = {
    "clean": {"id": "clean", "text": "ok", "status": "ok", "score": 0.9},
    "errored": {"id": "errored", "text": "boom", "status": "error"},
    "lowscore": {"id": "lowscore", "text": "meh", "score": 0.3},
}


# --- metadata stored on add_item -------------------------------------------

def test_add_item_stores_triage_metadata():
    ism = _manager(PRIORITY_CFG, ITEMS)
    assert ism.get_item("errored").get_metadata("triage_priority") == 100
    assert ism.get_item("errored").get_metadata("triage_reason") == "Agent errored"
    assert ism.get_item("clean").get_metadata("triage_priority") == 0
    assert ism.get_item("clean").get_metadata("triage_reason") is None


def test_no_triage_metadata_when_disabled():
    ism = _manager({"max_annotations_per_item": -1}, ITEMS)
    assert ism.get_item("errored").get_metadata("triage_priority") is None


# --- auto strategy selection ------------------------------------------------

def test_triage_enabled_auto_selects_priority_strategy():
    ism = _manager({"triage": {"enabled": True}, "max_annotations_per_item": -1}, ITEMS)
    assert ism.assignment_strategy == AssignmentStrategy.PRIORITY


def test_explicit_strategy_overrides_triage_auto():
    ism = _manager(
        {"triage": {"enabled": True}, "assignment_strategy": "fixed_order",
         "max_annotations_per_item": -1},
        ITEMS,
    )
    assert ism.assignment_strategy == AssignmentStrategy.FIXED_ORDER


# --- ordering ---------------------------------------------------------------

def test_priority_serves_highest_first():
    ism = _manager(PRIORITY_CFG, ITEMS)
    user = _user("u1")
    ism.assign_instances_to_user(user)
    # errored (100) > lowscore (60) > clean (0)
    assert user.instance_id_ordering == ["errored", "lowscore", "clean"]


def test_order_asc_flips_priority():
    cfg = {
        "assignment_strategy": "priority",
        "max_annotations_per_item": -1,
        "triage": {"enabled": True, "order": "asc"},
    }
    ism = _manager(cfg, ITEMS)
    user = _user("u1")
    ism.assign_instances_to_user(user)
    assert user.instance_id_ordering == ["clean", "lowscore", "errored"]


def test_ties_broken_by_original_order_deterministically():
    items = {
        "a": {"id": "a", "status": "error"},
        "b": {"id": "b", "status": "error"},
        "c": {"id": "c", "status": "error"},
    }
    ism = _manager(PRIORITY_CFG, items)
    user = _user("u1")
    ism.assign_instances_to_user(user)
    # all priority 100 -> original insertion order preserved
    assert user.instance_id_ordering == ["a", "b", "c"]


def test_priority_respects_limited_user_quota():
    ism = _manager(PRIORITY_CFG, ITEMS)
    user = _user("u1", max_assignments=1)
    assigned = ism.assign_instances_to_user(user)
    assert assigned == 1
    assert user.instance_id_ordering == ["errored"]  # only the top one


def test_custom_rule_priorities_order_queue():
    cfg = {
        "assignment_strategy": "priority",
        "max_annotations_per_item": -1,
        "triage": {
            "enabled": True,
            "rules": [
                {"name": "high", "priority": 90, "when": {"field": "tag", "equals": "urgent"}},
                {"name": "mid", "priority": 50, "when": {"field": "tag", "equals": "normal"}},
            ],
        },
    }
    items = {
        "x": {"id": "x", "tag": "normal"},
        "y": {"id": "y", "tag": "urgent"},
        "z": {"id": "z", "tag": "other"},
    }
    ism = _manager(cfg, items)
    user = _user("u1")
    ism.assign_instances_to_user(user)
    assert user.instance_id_ordering == ["y", "x", "z"]


def test_runtime_added_high_priority_item_jumps_queue():
    # Mimics a trace ingested mid-session: it should outrank a clean item that
    # was already waiting, on the next assignment.
    ism = _manager(PRIORITY_CFG, {"clean": {"id": "clean", "status": "ok", "score": 0.9}})
    ism.add_item("late_error", {"id": "late_error", "status": "error"})
    user = _user("u1")
    ism.assign_instances_to_user(user)
    assert user.instance_id_ordering[0] == "late_error"


# --- other strategies unaffected -------------------------------------------

def test_fixed_order_unaffected_by_triage_metadata():
    cfg = {
        "assignment_strategy": "fixed_order",
        "max_annotations_per_item": -1,
        "triage": {"enabled": True},
    }
    ism = _manager(cfg, ITEMS)
    user = _user("u1")
    ism.assign_instances_to_user(user)
    # fixed order = insertion order, regardless of triage priority
    assert user.instance_id_ordering == ["clean", "errored", "lowscore"]
