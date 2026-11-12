"""
Unit tests for the shared answer collapse (Python half of the parity pair).

The JS half is tests/jest/display-logic-collapse.test.js. Both drive
tests/data/answer_collapse_cases.json; if they disagree, a conditional question can be
shown in the browser and treated as hidden by the export — which silently drops the
answer from the exported data.
"""

import json
import os

import pytest

from potato.server_utils.answer_collapse import (
    EXEMPT_LABEL_NAMES,
    collapse_answers,
    collapse_entries,
    is_selected,
)

CASES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "answer_collapse_cases.json",
)

with open(CASES_PATH) as _f:
    CASES = json.load(_f)["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_shared_parity_cases(case):
    """Every case in the shared fixture, as Python sees it."""
    entries = [tuple(e) for e in case["entries"]]
    value, _winner, _method = collapse_entries(
        entries, schema="q", annotation_type=case.get("annotation_type"))
    assert value == case["expected"], (
        f"{case['name']}: got {value!r}, expected {case['expected']!r}")


class TestIsSelected:

    @pytest.mark.parametrize("value", [True, 1, "true", "TRUE"])
    def test_truthy_markers(self, value):
        assert is_selected("Yes", value) is True

    def test_value_echoing_its_label(self):
        """The shape the current frontend writes for radio and multiselect."""
        assert is_selected("en", "en") is True

    @pytest.mark.parametrize("value", [False, 0, "", "false", None])
    def test_not_selected(self, value):
        assert is_selected("Yes", value) is False

    def test_false_is_not_selected_despite_equalling_zero(self):
        """Guard against Python's False == 0 collapsing the two branches."""
        assert is_selected("Yes", False) is False

    def test_unrelated_string_is_not_a_selection(self):
        assert is_selected("Yes", "some typed text") is False


class TestExemptLabels:

    def test_free_response_is_the_only_exemption(self):
        assert EXEMPT_LABEL_NAMES == frozenset({"free_response"})

    def test_bad_text_is_not_exempt(self):
        """A likert's bad_text option is a real member of the radio group, so
        choosing it must replace the scale point rather than sit beside it."""
        value, _w, _m = collapse_entries(
            [("3", "3"), ("bad_text", "bad_text")], schema="q",
            annotation_type="likert")
        # Two selections for a single-select schema resolve to one; either way
        # bad_text must not be treated as a companion answer.
        assert value in ("3", "bad_text")
        assert not isinstance(value, list)


class TestSingleSelectResolution:

    def test_legacy_duplicate_resolves_by_behavioral_trail(self):
        """Pre-#167 data can hold two scale points. The trail decides, not order —
        stored order is first-touch, so 5 -> 4 -> 5 persists as [5, 4]."""
        changes = [
            {"timestamp": 100.0, "schema_name": "conf", "label_name": "5", "action": "select"},
            {"timestamp": 200.0, "schema_name": "conf", "label_name": "4", "action": "select"},
            {"timestamp": 300.0, "schema_name": "conf", "label_name": "5", "action": "select"},
        ]
        value, winner, method = collapse_entries(
            [("5", "5"), ("4", "4")], schema="conf",
            annotation_type="likert", changes=changes)
        assert (value, winner, method) == ("5", "5", "behavioral")

    def test_without_a_trail_it_falls_back_to_order(self):
        value, _winner, method = collapse_entries(
            [("5", "5"), ("4", "4")], schema="conf", annotation_type="likert")
        assert (value, method) == ("4", "order")


class TestCollapseAnswers:

    def test_omits_schemas_with_nothing_to_compare(self):
        result = collapse_answers({
            "answered": [("Yes", "Yes")],
            "blank": [("text_box", "")],
        }, schema_types={"answered": "radio", "blank": "text"})
        assert result == {"answered": "Yes"}

    def test_ignores_empty_schema_names(self):
        assert collapse_answers({"": [("Yes", "Yes")]}) == {}


class TestFlattenPhaseAnnotations:
    """The public entry point used by the export path."""

    @staticmethod
    def _label(schema, name):
        return {"schema": schema, "name": name}

    def test_multiselect_across_the_real_stored_shape(self):
        from potato.server_utils.display_logic import flatten_phase_annotations
        pages = {"p1": [
            [self._label("langs", "en"), "en"],
            [self._label("langs", "fr"), "fr"],
        ]}
        assert flatten_phase_annotations(
            pages, schema_types={"langs": "multiselect"}) == {"langs": ["en", "fr"]}

    def test_repeated_question_across_pages_is_one_answer(self):
        from potato.server_utils.display_logic import flatten_phase_annotations
        pages = {
            "p1": [[self._label("q", "Yes"), "Yes"]],
            "p2": [[self._label("q", "Yes"), "Yes"]],
        }
        assert flatten_phase_annotations(
            pages, schema_types={"q": "radio"}) == {"q": "Yes"}

    def test_dict_form_still_supported(self):
        from potato.server_utils.display_logic import flatten_phase_annotations
        from potato.item_state_management import Label
        pages = {"p1": {Label("q", "Yes"): "Yes"}}
        assert flatten_phase_annotations(pages) == {"q": "Yes"}
