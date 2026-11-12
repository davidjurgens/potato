"""
AI cost estimate and spend cap.

The loudest money complaint about commercial annotation platforms is not the
price -- it is the surprise: credits consumed by auto-labelling and discovered
at export time, when the work is done and the bill is owed. Potato's
bring-your-own-key model avoids the lock-in and reproduces the surprise
exactly.

Two properties matter more than accuracy, and both are about what happens when
the tool does NOT know something:

* an unpriced model reports ``cost: None``, never zero. "Free" and "unknown"
  are different, and only one is safe to budget against.
* the cap is checked BEFORE the first call. Halting halfway leaves a
  part-labelled dataset and a bill for it, which is the worst of both.
"""

from __future__ import annotations

import pytest

from potato.ai import cost


class TestPricing:
    def test_the_longest_prefix_wins(self):
        """
        gpt-4o-mini costs a sixteenth of gpt-4o. Getting that backwards is a
        sixteen-fold overstatement, in the direction that stops people using
        the feature at all.
        """
        mini = cost.price_for("gpt-4o-mini-2026-01")
        full = cost.price_for("gpt-4o-2026-01")
        assert mini != full
        assert mini[0] < full[0]

    def test_an_unknown_model_has_no_price(self):
        assert cost.price_for("some-new-model-nobody-has-heard-of") is None

    def test_self_hosted_is_priced_at_zero_not_unknown(self):
        """
        The marginal cost of a local call is electricity. Zero is the correct
        price, not a missing one.
        """
        assert cost.price_for("llama-3-70b", endpoint_type="vllm") == (0.0, 0.0)
        assert cost.price_for("anything", endpoint_type="ollama") == (0.0, 0.0)

    def test_matching_is_case_insensitive(self):
        assert cost.price_for("GPT-4O-MINI") is not None


class TestEstimate:
    def test_tokens_scale_with_the_text(self):
        small = cost.estimate(["hi"], "gpt-4o-mini")
        large = cost.estimate(["hi" * 1000], "gpt-4o-mini")
        assert large.input_tokens > small.input_tokens

    def test_output_is_counted_at_the_configured_maximum(self):
        """
        An estimate that assumes short answers is the one that surprises you.
        """
        e = cost.estimate(["x"] * 10, "gpt-4o-mini", max_output_tokens=500)
        assert e.output_tokens == 5000

    def test_prompt_overhead_is_charged_per_item(self):
        """
        The rubric and label list ride along with EVERY item. Leaving them out
        understates a short-text project by more than the items themselves.
        """
        bare = cost.estimate(["x"] * 100, "gpt-4o-mini", prompt_overhead_chars=0)
        real = cost.estimate(["x"] * 100, "gpt-4o-mini",
                             prompt_overhead_chars=600)
        assert real.input_tokens > bare.input_tokens * 10

    def test_multiple_calls_per_item_multiply_the_cost(self):
        """
        The position-bias probe judges everything twice. An estimate that
        halved its cost would be exactly the surprise this prevents.
        """
        once = cost.estimate(["x" * 100] * 10, "gpt-4o", calls_per_item=1)
        twice = cost.estimate(["x" * 100] * 10, "gpt-4o", calls_per_item=2)
        assert twice.total_tokens == once.total_tokens * 2
        assert twice.cost_usd == pytest.approx(once.cost_usd * 2)
        assert any("2 times per item" in n for n in twice.notes)

    def test_an_unpriced_model_reports_none_not_zero(self):
        """
        The defect that matters. Zero reads as "this is free" and gets
        budgeted against; None reads as "we do not know".
        """
        e = cost.estimate(["x"], "mystery-model-9000")
        assert e.cost_usd is None
        assert e.priced is False
        assert e.total_tokens > 0
        assert any("No price on record" in n for n in e.notes)

    def test_a_local_model_is_priced_at_zero_and_says_why(self):
        e = cost.estimate(["x" * 500], "llama-3", endpoint_type="vllm")
        assert e.cost_usd == 0.0
        assert e.priced is True
        assert e.local is True
        assert e.total_tokens > 0, "tokens still predict how long the run takes"
        assert any("Self-hosted" in n for n in e.notes)
        assert "self-hosted" in e.summary()

    def test_an_empty_batch_is_not_described_as_self_hosted(self):
        """
        An empty batch on a PAID model also costs zero. Inferring "self-hosted"
        from cost == 0 made a claim about someone's infrastructure that
        happened to be wrong -- found by running the estimate endpoint on a
        project with nothing to judge.
        """
        e = cost.estimate([], "gpt-4o", endpoint_type="openai")
        assert e.cost_usd == 0.0
        assert e.local is False
        assert "self-hosted" not in e.summary()
        assert e.summary() == "Nothing to run."

    def test_every_estimate_carries_the_price_date(self):
        """A stale price is still useful; a stale price presented as a quote
        is not."""
        assert cost.estimate(["x"], "gpt-4o").as_of == cost.PRICES_AS_OF

    def test_the_summary_never_calls_itself_a_quote(self):
        assert "not a quote" in cost.estimate(["x" * 1000], "gpt-4o").summary()

    def test_the_summary_says_unknown_when_it_is(self):
        assert "unknown" in cost.estimate(["x"], "mystery-9000").summary()

    def test_an_empty_batch_costs_nothing(self):
        e = cost.estimate([], "gpt-4o")
        assert e.n_items == 0
        assert e.total_tokens == 0
        assert e.cost_usd == 0.0
        assert e.local is False


class TestTheCap:
    def test_no_cap_configured_never_refuses(self):
        cost.check_before_running({}, cost.estimate(["x" * 10**6] * 100, "gpt-4o"))

    def test_a_run_within_the_cap_is_allowed(self):
        config = {"ai_budget": {"cap_usd": 100.0}}
        cost.check_before_running(config, cost.estimate(["x" * 100], "gpt-4o-mini"))

    def test_a_run_over_the_cap_is_refused_before_it_starts(self):
        config = {"ai_budget": {"cap_usd": 0.01}}
        projected = cost.estimate(["x" * 4000] * 500, "gpt-4o")
        with pytest.raises(cost.SpendCapExceeded) as exc:
            cost.check_before_running(config, projected)
        assert "Nothing has been run" in str(exc.value)
        assert exc.value.cap == pytest.approx(0.01)

    def test_money_already_spent_counts_toward_the_cap(self):
        """Otherwise the cap is per-run, which caps nothing."""
        config = {"ai_budget": {"cap_usd": 1.0}}
        projected = cost.estimate(["x" * 400] * 100, "gpt-4o")
        cost.check_before_running(config, projected, spent_usd=0.0)
        with pytest.raises(cost.SpendCapExceeded):
            cost.check_before_running(config, projected, spent_usd=0.99)

    def test_an_unpriced_model_does_not_block(self, caplog):
        """
        The cap is a dollar ceiling and there is no dollar figure to compare
        against. Refusing a run that might be free, or waving through one that
        might not be, are both worse than saying so.
        """
        config = {"ai_budget": {"cap_usd": 0.01}}
        with caplog.at_level("WARNING"):
            cost.check_before_running(config, cost.estimate(["x"], "mystery-9000"))
        assert "no price on record" in caplog.text

    def test_a_malformed_cap_is_ignored_with_a_warning(self, caplog):
        with caplog.at_level("WARNING"):
            assert cost.cap_for({"ai_budget": {"cap_usd": "lots"}}) is None
        assert "not a number" in caplog.text

    def test_the_message_says_what_to_do(self):
        config = {"ai_budget": {"cap_usd": 0.01}}
        with pytest.raises(cost.SpendCapExceeded) as exc:
            cost.check_before_running(
                config, cost.estimate(["x" * 4000] * 500, "gpt-4o"))
        message = str(exc.value)
        assert "ai_budget.cap_usd" in message
        assert "fewer items" in message


class TestRunningTotal:
    @pytest.fixture
    def config(self, tmp_path):
        return {"task_dir": str(tmp_path), "annotation_task_name": "proj"}

    def test_spend_accumulates(self, config):
        cost.record_spend(config, "judge_batch",
                          cost.estimate(["x" * 4000] * 10, "gpt-4o"))
        cost.record_spend(config, "judge_batch",
                          cost.estimate(["x" * 4000] * 10, "gpt-4o"))
        total = cost.total_spend(config)
        assert total["n_runs"] == 2
        assert total["cost_usd"] > 0

    def test_unpriced_runs_are_counted_apart_from_the_dollar_total(self, config):
        """
        Folding them in as zero would report a project using an unpriced model
        as having spent nothing.
        """
        cost.record_spend(config, "judge_batch",
                          cost.estimate(["x" * 4000] * 10, "mystery-9000"))
        total = cost.total_spend(config)
        assert total["cost_usd"] == 0
        assert total["n_unpriced_runs"] == 1
        assert total["total_tokens"] > 0
        assert "no price on record" in total["note"]

    def test_estimated_and_measured_are_distinguishable(self, config):
        """
        A total that silently mixes them cannot be checked against an invoice,
        which is the only way anyone finds out the estimate was wrong.
        """
        cost.record_spend(config, "a", cost.estimate(["x"], "gpt-4o"),
                          estimated=True)
        cost.record_spend(config, "b", cost.estimate(["x"], "gpt-4o"),
                          estimated=False)
        flags = {r["action"]: r["estimated"] for r in
                 cost.total_spend(config)["runs"]}
        assert flags == {"a": 1, "b": 0}

    def test_the_configured_cap_is_reported_alongside(self, config):
        config["ai_budget"] = {"cap_usd": 25.0}
        assert cost.total_spend(config)["cap_usd"] == pytest.approx(25.0)

    def test_an_unwritable_database_does_not_raise(self):
        """
        A run that happened but was not logged beats an exception after the
        model has already been paid for.
        """
        broken = {"task_dir": "/nonexistent/nowhere"}
        cost.record_spend(broken, "x", cost.estimate(["x"], "gpt-4o"))
        assert cost.total_spend(broken)["n_runs"] == 0

    def test_a_clean_project_reports_zero_not_an_error(self, config):
        total = cost.total_spend(config)
        assert total["n_runs"] == 0
        assert total["cost_usd"] == 0
        assert total["note"] == ""


class TestConfigRegistration:
    def test_the_keys_are_recognized(self):
        from potato.server_utils.config_module import KNOWN_CONFIG_KEYS

        assert "ai_budget" in KNOWN_CONFIG_KEYS
        assert "cap_usd" in KNOWN_CONFIG_KEYS["ai_budget"]

    def test_the_keys_are_documented(self):
        from potato.server_utils.config_key_docs import CONFIG_KEY_DOCS

        assert "ai_budget" in CONFIG_KEY_DOCS
        assert "ai_budget.cap_usd" in CONFIG_KEY_DOCS
