"""
Label Studio project import: questions, people's answers, model suggestions.

Fixtures are in tests/data/importers/label_studio (see the README there).
"""

import json
from pathlib import Path

import pytest

from potato.importers.projects import detect, resolve
from potato.importers.projects.base import utf16_to_code_points
from potato.importers.projects.label_studio import LabelStudioImporter
from potato.importers.projects.writer import label_entries

FIX = Path(__file__).resolve().parents[1] / "data" / "importers" / "label_studio"


def parse(name, xml=None):
    options = {"ls_config": str(FIX / xml)} if xml else {}
    return LabelStudioImporter().parse_path(FIX / name, options)


@pytest.fixture(scope="module")
def text():
    return parse("text_project.json", "text_label_config.xml")


@pytest.fixture(scope="module")
def image():
    return parse("image_project.json", "image_label_config.xml")


def scheme(result, name):
    return next(s for s in result.schemes if s["name"] == name)


class TestQuestions:
    def test_tags_map_to_scheme_types(self, text):
        types = {s["name"]: s["annotation_type"] for s in text.schemes}
        assert types == {"sentiment": "radio", "ner": "span", "topics": "multiselect",
                         "quality": "likert", "summary": "text"}

    def test_options_nobody_chose_survive_with_the_xml(self, text):
        assert scheme(text, "sentiment")["labels"] == ["Positive", "Neutral", "Negative"]
        assert "food" in scheme(text, "topics")["labels"]

    def test_header_becomes_the_description_and_colours_carry(self, text):
        assert scheme(text, "sentiment")["description"] == "What is the overall sentiment?"
        assert {"name": "PER", "color": "#ff0000"} in scheme(text, "ner")["labels"]

    def test_rating_and_textarea_settings(self, text):
        assert scheme(text, "quality")["size"] == 5
        assert scheme(text, "summary")["multiline"] is True

    def test_an_unsupported_tag_is_reported_not_imported(self, text):
        assert "domain" not in {s["name"] for s in text.schemes}
        assert any("Taxonomy" in w for w in text.warnings)
        assert text.skipped["answers of type 'taxonomy'"] == 1

    def test_without_the_xml_questions_are_inferred_with_a_warning(self):
        result = parse("text_project.json")
        assert {s["name"] for s in result.schemes} >= {"sentiment", "ner", "topics"}
        assert "Negative" not in scheme(result, "sentiment")["labels"]  # nobody chose it
        assert scheme(result, "topics")["annotation_type"] == "multiselect"
        assert any("--ls-config" in w for w in result.warnings)


class TestPeoplesAnswers:
    def test_each_annotator_is_kept_apart(self, text):
        item = text.items[0]
        assert item.responses["ls_user_7"]["sentiment"] == "Neutral"
        assert item.responses["bo@example.org"]["sentiment"] == "Positive"
        assert item.responses["ls_user_7"]["topics"] == ["travel", "people"]
        assert item.responses["ls_user_7"]["quality"] == 4
        assert item.responses["ls_user_7"]["summary"] == "Trip to Rome"

    def test_a_cancelled_annotation_is_dropped_and_counted(self, text):
        assert "ls_user_11" not in text.items[0].responses
        assert text.skipped["cancelled annotations"] == 1

    def test_annotator_names_map_back_to_the_source(self, text):
        assert text.annotator_ids["ls_user_7"] == "id 7"
        assert text.annotator_ids["bo@example.org"] == "bo@example.org (id 9)"

    def test_one_person_in_two_forms_is_one_annotator(self, tmp_path):
        """A bare id in one task and {"id", "email"} in another are the same user."""
        tasks = [
            {"id": 1, "data": {"text": "a"}, "annotations": [{"completed_by": 7, "result": [
                {"from_name": "s", "to_name": "text", "type": "choices", "value": {"choices": ["x"]}}]}]},
            {"id": 2, "data": {"text": "b"}, "annotations": [{"completed_by": {"id": 7, "email": "ann@lab.org"},
                "result": [{"from_name": "s", "to_name": "text", "type": "choices", "value": {"choices": ["y"]}}]}]},
        ]
        path = tmp_path / "export.json"
        path.write_text(json.dumps(tasks))
        result = LabelStudioImporter().parse_path(path)
        assert list(result.annotator_ids) == ["ann@lab.org"]
        assert {u for item in result.items for u in item.responses} == {"ann@lab.org"}

    def test_a_task_without_an_id_cannot_collide(self, tmp_path):
        tasks = [{"data": {"text": "no id"}, "annotations": []},
                 {"id": 0, "data": {"text": "id zero"}, "annotations": []}]
        path = tmp_path / "export.json"
        path.write_text(json.dumps(tasks))
        ids = [item.instance_id for item in LabelStudioImporter().parse_path(path).items]
        assert ids == ["ls_task_0", "0"]

    def test_utf16_offsets_after_an_emoji_become_code_points(self, text):
        item = text.items[1]
        [span] = item.responses["ls_user_7"]["ner"]
        assert item.fields["text"][span["start"]:span["end"]] == "Tokyo Grill"

    def test_the_conversion_itself(self):
        s = "a😀b"
        assert utf16_to_code_points(s, 3) == 2   # 'b' is unit 3, index 2
        assert utf16_to_code_points("plain", 3) == 3


class TestSuggestions:
    def test_the_highest_scoring_prediction_wins(self, text):
        item = text.items[0]
        assert item.predictions["sentiment"] == "Neutral"       # v2, 0.91
        assert item.prediction_sources["sentiment"] == {"model": "sentiment-v2", "score": 0.91}
        assert text.skipped["extra predictions on one task (highest score kept)"] == 1

    def test_a_task_with_no_prediction_has_none(self, text):
        assert text.items[1].predictions == {}


class TestImages:
    def test_tools_merge_into_one_image_scheme(self, image):
        [s] = image.schemes
        assert s["annotation_type"] == "image_annotation"
        assert s["tools"] == ["bbox", "polygon"]
        assert s["source_field"] == "image"
        assert {l["name"] for l in s["labels"]} == {"Car", "Person", "Road"}
        assert image.text_key == "image"

    def test_percent_geometry_becomes_normalized(self, image):
        objects = image.items[0].responses["ls_user_7"]["image"]
        box = next(o for o in objects if o["type"] == "bbox")
        assert box["coordinates"] == pytest.approx(
            {"x": 0.10, "y": 0.20, "width": 0.30, "height": 0.40})
        assert box["source"] == "import" and box["import_format"] == "label_studio"
        polygon = next(o for o in objects if o["type"] == "polygon")
        assert polygon["coordinates"][2] == pytest.approx({"x": 0.6, "y": 0.8})

    def test_a_predicted_box_names_its_model(self, image):
        [box] = image.items[0].predictions["image"]
        assert box["source"] == "ai" and box["ai_model"] == "yolo-v8"
        assert box["confidence"] == pytest.approx(0.8)


class TestDetection:
    def test_detects_an_export_and_resolves_aliases(self):
        assert detect(str(FIX / "text_project.json")) == "label_studio"
        assert resolve("label-studio") == resolve("ls") == "label_studio"

    def test_does_not_claim_other_json(self, tmp_path):
        other = tmp_path / "coco.json"
        other.write_text(json.dumps({"images": [], "annotations": []}))
        assert detect(str(other)) is None


class TestStoredFormat:
    """The pairs a live browser save writes (captured on 2.11.1)."""

    @pytest.mark.parametrize("kind,value,expected", [
        ("radio", "pos", [[{"schema": "s", "name": "pos"}, "pos"]]),
        ("multiselect", ["a", "c"], [[{"schema": "s", "name": "a"}, "a"],
                                     [{"schema": "s", "name": "c"}, "c"]]),
        ("likert", 4, [[{"schema": "s", "name": "4"}, "4"]]),
        ("text", "hi", [[{"schema": "s", "name": "text_box"}, "hi"]]),
        ("number", 7, [[{"schema": "s", "name": "number"}, "7"]]),
        ("slider", 8, [[{"schema": "s", "name": "slider"}, "8"]]),
    ])
    def test_label_entries(self, kind, value, expected):
        assert label_entries({"name": "s", "annotation_type": kind}, value) == expected


class TestKeptAnnotatorsProject:
    """What --keep-annotators writes, and what deploy preflight makes of it."""

    @pytest.fixture
    def project(self, tmp_path):
        from potato.importers.cli import main
        out = tmp_path / "proj"
        assert main(["-i", str(FIX / "text_project.json"), "--ls-config",
                     str(FIX / "text_label_config.xml"), "-o", str(out),
                     "--keep-annotators"]) == 0
        return out

    def test_enrolment_is_closed_to_the_imported_names(self, project):
        import yaml
        config = yaml.safe_load((project / "config.yaml").read_text())
        assert config["require_password"] is False
        assert config["user_config"] == {"allow_all_users": False,
                                         "users": ["bo@example.org", "ls_user_7"]}
        assert config["max_annotations_per_item"] == 2
        roster = [json.loads(line) for line in
                  (project / "annotation_output" / "user_config.json").read_text().splitlines()]
        assert roster == [{"username": "bo@example.org"}, {"username": "ls_user_7"}]

    def test_a_public_deploy_is_refused_until_passwords_exist(self, project):
        from potato.deploy.preflight import run_preflight
        report = run_preflight(str(project / "config.yaml"), provider="render")
        codes = [f.code for f in report.errors]
        assert "D022" in codes, [(f.code, f.message) for f in report.findings]

        # With passwords on every roster row, the finding goes away.
        roster = project / "annotation_output" / "user_config.json"
        rows = [dict(json.loads(line), password="pw") for line in roster.read_text().splitlines()]
        roster.write_text("".join(json.dumps(r) + "\n" for r in rows))
        report = run_preflight(str(project / "config.yaml"), provider="render")
        assert "D022" not in [f.code for f in report.findings]
