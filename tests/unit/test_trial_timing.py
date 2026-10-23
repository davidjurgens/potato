"""Timed trials (potato/trial_timing.py): config, client config, record checks,
and the completion accessors a timeout has to satisfy."""

import pytest

from potato import trial_timing as tt
from potato.server_utils.config_module import ConfigValidationError
from potato.user_state_management import InMemoryUserState

SCHEMES = [{"name": "decision", "annotation_type": "radio", "labels": ["word", "nonword"]}]


def _cfg(**block):
    base = {"enabled": True, "fixation_ms": 500, "trial_duration_ms": 2000,
            "response": {"schema": "decision", "keys": {"f": "word", "j": "nonword"}}}
    base.update(block)
    return {"annotation_schemes": SCHEMES, "trial_timing": base}


class TestValidation:
    def test_valid(self):
        tt.validate_trial_timing_config(_cfg())

    @pytest.mark.parametrize("block,match", [
        ({"fixation_ms": -1}, "fixation_ms"),
        ({"fixation_ms": 1.5}, "fixation_ms"),
        ({"stimulus_duration_ms": 0}, "omit it"),
        ({"trial_duration_ms": 0}, "omit it"),
        ({"response": {"keys": {"f": "word"}}}, "response.schema"),
        ({"response": {"schema": "missing", "keys": {"f": "word"}}}, "not in annotation_schemes"),

        ({"response": {"schema": "decision"}}, "keys"),
        ({"response": {"schema": "decision", "keys": {"f": "maybe"}}}, "not a label"),
        ({"response": {"schema": "decision", "keys": {"ff": "word"}}}, "one character"),
        ({"response": {"schema": "decision", "keys": {True: "word"}}}, "one character"),
        ({"response": {"schema": "decision", "keys": {"f": "word", "j": "word"}}}, "two keys"),
        ({"item_overrides": {"soa": "soa_ms"}}, "item_overrides"),
        ({"stimulus_ms": 100}, "unknown key"),
    ])
    def test_refused(self, block, match):
        with pytest.raises(ConfigValidationError, match=match):
            tt.validate_trial_timing_config(_cfg(**block))

    def test_note_scheme_type_refused(self):
        cfg = _cfg(response={"schema": "note", "keys": {"f": "word"}})
        cfg["annotation_schemes"] = [{"name": "note", "annotation_type": "text"}]
        with pytest.raises(ConfigValidationError, match="radio, likert"):
            tt.validate_trial_timing_config(cfg)

    def test_second_scheme_refused(self):
        """Audit 94, T3: a second question on a timed page can't be answered."""
        cfg = _cfg()
        cfg["annotation_schemes"] = SCHEMES + [{"name": "why", "annotation_type": "text"}]
        with pytest.raises(ConfigValidationError, match="only its response scheme"):
            tt.validate_trial_timing_config(cfg)
        cfg["annotation_schemes"] = SCHEMES + [{"name": "intro", "annotation_type": "pure_display"}]
        tt.validate_trial_timing_config(cfg)

    def test_mouse_only_ok(self):
        tt.validate_trial_timing_config(_cfg(response={"schema": "decision", "allow_mouse": True}))


class TestClientConfig:
    def test_off(self):
        assert tt.client_config({"trial_timing": {"enabled": False}}) is None
        assert tt.client_config({}) is None

    def test_labels_listed(self):
        assert tt.client_config(_cfg())["labels"] == ["word", "nonword"]

    def test_values(self):
        c = tt.client_config(_cfg(response={"schema": "decision",
                                            "keys": {"F": "word", "space": "nonword"}}))
        assert c["keys"] == {"f": "word", " ": "nonword"}
        assert c["fixation_ms"] == 500 and c["trial_duration_ms"] == 2000
        assert c["stimulus_duration_ms"] is None
        assert c["show_response_options"] is False

    def test_item_overrides(self):
        cfg = _cfg(item_overrides={"stimulus_duration_ms": "soa", "trial_duration_ms": "dl"})
        c = tt.client_config(cfg, {"soa": "150", "dl": 0})
        assert c["stimulus_duration_ms"] == 150
        assert c["trial_duration_ms"] is None   # 0 = no deadline for this item
        c = tt.client_config(cfg, {"soa": "fast"})
        assert c["stimulus_duration_ms"] is None and c["trial_duration_ms"] == 2000


class TestRecord:
    CFG = {"trial_duration_ms": 2000, "keys": {"f": "word", "j": "nonword"},
           "labels": ["word", "nonword"]}

    def test_response_ok(self):
        rec, flags = tt.validate_record(
            {"outcome": "response", "key": "f", "label": "word", "rt_ms": 512.3,
             "frame_ms": 16.7, "evil": "<script>"}, served_at=100.0, cfg=self.CFG, now=101.5)
        assert flags == [] and rec["rt_ms"] == 512.3 and "evil" not in rec
        assert rec["server_elapsed_ms"] == 1500.0

    def test_rt_longer_than_server_saw(self):
        _, flags = tt.validate_record({"outcome": "response", "label": "word", "rt_ms": 5000},
                                      served_at=100.0, cfg=self.CFG, now=101.0)
        assert "rt_exceeds_server_elapsed" in flags

    def test_early_timeout_flagged_and_not_excused(self):
        rec, flags = tt.validate_record({"outcome": "timeout"}, served_at=100.0,
                                        cfg=self.CFG, now=100.5)
        assert "timeout_too_early" in flags
        assert not tt.excuses_required_answer(rec)

    def test_real_timeout_excused(self):
        rec, flags = tt.validate_record({"outcome": "timeout"}, served_at=100.0,
                                        cfg=self.CFG, now=103.0)
        assert flags == [] and tt.excuses_required_answer(rec)

    def test_timeout_without_deadline(self):
        rec, flags = tt.validate_record({"outcome": "timeout"}, served_at=100.0,
                                        cfg={"trial_duration_ms": None}, now=110.0)
        assert "timeout_without_deadline" in flags and not tt.excuses_required_answer(rec)

    def test_unserved_item_is_flagged_and_not_excused(self):
        """Audit 94, T5: no served_at meant no check at all."""
        rec, flags = tt.validate_record({"outcome": "timeout"}, served_at=None, cfg=self.CFG)
        assert "not_served" in flags and not tt.excuses_required_answer(rec)

    @pytest.mark.parametrize("record,flag", [
        ({"outcome": "response", "key": "zz", "label": "word", "rt_ms": 300}, "key_not_mapped"),
        ({"outcome": "response", "key": "f", "label": "nonword", "rt_ms": 300}, "label_mismatch"),
        ({"outcome": "response", "label": "banana", "rt_ms": 300}, "label_not_in_scheme"),
    ])
    def test_key_and_label_checked(self, record, flag):
        """Audit 94, T6."""
        _, flags = tt.validate_record(record, served_at=100.0, cfg=self.CFG, now=101.0)
        assert flag in flags

    @pytest.mark.parametrize("bad", ["x", [], {"outcome": "skipped"}])
    def test_rejected(self, bad):
        rec, _ = tt.validate_record(bad, served_at=None, cfg=self.CFG)
        assert rec is None


class TestStore:
    def test_resend_is_not_a_new_attempt(self):
        us = InMemoryUserState("u", -1)
        tt.store_record(us, "i1", {"outcome": "timeout", "onset_epoch_ms": 10})
        tt.store_record(us, "i1", {"outcome": "timeout", "onset_epoch_ms": 10})
        assert us.instance_id_to_trial["i1"]["previous_attempts"] == []

    def test_rerun_keeps_history(self):
        us = InMemoryUserState("u", -1)
        tt.store_record(us, "i1", {"outcome": "timeout", "onset_epoch_ms": 10})
        tt.store_record(us, "i1", {"outcome": "response", "onset_epoch_ms": 20})
        rec = us.instance_id_to_trial["i1"]
        assert rec["outcome"] == "response"
        assert [a["onset_epoch_ms"] for a in rec["previous_attempts"]] == [10]


class TestCompletion:
    """A timed-out item has no label; it must still count as done, or the
    annotator never reaches the end of the task."""

    def _state(self, flags):
        us = InMemoryUserState("u", -1)
        us.instance_id_to_trial["i1"] = {"outcome": "timeout", "flags": flags}
        return us

    def test_real_timeout_counts(self):
        us = self._state([])
        assert us.has_annotated("i1")
        assert "i1" in us.get_annotated_instance_ids()

    def test_forged_timeout_does_not(self):
        us = self._state(["timeout_too_early"])
        assert not us.has_annotated("i1")
        assert "i1" not in us.get_annotated_instance_ids()

    def test_no_trials_unchanged(self):
        us = InMemoryUserState("u", -1)
        assert not us.has_annotated("i1") and us.get_annotated_instance_ids() == set()

    def test_clear_instance_drops_trial(self):
        us = self._state([])
        us.clear_instance_annotations("i1")
        assert not us.has_annotated("i1")
