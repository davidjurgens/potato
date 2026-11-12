"""LimeSurvey .lss survey structures into Potato survey pages (potato import)."""

import json
import os
from pathlib import Path

import pytest
import yaml

from potato.importers.surveys.limesurvey import LimeSurveyImporter
from potato.importers.surveys.writer import write_new_project
from potato.server_utils.config_module import (
    load_and_validate_config, normalize_config_before_validation)
from potato.server_utils.display_logic import DisplayLogicEvaluator, DisplayLogicRule
from tests.helpers.test_utils import create_test_directory

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "surveys" / "limesurvey"
LEGACY = FIXTURES / "screener_legacy.lss"     # DBVersion 355, language column, en + de
MODERN = FIXTURES / "mobility_l10ns.lss"      # DBVersion 600, *_l10ns tables, base de


@pytest.fixture(scope="module")
def legacy():
    return LimeSurveyImporter().parse_path(LEGACY)


@pytest.fixture(scope="module")
def modern():
    return LimeSurveyImporter().parse_path(MODERN)


def _q(result, name):
    return next(q for q in result.all_questions() if q["name"] == name)


def _names(result):
    return {q["name"] for q in result.all_questions()}


def _holds(rule, answers):
    return DisplayLogicEvaluator.evaluate_rule(DisplayLogicRule.from_dict(rule), answers)


def _reported(result):
    return [u.line() for u in result.untranslated]


# --------------------------------------------------------------------------
# Detection and languages

def test_detects_lss_and_not_other_xml(tmp_path):
    imp = LimeSurveyImporter()
    assert imp.detect_path(LEGACY) and imp.detect_path(MODERN)
    other = tmp_path / "notes.lss"
    other.write_text('<?xml version="1.0"?><notes><note>hi</note></notes>')
    assert not imp.detect_path(other)
    group = tmp_path / "group.lss"
    group.write_text('<?xml version="1.0"?><document><LimeSurveyDocType>Group'
                     '</LimeSurveyDocType></document>')
    assert imp.detect_path(group)
    with pytest.raises(ValueError, match="export the whole survey"):
        imp.parse_path(group)


def test_legacy_reads_the_base_language(legacy):
    assert legacy.title == "Annotator screener"
    assert _q(legacy, "country")["labels"][:3] == ["United States", "United Kingdom", "Germany"]
    german = LimeSurveyImporter().parse_path(LEGACY, {"language": "de"})
    assert german.title == "Annotator-Screening"
    assert _q(german, "country")["labels"][0] == "[de] United States"
    assert german.pages[0].title == "[de] About you"


def test_l10n_tables_and_base_language(modern):
    # Base language is German; the English text is one option away.
    assert modern.title == "Mobilitätsumfrage"
    assert _q(modern, "Q1")["labels"] == ["Täglich", "Manchmal", "Nie"]
    english = LimeSurveyImporter().parse_path(MODERN, {"language": "en"})
    assert english.title == "Mobility survey"
    assert _q(english, "Q1")["labels"] == ["Daily", "Sometimes", "Never"]
    assert _q(english, "Q2")["labels"] == ["Bus", "Train", "Tram"]
    assert [p.title for p in english.pages] == ["Travel", "Rating"]


# --------------------------------------------------------------------------
# Structure and types

def test_groups_become_pages_in_order(legacy):
    assert [p.title for p in legacy.pages] == ["About you", "Experience", "Follow-up"]
    intro = legacy.pages[0].questions[0]
    assert intro["annotation_type"] == "pure_display"
    assert intro["labels"] == ["A few questions about you."]


def test_question_types(legacy):
    age = _q(legacy, "age")
    assert age["annotation_type"] == "number"
    assert (age["min"], age["max"], age["step"]) == (16, 99, 1)
    assert age["label_requirement"] == {"required": True}
    assert age["description"] == "How old are you? (In whole years)"
    assert _q(legacy, "gender")["labels"] == ["Female", "Male"]
    country = _q(legacy, "country")
    assert country["annotation_type"] == "radio"
    assert country["labels"][-1] == "Somewhere else"          # other_replace_text
    assert country["has_free_response"]
    langs = _q(legacy, "langs")
    assert langs["annotation_type"] == "multiselect"
    assert langs["labels"] == ["English", "Spanish", "French"]
    assert langs["randomize_order"] is True
    assert _q(legacy, "bilingual")["labels"] == ["Yes", "No"]
    assert _q(legacy, "notes")["textarea"]["on"] is True
    assert _q(legacy, "feedback")["textarea"]["rows"] == 8
    assert _q(legacy, "exp")["labels"] == ["1", "2", "3", "4", "5"]
    assert _q(legacy, "tool")["annotation_type"] == "select"
    agree = _q(legacy, "agree")
    assert agree["annotation_type"] == "multirate"
    assert agree["options"] == ["Guidelines were clear", "The interface was fast"]
    assert agree["labels"] == ["Disagree", "Neutral", "Agree"]
    assert agree["randomize_order"] is True
    assert _q(legacy, "speed")["labels"] == ["1", "2", "3", "4", "5"]
    assert _q(legacy, "ynu")["labels"] == ["Yes", "Uncertain", "No"]
    assert _q(legacy, "isd")["labels"] == ["Increase", "Same", "Decrease"]
    assert {"hours_SQ001", "hours_SQ002", "contact_name", "contact_phone"} <= _names(legacy)
    assert _q(legacy, "hours_SQ001")["max"] == 80
    assert _q(legacy, "rank")["annotation_type"] == "ranking"
    assert _q(legacy, "exp_intro")["annotation_type"] == "pure_display"
    assert _q(legacy, "devices")["annotation_type"] == "multiselect"
    assert _q(legacy, "fav_color")["labels"] == ["Red", "Blue"]
    assert _q(legacy, "dob")["annotation_type"] == "text"


def test_unsupported_and_hidden_questions_are_left_out(legacy):
    for name in ("hidden_score", "score_eq", "upload", "dual"):
        assert name not in _names(legacy)


# --------------------------------------------------------------------------
# Logic, evaluated

def test_choice_codes_become_labels(legacy):
    rule = _q(legacy, "state")["display_logic"]
    assert _holds(rule, {"country": "United States"})
    assert not _holds(rule, {"country": "Germany"})


def test_other_code(legacy):
    rule = _q(legacy, "other_where")["display_logic"]
    assert _holds(rule, {"country": "Somewhere else"})
    assert not _holds(rule, {"country": "Germany"})


def test_count_of_all_options_is_a_selection_count(legacy):
    rule = _q(legacy, "bilingual")["display_logic"]
    assert _holds(rule, {"langs": ["English", "French"]})
    assert not _holds(rule, {"langs": ["English"]})
    assert not _holds(rule, {})


def test_subquestion_membership_or_and_not_is_empty(legacy):
    # langs_SQ003 == "Y" || (country == "A2" && !is_empty(langs_SQ002))
    rule = _q(legacy, "notes")["display_logic"]
    assert _holds(rule, {"langs": ["French"]})
    assert _holds(rule, {"langs": ["Spanish"], "country": "United Kingdom"})
    assert not _holds(rule, {"langs": ["Spanish"], "country": "Germany"})
    assert not _holds(rule, {"langs": ["English"], "country": "United Kingdom"})


def test_sgqa_reference_and_word_operators(legacy):
    # 481516X20X202.NAOK > 3 and not is_empty(age)
    rule = _q(legacy, "tool")["display_logic"]
    assert _holds(rule, {"exp": "4", "age": 30})
    assert not _holds(rule, {"exp": "2", "age": 30})
    assert not _holds(rule, {"exp": "5"})


def test_negated_comparison_on_multiple_numerical(legacy):
    for name in ("hours_SQ001", "hours_SQ002"):
        rule = _q(legacy, name)["display_logic"]
        assert _holds(rule, {"exp": "3"}) and not _holds(rule, {"exp": "1"})


def test_group_relevance_is_the_page_rule(legacy):
    page = legacy.pages[1]
    assert _holds(page.show_when, {"age": 18})
    assert not _holds(page.show_when, {"age": 16})


def test_legacy_conditions_table(legacy):
    # scenario 1: (country A1 or A2) and gender F; scenario 2: French ticked
    rule = _q(legacy, "followup")["display_logic"]
    assert _holds(rule, {"country": "United Kingdom", "gender": "Female"})
    assert _holds(rule, {"country": "United States", "gender": "Female"})
    assert not _holds(rule, {"country": "United States", "gender": "Male"})
    assert not _holds(rule, {"country": "Germany", "gender": "Female"})
    assert _holds(rule, {"country": "Germany", "langs": ["French"]})
    assert "display_logic" not in _q(legacy, "always")


def test_l10n_survey_logic(modern):
    english = LimeSurveyImporter().parse_path(MODERN, {"language": "en"})
    q2 = _q(english, "Q2")["display_logic"]
    assert _holds(q2, {"Q1": "Daily"}) and not _holds(q2, {"Q1": "Never"})
    q3 = _q(english, "Q3")["display_logic"]
    assert _holds(q3, {"Q1": "Daily", "Q2": ["Bus", "Train"]})
    assert not _holds(q3, {"Q1": "Sometimes", "Q2": ["Train"]})
    assert not _holds(q3, {"Q1": "Daily", "Q2": ["Bus"]})
    q5 = _q(english, "Q5")["display_logic"]
    assert _holds(q5, {}) and _holds(q5, {"Q3": 30}) and not _holds(q5, {"Q3": 90})
    page = english.pages[1]
    assert _holds(page.show_when, {"Q2": ["Tram"]})
    assert not _holds(page.show_when, {"Q2": ["Train"]})
    assert _q(english, "Q3")["max"] == 300
    assert english.untranslated == []


# --------------------------------------------------------------------------
# Reporting

def test_everything_dropped_is_reported(legacy):
    lines = _reported(legacy)
    for needle in ("welcome text", "date question", "hidden question", "soft mandatory",
                   "validation regex", "maximum total", "'*' (equation)", "'|' (file upload)",
                   "per-option comment", "comment box of a list-with-comment",
                   "'1' (array dual scale)", "piped text", "validation equation",
                   "group randomization", "default value"):
        assert any(needle in line for line in lines), needle
    by_question = {line.split(":")[0]: line for line in lines if "relevance" in line}
    assert "hidden question" in by_question["question uses_hidden"]
    assert "one row of the array agree" in by_question["question contact"]
    assert ".shown" in by_question["question speed"]
    assert "if()" in by_question["question feedback"]
    for translated in ("state", "notes", "tool", "bilingual", "followup"):
        assert not any(line.startswith(f"question {translated}:") and "relevance" in line
                       for line in lines), translated


# --------------------------------------------------------------------------
# Output

def _boot_check(config_path):
    """The generated config passes the same validation the server runs."""
    config_path = str(config_path)
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    normalize_config_before_validation(raw, os.path.dirname(config_path))
    load_and_validate_config(config_path, os.path.dirname(config_path))


@pytest.mark.parametrize("fixture,dirname", [(LEGACY, "survey_import_lss_legacy"),
                                             (MODERN, "survey_import_lss_l10ns")])
def test_new_project_is_valid(fixture, dirname):
    out = create_test_directory(dirname)
    res = LimeSurveyImporter().parse_path(fixture)
    write_new_project(res, out, str(fixture))
    config = yaml.safe_load(open(os.path.join(out, "config.yaml")))
    pages = [p.name for p in res.pages]
    assert config["phases"]["order"] == pages + ["annotation"]
    assert any("show_when" in config["phases"][p] for p in pages)
    for page in pages:
        questions = json.load(open(os.path.join(out, "surveys", f"{page}.json")))
        assert questions
    _boot_check(os.path.join(out, "config.yaml"))
