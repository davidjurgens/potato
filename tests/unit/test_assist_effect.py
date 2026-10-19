"""
The no-assistance comparison group and the effect calculation.

assist_holdout decides, per (annotator, item), whether AI assistance is
withheld; assist_effect compares the two groups. Both are pure functions over
config and user state, tested here directly.
"""

import pytest

from potato.assist_effect import MIN_PAIRS, assist_effect
from potato.assist_holdout import (
    holdout_draw, holdout_settings, is_held_out, strip_holdout_fields,
)
from potato.item_state_management import Label

SCHEME = {"annotation_type": "radio", "name": "s", "description": "d", "labels": ["a", "b"]}


def config(fraction=0.5, salt="t"):
    return {"annotation_schemes": [SCHEME],
            "ai_support": {"enabled": True, "holdout": {"fraction": fraction, "salt": salt}},
            "pre_annotation": {"enabled": True, "field": "predictions"}}


class FakeState:
    def __init__(self, answers):
        self.answers = answers  # {iid: label}

    def get_annotated_instance_ids(self):
        return set(self.answers)

    def get_label_annotations(self, iid):
        return {Label("s", self.answers[iid]): self.answers[iid]}


class TestHoldout:
    def test_the_draw_is_deterministic_and_salted(self):
        assert holdout_draw("x", "u", "i") == holdout_draw("x", "u", "i")
        assert holdout_draw("x", "u", "i") != holdout_draw("y", "u", "i")

    def test_the_share_held_out_matches_the_fraction(self):
        cfg = config(0.25)
        held = sum(is_held_out(cfg, f"u{u}", f"i{i}") for u in range(40) for i in range(50))
        assert 0.22 < held / 2000 < 0.28

    def test_it_is_per_annotator_not_per_item(self):
        """Each item gets some held-out and some assisted annotators."""
        cfg = config(0.5)
        for i in range(20):
            groups = {is_held_out(cfg, f"u{u}", f"i{i}") for u in range(12)}
            assert groups == {True, False}

    def test_off_by_default(self):
        assert holdout_settings({}) == (0.0, "")
        assert not is_held_out({}, "u", "i")

    def test_the_prediction_field_is_stripped_for_a_held_out_pair(self):
        cfg = config(1.0)
        record = {"id": "i1", "text": "x", "predictions": {"s": "a"}}
        assert "predictions" not in strip_holdout_fields(cfg, record, "u", "i1")
        assert "predictions" in strip_holdout_fields(config(0.0), record, "u", "i1")


class TestEffect:
    def _arms(self, cfg, n_users=40, n_items=30):
        """Users who copy the model when assisted and answer 'b' when held out."""
        items = {f"i{i}": {"predictions": {"s": "a"}} for i in range(n_items)}
        states = {}
        for u in range(n_users):
            user = f"u{u}"
            states[user] = FakeState({
                iid: ("b" if is_held_out(cfg, user, iid) else "a") for iid in items})
        return states, items

    def test_anchoring_shows_as_a_difference_in_model_agreement(self):
        cfg = config(0.3)
        states, items = self._arms(cfg)
        report = assist_effect(cfg, states, items)["schemas"]["s"]
        assert report["assisted"]["model_agreement"] == 1.0
        assert report["held_out"]["model_agreement"] == 0.0
        assert report["model_agreement_difference"] == pytest.approx(1.0)
        low, high = report["difference_ci95"]
        assert low <= 1.0 <= high + 1e-9

    def test_gold_accuracy_is_reported_per_group(self):
        cfg = config(0.3)
        states, items = self._arms(cfg)
        gold = {iid: "b" for iid in items}
        report = assist_effect(cfg, states, items, gold)["schemas"]["s"]
        assert report["assisted"]["gold_accuracy"] == 0.0
        assert report["held_out"]["gold_accuracy"] == 1.0

    def test_a_unanimous_group_says_why_alpha_is_missing(self):
        """Found by the potato-skill agent: a null alpha with no note reads as
        "not computed" when it means everyone gave the same answer."""
        cfg = config(0.3)
        states, items = self._arms(cfg)
        report = assist_effect(cfg, states, items)["schemas"]["s"]
        assert report["held_out"]["alpha"] is None
        assert "every answer in this group is the same" in report["held_out"]["alpha_note"]
        assert "alpha_note" not in report["assisted"] or report["assisted"]["alpha"] is None

    def test_small_groups_are_not_compared(self):
        cfg = config(0.5)
        states, items = self._arms(cfg, n_users=2, n_items=3)
        report = assist_effect(cfg, states, items)["schemas"]["s"]
        assert "model_agreement_difference" not in report
        assert f"{MIN_PAIRS} each needed" in report["note"]

    def test_no_holdout_says_how_to_turn_it_on(self):
        report = assist_effect(config(0.0), {}, {})
        assert "ai_support.holdout.fraction" in report["note"]
