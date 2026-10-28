"""
Unit tests for `answers` on a `type: jspsych` page (issue #177).

Each name takes its value from the last trial that recorded it, as a data
field or as a survey question's response, and becomes `<page>_<name>`, which
`show_when` and `exit_when` may test.
"""

import pytest

from potato.runtimes.adapters.jspsych import ADAPTER
from potato.server_utils.config_module import (
    ConfigValidationError,
    validate_phase_flow_references,
)

SPEC = {"page_name": "consent", "answers": ["agree", "age"]}


class TestSummarize:
    def test_survey_response_and_data_field(self):
        trials = [
            {"trial_type": "survey-multi-choice", "response": {"agree": "Yes"}},
            {"trial_type": "html-button-response", "response": 0, "age": 34},
        ]
        assert ADAPTER.summarize(SPEC, trials) == {"consent_agree": "Yes", "consent_age": 34}

    def test_the_last_trial_that_recorded_it_wins(self):
        trials = [{"response": {"agree": "Yes"}}, {"response": {"agree": "No"}}]
        assert ADAPTER.summarize(SPEC, trials)["consent_agree"] == "No"

    def test_an_unrecorded_name_stays_unanswered(self):
        assert ADAPTER.summarize(SPEC, [{"response": "f", "rt": 300}]) == {}
        assert ADAPTER.summarize(SPEC, []) == {}

    def test_null_and_objects_are_not_answers(self):
        trials = [{"agree": None}, {"age": {"nested": 1}}]
        assert ADAPTER.summarize(SPEC, trials) == {}

    def test_without_answers_nothing_is_derived(self):
        assert ADAPTER.summarize({"page_name": "stroop"},
                                 [{"response": {"agree": "Yes"}}]) == {}


class TestConfig:
    def test_answer_schemes_name_the_page(self):
        names = [s["name"] for s in ADAPTER.answer_schemes("consent", {"answers": ["agree"]})]
        assert names == ["consent_agree"]

    @pytest.mark.parametrize("bad", ["agree", [""], ["has space"], [1]])
    def test_bad_answers_are_refused(self, bad):
        with pytest.raises(ConfigValidationError, match="answers must be a list"):
            ADAPTER.validate("phases.consent", {"answers": bad})

    def _config(self, answers):
        return {"phases": {
            "order": ["consent", "annotation"],
            "consent": {"type": "prestudy", "_kind": "jspsych", "timeline": "c.js",
                        "answers": answers,
                        "exit_when": {"show_when": [{"schema": "consent_agree",
                                                     "operator": "equals",
                                                     "value": "No"}]}},
        }}

    def test_exit_when_may_test_a_declared_answer(self):
        validate_phase_flow_references(self._config(["agree"]), {})

    def test_exit_when_on_an_undeclared_answer_is_refused(self):
        with pytest.raises(ConfigValidationError, match="consent_agree"):
            validate_phase_flow_references(self._config([]), {})
