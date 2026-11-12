"""Beiwe survey JSON into Potato survey pages (potato import)."""

import json
import os
from pathlib import Path

import pytest
import yaml

from potato.importers.surveys.beiwe import BeiweImporter
from potato.importers.surveys.surveyjs import SurveyJSImporter
from potato.importers.surveys.writer import write_new_project
from potato.server_utils.config_module import (
    load_and_validate_config, normalize_config_before_validation)
from potato.server_utils.display_logic import DisplayLogicEvaluator, DisplayLogicRule
from tests.helpers.test_utils import create_test_directory

DATA = Path(__file__).resolve().parents[1] / "data" / "surveys"
STUDY = DATA / "beiwe" / "mood_study_settings.json"     # study settings export
SINGLE = DATA / "beiwe" / "single_survey.json"          # one survey, UTF-8 BOM

MOOD = "how_is_your_mood_right_now"
SLEPT = "did_you_sleep_well_last_night"
DID = "what_did_you_do_today"
WEEK = "overall_how_was_your_week"


@pytest.fixture(scope="module")
def result():
    return BeiweImporter().parse_path(STUDY)


def _q(result, name):
    return next(q for q in result.all_questions() if q["name"] == name)


def _holds(rule, answers):
    return DisplayLogicEvaluator.evaluate_rule(DisplayLogicRule.from_dict(rule), answers)


def _reported(result, where_fragment, what_fragment=""):
    return [u for u in result.untranslated
            if where_fragment in u.where and what_fragment in (u.what + u.detail)]


def _survey(*questions, settings=None):
    return {"content": list(questions), "settings": settings or {}, "survey_type": "tracking_survey"}


def _radio(qid, *answers, display_if=None):
    return {"question_id": qid, "question_type": "radio_button", "question_text": qid,
            "answers": [{"text": a} for a in answers], "display_if": display_if}


def _check(qid, *answers, display_if=None):
    return dict(_radio(qid, *answers, display_if=display_if), question_type="checkbox")


def _text(qid, display_if):
    return {"question_id": qid, "question_type": "free_response", "question_text": qid,
            "text_field_type": "SINGLE_LINE_TEXT", "display_if": display_if}


# --------------------------------------------------------------------------
# Detection


def test_detects_beiwe_and_not_other_json(tmp_path):
    imp = BeiweImporter()
    assert imp.detect_path(STUDY)
    assert imp.detect_path(SINGLE)
    bare = tmp_path / "content.json"
    bare.write_text(json.dumps(_survey(_radio("a", "x", "y"))["content"]))
    assert imp.detect_path(bare)
    other = tmp_path / "items.json"
    other.write_text(json.dumps([{"id": 1, "text": "x"}]))
    assert not imp.detect_path(other)
    assert not imp.detect_path(DATA / "surveyjs_screener.json")
    assert not SurveyJSImporter().detect_path(STUDY)


def test_single_survey_with_bom(tmp_path):
    assert SINGLE.read_bytes().startswith(b"\xef\xbb\xbf")
    res = BeiweImporter().parse_path(SINGLE)
    assert [p.name for p in res.pages] == ["survey_1"]
    assert _q(res, SLEPT)["labels"] == ["Yes", "No", "Not sure"]


# --------------------------------------------------------------------------
# Surveys and question types


def test_each_tracking_survey_is_a_page(result):
    assert [(p.name, p.title) for p in result.pages] == [
        ("daily_check_in", "Daily check-in"), ("weekly_reflection", "Weekly reflection")]
    assert _reported(result, "Voice diary", "audio survey")


def test_question_types(result):
    assert _q(result, "please_answer_about_the_last_24")["annotation_type"] == "pure_display"
    mood = _q(result, MOOD)
    assert (mood["annotation_type"], mood["min_value"], mood["max_value"]) == ("slider", 0, 10)
    assert _q(result, SLEPT)["annotation_type"] == "radio"
    assert _q(result, DID) == {"name": DID, "annotation_type": "multiselect",
                               "description": "What did you do today?",
                               "labels": ["Exercise", "Work", "Socialize", "Rest"]}
    assert _q(result, "how_many_hours_did_you_sleep")["annotation_type"] == "number"
    assert _q(result, "tell_us_about_your_exercise")["textarea"]["on"] is True
    assert "textarea" not in _q(result, "what_made_your_mood_low")
    assert len(result.name_map) == result.num_questions()


def test_unmapped_questions_and_settings_are_reported(result):
    names = {q["name"] for q in result.all_questions()}
    assert not any("doctor" in n or "wake" in n for n in names)
    assert _reported(result, "question 9", "'date'")
    assert _reported(result, "Weekly reflection' / question 3", "'time'")
    assert _reported(result, "Daily check-in", "Sun: 09:00")
    assert _reported(result, "Weekly reflection", "Fri: 19:00")
    assert _reported(result, "Weekly reflection", "randomize_with_memory")
    assert _reported(result, "Weekly reflection", "number_of_random_questions")
    assert _reported(result, "Voice diary", "absolute_timings")
    assert _reported(result, "study", "device settings")


def test_randomize_setting(result):
    daily, weekly = result.pages
    assert daily.randomize_questions is True
    assert not weekly.randomize_questions


# --------------------------------------------------------------------------
# display_if, by behaviour


def test_radio_index_becomes_its_label(result):
    rule = _q(result, "how_many_hours_did_you_sleep")["display_logic"]
    assert _holds(rule, {SLEPT: "No"})
    assert not _holds(rule, {SLEPT: "Yes"})
    assert not _holds(rule, {})


def test_nested_and_not_on_checkbox_and_slider(result):
    # and: [Exercise selected, not(mood < 4)]
    rule = _q(result, "tell_us_about_your_exercise")["display_logic"]
    assert _holds(rule, {DID: ["Exercise", "Work"], MOOD: "6"})
    assert not _holds(rule, {DID: ["Exercise"], MOOD: "2"})
    assert not _holds(rule, {DID: ["Work"], MOOD: "6"})


def test_or_with_slider_and_radio_ordering(result):
    # or: [mood <= 3, slept index >= 2]
    rule = _q(result, "what_made_your_mood_low")["display_logic"]
    assert _holds(rule, {MOOD: "3", SLEPT: "Yes"})
    assert _holds(rule, {MOOD: "8", SLEPT: "Not sure"})
    assert not _holds(rule, {MOOD: "8", SLEPT: "No"})


def test_checkbox_not_equal_needs_an_answer(result):
    # Beiwe: != on a checkbox is "that answer not selected"; nothing selected is false
    rule = _q(result, "how_stressed_do_you_feel")["display_logic"]
    assert _holds(rule, {DID: ["Work"]})
    assert not _holds(rule, {DID: ["Work", "Rest"]})
    assert not _holds(rule, {DID: []})


def test_checkbox_ordering_is_any_selected(result):
    # > 1: some selected answer has index 2 or 3
    rule = _q(result, "how_many_cups_of_coffee_did")["display_logic"]
    assert _holds(rule, {DID: ["Work", "Socialize"]})
    assert _holds(rule, {DID: ["Rest"]})
    assert not _holds(rule, {DID: ["Exercise", "Work"]})


def test_empty_and_is_always_shown(result):
    assert "display_logic" not in _q(result, "thank_you_for_checking_in")


def test_untranslatable_display_if_is_reported(result):
    # references an info text box; compares with a non-number
    assert "display_logic" not in _q(result, "what_would_have_made_it_better")
    assert _reported(result, "Weekly reflection' / question 4", "display-only")
    assert _reported(result, "Weekly reflection' / question 5", "not a number")


@pytest.mark.parametrize("logic,answers,expected", [
    ({"!=": ["n", 3]}, {"n": "4"}, True),
    ({"!=": ["n", 3]}, {"n": "3"}, False),
    ({"!=": ["n", 3]}, {}, False),                 # unanswered: false, as in the app
    ({"not": {"==": ["n", 3]}}, {}, True),
    ({">=": ["n", 2.5]}, {"n": "2.5"}, True),
    ({"==": ["r", 0]}, {"r": "low"}, True),
    ({"!=": ["r", 0]}, {"r": "high"}, True),
    ({"!=": ["r", 0]}, {}, False),
    ({"<": ["r", 1]}, {"r": "mid"}, False),
    ({"or": [{"==": ["c", 9]}, {"==": ["c", 0]}]}, {"c": ["a"]}, True),
    ({"or": [{"<": ["r", 0]}, {"==": ["n", 1]}]}, {"n": "1"}, True),
    ({"and": [{"or": [{"==": ["r", 2]}, {"==": ["r", 1]}]}, {"not": {"<=": ["n", 5]}}]},
     {"r": "high", "n": "9"}, True),
    ({"and": [{"or": [{"==": ["r", 2]}, {"==": ["r", 1]}]}, {"not": {"<=": ["n", 5]}}]},
     {"r": "low", "n": "9"}, False),
])
def test_logic_translation(logic, answers, expected):
    survey = _survey(
        _radio("r", "low", "mid", "high"), _check("c", "a", "b"),
        {"question_id": "n", "question_type": "free_response", "question_text": "n",
         "text_field_type": "NUMERIC"},
        _text("t", logic))
    res = BeiweImporter().parse(survey)
    rule = _q(res, "t")["display_logic"]
    assert _holds(rule, answers) is expected


def test_never_true_logic_is_reported():
    res = BeiweImporter().parse(_survey(_radio("r", "a", "b"), _text("t", {"<": ["r", 0]})))
    assert "display_logic" not in _q(res, "t")
    assert _reported(res, "question 2", "never true")


def test_short_question_ids_are_used_as_names():
    res = BeiweImporter().parse(_survey(_radio("mood", "a", "b")))
    assert _q(res, "mood")["labels"] == ["a", "b"]


# --------------------------------------------------------------------------
# Output


def _boot_check(config_path):
    """The generated config passes the same validation the server runs."""
    config_path = str(config_path)
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    normalize_config_before_validation(raw, os.path.dirname(config_path))
    load_and_validate_config(config_path, os.path.dirname(config_path))


def test_new_project_is_valid():
    out = create_test_directory("survey_import_beiwe_new")
    res = BeiweImporter().parse_path(STUDY)
    write_new_project(res, out, str(STUDY))
    config = yaml.safe_load(open(os.path.join(out, "config.yaml")))
    assert config["phases"]["order"] == ["daily_check_in", "weekly_reflection", "annotation"]
    assert config["phases"]["daily_check_in"]["randomize_questions"] is True
    pages = json.load(open(os.path.join(out, "surveys", "daily_check_in.json")))
    assert any(q.get("display_logic") for q in pages)
    report = open(os.path.join(out, "IMPORT_REPORT.md")).read()
    assert "audio survey" in report and "weekly schedule" in report
    _boot_check(os.path.join(out, "config.yaml"))
