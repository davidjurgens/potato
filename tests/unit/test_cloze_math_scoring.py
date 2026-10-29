"""Cloze `numeric` and `latex` scoring: grading typed math answers against a key."""

from fractions import Fraction

import pytest

from potato.server_utils.config_module import ConfigValidationError, validate_single_annotation_scheme
from potato.server_utils.schemas.cloze import (
    math_answer_matches,
    normalize_latex,
    parse_number,
    score_responses,
)

ITEM_SCHEME = {"annotation_type": "cloze", "name": "ans", "description": "Answer",
               "source_field": "prompt", "answer_field": "key", "scoring": "numeric"}


@pytest.mark.parametrize("text, value", [
    ("1/2", Fraction(1, 2)), ("0.5", Fraction(1, 2)), (".5", Fraction(1, 2)),
    ("5e-1", Fraction(1, 2)), ("\\frac{1}{2}", Fraction(1, 2)),
    ("\\dfrac{1}{2}", Fraction(1, 2)), ("$\\tfrac12$", Fraction(1, 2)),
    ("-\\frac{3}{4}", Fraction(-3, 4)), ("−3", Fraction(-3)), ("+7", Fraction(7)),
    ("1,000", Fraction(1000)), ("1,000.5", Fraction(2001, 2)), ("3.", Fraction(3)),
    ("\\(42\\)", Fraction(42)), ("2.5/0.5", Fraction(5)),
])
def test_numbers_parse_exactly(text, value):
    assert parse_number(text) == value


@pytest.mark.parametrize("text", [
    "2+2", "x", "1/0", "\\frac{1}{0}", "", "1,00", "1e999999999", "sqrt(2)", "1/2/3",
])
def test_non_numbers_are_none(text):
    assert parse_number(text) is None


def test_latex_normalization():
    assert normalize_latex("$\\left( 1, 2 \\right)$") == "(1,2)"
    assert normalize_latex("\\dfrac{a}{b}") == normalize_latex("\\frac {a}{b}")
    assert normalize_latex("x \\, = \\; 2.") == "x=2"
    # \leftarrow is not \left: the spacing pattern stops at a whole command.
    assert normalize_latex("\\leftarrow") == "\\leftarrow"


@pytest.mark.parametrize("given, key, mode, tol, ok", [
    ("0.5", "1/2", "numeric", 0, True),
    ("0.50001", "1/2", "numeric", 0, False),
    ("3.1416", "3.14159", "numeric", Fraction(1, 1000), True),
    ("3.15", "3.14159", "numeric", Fraction(1, 1000), False),
    ("x = 2", "x=2", "numeric", 0, True),       # key is not a number: compared as LaTeX
    ("two", "2", "numeric", 0, False),          # key is a number, answer is not
    ("", "0", "numeric", 0, False),
    ("\\frac{x}{2}", "\\dfrac{x}{2}", "latex", 0, True),
    ("2x", "x+x", "latex", 0, False),           # no algebra
    ("0.25", "\\frac14", "latex", 0, True),
])
def test_math_answer_matches(given, key, mode, tol, ok):
    assert math_answer_matches(given, key, mode, Fraction(tol)) is ok


def test_numeric_scoring_of_an_item_driven_cloze():
    item = {"prompt": "S = [[]] and the root is [[]].", "key": ["1/2", "3|-3"]}
    out = score_responses(ITEM_SCHEME, {"blank_1": "\\frac{2}{4}", "blank_2": "-3.0"}, item)
    assert out == {"blank_1_correct": 1, "blank_2_correct": 1, "score": 2, "scored_blanks": 2}
    # The old normalized mode strips the decimal point and the sign.
    out = score_responses(dict(ITEM_SCHEME, scoring="normalized"),
                          {"blank_1": "0.5", "blank_2": "-3"}, item)
    assert out["blank_1_correct"] == 0


def test_tolerance_applies_to_numeric_scoring():
    item = {"prompt": "pi = [[]]", "key": "3.14159"}
    loose = dict(ITEM_SCHEME, tolerance=0.01)
    assert score_responses(loose, {"blank_1": "3.14"}, item)["score"] == 1
    assert score_responses(ITEM_SCHEME, {"blank_1": "3.14"}, item)["score"] == 0


@pytest.mark.parametrize("extra, message", [
    ({"tolerance": -1}, "tolerance must be a number >= 0"),
    ({"tolerance": "0.1"}, "tolerance must be a number >= 0"),
    ({"tolerance": True}, "tolerance must be a number >= 0"),
    ({"tolerance": 0.1, "scoring": "normalized"}, "only applies with scoring: numeric or latex"),
    ({"scoring": "algebra"}, "scoring must be one of"),
])
def test_bad_scoring_settings_are_refused(extra, message):
    with pytest.raises(ConfigValidationError, match=message):
        validate_single_annotation_scheme(dict(ITEM_SCHEME, **extra), "annotation_schemes[0]")


def test_good_scoring_settings_validate():
    validate_single_annotation_scheme(dict(ITEM_SCHEME, tolerance=0.001), "annotation_schemes[0]")
    validate_single_annotation_scheme(dict(ITEM_SCHEME, scoring="latex"), "annotation_schemes[0]")
