"""`num_annotators_per_item: 0` means unlimited.

The validation message for a negative value says "use 0 or omit the key for
unlimited", but the cap checks treated any cap >= 0 as a limit, so 0 retired
every item: validate passed and a new annotator got nothing to annotate.
"""

import potato.item_state_management
from potato.item_state_management import init_item_state_manager
from potato.server_utils.config_module import resolve_num_annotators_per_item
from potato.user_state_management import InMemoryUserState

SCHEMES = [{"annotation_type": "radio", "name": "s", "description": "d",
            "labels": ["a", "b"]}]


def manager(cap):
    potato.item_state_management.ITEM_STATE_MANAGER = None
    ism = init_item_state_manager({"num_annotators_per_item": cap,
                                   "annotation_schemes": SCHEMES})
    ism.add_items({f"item_{i}": {"id": f"item_{i}", "text": f"s{i}"} for i in range(3)})
    return ism


def test_zero_resolves_to_unlimited():
    assert resolve_num_annotators_per_item({"num_annotators_per_item": 0}) == -1
    assert resolve_num_annotators_per_item({"num_annotators_per_item": {"default": 0}}) == -1


def test_a_new_annotator_gets_an_item_with_a_zero_cap():
    ism = manager(0)
    state = InMemoryUserState("a", max_assignments=2)
    ism.assign_instances_to_user(state)
    assert state.get_assigned_instance_ids()


def test_a_zero_cap_behaves_like_no_cap():
    picks = {}
    for cap in (0, None):
        ism = manager(cap)
        states = [InMemoryUserState(n, max_assignments=3) for n in "abcd"]
        for s in states:
            ism.assign_instances_to_user(s)
        picks[cap] = [sorted(s.get_assigned_instance_ids()) for s in states]
    assert picks[0] == picks[None]
