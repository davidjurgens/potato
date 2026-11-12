"""Items another feature gives a user are kept out of their solo queue.

A member of a live collaborative team annotates the team's items on the
team's page. If ordinary assignment also handed them those items, the same
person would produce a solo answer and a team answer for one item, and the
two would be counted as independent judgements. Every strategy has to honour
the exclusion, including the ones that pick candidates through their own code.
"""

import pytest

import potato.item_state_management as ism_module
from potato.item_state_management import (
    excluded_items_for,
    init_item_state_manager,
    register_assignment_exclusion,
    unregister_assignment_exclusion,
)
from potato.user_state_management import InMemoryUserState

ITEM_IDS = [f"n{i:03d}" for i in range(1, 9)]
TEAM_ITEMS = {"n002", "n005", "n007"}

STRATEGIES = ["random", "fixed_order", "least_annotated", "max_diversity",
              "active_learning", "llm_confidence", "priority"]


def _team_items(username):
    return TEAM_ITEMS if username == "member" else set()


@pytest.fixture(autouse=True)
def _provider():
    register_assignment_exclusion(_team_items)
    yield
    unregister_assignment_exclusion(_team_items)
    ism_module.ITEM_STATE_MANAGER = None


def _manager(strategy):
    ism_module.ITEM_STATE_MANAGER = None
    ism = init_item_state_manager(
        {"assignment_strategy": strategy, "max_annotations_per_item": -1})
    ism.add_items({iid: {"id": iid, "text": f"item {iid}"} for iid in ITEM_IDS})
    return ism


def _drain(ism, user_state, calls=30):
    for _ in range(calls):
        ism.assign_instances_to_user(user_state)
    return set(user_state.get_assigned_instance_ids())


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_member_never_gets_team_items(strategy):
    ism = _manager(strategy)
    member = InMemoryUserState("member", max_assignments=len(ITEM_IDS))

    assigned = _drain(ism, member)

    assert not assigned & TEAM_ITEMS, f"{strategy} handed out team items {assigned & TEAM_ITEMS}"
    # ...and the rest of the corpus still reaches them.
    assert assigned == set(ITEM_IDS) - TEAM_ITEMS


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_other_users_are_unaffected(strategy):
    ism = _manager(strategy)
    outsider = InMemoryUserState("outsider", max_assignments=len(ITEM_IDS))
    assert _drain(ism, outsider) == set(ITEM_IDS)


def test_excluded_items_never_count_against_the_member():
    """The safety net drops an excluded pick and does not report it."""
    ism = _manager("fixed_order")
    member = InMemoryUserState("member", max_assignments=len(ITEM_IDS))
    _drain(ism, member)
    for iid in TEAM_ITEMS:
        assert "member" not in ism.instance_assignees.get(iid, set())


def test_a_broken_provider_does_not_stop_assignment():
    def broken(_username):
        raise RuntimeError("boom")

    register_assignment_exclusion(broken)
    try:
        ism = _manager("fixed_order")
        outsider = InMemoryUserState("outsider", max_assignments=len(ITEM_IDS))
        assert _drain(ism, outsider) == set(ITEM_IDS)
        assert excluded_items_for("member") == TEAM_ITEMS
    finally:
        unregister_assignment_exclusion(broken)


def test_no_providers_means_no_exclusions():
    unregister_assignment_exclusion(_team_items)
    assert excluded_items_for("member") == set()
