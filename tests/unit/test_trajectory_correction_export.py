"""
Unit tests for the trajectory_correction exporter (SFT/DPO output).
"""

import json
import os
import tempfile

import pytest

from potato.export.registry import export_registry
from potato.export.base import ExportContext
from potato.export.trajectory_correction_exporter import TrajectoryCorrectionExporter


SCHEME = {
    "annotation_type": "trajectory_edit",
    "name": "fix",
    "steps_key": "steps",
    "step_text_key": "action",
    "final_answer_key": "final_answer",
}


def _correction(steps, final_answer=None):
    n_edited = sum(1 for s in steps if s.get("edited"))
    if final_answer and final_answer.get("edited"):
        n_edited += 1
    return json.dumps({
        "steps": steps, "final_answer": final_answer,
        "n_steps_edited": n_edited,
        "total_edit_distance": sum(s.get("edit_distance_chars", 0) for s in steps),
    })


def _ctx(annotations, items):
    return ExportContext(
        config={}, annotations=annotations, items=items,
        schemas=[SCHEME], output_dir="/tmp",
    )


def _run(ctx):
    out = tempfile.mkdtemp()
    res = export_registry.export("trajectory_correction", ctx, out)
    return res, out


def _read_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


class TestRegistration:
    def test_registered(self):
        assert export_registry.is_registered("trajectory_correction")


class TestCanExport:
    def test_false_without_annotations(self):
        ok, msg = TrajectoryCorrectionExporter().can_export(
            ExportContext(config={}, annotations=[], items={}, schemas=[SCHEME], output_dir="/tmp")
        )
        assert not ok

    def test_false_without_trajedit_schema(self):
        ok, msg = TrajectoryCorrectionExporter().can_export(
            ExportContext(config={}, annotations=[{"instance_id": "a"}], items={},
                          schemas=[{"annotation_type": "radio", "name": "r"}], output_dir="/tmp")
        )
        assert not ok


class TestReconstruction:
    def test_applies_edit_and_preserves_unedited(self):
        steps = [
            {"step_index": 0, "field": "action", "original_text": "f(queyr=1)",
             "edited_text": "f(query=1)", "edited": True, "edit_distance_chars": 2},
            {"step_index": 1, "field": "action", "original_text": "g()",
             "edited_text": "g()", "edited": False, "edit_distance_chars": 0},
        ]
        ctx = _ctx(
            [{"instance_id": "t1", "user_id": "u1",
              "labels": {"fix": {"label": _correction(steps)}}}],
            {"t1": {"task_description": "task", "steps": [{"action": "f(queyr=1)"}, {"action": "g()"}]}},
        )
        res, out = _run(ctx)
        assert res.success
        corr = json.load(open(os.path.join(out, "trajectory_corrections.json")))
        rec = corr["records"][0]
        assert rec["corrected_trace"]["steps"][0]["action"] == "f(query=1)"
        assert rec["corrected_trace"]["steps"][1]["action"] == "g()"
        assert rec["original_trace"]["steps"][0]["action"] == "f(queyr=1)"
        assert rec["n_edits"] == 1

    def test_final_answer_edit_applied(self):
        steps = [{"step_index": 0, "field": "action", "original_text": "a",
                  "edited_text": "a", "edited": False}]
        fa = {"original_text": "Bad.", "edited_text": "Good and complete.",
              "edited": True, "edit_distance_chars": 10}
        ctx = _ctx(
            [{"instance_id": "t1", "user_id": "u1",
              "labels": {"fix": {"label": _correction(steps, fa)}}}],
            {"t1": {"task_description": "task", "steps": [{"action": "a"}], "final_answer": "Bad."}},
        )
        res, out = _run(ctx)
        rec = json.load(open(os.path.join(out, "trajectory_corrections.json")))["records"][0]
        assert rec["corrected_trace"]["final_answer"] == "Good and complete."
        assert rec["original_trace"]["final_answer"] == "Bad."
        assert rec["n_edits"] == 1

    def test_string_step_edit(self):
        # Steps stored as bare strings; editing step_text_key replaces the string.
        steps = [{"step_index": 0, "field": "action", "original_text": "old",
                  "edited_text": "new", "edited": True, "edit_distance_chars": 3}]
        ctx = _ctx(
            [{"instance_id": "t1", "user_id": "u1",
              "labels": {"fix": {"label": _correction(steps)}}}],
            {"t1": {"task_description": "task", "steps": ["old"]}},
        )
        res, out = _run(ctx)
        rec = json.load(open(os.path.join(out, "trajectory_corrections.json")))["records"][0]
        assert rec["corrected_trace"]["steps"][0] == "new"


class TestSFTandDPO:
    def _two_traces(self):
        edited = [{"step_index": 0, "field": "action", "original_text": "f(queyr=1)",
                   "edited_text": "f(query=1)", "edited": True, "edit_distance_chars": 2}]
        unedited = [{"step_index": 0, "field": "action", "original_text": "h()",
                     "edited_text": "h()", "edited": False, "edit_distance_chars": 0}]
        return _ctx(
            [
                {"instance_id": "t1", "user_id": "u1", "labels": {"fix": {"label": _correction(edited)}}},
                {"instance_id": "t2", "user_id": "u1", "labels": {"fix": {"label": _correction(unedited)}}},
            ],
            {
                "t1": {"task_description": "fix me", "steps": [{"action": "f(queyr=1)"}]},
                "t2": {"task_description": "leave me", "steps": [{"action": "h()"}]},
            },
        )

    def test_only_edited_traces_in_sft_and_dpo(self):
        res, out = _run(self._two_traces())
        sft = _read_jsonl(os.path.join(out, "trajectory_sft.jsonl"))
        dpo = _read_jsonl(os.path.join(out, "trajectory_dpo.jsonl"))
        assert len(sft) == 1 and sft[0]["trace_id"] == "t1"
        assert len(dpo) == 1 and dpo[0]["trace_id"] == "t1"
        assert res.stats["edited_traces"] == 1
        assert res.stats["unedited_traces"] == 1

    def test_unedited_warning_emitted(self):
        res, _ = _run(self._two_traces())
        assert any("no edits" in w for w in res.warnings)

    def test_dpo_chosen_differs_from_rejected(self):
        res, out = _run(self._two_traces())
        dpo = _read_jsonl(os.path.join(out, "trajectory_dpo.jsonl"))[0]
        assert dpo["chosen"] != dpo["rejected"]
        assert dpo["chosen"]["steps"][0]["action"] == "f(query=1)"
        assert dpo["rejected"]["steps"][0]["action"] == "f(queyr=1)"

    def test_sft_completion_is_corrected(self):
        res, out = _run(self._two_traces())
        sft = _read_jsonl(os.path.join(out, "trajectory_sft.jsonl"))[0]
        assert sft["completion"]["steps"][0]["action"] == "f(query=1)"
        assert sft["prompt"] == "fix me"


class TestMultiAnnotator:
    def test_one_record_per_annotator(self):
        edited = lambda et: [{"step_index": 0, "field": "action", "original_text": "f(0)",
                              "edited_text": et, "edited": True, "edit_distance_chars": 1}]
        ctx = _ctx(
            [
                {"instance_id": "t1", "user_id": "u1", "labels": {"fix": {"label": _correction(edited("f(1)"))}}},
                {"instance_id": "t1", "user_id": "u2", "labels": {"fix": {"label": _correction(edited("f(2)"))}}},
            ],
            {"t1": {"task_description": "t", "steps": [{"action": "f(0)"}]}},
        )
        res, out = _run(ctx)
        dpo = _read_jsonl(os.path.join(out, "trajectory_dpo.jsonl"))
        assert len(dpo) == 2
        chosen = sorted(r["chosen"]["steps"][0]["action"] for r in dpo)
        assert chosen == ["f(1)", "f(2)"]


class TestRobustness:
    def test_unparseable_label_counted_not_fatal(self):
        ctx = _ctx(
            [{"instance_id": "t1", "user_id": "u1", "labels": {"fix": {"label": "{not json"}}}],
            {"t1": {"task_description": "t", "steps": [{"action": "a"}]}},
        )
        res, _ = _run(ctx)
        assert res.success
        assert res.stats["unparseable"] == 1
