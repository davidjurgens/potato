"""Gold standards grade the answer, and say what the configuration will do.

Five defects, all measured on live servers by the audit before they were
reproduced here.

The one that matters most is the separator. ``/updateinstance`` refuses a
payload whose keys name no label with a message that asks for
``schema:::label``; quality control split on the FIRST colon, so a caller who
complied had their answer read as the label ``"::Sincere"``. Two annotators on
one server, both correct, both storing byte-identical annotations, scored 3/3
and 0/3 -- with nothing in the log.

The rest:

* ``mode: training`` loads the items, logs the same two lines as a working
  config, passes ``validate --strict``, and serves nothing.
* ``accuracy.min_threshold`` was evaluated inside ``if show_feedback``, so an
  accuracy threshold on a silent study -- the mode gold standards are
  recommended for -- evaluated nothing at all.
* Nothing rendered gold feedback: ``handleQualityControlResponse`` had no
  branch for ``type: "gold_standard"``.
* ``auto_promote`` grouped by wire key, so two annotators giving OPPOSITE
  answers agreed on the ``"stance": "on"`` half and the item was promoted as
  unanimous with a consensus label asserting both answers.
"""

import json
import os
import subprocess
import tempfile

import pytest

from potato.quality_control import QualityControlManager


GOLD = [
    {"id": "g1", "text": "sure, great", "gold_label": {"stance": "Sarcastic"}},
    {"id": "g2", "text": "i liked it", "gold_label": {"stance": "Sincere"}},
]


def make_manager(tmp_path, **gold_overrides):
    gold_file = os.path.join(tmp_path, "gold.json")
    with open(gold_file, "w", encoding="utf-8") as fh:
        json.dump(GOLD, fh)
    gold_config = {"enabled": True, "items_file": gold_file,
                   "mode": "mixed", "frequency": 2}
    gold_config.update(gold_overrides)
    return QualityControlManager({"gold_standards": gold_config}, tmp_path)


@pytest.fixture
def tmp_task_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


# ----------------------------------------------------------------------
# 1. The separator the route's own refusal message asks for
# ----------------------------------------------------------------------

class TestBothSeparatorsGradeTheSame:
    """The two payloads carry the same answer, so they must earn the same grade.

    Stated as behaviour rather than as a claim about how the key is split: the
    point is not that a particular function partitions on ``:::``, it is that
    an annotator is not marked wrong for the separator they used.
    """

    @pytest.mark.parametrize("key", ["stance:Sarcastic", "stance:::Sarcastic"])
    def test_a_correct_answer_is_correct(self, tmp_task_dir, key):
        qc = make_manager(tmp_task_dir)
        result = qc.validate_gold_response("hank", "g1", {"stance": "on", key: "on"})
        assert result is not None, "g1 is a gold item and was not graded"
        assert qc.get_gold_accuracy("hank")["correct"] == 1, (
            f"a correct answer posted as {key!r} was graded wrong; the route "
            "accepts both separators and its 400 message asks for the long one")

    @pytest.mark.parametrize("key", ["stance:Sincere", "stance:::Sincere"])
    def test_a_wrong_answer_is_still_wrong(self, tmp_task_dir, key):
        """The fix must not turn the grader into something that passes anything."""
        qc = make_manager(tmp_task_dir)
        qc.validate_gold_response("iris", "g1", {"stance": "on", key: "on"})
        assert qc.get_gold_accuracy("iris")["correct"] == 0

    def test_the_two_separators_produce_the_same_accuracy(self, tmp_task_dir):
        qc = make_manager(tmp_task_dir)
        for item_id, label in (("g1", "Sarcastic"), ("g2", "Sincere")):
            qc.validate_gold_response(
                "hank", item_id, {"stance": "on", f"stance:{label}": "on"})
            qc.validate_gold_response(
                "iris", item_id, {"stance": "on", f"stance:::{label}": "on"})
        assert (qc.get_gold_accuracy("hank")["accuracy"]
                == qc.get_gold_accuracy("iris")["accuracy"] == 1.0)

    def test_the_route_still_asks_for_a_separator_it_can_read(self, tmp_task_dir):
        """The 400 message and the grader must not name different shapes.

        Whatever the refusal message tells a caller to send has to be a shape
        that scores correctly, which is the whole content of this finding.
        """
        import re

        from potato import routes

        # Read the message the route actually emits, with adjacent string
        # literals joined the way Python joins them, so the test tracks the
        # sentence rather than its line breaks.
        source = open(routes.__file__, encoding="utf-8").read()
        joined = re.sub(r'"\s*\n\s*(?:f?")', "", source)
        message = re.search(r"every key must name[^\"]*?'([a-z]+:+[a-z]+)'",
                            joined)
        assert message, "the /updateinstance refusal message moved or changed"
        template = message.group(1)          # e.g. "schema:::label"
        separator = template.replace("schema", "").replace("label", "")
        assert set(separator) == {":"}, template

        qc = make_manager(tmp_task_dir)
        qc.validate_gold_response(
            "quoted", "g1", {"stance": "on", f"stance{separator}Sarcastic": "on"})
        assert qc.get_gold_accuracy("quoted")["correct"] == 1, (
            f"a caller following the route's own message ({template!r}) is "
            "graded wrong")


class TestAttentionChecksUseTheSameReading:
    """Attention checks are graded by the same comparator, so they inherit the
    fix -- and would inherit a regression."""

    def test_both_separators_pass_an_attention_check(self, tmp_task_dir):
        attn_file = os.path.join(tmp_task_dir, "attn.json")
        with open(attn_file, "w", encoding="utf-8") as fh:
            json.dump([{"id": "a1", "text": "pick Sincere",
                        "expected_answer": {"stance": "Sincere"}}], fh)
        qc = QualityControlManager(
            {"attention_checks": {"enabled": True, "items_file": attn_file,
                                  "frequency": 2}}, tmp_task_dir)
        long_form = qc.validate_attention_response(
            "u1", "a1", {"stance": "on", "stance:::Sincere": "on"}, 30.0)
        assert long_form["passed"] is True


# ----------------------------------------------------------------------
# 2. A mode that serves nothing says so
# ----------------------------------------------------------------------

class TestTrainingModeIsNotSilent:

    def test_training_mode_still_serves_nothing(self, tmp_task_dir):
        """Pinned, because the warning below is only honest while this holds."""
        qc = make_manager(tmp_task_dir, mode="training")
        qc.user_items_since_gold["u1"] = 99
        assert qc.should_inject_gold_standard("u1") is False

    def test_the_working_modes_still_serve(self, tmp_task_dir):
        for mode in ("mixed", "separate"):
            qc = make_manager(tmp_task_dir, mode=mode)
            qc.user_items_since_gold["u1"] = 99
            assert qc.should_inject_gold_standard("u1") is True, mode

    def test_boot_warns_that_training_mode_serves_nothing(self, tmp_task_dir, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="potato.quality_control"):
            make_manager(tmp_task_dir, mode="training")
        warnings = [r.getMessage() for r in caplog.records
                    if r.levelno >= logging.WARNING]
        assert any("training" in w and "NONE will be served" in w
                   for w in warnings), (
            "a config that loads gold items and serves none boots with the "
            f"same lines as one that works: {warnings}")

    def test_a_working_mode_does_not_warn(self, tmp_task_dir, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="potato.quality_control"):
            make_manager(tmp_task_dir, mode="mixed")
        assert not [r for r in caplog.records
                    if r.levelno >= logging.WARNING
                    and "NONE will be served" in r.getMessage()]

    def test_validate_flags_training_mode(self, tmp_task_dir, caplog):
        import logging

        from potato.server_utils import config_module

        gold_file = os.path.join(tmp_task_dir, "gold.json")
        with open(gold_file, "w", encoding="utf-8") as fh:
            json.dump(GOLD, fh)
        with caplog.at_level(logging.WARNING):
            config_module.validate_quality_control_config({
                "gold_standards": {"enabled": True, "items_file": gold_file,
                                   "mode": "training"}})
        assert any("serves no gold items" in r.getMessage()
                   for r in caplog.records), (
            "`validate --strict` passed a config that measures nothing")


# ----------------------------------------------------------------------
# 3. The accuracy threshold is a measurement, not a message
# ----------------------------------------------------------------------

class TestAccuracyThresholdOnASilentStudy:

    def _fail_three(self, qc, user="slip"):
        for item_id in ("g1", "g2", "g1"):
            qc.validate_gold_response(
                user, item_id, {"stance": "on", "stance:Wrong": "on"})

    def test_a_silent_study_still_evaluates_the_threshold(self, tmp_task_dir):
        qc = make_manager(tmp_task_dir,
                          accuracy={"min_threshold": 0.9, "evaluation_count": 2})
        self._fail_three(qc)
        assert "slip" in qc.users_below_accuracy_threshold(), (
            "an accuracy threshold on a study with feedback off evaluated "
            "nothing, so nothing could act on it")

    def test_the_annotator_is_still_told_nothing(self, tmp_task_dir):
        """Silence towards the ANNOTATOR is the documented default and stays."""
        qc = make_manager(tmp_task_dir,
                          accuracy={"min_threshold": 0.9, "evaluation_count": 2})
        self._fail_three(qc)
        last = qc.validate_gold_response(
            "slip", "g2", {"stance": "on", "stance:Wrong": "on"})
        assert last == {"recorded": True, "silent": True}

    def test_an_accurate_annotator_is_not_flagged(self, tmp_task_dir):
        qc = make_manager(tmp_task_dir,
                          accuracy={"min_threshold": 0.9, "evaluation_count": 2})
        for item_id, label in (("g1", "Sarcastic"), ("g2", "Sincere"),
                               ("g1", "Sarcastic")):
            qc.validate_gold_response(
                "good", item_id, {"stance": "on", f"stance:{label}": "on"})
        assert qc.users_below_accuracy_threshold() == []

    def test_the_threshold_reaches_the_admin_metrics(self, tmp_task_dir):
        qc = make_manager(tmp_task_dir,
                          accuracy={"min_threshold": 0.9, "evaluation_count": 2})
        self._fail_three(qc)
        metrics = qc.get_quality_metrics()
        assert "slip" in metrics["gold_standards"]["below_accuracy_threshold"]

    def test_feedback_on_still_warns_the_annotator(self, tmp_task_dir):
        qc = make_manager(tmp_task_dir,
                          accuracy={"min_threshold": 0.9, "evaluation_count": 2},
                          feedback={"show_correct_answer": True})
        self._fail_three(qc)
        result = qc.validate_gold_response(
            "slip", "g2", {"stance": "on", "stance:Wrong": "on"})
        assert result.get("accuracy_warning") is True
        assert result.get("required_accuracy") == 0.9


# ----------------------------------------------------------------------
# 4. Something renders the feedback
# ----------------------------------------------------------------------

class TestTheClientRendersGoldFeedback:
    """A response body nobody reads is not feedback.

    Driven through the real function in node rather than asserted against the
    source text, so a rename cannot pass it and a broken render cannot.
    """

    HARNESS = r"""
    const fs = require('fs');
    const shown = [];
    global.showNotification = (msg, type) => shown.push({msg, type});
    global.showError = () => {};
    const src = fs.readFileSync(process.argv[2], 'utf8');
    const start = src.indexOf('function handleQualityControlResponse');
    const end = src.indexOf('function showNotification');
    eval(src.slice(start, end));
    handleQualityControlResponse(JSON.parse(process.argv[3]));
    console.log(JSON.stringify(shown));
    """

    def _run(self, payload):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(self.HARNESS)
            harness = fh.name
        try:
            out = subprocess.run(
                ["node", harness, "potato/static/annotation.js",
                 json.dumps(payload)],
                capture_output=True, text=True, timeout=30)
            assert out.returncode == 0, out.stderr
            return json.loads(out.stdout)
        finally:
            os.unlink(harness)

    def test_a_wrong_answer_shows_the_expected_label(self):
        shown = self._run({"qc_result": {
            "type": "gold_standard", "correct": False, "recorded": True,
            "gold_label": {"stance": "Sarcastic"}}})
        assert shown, "the annotator was shown nothing at all"
        text = " ".join(s["msg"] for s in shown)
        assert "Sarcastic" in text, (
            f"the correct answer was in the response body and not on the "
            f"page: {shown}")

    def test_a_correct_answer_says_so(self):
        shown = self._run({"qc_result": {
            "type": "gold_standard", "correct": True, "recorded": True}})
        assert shown and shown[0]["type"] == "success"

    def test_an_explanation_is_rendered(self):
        shown = self._run({"qc_result": {
            "type": "gold_standard", "correct": False, "recorded": True,
            "explanation": "The praise is undercut by the next clause."}})
        assert "undercut" in " ".join(s["msg"] for s in shown)

    def test_a_silent_result_shows_nothing(self):
        """Silent is the default and must stay silent on the page."""
        shown = self._run({"qc_result": {
            "type": "gold_standard", "recorded": True, "silent": True}})
        assert shown == []

    def test_the_accuracy_warning_reaches_the_annotator(self):
        shown = self._run({"qc_result": {
            "type": "gold_standard", "correct": False, "recorded": True,
            "accuracy_warning": True, "current_accuracy": 0.0,
            "required_accuracy": 0.9}})
        text = " ".join(s["msg"] for s in shown)
        assert "90%" in text and "0%" in text, shown

    def test_blocking_still_wins(self):
        """The pre-existing branches must not be displaced by the new one."""
        shown = self._run({"status": "blocked", "message": "You have been blocked.",
                           "qc_result": {"type": "attention_check",
                                         "blocked": True}})
        assert shown and shown[0]["type"] == "error"


# ----------------------------------------------------------------------
# 5. Auto-promotion
# ----------------------------------------------------------------------

def promoting_manager(tmp_path, **overrides):
    auto = {"enabled": True, "min_annotators": 2, "agreement_threshold": 1.0}
    auto.update(overrides)
    return make_manager(tmp_path, auto_promote=auto)


class TestPromotionRequiresRealAgreement:

    def test_two_opposite_answers_do_not_promote(self, tmp_task_dir):
        qc = promoting_manager(tmp_task_dir)
        qc.record_item_annotation("r1", "a", {"stance:Sincere": "on"})
        second = qc.record_item_annotation("r1", "b", {"stance:Sarcastic": "on"})
        assert second is None, (
            "two annotators who answered OPPOSITELY promoted the item as "
            "unanimous; every later annotator was then graded against a gold "
            "label asserting both answers")
        assert qc.is_gold_standard("r1") is False

    def test_agreement_still_promotes(self, tmp_task_dir):
        qc = promoting_manager(tmp_task_dir)
        qc.record_item_annotation("r1", "a", {"stance:Sincere": "on"})
        second = qc.record_item_annotation("r1", "b", {"stance:Sincere": "on"})
        assert second and second["promoted"] is True

    def test_agreement_across_the_two_separators_promotes(self, tmp_task_dir):
        qc = promoting_manager(tmp_task_dir)
        qc.record_item_annotation("r1", "a", {"stance:Sincere": "on"})
        second = qc.record_item_annotation("r1", "b", {"stance:::Sincere": "on"})
        assert second and second["promoted"] is True, (
            "the same answer posted with the two accepted separators read as "
            "two different answers")

    def test_the_consensus_label_is_a_label(self, tmp_task_dir):
        qc = promoting_manager(tmp_task_dir)
        qc.record_item_annotation("r1", "a", {"stance:Sincere": "on"})
        result = qc.record_item_annotation("r1", "b", {"stance:Sincere": "on"})
        assert result["consensus_label"] == {"stance": "Sincere"}, (
            "the raw wire payload was persisted as the consensus label, so a "
            "researcher reviewing promoted gold read a DOM marker")

    def test_a_schema_only_one_annotator_answered_does_not_promote(self, tmp_task_dir):
        qc = promoting_manager(tmp_task_dir)
        qc.record_item_annotation("r1", "a", {"stance:Sincere": "on",
                                              "tone:Warm": "on"})
        second = qc.record_item_annotation("r1", "b", {"stance:Sincere": "on"})
        assert second is None, (
            "a schema one annotator answered is unopposed, not unanimous")


class TestPromotedGoldIsReportedHonestly:

    def _promote(self, qc, item_id):
        qc.record_item_annotation(item_id, "a", {"stance:Sincere": "on"})
        qc.record_item_annotation(item_id, "b", {"stance:Sincere": "on"})

    def test_the_total_matches_the_breakdown(self, tmp_task_dir):
        qc = promoting_manager(tmp_task_dir)
        for item_id in ("r1", "r2", "r3"):
            self._promote(qc, item_id)
        gold = qc.get_quality_metrics()["gold_standards"]
        assert gold["total_items"] == len(GOLD) + 3
        assert gold["configured_items"] == len(GOLD)
        assert gold["promoted_items"] == 3

    def test_a_promoted_item_is_not_a_configured_one(self, tmp_task_dir):
        qc = promoting_manager(tmp_task_dir)
        self._promote(qc, "r1")
        assert qc.is_gold_standard("r1") is True
        assert qc.is_configured_gold_standard("r1") is False, (
            "a promoted item is served as ordinary work, so it must still "
            "count towards the spacing of the checks that ARE injected"
        )
        assert qc.is_configured_gold_standard("g1") is True

    def test_the_comparable_denominator_is_reported(self, tmp_task_dir):
        """Promotion makes the headline denominator depend on arrival order.

        The configured pool is the same for everyone, so it is reported too.
        """
        qc = promoting_manager(tmp_task_dir)
        self._promote(qc, "r1")
        qc.validate_gold_response("late", "g1",
                                  {"stance": "on", "stance:Sarcastic": "on"})
        qc.validate_gold_response("late", "r1",
                                  {"stance": "on", "stance:Sincere": "on"})
        by_user = qc.get_quality_metrics()["gold_standards"]["by_user"]["late"]
        assert by_user["total"] == 2
        assert by_user["configured_total"] == 1
        assert by_user["configured_accuracy"] == 1.0
