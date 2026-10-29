"""Qualtrics .qsf survey files into Potato survey pages (potato import)."""

import copy
import json
import os
from pathlib import Path

import pytest
import yaml

from potato.importers.surveys.qualtrics import QualtricsImporter
from potato.importers.surveys.writer import write_new_project
from potato.server_utils.config_module import (
    load_and_validate_config, normalize_config_before_validation)
from potato.server_utils.display_logic import (
    DisplayLogicEvaluator, DisplayLogicRule, iter_leaf_conditions)
from potato.server_utils.schemas.registry import schema_registry
from tests.helpers.test_utils import create_test_directory

FIXTURE = (Path(__file__).resolve().parents[1] / "data" / "surveys" / "qualtrics"
           / "media_habits.qsf")


@pytest.fixture(scope="module")
def result():
    return QualtricsImporter().parse_path(FIXTURE)


def _q(result, name):
    return next(q for q in result.all_questions() if q["name"] == name)


def _page(result, name):
    return next(p for p in result.pages if p.name == name)


def _holds(rule, answers):
    return DisplayLogicEvaluator.evaluate_rule(DisplayLogicRule.from_dict(rule), answers)


def _lines(result):
    return [u.line() for u in result.untranslated]


# --------------------------------------------------------------------------
# Detection and structure
# --------------------------------------------------------------------------

def test_detects_qsf_and_not_other_json(tmp_path):
    imp = QualtricsImporter()
    assert imp.detect_path(FIXTURE)
    as_json = tmp_path / "export.json"
    as_json.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    assert imp.detect_path(as_json)
    other = tmp_path / "survey.json"
    other.write_text(json.dumps({"pages": [{"elements": [{"type": "text", "name": "a"}]}]}))
    assert not imp.detect_path(other)
    broken = tmp_path / "broken.qsf"
    broken.write_text("{not json")
    assert not imp.detect_path(broken)


def test_the_fixture_escapes_its_slashes_like_a_real_export():
    raw = FIXTURE.read_text(encoding="utf-8")
    assert "q:\\/\\/QID2\\/SelectableChoice\\/2" in raw


def test_blocks_and_page_breaks_become_pages(result):
    assert result.title == "Social media habits (synthetic)"
    assert [p.name for p in result.pages] == [
        "Screener", "Screener_p2", "Media_habits", "Media_habits_p2", "News_block",
        "Entertainment_block", "Gain_frame", "Loss_frame", "Deep_dive", "Brand_ratings",
        "Wrap_up"]
    assert [q["name"] for q in _page(result, "Screener").questions] == ["intro", "consent", "age"]
    # the Timing question is dropped, the trash block never appears
    assert [q["name"] for q in _page(result, "Screener_p2").questions] == ["platforms"]
    assert "old_q" not in {q["name"] for q in result.all_questions()}


def test_question_types(result):
    assert _q(result, "intro")["annotation_type"] == "pure_display"
    assert _q(result, "intro")["description"] == "Welcome."
    assert _q(result, "intro")["labels"] == ["This study asks about how you use social media."]
    consent = _q(result, "consent")
    assert consent["annotation_type"] == "radio"
    assert consent["labels"] == ["Yes, I agree", "No"]
    assert consent["label_requirement"] == {"required": True}
    age = _q(result, "age")
    assert (age["annotation_type"], age["min"], age["max"]) == ("number", 18, 99)
    assert age["label_requirement"] == {"required": True}
    platforms = _q(result, "platforms")
    assert platforms["annotation_type"] == "multiselect"
    # ChoiceOrder holds ints in real exports
    assert platforms["labels"] == ["Facebook", "Instagram", "TikTok", "Other (please specify)",
                                   "None of these"]
    assert platforms["has_free_response"] == {"instruction": "Other (please specify)"}
    assert platforms["randomize_order"] is True
    assert "label_requirement" not in platforms
    assert _q(result, "frequency")["horizontal"] is True
    assert _q(result, "tiktok_session")["textarea"] == {"on": True, "rows": 4}
    trust = _q(result, "trust")
    assert trust["annotation_type"] == "multirate"
    assert trust["options"] == ["News sites", "Social media", "Friends and family"]
    assert trust["labels"] == ["Distrust", "Neutral", "Trust"]
    for name, label in (("hours_1", "On weekdays"), ("hours_2", "On weekends")):
        s = _q(result, name)
        assert (s["annotation_type"], s["min_value"], s["max_value"], s["starting_value"],
                s["step"]) == ("slider", 0, 12, 0, 0.1)
        assert s["description"].endswith(label)
    assert _q(result, "priorities")["labels"] == ["Accuracy", "Speed", "Entertainment"]
    assert _q(result, "country")["annotation_type"] == "select"
    assert [(_q(result, n)["annotation_type"], _q(result, n)["description"])
            for n in ("about_1", "about_2")] == [
        ("text", "Tell us a little more: City"), ("text", "Tell us a little more: Favorite app")]
    assert _q(result, "news_intro")["description"] == "The next question is about news."
    assert _q(result, "budget")["annotation_type"] == "constant_sum"
    assert _q(result, "recommend")["labels"] == [str(i) for i in range(11)]
    assert _q(result, "stars")["labels"] == ["1", "2", "3", "4", "5"]
    assert _q(result, "comments")["textarea"]["on"] is True
    assert result.name_map["QID10.2"] == "hours_2" and result.name_map["QID2"] == "consent"


def test_every_scheme_renders(result):
    for q in result.all_questions():
        html, _keys = schema_registry.generate(dict(q, annotation_id=0))
        assert "annotation-error" not in html, (q["name"], html[:400])
        assert f'data-schema-name="{q["name"]}"' in html or q["name"] in html


# --------------------------------------------------------------------------
# Display logic
# --------------------------------------------------------------------------

def test_selected_on_a_multiselect_is_contains(result):
    rule = _q(result, "tiktok_session")["display_logic"]
    assert _holds(rule, {"platforms": ["Facebook", "TikTok"]})
    assert not _holds(rule, {"platforms": ["Facebook"]})


def test_and_binds_tighter_than_or_within_a_set(result):
    # Daily Or Weekly And age > 30  ==  Daily OR (Weekly AND age > 30)
    rule = _q(result, "check_first")["display_logic"]
    assert _holds(rule, {"frequency": "Daily", "age": 20})
    assert _holds(rule, {"frequency": "Weekly", "age": 40})
    assert not _holds(rule, {"frequency": "Weekly", "age": 20})
    assert not _holds(rule, {"frequency": "Monthly", "age": 40})


def test_andif_binds_tighter_than_elseif(result):
    # If (consent AND >1 platform) / ElseIf Never / AndIf age < 25
    # == (consent AND >1 platform) OR (Never AND age < 25)
    rule = _q(result, "ad_recall")["display_logic"]
    agreed = {"consent": "Yes, I agree", "platforms": ["Facebook", "TikTok"]}
    # left-to-right reading, ((G0 or G1) and G2), would hide this one
    assert _holds(rule, dict(agreed, frequency="Daily", age=40))
    assert _holds(rule, {"consent": "No", "platforms": [], "frequency": "Never", "age": 20})
    assert not _holds(rule, {"consent": "No", "platforms": [], "frequency": "Never", "age": 40})
    assert not _holds(rule, {"consent": "Yes, I agree", "platforms": ["Facebook"],
                             "frequency": "Daily", "age": 20})


def test_logic_may_test_a_later_page(result):
    rule = _q(result, "country")["display_logic"]
    assert _holds(rule, {"gain_choice": "Accept"})
    assert not _holds(rule, {"gain_choice": "Reject"})


def test_an_untranslatable_condition_drops_the_whole_rule(result):
    # "Daily Selected And QID7 Displayed": no partial rule (Daily alone)
    assert "display_logic" not in _q(result, "session_followup")
    line = next(l for l in _lines(result) if l.startswith("QID14"))
    assert "displayed" in line and "always shown" in line


def test_embedded_field_on_a_condition_factor(result):
    rule = _q(result, "framing_feel")["display_logic"]
    assert _holds(rule, {"condition.frame": "loss"})
    assert not _holds(rule, {"condition.frame": "gain"})


# --------------------------------------------------------------------------
# Flow
# --------------------------------------------------------------------------

def test_counterbalanced_block_randomizer(result):
    assert result.counterbalance == [{"pages": ["News_block", "Entertainment_block"],
                                      "method": "random"}]


def test_show_one_of_n_embedded_data_is_a_condition(result):
    assert result.conditions == {"factors": {"frame": ["gain", "loss"]}, "assignment": "balanced"}
    gain, loss = _page(result, "Gain_frame"), _page(result, "Loss_frame")
    assert _holds(gain.show_when, {"condition.frame": "gain"})
    assert not _holds(gain.show_when, {"condition.frame": "loss"})
    assert _holds(loss.show_when, {"condition.frame": "loss"})
    # the randomizer is translated, not reported
    assert not any("frame = " in l for l in _lines(result))


def test_nested_branches_and_together(result):
    rule = _page(result, "Deep_dive").show_when
    assert _holds(rule, {"frequency": "Daily", "age": 30})
    assert _holds(rule, {"frequency": "Weekly", "age": 21})
    assert not _holds(rule, {"frequency": "Weekly", "age": 20})
    assert not _holds(rule, {"frequency": "Monthly", "age": 30})
    assert _page(result, "Deep_dive").randomize_questions is True


def test_skip_to_end_of_survey_is_an_exit(result):
    rule = _page(result, "Screener").exit_when
    assert rule["message"]
    assert _holds(rule, {"consent": "No"})
    assert not _holds(rule, {"consent": "Yes, I agree"})


def test_end_of_survey_in_a_branch_exits_from_a_page_everyone_sees(result):
    # Media_habits_p2 can be skipped (skip logic), so the exit sits on the page before it
    rule = _page(result, "Media_habits").exit_when
    assert _holds(rule, {"platforms": []})
    assert not _holds(rule, {"platforms": ["TikTok"]})
    assert _page(result, "Media_habits_p2").exit_when is None
    assert any("Media_habits_p2" in w for w in result.warnings)


def test_skip_to_end_of_block_hides_the_rest_of_the_block(result):
    later = _page(result, "Media_habits_p2").show_when
    assert not _holds(later, {"frequency": "Never"})
    assert _holds(later, {"frequency": "Weekly"})
    # Qualtrics applies skip logic when the page is submitted: same-page questions stay
    assert "display_logic" not in _q(result, "frequency")


def test_everything_dropped_is_reported(result):
    lines = _lines(result)
    for needle in ("loop and merge", "piped text: ${lm://Field/1}", "piped text: ${e://Field/frame}",
                   "timing question", "web service", "exclusive choice: None of these",
                   "request response", "display logic on choice 2", "default choices",
                   "question JavaScript", "quota: Adults quota", "constant sum total",
                   "Captcha", "embedded data: PROLIFIC_PID"):
        assert any(needle in line for line in lines), needle
    # empty scoring is not noise in the report
    assert not any("scoring" in line for line in lines)
    # nothing translated shows up as untranslated
    for fine in ("QID8", "QID12", "QID13", "QID7 ", "FL_14", "FL_16", "FL_18", "FL_19"):
        assert not any(line.startswith(fine) for line in lines), fine


# --------------------------------------------------------------------------
# Logic precedence and edge cases on small surveys
# --------------------------------------------------------------------------

def _survey(blocks, flow, questions):
    elements = [{"Element": "BL", "Payload": blocks},
                {"Element": "FL", "Payload": {"Type": "Root", "FlowID": "FL_1", "Flow": flow}}]
    elements += [{"Element": "SQ", "PrimaryAttribute": q["QuestionID"], "Payload": q}
                 for q in questions]
    return {"SurveyEntry": {"SurveyName": "t"}, "SurveyElements": elements}


def _mc(qid, tag, labels, multi=False, **extra):
    return dict({"QuestionID": qid, "DataExportTag": tag, "QuestionType": "MC",
                 "Selector": "MAVR" if multi else "SAVR", "QuestionText": tag,
                 "Choices": {str(i + 1): {"Display": l} for i, l in enumerate(labels)},
                 "ChoiceOrder": [str(i + 1) for i in range(len(labels))]}, **extra)


def _cond(qid, cid, conj=None, op="Selected"):
    e = {"LogicType": "Question", "Operator": op,
         "LeftOperand": f"q://{qid}/SelectableChoice/{cid}", "Type": "Expression"}
    if conj:
        e["Conjuction"] = conj
    return e


def _target_rule(sets):
    """Display logic built from ``sets`` on a question testing a, b, c."""
    logic = {"Type": "BooleanExpression"}
    for i, (stype, exprs) in enumerate(sets):
        s = {str(j): e for j, e in enumerate(exprs)}
        if stype:
            s["Type"] = stype
        logic[str(i)] = s
    qs = [_mc("QID1", "a", ["y", "n"]), _mc("QID2", "b", ["y", "n"]), _mc("QID3", "c", ["y", "n"]),
          _mc("QID4", "target", ["x"], DisplayLogic=logic)]
    blocks = [{"ID": "BL_1", "Description": "One", "Type": "Default",
               "BlockElements": [{"Type": "Question", "QuestionID": f"QID{i}"} for i in range(1, 5)]}]
    res = QualtricsImporter().parse(_survey(blocks, [{"Type": "Block", "ID": "BL_1"}], qs), {})
    return _q(res, "target").get("display_logic"), res


def _abc(a, b, c):
    return {"a": "y" if a else "n", "b": "y" if b else "n", "c": "y" if c else "n"}


CASES = [(a, b, c) for a in (0, 1) for b in (0, 1) for c in (0, 1)]


@pytest.mark.parametrize("sets,truth", [
    # A Or B And C == A or (B and C)
    ([("If", [_cond("QID1", 1), _cond("QID2", 1, "Or"), _cond("QID3", 1, "And")])],
     lambda a, b, c: a or (b and c)),
    # A And B Or C == (A and B) or C
    ([("If", [_cond("QID1", 1), _cond("QID2", 1, "And"), _cond("QID3", 1, "Or")])],
     lambda a, b, c: (a and b) or c),
    # If A / ElseIf B / AndIf C == A or (B and C)
    ([("If", [_cond("QID1", 1)]), ("ElseIf", [_cond("QID2", 1)]), ("AndIf", [_cond("QID3", 1)])],
     lambda a, b, c: a or (b and c)),
    # If A / AndIf B / ElseIf C == (A and B) or C
    ([("If", [_cond("QID1", 1)]), ("AndIf", [_cond("QID2", 1)]), ("ElseIf", [_cond("QID3", 1)])],
     lambda a, b, c: (a and b) or c),
    # a set with no Type joins as AND
    ([("If", [_cond("QID1", 1)]), (None, [_cond("QID2", 1, op="NotSelected")])],
     lambda a, b, c: a and not b),
])
def test_precedence_truth_tables(sets, truth):
    rule, _res = _target_rule(sets)
    for a, b, c in CASES:
        assert _holds(rule, _abc(a, b, c)) is bool(truth(a, b, c)), (a, b, c)


def test_unknown_question_and_matrix_cell_are_reported_not_emitted():
    rule, res = _target_rule([("If", [_cond("QID1", 1), _cond("QID9", 1, "And")])])
    assert rule is None
    assert any("unknown question QID9" in l for l in _lines(res))
    cell = {"LogicType": "Question", "Operator": "Selected",
            "LeftOperand": "q://QID1/SelectableChoice/1/2", "Type": "Expression"}
    rule, res = _target_rule([("If", [cell])])
    assert rule is None and any("matrix cell" in l for l in _lines(res))


def test_a_block_shown_twice_gets_its_own_pages():
    qs = [_mc("QID1", "pick", ["left", "right"]), _mc("QID2", "shared", ["ok"])]
    blocks = {"0": {"ID": "BL_1", "Description": "Pick", "Type": "Default",
                    "BlockElements": [{"Type": "Question", "QuestionID": "QID1"}]},
              "1": {"ID": "BL_2", "Description": "Shared", "Type": "Standard",
                    "BlockElements": [{"Type": "Question", "QuestionID": "QID2"}]}}
    flow = [{"Type": "Block", "ID": "BL_1"},
            {"Type": "Branch", "BranchLogic": {"0": {"0": _cond("QID1", 1), "Type": "If"}},
             "Flow": [{"Type": "Standard", "ID": "BL_2"}]},
            {"Type": "Branch", "BranchLogic": {"0": {"0": _cond("QID1", 2), "Type": "If"}},
             "Flow": [{"Type": "Standard", "ID": "BL_2"}]}]
    res = QualtricsImporter().parse(_survey(blocks, flow, qs), {})
    assert [p.name for p in res.pages] == ["Pick", "Shared", "Shared_2"]
    assert [q["name"] for q in res.pages[2].questions] == ["shared_2"]
    assert _holds(res.pages[2].show_when, {"pick": "right"})
    assert not _holds(res.pages[2].show_when, {"pick": "left"})
    assert any("appears 2 times" in w for w in res.warnings)


def test_show_k_of_n_blocks_is_reported():
    qs = [_mc("QID1", "a", ["y"]), _mc("QID2", "b", ["y"])]
    blocks = [{"ID": f"BL_{i}", "Description": n, "Type": "Standard",
               "BlockElements": [{"Type": "Question", "QuestionID": f"QID{i}"}]}
              for i, n in ((1, "A"), (2, "B"))]
    flow = [{"Type": "BlockRandomizer", "SubSet": "1", "EvenPresentation": True,
             "Flow": [{"Type": "Standard", "ID": "BL_1"}, {"Type": "Standard", "ID": "BL_2"}]}]
    res = QualtricsImporter().parse(_survey(blocks, flow, qs), {})
    assert not res.counterbalance and res.conditions is None
    assert any("presents 1 of 2" in l for l in _lines(res))


def test_not_a_qualtrics_file():
    with pytest.raises(ValueError):
        QualtricsImporter().parse({"pages": []}, {})


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def _boot_check(config_path):
    """The generated config passes the same validation the server runs."""
    config_path = str(config_path)
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    normalize_config_before_validation(raw, os.path.dirname(config_path))
    load_and_validate_config(config_path, os.path.dirname(config_path))


def test_new_project_is_valid():
    out = create_test_directory("survey_import_qualtrics_new")
    res = QualtricsImporter().parse_path(FIXTURE)
    write_new_project(res, out, str(FIXTURE))
    config = yaml.safe_load(open(os.path.join(out, "config.yaml")))
    phases = config["phases"]
    assert phases["order"][-1] == "annotation"
    assert phases["order"][:2] == ["Screener", "Screener_p2"]
    assert phases["counterbalance"] == [{"pages": ["News_block", "Entertainment_block"],
                                         "method": "random"}]
    assert config["conditions"]["factors"] == {"frame": ["gain", "loss"]}
    assert phases["Screener"]["exit_when"]["message"]
    assert phases["Gain_frame"]["show_when"][0]["schema"] == "condition.frame"
    assert phases["Deep_dive"]["randomize_questions"] is True
    page = json.load(open(os.path.join(out, "surveys", "Media_habits.json")))
    assert [q["name"] for q in page] == ["frequency", "tiktok_session", "check_first"]
    report = open(os.path.join(out, "IMPORT_REPORT.md")).read()
    assert "loop and merge" in report and "| QID2 | consent |" in report
    _boot_check(os.path.join(out, "config.yaml"))


def test_a_rule_on_a_later_page_is_kept_off_the_page():
    """Branch logic that tests a question asked later would make the server refuse the config."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    flow = next(e for e in data["SurveyElements"] if e["Element"] == "FL")["Payload"]
    branch = next(n for n in flow["Flow"] if n.get("Description") == "Frequent users")
    branch = copy.deepcopy(branch)
    branch["BranchLogic"]["0"]["0"]["LeftOperand"] = "q://QID26/SelectableChoice/10"
    branch["BranchLogic"]["0"]["1"]["LeftOperand"] = "q://QID26/SelectableChoice/9"
    flow["Flow"] = [n if n.get("Description") != "Frequent users" else branch for n in flow["Flow"]]
    res = QualtricsImporter().parse(data, {})
    deep = _page(res, "Deep_dive").show_when
    assert {c["schema"] for _p, c in iter_leaf_conditions(deep["show_when"])} == {"age"}
    assert any(l.startswith("page 'Deep_dive'") for l in _lines(res))
    out = create_test_directory("survey_import_qualtrics_later")
    write_new_project(res, out, str(FIXTURE))
    _boot_check(os.path.join(out, "config.yaml"))


def _slider(qid, tag, text, statements):
    return {"QuestionID": qid, "DataExportTag": tag, "QuestionType": "Slider",
            "Selector": "HSLIDER", "QuestionText": text,
            "Choices": {str(i + 1): {"Display": s} for i, s in enumerate(statements)},
            "ChoiceOrder": [str(i + 1) for i in range(len(statements))],
            "Configuration": {"CSSliderMin": 0, "CSSliderMax": 120}}


def _one_block(question):
    blocks = {"0": {"ID": "BL_1", "Description": "B", "Type": "Default",
                    "BlockElements": [{"Type": "Question", "QuestionID": question["QuestionID"]}]}}
    return QualtricsImporter().parse(_survey(blocks, [{"Type": "Block", "ID": "BL_1"}],
                                             [question]), {})


def test_a_single_statement_slider_keeps_its_question_text():
    """The one statement is the slider's caption, not a sub-question; it was
    appended, giving "...watching news: Minutes per day"."""
    res = _one_block(_slider("QID1", "news", "How long do you spend watching news?",
                             ["Minutes per day"]))
    assert _q(res, "news")["description"] == "How long do you spend watching news?"


def test_a_single_statement_slider_with_no_text_uses_the_statement():
    res = _one_block(_slider("QID1", "news", "", ["Minutes per day"]))
    assert _q(res, "news")["description"] == "Minutes per day"
