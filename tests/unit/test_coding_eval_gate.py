"""`coding_eval` refuses a study it cannot export, instead of succeeding at nothing.

Two things combined to produce "Export successful!" over an empty directory.

`can_export` admitted the study on this line:

    relevant = schema_types & {"process_reward", "code_review", "pairwise", "radio"}

`radio` is the most generic scheme type Potato has. Nearly every study declares
one, so nearly every study cleared the gate. And `export` then returned
`success=True` unconditionally, with `files_written`, `warnings` and `stats` all
still empty:

    Export successful!
    Files written:
    $ ls -la /tmp/ce
    total 0

Twenty-two of the thirty-one formats already refuse cleanly on a study that
lacks what they need, naming the missing thing. This makes coding_eval the
twenty-third.

A radio scheme does reach this exporter, but only through `_export_swebench`
and only when its labels are the outcome vocabulary that reads, so that is what
the gate checks rather than the type.
"""

import json
import tempfile

import pytest

from potato.export.base import ExportContext
from potato.export.coding_eval_exporter import CodingEvalExporter


def context(schemes, labels=None):
    annotation = {"instance_id": "i1", "user": "u1",
                  "labels": labels or {"q": {"label": "good"}},
                  "spans": {}, "links": {}}
    return ExportContext(config={}, annotations=[annotation],
                         items={"i1": {"id": "i1"}}, schemas=schemes,
                         output_dir="")


def radio(*labels, name="q"):
    return {"annotation_type": "radio", "name": name, "labels": list(labels)}


class TestTheGate:

    def test_a_plain_radio_study_is_refused(self):
        allowed, why = CodingEvalExporter().can_export(
            context([radio("good", "bad")]))
        assert allowed is False, (
            "the most generic scheme type in Potato admitted nearly every "
            "study to an exporter that then wrote nothing")
        assert "process_reward" in why and "SWE-bench" in why

    @pytest.mark.parametrize("annotation_type",
                             ["process_reward", "code_review", "pairwise"])
    def test_the_real_coding_schemes_are_admitted(self, annotation_type):
        allowed, _ = CodingEvalExporter().can_export(
            context([{"annotation_type": annotation_type, "name": "s"}]))
        assert allowed is True

    def test_a_radio_scheme_of_swebench_outcomes_is_admitted(self):
        allowed, _ = CodingEvalExporter().can_export(
            context([radio("resolved", "unresolved")]))
        assert allowed is True, (
            "this is the one radio shape the exporter actually reads")

    def test_a_dict_spelled_label_is_read_by_name(self):
        allowed, _ = CodingEvalExporter().can_export(
            context([{"annotation_type": "radio", "name": "q",
                      "labels": [{"name": "success"}, {"name": "failure"}]}]))
        assert allowed is True

    def test_an_unrelated_study_is_refused(self):
        allowed, _ = CodingEvalExporter().can_export(
            context([{"annotation_type": "text", "name": "t"}]))
        assert allowed is False

    def test_no_annotations_is_still_refused_first(self):
        empty = ExportContext(config={}, annotations=[], items={},
                              schemas=[radio("resolved")], output_dir="")
        allowed, why = CodingEvalExporter().can_export(empty)
        assert allowed is False and "annotation" in why.lower()


class TestWritingNothingIsNotSuccess:

    def _export(self, ctx):
        with tempfile.TemporaryDirectory() as out:
            return CodingEvalExporter().export(ctx, out)

    def test_zero_files_is_a_failure(self):
        """A study that clears the gate can still hold none of the four
        shapes; that is not a successful export."""
        result = self._export(context([radio("resolved", "unresolved")],
                                      labels={"q": {"label": "good"}}))
        assert result.files_written == []
        assert result.success is False, (
            'the run printed "Export successful!" with nothing under '
            '"Files written:" and exited 0')

    def test_the_failure_says_what_it_looked_for(self):
        result = self._export(context([radio("resolved", "unresolved")],
                                      labels={"q": {"label": "good"}}))
        joined = " ".join(result.errors)
        assert "process_reward" in joined and "pairwise" in joined
        assert "resolved" in joined, "the SWE-bench vocabulary is not named"

    def test_a_real_export_still_succeeds(self):
        """The refusal must not swallow the working case."""
        result = self._export(context(
            [radio("resolved", "unresolved", name="task_success")],
            labels={"task_success": {"label": "resolved"}}))
        assert result.success is True
        assert any(p.endswith("swebench_results.jsonl")
                   for p in result.files_written)
        assert result.errors == []
