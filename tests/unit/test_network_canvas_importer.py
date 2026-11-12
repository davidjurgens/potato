"""Network Canvas protocol import, on a synthetic protocol written here.

The protocol below exercises the documented shape of the format (stages,
codebook, assetManifest, skipLogic filters); it is not copied from any
published protocol.
"""

import json
import os
import zipfile
from pathlib import Path

import pytest

from potato.importers import surveys
from potato.importers.surveys.network_canvas import NetworkCanvasImporter, md_to_text
from potato.importers.surveys.writer import write_new_project
from potato.server_utils.phase_files import check_phase_schemes, load_phase_schemes
from potato.server_utils.schemas.ego_network import normalize_scheme
from tests.helpers.test_utils import create_test_directory


def protocol():
    yes_no = [{"label": {"en-US": "Yes", "fr": "Oui"}, "value": True},
              {"label": {"en-US": "No", "fr": "Non"}, "value": False}]
    return {
        "name": "Synthetic study", "schemaVersion": 8,
        "assetManifest": {"club": {"id": "club", "type": "network", "name": "club",
                                   "source": "club_members.csv"}},
        "codebook": {
            "ego": {"variables": {
                "v_consent": {"name": "consent", "type": "boolean", "component": "Boolean",
                              "options": yes_no, "validation": {"required": True}},
                "v_age": {"name": "age", "type": "number", "component": "Number",
                          "validation": {"minValue": 18, "maxValue": 99}},
                "v_mood": {"name": "mood", "type": "ordinal", "component": "LikertScale",
                           "options": [{"label": "Low", "value": 1}, {"label": "Mid", "value": 2},
                                       {"label": "High", "value": 3}]},
                "v_groups": {"name": "groups", "type": "categorical", "component": "CheckboxGroup",
                             "options": [{"label": "Sport", "value": "sport"},
                                         {"label": "Faith", "value": "faith"},
                                         {"label": "Arts", "value": "arts"}]},
                "v_note": {"name": "note", "type": "text", "component": "TextArea"},
                "v_dob": {"name": "dob", "type": "datetime", "component": "DatePicker"},
                "v_feel": {"name": "feel", "type": "scalar", "component": "VisualAnalogScale",
                           "parameters": {"minLabel": "Bad", "maxLabel": "Good"}},
            }},
            "node": {"person": {"name": "Person", "variables": {
                "n_name": {"name": "name", "type": "text"},
                "n_age": {"name": "alter_age", "type": "number"},
                "n_support": {"name": "support", "type": "boolean"},
                "n_close": {"name": "closeness", "type": "ordinal",
                            "options": [{"label": "Very close", "value": 3}, {"label": "Close", "value": 2},
                                        {"label": "Not close", "value": 1}]},
                "n_kin": {"name": "kin", "type": "boolean", "options": yes_no},
                "n_layout": {"name": "layout", "type": "layout"},
            }}},
            "edge": {"knows": {"name": "knows", "variables": {}},
                     "close_tie": {"name": "close_tie", "variables": {
                         "e_strength": {"name": "strength", "type": "ordinal",
                                        "options": [{"label": "Strong", "value": "strong"},
                                                    {"label": "Weak", "value": "weak"}]}}}},
        },
        "stages": [
            {"id": "s_intro", "type": "Information", "label": "Welcome", "title": "## Welcome",
             "items": [{"type": "text", "content": "This study is about **your** network.\n\nIt takes ten minutes."},
                       {"type": "asset", "content": "picture"}]},
            {"id": "s_consent", "type": "EgoForm", "label": "Consent",
             "introductionPanel": {"title": "Consent", "text": "Please read this."},
             "form": {"fields": [{"variable": "v_consent", "prompt": "Do you agree to take part?"}]}},
            {"id": "s_about", "type": "EgoForm", "label": "About you",
             "skipLogic": {"action": "SKIP", "destination": {"type": "stage", "stageId": "s_end_no"},
                           "filter": {"rules": [{"type": "ego", "options": {
                               "attribute": "v_consent", "operator": "EXACTLY", "value": False}}]}},
             "form": {"fields": [{"variable": "v_age", "prompt": "Your age?"},
                                 {"variable": "v_mood", "prompt": "Your mood?"},
                                 {"variable": "v_groups", "prompt": "Groups you belong to?"},
                                 {"variable": "v_note", "prompt": "Anything else?"},
                                 {"variable": "v_dob", "prompt": "Date of birth?"},
                                 {"variable": "v_feel", "prompt": "How do you feel?"}]}},
            {"id": "ng", "type": "NameGenerator", "label": "People",
             "subject": {"entity": "node", "type": "person"},
             "behaviours": {"minNodes": 1, "maxNodes": 6},
             "form": {"fields": [{"variable": "n_name", "prompt": "Name?"},
                                 {"variable": "n_age", "prompt": "How old is this person?"}]},
             "prompts": [{"id": "talk", "text": "Who do you **talk** to?",
                          "additionalAttributes": [{"variable": "n_support", "value": True}]},
                         {"id": "help", "text": "Who helps you?"}]},
            {"id": "info_mid", "type": "Information", "label": "Next",
             "items": [{"type": "text", "content": "Now some questions about them."}]},
            {"id": "af", "type": "AlterForm", "label": "About them",
             "subject": {"entity": "node", "type": "person"},
             "form": {"fields": [{"variable": "n_kin", "prompt": "Is {nodeLabel} family?"}]}},
            {"id": "bin", "type": "OrdinalBin", "label": "Closeness",
             "subject": {"entity": "node", "type": "person"},
             "prompts": [{"id": "pclose", "text": "How close are you?", "variable": "n_close"}]},
            {"id": "dc", "type": "DyadCensus", "label": "Who knows whom",
             "subject": {"entity": "node", "type": "person"},
             "prompts": [{"id": "dck", "text": "Do these people know each other?", "createEdge": "knows"}]},
            {"id": "tsc", "type": "TieStrengthCensus", "label": "How close",
             "subject": {"entity": "node", "type": "person"},
             "prompts": [{"id": "tscp", "text": "How close are they?", "createEdge": "close_tie",
                          "edgeVariable": "e_strength", "negativeLabel": "Not close at all"}]},
            {"id": "soc", "type": "Sociogram", "label": "Map",
             "subject": {"entity": "node", "type": "person"},
             "background": {"concentricCircles": 4},
             "prompts": [{"id": "socp", "text": "Place people", "layout": {"layoutVariable": "n_layout"},
                          "edges": {"create": "knows"}}]},
            {"id": "roster", "type": "NameGeneratorRoster", "label": "Club",
             "subject": {"entity": "node", "type": "person"}, "dataSource": "club",
             "prompts": [{"id": "clubp", "text": "Who from the club do you know?"}]},
            {"id": "older", "type": "Information", "label": "Older",
             "skipLogic": {"action": "SHOW", "filter": {"join": "OR", "rules": [
                 {"type": "ego", "options": {"attribute": "v_age", "operator": "GREATER_THAN", "value": 60}},
                 {"type": "ego", "options": {"attribute": "v_groups", "operator": "INCLUDES",
                                             "value": ["sport", "arts"]}}]}},
             "items": [{"type": "text", "content": "A note for older participants."}]},
            {"id": "nodey", "type": "EgoForm", "label": "Follow-up",
             "skipLogic": {"action": "SKIP", "filter": {"rules": [
                 {"type": "node", "options": {"type": "person", "operator": "EXISTS"}}]}},
             "form": {"fields": [{"variable": "v_note", "prompt": "One more thing?"}]}},
            {"id": "narr", "type": "Narrative", "label": "Story",
             "subject": {"entity": "node", "type": "person"}},
            {"id": "s_end", "type": "FinishSession", "label": "End", "content": "# Done"},
            {"id": "s_end_no", "type": "FinishSession", "label": "Declined",
             "content": "# You chose not to take part\n\nThank you."},
        ],
    }


@pytest.fixture
def workdir():
    return Path(create_test_directory("network_canvas_import"))


def netcanvas(workdir, data=None, roster="name,role\nZoe,coach\nYan,player\nZoe,dup\n"):
    path = workdir / "study.netcanvas"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("protocol.json", json.dumps(data or protocol()))
        if roster is not None:
            zf.writestr("assets/club_members.csv", roster)
    return path


def parse(workdir, **kw):
    return NetworkCanvasImporter().parse_path(netcanvas(workdir, **kw), {})


def page(result, name):
    return next(p for p in result.pages if p.name == name)


def ego_scheme(result):
    return next(q for p in result.pages for q in p.questions if q["annotation_type"] == "ego_network")


class TestDetection:
    def test_netcanvas_zip_and_bare_protocol(self, workdir):
        path = netcanvas(workdir)
        assert surveys.detect(str(path)) == "network_canvas"
        bare = workdir / "protocol.json"
        bare.write_text(json.dumps(protocol()))
        assert surveys.detect(str(bare)) == "network_canvas"
        other = workdir / "other.json"
        other.write_text(json.dumps({"pages": [{"elements": [{"type": "text", "name": "q"}]}]}))
        assert surveys.detect(str(other)) == "surveyjs"

    @pytest.mark.parametrize("alias", ["network_canvas", "netcanvas", "networkcanvas", "NetCanvas"])
    def test_aliases(self, alias):
        assert surveys.resolve(alias) == "network_canvas"


class TestPages:
    def test_page_order_and_kinds(self, workdir):
        r = parse(workdir)
        assert [p.name for p in r.pages] == ["welcome", "consent", "about_you", "people", "older", "follow_up"]
        intro = page(r, "welcome").questions[0]
        assert intro["annotation_type"] == "pure_display"
        assert intro["description"] == "Welcome."
        assert intro["labels"] == ["This study is about your network.", "It takes ten minutes."]

    def test_ego_form_question_types(self, workdir):
        r = parse(workdir)
        qs = {q["name"]: q for q in page(r, "about_you").questions}
        assert qs["age"]["annotation_type"] == "number" and (qs["age"]["min"], qs["age"]["max"]) == (18, 99)
        assert qs["mood"]["annotation_type"] == "radio" and qs["mood"]["horizontal"] is True
        assert [l["name"] for l in qs["mood"]["labels"]] == ["1", "2", "3"]
        assert qs["groups"]["annotation_type"] == "multiselect"
        assert qs["note"]["annotation_type"] == "text" and qs["note"]["textarea"]["on"] is True
        assert qs["feel"]["annotation_type"] == "vas" and qs["feel"]["left_label"] == "Bad"
        assert "dob" not in qs
        consent = page(r, "consent").questions
        assert consent[0]["annotation_type"] == "pure_display"
        c = consent[1]
        assert c["labels"] == [{"name": "true", "text": "Yes"}, {"name": "false", "text": "No"}]
        assert c["label_requirement"] == {"required": True}

    def test_every_page_renders_as_a_phase_page(self, workdir):
        r = parse(workdir)
        out = workdir / "project"
        write_new_project(r, str(out), "study.netcanvas")
        for p in r.pages:
            schemes = load_phase_schemes(str(out / "surveys" / f"{p.name}.json"))
            check_phase_schemes(schemes, p.name, p.name)
        assert (out / "IMPORT_REPORT.md").read_text().count("datetime") >= 1


class TestNetwork:
    def test_one_scheme_with_every_network_stage(self, workdir):
        r = parse(workdir)
        ego = ego_scheme(r)
        normalize_scheme(ego)  # validates
        kinds = [(s["type"], s["id"]) for s in ego["stages"]]
        assert kinds == [("name_generator", "talk"), ("name_generator", "help"),
                         ("name_interpreter", "ng_details"), ("name_interpreter", "af"),
                         ("name_interpreter", "bin"), ("dyad_census", "dck"), ("dyad_census", "tscp"),
                         ("sociogram", "socp"), ("name_generator", "clubp")]
        talk, help_, details, af, bins, dc, tsc, soc, club = ego["stages"]
        assert talk["min_alters"] == 1 and talk["max_alters"] == 6 and "min_alters" not in help_
        assert talk["sets"] == {"support": True} and talk["prompt"] == "Who do you talk to?"
        assert [q["name"] for q in details["questions"]] == ["alter_age"]
        assert af["questions"][0]["description"] == "Is {name} family?"
        assert af["instructions"] == "Now some questions about them."
        assert bins["questions"][0]["type"] == "radio"
        assert [l["text"] for l in bins["questions"][0]["labels"]] == ["Very close", "Close", "Not close"]
        assert dc["relation"] == "knows" and "{a}" in dc["prompt"]
        assert tsc["relation"] == "close_tie" and tsc["strength_variable"] == "strength"
        assert [l["name"] for l in tsc["strength_labels"]] == ["strong", "weak"]
        assert tsc["no_label"] == "Not close at all"
        assert soc["rings"] == 4 and soc["relation"] == "knows"
        assert [x["name"] for x in club["roster"]] == ["Zoe", "Yan"]
        assert ego["label_requirement"] == {"required": True}

    def test_roster_missing_from_the_file_is_reported(self, workdir):
        r = parse(workdir, roster=None)
        club = ego_scheme(r)["stages"][-1]
        assert "roster" not in club
        assert any("club_members.csv" in u.detail for u in r.untranslated)

    def test_json_network_asset_roster(self, workdir):
        data = protocol()
        data["assetManifest"]["club"]["source"] = "club.json"
        path = workdir / "json.netcanvas"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("protocol.json", json.dumps(data))
            zf.writestr("assets/club.json", json.dumps(
                {"nodes": [{"attributes": {"name": "Ola"}}, {"attributes": {"nick": "Pip"}}]}))
        r = NetworkCanvasImporter().parse_path(path, {})
        assert [x["name"] for x in ego_scheme(r)["stages"][-1]["roster"]] == ["Ola", "Pip"]


class TestLogic:
    def test_skip_to_finish_becomes_exit_when_on_the_page_before(self, workdir):
        r = parse(workdir)
        exit_rule = page(r, "consent").exit_when
        assert exit_rule["show_when"] == [{"schema": "consent", "operator": "equals", "value": "false"}]
        assert exit_rule["message"].startswith("You chose not to take part.")

    def test_show_with_or_rules(self, workdir):
        r = parse(workdir)
        rule = page(r, "older").show_when
        assert rule["show_when"] == [{"any": [
            {"schema": "age", "operator": "gt", "value": 60},
            {"all": [{"schema": "groups", "operator": "contains", "value": "sport"},
                     {"schema": "groups", "operator": "contains", "value": "arts"}]}]}]

    def test_node_rules_and_unsupported_stages_are_reported(self, workdir):
        r = parse(workdir)
        lines = [u.line() for u in r.untranslated]
        assert page(r, "follow_up").show_when is None
        assert any("Follow-up" in l and "node data" in l for l in lines)
        assert any("Narrative" in l for l in lines)
        assert any("datetime" in l for l in lines)
        assert any("asset item" in l for l in lines)
        assert not any("FinishSession" in l for l in lines)   # used as the exit, not dropped

    def test_language_choice(self, workdir):
        path = netcanvas(workdir)
        fr = NetworkCanvasImporter().parse_path(path, {"language": "fr"})
        assert page(fr, "consent").questions[1]["labels"][0]["text"] == "Oui"
        en = NetworkCanvasImporter().parse_path(path, {})
        assert any("en-US, fr" in w and "imported en-US" in w for w in en.warnings)


def test_markdown_to_text():
    assert md_to_text("# Title\n\nSome **bold** and _em_ and [a link](https://x.org).") == \
        "Title.\n\nSome bold and em and a link (https://x.org)."
