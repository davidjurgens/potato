"""Zooniverse project import: workflow tasks, branching, subjects, classifications.

The fixtures under tests/data/zooniverse/ are invented. `project/` is a whole
project export (workflows, subjects, classifications) for one workflow with
two major versions; `workflow_branching.api.json` is a workflow alone, in the
Panoptes API's shape; `text_project/` has a highlighter task over text.
"""

import json
import os
from pathlib import Path

import pytest
import yaml

from potato.importers.projects.base import SUPPORTED_TYPES
from potato.importers.projects.writer import write_project
from potato.importers.projects.zooniverse import ZooniverseImporter, clean_text
from potato.server_utils.config_module import (
    load_and_validate_config, normalize_config_before_validation)
from potato.server_utils.display_logic import (DisplayLogicEvaluator,
                                               validate_display_logic_config)
from tests.helpers.test_utils import create_test_directory

DATA = Path(__file__).resolve().parents[1] / "data" / "zooniverse"
PROJECT = DATA / "project"
CLASSIFICATIONS = PROJECT / "animal-finder-classifications.csv"
WORKFLOWS = PROJECT / "animal-finder-workflows.csv"
BRANCHING = DATA / "workflow_branching.api.json"
TEXT_PROJECT = DATA / "text_project"


@pytest.fixture(scope="module")
def result():
    return ZooniverseImporter().parse_path(PROJECT)


def schemes_by_name(res):
    return {s["name"]: s for s in res.schemes}


def visible(scheme, answers):
    shown, _ = DisplayLogicEvaluator.evaluate_visibility(
        scheme["name"], scheme.get("display_logic"), answers)
    return shown


def item(res, instance_id):
    return next(i for i in res.items if i.instance_id == instance_id)


# ----------------------------------------------------------------- detection

class TestDetection:
    def test_detects_each_input_shape(self):
        imp = ZooniverseImporter()
        assert imp.detect_path(PROJECT)
        assert imp.detect_path(CLASSIFICATIONS)
        assert imp.detect_path(WORKFLOWS)
        assert imp.detect_path(BRANCHING)

    def test_rejects_other_files(self):
        out = Path(create_test_directory("zooniverse_detect_negative"))
        ls = out / "ls.json"
        ls.write_text(json.dumps([{"data": {"text": "x"}, "annotations": []}]))
        plain = out / "plain.csv"
        plain.write_text("id,text\n1,hello\n")
        subjects_only = PROJECT / "animal-finder-subjects.csv"
        imp = ZooniverseImporter()
        assert not imp.detect_path(ls)
        assert not imp.detect_path(plain)
        # A subject export alone has no questions to import.
        assert not imp.detect_path(subjects_only)


# ----------------------------------------------------------------- schemes

class TestSchemes:
    def test_tasks_map_to_schemes(self, result):
        schemes = schemes_by_name(result)
        assert list(schemes) == ["T0", "T1", "T2", "T3", "T4"]
        assert schemes["T0"]["annotation_type"] == "radio"
        # Translation keys are resolved through `strings`, markdown is removed.
        assert schemes["T0"]["description"] == "Is there an animal in the image?"
        assert schemes["T0"]["labels"] == ["Yes", "No"]
        assert schemes["T0"]["label_requirement"] == {"required": True}
        assert schemes["T2"]["annotation_type"] == "multiselect"
        # An answer that is an image plus a word becomes the word.
        assert schemes["T2"]["labels"] == ["Grass", "Water", "Sky"]
        assert schemes["T3"]["annotation_type"] == "text"
        slider = schemes["T4"]
        assert (slider["annotation_type"], slider["min_value"], slider["max_value"],
                slider["step"], slider["starting_value"]) == ("slider", 0, 10, 1, 5)

    def test_drawing_becomes_image_annotation(self, result):
        drawing = schemes_by_name(result)["T1"]
        assert drawing["annotation_type"] == "image_annotation"
        assert drawing["tools"] == ["bbox", "landmark"]
        assert drawing["labels"] == [{"name": "Animal", "color": "#ff0000"},
                                     {"name": "Eye", "color": "#00ff00"}]
        assert drawing["source_field"] == "image"
        assert result.text_key == "image"

    def test_survey_and_details_are_reported(self, result):
        assert result.skipped["survey tasks"] == 1
        assert result.skipped["drawing detail questions"] == 1
        assert any("T5 (survey)" in w for w in result.warnings)
        assert "T5" not in schemes_by_name(result)

    def test_guidelines_carry_task_help(self, result):
        assert "Look at the whole image." in result.guidelines


# ----------------------------------------------------------------- branching

class TestBranching:
    def test_branches_become_display_logic(self, result):
        schemes = schemes_by_name(result)
        assert "display_logic" not in schemes["T0"]
        # Both answers of T0 lead (through T1 or T2) to T3, so it always shows.
        assert "display_logic" not in schemes["T3"]
        assert "display_logic" not in schemes["T4"]
        assert visible(schemes["T1"], {"T0": "Yes"})
        assert not visible(schemes["T1"], {"T0": "No"})
        assert not visible(schemes["T1"], {})
        assert visible(schemes["T2"], {"T0": "No"})
        assert not visible(schemes["T2"], {"T0": "Yes"})
        ok, errors = validate_display_logic_config(result.schemes)
        assert ok, errors

    def test_several_paths_and_cycles(self):
        res = ZooniverseImporter().parse_path(BRANCHING)
        assert res.items == []
        schemes = schemes_by_name(res)
        assert list(schemes) == ["T0", "T1", "T2", "T3", "T4"]
        t3 = schemes["T3"]  # reached by T0=A then T1=X, or by T0=B
        assert visible(t3, {"T0": "B"})
        assert visible(t3, {"T0": "A", "T1": "X"})
        assert not visible(t3, {"T0": "A", "T1": "Y"})
        assert not visible(t3, {"T0": "C"})
        # A stale answer to a question that is now hidden does not open T3.
        assert not visible(t3, {"T0": "C", "T1": "X"})
        t4 = schemes["T4"]  # every route except C ends at T4
        assert t4["display_logic"]["show_when"] == [
            {"schema": "T0", "operator": "equals", "value": ["A", "B"]}]
        assert visible(t4, {"T0": "A"}) and not visible(t4, {"T0": "C"})
        # T4 -> T1 loops back; T9 is never reached.
        assert res.skipped["branches that loop back (cycles)"] == 1
        assert res.skipped["tasks no path reaches (never shown)"] == 1
        ok, errors = validate_display_logic_config(res.schemes)
        assert ok, errors

    def test_dropdown(self):
        dropdown = schemes_by_name(ZooniverseImporter().parse_path(BRANCHING))["T2"]
        expected = "select" if "select" in SUPPORTED_TYPES else "radio"
        assert dropdown["annotation_type"] == expected
        assert dropdown["labels"] == ["Red", "Blue"]


# ----------------------------------------------------------------- answers

class TestResponses:
    def test_items_and_media(self, result):
        assert [i.instance_id for i in result.items] == ["1001", "1002", "1003"]
        first = item(result, "1001")
        assert first.fields["image"] == "https://example.org/subjects/a.jpg"
        assert first.fields["site"] == "north"
        assert "retired" not in first.fields
        # A subject nobody classified yet is still an item to annotate.
        assert item(result, "1003").responses == {}
        assert item(result, "1003").fields["locations"][1].endswith("c2.jpg")
        assert result.skipped["subjects linked only to other workflows"] == 1
        assert all(not i.predictions for i in result.items)

    def test_answer_shapes(self, result):
        answers = item(result, "1001").responses
        alice = answers["alice"]
        assert alice["T0"] == "Yes"
        assert alice["T3"] == "a lion"
        assert alice["T4"] == 7
        anon = next(name for name in answers if name.startswith("anon_"))
        assert answers[anon]["T0"] == "No"
        assert answers[anon]["T2"] == ["Grass", "Sky"]
        assert answers[anon]["T4"] == 2

    def test_reworded_label_of_an_earlier_minor_version(self, result):
        # bob answered under 4.1, when the option read "Yes!".
        bob = item(result, "1001").responses["bob"]
        assert bob["T0"] == "Yes"
        assert bob["T4"] == 6

    def test_marks_are_normalized(self, result):
        box, eye = item(result, "1001").responses["alice"]["T1"]
        # 800 x 600 image (subject_dimensions): box at (100,150) size 200 x 300.
        assert box["type"] == "bbox" and box["label"] == "Animal"
        assert box["coordinates"] == pytest.approx(
            {"x": 0.125, "y": 0.25, "width": 0.25, "height": 0.5})
        assert eye["type"] == "landmark" and eye["label"] == "Eye"
        assert eye["coordinates"] == pytest.approx({"x": 0.5, "y": 0.5})
        assert box["source"] == "import" and box["import_format"] == "zooniverse"
        bob_box = item(result, "1001").responses["bob"]["T1"][0]
        assert bob_box["coordinates"] == pytest.approx(
            {"x": 0.0, "y": 0.0, "width": 0.5, "height": 0.5})
        assert result.skipped["drawing detail answers"] == 1

    def test_marks_without_an_image_size_are_skipped(self, result):
        bob = item(result, "1002").responses["bob"]
        assert bob == {"T0": "Yes"}
        assert result.skipped["marks on subjects of unknown size"] == 1

    def test_versions_repeats_and_people(self, result):
        assert result.skipped["classifications from other workflow versions"] == 1
        assert all("carol" not in i.responses for i in result.items)
        # alice classified 1002 twice; the later one is kept.
        assert item(result, "1002").responses["alice"] == {"T0": "No", "T2": ["Sky"]}
        assert result.skipped[
            "repeat classifications of a subject by one person (latest kept)"] == 1
        # alice's survey answer was in the 1002 classification her later one
        # replaced, so it is not counted (audit 96 L7).
        assert result.skipped["answers to survey tasks"] == 0
        names = set(result.annotator_ids)
        assert {"alice", "bob"} < names and len(names) == 3
        assert any(name.startswith("anon_") for name in names)
        assert result.annotator_ids["alice"] == "alice (user id 11)"
        assert any("not logged in" in w for w in result.warnings)
        assert result.annotations_per_item == 3

    def test_classification_file_with_workflow_option(self, result):
        res = ZooniverseImporter().parse_path(
            CLASSIFICATIONS, {"workflow": str(WORKFLOWS)})
        assert len(res.items) == 3
        assert res.num_responses == result.num_responses == 15
        assert item(res, "1001").fields["image"].endswith("a.jpg")

    def test_choosing_an_older_version(self):
        res = ZooniverseImporter().parse_path(PROJECT, {"workflow_version": "3"})
        assert [s["name"] for s in res.schemes] == ["T0"]
        assert schemes_by_name(res)["T0"]["description"] == "Animal?"
        assert item(res, "1001").responses == {"carol": {"T0": "Yes"}}
        assert res.skipped["classifications from other workflow versions"] == 6

    def test_unknown_version_is_an_error(self):
        with pytest.raises(ValueError, match="no version 9"):
            ZooniverseImporter().parse_path(PROJECT, {"workflow_version": "9"})

    def test_highlighter_spans_in_code_points(self):
        res = ZooniverseImporter().parse_path(TEXT_PROJECT)
        scheme = res.schemes[0]
        assert scheme["annotation_type"] == "span"
        assert scheme["labels"] == ["Predator", "Prey"]
        assert res.text_key == "text"
        subject = res.items[0]
        spans = subject.responses["dana"]["T0"]
        text = subject.fields["text"]
        assert [(text[s["start"]:s["end"]], s["label"]) for s in spans] == [
            ("Cats", "Predator"), ("mice", "Prey")]


@pytest.mark.parametrize("tool, mark, expected", [
    # Front-end-monorepo rectangles are centred.
    (("bbox", "Box"), {"x_center": 400, "y_center": 300, "width": 200, "height": 100},
     {"x": 0.375, "y": 0.4166667, "width": 0.25, "height": 0.1666667}),
    # A box dragged up and left has a negative size.
    (("bbox", "Box"), {"x": 300, "y": 200, "width": -200, "height": -100},
     {"x": 0.125, "y": 0.1666667, "width": 0.25, "height": 0.1666667}),
    (("ellipse", "Circle"), {"x": 400, "y": 300, "r": 80},
     {"cx": 0.5, "cy": 0.5, "rx": 0.1, "ry": 0.1333333, "angle": 0.0}),
    # Zooniverse angles run counter-clockwise; Potato's clockwise.
    (("ellipse", "Blob"), {"x": 80, "y": 60, "rx": 40, "ry": 30, "angle": 30},
     {"cx": 0.1, "cy": 0.1, "rx": 0.05, "ry": 0.05, "angle": -30.0}),
    (("polyline", "Line"), {"x1": 0, "y1": 0, "x2": 800, "y2": 600},
     [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]),
    # A polygon that repeats its first point closes without the repeat.
    (("polygon", "Area"), {"points": [{"x": 0, "y": 0}, {"x": 800, "y": 0},
                                      {"x": 800, "y": 600}, {"x": 0, "y": 0}]},
     [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]),
    (("freeform", "Path"), {"pathX": [0, 400], "pathY": [0, 300]},
     [{"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 0.5}]),
])
def test_mark_geometry(tool, mark, expected):
    from collections import Counter
    from types import SimpleNamespace
    sink = SimpleNamespace(skipped=Counter(), warn=lambda m: None)
    obj = ZooniverseImporter._mark_object(tool, mark, (800.0, 600.0), sink)
    assert obj["type"] == tool[0] and obj["label"] == tool[1]
    if isinstance(expected, dict):
        assert obj["coordinates"] == pytest.approx(expected, abs=1e-6)
    else:
        assert [pytest.approx(p) for p in expected] == obj["coordinates"]


def test_clean_text():
    assert clean_text("![a.png](https://x/a.png =60x) **Smooth**") == "Smooth"
    assert clean_text("[Field guide](https://x) here") == "Field guide here"


# ----------------------------------------------------------------- writing

def _validate(config_path):
    config_path = str(config_path)
    with open(config_path) as handle:
        raw = yaml.safe_load(handle)
    normalize_config_before_validation(raw, os.path.dirname(config_path))
    return load_and_validate_config(config_path, os.path.dirname(config_path))


def test_written_project_validates_with_annotators(result):
    out = create_test_directory("zooniverse_import_project")
    write_project(result, out, str(PROJECT), keep_annotators=True)
    config_path = Path(out) / "config.yaml"
    _validate(config_path)
    config = yaml.safe_load(config_path.read_text())
    assert config["max_annotations_per_item"] == 3
    assert config["item_properties"]["text_key"] == "image"
    assert "pre_annotation" not in config
    by_name = {s["name"]: s for s in config["annotation_schemes"]}
    assert by_name["T1"]["display_logic"]["show_when"][0]["value"] == "Yes"

    rows = [json.loads(line) for line in
            (Path(out) / "data" / "project.jsonl").read_text().splitlines()]
    assert [r["id"] for r in rows] == ["1001", "1002", "1003"]

    state = json.loads((Path(out) / "annotation_output" / "alice" /
                        "user_state.json").read_text())
    entries = state["instance_id_to_label_to_value"]["1001"]
    stored = {(label["schema"], label["name"]): value for label, value in entries}
    assert stored[("T0", "Yes")] == "Yes"
    assert stored[("T3", "text_box")] == "a lion"
    assert stored[("T4", "slider")] == "7"
    boxes = json.loads(stored[("T1", "_data")])
    assert boxes[0]["coordinates"]["width"] == pytest.approx(0.25)
    anon = next(p for p in (Path(out) / "annotation_output").iterdir()
                if p.name.startswith("anon_"))
    assert (anon / "user_state.json").is_file()


def test_written_text_project_validates():
    res = ZooniverseImporter().parse_path(TEXT_PROJECT)
    out = create_test_directory("zooniverse_import_text")
    write_project(res, out, str(TEXT_PROJECT), keep_annotators=True)
    _validate(Path(out) / "config.yaml")
    state = json.loads((Path(out) / "annotation_output" / "dana" /
                        "user_state.json").read_text())
    spans = state["instance_id_to_span_to_value"]["5001"]
    assert [(s[0]["name"], s[0]["start"], s[0]["end"]) for s in spans] == [
        ("Predator", 0, 4), ("Prey", 13, 17)]


def test_workflow_only_project_validates():
    res = ZooniverseImporter().parse_path(BRANCHING)
    out = create_test_directory("zooniverse_import_workflow_only")
    write_project(res, out, str(BRANCHING), config_only=True)
    config = yaml.safe_load((Path(out) / "config.yaml").read_text())
    assert [s["name"] for s in config["annotation_schemes"]] == ["T0", "T1", "T2", "T3", "T4"]


def test_degenerate_and_out_of_image_marks():
    """Audit 96 L7: a box past the image edge imported with x < 0 and w > 1,
    and a two-point polygon imported at all."""
    from collections import Counter
    from types import SimpleNamespace
    sink = SimpleNamespace(skipped=Counter(), warn=lambda m: None)
    box = ZooniverseImporter._mark_object(("bbox", "Box"), {"x": -50, "y": 100, "width": 2000,
                                                            "height": 100}, (800.0, 600.0), sink)
    c = box["coordinates"]
    assert c["x"] == 0.0 and c["width"] == pytest.approx(1.0)
    assert sink.skipped["boxes clipped to the image edge"] == 1
    assert ZooniverseImporter._mark_object(("bbox", "Box"), {"x": 900, "y": 0, "width": 10,
                                                             "height": 10}, (800.0, 600.0), sink) is None
    assert ZooniverseImporter._mark_object(
        ("polygon", "Area"), {"points": [{"x": 0, "y": 0}, {"x": 5, "y": 5}]}, (800.0, 600.0), sink) is None
    assert sink.skipped["polygon shapes with too few points"] == 1


def test_saved_shapes_carry_their_tool_colour():
    """Audit 96 L7: the scheme had each tool's hex colour, the saved shapes had ""."""
    from collections import Counter
    from types import SimpleNamespace
    sink = SimpleNamespace(skipped=Counter(), warn=lambda m: None)
    task = {"type": "drawing", "tools": [
        {"type": "rectangle", "label": "Red", "color": "#f00"},
        {"type": "rectangle", "label": "Green", "color": "#0f0"},
        {"type": "point", "label": "Blue", "color": "#00f"}]}
    converter = ZooniverseImporter._drawing_scheme("T0", task, {"name": "T0"}, "T0", sink)
    marks = [{"tool": 0, "x": 10, "y": 10, "width": 20, "height": 20},
             {"tool": 1, "x": 50, "y": 50, "width": 20, "height": 20},
             {"tool": 2, "x": 5, "y": 5}]
    objects = ZooniverseImporter()._marks(converter, marks, [(800.0, 600.0)], sink)
    assert [o["color"] for o in objects] == ["#f00", "#0f0", "#00f"]
