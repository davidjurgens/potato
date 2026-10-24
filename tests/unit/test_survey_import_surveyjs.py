"""SurveyJS survey JSON into Potato survey pages (potato import)."""

import json
import os
from pathlib import Path

import pytest
import yaml

from potato.importers.surveys import IMPORTERS, detect
from potato.importers.surveys.expr import SURVEYJS, VarInfo, parse, to_rule
from potato.importers.surveys.writer import apply_prefix, write_into, write_new_project
from potato.server_utils.config_module import (
    load_and_validate_config, normalize_config_before_validation)
from potato.server_utils.display_logic import DisplayLogicEvaluator, DisplayLogicRule
from tests.helpers.test_utils import create_test_directory

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "surveys" / "surveyjs_screener.json"


@pytest.fixture(scope="module")
def result():
    return IMPORTERS["surveyjs"].parse_path(FIXTURE)


def _q(result, name):
    return next(q for q in result.all_questions() if q["name"] == name)


def _holds(rule, answers):
    return DisplayLogicEvaluator.evaluate_rule(DisplayLogicRule.from_dict(rule), answers)


def test_detects_surveyjs_and_not_other_json(tmp_path):
    assert detect(str(FIXTURE)) == "surveyjs"
    other = tmp_path / "items.json"
    other.write_text(json.dumps([{"id": 1, "text": "x"}]))
    assert detect(str(other)) is None


def test_pages_and_types(result):
    assert [p.name for p in result.pages] == ["about_you", "experience"]
    assert _q(result, "age")["annotation_type"] == "number"
    assert _q(result, "age")["label_requirement"] == {"required": True}
    assert _q(result, "country")["labels"] == ["United States", "United Kingdom", "Other"]
    assert _q(result, "country")["has_free_response"]
    assert _q(result, "languages")["annotation_type"] == "multiselect"
    assert _q(result, "languages")["randomize_order"] is True
    assert _q(result, "bilingual_home")["labels"] == ["Yes", "No"]
    assert _q(result, "lang_notes")["textarea"]["on"] is True
    assert _q(result, "annot_exp")["annotation_type"] == "likert"
    assert _q(result, "tool")["annotation_type"] == "select"
    assert _q(result, "agree")["annotation_type"] == "multirate"
    assert {"years_start", "years_end"} <= {q["name"] for q in result.all_questions()}


def test_choice_values_become_labels_in_logic(result):
    rule = _q(result, "state")["display_logic"]
    assert _holds(rule, {"country": "United States"})
    assert not _holds(rule, {"country": "United Kingdom"})


def test_or_of_contains(result):
    rule = _q(result, "lang_notes")["display_logic"]
    assert _holds(rule, {"languages": ["French"]})
    assert not _holds(rule, {"languages": ["English"]})


def test_length_becomes_a_count(result):
    rule = _q(result, "bilingual_home")["display_logic"]
    assert _holds(rule, {"languages": ["English", "Spanish"]})
    assert not _holds(rule, {"languages": ["English"]})


def test_panel_rule_reaches_its_questions(result):
    for name in ("tool", "years_start", "details_title"):
        rule = _q(result, name)["display_logic"]
        assert _holds(rule, {"annot_exp": "4"}) and not _holds(rule, {"annot_exp": "2"})


def test_page_rule_randomization_and_complete_trigger(result):
    about, exp = result.pages
    assert _holds(exp.show_when, {"age": 30}) and not _holds(exp.show_when, {"age": 15})
    assert exp.randomize_questions is True
    assert about.exit_when and _holds(about.exit_when, {"age": 15})


def test_everything_dropped_is_reported(result):
    lines = [u.line() for u in result.untranslated]
    for needle in ("'expression'", "enableIf", "validators", "setvalue"):
        assert any(needle in line for line in lines), needle
    assert not any("bilingual_home" in line for line in lines)


@pytest.mark.parametrize("expression,answers,expected", [
    ("{a} = 'x' and not ({b} > 3)", {"a": "x", "b": 2}, True),
    ("{a} = 'x' and not ({b} > 3)", {"a": "x", "b": 5}, False),
    ("{m} anyof ['p', 'q']", {"m": ["q"]}, True),
    ("{m} allof ['p', 'q']", {"m": ["p"]}, False),
    ("{a} notempty", {"a": "z"}, True),
    ("{a} != 'x'", {"a": "y"}, True),
    ("3 < {b}", {"b": 4}, True),
])
def test_expression_translation(expression, answers, expected):
    def resolve(ref):
        return VarInfo(schema=ref, kind="multi" if ref == "m" else "single")
    rule = to_rule(parse(expression, SURVEYJS), resolve)
    assert _holds(rule, answers) is expected


def _boot_check(config_path):
    """The generated config passes the same validation the server runs."""
    config_path = str(config_path)
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    normalize_config_before_validation(raw, os.path.dirname(config_path))
    load_and_validate_config(config_path, os.path.dirname(config_path))


def test_new_project_is_valid():
    out = create_test_directory("survey_import_surveyjs_new")
    res = IMPORTERS["surveyjs"].parse_path(FIXTURE)
    written = write_new_project(res, out, str(FIXTURE))
    config = yaml.safe_load(open(os.path.join(out, "config.yaml")))
    assert config["phases"]["order"] == ["about_you", "experience", "annotation"]
    assert config["phases"]["experience"]["show_when"]
    assert config["phases"]["about_you"]["exit_when"]["message"]
    pages = json.load(open(os.path.join(out, "surveys", "experience.json")))
    assert any(q["name"] == "annot_exp" for q in pages)
    report = open(os.path.join(out, "IMPORT_REPORT.md")).read()
    assert "enableIf" in report
    assert any(w.endswith("README.md") for w in written)
    _boot_check(os.path.join(out, "config.yaml"))


def test_into_existing_config_writes_a_copy():
    out = create_test_directory("survey_import_surveyjs_into")
    os.makedirs(os.path.join(out, "data"), exist_ok=True)
    with open(os.path.join(out, "data", "d.jsonl"), "w") as f:
        f.write(json.dumps({"id": "1", "text": "hi"}) + "\n")
    base = {"annotation_task_name": "t", "task_dir": ".", "output_annotation_dir": "out/",
            "data_files": ["data/d.jsonl"], "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
            "annotation_schemes": [{"annotation_type": "radio", "name": "age",
                                    "description": "clash", "labels": ["a", "b"]}]}
    cfg = os.path.join(out, "config.yaml")
    with open(cfg, "w") as f:
        yaml.safe_dump(base, f)
    res = IMPORTERS["surveyjs"].parse_path(FIXTURE)
    with pytest.raises(ValueError, match="--prefix"):
        write_into(res, cfg, str(FIXTURE))
    apply_prefix(res, "scr_")
    written = write_into(res, cfg, str(FIXTURE), slot="poststudy", prefix="scr_")
    assert yaml.safe_load(open(cfg)) == base, "the original config was modified"
    merged_path = next(w for w in written if w.endswith(".yaml"))
    merged = yaml.safe_load(open(merged_path))
    assert merged["phases"]["order"] == ["annotation", "scr_about_you", "scr_experience"]
    rule = merged["phases"]["scr_experience"]["show_when"]
    assert rule[0]["schema"] == "scr_age"
    _boot_check(merged_path)
    # Audit 96 L6: the phase-data switch is announced, and a second import
    # with the same prefix refuses to replace the first one's files.
    assert merged["export_include_phase_data"] is True
    assert any("export_include_phase_data" in w for w in res.warnings)
    assert "export_include_phase_data was set to true" in open(merged_path).read()
    with pytest.raises(ValueError, match="would be replaced"):
        write_into(res, cfg, str(FIXTURE), slot="poststudy", prefix="scr_")
    # Audit 96 L6 re-verify: the refusal says "use another --prefix", so
    # another prefix has to write beside the first import, not over it.
    assert os.path.basename(merged_path) == f"config.with-{FIXTURE.stem}-scr.yaml"
    again = IMPORTERS["surveyjs"].parse_path(FIXTURE)
    apply_prefix(again, "alt_")
    second = write_into(again, cfg, str(FIXTURE), slot="poststudy", prefix="alt_")
    assert set(second).isdisjoint(written)
    assert any(os.path.basename(w) == f"IMPORT_REPORT.{FIXTURE.stem}-alt.md" for w in second)


def test_every_question_renders(result):
    """A scheme the generator refuses shows an error box instead of a question."""
    from potato.server_utils.schemas.registry import schema_registry
    for q in result.all_questions():
        html, _ = schema_registry.generate(dict(q))
        assert "Error Generating" not in html and "annotation-error" not in html, q["name"]


def test_untitled_html_element_renders():
    from potato.server_utils.schemas.registry import schema_registry
    res = IMPORTERS["surveyjs"].parse({"pages": [{"elements": [
        {"type": "html", "name": "note", "html": "<p>Read <style>p{x:1}</style>carefully</p>"}]}]}, {})
    q = next(res.all_questions())
    assert q["description"] == "Read carefully"
    html, _ = schema_registry.generate(dict(q))
    assert "Error Generating" not in html
