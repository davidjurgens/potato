"""
Unit tests for SurveyFlow conditional display_logic (issue #165).

Covers the server-side pieces added to bring `display_logic` to SurveyFlow
phase questions (consent/prestudy/poststudy):

- flatten_phase_annotations: on-disk phase answers -> {schema: comparable_value}
- compute_hidden_schemas: which questions a user's answers hide (cross-page aware)
- validate_display_logic_references: cross-phase reference/operator/cycle validation
- load_phase_responses_from_output_dir: server-side exclusion of hidden answers

The frontend show/hide and required-field behavior is covered by the Playwright
UI test in tests/selenium/test_surveyflow_conditional_ui.py.
"""

import json
import os

import pytest

from potato.server_utils.display_logic import (
    flatten_phase_annotations,
    compute_hidden_schemas,
)
from potato.server_utils.config_module import (
    validate_display_logic_references,
    ConfigValidationError,
)
from potato.export.cli import load_phase_responses_from_output_dir


# ---------------------------------------------------------------------------
# flatten_phase_annotations
# ---------------------------------------------------------------------------
class TestFlattenPhaseAnnotations:
    def test_list_form_radio_and_text(self):
        pages = {
            "prestudy": [
                [{"schema": "prior_experience", "name": "Yes"}, "Yes"],
                [{"schema": "experience_details", "name": "text_box"}, "Two years"],
            ]
        }
        flat = flatten_phase_annotations(pages)
        assert flat["prior_experience"] == "Yes"
        assert flat["experience_details"] == "Two years"

    def test_dict_form(self):
        pages = {"consent": {"consent_agree": "I agree"}}
        flat = flatten_phase_annotations(pages)
        assert flat["consent_agree"] == "I agree"

    def test_multiselect_collapses_to_list(self):
        pages = {
            "prestudy": [
                [{"schema": "langs", "name": "en"}, True],
                [{"schema": "langs", "name": "fr"}, True],
            ]
        }
        flat = flatten_phase_annotations(pages)
        assert sorted(flat["langs"]) == ["en", "fr"]

    def test_single_selected_label_collapses_to_name(self):
        pages = {"prestudy": [[{"schema": "q", "name": "Yes"}, "true"]]}
        flat = flatten_phase_annotations(pages)
        assert flat["q"] == "Yes"

    def test_empty_and_none_are_ignored(self):
        pages = {"prestudy": [[{"schema": "q", "name": "text_box"}, ""]]}
        flat = flatten_phase_annotations(pages)
        assert "q" not in flat
        assert flatten_phase_annotations({}) == {}


# ---------------------------------------------------------------------------
# compute_hidden_schemas
# ---------------------------------------------------------------------------
SCHEMES = [
    {"name": "prior_experience"},
    {
        "name": "experience_details",
        "display_logic": {
            "show_when": [
                {"schema": "prior_experience", "operator": "equals", "value": "Yes"}
            ]
        },
    },
    {"name": "overall_rating"},
    {
        "name": "low_rating_reason",
        "display_logic": {
            "show_when": [
                {"schema": "overall_rating", "operator": "equals", "value": ["Fair", "Poor"]}
            ],
            "logic": "any",
        },
    },
    {
        "name": "experience_match",
        "display_logic": {
            "show_when": [
                {"schema": "prior_experience", "operator": "equals", "value": "Yes"}
            ]
        },
    },
]


class TestComputeHiddenSchemas:
    def test_no_display_logic_never_hidden(self):
        assert compute_hidden_schemas([{"name": "a"}, {"name": "b"}], {}) == set()

    def test_trigger_met_shows(self):
        hidden = compute_hidden_schemas(SCHEMES, {"prior_experience": "Yes"})
        assert "experience_details" not in hidden
        assert "experience_match" not in hidden

    def test_trigger_unmet_hides(self):
        hidden = compute_hidden_schemas(SCHEMES, {"prior_experience": "No"})
        assert "experience_details" in hidden
        assert "experience_match" in hidden

    def test_cross_page_visibility(self):
        # experience_match lives on poststudy but depends on the prestudy answer;
        # low_rating_reason is same-page and stays hidden for a high rating.
        flat = {
            "prior_experience": "Yes",
            "overall_rating": "Excellent",
        }
        hidden = compute_hidden_schemas(SCHEMES, flat)
        assert hidden == {"low_rating_reason"}

    def test_missing_trigger_answer_hides(self):
        # If the trigger was never answered, dependent questions stay hidden.
        hidden = compute_hidden_schemas(SCHEMES, {})
        assert "experience_details" in hidden
        assert "experience_match" in hidden


# ---------------------------------------------------------------------------
# validate_display_logic_references — cross-phase union validation
# ---------------------------------------------------------------------------
class TestSurveyflowValidation:
    def test_valid_same_phase(self):
        schemes = [
            {"name": "q1", "annotation_type": "radio", "labels": ["Yes", "No"]},
            {
                "name": "q2",
                "annotation_type": "text",
                "display_logic": {
                    "show_when": [{"schema": "q1", "operator": "equals", "value": "Yes"}]
                },
            },
        ]
        validate_display_logic_references(schemes)  # no raise

    def test_valid_cross_phase_reference(self):
        # A poststudy question referencing a prestudy question resolves against
        # the union of all phase schemes.
        union = [
            {"name": "prior_experience", "annotation_type": "radio", "labels": ["Yes", "No"]},
            {
                "name": "experience_match",
                "annotation_type": "radio",
                "labels": ["Same", "Different"],
                "display_logic": {
                    "show_when": [
                        {"schema": "prior_experience", "operator": "equals", "value": "Yes"}
                    ]
                },
            },
        ]
        validate_display_logic_references(union)  # no raise

    def test_unknown_reference_raises(self):
        schemes = [
            {"name": "q1", "annotation_type": "radio", "labels": ["Yes", "No"]},
            {
                "name": "q2",
                "annotation_type": "text",
                "display_logic": {
                    "show_when": [{"schema": "nope", "operator": "equals", "value": "Yes"}]
                },
            },
        ]
        with pytest.raises(ConfigValidationError):
            validate_display_logic_references(schemes)

    def test_bad_operator_raises(self):
        schemes = [
            {"name": "q1", "annotation_type": "radio", "labels": ["Yes", "No"]},
            {
                "name": "q2",
                "annotation_type": "text",
                "display_logic": {
                    "show_when": [{"schema": "q1", "operator": "is_kinda", "value": "Yes"}]
                },
            },
        ]
        with pytest.raises(ConfigValidationError):
            validate_display_logic_references(schemes)

    def test_cycle_raises(self):
        schemes = [
            {
                "name": "a",
                "annotation_type": "text",
                "display_logic": {"show_when": [{"schema": "b", "operator": "equals", "value": "x"}]},
            },
            {
                "name": "b",
                "annotation_type": "text",
                "display_logic": {"show_when": [{"schema": "a", "operator": "equals", "value": "x"}]},
            },
        ]
        with pytest.raises(ConfigValidationError):
            validate_display_logic_references(schemes)


# ---------------------------------------------------------------------------
# load_phase_responses_from_output_dir — server-side hidden-answer exclusion
# ---------------------------------------------------------------------------
def _write_user_state(output_dir, user_id, phase_data):
    user_dir = os.path.join(output_dir, user_id)
    os.makedirs(user_dir, exist_ok=True)
    with open(os.path.join(user_dir, "user_state.json"), "w") as f:
        json.dump({"user_id": user_id, "phase_to_page_to_label_to_value": phase_data}, f)


class TestExportHiddenExclusion:
    @pytest.fixture
    def output_dir(self, tmp_path):
        # A participant answered prior_experience=No (hiding experience_details),
        # but the frontend preserved the previously-typed experience_details value.
        phase_data = {
            "prestudy": {
                "prestudy": [
                    [{"schema": "prior_experience", "name": "No"}, "No"],
                    [{"schema": "experience_details", "name": "text_box"}, "leftover"],
                ]
            }
        }
        d = str(tmp_path / "out")
        _write_user_state(d, "u1", phase_data)
        return d

    def test_default_behavior_unchanged_without_schemes(self, output_dir):
        rows = load_phase_responses_from_output_dir(output_dir)
        schemas = {r["schema"] for r in rows}
        assert schemas == {"prior_experience", "experience_details"}
        assert all("hidden" not in r for r in rows)

    def test_hidden_answer_excluded(self, output_dir):
        rows = load_phase_responses_from_output_dir(output_dir, display_logic_schemes=SCHEMES)
        schemas = {r["schema"] for r in rows}
        assert "experience_details" not in schemas  # hidden -> excluded
        assert "prior_experience" in schemas

    def test_hidden_answer_tagged_when_not_excluding(self, output_dir):
        rows = load_phase_responses_from_output_dir(
            output_dir, display_logic_schemes=SCHEMES, exclude_hidden=False
        )
        by_schema = {r["schema"]: r for r in rows}
        assert by_schema["experience_details"]["hidden"] is True
        assert by_schema["prior_experience"]["hidden"] is False
