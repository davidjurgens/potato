"""
Paper Mode's data-quality precautions paragraph.

Reviewers and editors challenge data quality from online panels as a matter of
routine, and what settles it is a statement of the precautions actually taken
-- which checks ran, at what rate, with what exclusion rule, and how many
people it excluded. Potato computed alpha and kappa and said nothing about any
of that.

The rule these tests enforce is that the paragraph never overstates. A project
with no quality control must say so plainly rather than receive boilerplate
about precautions it did not take, because a methods section that claims a
check that never ran is worse than one that claims nothing.
"""

from __future__ import annotations

import pytest

from potato.paper import report
from potato.paper.collect import ProjectData, _training_outcome
from potato.paper.metrics import _quality_control


class PlainStyle(report.Style):
    """The Markdown style, used so assertions read against plain text."""


STYLE = report.Style()


def metrics_for(config, outcomes=None):
    project = ProjectData(
        config=config, config_path="config.yaml", task_name="t",
        schemes=[], skipped_schemes=[],
        training_outcomes=dict(outcomes or {}),
    )
    return {"quality_control": _quality_control(project)}


class TestConfigIsReadFromTheRightPlace:
    def test_attention_checks_are_a_top_level_key(self):
        """
        `attention_checks` and `gold_standards` are TOP-LEVEL; only the
        drawn-answer tolerance lives under `quality_control`. Reading them
        from the wrong place would report every project as having taken no
        precautions at all -- the most damaging thing this can get wrong.
        """
        m = metrics_for({"attention_checks": {"enabled": True, "frequency": 10}})
        assert m["quality_control"]["attention_checks"]["enabled"] is True

    def test_a_nested_block_is_not_mistaken_for_the_real_one(self):
        m = metrics_for({"quality_control": {"attention_checks":
                                             {"enabled": True}}})
        assert m["quality_control"]["attention_checks"]["enabled"] is False

    def test_the_failure_threshold_comes_from_failure_handling(self):
        m = metrics_for({"attention_checks": {
            "enabled": True, "failure_handling": {"block_threshold": 3}}})
        assert m["quality_control"]["attention_checks"]["block_threshold"] == 3

    def test_the_gold_threshold_comes_from_accuracy(self):
        m = metrics_for({"gold_standards": {
            "enabled": True, "accuracy": {"min_threshold": 0.8,
                                          "evaluation_count": 10}}})
        gold = m["quality_control"]["gold_standards"]
        assert gold["min_accuracy"] == pytest.approx(0.8)
        assert gold["evaluation_count"] == 10


class TestTheParagraph:
    def test_no_quality_control_says_so_rather_than_inventing_some(self):
        text = report.data_quality_paragraph(metrics_for({}), STYLE)
        assert "No attention checks" in text
        assert "gold" in text.lower()

    def test_attention_checks_are_described_with_their_rate(self):
        text = report.data_quality_paragraph(metrics_for({
            "attention_checks": {"enabled": True, "frequency": 15,
                                 "failure_handling": {"block_threshold": 3}}}),
            STYLE)
        assert "Attention checks" in text
        assert "15 items" in text
        assert "3 failures" in text

    def test_probability_is_used_when_there_is_no_frequency(self):
        text = report.data_quality_paragraph(metrics_for({
            "attention_checks": {"enabled": True, "probability": 0.1}}), STYLE)
        assert "probability 0.1" in text

    def test_gold_standards_are_described(self):
        text = report.data_quality_paragraph(metrics_for({
            "gold_standards": {"enabled": True, "frequency": 20,
                               "accuracy": {"min_threshold": 0.75,
                                            "evaluation_count": 8}}}), STYLE)
        assert "Gold-standard items" in text
        assert "every 20 items" in text
        assert "75%" in text

    def test_training_criteria_are_described(self):
        text = report.data_quality_paragraph(metrics_for({
            "training": {"enabled": True,
                         "passing_criteria": {"min_correct": 8,
                                              "max_mistakes": 3}}}), STYLE)
        assert "training phase" in text
        assert "8 correct" in text
        assert "3 mistakes" in text

    def test_overlap_is_reported_when_items_are_multiply_annotated(self):
        text = report.data_quality_paragraph(
            metrics_for({"num_annotators_per_item": 3}), STYLE)
        assert "3 annotators" in text

    def test_single_annotation_is_not_described_as_overlap(self):
        text = report.data_quality_paragraph(
            metrics_for({"num_annotators_per_item": 1}), STYLE)
        assert "independently annotated" not in text


class TestExclusionCounts:
    def test_pass_and_fail_counts_are_reported(self):
        text = report.data_quality_paragraph(metrics_for(
            {"training": {"enabled": True}},
            outcomes={"a": "passed", "b": "passed", "c": "failed"}), STYLE)
        assert "3 annotators who reached that gate" in text
        assert "2 passed" in text
        assert "1 was excluded" in text

    def test_no_one_reaching_the_gate_is_not_reported_as_zero_excluded(self):
        """
        "0 excluded" and "we have no record" are different claims, and a
        methods section must not make the stronger one by accident.
        """
        text = report.data_quality_paragraph(
            metrics_for({"training": {"enabled": True}}), STYLE)
        assert "excluded" not in text

    def test_plurals_agree(self):
        text = report.data_quality_paragraph(metrics_for(
            {"training": {"enabled": True}}, outcomes={"a": "failed"}), STYLE)
        assert "1 annotator who reached" in text
        assert "1 was excluded" in text


class TestTrainingOutcomeReader:
    def test_a_failed_state_reads_as_failed(self):
        assert _training_outcome({"training_state": {
            "failed": True, "passed": False,
            "completed_questions": {"q": {}}}}) == "failed"

    def test_a_passed_state_reads_as_passed(self):
        assert _training_outcome({"training_state": {
            "passed": True, "completed_questions": {"q": {}}}}) == "passed"

    def test_a_partly_done_state_is_in_progress(self):
        assert _training_outcome({"training_state": {
            "completed_questions": {"q": {}}}}) == "in_progress"

    def test_an_untouched_state_is_no_record_at_all(self):
        """
        A user who never reached the gate must not be counted as having been
        screened, or a project without training reports a fabricated
        exclusion denominator.
        """
        assert _training_outcome({"training_state": {
            "completed_questions": {}, "passed": False, "failed": False}}) is None
        assert _training_outcome({"training_state": {}}) is None
        assert _training_outcome({}) is None


class TestItReachesTheRenderedReport:
    def test_markdown_carries_a_data_quality_section(self):
        from potato.paper.markdown import render_markdown

        metrics = metrics_for({"attention_checks": {"enabled": True,
                                                    "frequency": 10}})
        metrics.update({
            "task_name": "t", "n_annotators": 1, "n_annotated_instances": 1,
            "n_total_items": 1, "n_label_records": 1,
            "mean_annotations_per_instance": 1.0,
            "instances_single_annotated": 0, "schemes": [],
            "skipped_schemes": [], "annotators": [],
            "timing": {"median_seconds_per_item": None,
                       "total_person_hours": None},
        })
        rendered = render_markdown(metrics)
        assert "## Data Quality" in rendered
        assert "Attention checks" in rendered
