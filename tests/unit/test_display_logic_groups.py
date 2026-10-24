"""Nested all / any / not groups and the count_* operators in display_logic.

Survey importers (Qualtrics, SurveyJS, XLSForm, REDCap) translate nested
boolean logic, so a `show_when` item may be a group. The server evaluator,
the config validators and the browser evaluator must agree on it.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError, validate_display_logic_structure as validate_scheme_logic)
from potato.server_utils.display_logic import (
    DisplayLogicEvaluator, DisplayLogicRule, DisplayLogicValidator, iter_leaf_conditions)

RULE = {"show_when": [
    {"schema": "age", "operator": "gte", "value": 18},
    {"any": [
        {"schema": "country", "operator": "equals", "value": "US"},
        {"not": {"schema": "region", "operator": "empty"}},
    ]},
]}

CASES = [
    ({"age": 20, "country": "US"}, True),
    ({"age": 20, "country": "UK", "region": "Wales"}, True),
    ({"age": 20, "country": "UK"}, False),
    ({"age": 16, "country": "US"}, False),
]


@pytest.mark.parametrize("answers,expected", CASES)
def test_nested_groups_evaluate(answers, expected):
    rule = DisplayLogicRule.from_dict(RULE)
    assert DisplayLogicEvaluator.evaluate_rule(rule, answers) is expected


def test_not_over_a_list_negates_their_conjunction():
    rule = DisplayLogicRule.from_dict({"show_when": [{"not": [
        {"schema": "a", "operator": "equals", "value": "x"},
        {"schema": "b", "operator": "equals", "value": "y"}]}]})
    assert DisplayLogicEvaluator.evaluate_rule(rule, {"a": "x", "b": "z"})
    assert not DisplayLogicEvaluator.evaluate_rule(rule, {"a": "x", "b": "y"})


@pytest.mark.parametrize("op,value,selected,expected", [
    ("count_gt", 1, ["a", "b"], True),
    ("count_gt", 2, ["a", "b"], False),
    ("count_lt", 1, [], True),
    ("count_equals", 1, "a", True),
    ("count_equals", 0, None, True),
])
def test_count_operators(op, value, selected, expected):
    rule = DisplayLogicRule.from_dict({"show_when": [{"schema": "m", "operator": op, "value": value}]})
    assert DisplayLogicEvaluator.evaluate_rule(rule, {"m": selected}) is expected


def test_watched_schemas_and_leaves_descend_into_groups():
    rule = DisplayLogicRule.from_dict(RULE)
    assert rule.get_watched_schemas() == {"age", "country", "region"}
    paths = [p for p, _ in iter_leaf_conditions(RULE["show_when"])]
    assert paths == ["show_when[0]", "show_when[1].any[0]", "show_when[1].any[1].not[0]"]


def test_round_trips_through_to_dict():
    rule = DisplayLogicRule.from_dict(RULE)
    again = DisplayLogicRule.from_dict(rule.to_dict())
    for answers, expected in CASES:
        assert DisplayLogicEvaluator.evaluate_rule(again, answers) is expected


def _schemes(logic):
    return [{"name": n, "annotation_type": "text", "description": n}
            for n in ("age", "country", "region")] + [
        {"name": "q", "annotation_type": "text", "description": "q", "display_logic": logic}]


def test_validator_accepts_groups_and_checks_references_inside_them():
    ok, errors = DisplayLogicValidator(_schemes(RULE)).validate()
    assert ok, errors
    bad = {"show_when": [{"any": [{"schema": "nope", "operator": "empty"}]}]}
    ok, errors = DisplayLogicValidator(_schemes(bad)).validate()
    assert not ok and "nope" in errors[0] and "any[0]" in errors[0]


def test_cycle_through_a_group_is_found():
    schemes = [
        {"name": "a", "annotation_type": "text", "description": "a",
         "display_logic": {"show_when": [{"all": [{"schema": "b", "operator": "empty"}]}]}},
        {"name": "b", "annotation_type": "text", "description": "b",
         "display_logic": {"show_when": [{"schema": "a", "operator": "empty"}]}},
    ]
    ok, errors = DisplayLogicValidator(schemes).validate()
    assert not ok and any("Circular" in e for e in errors)


@pytest.mark.parametrize("show_when,match", [
    ([{"all": []}], "at least one"),
    ([{"all": [{"schema": "a", "operator": "empty"}], "any": []}], "exactly one"),
    ([{"any": [{"schema": "a", "operator": "count_gt"}]}], "requires a value"),
    ([{"any": [{"schema": "a", "operator": "bogus", "value": 1}]}], "not supported"),
])
def test_config_validator_refuses_bad_groups(show_when, match):
    with pytest.raises(ConfigValidationError, match=match):
        validate_scheme_logic({"show_when": show_when}, "annotation_schemes[0]")


def test_too_deep_is_refused():
    item = {"schema": "a", "operator": "empty"}
    for _ in range(12):
        item = {"all": [item]}
    with pytest.raises(ValueError, match="deeper"):
        DisplayLogicRule.from_dict({"show_when": [item]})


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_browser_evaluator_agrees():
    """Run static/display-logic.js under node on the same cases."""
    js = Path(__file__).resolve().parents[2] / "potato" / "static" / "display-logic.js"
    cases = [{"rule": RULE, "answers": a, "expected": e} for a, e in CASES]
    cases += [{"rule": {"show_when": [{"schema": "m", "operator": "count_gt", "value": 1}]},
               "answers": {"m": ["a", "b"]}, "expected": True},
              {"rule": {"show_when": [{"not": [{"schema": "a", "operator": "equals", "value": "x"},
                                                {"schema": "b", "operator": "equals", "value": "y"}]}]},
               "answers": {"a": "x", "b": "y"}, "expected": False}]
    script = f"""
global.window = global; global.document = {{addEventListener(){{}}, querySelectorAll(){{return [];}},
  readyState: 'loading'}};
const {{ DisplayLogicManager }} = require({json.dumps(str(js))});
const m = Object.create(DisplayLogicManager.prototype);
const cases = {json.dumps(cases)};
const out = cases.map(c => m.evaluateRule(c.rule, c.answers) === c.expected);
console.log(JSON.stringify(out));
"""
    res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout.strip().splitlines()[-1]) == [True] * len(cases)


@pytest.mark.parametrize("operator,value", [
    ("count_gt", "2"), ("count_gt", True), ("gt", "3"), ("lt", False), ("length_gt", "5"),
    ("in_range", ["1", 5]), ("in_range", [True, 5]),
])
def test_values_the_runtime_refuses_are_refused_at_validate(operator, value):
    """Audit 96 R5: validate used float(), which takes "2" and True; the rule
    then failed at runtime and the server showed what the browser hid."""
    logic = {"show_when": [{"schema": "age", "operator": operator, "value": value}]}
    ok, errors = DisplayLogicValidator(_schemes(logic)).validate()
    assert not ok and errors, (operator, value)
    with pytest.raises(ValueError):
        DisplayLogicRule.from_dict(logic)


def test_matches_with_a_non_string_is_an_error_not_a_crash():
    """Audit 96 R6."""
    logic = {"show_when": [{"schema": "age", "operator": "matches", "value": 5}]}
    ok, errors = DisplayLogicValidator(_schemes(logic)).validate()
    assert not ok and "string" in " ".join(errors)


# Audit 96 R7: the four places a differential run found the two evaluators
# disagreeing. Each case is evaluated by both and must give the same answer.
EDGE_CASES = [
    ({"schema": "t", "operator": "matches", "value": "x*"}, {}, False),
    ({"schema": "m", "operator": "equals", "value": "a"}, {"m": ["a"]}, False),
    ({"schema": "m", "operator": "not_equals", "value": "a"}, {"m": ["a"]}, True),
    ({"schema": "m", "operator": "length_gt", "value": 1}, {"m": ["a", "b"]}, True),
    ({"schema": "m", "operator": "length_lt", "value": 2}, {"m": ["abc"]}, True),
    ({"schema": "n", "operator": "gt", "value": 2}, {"n": "3abc"}, False),
    ({"schema": "n", "operator": "gt", "value": 2}, {"n": "3"}, True),
    ({"schema": "n", "operator": "lt", "value": 2}, {"n": ""}, False),
    ({"schema": "n", "operator": "gt", "value": 2}, {"n": ["3"]}, False),
    ({"schema": "n", "operator": "in_range", "value": [1, 5]}, {"n": "4x"}, False),
]


@pytest.mark.parametrize("cond,answers,expected", EDGE_CASES)
def test_edge_cases_python(cond, answers, expected):
    rule = DisplayLogicRule.from_dict({"show_when": [cond]})
    assert DisplayLogicEvaluator.evaluate_rule(rule, answers) is expected


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_edge_cases_browser():
    js = Path(__file__).resolve().parents[2] / "potato" / "static" / "display-logic.js"
    cases = [{"rule": {"show_when": [c]}, "answers": a, "expected": e} for c, a, e in EDGE_CASES]
    script = f"""
global.window = global; global.document = {{addEventListener(){{}}, querySelectorAll(){{return [];}},
  readyState: 'loading'}};
const {{ DisplayLogicManager }} = require({json.dumps(str(js))});
const m = Object.create(DisplayLogicManager.prototype);
console.log(JSON.stringify({json.dumps(cases)}.map(c => m.evaluateRule(c.rule, c.answers))));
"""
    res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    got = json.loads(res.stdout.strip().splitlines()[-1])
    assert got == [e for _, _, e in EDGE_CASES], list(zip(EDGE_CASES, got))


@pytest.mark.parametrize("value", [5, True, ["x"]])
def test_matches_non_string_through_the_config_validator(value):
    """Audit 96 R6 re-verify: validate_display_logic_structure compiled the
    pattern first, so the error was a TypeError, not a config message."""
    from potato.server_utils.config_module import ConfigValidationError
    scheme = {"name": "q", "annotation_type": "text", "description": "q",
              "display_logic": {"show_when": [{"schema": "age", "operator": "matches", "value": value}]}}
    with pytest.raises(ConfigValidationError, match="as a string"):
        validate_scheme_logic(scheme["display_logic"], "annotation_schemes[0].display_logic")


@pytest.mark.parametrize("operator,value", [("gt", "3"), ("count_gt", True), ("in_range", ["1", 5])])
def test_numeric_values_through_the_config_validator(operator, value):
    from potato.server_utils.config_module import ConfigValidationError
    scheme = {"name": "q", "annotation_type": "text", "description": "q",
              "display_logic": {"show_when": [{"schema": "age", "operator": operator, "value": value}]}}
    with pytest.raises(ConfigValidationError, match="number"):
        validate_scheme_logic(scheme["display_logic"], "annotation_schemes[0].display_logic")
