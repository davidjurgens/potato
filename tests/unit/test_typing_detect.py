"""
Unit tests for potato.typing_detect.

Two things are being protected here, and the second matters more than the first:

1. Each flag fires on its own behavioural signature.
2. Each flag stays SILENT on the innocent behaviours that superficially
   resemble it — quoting the passage under annotation, typing on a phone, using
   an IME, writing a two-word answer. Every false positive in this feature is a
   researcher accusing an annotator of something they did not do, so the
   suppression tests are the load-bearing ones.
"""

import pytest

from potato.typing_detect import (
    DEFAULT_THRESHOLDS,
    MAX_CALIBRATION_DRIFT,
    MIN_CHARS_FOR_RHYTHM_FLAGS,
    Flag,
    Verdict,
    calibrate,
    evaluate,
)
from potato.typing_dynamics import TypingEvent, summarize

from tests.unit.test_typing_dynamics import (
    natural_trace,
    paste_trace,
    transcription_trace,
)


def mobile_trace(n=200, seed=5):
    """Soft keyboard: text arrives with no keydown, so key_class is unknown."""
    import random
    rng = random.Random(seed)
    ev, t, pos = [], 0, 0
    for i in range(n):
        t += int(rng.lognormvariate(5.3, 0.6))
        ev.append(TypingEvent(t, "insertText", "unknown", pos, 1))
        pos += 1
    return ev


def automated_trace(n=200):
    """Scripted entry: uniform 20ms, and the browser says isTrusted=false."""
    return [TypingEvent(i * 20, "insertText", "letter", i, 1, {"is_trusted": False})
            for i in range(n)]


class TestFlagsFireOnTheirSignature:
    def test_external_paste_fires_three_flags(self):
        v = evaluate(summarize(paste_trace(source="external"), final_chars=292))
        assert set(v.flag_names) == {
            "paste_dominant", "silent_insertion", "offscreen_composition"}
        assert v.level == "suspect"

    def test_transcription_fires_rhythm_flag(self):
        v = evaluate(summarize(transcription_trace()))
        assert "transcription_rhythm" in v.flag_names
        assert v.level == "review"

    def test_automation_fires_synthetic_input(self):
        v = evaluate(summarize(automated_trace()))
        assert "synthetic_input" in v.flag_names
        assert v.level == "suspect"

    def test_implausible_speed_fires_on_superhuman_typing(self):
        events = [TypingEvent(i * 20, "insertText", "letter", i, 1) for i in range(600)]
        v = evaluate(summarize(events))
        assert "implausible_speed" in v.flag_names

    def test_every_flag_carries_its_evidence(self):
        v = evaluate(summarize(paste_trace(), final_chars=292))
        for flag in v.flags:
            assert flag.evidence, f"{flag.name} fired with no evidence"
            assert flag.explanation
            assert flag.severity in ("review", "suspect")


class TestFalsePositiveSuppression:
    """The tests that keep this feature ethically usable."""

    def test_natural_composition_is_clean(self):
        v = evaluate(summarize(natural_trace()))
        assert v.flag_names == []
        assert v.level == "ok"

    @pytest.mark.parametrize("source", ["self", "instance_text"])
    def test_quoting_the_passage_is_not_flagged(self, source):
        """Pasting the passage you are annotating, or moving your own draft
        around, must not read as importing text from off-screen."""
        v = evaluate(summarize(paste_trace(source=source), final_chars=292))
        assert v.flag_names == []
        assert v.level == "ok"
        assert "paste_dominant" in v.suppressed
        assert v.notes

    def test_time_away_then_quoting_the_passage_is_not_flagged(self):
        v = evaluate(summarize(paste_trace(source="instance_text", blur_ms=60000),
                               final_chars=292))
        assert "offscreen_composition" not in v.flag_names
        assert "offscreen_composition" in v.suppressed

    def test_unknown_paste_source_fails_toward_flagging(self):
        """When source classification is off or inconclusive, we would rather
        flag for review than silently miss an import."""
        v = evaluate(summarize(paste_trace(source="unknown"), final_chars=292))
        assert "paste_dominant" in v.flag_names

    def test_mobile_keyboard_suppresses_silent_insertion(self):
        """Soft keyboards do not emit usable keydown, so every insert looks
        silent. Flagging that would flag every phone user."""
        s = summarize(mobile_trace(), virtual_keyboard=True)
        s.external_insert_ratio = 0.9   # force the rule's precondition
        v = evaluate(s)
        assert "silent_insertion" not in v.flag_names
        assert "silent_insertion" in v.suppressed
        assert any("soft keyboard" in n for n in v.notes)

    def test_ime_composition_suppresses_silent_insertion(self):
        s = summarize([TypingEvent(i * 150, "insertCompositionText", "unknown", i, 1,
                                   {"composing": True}) for i in range(60)])
        s.external_insert_ratio = 0.9
        v = evaluate(s)
        assert "silent_insertion" not in v.flag_names
        assert any("IME" in n for n in v.notes)

    def test_short_answers_do_not_trip_rhythm_rules(self):
        """A two-word answer has no rhythm to speak of."""
        events = [TypingEvent(i * 100, "insertText", "letter", i, 1) for i in range(12)]
        v = evaluate(summarize(events))
        assert "transcription_rhythm" not in v.flag_names

    def test_rhythm_rule_needs_all_three_conditions(self):
        """Conjunctive by design: regular typing alone, with pauses or revision
        present, is just someone who types steadily."""
        s = summarize(transcription_trace())
        assert "transcription_rhythm" in evaluate(s).flag_names
        # Add revision behaviour and the flag must go quiet.
        s.revision_ratio = 0.25
        assert "transcription_rhythm" not in evaluate(s).flag_names

    def test_slow_careful_typing_is_not_implausible(self):
        events = [TypingEvent(i * 400, "insertText", "letter", i, 1) for i in range(300)]
        assert "implausible_speed" not in evaluate(summarize(events)).flag_names


class TestThresholdOverrides:
    def test_override_makes_a_rule_stricter(self):
        s = summarize(paste_trace(paste_chars=100), final_chars=400)
        assert "paste_dominant" not in evaluate(s).flag_names
        v = evaluate(s, thresholds={"paste_dominant.pasted_fraction": 0.2})
        assert "paste_dominant" in v.flag_names

    def test_override_makes_a_rule_looser(self):
        s = summarize(paste_trace(), final_chars=292)
        v = evaluate(s, thresholds={"paste_dominant.pasted_fraction": 0.999})
        assert "paste_dominant" not in v.flag_names

    def test_threshold_recorded_in_evidence(self):
        v = evaluate(summarize(paste_trace(), final_chars=292),
                     thresholds={"paste_dominant.pasted_fraction": 0.4})
        flag = next(f for f in v.flags if f.name == "paste_dominant")
        assert flag.evidence["threshold"] == 0.4


class TestVerdictSerialization:
    def test_roundtrip(self):
        v = evaluate(summarize(paste_trace(), final_chars=292))
        restored = Verdict.from_dict(v.to_dict())
        assert restored.level == v.level
        assert restored.flag_names == v.flag_names
        assert restored.flags[0].evidence == v.flags[0].evidence

    def test_empty_verdict_roundtrip(self):
        v = evaluate(summarize(natural_trace()))
        restored = Verdict.from_dict(v.to_dict())
        assert restored.level == "ok"
        assert restored.flags == []

    def test_flag_roundtrip(self):
        f = Flag(name="x", explanation="y", evidence={"a": 1}, severity="suspect")
        assert Flag.from_dict(f.to_dict()).to_dict() == f.to_dict()


class TestCalibration:
    def _population(self, n=60, seed_base=0):
        rows = []
        for i in range(n):
            s = summarize(natural_trace(300, seed=seed_base + i))
            rows.append({
                "final_chars": s.final_chars,
                "iki_log_cv": s.iki_log_cv,
                "active_ms": s.active_ms,
                "chars_typed": s.chars_typed,
                "virtual_keyboard": 0,
            })
        return rows

    def test_insufficient_data_returns_no_thresholds(self):
        result = calibrate(self._population(5))
        assert result["thresholds"] == {}
        assert result["detail"]["status"] == "insufficient_data"

    def test_fits_thresholds_with_enough_data(self):
        result = calibrate(self._population())
        assert result["detail"]["status"] == "fitted"
        assert result["thresholds"]
        assert result["n_sessions"] >= 30

    def test_drift_is_bounded(self):
        """A homogeneous population must not drag a threshold onto its own
        median and start flagging honest annotators."""
        result = calibrate(self._population())
        for key, value in result["thresholds"].items():
            default = DEFAULT_THRESHOLDS[key]
            assert default / MAX_CALIBRATION_DRIFT <= value <= default * MAX_CALIBRATION_DRIFT

    def test_caveat_is_always_present_when_fitted(self):
        """Percentile thresholds flag a fixed share by construction. The result
        must say so, because a caller will otherwise read it as a finding."""
        result = calibrate(self._population())
        assert "caveat" in result["detail"]
        assert "honest population" in result["detail"]["caveat"]

    def test_mobile_and_short_sessions_excluded(self):
        rows = self._population()
        rows += [{"final_chars": 500, "iki_log_cv": 0.001, "active_ms": 1000,
                  "chars_typed": 500, "virtual_keyboard": 1}] * 50
        rows += [{"final_chars": 5, "iki_log_cv": 0.001, "active_ms": 1000,
                  "chars_typed": 5, "virtual_keyboard": 0}] * 50
        result = calibrate(rows)
        assert result["n_sessions"] == 60

    def test_short_sessions_below_rhythm_minimum_excluded(self):
        rows = [{"final_chars": MIN_CHARS_FOR_RHYTHM_FLAGS - 1, "iki_log_cv": 0.1,
                 "active_ms": 10000, "chars_typed": 50, "virtual_keyboard": 0}] * 100
        assert calibrate(rows)["thresholds"] == {}


class TestSupervisedFit:
    def test_requires_two_classes(self):
        pytest.importorskip("sklearn")
        from potato.typing_detect import fit_supervised
        rows = [{"keystrokes": 10}] * 10
        with pytest.raises(ValueError, match="both composed"):
            fit_supervised(rows, [0] * 10)

    def test_separates_the_synthetic_classes(self):
        """The supervised path should reproduce the literature's result on data
        where the classes are genuinely separable."""
        pytest.importorskip("sklearn")
        from potato.typing_detect import fit_supervised

        rows, labels = [], []
        for i in range(25):
            composed = summarize(natural_trace(300, seed=i))
            rows.append(composed.to_dict())
            labels.append(0)
            pasted = summarize(paste_trace(), final_chars=292)
            rows.append(pasted.to_dict())
            labels.append(1)

        result = fit_supervised(rows, labels, model="random_forest")
        assert result["cv_accuracy_mean"] > 0.9
        assert result["n_samples"] == 50
        assert result["feature_importances"]
