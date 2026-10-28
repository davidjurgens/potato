"""
Unit tests for potato/agent_chat_store.py and the export of its transcripts.

A finished interactive_chat conversation is stored per (user, instance) in the
project database. It must never land on the shared item, must survive the
connection being reopened (a restart), and must reach the JSONL record and the
CSV/TSV agent_chat_turns sidecar.
"""

import csv
import json
import os

import pytest

from potato import agent_chat_store as store
from potato.persistence import clear_db_cache
from tests.helpers.test_utils import create_test_directory


PROJECT = "chat-project"


def _conv(text):
    return [
        {"speaker": "User", "text": text, "timestamp": 1.0},
        {"speaker": "Agent", "text": "reply to " + text, "timestamp": 2.0},
    ]


def _config(task_dir, with_chat=True):
    fields = [{"key": "task_description", "type": "text"}]
    if with_chat:
        fields.append({"key": "conv", "type": "interactive_chat"})
    return {
        "task_dir": task_dir,
        "annotation_task_name": PROJECT,
        "output_annotation_dir": os.path.join(task_dir, "output"),
        "annotation_schemes": [{"name": "ok", "annotation_type": "radio",
                                "labels": ["yes", "no"]}],
        "agent_proxy": {"type": "echo"},
        "instance_display": {"fields": fields},
    }


@pytest.fixture
def task_dir():
    d = os.path.abspath(create_test_directory("agent_chat_store_unit"))
    yield d
    clear_db_cache()


def _save(task_dir, user, inst, text, **kw):
    store.save_transcript(task_dir, project=PROJECT, user_id=user,
                          instance_id=inst, field_key="conv",
                          conversation=_conv(text), step_count=1,
                          started_at=0.5, proxy_type="echo", **kw)


class TestStore:

    def test_round_trip_is_per_user(self, task_dir):
        _save(task_dir, "alice", "i1", "alice text")
        _save(task_dir, "bob", "i1", "bob text")
        a = store.get_transcript(task_dir, PROJECT, "alice", "i1")
        b = store.get_transcript(task_dir, PROJECT, "bob", "i1")
        assert a["conversation"][0]["text"] == "alice text"
        assert b["conversation"][0]["text"] == "bob text"
        assert a["step_count"] == 1 and a["proxy_type"] == "echo"
        assert store.get_transcript(task_dir, PROJECT, "carol", "i1") is None
        assert store.get_transcript(task_dir, "other", "alice", "i1") is None

    def test_second_save_replaces(self, task_dir):
        _save(task_dir, "alice", "i1", "first")
        _save(task_dir, "alice", "i1", "second")
        rows = store.transcripts_for_project(task_dir, PROJECT)
        assert len(rows) == 1
        assert rows[0]["conversation"][0]["text"] == "second"

    def test_survives_reopening_the_database(self, task_dir):
        _save(task_dir, "alice", "i1", "durable text")
        clear_db_cache()
        got = store.get_transcript(task_dir, PROJECT, "alice", "i1")
        assert got["conversation"][0]["text"] == "durable text"
        assert os.path.isfile(os.path.join(task_dir, "project.sqlite"))

    def test_delete_for_user(self, task_dir):
        _save(task_dir, "alice", "i1", "a")
        _save(task_dir, "bob", "i1", "b")
        assert store.delete_for_user(task_dir, PROJECT, "alice") == 1
        assert store.get_transcript(task_dir, PROJECT, "alice", "i1") is None
        assert store.get_transcript(task_dir, PROJECT, "bob", "i1") is not None


class TestUserView:

    def test_overlay_is_per_user_and_leaves_item_untouched(self, task_dir):
        config = _config(task_dir)
        item = {"id": "i1", "task_description": "t", "conv": None}
        _save(task_dir, "alice", "i1", "alice text")

        alice_view = store.with_user_transcript(config, item, "alice", "i1")
        bob_view = store.with_user_transcript(config, item, "bob", "i1")

        assert alice_view["conv"][0]["text"] == "alice text"
        assert bob_view["conv"] is None
        assert item["conv"] is None, "the shared item was modified"

    def test_no_chat_field_returns_item_unchanged(self, task_dir):
        config = _config(task_dir, with_chat=False)
        item = {"id": "i1", "task_description": "t"}
        _save(task_dir, "alice", "i1", "alice text")
        assert store.with_user_transcript(config, item, "alice", "i1") is item
        assert store.transcripts_by_user_instance(config) == {}

    def test_chat_field_key(self):
        assert store.chat_field_key({}) is None
        assert store.chat_field_key({"instance_display": {"fields": [
            {"key": "c", "type": "interactive_chat"}]}}) == "c"


class TestExport:

    def _write_state(self, config, user, inst):
        user_dir = os.path.join(config["output_annotation_dir"], user)
        os.makedirs(user_dir, exist_ok=True)
        state = {
            "user_id": user,
            "instance_id_to_label_to_value": {
                inst: [[{"schema": "ok", "name": "yes"}, "true"]]},
            "instance_id_to_span_to_value": {},
        }
        with open(os.path.join(user_dir, "user_state.json"), "w") as f:
            json.dump(state, f)

    def _context(self, config):
        from potato.export.base import ExportContext
        from potato.export.cli import load_annotations_from_output_dir
        anns = load_annotations_from_output_dir(
            config["output_annotation_dir"], config["annotation_schemes"], config)
        return ExportContext(config=config, annotations=anns, items={},
                             schemas=config["annotation_schemes"],
                             output_dir=config["output_annotation_dir"])

    def test_jsonl_record_carries_own_transcript(self, task_dir):
        from potato.export.tabular_exporter import JSONLExporter
        config = _config(task_dir)
        self._write_state(config, "alice", "i1")
        self._write_state(config, "bob", "i1")
        _save(task_dir, "alice", "i1", "alice text")

        out = os.path.join(task_dir, "export_jsonl")
        result = JSONLExporter().export(self._context(config), out)
        assert result.success
        with open(os.path.join(out, "annotations.jsonl")) as f:
            records = {r["user_id"]: r for r in map(json.loads, f)}
        chat = records["alice"]["agent_chat"]
        assert chat["field"] == "conv"
        assert [t["text"] for t in chat["conversation"]] == [
            "alice text", "reply to alice text"]
        assert "agent_chat" not in records["bob"]

    def test_csv_writes_turns_sidecar(self, task_dir):
        from potato.export.tabular_exporter import CSVExporter
        config = _config(task_dir)
        self._write_state(config, "alice", "i1")
        _save(task_dir, "alice", "i1", "alice text")
        # A chat on an item the annotator never labelled is exported too.
        _save(task_dir, "alice", "i2", "unlabelled chat")

        out = os.path.join(task_dir, "export_csv")
        result = CSVExporter().export(self._context(config), out)
        sidecar = os.path.join(out, "agent_chat_turns.csv")
        assert sidecar in result.files_written
        with open(sidecar, newline="") as f:
            rows = list(csv.DictReader(f))
        assert [(r["instance_id"], r["turn_index"], r["speaker"], r["text"])
                for r in rows] == [
            ("i1", "0", "User", "alice text"),
            ("i1", "1", "Agent", "reply to alice text"),
            ("i2", "0", "User", "unlabelled chat"),
            ("i2", "1", "Agent", "reply to unlabelled chat"),
        ]
        # The main table is unchanged: no transcript column.
        with open(os.path.join(out, "annotations.csv"), newline="") as f:
            header = next(csv.reader(f))
        assert not any("agent_chat" in h for h in header)

    def test_no_sidecar_without_transcripts(self, task_dir):
        from potato.export.tabular_exporter import CSVExporter
        config = _config(task_dir)
        self._write_state(config, "alice", "i1")
        out = os.path.join(task_dir, "export_csv_empty")
        result = CSVExporter().export(self._context(config), out)
        assert not any(os.path.basename(p).startswith("agent_chat")
                       for p in result.files_written)
        assert result.files_written, "the main table should still be written"
