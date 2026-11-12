"""
The force-lock table in the docs is checked against real behaviour.

Twice in two rounds a safety guarantee was documented that the code did not
make: `min_annotators_per_instance` described as an enforced floor that
enforces nothing, and the codebook force-lock described as applying "whichever
way the platform is named" when `login.type: url_direct` was open and
`crowdsourcing.provider: url_direct` was locked.

Both passed every existing guard, and they passed for a structural reason:
the doc tests prove the prose matches the config registry, and the agent
pack's guard proves the pack matches the registry -- nobody checks that the
registry matches the code. A false claim written into the registry is
consistent with everything downstream of it.

There is no cheap general fix for that. This is the honest partial: the one
table that states the guarantee is parsed out of the doc and each row is run
against `get_codebook_mode`, so the prose cannot drift from the behaviour
without failing. It covers one claim, deliberately, and it is the claim that
was wrong.
"""

import re
from pathlib import Path

import pytest

from potato.server_utils.config_module import get_codebook_mode

DOC = (Path(__file__).resolve().parents[2]
       / "docs" / "advanced" / "codebook.md")

#: Doc row -> the config it describes. A row whose text is not here fails
#: the test rather than being skipped: an unmapped row is a claim nobody
#: checked, which is the thing this file exists to prevent.
ROW_CONFIGS = {
    "`crowdsourcing.provider`, any value except `expert`":
        {"crowdsourcing": {"provider": "prolific"}},
    "`crowdsourcing.provider` Potato does not recognize":
        {"crowdsourcing": {"provider": "not_a_real_platform"}},
    "top-level `prolific:` or `mturk:` block":
        {"prolific": {"completion_code": "ABC"}},
    "`login.type: prolific` or `mturk`":
        {"login": {"type": "prolific"}},
    "`crowdsourcing.provider: expert`":
        {"crowdsourcing": {"provider": "expert"}},
    "`login.type: url_direct` alone":
        {"login": {"type": "url_direct"}},
    "anything else":
        {"login": {"type": "standard"}},
}


def _table_rows():
    """The rows of the force-lock table, as (configuration, outcome)."""
    text = DOC.read_text(encoding="utf-8")
    heading = "| Configuration | Codebook |"
    assert heading in text, (
        f"the force-lock table is gone from {DOC.name}. If it moved, point "
        "this test at it; if it was deleted, the guarantee it stated is now "
        "undocumented.")
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
            continue                             # the |---|---| rule
        rows.append(tuple(cells))
    assert rows, "found the table heading but no rows under it"
    return rows


def test_every_documented_row_is_mapped_to_a_config():
    """A row nobody mapped is a claim nobody checked."""
    documented = {config for config, _ in _table_rows()}
    unmapped = documented - set(ROW_CONFIGS)
    assert not unmapped, (
        f"these documented rows are not exercised: {sorted(unmapped)}. Add "
        "them to ROW_CONFIGS -- do not delete them from the doc to make this "
        "pass.")


def test_the_mapping_has_no_rows_the_doc_dropped():
    """The other direction: a row deleted from the doc leaves a test that
    proves something nobody is told."""
    documented = {config for config, _ in _table_rows()}
    stale = set(ROW_CONFIGS) - documented
    assert not stale, f"mapped rows no longer in the doc: {sorted(stale)}"


@pytest.mark.parametrize("config_text,outcome", _table_rows())
def test_the_documented_outcome_is_what_happens(config_text, outcome):
    config = dict(ROW_CONFIGS[config_text])
    config["codebook_mode"] = "open"
    mode = get_codebook_mode(config)

    if outcome.startswith("locked"):
        assert mode == "fixed", (
            f"the docs say {config_text} is locked; it resolved to {mode!r}")
    elif outcome.startswith("as requested"):
        assert mode == "open", (
            f"the docs say {config_text} keeps the requested mode; it "
            f"resolved to {mode!r}")
    else:
        pytest.fail(f"unrecognized documented outcome {outcome!r}")
