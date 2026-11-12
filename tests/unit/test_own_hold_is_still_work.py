"""An annotator's own hold must not make their own queue look empty.

Once the per-item cap began counting outstanding holds as well as submissions,
`_item_is_saturated` answered "may this go to somebody NEW". But
`has_unlabeled_items_for_user` asked it "does this annotator have work", and on
a study with `num_annotators_per_item: 2` the second annotator was assigned
every item, each item then read as saturated -- one submitter plus their own
hold -- and they were declared finished holding a queue of blank items.

Silent and total, because `UserState._label_container` routes writes by the
user's current phase. Every annotation they submitted afterwards went into
`phase_to_page_to_label_to_value[DONE]` rather than the instance store, each
one overwriting the last, and every save returned HTTP 200. The agreement
report over a two-annotator study showed one annotator, and the second
annotator's whole session did not exist.

Caught only because `/admin/iaa` rendered "no item has two or more
annotators" over a study that plainly had two.
"""

import pytest

import potato.item_state_management
from potato.item_state_management import init_item_state_manager
from potato.phase import UserPhase
from potato.user_state_management import InMemoryUserState


ITEMS = ["scene_0", "scene_1", "scene_2"]


@pytest.fixture
def ism():
    potato.item_state_management.ITEM_STATE_MANAGER = None
    manager = init_item_state_manager({
        "num_annotators_per_item": 2,
        "annotation_schemes": [{"annotation_type": "radio", "name": "s",
                                "description": "d", "labels": ["a", "b"]}],
    })
    manager.add_items({iid: {"id": iid, "text": iid} for iid in ITEMS})
    return manager


def _annotator(name):
    """A user state in the annotation phase, which is where item writes land."""
    state = InMemoryUserState(name, max_assignments=len(ITEMS))
    state.advance_to_phase(UserPhase.ANNOTATION, None)
    return state


def _annotate_all(ism, user_state):
    """Record a submission on both sides, the way /updateinstance does."""
    from potato.item_state_management import Label
    for iid in list(user_state.get_assigned_instance_ids()):
        user_state.add_label_annotation(iid, Label("s", "a"), "a")
        ism.register_annotator(iid, user_state.user_id)


class TestTheSecondAnnotator:
    def test_they_are_not_finished_while_holding_blank_items(self, ism):
        alice = _annotator("alice")
        ism.assign_instances_to_user(alice)
        _annotate_all(ism, alice)

        bob = _annotator("bob")
        ism.assign_instances_to_user(bob)

        assert bob.get_assigned_instance_ids(), "bob was given nothing to do"
        assert ism.has_unlabeled_items_for_user(bob), (
            "bob holds items he has not annotated, so he has work; saying "
            "otherwise moves him to DONE and his answers are written to the "
            "phase store instead of the instance store"
        )
        assert bob.has_remaining_assignments()

    def test_they_are_finished_once_they_have_answered(self, ism):
        alice = _annotator("alice")
        ism.assign_instances_to_user(alice)
        _annotate_all(ism, alice)

        bob = _annotator("bob")
        ism.assign_instances_to_user(bob)
        _annotate_all(ism, bob)

        assert not ism.has_unlabeled_items_for_user(bob), (
            "every item now has both its annotators, so bob really is done"
        )


class TestTheSurplusAnnotatorIsUnaffected:
    """Holding nothing is still holding nothing — this must not hand out work."""

    def test_an_annotator_with_no_assignment_has_no_work(self, ism):
        holders = []
        for name in ("alice", "bob"):
            state = _annotator(name)
            ism.assign_instances_to_user(state)
            _annotate_all(ism, state)
            holders.append(state)

        carol = _annotator("carol")
        ism.assign_instances_to_user(carol)

        assert not carol.get_assigned_instance_ids()
        assert not ism.has_unlabeled_items_for_user(carol)
