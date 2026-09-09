"""Attention checks: the record survives the next click, and the check reads
the payload the client actually sends.

Three defects from audit round 36, all measured against a live server before
they were reproduced here.

1. `validate_attention_response` keeps one result per (user, item) and kept the
   LAST one -- while the annotation page saves twice for one answer, on
   selection and again on Next. So the second save, carrying the seconds spent
   looking at an answer already given, rewrote every `min_response_time`
   violation as a pass. Measured: answered correctly 3.9s after render against
   a minimum of 8, stored `too_fast: true`; eleven seconds later a Next that
   changed nothing rewrote the same record to `passed: true, 40.9s`. The
   violation survived only as a log line, so the key could not reach the file
   anyone analyses.

2. The comparison read the annotation's VALUE. `/updateinstance` takes two
   shapes for one selection: `{"sarcasm:Sarcastic": "Sarcastic"}` from the
   annotation page, where the label is in both halves, and
   `{"sarcasm:Sarcastic": "on"}` from anything posting what the form element
   holds -- which is what Potato's own simulator sends. A correct answer in the
   second shape failed, so a simulated annotator failed every check regardless
   of its answer and a QC config could not be validated with the simulator.

3. `attention_checks.failure_handling` accepted keys it does not read.
   `action: warn` is the natural guess, appears nowhere in the docs, and was
   taken in silence: thresholds stayed at their defaults and the author
   concluded the feature did nothing.
"""

import json
import os

import pytest

from potato.quality_control import QualityControlManager
from tests.helpers.test_utils import create_test_directory


CHECK_ID = "attn_001"


def make_manager(name, min_response_time=0.0, items=None):
    task_dir = create_test_directory(f"audit36_{name}")
    items_path = os.path.join(task_dir, "checks.json")
    with open(items_path, "w", encoding="utf-8") as fh:
        json.dump(items or [{
            "id": CHECK_ID,
            "text": "Select Sarcastic to show you are reading.",
            "expected_answer": {"sarcasm": "Sarcastic"},
        }], fh)

    config = {
        "output_annotation_dir": os.path.join(task_dir, "out"),
        "annotation_schemes": [
            {"annotation_type": "radio", "name": "sarcasm",
             "labels": ["Sarcastic", "Sincere"]},
        ],
        "attention_checks": {
            "enabled": True,
            "items_file": items_path,
            "frequency": 3,
            "min_response_time": min_response_time,
        },
    }
    manager = QualityControlManager(config, task_dir)
    assert manager.attention_expected.get(CHECK_ID), (
        "fixture did not load the check")
    return manager


def only_result(manager, user="ann"):
    results = manager.attention_results[user]
    assert len(results) == 1, [r.item_id for r in results]
    return results[0]


# ----------------------------------------------------------------------
# 1. A re-save may correct the answer; it may not launder the timing
# ----------------------------------------------------------------------

class TestARepeatSaveDoesNotEraseTheViolation:

    def test_the_next_click_does_not_rewrite_a_too_fast_check(self):
        """The measured sequence: 3.9s against a minimum of 8, then a second
        save at 40.9s that changed nothing."""
        manager = make_manager("relaunder", min_response_time=8.0)
        answer = {"sarcasm": "Sarcastic"}

        manager.validate_attention_response("ann", CHECK_ID, answer, 3.913)
        first = only_result(manager)
        assert first.too_fast is True and first.passed is False

        manager.validate_attention_response("ann", CHECK_ID, answer, 40.941)
        after = only_result(manager)
        assert after.too_fast is True, (
            "the second save cleared too_fast; the annotation page sends it "
            "for every answer, so this erases the key in the ordinary flow")
        assert after.passed is False
        assert after.response_time_seconds == pytest.approx(3.913), (
            f"kept {after.response_time_seconds}s; min_response_time is about "
            "the fastest reading, not the last one")

    def test_a_re_save_can_still_correct_a_wrong_answer(self):
        """Stickiness applies to the timing, not to the answer. An annotator
        who changes their mind before moving on has answered correctly."""
        manager = make_manager("correct")
        manager.validate_attention_response(
            "ann", CHECK_ID, {"sarcasm": "Sincere"}, 12.0)
        assert only_result(manager).passed is False

        manager.validate_attention_response(
            "ann", CHECK_ID, {"sarcasm": "Sarcastic"}, 14.0)
        assert only_result(manager).passed is True

    def test_a_correct_answer_after_a_too_fast_one_still_fails(self):
        """Both halves at once: the answer is fixed, the timing is not."""
        manager = make_manager("both", min_response_time=8.0)
        manager.validate_attention_response(
            "ann", CHECK_ID, {"sarcasm": "Sincere"}, 1.0)
        manager.validate_attention_response(
            "ann", CHECK_ID, {"sarcasm": "Sarcastic"}, 30.0)

        result = only_result(manager)
        assert result.passed is False and result.too_fast is True

    def test_one_item_still_counts_once(self):
        """The merge must not turn re-saves into extra failures, which is what
        appending would do to the block threshold."""
        manager = make_manager("once")
        for _ in range(4):
            manager.validate_attention_response(
                "ann", CHECK_ID, {"sarcasm": "Sincere"}, 12.0)
        assert len(manager.attention_results["ann"]) == 1


# ----------------------------------------------------------------------
# 2. Both payload shapes are the same answer
# ----------------------------------------------------------------------

class TestBothPayloadShapesAreRead:

    @pytest.mark.parametrize("payload,label", [
        ({"sarcasm": "Sarcastic"}, "bare schema key"),
        ({"sarcasm:Sarcastic": "Sarcastic"}, "annotation page"),
        ({"sarcasm:Sarcastic": "on"}, "form value / simulator"),
        ({"sarcasm:Sarcastic": "true"}, "rooms, before it was aligned"),
    ])
    def test_a_correct_answer_passes_in_every_shape(self, payload, label):
        manager = make_manager("shapes_" + label.split()[0])
        result = manager.validate_attention_response(
            "ann", CHECK_ID, payload, 12.0)
        assert result["passed"] is True, (
            f"a correct answer sent as the {label} shape failed: {payload}")

    @pytest.mark.parametrize("payload", [
        {"sarcasm": "Sincere"},
        {"sarcasm:Sincere": "Sincere"},
        {"sarcasm:Sincere": "on"},
    ])
    def test_a_wrong_answer_still_fails_in_every_shape(self, payload):
        """The permissive reading must not pass everything. If it did, the
        simulator would go from failing every check to passing every check,
        which is the same amount of information."""
        manager = make_manager("wrong")
        result = manager.validate_attention_response(
            "ann", CHECK_ID, payload, 12.0)
        assert result["passed"] is False, payload

    def test_an_unticked_option_is_not_an_answer(self):
        """`off`/empty means the annotator did not choose it. Reading the key
        alone would score an untouched form as correct."""
        manager = make_manager("unticked")
        result = manager.validate_attention_response(
            "ann", CHECK_ID, {"sarcasm:Sarcastic": "off"}, 12.0)
        assert result["passed"] is False

    def test_a_multiselect_check_reads_the_ticked_labels(self):
        """Multiselect posts one key per option. Reading a single value meant
        the expected list was compared against one element."""
        manager = make_manager("multi", items=[{
            "id": CHECK_ID,
            "text": "Tick both.",
            "expected_answer": {"topics": ["sports", "politics"]},
        }])
        result = manager.validate_attention_response(
            "ann", CHECK_ID,
            {"topics:sports": "on", "topics:politics": "on"}, 12.0)
        assert result["passed"] is True

    def test_a_partial_multiselect_answer_fails(self):
        manager = make_manager("multi_partial", items=[{
            "id": CHECK_ID,
            "text": "Tick both.",
            "expected_answer": {"topics": ["sports", "politics"]},
        }])
        result = manager.validate_attention_response(
            "ann", CHECK_ID, {"topics:sports": "on"}, 12.0)
        assert result["passed"] is False

    def test_a_free_text_answer_is_still_read_from_the_value(self):
        """Where the answer really is in the value, the value still wins."""
        manager = make_manager("text", items=[{
            "id": CHECK_ID,
            "text": "Type banana.",
            "expected_answer": {"word": "banana"},
        }])
        assert manager.validate_attention_response(
            "ann", CHECK_ID, {"word:text_box": "banana"}, 12.0)["passed"] is True
        manager2 = make_manager("text_wrong", items=[{
            "id": CHECK_ID, "text": "Type banana.",
            "expected_answer": {"word": "banana"},
        }])
        assert manager2.validate_attention_response(
            "ann", CHECK_ID, {"word:text_box": "apple"}, 12.0)["passed"] is False


# ----------------------------------------------------------------------
# 3. An invented failure_handling key is not accepted in silence
# ----------------------------------------------------------------------

def _validate(name, attention_block):
    import yaml
    from potato.validate_cli import validate_config_file

    task_dir = create_test_directory(f"audit36_cfg_{name}")
    data_path = os.path.join(task_dir, "items.json")
    with open(data_path, "w", encoding="utf-8") as fh:
        json.dump([{"id": "s1", "text": "well that went great"}], fh)
    checks_path = os.path.join(task_dir, "checks.json")
    with open(checks_path, "w", encoding="utf-8") as fh:
        json.dump([{"id": CHECK_ID, "text": "Pick Sarcastic.",
                    "expected_answer": {"sarcasm": "Sarcastic"}}], fh)

    block = dict(attention_block)
    block.setdefault("enabled", True)
    block.setdefault("items_file", checks_path)
    block.setdefault("frequency", 3)

    config = {
        "port": 8000, "annotation_task_name": "audit36",
        "task_dir": task_dir, "data_files": [data_path],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "output_annotation_dir": os.path.join(task_dir, "out"),
        "annotation_schemes": [
            {"annotation_type": "radio", "name": "sarcasm",
             "description": "Sarcasm?", "labels": ["Sarcastic", "Sincere"]}],
        "attention_checks": block,
    }
    path = os.path.join(task_dir, "cfg.yaml")
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(config, fh)
    report = validate_config_file(path)
    assert report.ok, report.errors
    return report


def _failure_warnings(report):
    return [w for w in report.other_warnings if "failure_handling" in w]


def test_an_invented_failure_handling_key_is_reported():
    report = _validate("invented", {"failure_handling": {"action": "warn"}})
    warnings = _failure_warnings(report)
    assert warnings, (
        "`action: warn` was accepted in silence; it configures nothing and "
        f"the thresholds stay at their defaults. warnings={report.other_warnings}")
    assert "action" in warnings[0]
    assert "warn_threshold" in warnings[0], (
        "the warning must name what the block does accept")


def test_the_documented_keys_are_quiet():
    report = _validate("documented", {"failure_handling": {
        "warn_threshold": 2,
        "warn_message": "Please read items carefully before answering.",
        "block_threshold": 5,
        "block_message": "You have been blocked.",
    }})
    assert not _failure_warnings(report), report.other_warnings
