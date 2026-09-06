"""`ai_budget.prices` prices a model this release has never heard of.

The built-in table is stale the moment a vendor ships a model, and the
2026-09-05 refresh showed how stale it gets: three Anthropic rows carried
retired generations' prices, one of them threefold high. A researcher who
hits that today cannot wait for a Potato release, and their two existing
options are both bad -- run uncapped, or be budgeted against a neighbouring
model's rate.

The cap is the only consumer of these numbers, which is why a malformed
override is refused rather than warned about: a bare number or a transposed
pair produces a cap that silently refuses affordable runs or permits
expensive ones, from a config that reads fine.
"""

import pytest

from potato.ai import cost
from potato.server_utils.config_module import (
    ConfigValidationError, validate_ai_budget_prices)

TEXTS = ["an item to label"] * 500
UNLISTED = "gpt-5.7"


class TestAnOverridePrices:
    def test_the_model_is_unpriced_by_its_own_row_to_begin_with(self):
        """Establishes the premise: without the override this test would
        pass for the wrong reason."""
        match = cost._price_match(UNLISTED)
        assert match is not None and match[0] != UNLISTED, (
            f"{UNLISTED} now has its own row; pick a model that does not")

    def test_an_override_wins_over_the_family_match(self):
        assert cost.price_for(UNLISTED) == (1.25, 10.00)
        assert cost.price_for(UNLISTED, "", {UNLISTED: [3.00, 24.00]}) == \
            (3.00, 24.00)

    def test_an_override_makes_the_match_exact(self):
        assert cost.price_matched_exactly(UNLISTED) is False
        assert cost.price_matched_exactly(
            UNLISTED, overrides={UNLISTED: [3.00, 24.00]}) is True

    def test_an_override_prices_a_model_with_no_match_at_all(self):
        model = "some-vendor-model-v9"
        assert cost.price_for(model) is None
        assert cost.price_for(model, "", {model: [1.0, 2.0]}) == (1.0, 2.0)

    def test_the_estimate_uses_it(self):
        without = cost.estimate(TEXTS, UNLISTED, "")
        with_ = cost.estimate(TEXTS, UNLISTED, "",
                              price_overrides={UNLISTED: [3.00, 24.00]})
        assert without.cost_usd is not None
        assert with_.cost_usd > without.cost_usd

    def test_it_is_case_insensitive_like_the_table(self):
        assert cost.price_for("GPT-5.7", "", {"GPT-5.7": [3.0, 24.0]}) == \
            (3.0, 24.0)

    def test_a_local_endpoint_stays_free(self):
        # Overrides must not resurrect a price for hardware already paid for.
        assert cost.price_for("anything", "vllm", {"anything": [9.0, 9.0]}) == \
            (0.0, 0.0)


class TestTheCapReadsTheOverride:
    def test_an_overridden_model_no_longer_warns_about_its_family(self, caplog):
        # Telling someone their fix did not work, when it did, is how a
        # warning stops being read.
        config = {"ai_budget": {"cap_usd": 50.0,
                                "prices": {UNLISTED: [3.00, 24.00]}}}
        projected = cost.estimate(TEXTS, UNLISTED, "",
                                  price_overrides={UNLISTED: [3.00, 24.00]})
        with caplog.at_level("WARNING", logger="potato.ai.cost"):
            cost.check_before_running(config, projected)
        assert not any("matched to the nearest family" in r.message
                       for r in caplog.records), \
            [r.message for r in caplog.records]

    def test_without_the_override_it_does_warn(self, caplog):
        config = {"ai_budget": {"cap_usd": 50.0}}
        with caplog.at_level("WARNING", logger="potato.ai.cost"):
            cost.check_before_running(config, cost.estimate(TEXTS, UNLISTED, ""))
        assert any("matched to the nearest family" in r.message
                   for r in caplog.records)

    def test_an_override_can_make_a_run_cross_the_cap(self):
        """The point of the feature, stated as an outcome rather than a
        returned number: a model that ran uncapped now refuses."""
        model = "some-vendor-model-v9"
        assert cost.price_for(model) is None

        uncapped = cost.estimate(TEXTS, model, "")
        assert uncapped.cost_usd is None
        cost.check_before_running({"ai_budget": {"cap_usd": 1.00}}, uncapped)

        overrides = {model: [50.00, 200.00]}
        priced = cost.estimate(TEXTS, model, "", price_overrides=overrides)
        with pytest.raises(cost.SpendCapExceeded):
            cost.check_before_running(
                {"ai_budget": {"cap_usd": 1.00, "prices": overrides}}, priced)


class TestAMalformedOverrideIsRefused:
    @pytest.mark.parametrize("prices", [
        {"m": 3.0},                 # a bare number, not a pair
        {"m": [1.0]},               # one entry
        {"m": [1.0, 2.0, 3.0]},     # three
        {"m": [1.0, "2.0"]},        # a string price
        {"m": [True, 2.0]},         # a bool is not a price
        {"m": [-1.0, 2.0]},         # negative
        {"m": "1.0,2.0"},           # a string that looks like a pair
        {"": [1.0, 2.0]},           # empty model name
    ])
    def test_it_raises(self, prices):
        with pytest.raises(ConfigValidationError):
            validate_ai_budget_prices({"ai_budget": {"prices": prices}})

    def test_a_non_mapping_raises(self):
        with pytest.raises(ConfigValidationError):
            validate_ai_budget_prices({"ai_budget": {"prices": [1, 2]}})

    def test_a_well_formed_override_is_accepted(self):
        validate_ai_budget_prices(
            {"ai_budget": {"cap_usd": 10, "prices": {"m": [1.0, 2.0]}}})

    def test_no_ai_budget_is_fine(self):
        validate_ai_budget_prices({})
        validate_ai_budget_prices({"ai_budget": {"cap_usd": 10}})

    def test_a_reversed_looking_pair_warns_rather_than_raising(self, caplog):
        # Evidence of a swap, not proof: refusing a real price the user
        # cannot override would be worse than saying so.
        with caplog.at_level("WARNING",
                             logger="potato.server_utils.config_module"):
            validate_ai_budget_prices(
                {"ai_budget": {"prices": {"m": [20.0, 1.0]}}})
        assert "reversed" in caplog.text


def test_the_key_is_allowed_in_the_config():
    """An unknown key only warns, so a key that works but is not registered
    tells every author it is a typo."""
    from potato.server_utils.config_module import validate_optional_field_types

    validate_optional_field_types(
        {"ai_budget": {"cap_usd": 10.0, "prices": {"m": [1.0, 2.0]}}})
