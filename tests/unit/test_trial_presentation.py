"""trial_timing.presentation: self-paced reading, RSVP and the maze task."""

import pytest

from potato import trial_timing as tt
from potato.server_utils.config_module import ConfigValidationError

SCHEMES = [{"name": "answer", "annotation_type": "radio", "labels": ["Yes", "No"]}]


def _cfg(presentation, response=True, schemes=SCHEMES):
    block = {"enabled": True, "presentation": presentation}
    if response:
        block["response"] = {"schema": "answer", "keys": {"f": "Yes", "j": "No"}}
    return {"annotation_schemes": schemes, "item_properties": {"text_key": "text"},
            "trial_timing": block}


class TestValidation:
    def test_moving_window_ok(self):
        tt.validate_trial_timing_config(_cfg({"mode": "moving_window", "region_separator": "|"}))

    def test_maze_ok_without_response(self):
        tt.validate_trial_timing_config(_cfg(
            {"mode": "maze", "distractor_field": "d"}, response=False,
            schemes=[{"name": "i", "annotation_type": "pure_display", "description": "x"}]))

    @pytest.mark.parametrize("presentation,match", [
        ({"mode": "scroll"}, "mode must be one of"),
        ({"mode": "maze"}, "needs distractor_field"),
        ({"mode": "maze", "distractor_field": "d", "maze_keys": {"left": "e", "right": "e"}},
         "two different"),
        ({"mode": "maze", "distractor_field": "d", "on_error": "retry"}, "stop or redo"),
        ({"mode": "moving_window", "on_error": "stop"}, "maze only"),
        ({"mode": "moving_window", "advance_key": "enter"}, "one key"),
        ({"mode": "moving_window", "advance_key": "f"}, "uses f"),
        ({"region_separator": ""}, "1-3 characters"),
        ({"bogus": 1}, "unknown key"),
    ])
    def test_refused(self, presentation, match):
        with pytest.raises(ConfigValidationError, match=match):
            tt.validate_trial_timing_config(_cfg(presentation))

    def test_reading_only_cannot_hold_a_question(self):
        with pytest.raises(ConfigValidationError, match="could never be answered"):
            tt.validate_trial_timing_config(_cfg({"mode": "centered"}, response=False))


class TestClientConfig:
    def test_regions_split_by_separator_or_words(self):
        cfg = _cfg({"mode": "moving_window", "region_separator": "|", "question_field": "q"})
        out = tt.client_config(cfg, {"text": "The horse | raced past |  the barn", "q": ""})
        assert out["presentation"]["regions"] == ["The horse", "raced past", "the barn"]
        assert out["presentation"]["ask"] is False and out["presentation"]["advance_key"] == " "
        words = tt.client_config(_cfg({"mode": "centered"}), {"text": "a  b c"})
        assert words["presentation"]["regions"] == ["a", "b", "c"]
        assert words["presentation"]["ask"] is True

    def test_maze_first_distractor_is_added(self):
        cfg = _cfg({"mode": "maze", "distractor_field": "d"}, response=False)
        out = tt.client_config(cfg, {"text": "the cat sat", "d": "ugly when"})
        assert out["presentation"]["distractors"] == [tt.MAZE_FIRST_DISTRACTOR, "ugly", "when"]
        assert out["presentation"]["maze_keys"] == {"left": "e", "right": "i"}


class TestRecords:
    def _view(self):
        return tt.client_config(_cfg({"mode": "moving_window"}), {"text": "a b c"})

    def test_completed_with_regions_is_excused(self):
        # An item with no question (question_field empty for it), every region read.
        view = tt.client_config(_cfg({"mode": "moving_window", "question_field": "q"}),
                                {"text": "a b", "q": ""})
        rec, flags = tt.validate_record(
            {"outcome": "completed", "onset_epoch_ms": 1,
             "regions": [{"index": 0, "text": "a", "rt_ms": 300}, {"index": 1, "rt_ms": 280}]},
            served_at=1000.0, cfg=view, now=1002.0)
        assert flags == [] and len(rec["regions"]) == 2
        assert tt.excuses_required_answer(rec) and tt.is_terminal(rec)

    def test_reading_longer_than_the_server_saw_is_flagged(self):
        rec, flags = tt.validate_record(
            {"outcome": "completed", "regions": [{"index": 0, "rt_ms": 9000}]},
            served_at=1000.0, cfg=self._view(), now=1001.0)
        assert "reading_exceeds_server_elapsed" in flags

    def test_completed_without_presentation_is_not_excused(self):
        cfg = tt.client_config({"annotation_schemes": SCHEMES, "trial_timing": {
            "enabled": True, "response": {"schema": "answer", "keys": {"f": "Yes"}}}}, {})
        rec, flags = tt.validate_record({"outcome": "completed"}, served_at=1000.0, cfg=cfg,
                                        now=1001.0)
        assert "completed_without_presentation" in flags and not tt.excuses_required_answer(rec)

    def test_region_junk_is_dropped(self):
        rec, _ = tt.validate_record(
            {"outcome": "completed", "regions": ["x", {"rt_ms": "fast", "text": "a" * 500},
                                                 {"rt_ms": -5}]},
            served_at=1000.0, cfg=self._view(), now=1001.0)
        assert rec["regions"][0] == {} and rec["regions"][1] == {"rt_ms": -5}
        assert "bad_region_rt" in rec["flags"]


def _spr_cfg(**pres):
    base = {"mode": "moving_window", "regions": ["The", "horse", "fell."], "ask": True}
    base.update(pres)
    return {"presentation": base, "schema": "comp", "keys": {"f": "Yes", "j": "No"}}


def test_completed_with_a_question_does_not_excuse():
    """Audit 96 R1: a forged `completed` must not skip the comprehension question."""
    from potato.trial_timing import excuses_required_answer, validate_record
    rec = {"outcome": "completed", "regions": [{"index": 0, "rt_ms": 0, "text": "x"}]}
    clean, flags = validate_record(rec, served_at=None, cfg=_spr_cfg())
    assert "completed_with_question" in flags and "regions_incomplete" in flags
    assert not excuses_required_answer(clean)


def test_completed_reading_without_question_still_excuses(monkeypatch):
    import time
    from potato.trial_timing import excuses_required_answer, validate_record
    rec = {"outcome": "completed",
           "regions": [{"index": i, "rt_ms": 300, "text": t} for i, t in enumerate(["The", "horse", "fell."])]}
    clean, flags = validate_record(rec, served_at=time.time() - 5, cfg=_spr_cfg(ask=False))
    assert flags == [] and excuses_required_answer(clean)


def test_maze_stop_is_flagged_but_finished():
    import time
    from potato.trial_timing import excuses_required_answer, validate_record
    rec = {"outcome": "completed", "regions": [
        {"index": 0, "rt_ms": 400, "correct": True}, {"index": 1, "rt_ms": 500, "correct": False}]}
    clean, flags = validate_record(rec, served_at=time.time() - 5,
                                   cfg=_spr_cfg(mode="maze", ask=False, on_error="stop"))
    assert "maze_error" in flags and "regions_incomplete" not in flags
    assert excuses_required_answer(clean)


def test_reload_mid_sentence_is_flagged():
    from potato.trial_timing import validate_record
    _, flags = validate_record({"outcome": "response", "label": "Yes", "rt_ms": 10, "reloads": 1},
                               served_at=None, cfg=_spr_cfg())
    assert "reloaded_mid_trial" in flags


def test_timing_keys_with_reading_warn_in_the_validate_report():
    """Audit 96 R8 re-verify: the warning reached the log but not the report."""
    import yaml
    from potato.validate_cli import validate_config_file
    from tests.helpers.test_utils import create_test_config, create_test_data_file, create_test_directory
    d = create_test_directory("spr_timing_warning")
    data = create_test_data_file(d, [{"id": "1", "text": "The horse raced past the barn fell."}])
    cfg = create_test_config(d, annotation_schemes=[{"annotation_type": "radio", "name": "comp",
                                                     "description": "?", "labels": ["Yes", "No"]}],
                             data_files=[data])
    config = yaml.safe_load(open(cfg))
    config["trial_timing"] = {"enabled": True, "trial_duration_ms": 3000,
                              "presentation": {"mode": "moving_window"},
                              "response": {"schema": "comp", "keys": {"f": "Yes", "j": "No"}}}
    yaml.safe_dump(config, open(cfg, "w"))
    report = validate_config_file(cfg)
    assert any("trial_duration_ms applies to the question after the reading" in w
               for w in report.other_warnings), report.other_warnings
