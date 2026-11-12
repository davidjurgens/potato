"""
Unit tests for the adaptive boost path in ItemStateManager.

We mock the UserStateManager to control what disagreement looks like.
"""

from unittest.mock import MagicMock, patch

import pytest

from potato.item_state_management import ItemStateManager, Label
from potato.phase import UserPhase


@pytest.fixture
def config():
    return {
        "random_seed": 7,
        "num_annotators_per_item": {
            "default": 1,
            "adaptive": {"enabled": True, "disagreement_threshold": 0.5, "boost_to": 3},
        },
    }


def _make_user_state(answers_by_iid):
    """A stand-in for the real accessor, returning the shape it really returns.

    ``get_label_annotations`` hands back the FLAT ``{Label: value}`` container,
    not ``{schema_name: [label, ...]}``. These fixtures used to mock the nested
    shape, so they exercised a contract the production code has never produced
    -- which is how `_calculate_disagreement_score` shipped returning 0.0 for
    every item with three unit tests reporting that adaptive boost worked.

    ``answers_by_iid`` is ``{instance_id: {schema: label_name}}``; the stored
    value is the radio convention, ``{"pos": True}`` flattened onto the key.
    """
    ustate = MagicMock()

    def _labels(iid):
        return {Label(schema, name): True
                for schema, name in answers_by_iid.get(iid, {}).items()}

    ustate.get_label_annotations.side_effect = _labels
    ustate.get_span_annotations.return_value = {}
    return ustate


class TestAdaptiveBoost:
    def test_boost_fires_on_disagreement(self, config):
        ism = ItemStateManager(config)
        ism.add_item("item_1", {"text": "x"})

        # Two annotators give different labels for the same schema
        users = {
            "u1": _make_user_state({"item_1": {"sentiment": "pos"}}),
            "u2": _make_user_state({"item_1": {"sentiment": "neg"}}),
        }
        usm = MagicMock()
        usm.get_user_state.side_effect = lambda uid: users.get(uid)

        with patch("potato.user_state_management.get_user_state_manager", return_value=usm):
            ism.register_annotator("item_1", "u1")
            ism.register_annotator("item_1", "u2")

        item = ism.instance_id_to_instance["item_1"]
        assert item.get_metadata("required_annotations") == 3

    def test_no_boost_when_users_agree(self, config):
        ism = ItemStateManager(config)
        ism.add_item("item_1", {"text": "x"})

        users = {
            "u1": _make_user_state({"item_1": {"sentiment": "pos"}}),
            "u2": _make_user_state({"item_1": {"sentiment": "pos"}}),
        }
        usm = MagicMock()
        usm.get_user_state.side_effect = lambda uid: users.get(uid)

        with patch("potato.user_state_management.get_user_state_manager", return_value=usm):
            ism.register_annotator("item_1", "u1")
            ism.register_annotator("item_1", "u2")

        item = ism.instance_id_to_instance["item_1"]
        assert item.get_metadata("required_annotations") is None

    def test_boost_re_adds_completed_item(self, config):
        ism = ItemStateManager(config)
        ism.add_item("item_1", {"text": "x"})

        users = {
            "u1": _make_user_state({"item_1": {"sentiment": "pos"}}),
            "u2": _make_user_state({"item_1": {"sentiment": "neg"}}),
        }
        usm = MagicMock()
        usm.get_user_state.side_effect = lambda uid: users.get(uid)

        with patch("potato.user_state_management.get_user_state_manager", return_value=usm):
            ism.register_annotator("item_1", "u1")  # cap=1, hits saturation
            assert "item_1" in ism.completed_instance_ids
            ism.register_annotator("item_1", "u2")  # disagreement -> boost to 3

        # After boost: cap=3, count=2 -> not saturated, should be available again
        assert "item_1" not in ism.completed_instance_ids
        assert "item_1" in ism.remaining_instance_ids


def _review_config(**schemes):
    """Two reviewers per item, a third on disagreement, with real schemes."""
    return {
        "random_seed": 7,
        "num_annotators_per_item": {
            "default": 2,
            "adaptive": {"enabled": True, "disagreement_threshold": 0.5, "boost_to": 3},
        },
        "annotation_schemes": [
            {"annotation_type": "radio", "name": "triage", "labels": ["empty", "animal"]},
            {"annotation_type": "radio", "name": "species", "labels": ["deer", "fox"]},
            {"annotation_type": "text", "name": "notes"},
        ],
    }


def _run(users, steps):
    ism = ItemStateManager(_review_config())
    ism.add_item("item_1", {"text": "x"})
    usm = MagicMock()
    usm.get_user_state.side_effect = lambda uid: users.get(uid)
    with patch("potato.user_state_management.get_user_state_manager", return_value=usm):
        for step in steps:
            step(ism, users)
    return ism.instance_id_to_instance["item_1"].get_metadata("required_annotations")


def _register(uid):
    return lambda ism, users: ism.register_annotator("item_1", uid)


class TestBlankAnswersDisagree:
    def test_a_species_left_blank_beside_a_named_one_escalates(self):
        users = {
            "u1": _make_user_state({"item_1": {"triage": "animal", "species": "deer"}}),
            "u2": _make_user_state({"item_1": {"triage": "animal"}}),
        }
        assert _run(users, [_register("u1"), _register("u2")]) == 3

    def test_a_note_one_reviewer_wrote_is_not_a_disagreement(self):
        users = {
            "u1": _make_user_state({"item_1": {"triage": "animal", "notes": "text_box"}}),
            "u2": _make_user_state({"item_1": {"triage": "animal"}}),
        }
        assert _run(users, [_register("u1"), _register("u2")]) is None


class TestACorrectedMisclickIsNotEscalated:
    def test_the_boost_is_withdrawn_when_the_answers_agree_again(self):
        users = {
            "u1": _make_user_state({"item_1": {"triage": "animal"}}),
            "u2": _make_user_state({"item_1": {"triage": "empty"}}),   # misclick
        }

        def correct(ism, users):
            assert ism.instance_id_to_instance["item_1"].get_metadata(
                "required_annotations") == 3
            users["u2"] = _make_user_state({"item_1": {"triage": "animal"}})
            ism.register_annotator("item_1", "u2")                    # autosave

        cap = _run(users, [_register("u1"), _register("u2"), correct])
        assert cap is None

    def test_a_third_reviewer_already_handed_the_item_keeps_it(self):
        users = {
            "u1": _make_user_state({"item_1": {"triage": "animal"}}),
            "u2": _make_user_state({"item_1": {"triage": "empty"}}),
        }

        def expert_takes_it_then_correct(ism, users):
            ism.instance_assignees["item_1"].add("expert")
            users["u2"] = _make_user_state({"item_1": {"triage": "animal"}})
            ism.register_annotator("item_1", "u2")

        assert _run(users, [_register("u1"), _register("u2"),
                            expert_takes_it_then_correct]) == 3


class TestAHalfFinishedItemIsNotADisagreement:
    def test_a_question_not_reached_yet_does_not_escalate(self):
        """An autosave after the first question carries the rest as blanks;
        u2 was still on the item, and a third annotator got an item both
        agreed on."""
        users = {
            "u1": _make_user_state({"item_1": {"triage": "animal", "species": "deer"}}),
            "u2": _make_user_state({"item_1": {"triage": "animal"}}),
        }
        users["u2"].get_current_instance_id.return_value = "item_1"
        users["u2"].get_phase.return_value = UserPhase.ANNOTATION
        assert _run(users, [_register("u1"), _register("u2")]) is None

    def test_the_blank_counts_once_the_annotator_moves_on(self):
        users = {
            "u1": _make_user_state({"item_1": {"triage": "animal", "species": "deer"}}),
            "u2": _make_user_state({"item_1": {"triage": "animal"}}),
        }
        users["u2"].get_current_instance_id.return_value = "item_1"
        users["u2"].get_phase.return_value = UserPhase.ANNOTATION

        def moves_on(ism, users):
            # Next: the route checks the item again once u2 is on the next one.
            users["u2"].get_current_instance_id.return_value = "item_2"
            ism.reevaluate_adaptive_boost("item_1")

        assert _run(users, [_register("u1"), _register("u2"), moves_on]) == 3

    def test_a_question_display_logic_can_hide_is_not_counted_blank(self):
        config = _review_config()
        config["annotation_schemes"][1]["display_logic"] = {
            "show_when": [{"schema": "triage", "operator": "equals", "value": "animal"}]}
        ism = ItemStateManager(config)
        ism.add_item("item_1", {"text": "x"})
        users = {
            "u1": _make_user_state({"item_1": {"triage": "animal", "species": "deer"}}),
            "u2": _make_user_state({"item_1": {"triage": "animal"}}),
        }
        usm = MagicMock()
        usm.get_user_state.side_effect = lambda uid: users.get(uid)
        with patch("potato.user_state_management.get_user_state_manager", return_value=usm):
            ism.register_annotator("item_1", "u1")
            ism.register_annotator("item_1", "u2")
        assert ism.instance_id_to_instance["item_1"].get_metadata("required_annotations") is None
