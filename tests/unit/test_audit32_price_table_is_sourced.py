"""The price table has to be internally consistent and actually reachable.

Refreshing it on 2026-09-05 against the three vendors' pricing pages found
four things no existing test could have caught, because nothing checked the
numbers against anything:

  claude-opus     $15/$75, the RETIRED generation's price. Opus 4.5 and later
                  are $5/$25, so every current Opus was priced at three times
                  its rate -- and an over-price makes a cap refuse runs the
                  researcher could afford.
  claude-haiku    $0.80/$4, also the retired generation. Haiku 4.5 is $1/$5.
  gpt-4.1-nano    absent, so priced from gpt-4.1 at twenty times its rate.
  defaults        two of the three endpoint DEFAULT_MODELs matched no row at
                  all, so `cap_usd` did not bind for a study that never named
                  a model.

The first two are the deeper point: a FAMILY does not have one price. Opus 4
and 4.1 are $15/$75 while 4.5+ are $5/$25 under the same "claude-opus"
substring, so no single family row can be right. Rows are per generation.

These tests check the properties a refresh can break. They cannot check that
a number matches a vendor's page today -- only a fresh fetch does that, which
is why PRICES_AS_OF is reported with every estimate.
"""

import pytest

from potato.ai import cost


class TestNoRowIsShadowedByAnother:
    """Matching is longest-substring, so a badly chosen key can silently
    take another key's lookups. `o1` and `o3` are two characters."""

    @pytest.mark.parametrize("model", sorted(cost.PRICE_TABLE))
    def test_a_model_named_in_the_table_gets_its_own_price(self, model):
        match = cost._price_match(model)
        assert match is not None, f"{model} matched no row"
        assert match[0] == model, (
            f"{model} was priced from row {match[0]!r} "
            f"({cost.PRICE_TABLE[match[0]]}) instead of its own "
            f"{cost.PRICE_TABLE[model]}")

    @pytest.mark.parametrize("model", sorted(cost.PRICE_TABLE))
    def test_and_reports_that_as_an_exact_match(self, model):
        assert cost.price_matched_exactly(model)


class TestPricesAreWellFormed:
    @pytest.mark.parametrize("model,prices", sorted(cost.PRICE_TABLE.items()))
    def test_two_positive_numbers(self, model, prices):
        assert len(prices) == 2, model
        assert all(isinstance(p, (int, float)) and p > 0 for p in prices), model

    @pytest.mark.parametrize("model,prices", sorted(cost.PRICE_TABLE.items()))
    def test_output_is_not_cheaper_than_input(self, model, prices):
        # True of every published rate from all three vendors. A row that
        # breaks it is a transposed pair, which is the typo this table
        # invites and the one nothing else would catch.
        assert prices[1] >= prices[0], f"{model}: input/output look swapped"


class TestGenerationsAreSeparated:
    """The defect that motivated the refresh, stated as prices."""

    @pytest.mark.parametrize("model,expected", [
        ("claude-opus-4-1-20250805", (15.00, 75.00)),
        ("claude-opus-4-5-20251101", (5.00, 25.00)),
        ("claude-opus-5", (5.00, 25.00)),
        ("claude-sonnet-4-5-20250929", (3.00, 15.00)),
        ("claude-sonnet-5", (2.00, 10.00)),
        ("claude-haiku-4-5-20251001", (1.00, 5.00)),
    ])
    def test_each_generation_gets_its_own_rate(self, model, expected):
        assert cost.price_for(model) == expected

    def test_a_current_opus_is_not_priced_as_the_retired_one(self):
        assert cost.price_for("claude-opus-5") != cost.price_for("claude-opus-4")

    def test_a_dated_snapshot_at_its_own_price_is_not_read_off_the_alias(self):
        # gpt-4o-2024-05-13 costs twice what the gpt-4o alias does. A dated
        # suffix is treated as the same model by `price_matched_exactly`, so
        # without its own row this is wrong AND silent.
        assert cost.price_for("gpt-4o-2024-05-13") == (5.00, 15.00)
        assert cost.price_for("gpt-4o") == (2.50, 10.00)

    def test_the_cheap_variant_is_not_priced_as_its_parent(self):
        assert cost.price_for("gpt-4.1-nano") == (0.10, 0.40)
        assert cost.price_for("gpt-4.1") == (2.00, 8.00)


class TestEveryEndpointDefaultIsPriced:
    """`cap_usd` binds only priced models, so an unpriced default means a
    study that never names a model runs with no cap."""

    @pytest.mark.parametrize("module", [
        "potato.ai.openai_endpoint",
        "potato.ai.anthropic_endpoint",
        "potato.ai.gemini_endpoint",
    ])
    def test_the_default_model_has_a_price(self, module):
        import importlib

        default = importlib.import_module(module).DEFAULT_MODEL
        assert cost.price_for(default) is not None, (
            f"{module}.DEFAULT_MODEL = {default!r} matches no PRICE_TABLE row, "
            "so cap_usd does not bind for a study that never sets a model")

    @pytest.mark.parametrize("module", [
        "potato.ai.openai_endpoint",
        "potato.ai.anthropic_endpoint",
        "potato.ai.gemini_endpoint",
    ])
    def test_the_default_model_is_not_priced_off_its_family(self, module):
        import importlib

        default = importlib.import_module(module).DEFAULT_MODEL
        assert cost.price_matched_exactly(default), (
            f"{module}.DEFAULT_MODEL = {default!r} inherits another model's "
            "price, so every study that does not set a model is budgeted "
            "against a number that is not its own")


def test_prices_as_of_is_a_date_not_a_month():
    # "2026-08" cannot say whether a September refresh happened. The value is
    # reported with every estimate, so it is the only staleness signal a
    # researcher gets.
    assert cost.PRICES_AS_OF.count("-") == 2, cost.PRICES_AS_OF
