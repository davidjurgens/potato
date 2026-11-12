"""REDCap data dictionaries into Potato survey pages (potato import)."""

import json
import os
from pathlib import Path

import pytest
import yaml

from potato.importers.surveys.expr import REDCAP, parse
from potato.importers.surveys.redcap import REDCapImporter, parse_choices
from potato.importers.surveys.surveyjs import SurveyJSImporter
from potato.importers.surveys.writer import write_new_project
from potato.server_utils.config_module import (
    load_and_validate_config, normalize_config_before_validation)
from potato.server_utils.display_logic import DisplayLogicEvaluator, DisplayLogicRule
from tests.helpers.test_utils import create_test_directory

DATA = Path(__file__).resolve().parents[1] / "data" / "surveys" / "redcap"
DESIGNER = DATA / "sleep_study_DataDictionary.csv"   # Designer header, UTF-8 BOM
API = DATA / "api_metadata.csv"                       # API snake_case header


@pytest.fixture(scope="module")
def result():
    return REDCapImporter().parse_path(DESIGNER)


@pytest.fixture(scope="module")
def api_result():
    return REDCapImporter().parse_path(API)


def _q(result, name):
    return next(q for q in result.all_questions() if q["name"] == name)


def _names(result):
    return {q["name"] for q in result.all_questions()}


def _holds(rule, answers):
    return DisplayLogicEvaluator.evaluate_rule(DisplayLogicRule.from_dict(rule), answers)


def _reported(result, where_fragment, what_fragment=""):
    return [u for u in result.untranslated
            if where_fragment in u.where and what_fragment in (u.what + u.detail)]


# --------------------------------------------------------------------------
# Detection and reading


def test_detects_both_headers_and_nothing_else(tmp_path):
    imp = REDCapImporter()
    assert DESIGNER.read_bytes().startswith(b"\xef\xbb\xbf")
    assert imp.detect_path(DESIGNER)
    assert imp.detect_path(API)
    other = tmp_path / "items.csv"
    other.write_text("id,text\n1,hello\n")
    assert not imp.detect_path(other)
    assert not SurveyJSImporter().detect_path(DESIGNER)


def test_bom_does_not_hide_the_first_column(result):
    # With the BOM left on, "Variable / Field Name" would not match and
    # parsing would refuse the file.
    assert [p.name for p in result.pages] == ["screening", "sleep", "followup"]
    assert result.pages[0].title == "Screening"


def test_cp1252_file_is_read(tmp_path):
    path = tmp_path / "dict.csv"
    path.write_bytes(
        b'"Variable / Field Name","Form Name","Field Type","Field Label"\r\n'
        b'record_id,f,text,ID\r\nmood,f,radio,"Caf\xe9 mood"\r\n')
    res = REDCapImporter().parse_path(path)
    assert _q(res, "mood")["description"] == "Café mood"


def test_record_id_is_left_out(result, api_result):
    assert "record_id" not in _names(result)
    assert "participant_id" not in _names(api_result)
    assert any("record ID" in w for w in result.warnings)


def test_choice_strings_split_on_the_first_comma():
    assert parse_choices("1, Yes | 2, No") == [("1", "Yes"), ("2", "No")]
    assert parse_choices("98, Other, please specify|a_1,<b>Bold</b>") == [
        ("98", "Other, please specify"), ("a_1", "Bold")]


# --------------------------------------------------------------------------
# Field types


def test_field_types(result):
    assert _q(result, "welcome")["annotation_type"] == "pure_display"
    assert _q(result, "welcome")["description"] == "Welcome This study asks about your sleep and mood."
    age = _q(result, "age")
    assert (age["annotation_type"], age["min"], age["max"], age["step"]) == ("number", 18, 99, 1)
    assert age["label_requirement"] == {"required": True}
    assert age["description"] == "How old are you? (Years)"
    assert _q(result, "sleep_hours")["step"] == 0.1
    assert _q(result, "sex")["labels"] == ["Female", "Male", "Intersex", "Prefer not to say"]
    race = _q(result, "race")
    assert race["annotation_type"] == "multiselect"
    assert "Other, please specify" in race["labels"]
    assert _q(result, "caffeine")["annotation_type"] == "select"
    assert _q(result, "smoker")["labels"] == ["Yes", "No"]
    assert _q(result, "shift_work")["labels"] == ["True", "False"]
    assert _q(result, "shift_work")["horizontal"] is True
    assert _q(result, "sleep_problems")["textarea"]["on"] is True
    assert _q(result, "sleep_problems")["placeholder"] == "e.g. noise, worry, pain"
    assert _q(result, "email")["placeholder"] == "name@example.org"
    assert _q(result, "dob")["placeholder"] == "YYYY-MM-DD"
    assert _q(result, "bedtime")["description"] == "1 Usual bedtime"
    energy = _q(result, "energy")
    assert (energy["annotation_type"], energy["min_value"], energy["max_value"]) == ("slider", 0, 100)
    assert "labels" not in energy, "labels would turn the slider into radio buttons"


def test_api_slider_range_and_decimal_step(api_result):
    s = _q(api_result, "pain_score")
    assert (s["min_value"], s["max_value"], s["starting_value"]) == (0, 10, 5)
    assert _q(api_result, "opioid_dose")["step"] == 0.01


def test_section_header_is_a_heading_before_its_field(result):
    sleep = next(p for p in result.pages if p.name == "sleep")
    names = [q["name"] for q in sleep.questions]
    assert names.index("bedtime_section") == names.index("bedtime") - 1
    assert _q(result, "bedtime_section")["description"] == "Your sleep in the past month"
    assert _q(result, "smoker_section")["annotation_type"] == "pure_display"


def test_forms_keep_first_appearance_order_even_when_split(result):
    # contact_thanks is listed after the followup rows but belongs to screening
    screening = result.pages[0]
    assert screening.questions[-1]["name"] == "contact_thanks"


def test_unmapped_fields_are_reported_not_asked(result):
    names = _names(result)
    for field, what in (("sleep_score", "calculated"), ("sleep_diary", "file upload"),
                        ("screen_time", "hidden from participants")):
        assert field not in names
        assert _reported(result, field, what), field
    assert _reported(result, "email", "text validation 'email'")
    assert _reported(result, "dob", "max today")
    assert _reported(result, "energy", "Exhausted")
    assert _reported(result, "wants_contact", "@DEFAULT")
    assert _reported(result, "wants_contact", "piped value")
    assert _reported(result, "dictionary", "first_name, email")
    # @PLACEHOLDER was carried over, so it is not reported
    assert not _reported(result, "sleep_problems", "action tags")


def test_embedded_field_is_removed_from_the_choice(result):
    assert not any("{" in lab for lab in _q(result, "race")["labels"])
    assert _reported(result, "race", "race_other")


# --------------------------------------------------------------------------
# Matrix groups


def test_unreferenced_matrix_is_one_multirate(result):
    grid = _q(result, "mood_grid")
    assert grid["annotation_type"] == "multirate"
    assert grid["options"] == ["Feeling down or hopeless", "Little interest in doing things",
                               "Feeling tired or having little energy"]
    assert grid["labels"] == ["Not at all", "Several days", "More than half the days",
                              "Nearly every day"]
    assert grid["description"].startswith("Over the last two weeks")
    assert grid["label_requirement"] == {"required": True}
    assert not {"mood_down", "mood_interest", "mood_tired"} & _names(result)
    assert result.name_map["mood_down"].startswith("mood_grid")


def test_matrix_tested_by_logic_stays_separate_radios(result):
    for name in ("stress_work", "stress_home"):
        q = _q(result, name)
        assert q["annotation_type"] == "radio" and q["horizontal"] is True
    rule = _q(result, "work_followup")["display_logic"]
    assert _holds(rule, {"stress_work": "Often"})
    assert not _holds(rule, {"stress_work": "Sometimes"})


def test_matrix_rows_with_own_logic_stay_separate(api_result):
    names = _names(api_result)
    assert {"pain_back", "pain_neck", "pain_legs"} <= names
    assert "pain_sites" not in names
    names_in_order = [q["name"] for q in api_result.pages[0].questions]
    assert names_in_order.index("pain_back_section") == names_in_order.index("pain_back") - 1
    rule = _q(api_result, "pain_legs")["display_logic"]
    assert _holds(rule, {"pain_now": "Mild"}) and not _holds(rule, {"pain_now": "None"})


# --------------------------------------------------------------------------
# Branching logic, by behaviour


def test_choice_code_becomes_its_label(result):
    rule = _q(result, "cigs_per_day")["display_logic"]
    assert _holds(rule, {"smoker": "Yes"})
    assert not _holds(rule, {"smoker": "No"})
    assert not _holds(rule, {})


def test_checkbox_choice_reference(result, api_result):
    rule = _q(result, "race_other")["display_logic"]
    assert _holds(rule, {"race": ["Asian", "Other, please specify"]})
    assert not _holds(rule, {"race": ["Asian"]})
    # [race(99)] <> '0': choice 99 is checked
    rule = _q(result, "no_race_answer")["display_logic"]
    assert _holds(rule, {"race": ["Prefer not to say"]})
    assert not _holds(rule, {"race": ["White"]})
    rule = _q(api_result, "opioid_dose")["display_logic"]
    assert _holds(rule, {"pain_meds": ["Opioid", "Ibuprofen"]})
    assert not _holds(rule, {"pain_meds": ["Ibuprofen"]})


def test_numeric_comparisons(result, api_result):
    rule = _q(result, "heavy_smoker_note")["display_logic"]
    assert _holds(rule, {"cigs_per_day": "15"}) and not _holds(rule, {"cigs_per_day": "10"})
    assert not _holds(rule, {}), "unanswered is not a number"
    rule = _q(api_result, "pain_scale_low")["display_logic"]
    assert _holds(rule, {"pain_score": "2"}) and not _holds(rule, {"pain_score": "3"})


def test_numeric_comparison_on_coded_choices(result):
    # [sleep_quality] >= 2 on codes 0..3 with word labels
    rule = _q(result, "sleep_problems")["display_logic"]
    assert _holds(rule, {"sleep_quality": "Fairly bad"})
    assert _holds(rule, {"sleep_quality": "Very bad"})
    assert not _holds(rule, {"sleep_quality": "Fairly good"})
    assert not _holds(rule, {})


def test_and_binds_tighter_than_or(result):
    # [age] >= 65 or [sex] = '1' and [smoker] = '1'
    rule = _q(result, "older_or_female_smoker")["display_logic"]
    assert _holds(rule, {"age": "70", "sex": "Male", "smoker": "No"})
    assert _holds(rule, {"age": "30", "sex": "Female", "smoker": "Yes"})
    assert not _holds(rule, {"age": "30", "sex": "Female", "smoker": "No"})
    assert not _holds(rule, {"age": "30", "sex": "Male", "smoker": "Yes"})


def test_logic_may_test_a_field_on_a_later_form(result):
    rule = _q(result, "contact_thanks")["display_logic"]
    assert _holds(rule, {"wants_contact": "Yes"}) and not _holds(rule, {"wants_contact": "No"})


def test_untranslatable_logic_is_reported_and_question_kept(result, api_result):
    for field, why in (("arm_question", "longitudinal"),
                       ("completed_check", "completion status"),
                       ("senior_check", "function datediff()"),
                       ("not_white", "without a choice code")):
        assert field in _names(result)
        assert "display_logic" not in _q(result, field)
        assert _reported(result, field, why), field
    assert _reported(api_result, "baseline_thanks", "completion status")


def test_not_empty_and_empty():
    imp = REDCapImporter()
    res = imp.parse_text(
        '"Variable / Field Name","Form Name","Field Type","Field Label",'
        '"Choices, Calculations, OR Slider Labels","Branching Logic (Show field only if...)"\n'
        'record_id,f,text,ID,,\n'
        'color,f,dropdown,Color,"r, Red | g, Green",\n'
        'why,f,text,Why?,,"[color] <> """""\n'
        'skip,f,text,Skipped?,,"[color] = \'\'"\n'
        'not_red,f,text,Not red?,,"not([color] = \'r\') AND [color] <> \'\'"\n')
    assert _holds(_q(res, "why")["display_logic"], {"color": "Red"})
    assert not _holds(_q(res, "why")["display_logic"], {})
    assert _holds(_q(res, "skip")["display_logic"], {})
    rule = _q(res, "not_red")["display_logic"]
    assert _holds(rule, {"color": "Green"})
    assert not _holds(rule, {"color": "Red"}) and not _holds(rule, {})


def test_event_reference_tokenizes_as_field_at_event():
    tree = parse("[baseline_arm_1][age] > 30", REDCAP)
    assert tree == ("cmp", ">", ("var", "age@baseline_arm_1"), ("lit", 30))


# --------------------------------------------------------------------------
# Output


def _boot_check(config_path):
    """The generated config passes the same validation the server runs."""
    config_path = str(config_path)
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    normalize_config_before_validation(raw, os.path.dirname(config_path))
    load_and_validate_config(config_path, os.path.dirname(config_path))


@pytest.mark.parametrize("fixture", [DESIGNER, API], ids=["designer", "api"])
def test_new_project_is_valid(fixture):
    out = create_test_directory(f"survey_import_redcap_{fixture.stem}")
    res = REDCapImporter().parse_path(fixture)
    write_new_project(res, out, str(fixture))
    config = yaml.safe_load(open(os.path.join(out, "config.yaml")))
    assert config["phases"]["order"] == [p.name for p in res.pages] + ["annotation"]
    for page in res.pages:
        written = json.load(open(os.path.join(out, "surveys", f"{page.name}.json")))
        assert [q["name"] for q in written] == [q["name"] for q in page.questions]
    report = open(os.path.join(out, "IMPORT_REPORT.md")).read()
    assert "Format: REDCap" in report
    _boot_check(os.path.join(out, "config.yaml"))
