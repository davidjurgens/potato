"""
Unit tests for the adaptive boost path in ItemStateManager.

We mock the UserStateManager to control what disagreement looks like.
"""

from unittest.mock import MagicMock, patch

import pytest

from potato.item_state_management import ItemStateManager


@pytest.fixture
def config():
    return {
        "random_seed": 7,
        "num_annotators_per_item": {
            "default": 1,
            "adaptive": {"enabled": True, "disagreement_threshold": 0.5, "boost_to": 3},
        },
    }


def _make_label(name):
    m = MagicMock()
    m.name = name
    return m


def _make_user_state(label_by_iid):
    ustate = MagicMock()
    ustate.get_label_annotations.side_effect = lambda iid: label_by_iid.get(iid, {})
    ustate.get_span_annotations.return_value = {}
    return ustate


class TestAdaptiveBoost:
    def test_boost_fires_on_disagreement(self, config):
        ism = ItemStateManager(config)
        ism.add_item("item_1", {"text": "x"})

        # Two annotators give different labels for the same schema
        users = {
            "u1": _make_user_state({"item_1": {"sentiment": [_make_label("pos")]}}),
            "u2": _make_user_state({"item_1": {"sentiment": [_make_label("neg")]}}),
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
            "u1": _make_user_state({"item_1": {"sentiment": [_make_label("pos")]}}),
            "u2": _make_user_state({"item_1": {"sentiment": [_make_label("pos")]}}),
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
            "u1": _make_user_state({"item_1": {"sentiment": [_make_label("pos")]}}),
            "u2": _make_user_state({"item_1": {"sentiment": [_make_label("neg")]}}),
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
