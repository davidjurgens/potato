"""A duplicate key_value must cost the label its shortcut, not the label.

radio and multiselect `continue`d out of the label loop on a key conflict, so
the second label with the same key_value was never rendered: an option
silently missing from the page. CLAUDE.md's convention is warn and continue.
"""

import pytest

from potato.server_utils.schemas.multiselect import generate_multiselect_layout
from potato.server_utils.schemas.radio import generate_radio_layout


@pytest.mark.parametrize("generate,kind", [
    (generate_radio_layout, "radio"),
    (generate_multiselect_layout, "multiselect"),
])
def test_conflicting_label_is_still_rendered(generate, kind, caplog):
    scheme = {"annotation_type": kind, "name": "q", "description": "d",
              "labels": [{"name": "A", "key_value": "1"}, {"name": "B", "key_value": "1"}, "C"]}
    html, keys = generate(scheme)
    for name in ("A", "B", "C"):
        assert f'value="{name}"' in html
    assert [k for k, _ in keys].count("1") == 1
    assert ("1", "q: A") in keys
    assert "already bound to 'A'" in caplog.text


@pytest.mark.parametrize("generate,kind", [
    (generate_radio_layout, "radio"),
    (generate_multiselect_layout, "multiselect"),
])
def test_sequential_keys_do_not_take_an_explicit_key(generate, kind):
    # B is label 1, so the sequential fallback would give it "1", which A holds.
    scheme = {"annotation_type": kind, "name": "q", "description": "d",
              "sequential_key_binding": True,
              "labels": [{"name": "A", "key_value": "1"}, "B"]}
    _, keys = generate(scheme)
    assert [k for k, _ in keys].count("1") == 1
    assert ("1", "q: A") in keys
