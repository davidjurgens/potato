"""price_list, bdm and belief_elicitation: generators, config validation and
the single-switch rule."""

import json
import re
from itertools import product

import pytest

from potato.server_utils.config_module import ConfigValidationError, validate_single_annotation_scheme
from potato.server_utils.schemas.bdm import generate_bdm_layout
from potato.server_utils.schemas.belief_elicitation import generate_belief_elicitation_layout
from potato.server_utils.schemas.price_list import (
    count_switches, generate_price_list_layout, single_switch_fill)
from potato.server_utils.schemas.registry import schema_registry


def _hidden(html):
    return re.search(r'<input type="hidden"[^>]*>', html.replace("\n", " ")).group(0)


def test_price_list_renders_one_radiogroup_per_row_and_one_hidden_input():
    html, keys = generate_price_list_layout(
        {"annotation_type": "price_list", "name": "risk", "description": "Pick", "preset": "holt_laury",
         "single_switch": True, "label_requirement": {"required": True}})
    assert keys == []
    assert html.count('role="radiogroup"') == 10
    assert html.count('class="pl-choice"') == 20
    hidden = _hidden(html)
    assert 'name="risk:::risk"' in hidden and 'validation="required"' in hidden
    config = json.loads(re.search(r"data-price-list='([^']*)'", html).group(1).replace("&quot;", '"'))
    assert config == {"rows": 10, "single_switch": True}
    assert 'data-annotation-type="price_list"' in html


def test_price_list_escapes_row_text():
    html, _ = generate_price_list_layout(
        {"annotation_type": "price_list", "name": "p", "description": "d",
         "rows": [{"a": "<b>x</b>", "b": "y"}, {"a": "z", "b": "w"}]})
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html


def test_time_preference_rows():
    html, _ = generate_price_list_layout(
        {"annotation_type": "price_list", "name": "tp", "description": "d", "preset": "time_preference",
         "amount_now": 10, "amounts_later": [10.5, 12], "delay_label": "in 2 weeks"})
    assert "$10.00 today" in html and "$12.00 in 2 weeks" in html


def test_bdm_number_and_slider():
    html, _ = generate_bdm_layout({"annotation_type": "bdm", "name": "wtp", "description": "d", "max": 5})
    assert 'type="number"' in html and 'max="5"' in html and "from $0.00 to $5.00" in html
    html, _ = generate_bdm_layout({"annotation_type": "bdm", "name": "wtp", "description": "d", "max": 5,
                                   "input": "slider", "currency": "£"})
    assert 'type="range"' in html and "£5.00" in html


def test_belief_modes():
    html, _ = generate_belief_elicitation_layout(
        {"annotation_type": "belief_elicitation", "name": "fc", "description": "d"})
    assert 'class="be-slider"' in html and 'max="100"' in html
    html, _ = generate_belief_elicitation_layout(
        {"annotation_type": "belief_elicitation", "name": "dist", "description": "d", "mode": "bins",
         "bins": ["< 10", "10-20", "> 20"]})
    assert html.count('class="be-bin-input"') == 3 and "&lt; 10" in html and "of 100" in html


@pytest.mark.parametrize("scheme,match", [
    ({"annotation_type": "price_list"}, "exactly one of"),
    ({"annotation_type": "price_list", "preset": "holt_laury", "rows": []}, "exactly one of"),
    ({"annotation_type": "price_list", "preset": "random"}, "preset must be"),
    ({"annotation_type": "price_list", "preset": "holt_laury", "scale": 0}, "scale"),
    ({"annotation_type": "price_list", "rows": [{"a": "x", "b": "y"}] * 2, "scale": 2}, "presets only"),
    ({"annotation_type": "price_list", "rows": [{"a": "x"}, {"a": "x", "b": "y"}]}, "option B"),
    ({"annotation_type": "price_list", "rows": [{"a_pays": [[0.5, 1]], "b": "y"}] * 2}, "sum to 1"),
    ({"annotation_type": "price_list", "preset": "time_preference", "amount_now": 5}, "amounts_later"),
    ({"annotation_type": "price_list", "preset": "holt_laury", "amount_now": 5}, "time_preference only"),
    ({"annotation_type": "price_list", "preset": "holt_laury", "single_switch": "yes"}, "single_switch"),
    ({"annotation_type": "bdm"}, "needs `max`"),
    ({"annotation_type": "bdm", "max": 5, "min": 6}, "min < max"),
    ({"annotation_type": "bdm", "max": 5, "input": "dial"}, "input must be"),
    ({"annotation_type": "belief_elicitation", "mode": "bins"}, "needs `bins`"),
    ({"annotation_type": "belief_elicitation", "mode": "bins", "bins": ["a", "a"]}, "distinct"),
    ({"annotation_type": "belief_elicitation", "bins": ["a", "b"]}, "mode: bins only"),
    ({"annotation_type": "belief_elicitation", "mode": "ranked"}, "mode must be"),
])
def test_bad_schemes_are_refused_at_validation(scheme, match):
    with pytest.raises(ConfigValidationError, match=match):
        validate_single_annotation_scheme({"name": "s", "description": "d", **scheme}, "annotation_schemes[0]")


def test_good_schemes_validate():
    for scheme in ({"annotation_type": "price_list", "preset": "holt_laury", "scale": 5},
                   {"annotation_type": "bdm", "max": 10, "step": 0.5, "input": "slider"},
                   {"annotation_type": "belief_elicitation", "mode": "bins", "bins": [1, 2, 3]}):
        validate_single_annotation_scheme({"name": "s", "description": "d", **scheme}, "x")


def test_switch_counting():
    assert count_switches(["A", "A", "B", "B"]) == 1
    assert count_switches(["A", "B", "A", "B"]) == 3
    assert count_switches(["A", None, "B", None]) == 1
    assert count_switches([None] * 4) == 0


def test_single_switch_rule_never_leaves_two_switches():
    """Every sequence of three clicks on a four-row list keeps all A before all B."""
    clicks = list(product(range(4), "AB"))
    for seq in product(clicks, repeat=3):
        choices = [None] * 4
        for row, choice in seq:
            choices = single_switch_fill(choices, row, choice)
            answered = [c for c in choices if c]
            assert answered == sorted(answered), (seq, choices)
            assert choices[row] == choice


def test_registered_with_a_frontend_marker():
    from potato.flask_server import FRONTEND_ASSET_MARKERS
    markers = FRONTEND_ASSET_MARKERS["incentive_elicitation"]
    for name, scheme in (("price_list", {"preset": "holt_laury"}), ("bdm", {"max": 1}),
                         ("belief_elicitation", {})):
        assert name in schema_registry.get_supported_types()
        html, _ = schema_registry.generate({"annotation_type": name, "name": "x", "description": "d", **scheme})
        assert any(m in html for m in markers)
