"""
Loading item data for export.

``ExportContext.items`` carries the original data every exporter needs to make
sense of an annotation — which utterance a span falls in, which image a box was
drawn on, what the underlying text said. When it comes back empty, exporters do
not fail loudly; they emit a well-formed file with nothing useful in it.

That is exactly what used to happen for a data file written as a JSON array.
``load_instance_data`` accepts both a JSON array and JSON Lines, and Potato's own
tooling writes arrays (``potato transcripts`` defaults to one), but the export
loader read line by line only — so a pretty-printed array parsed as zero items.
"""

import json
import os

import pytest

from potato.export.cli import load_items_from_data_files


def write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def config_for(filename):
    return {
        "data_files": [filename],
        "item_properties": {"id_key": "id"},
        "task_dir": ".",
    }


ITEMS = [
    {"id": "a", "text": "first", "conversation": [{"turn_id": "t1", "text": "hi"}]},
    {"id": "b", "text": "second"},
]


class TestJsonLines:
    def test_reads_json_lines(self, tmp_path):
        write(tmp_path, "d.jsonl", "\n".join(json.dumps(i) for i in ITEMS))
        items = load_items_from_data_files(config_for("d.jsonl"), str(tmp_path))
        assert set(items) == {"a", "b"}

    def test_blank_lines_are_skipped(self, tmp_path):
        write(tmp_path, "d.jsonl", json.dumps(ITEMS[0]) + "\n\n" + json.dumps(ITEMS[1]))
        assert len(load_items_from_data_files(config_for("d.jsonl"), str(tmp_path))) == 2

    def test_nested_structure_survives(self, tmp_path):
        write(tmp_path, "d.jsonl", json.dumps(ITEMS[0]))
        items = load_items_from_data_files(config_for("d.jsonl"), str(tmp_path))
        assert items["a"]["conversation"][0]["turn_id"] == "t1"


class TestJsonArray:
    """Regression: an array used to load as zero items."""

    def test_compact_array(self, tmp_path):
        write(tmp_path, "d.json", json.dumps(ITEMS))
        items = load_items_from_data_files(config_for("d.json"), str(tmp_path))
        assert set(items) == {"a", "b"}

    def test_pretty_printed_array(self, tmp_path):
        write(tmp_path, "d.json", json.dumps(ITEMS, indent=2))
        items = load_items_from_data_files(config_for("d.json"), str(tmp_path))
        assert set(items) == {"a", "b"}
        assert items["a"]["text"] == "first"

    def test_single_object(self, tmp_path):
        write(tmp_path, "d.json", json.dumps(ITEMS[0], indent=1))
        items = load_items_from_data_files(config_for("d.json"), str(tmp_path))
        assert set(items) == {"a"}

    def test_empty_array(self, tmp_path):
        write(tmp_path, "d.json", "[]")
        assert load_items_from_data_files(config_for("d.json"), str(tmp_path)) == {}


class TestRobustness:
    def test_missing_file_is_not_fatal(self, tmp_path):
        assert load_items_from_data_files(config_for("nope.json"), str(tmp_path)) == {}

    def test_non_json_lines_are_skipped(self, tmp_path):
        write(tmp_path, "d.jsonl", json.dumps(ITEMS[0]) + "\nid,text\na,b\n")
        items = load_items_from_data_files(config_for("d.jsonl"), str(tmp_path))
        assert set(items) == {"a"}

    def test_custom_id_key(self, tmp_path):
        write(tmp_path, "d.jsonl", json.dumps({"uid": "z", "text": "t"}))
        config = config_for("d.jsonl")
        config["item_properties"]["id_key"] = "uid"
        assert set(load_items_from_data_files(config, str(tmp_path))) == {"z"}

    def test_scalar_json_file_yields_nothing(self, tmp_path):
        """A bare number is valid JSON but not item data."""
        write(tmp_path, "d.json", "42")
        assert load_items_from_data_files(config_for("d.json"), str(tmp_path)) == {}


class TestConvoKitProvenanceSurvives:
    """The ConvoKit exporter depends entirely on this reaching it."""

    @pytest.mark.parametrize("dumper", [
        lambda items: "\n".join(json.dumps(i) for i in items),
        lambda items: json.dumps(items, indent=1),
    ])
    def test_provenance_block_round_trips(self, tmp_path, dumper):
        items = [{
            "id": "convo:c0",
            "conversation": [{"turn_id": "c0", "text": "hi"}],
            "_convokit": {"corpus": "test", "conversation_id": "c0",
                          "utterance_ids": ["c0"]},
        }]
        write(tmp_path, "d.json", dumper(items))
        loaded = load_items_from_data_files(config_for("d.json"), str(tmp_path))
        assert loaded["convo:c0"]["_convokit"]["conversation_id"] == "c0"
