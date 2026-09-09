"""
The running AI total is charged for the calls that happened, not the ones a
projection covered.

`ai_budget.cap_usd` is checked against `total_spend`, so every dollar in that
table decides whether the NEXT batch is allowed to run. Both batch runners
recorded the whole projection inside the cap check -- after the estimate, before
the first model call. Any batch that then ran fewer items than were projected
was charged for the difference, and the error only ever runs one way, because a
run cannot do more work than it was priced for.

Stopping short is not the rare case. A judge service that goes away mid-batch
raises out of the loop, and a position-bias probe over three schemes can die on
the second. The projection covered all of it; the money was spent on part of
it; the total kept the whole number, and the next batch was refused against
money nobody spent.

What is deliberately NOT changed: a call that reached the model and came back
empty is still charged. It was billed. `judged` and `failed` both count.

These tests drive the real batch functions with a judge that works, one that
returns nothing, and one that raises partway, and read the spend table back.
"""

import pytest

from potato.ai import cost
from potato.ai.cost import estimate


# --------------------------------------------------------------------------
# CostEstimate.rescaled: the arithmetic the recording depends on
# --------------------------------------------------------------------------

class TestRescaled:

    def test_half_a_batch_costs_about_half(self):
        full = estimate(["an item to label"] * 100, "gpt-4o-mini", "")
        half = full.rescaled(50)
        assert full.cost_usd is not None, "fixture lost its price"
        assert half.cost_usd == pytest.approx(full.cost_usd / 2, rel=1e-6)
        assert half.n_items == 50

    def test_no_items_attempted_costs_nothing(self):
        full = estimate(["an item"] * 10, "gpt-4o-mini", "")
        assert full.rescaled(0).cost_usd == 0.0
        assert full.rescaled(0).total_tokens == 0

    def test_it_never_scales_up(self):
        """A run cannot attempt more than was projected, and if the counters
        say otherwise the projection is what we know -- inventing spend from a
        miscount is worse than under-reporting it."""
        full = estimate(["an item"] * 10, "gpt-4o-mini", "")
        assert full.rescaled(999) is full
        assert full.rescaled(10) is full

    def test_an_unpriced_model_stays_unpriced(self):
        """None means 'no price on record'. Scaling it to 0.0 would report an
        unpriced run as free, which is the one reading `total_spend` goes out
        of its way to avoid."""
        u = estimate(["an item"] * 10, "a-model-with-no-price", "")
        assert u.cost_usd is None
        assert u.rescaled(5).cost_usd is None

    def test_the_scaling_is_disclosed(self):
        full = estimate(["an item"] * 10, "gpt-4o-mini", "")
        note = " ".join(full.rescaled(3).notes)
        assert "3" in note and "10" in note, note

    def test_an_empty_projection_does_not_divide_by_zero(self):
        empty = estimate([], "gpt-4o-mini", "")
        assert empty.rescaled(0) is empty


# --------------------------------------------------------------------------
# The batch runners
# --------------------------------------------------------------------------

@pytest.fixture
def project(tmp_path):
    """A judge-alignment config with one schema and a $1 cap."""
    return {
        "task_dir": str(tmp_path),
        "annotation_task_name": "audit33",
        "annotation_schemes": [
            {"annotation_type": "radio", "name": "sentiment",
             "description": "Sentiment", "labels": ["pos", "neg"]},
        ],
        # The model lives at ai_support.ai_config.model -- that is the path
        # estimate_batch_cost reads, and a config that puts it anywhere else
        # prices the run at "" and quietly stops the cap binding.
        "ai_support": {"endpoint_type": "openai",
                       "ai_config": {"model": "gpt-4o-mini",
                                     "max_tokens": 100}},
        "ai_budget": {"cap_usd": 1.00},
        "judge_alignment": {"enabled": True},
    }


ITEM_TEXT = "a sentence to judge, about this long"


def _reference(n_items):
    """What `n_items` of ITEM_TEXT costs on gpt-4o-mini, with the judge
    batch's own overhead figures written out here on purpose: a test that
    asked the code under test for its expected value would agree with any
    bug in it."""
    return estimate([ITEM_TEXT] * n_items, "gpt-4o-mini", "openai",
                    prompt_overhead_chars=600, max_output_tokens=100)


def _spend(project_cfg):
    """(dollar total, number of recorded runs)."""
    total = cost.total_spend(project_cfg)
    return total["cost_usd"], total["n_runs"]


class TestBatchSpendFollowsTheWork:
    """Drives `run_judge_batch` with a stubbed JudgeService."""

    def _run(self, project_cfg, monkeypatch, judge_instance, n_items=10):
        from potato.server_utils import judge_alignment as ja

        ids = [f"item-{i}" for i in range(n_items)]

        class _Item:
            def __init__(self, iid):
                self._iid = iid

            def get_text(self):
                return ITEM_TEXT

        class _ISM:
            def get_item(self, iid):
                return _Item(iid)

        class _Service:
            def __init__(self, cfg):
                pass

            def judge_instance(self, iid, schema, text, few_shot_examples=None):
                return judge_instance(iid)

        # Both are imported inside the function, so they are patched on the
        # modules they come from rather than on judge_alignment.
        import potato.ai.judge as judge_mod
        import potato.item_state_management as ism_mod

        monkeypatch.setattr(ism_mod, "get_item_state_manager", lambda: _ISM())
        monkeypatch.setattr(judge_mod, "JudgeService", _Service)
        monkeypatch.setattr(ja, "annotated_instance_ids",
                            lambda users, schema_name: list(ids))
        monkeypatch.setattr(ja, "save_prediction", lambda cfg, pred: None)
        return ja.run_judge_batch(project_cfg, ["annotator-a"])

    def test_a_batch_that_fails_every_call_is_not_charged_in_full(
            self, project, monkeypatch):
        """A batch that judged nothing still reached the model ten times, so
        it is charged for ten. Pinned because the obvious "fix" for the drift
        is to charge only successes, which would let a project that fails
        every call run forever against a cap it never touches."""
        result = self._run(project, monkeypatch, lambda iid: None)
        assert result["failed"] == 10 and result["judged"] == 0

        spent, n_runs = _spend(project)
        assert n_runs == 1, "the run should be recorded exactly once"
        full = _reference(10)
        assert spent == pytest.approx(full.cost_usd, rel=1e-6), (
            "a batch of ten failed calls is ten calls' worth of spend")

    def test_a_batch_that_stops_short_is_charged_for_what_it_sent(
            self, project, monkeypatch):
        """Four of ten items reach the model before the service starts
        refusing. Charging ten is the drift; charging four is the fix."""
        seen = {"n": 0}

        def _judge(iid):
            seen["n"] += 1
            if seen["n"] > 4:
                raise RuntimeError("service went away")
            return _prediction(iid)

        with pytest.raises(RuntimeError):
            self._run(project, monkeypatch, _judge)

        spent, n_runs = _spend(project)
        assert n_runs == 1, (
            "a batch that raised partway still spent money; it must be "
            "recorded, or the next batch runs against a total that forgot it")

        full = _reference(10)
        assert spent < full.cost_usd * 0.75, (
            f"charged ${spent:.6f} for 4 of 10 items against a full "
            f"projection of ${full.cost_usd:.6f} -- the tail that never ran "
            "is being billed")

    def test_a_full_batch_is_charged_the_whole_projection(
            self, project, monkeypatch):
        """The fix must not under-charge the ordinary case."""
        result = self._run(project, monkeypatch, _prediction)
        assert result["judged"] == 10

        spent, _ = _spend(project)
        assert spent == pytest.approx(_reference(10).cost_usd, rel=1e-6)

    def test_a_refused_batch_is_not_charged_at_all(self, project, monkeypatch):
        """The cap refuses before the first call, so nothing was spent. A
        charge here would make one refusal cause the next."""
        project["ai_budget"]["cap_usd"] = 0.0000001
        from potato.ai.cost import SpendCapExceeded

        with pytest.raises(SpendCapExceeded):
            self._run(project, monkeypatch, _prediction)

        spent, n_runs = _spend(project)
        assert n_runs == 0 and spent == 0.0, (
            "a run that never happened was charged")

    def test_the_reported_estimate_matches_what_was_charged(
            self, project, monkeypatch):
        """The number in the response and the number in the spend table are
        the same number. A response that reports the full projection while the
        table records a third is two answers to one question."""
        seen = {"n": 0}

        def _judge(iid):
            seen["n"] += 1
            return None if seen["n"] > 3 else _prediction(iid)

        result = self._run(project, monkeypatch, _judge)
        reported = result["estimated_cost"]["cost_usd"]
        spent, _ = _spend(project)
        assert reported == pytest.approx(spent, rel=1e-6)


def _prediction(iid):
    class _Pred:
        prompt_version = "v1"
        instance_id = iid
        label = "pos"
    return _Pred()


# --------------------------------------------------------------------------
# The seam itself
# --------------------------------------------------------------------------

def test_the_cap_check_does_not_record(project, monkeypatch):
    """`check_batch_against_cap` must not write to the spend table: it runs
    before the first model call, and anything it records is a charge for work
    that has not happened yet."""
    from potato.server_utils.judge_alignment import check_batch_against_cap

    projected = estimate(["an item"] * 10, "gpt-4o-mini", "openai")
    check_batch_against_cap(project, projected, "judge_batch")

    _, n_runs = _spend(project)
    assert n_runs == 0, (
        "the cap check recorded spend. It runs BEFORE the batch, so the "
        "recording belongs in record_batch_spend, after it.")


def test_record_batch_spend_ignores_an_empty_run(project):
    from potato.server_utils.judge_alignment import record_batch_spend

    projected = estimate(["an item"] * 10, "gpt-4o-mini", "openai")
    record_batch_spend(project, projected, "judge_batch", 0)

    _, n_runs = _spend(project)
    assert n_runs == 0, "a run that attempted nothing left a row"
