"""
The spend-cap table in the docs is checked against real behaviour.

`ai_budget.cap_usd` is a safety guarantee about money, and its registry
description said a crossing run "cannot leave a part-labelled dataset and a bill
for it" -- unqualified. The cap binds only a model Potato can price. Anything
absent from `PRICE_TABLE` logs a warning and runs, which is a defensible design
(the code says so in `check_before_running` and explains why) described by a
sentence that promised more than it did.

Found by grepping registry descriptions for force-locks / always / never /
cannot / regardless: phrases that assert behaviour rather than describe a key,
and so the set most likely to be overclaiming.

Same treatment as the codebook force-lock table: the doc states the cases, and
this parses them back out and runs each one. A documented row nobody mapped to a
model fails rather than being skipped.
"""

from pathlib import Path

import pytest

from potato.ai.cost import (SpendCapExceeded, check_before_running, estimate,
                            price_for)

DOC = (Path(__file__).resolve().parents[2]
       / "docs" / "ai-intelligence" / "ai_costs.md")

CAP_USD = 1.00
#: 500 short items: enough that an expensive model crosses a $1 cap and a
#: cheap one does not, so the table's first two rows are distinguishable.
TEXTS = ["an item to label"] * 500

#: Doc row -> (model, endpoint_type). Chosen so each row is the case it
#: claims to be; `test_the_fixture_matches_the_row` proves that rather
#: than assuming it.
ROW_MODELS = {
    # Was the bare family name "claude-opus", which stopped being a row in
    # the 2026-09-05 refresh: a family does not have one price, since Opus
    # 4.x-retired is $15/$75 and 4.5+ is $5/$25. A named generation is what
    # a researcher would actually write anyway.
    "priced above the cap": ("claude-opus-5", ""),
    "priced below the cap": ("gpt-4o-mini", ""),
    "a local endpoint (vLLM, Ollama, …)": ("any-local-model", "vllm"),
    "absent from the price table": ("a-model-with-no-price", ""),
}


def _table_rows():
    text = DOC.read_text(encoding="utf-8")
    heading = "| Model | Cap |"
    assert heading in text, (
        f"the cap table is gone from {DOC.name}. If it moved, point this test "
        "at it; if it was deleted, the guarantee it stated is undocumented.")
    body = text.split(heading, 1)[1]
    rows = []
    for line in body.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 2:
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        rows.append(tuple(cells))
    assert rows, "found the table heading but no rows under it"
    return rows


def _run(model, endpoint_type):
    """Returns 'refused' or 'ran'."""
    projected = estimate(TEXTS, model, endpoint_type)
    try:
        check_before_running({"ai_budget": {"cap_usd": CAP_USD}}, projected)
    except SpendCapExceeded:
        return "refused"
    return "ran"


def test_every_documented_row_is_mapped():
    documented = {row for row, _ in _table_rows()}
    unmapped = documented - set(ROW_MODELS)
    assert not unmapped, (
        f"these documented rows are not exercised: {sorted(unmapped)}. Map "
        "them -- do not delete them from the doc to make this pass.")


def test_no_mapped_row_has_left_the_doc():
    documented = {row for row, _ in _table_rows()}
    stale = set(ROW_MODELS) - documented
    assert not stale, f"mapped rows no longer in the doc: {sorted(stale)}"


@pytest.mark.parametrize("row,model_spec", sorted(ROW_MODELS.items()))
def test_the_fixture_matches_the_row(row, model_spec):
    """The fixture has to BE the case the row describes, or the outcome
    test below passes for the wrong reason. A model that stopped being
    priced would otherwise turn 'priced above the cap' into a silent
    unpriced test that still reads green."""
    model, endpoint_type = model_spec
    price = price_for(model, endpoint_type)
    projected = estimate(TEXTS, model, endpoint_type)

    if row == "absent from the price table":
        assert price is None, f"{model!r} is priced; pick an unpriced model"
    elif row == "a local endpoint (vLLM, Ollama, …)":
        assert price == (0.0, 0.0), f"{endpoint_type!r} is not priced at zero"
    elif row == "priced above the cap":
        assert price is not None, f"{model!r} lost its price"
        assert projected.cost_usd > CAP_USD, (
            f"{model!r} projects ${projected.cost_usd:.2f}, under the "
            f"${CAP_USD:.2f} cap -- this row no longer tests a crossing run")
    elif row == "priced below the cap":
        assert price is not None, f"{model!r} lost its price"
        assert projected.cost_usd < CAP_USD, (
            f"{model!r} projects ${projected.cost_usd:.2f}, over the cap")


@pytest.mark.parametrize("row,outcome", _table_rows())
def test_the_documented_outcome_is_what_happens(row, outcome):
    model, endpoint_type = ROW_MODELS[row]
    result = _run(model, endpoint_type)

    if outcome.startswith("refuses"):
        assert result == "refused", (
            f"the docs say {row!r} refuses; it {result}")
    elif outcome.startswith("runs"):
        assert result == "ran", f"the docs say {row!r} runs; it {result}"
    else:
        pytest.fail(f"unrecognized documented outcome {outcome!r}")


def test_an_unpriced_run_says_so_in_the_log(caplog):
    """The warning is the only thing standing between an unbound cap and
    silence, so it is part of the contract rather than a nicety."""
    with caplog.at_level("WARNING", logger="potato.ai.cost"):
        _run("a-model-with-no-price", "")
    assert any("no price on record" in r.message for r in caplog.records), [
        r.message for r in caplog.records]
