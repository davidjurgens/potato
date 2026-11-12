"""
Argilla dataset import, from to_disk folders and to_hub snapshots.

Fixtures are in tests/data/importers/argilla (see the README there).
"""

import json
from pathlib import Path

import pytest

from potato.importers.projects import detect
from potato.importers.projects.argilla import ArgillaImporter

FIX = Path(__file__).resolve().parents[1] / "data" / "importers" / "argilla"
U1, U2 = "argilla_1f3a9c2e", "argilla_7b8d1e4f"


@pytest.fixture(scope="module")
def disk():
    return ArgillaImporter().parse_path(FIX / "to_disk")


@pytest.fixture(scope="module")
def hub():
    pytest.importorskip("datasets")
    return ArgillaImporter().parse_path(FIX / "to_hub")


def scheme(result, name):
    return next(s for s in result.schemes if s["name"] == name)


class TestQuestions:
    def test_question_types_map(self, disk):
        types = {s["name"]: s["annotation_type"] for s in disk.schemes}
        assert types == {"helpful": "radio", "issues": "multiselect", "score": "likert",
                         "fix": "text", "entities": "span"}

    def test_ranking_is_reported_and_left_out(self, disk):
        assert "rank" not in {s["name"] for s in disk.schemes}
        assert disk.skipped["ranking questions"] == 1
        assert disk.skipped["answers to questions left out"] == 1

    def test_required_and_guidelines_carry(self, disk):
        assert scheme(disk, "helpful")["label_requirement"] == {"required": True}
        assert disk.guidelines.startswith("Rate whether")

    def test_two_text_fields_are_both_shown_and_the_span_field_is_the_target(self, disk):
        fields = disk.instance_display["fields"]
        assert [f["key"] for f in fields] == ["prompt", "response"]
        assert next(f for f in fields if f["key"] == "response")["span_target"] is True
        assert disk.text_key == "response"

    def test_a_zero_based_rating_becomes_radio(self, tmp_path):
        settings = json.loads((FIX / "to_disk" / ".argilla" / "settings.json").read_text())
        settings["questions"] = [{"name": "r", "title": "R", "settings": {
            "type": "rating", "options": [{"value": v} for v in range(0, 11)]}}]
        (tmp_path / ".argilla").mkdir()
        (tmp_path / ".argilla" / "settings.json").write_text(json.dumps(settings))
        (tmp_path / "records.json").write_text(json.dumps([
            {"id": "x", "fields": {"prompt": "p", "response": "q"},
             "responses": {"r": [{"value": 0, "user_id": "u"}]}}]))
        result = ArgillaImporter().parse_path(tmp_path)
        r = scheme(result, "r")
        assert r["annotation_type"] == "radio" and r["labels"][0] == "0"
        assert result.items[0].responses["argilla_u"]["r"] == "0"


class TestToDisk:
    def test_every_response_is_imported_and_the_status_gap_is_said(self, disk):
        r1 = disk.items[0]
        assert r1.responses[U1]["helpful"] == "yes"
        assert r1.responses[U2]["helpful"] == "no"
        assert r1.responses[U1]["score"] == 4
        assert r1.responses[U2]["issues"] == ["vague"]
        assert any("records.json does not record" in w for w in disk.warnings)

    def test_span_responses(self, disk):
        spans = disk.items[0].responses[U1]["entities"]
        text = disk.items[0].fields["response"]
        assert [text[s["start"]:s["end"]] for s in spans] == ["Ada Lovelace", "Babbage"]

    def test_suggestions_become_predictions_with_their_agent(self, disk):
        r1 = disk.items[0]
        assert r1.predictions == {"helpful": "yes"}
        assert r1.prediction_sources["helpful"] == {"model": "gpt-judge", "score": 0.7}

    def test_metadata_is_kept(self, disk):
        assert disk.items[0].fields["metadata"] == {"source": "wiki"}


class TestToHub:
    def test_only_submitted_responses_are_imported(self, hub):
        r1, r2 = hub.items
        assert r1.responses[U1]["helpful"] == "yes"
        assert U2 not in r1.responses                    # discarded
        assert "helpful" not in r2.responses.get(U1, {})  # draft
        assert hub.skipped["discarded responses"] == 1
        assert hub.skipped["draft responses"] == 1

    def test_flattened_suggestions(self, hub):
        assert hub.items[0].prediction_sources["helpful"] == {"model": "gpt-judge", "score": 0.7}
        assert "helpful" not in hub.items[1].predictions

    def test_flattened_columns_are_not_item_fields(self, hub):
        assert set(hub.items[0].fields) == {"prompt", "response"}


class TestDetection:
    def test_both_layouts_are_detected(self):
        assert detect(str(FIX / "to_disk")) == "argilla"
        assert detect(str(FIX / "to_hub")) == "argilla"

    def test_a_plain_folder_is_not(self, tmp_path):
        assert detect(str(tmp_path)) is None
