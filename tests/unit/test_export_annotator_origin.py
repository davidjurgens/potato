"""Annotator origin reaches the files a researcher actually opens.

Every export record carried ``_origin``, but no exporter read it, so a csv of a
study with three pipelines and two curators had five rows per item and nothing
saying which were people. Pinned here:

* The per-annotator formats (csv, tsv, jsonl, parquet, HuggingFace, the
  publish bundle) gain ``annotator_origin`` beside ``user_id`` when any record
  is from a machine rater, and are unchanged when none is.
* An offline export labels a declared rater even when its state file was
  written before the server ever loaded it.
* Adjudication decisions record what each adopted answer's author was, and
  both adjudication csv writers carry it.
"""

from __future__ import annotations

import csv
import json
import os
from unittest.mock import patch

import pytest

from potato.export.base import ExportContext
from potato.export.origin_columns import ORIGIN_COLUMN, ORIGIN_DETAIL_COLUMN
from tests.helpers.test_utils import create_test_directory

TOOL = {"kind": "tool", "id": "pipeline_a", "tool": "pipeline_a",
        "version": "2.1.0", "database_version": "refdb-2024-03"}


def _ann(user_id, label, origin=None):
    record = {
        "instance_id": "i1",
        "user_id": user_id,
        "labels": {"function": {label: True}},
        "spans": {},
        "links": {},
    }
    if origin is not None:
        record["_origin"] = origin
    return record


def _context(annotations, output_dir):
    return ExportContext(
        config={}, annotations=annotations, items={"i1": {"text": "x"}},
        schemas=[{"name": "function", "annotation_type": "radio",
                  "labels": ["metabolism", "transport"]}],
        output_dir=output_dir,
    )


def _mixed():
    return [_ann("curator_1", "transport", {"kind": "human"}),
            _ann("pipeline_a", "metabolism", TOOL)]


def _people():
    return [_ann("curator_1", "transport", {"kind": "human"}),
            _ann("curator_2", "transport")]


@pytest.fixture
def out_dir():
    return create_test_directory("export_annotator_origin")


def _read_csv(path, delimiter=","):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=delimiter))


class TestTabular:
    @pytest.mark.parametrize("fmt,delim", [("csv", ","), ("tsv", "\t")])
    def test_machine_rows_are_labelled(self, out_dir, fmt, delim):
        from potato.export.registry import export_registry
        result = export_registry.export(fmt, _context(_mixed(), out_dir), out_dir)
        assert result.success, result.errors
        rows = _read_csv(os.path.join(out_dir, f"annotations.{fmt}"), delim)
        by_user = {r["user_id"]: r for r in rows}
        assert by_user["curator_1"][ORIGIN_COLUMN] == "human"
        assert by_user["curator_1"][ORIGIN_DETAIL_COLUMN] == ""
        assert by_user["pipeline_a"][ORIGIN_COLUMN] == "tool"
        detail = json.loads(by_user["pipeline_a"][ORIGIN_DETAIL_COLUMN])
        assert detail["version"] == "2.1.0"
        assert detail["database_version"] == "refdb-2024-03"

    def test_origin_sits_beside_user_id(self, out_dir):
        from potato.export.registry import export_registry
        export_registry.export("csv", _context(_mixed(), out_dir), out_dir)
        with open(os.path.join(out_dir, "annotations.csv"), encoding="utf-8") as f:
            header = next(csv.reader(f))
        assert header[:4] == ["instance_id", "user_id",
                              ORIGIN_COLUMN, ORIGIN_DETAIL_COLUMN]

    def test_an_all_human_export_is_unchanged(self, out_dir):
        from potato.export.registry import export_registry
        export_registry.export("csv", _context(_people(), out_dir), out_dir)
        with open(os.path.join(out_dir, "annotations.csv"), encoding="utf-8") as f:
            header = next(csv.reader(f))
        assert ORIGIN_COLUMN not in header
        assert ORIGIN_DETAIL_COLUMN not in header


class TestJsonl:
    def _records(self, out_dir, annotations):
        from potato.export.registry import export_registry
        export_registry.export("jsonl", _context(annotations, out_dir), out_dir)
        with open(os.path.join(out_dir, "annotations.jsonl"), encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def test_carries_the_whole_declaration(self, out_dir):
        records = {r["user_id"]: r for r in self._records(out_dir, _mixed())}
        assert records["pipeline_a"]["annotator_origin"] == TOOL
        assert records["curator_1"]["annotator_origin"] == {"kind": "human"}

    def test_an_all_human_export_is_unchanged(self, out_dir):
        for record in self._records(out_dir, _people()):
            assert "annotator_origin" not in record


class TestParquetAndHuggingFaceRows:
    """The row builders, which need neither pyarrow nor the Hub."""

    @pytest.fixture(params=["parquet", "huggingface"])
    def exporter(self, request):
        if request.param == "parquet":
            from potato.export.parquet_exporter import ParquetExporter
            return ParquetExporter()
        from potato.export.huggingface_exporter import HuggingFaceExporter
        return HuggingFaceExporter()

    def test_annotation_rows(self, exporter):
        rows = {r["user_id"]: r
                for r in exporter._build_annotation_rows(_mixed(), {})}
        assert rows["pipeline_a"][ORIGIN_COLUMN] == "tool"
        assert rows["curator_1"][ORIGIN_COLUMN] == "human"

    def test_all_human_rows_have_no_origin(self, exporter):
        for row in exporter._build_annotation_rows(_people(), {}):
            assert ORIGIN_COLUMN not in row

    def test_span_rows(self, exporter):
        anns = _mixed()
        anns[1]["spans"] = {"genes": [{"start": 0, "end": 1, "name": "cds",
                                       "text": "x"}]}
        rows = exporter._build_span_rows(anns)
        assert [r[ORIGIN_COLUMN] for r in rows] == ["tool"]


class TestPublishBundle:
    def test_rows_match_the_tabular_exporter(self):
        from potato.publish.bundle import build_annotation_rows
        rows = {r["user_id"]: r for r in build_annotation_rows(_mixed())}
        assert rows["pipeline_a"][ORIGIN_COLUMN] == "tool"
        assert all(ORIGIN_COLUMN not in r for r in build_annotation_rows(_people()))


class TestOfflineExportUsesTheDeclaration:
    """A state written by a script has no origin until the server loads it."""

    def _write_state(self, output_dir, user_id, origin=None):
        state = {"user_id": user_id, "instance_id_to_label_to_value": {
            "i1": [[{"schema": "function", "name": "metabolism"}, True]]}}
        if origin is not None:
            state["origin"] = origin
        os.makedirs(os.path.join(output_dir, user_id), exist_ok=True)
        with open(os.path.join(output_dir, user_id, "user_state.json"), "w") as f:
            json.dump(state, f)

    def _config(self):
        return {"machine_annotators": {"enabled": True, "annotators": [
            {"id": "pipeline_a", "kind": "tool", "version": "2.1.0"}]}}

    def test_a_declared_rater_without_a_stamp_is_a_machine(self, out_dir):
        from potato.export.cli import load_annotations_from_output_dir
        self._write_state(out_dir, "pipeline_a")
        self._write_state(out_dir, "curator_1")
        records = {r["user_id"]: r for r in
                   load_annotations_from_output_dir(out_dir, [], self._config())}
        origin = records["pipeline_a"]["_origin"]
        assert origin["kind"] == "tool" and origin["version"] == "2.1.0"
        # The export time is not when the rater was recorded.
        assert "recorded_at" not in origin
        assert records["curator_1"]["_origin"] == {"kind": "human"}

    def test_the_stored_origin_wins(self, out_dir):
        from potato.export.cli import load_annotations_from_output_dir
        stored = dict(TOOL, version="1.0.0")
        self._write_state(out_dir, "pipeline_a", stored)
        records = load_annotations_from_output_dir(out_dir, [], self._config())
        assert records[0]["_origin"]["version"] == "1.0.0"

    def test_no_config_means_no_declaration(self, out_dir):
        from potato.export.cli import load_annotations_from_output_dir
        self._write_state(out_dir, "pipeline_a")
        records = load_annotations_from_output_dir(out_dir, [])
        assert records[0]["_origin"] == {"kind": "human"}


# ---------------------------------------------------------------------------
# Adjudication
# ---------------------------------------------------------------------------

class _State:
    def __init__(self, origin=None):
        self.instance_id_to_label_to_value = {}
        self.instance_id_to_span_to_value = {}
        self.instance_id_to_behavioral_data = {}
        if origin is not None:
            self.origin = origin


class _USM:
    def __init__(self, states):
        self.states = states

    def get_user_state(self, uid):
        return self.states.get(uid)


def _decision(source):
    from potato.adjudication import AdjudicationDecision
    return AdjudicationDecision(
        instance_id="i1", adjudicator_id="lead", timestamp="2026-09-23T00:00:00",
        label_decisions={s: "metabolism" for s in source}, span_decisions=[],
        source=source, confidence="high", notes="", error_taxonomy=[])


def _manager(out_dir, machines=True):
    from potato.adjudication import AdjudicationManager
    declared = {"machine_annotators": {"enabled": True, "annotators": [
        {"id": "pipeline_a", "kind": "tool"}]}} if machines else {}
    return AdjudicationManager({
        **declared,
        "adjudication": {"enabled": True, "adjudicator_users": ["lead"]},
        "annotation_schemes": [{"name": "function", "annotation_type": "radio",
                                "labels": ["metabolism", "transport"]},
                               {"name": "confidence", "annotation_type": "radio",
                                "labels": ["low", "high"]}],
        "output_annotation_dir": out_dir,
        "item_properties": {"id_key": "id", "text_key": "text"},
    })


class TestDecisionRecordsAdoptedOrigin:
    def _submit(self, out_dir, source, states, answers=None, value="metabolism"):
        from potato.adjudication import AdjudicationItem
        with patch("potato.user_state_management.get_user_state_manager",
                   return_value=_USM(states)):
            mgr = _manager(out_dir)
            if answers is not None:
                mgr.queue["i1"] = AdjudicationItem(
                    instance_id="i1", annotations=answers, span_annotations={},
                    behavioral_data={}, agreement_scores={},
                    overall_agreement=0.5, num_annotators=len(answers))
            decision = _decision(source)
            decision.label_decisions = {s: value for s in source}
            mgr.submit_decision(decision)
            return decision

    def test_adopted_machine_and_person_are_recorded(self, out_dir):
        decision = self._submit(
            out_dir, {"function": "pipeline_a", "confidence": "curator_1"},
            {"pipeline_a": _State(TOOL), "curator_1": _State()})
        assert decision.source_origins == {
            "function": "pipeline_a 2.1.0 db refdb-2024-03 (tool)",
            "confidence": "human",
        }

    def test_the_adjudicators_own_answer_has_no_entry(self, out_dir):
        decision = self._submit(out_dir, {"function": "adjudicator"},
                                {"pipeline_a": _State(TOOL)})
        assert decision.source_origins == {}

    def test_a_picked_value_names_everyone_who_gave_it(self, out_dir):
        """The radio form records "adjudicator" even when the chosen label is
        exactly what two tools answered; the origins say so."""
        pipeline_b = dict(TOOL, id="pipeline_b", version="1.8.2")
        decision = self._submit(
            out_dir, {"function": "adjudicator"},
            {"pipeline_a": _State(TOOL), "pipeline_b": _State(pipeline_b),
             "curator_1": _State()},
            answers={"pipeline_a": {"function": {"transport": True}},
                     "pipeline_b": {"function": {"transport": True}},
                     "curator_1": {"function": {"hypothetical": True}}},
            value="transport")
        assert decision.source_origins == {"function": (
            "pipeline_a 2.1.0 db refdb-2024-03 (tool); "
            "pipeline_b 1.8.2 db refdb-2024-03 (tool)")}

    def test_a_person_and_a_tool_agreeing_are_both_named(self, out_dir):
        decision = self._submit(
            out_dir, {"function": "adjudicator"},
            {"pipeline_a": _State(TOOL), "curator_1": _State()},
            answers={"pipeline_a": {"function": {"transport": True}},
                     "curator_1": {"function": {"transport": True}}},
            value="transport")
        assert decision.source_origins["function"] == (
            "human; pipeline_a 2.1.0 db refdb-2024-03 (tool)")

    def test_a_value_nobody_gave_has_no_entry(self, out_dir):
        decision = self._submit(
            out_dir, {"function": "adjudicator"}, {"pipeline_a": _State(TOOL)},
            answers={"pipeline_a": {"function": {"transport": True}}},
            value="metabolism")
        assert decision.source_origins == {}

    def test_an_all_human_study_records_nothing(self, out_dir):
        with patch("potato.user_state_management.get_user_state_manager",
                   return_value=_USM({"curator_1": _State()})):
            mgr = _manager(out_dir, machines=False)
            decision = _decision({"function": "curator_1"})
            mgr.submit_decision(decision)
        assert decision.source_origins == {}

    def test_an_unknown_author_is_not_guessed_human(self, out_dir):
        decision = self._submit(out_dir, {"function": "deleted_user"}, {})
        assert decision.source_origins == {}

    def test_it_is_persisted(self, out_dir):
        self._submit(out_dir, {"function": "pipeline_a"},
                     {"pipeline_a": _State(TOOL)})
        with open(os.path.join(out_dir, "adjudication", "decisions.json")) as f:
            payload = json.load(f)
        decisions = payload["decisions"] if isinstance(payload, dict) else payload
        assert decisions[0]["source_origins"]["function"].endswith("(tool)")


class TestAdjudicatedCsv:
    def _write_decisions(self, out_dir, decisions):
        os.makedirs(os.path.join(out_dir, "adjudication"), exist_ok=True)
        with open(os.path.join(out_dir, "adjudication", "decisions.json"), "w") as f:
            json.dump({"decisions": decisions}, f)

    def _export(self, out_dir):
        from potato.export.registry import export_registry
        dest = os.path.join(out_dir, "export")
        ctx = _context([], out_dir)
        ctx.config = {"adjudication": {"enabled": True}}
        result = export_registry.export("adjudication", ctx, dest)
        assert result.success, result.errors
        return _read_csv(os.path.join(dest, "adjudicated.csv"))

    def test_source_origin_column(self, out_dir):
        d = _decision({"function": "pipeline_a"}).to_dict()
        d["source_origins"] = {"function": "pipeline_a 2.1.0 (tool)"}
        self._write_decisions(out_dir, [d])
        rows = self._export(out_dir)
        assert rows[0]["source"] == "pipeline_a"
        assert rows[0]["source_origin"] == "pipeline_a 2.1.0 (tool)"

    def test_decisions_without_origins_keep_the_old_columns(self, out_dir):
        self._write_decisions(out_dir, [_decision({"function": "curator_1"}).to_dict()])
        rows = self._export(out_dir)
        assert "source_origin" not in rows[0]
