"""XLSForm spreadsheets (ODK / KoboToolbox) into Potato survey pages (potato import).

The workbooks are built here with openpyxl, so the fixture is readable in the
diff rather than a binary .xlsx.
"""

import json
import os
from pathlib import Path

import pytest
import yaml

openpyxl = pytest.importorskip("openpyxl")

from potato.importers.surveys.xlsform import XLSFormImporter  # noqa: E402
from potato.importers.surveys.writer import write_new_project  # noqa: E402
from potato.server_utils.config_module import (  # noqa: E402
    load_and_validate_config, normalize_config_before_validation)
from potato.server_utils.display_logic import DisplayLogicEvaluator, DisplayLogicRule  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

SURVEY_HEADER = ["type", "name", "label::English (en)", "label::Español (es)", "hint::English (en)",
                 "required", "relevant", "appearance", "constraint", "constraint_message::English (en)",
                 "choice_filter", "default", "parameters", "calculation"]

# A household screener in the shape KoboToolbox exports.
SURVEY = [
    ["start", "start"],
    ["end", "end"],
    ["deviceid", "deviceid"],
    ["note", "welcome", "Welcome to the household survey", "Bienvenido"],
    ["integer", "age", "How old are you?", "¿Cuántos años tiene?", "In years", "yes", "", "",
     ". >= 0 and . < 120", "Age must be 0-119"],
    ["select_one yes_no", "consent", "Do you agree to take part?", "¿Acepta?", "", "true()", "", "likert"],
    ["select_multiple langs", "languages", "Which languages do you speak?", "¿Idiomas?", "", "", "",
     "", "", "", "", "", "randomize=true"],
    ["select_one country", "country", "Country of residence", "País", "", "", "", "minimal"],
    ["select_one region", "region", "Region", "Región", "", "", "", "", "", "", "country=${country}"],
    ["text", "other_lang", "Which other language?", "¿Cuál?", "", "", "selected(${languages}, 'other')"],
    ["calculate", "age_months", "", "", "", "", "", "", "", "", "", "", "", "${age} * 12"],
    ["note", "minor_note", "You told us you are under 18", "", "", "", "${age} < 18 and ${consent} = 'yes'"],
    ["begin_group", "household", "Your household", "Su hogar", "", "", "${consent} = ‘yes’", "field-list"],
    ["integer", "hh_size", "How many people live with you?", "", "", "1"],
    ["decimal", "income", "Monthly income", "", "", "", "${hh_size} > 1 or ${age} >= 18"],
    ["select_one tenure", "tenure", "Do you rent or own?", "", "", "", "", "horizontal"],
    ["begin group", "renting", "Renting", "", "", "", "${tenure} = 'rent'"],
    ["integer", "rent", "Monthly rent", "", "", "${hh_size} > 2"],
    ["end group"],
    ["end_group"],
    ["begin_group", "about", "", "", "", "", "count-selected(${languages}) >= 2"],
    ["text", "lang_story", "Tell us how you learned them", "", "", "", "", "multiline"],
    ["range", "happiness", "How happy are you?", "", "", "", "not(${age} < 16)", "", "", "", "", "",
     "start=0 end=10 step=1"],
    ["rank colors", "color_rank", "Rank these colours", ""],
    ["acknowledge", "ack", "I have read the information", ""],
    ["end_group"],
    ["text", "nickname", "Nickname", "", "", "", "string-length(${lang_story}) > 20 and ${country} != ''"],
    ["text", "email", "E-mail", "", "", "", "regex(${nickname}, '^[a-z]+\\.[a-z]+$')"],
    ["date", "visit_date", "Date of visit", ""],
    ["geopoint", "home", "Home location", ""],
    ["text", "months", "Shown for babies", "", "", "", "${age_months} < 12"],
    ["text", "choice_name", "Uses a label lookup", "", "", "", "jr:choice-name(${country}, '${country}') = 'Kenya'"],
    ["text", "summary", "You said ${age}", "", "", "${consent} = 'yes'"],
    ["select_one yes_no or_other", "pet", "Do you have a pet?", ""],
    ["begin_repeat", "members", "Household member", "", "", "", "", "", "", "", "", "", "", ""],
    ["text", "member_name", "Member name", ""],
    ["end_repeat"],
    ["begin_group", "final", "Last questions", "", "", "", "", "table-list"],
    ["select_one yes_no", "followup", "May we contact you again?", "", "", "", "${country} = ''"],
    ["end_group"],
    ["text", "closing", "Any comments?", "", "", "", "not(selected(${languages}, 'en')) or ${pet} = 'other'"],
]

CHOICES = [
    ["list_name", "name", "label::English (en)", "label::Español (es)", "country"],
    ["yes_no", "yes", "Yes", "Sí"],
    ["yes_no", "no", "No", "No"],
    ["langs", "en", "English", "Inglés"],
    ["langs", "sw", "Swahili", "Suajili"],
    ["langs", "other", "Other", "Otro"],
    ["country", "ke", "Kenya", "Kenia"],
    ["country", "tz", "Tanzania", "Tanzania"],
    ["region", "nairobi", "Nairobi", "Nairobi", "ke"],
    ["region", "arusha", "Arusha", "Arusha", "tz"],
    ["tenure", "rent", "Rent", "Alquiler"],
    ["tenure", "own", "Own", "Propia"],
    ["colors", "red", "Red", "Rojo"],
    ["colors", "blue", "Blue", "Azul"],
]

SETTINGS = [["form_title", "form_id", "default_language"],
            ["Household screener", "hh_screener", "English (en)"]]


def _write_xlsx(path, sheets):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for row in rows:
            ws.append(row)
    wb.save(path)
    return Path(path)


@pytest.fixture(scope="module")
def form_path():
    out = create_test_directory("survey_import_xlsform_fixture")
    return _write_xlsx(os.path.join(out, "household.xlsx"),
                       {"survey": [SURVEY_HEADER] + SURVEY, "choices": CHOICES, "settings": SETTINGS})


@pytest.fixture(scope="module")
def result(form_path):
    return XLSFormImporter().parse_path(form_path)


def _q(result, name):
    return next(q for q in result.all_questions() if q["name"] == name)


def _page_of(result, name):
    return next(p for p in result.pages if any(q["name"] == name for q in p.questions))


def _names(result):
    return {q["name"] for q in result.all_questions()}


def _holds(rule, answers):
    return DisplayLogicEvaluator.evaluate_rule(DisplayLogicRule.from_dict(rule), answers)


def _shown(result, name, answers):
    """Whether a question shows: its page rule and its own rule both hold."""
    page = _page_of(result, name)
    rule = _q(result, name).get("display_logic")
    return ((page.show_when is None or _holds(page.show_when, answers))
            and (rule is None or _holds(rule, answers)))


def _reported(result):
    return [u.line() for u in result.untranslated]


# --------------------------------------------------------------------------
# Detection

def test_detects_xlsform_and_not_other_workbooks(form_path):
    imp = XLSFormImporter()
    assert imp.detect_path(form_path)
    out = create_test_directory("survey_import_xlsform_detect")
    other = _write_xlsx(os.path.join(out, "budget.xlsx"), {"Sheet1": [["item", "cost"], ["tea", 2]]})
    assert not imp.detect_path(other)
    no_name = _write_xlsx(os.path.join(out, "survey_only_type.xlsx"), {"survey": [["type", "label"]]})
    assert not imp.detect_path(no_name)


def test_legacy_xls_is_refused_with_advice():
    out = create_test_directory("survey_import_xlsform_xls")
    path = Path(out) / "old.xls"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 504)
    assert XLSFormImporter().detect_path(path)
    with pytest.raises(ValueError, match=r"\.xls"):
        XLSFormImporter().parse_path(path)


# --------------------------------------------------------------------------
# Structure and types

def test_language_and_title(result, form_path):
    assert result.title == "Household screener"
    assert _q(result, "consent")["labels"] == ["Yes", "No"]
    spanish = XLSFormImporter().parse_path(form_path, {"language": "Español (es)"})
    assert _q(spanish, "consent")["labels"] == ["Sí", "No"]
    assert _q(spanish, "age")["description"].startswith("¿Cuántos años tiene?")


def test_pages_follow_field_list_groups(result):
    # Top-level questions share a page; each field-list / table-list group is its own page.
    names = [p.name for p in result.pages]
    assert names == ["page1", "household", "page2", "final", "page3"]
    assert _page_of(result, "age").name == "page1"
    assert _page_of(result, "rent").name == "household"          # nested group stays on the page
    assert _page_of(result, "lang_story").name == "page2"        # non-field-list group: no page
    assert _page_of(result, "nickname").name == "page2"
    assert _page_of(result, "followup").name == "final"
    assert _page_of(result, "closing").name == "page3"


def test_question_types(result):
    age = _q(result, "age")
    assert age["annotation_type"] == "number" and age["step"] == 1
    assert age["label_requirement"] == {"required": True}
    assert age["description"] == "How old are you? (In years)"
    assert _q(result, "income")["step"] == "any"
    consent = _q(result, "consent")
    assert consent["annotation_type"] == "radio" and consent["horizontal"] is True
    assert consent["label_requirement"] == {"required": True}
    langs = _q(result, "languages")
    assert langs["annotation_type"] == "multiselect"
    assert langs["labels"] == ["English", "Swahili", "Other"]
    assert langs["randomize_order"] is True
    assert _q(result, "country")["annotation_type"] == "select"
    assert _q(result, "tenure")["horizontal"] is True
    assert _q(result, "hh_size")["label_requirement"] == {"required": True}
    assert _q(result, "lang_story")["textarea"]["on"] is True
    happy = _q(result, "happiness")
    assert happy["annotation_type"] == "slider"
    assert (happy["min_value"], happy["max_value"], happy["step"], happy["starting_value"]) == (0, 10, 1, 0)
    assert _q(result, "color_rank")["annotation_type"] == "ranking"
    assert _q(result, "color_rank")["labels"] == ["Red", "Blue"]
    assert _q(result, "ack")["labels"] == ["OK"]
    assert _q(result, "welcome")["annotation_type"] == "pure_display"
    pet = _q(result, "pet")
    assert pet["labels"] == ["Yes", "No", "Other"] and pet["has_free_response"]
    assert _q(result, "household_title")["description"] == "Your household"


def test_metadata_and_unsupported_types_are_left_out(result):
    for name in ("start", "end", "deviceid", "age_months", "visit_date", "home"):
        assert name not in _names(result)
    assert "member_name" in _names(result)        # a repeat's questions are imported once


# --------------------------------------------------------------------------
# Logic, evaluated

def test_selected_on_a_multiselect(result):
    assert _shown(result, "other_lang", {"languages": ["English", "Other"]})
    assert not _shown(result, "other_lang", {"languages": ["English"]})


def test_and_with_choice_value_mapping(result):
    assert _shown(result, "minor_note", {"age": 15, "consent": "Yes"})
    assert not _shown(result, "minor_note", {"age": 15, "consent": "No"})
    assert not _shown(result, "minor_note", {"age": 30, "consent": "Yes"})


def test_field_list_group_relevance_is_the_page_rule(result):
    page = _page_of(result, "hh_size")
    assert page.show_when is not None
    assert _holds(page.show_when, {"consent": "Yes"})            # curly quotes in the source
    assert not _holds(page.show_when, {"consent": "No"})
    assert "display_logic" not in _q(result, "hh_size")


def test_or_inside_a_group(result):
    assert _shown(result, "income", {"consent": "Yes", "hh_size": 3})
    assert _shown(result, "income", {"consent": "Yes", "hh_size": 1, "age": 40})
    assert not _shown(result, "income", {"consent": "Yes", "hh_size": 1, "age": 16})
    assert not _shown(result, "income", {"consent": "No", "hh_size": 3})


def test_nested_group_relevance_is_anded(result):
    # rent: inside `renting` (tenure = rent) inside the `household` page (consent = yes)
    assert _shown(result, "rent", {"consent": "Yes", "tenure": "Rent"})
    assert not _shown(result, "rent", {"consent": "Yes", "tenure": "Own"})
    assert not _shown(result, "rent", {"consent": "No", "tenure": "Rent"})
    assert _shown(result, "renting_title", {"consent": "Yes", "tenure": "Rent"})


def test_count_selected_and_not(result):
    # `about` group: count-selected(${languages}) >= 2; happiness adds not(${age} < 16)
    both = {"languages": ["English", "Swahili"], "age": 30}
    assert _shown(result, "lang_story", both)
    assert not _shown(result, "lang_story", {"languages": ["English"], "age": 30})
    assert _shown(result, "happiness", both)
    assert not _shown(result, "happiness", {**both, "age": 12})


def test_string_length_and_not_empty(result):
    long_story = "x" * 30
    assert _shown(result, "nickname", {"lang_story": long_story, "country": "Kenya"})
    assert not _shown(result, "nickname", {"lang_story": "short", "country": "Kenya"})
    assert not _shown(result, "nickname", {"lang_story": long_story})


def test_regex_keeps_backslashes(result):
    rule = _q(result, "email")["display_logic"]
    assert rule["show_when"][0]["value"] == "^[a-z]+\\.[a-z]+$"
    assert _holds(rule, {"nickname": "ada.lovelace"})
    assert not _holds(rule, {"nickname": "adaXlovelace"})


def test_empty_string_is_empty(result):
    assert _shown(result, "followup", {})
    assert not _shown(result, "followup", {"country": "Kenya"})


def test_not_selected_or_other(result):
    assert _shown(result, "closing", {"languages": ["Swahili"]})
    assert not _shown(result, "closing", {"languages": ["English"], "pet": "Yes"})
    assert _shown(result, "closing", {"languages": ["English"], "pet": "Other"})


# --------------------------------------------------------------------------
# Reporting

def test_everything_dropped_is_reported(result):
    lines = _reported(result)
    by_row = {}
    for line in lines:
        by_row.setdefault(line.split(":")[0], []).append(line)

    def row(name):
        return " | ".join(next(v for k, v in by_row.items() if k.endswith(f"'{name}'")))

    assert "constraint" in row("age") and "Age must be 0-119" in row("age")
    assert "choice filter" in row("region")
    assert "calculate field" in row("age_months")
    assert "question type 'date'" in row("visit_date")
    assert "question type 'geopoint'" in row("home")
    assert "age_months is a calculate field" in row("months")
    assert "jr:choice-name" in row("choice_name")
    assert "piped text" in row("summary")
    assert "conditional required" in row("summary")
    assert "repeat" in row("members")
    # Metadata fields are not questions: no report line for them.
    assert not any("'start'" in line or "'deviceid'" in line for line in lines)
    # Translated rules are not reported.
    for name in ("other_lang", "minor_note", "income", "rent", "nickname", "email", "closing"):
        assert not any(f"'{name}'" in line and "relevant" in line for line in lines), name


# --------------------------------------------------------------------------
# Output

def _boot_check(config_path):
    """The generated config passes the same validation the server runs."""
    config_path = str(config_path)
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    normalize_config_before_validation(raw, os.path.dirname(config_path))
    load_and_validate_config(config_path, os.path.dirname(config_path))


def test_new_project_is_valid(form_path):
    out = create_test_directory("survey_import_xlsform_new")
    res = XLSFormImporter().parse_path(form_path)
    write_new_project(res, out, str(form_path))
    config = yaml.safe_load(open(os.path.join(out, "config.yaml")))
    assert config["annotation_task_name"] == "Household screener"
    assert config["phases"]["order"] == ["page1", "household", "page2", "final", "page3", "annotation"]
    assert config["phases"]["household"]["show_when"]
    household = json.load(open(os.path.join(out, "surveys", "household.json")))
    assert {q["name"] for q in household} >= {"hh_size", "income", "tenure", "rent"}
    report = open(os.path.join(out, "IMPORT_REPORT.md")).read()
    assert "choice filter" in report
    _boot_check(os.path.join(out, "config.yaml"))


def test_language_by_code_and_a_missing_one_is_named(form_path):
    """Audit 96 L10: --survey-language fr fell back to English with only the
    generic warning."""
    by_code = XLSFormImporter().parse_path(form_path, {"language": "es"})
    assert _q(by_code, "consent")["labels"] == ["Sí", "No"]
    missing = XLSFormImporter().parse_path(form_path, {"language": "fr"})
    assert any("'fr' is not one of this form's languages" in w for w in missing.warnings)
