"""
The LLM-judge position-bias diagnostic.

Practitioners running judge pipelines describe the same check: swap the
positions so the judge does not always pick the first option, then hand-label
a sample to see whether the judge is any good. The second half is human work.
The first half is arithmetic, and no annotation tool reports it.

What makes this worth reporting rather than just fixing: a judge whose verdict
flips when you reverse the label list is not making a judgement, and its
labels should not be treated as a reference. But a flip rate near zero is not
sufficient either -- a judge that always answers the same label is perfectly
order-invariant and perfectly useless. The summary has to distinguish those,
because they have different fixes.
"""

from __future__ import annotations

import pytest

from potato.ai import position_bias as pb

SCHEMA = {
    "annotation_type": "radio",
    "name": "tone",
    "description": "Tone",
    "labels": [{"name": "positive"}, {"name": "neutral"}, {"name": "negative"}],
}


class FakePrediction:
    def __init__(self, label):
        self.predicted_label = label


class FakeJudge:
    """A judge whose behaviour is a function of the label order it is given."""

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = []

    def judge_instance(self, instance_id, schema_info, instance_text,
                       few_shot_examples=None, label_order=None):
        self.calls.append((instance_id, tuple(label_order or ())))
        label = self.behaviour(instance_id, list(label_order or []))
        return FakePrediction(label) if label else None


def always_first(_iid, order):
    return order[0] if order else None


def always(label):
    return lambda _iid, _order: label


def probe(behaviour, n=30):
    judge = FakeJudge(behaviour)
    items = [{"instance_id": f"i{k}", "text": f"text {k}"} for k in range(n)]
    return pb.probe_batch(judge, SCHEMA, items), judge


class TestTheProbeItself:
    def test_each_item_is_judged_under_both_orders(self):
        results, judge = probe(always("positive"), n=3)
        assert len(judge.calls) == 6
        forward = ("positive", "neutral", "negative")
        assert judge.calls[0][1] == forward
        assert judge.calls[1][1] == tuple(reversed(forward))

    def test_only_the_label_order_changes(self):
        """
        Nothing about the item changes, so any difference in verdict is
        attributable to the order and nothing else.
        """
        _results, judge = probe(always("positive"), n=2)
        assert {call[0] for call in judge.calls} == {"i0", "i1"}

    def test_a_failed_call_is_not_counted_as_a_flip(self):
        results = pb.probe_batch(
            FakeJudge(lambda _i, _o: None), SCHEMA,
            [{"instance_id": "i0", "text": "t"}])
        assert results[0].usable is False
        assert results[0].flipped is None
        assert pb.summarize(results)["n_usable"] == 0

    def test_one_raising_item_does_not_lose_the_whole_probe(self):
        """The calls already made are the expensive part."""
        class Flaky(FakeJudge):
            def judge_instance(self, instance_id, *a, **k):
                if instance_id == "i1":
                    raise RuntimeError("timeout")
                return super().judge_instance(instance_id, *a, **k)

        judge = Flaky(always("positive"))
        items = [{"instance_id": f"i{k}", "text": "t"} for k in range(3)]
        assert len(pb.probe_batch(judge, SCHEMA, items)) == 2

    def test_progress_is_reported(self):
        """It makes twice as many model calls as a normal pass."""
        seen = []
        judge = FakeJudge(always("positive"))
        pb.probe_batch(judge, SCHEMA,
                       [{"instance_id": "i0", "text": "t"},
                        {"instance_id": "i1", "text": "t"}],
                       on_progress=lambda done, total: seen.append((done, total)))
        assert seen == [(1, 2), (2, 2)]


class TestSummaryDistinguishesTheFailureModes:
    def test_a_first_position_judge_is_named_as_such(self):
        results, _ = probe(always_first)
        summary = pb.summarize(results)
        assert summary["flip_rate"] == pytest.approx(1.0)
        assert summary["first_position_rate"]["configured_order"] == pytest.approx(1.0)
        assert summary["first_position_rate"]["reversed_order"] == pytest.approx(1.0)
        assert "position preference" in summary["verdict"]

    def test_an_order_invariant_judge_passes(self):
        results, _ = probe(lambda iid, _o: ["positive", "negative"][int(iid[1:]) % 2])
        summary = pb.summarize(results)
        assert summary["flip_rate"] == pytest.approx(0.0)
        assert "order-invariant" in summary["verdict"]

    def test_a_constant_judge_is_flagged_despite_zero_flips(self):
        """
        The trap. A judge that always answers the same thing is perfectly
        order-invariant, and a flip rate alone calls that a pass.
        """
        results, _ = probe(always("positive"))
        summary = pb.summarize(results)
        assert summary["flip_rate"] == pytest.approx(0.0)
        assert summary["stable_label_rate"] == pytest.approx(1.0)
        assert summary["stable_label"] == "positive"
        assert "always answers the same" in summary["verdict"]

    def test_an_inconsistent_judge_is_distinguished_from_a_biased_one(self):
        """
        Flips without a first-position pull are noise, not bias, and the two
        have different fixes -- randomising order does not help the first.
        """
        def noisy(iid, order):
            n = int(iid[1:])
            # Flips on half the items, but never toward a consistent position.
            if n % 2:
                return order[-1]
            return "neutral"

        summary = pb.summarize(probe(noisy)[0])
        assert summary["flip_rate"] > 0.2
        assert summary["first_position_rate"]["configured_order"] < 0.7
        assert "not reading the item consistently" in summary["verdict"]


class TestReliability:
    def test_a_small_probe_is_reported_but_flagged(self):
        """
        A probe that says "5 items, 2 flips" beats silence, so the numbers are
        returned -- but nobody should quote them as a finding.
        """
        summary = pb.summarize(probe(always_first, n=5)[0])
        assert summary["n_usable"] == 5
        assert summary["reliable"] is False
        assert "smoke test" in summary["verdict"]

    def test_a_large_enough_probe_is_reliable(self):
        summary = pb.summarize(probe(always_first, n=pb.MIN_PAIRS)[0])
        assert summary["reliable"] is True
        assert "smoke test" not in summary["verdict"]

    def test_nothing_usable_says_so_rather_than_reporting_zero(self):
        summary = pb.summarize([])
        assert summary["flip_rate"] is None
        assert "nothing can be said" in summary["verdict"]

    def test_the_empty_summary_has_every_key_the_full_one_does(self):
        """
        Otherwise a consumer raises a KeyError exactly when there is no data
        -- the case a report most needs to survive. Found by running the
        probe against a misconfigured endpoint.
        """
        full = pb.summarize(probe(always_first, n=3)[0])
        assert set(pb.summarize([])) == set(full)

    def test_the_flip_rate_is_the_one_judge_bias_already_defined(self):
        """
        `position_swap_consistency` defined this measure and its severity
        bands and had no caller. Two definitions of one number is how the
        eval card and this report would come to disagree.
        """
        summary = pb.summarize(probe(always_first, n=25)[0])
        assert summary["swap"]["flip_rate"] == summary["flip_rate"]
        assert summary["swap"]["interpretation"] == "severe position bias"
        assert summary["swap"]["compared"] == 25


class TestPromptLabelOrder:
    def test_the_prompt_lists_labels_in_the_requested_order(self):
        from potato.ai.judge import JudgeService

        service = JudgeService({})
        prompt = service.build_prompt(SCHEMA, "an item",
                                      label_order=["negative", "positive",
                                                   "neutral"])
        line = next(l for l in prompt.splitlines()
                    if l.startswith("Allowed labels:"))
        assert line == "Allowed labels: negative, positive, neutral"

    def test_an_unknown_label_in_the_order_is_ignored(self):
        from potato.ai.judge import JudgeService

        prompt = JudgeService({}).build_prompt(
            SCHEMA, "an item", label_order=["ghost", "negative"])
        line = next(l for l in prompt.splitlines()
                    if l.startswith("Allowed labels:"))
        assert "ghost" not in line

    def test_a_partial_order_still_offers_every_label(self):
        """
        A stale order must not silently drop an option from the prompt: the
        judge would then be unable to give an answer the schema allows.
        """
        from potato.ai.judge import JudgeService

        prompt = JudgeService({}).build_prompt(
            SCHEMA, "an item", label_order=["negative"])
        line = next(l for l in prompt.splitlines()
                    if l.startswith("Allowed labels:"))
        assert line == "Allowed labels: negative, positive, neutral"

    def test_no_order_leaves_the_configured_one(self):
        from potato.ai.judge import JudgeService

        prompt = JudgeService({}).build_prompt(SCHEMA, "an item")
        line = next(l for l in prompt.splitlines()
                    if l.startswith("Allowed labels:"))
        assert line == "Allowed labels: positive, neutral, negative"


class TestItReachesTheEvalCard:
    """
    `build_eval_card` has had a `position` slot since it was written, always
    fed None because nothing could supply the pair of verdicts. These pin the
    wiring that finally fills it.
    """

    def test_a_biased_probe_becomes_a_concern_on_the_card(self):
        from potato.server_utils.judge_bias import eval_cards_from_pairs

        summary = pb.summarize(probe(always_first, n=25)[0])
        cards = eval_cards_from_pairs(
            {"tone": [("i0", "positive", "positive", 0.9, "")]},
            {"tone": {"kappa": 0.9, "agreement_rate": 0.95}},
            lambda _i: 100,
            position_by_schema={"tone": summary["swap"]},
        )
        card = cards["tone"]
        assert card["position"]["flip_rate"] == pytest.approx(1.0)
        assert "severe position bias" in card["concerns"]
        assert card["verdict"] != "trustworthy"

    def test_an_order_robust_probe_raises_no_concern(self):
        from potato.server_utils.judge_bias import eval_cards_from_pairs

        summary = pb.summarize(
            probe(lambda iid, _o: ["positive", "negative"][int(iid[1:]) % 2])[0])
        cards = eval_cards_from_pairs(
            {"tone": [("i0", "positive", "positive", 0.9, "")]},
            {"tone": {"kappa": 0.9, "agreement_rate": 0.95}},
            lambda _i: 100,
            position_by_schema={"tone": summary["swap"]},
        )
        assert cards["tone"]["position"]["interpretation"] == "robust to order"
        assert not any("position" in c for c in cards["tone"]["concerns"])

    def test_no_probe_leaves_the_slot_empty_as_before(self):
        from potato.server_utils.judge_bias import eval_cards_from_pairs

        cards = eval_cards_from_pairs(
            {"tone": [("i0", "positive", "positive", 0.9, "")]},
            {"tone": {"kappa": 0.9, "agreement_rate": 0.95}},
            lambda _i: 100)
        assert cards["tone"]["position"] is None
