"""
A model priced from its family, not its own row, has to say so.

`price_for` matches the longest PRICE_TABLE prefix contained in the model name.
Its docstring gives the reason: "gpt-4o-mini costs a sixteenth of gpt-4o, and
getting that backwards is a sixteen-fold error in the direction that stops
people using the feature."

The rule only protects variants somebody listed. It prevents that error for
`gpt-4o-mini`, which has a row, and commits it for any variant nobody listed.
`gpt-4.1-nano` was the original specimen, inheriting `gpt-4.1` at twenty times
its real rate until the 2026-09-05 refresh gave it a row. Same family, same
shape, opposite outcome -- and the refresh did not change that, it only moved
which names are exposed.

The error runs both ways, and both were silent:

  unlisted new GENERATION  -> priced from an older, cheaper row
                              -> a cap lets spend through
  unlisted cheap VARIANT   -> priced from its expensive parent
                              -> a cap refuses runs that were affordable

An absent price already warned. A wrong one did not, which by the standard that
absent-and-logged beats confident-and-quiet made it the worse of the two. The
prices themselves are not fixed here: putting plausible numbers in a price table
is the highest-stakes possible place for a right-shaped invention, because the
number is never read by a human again -- it is read by a cap that silently
refuses or permits.
"""

import pytest

from potato.ai.cost import (SpendCapExceeded, check_before_running, estimate,
                            price_for, price_matched_exactly)

TEXTS = ["an item to label"] * 500


class TestExactness:
    @pytest.mark.parametrize("model", [
        "gpt-4o",            # a row, named exactly
        "gpt-4o-mini",       # its own row, not the parent's
        "gpt-4.1-mini",
        "o3-mini",
    ])
    def test_a_model_with_its_own_row_is_exact(self, model):
        assert price_matched_exactly(model) is True

    @pytest.mark.parametrize("model", [
        "gpt-4o-2024-08-06",
        "gpt-4o-20240806",
    ])
    def test_a_dated_snapshot_is_the_same_model(self, model):
        """Dated model ids are ordinary practice. Warning on every one
        would be noise, and noise is how a log stops being read."""
        assert price_matched_exactly(model) is True
        assert price_for(model) == price_for("gpt-4o")

    # These four had their own rows added in the 2026-09-05 refresh, so
    # they no longer inherit and cannot demonstrate the mechanism:
    # gpt-4.1-nano, claude-opus-5, claude-sonnet-5, claude-haiku-4-5.
    # Fixing the table does not fix the rule, which is the whole reason
    # `price_matched_exactly` exists: the next unlisted model inherits
    # exactly as they did. These are unlisted names of the shape the
    # vendors actually ship.
    @pytest.mark.parametrize("model,inherited_from", [
        # A future Opus point release inherits the RETIRED generation's
        # row -- $15/$75 where its real siblings 4.5 through 4.8 are
        # $5/$25. Threefold, in the direction that refuses affordable runs.
        ("claude-opus-4-9-20260901", "claude-opus-4"),
        ("claude-sonnet-4-9", "claude-sonnet-4"),
        ("gpt-5.7", "gpt-5"),
        ("gpt-4.1-micro", "gpt-4.1"),
    ])
    def test_a_family_match_is_not_exact(self, model, inherited_from):
        assert price_matched_exactly(model) is False
        # It really did inherit -- the point is a confident wrong number,
        # not a missing one.
        assert price_for(model) == price_for(inherited_from)
        assert price_for(model) is not None

    def test_an_unlisted_variant_is_priced_as_its_parent_not_its_sibling(self):
        """The specific case the docstring's own rationale forbids.

        gpt-4.1-nano was this test until it got a row. The shape survives
        it: any unlisted small variant lands on the full-size parent."""
        assert price_for("gpt-4.1-micro") == price_for("gpt-4.1")
        assert price_for("gpt-4.1-micro") != price_for("gpt-4.1-mini")

    def test_an_unpriced_model_is_not_reported_as_a_family_match(self):
        """Absence is reported elsewhere and loudly; saying it twice in
        two different words helps nobody.

        Claude 3.5 Sonnet is real, retired, and matches no row: the
        substring "claude-sonnet" does not occur in "claude-3-5-sonnet".
        It was this package's own Anthropic default until 2026-09-05,
        which is how a study that never named a model ran uncapped."""
        assert price_for("claude-3-5-sonnet-20241022") is None
        assert price_matched_exactly("claude-3-5-sonnet-20241022") is True

    def test_a_local_endpoint_is_exact(self):
        assert price_matched_exactly("any-local-model", "vllm") is True


class TestTheCapSaysSo:
    CONFIG = {"ai_budget": {"cap_usd": 50.00}}

    def _run(self, model, endpoint_type=""):
        try:
            check_before_running(
                self.CONFIG, estimate(TEXTS, model, endpoint_type))
        except SpendCapExceeded:
            return "refused"
        return "ran"

    def test_a_family_matched_price_warns(self, caplog):
        with caplog.at_level("WARNING", logger="potato.ai.cost"):
            assert self._run("gpt-4.1-micro") == "ran"
        messages = [r.message for r in caplog.records]
        assert any("matched to the nearest family" in m for m in messages), \
            messages
        assert any("gpt-4.1-micro" in m for m in messages), messages

    @pytest.mark.parametrize("model,endpoint", [
        ("gpt-4o", ""),
        ("gpt-4o-2024-08-06", ""),
        ("gpt-4o-mini", ""),
        ("any-local-model", "vllm"),
    ])
    def test_a_price_that_is_really_this_model_is_silent(
            self, model, endpoint, caplog):
        with caplog.at_level("WARNING", logger="potato.ai.cost"):
            self._run(model, endpoint)
        assert not any("matched to the nearest family" in r.message
                       for r in caplog.records)

    def test_an_unpriced_model_keeps_its_own_warning(self, caplog):
        with caplog.at_level("WARNING", logger="potato.ai.cost"):
            self._run("claude-3-5-sonnet-20241022")
        messages = [r.message for r in caplog.records]
        assert any("no price on record" in m for m in messages), messages
        assert not any("matched to the nearest family" in m for m in messages)

    def test_warning_does_not_change_whether_the_run_happens(self):
        """This is a warning, not a refusal. Whether an ambiguous price
        should block is a behaviour change and is not decided here.

        Both directions matter: a family-matched model under the cap
        still runs, and one over it still refuses. A warning that
        quietly became a gate would be the behaviour change this
        deliberately does not make."""
        assert self._run("gpt-4.1-micro") == "ran"

        tight = {"ai_budget": {"cap_usd": 1.00}}
        projected = estimate(TEXTS, "claude-opus-4-1-20250805", "")
        assert projected.cost_usd > 1.00, (
            f"fixture no longer crosses the cap (${projected.cost_usd:.2f})")
        with pytest.raises(SpendCapExceeded):
            check_before_running(tight, projected)
