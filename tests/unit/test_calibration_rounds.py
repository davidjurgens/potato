"""
Calibration rounds: sending annotators back through training mid-study.

``TRAINING`` was a one-shot gate between ``INSTRUCTIONS`` and ``ANNOTATION``.
A user who passed it could never be sent back, so "re-calibrate periodically"
-- the qualifier without which the reported agreement gains do not hold -- was
not expressible at all.

The failure mode worth guarding is the quiet one: recalling a user whose
``passed`` flag is still set. They arrive in TRAINING, the route sees a passed
state, advances them straight out again, and the round appears to have run and
done nothing.
"""

from __future__ import annotations

import pytest

from potato import calibration
from potato.phase import UserPhase


class FakeTrainingState:
    def __init__(self):
        self.completed_questions = {"q1": {"correct": True, "attempts": 1}}
        self.total_correct = 3
        self.total_attempts = 4
        self.total_mistakes = 1
        self.passed = True
        self.failed = False
        self.current_question_index = 3
        self.training_instances = ["t1", "t2", "t3"]
        self.feedback_cleared = False

    def clear_feedback(self):
        self.feedback_cleared = True


class FakeUserState:
    def __init__(self, phase=UserPhase.ANNOTATION):
        self._phase = phase
        self._page = None
        self.training = FakeTrainingState()
        self.assignments = ["i1", "i2", "i3"]

    def get_phase(self):
        return self._phase

    def get_training_state(self):
        return self.training

    def advance_to_phase(self, phase, page):
        self._phase, self._page = phase, page


class FakeUSM:
    def __init__(self, states):
        self.user_to_annotation_state = dict(states)

    def get_user_state(self, uid):
        return self.user_to_annotation_state.get(uid)


@pytest.fixture
def config(tmp_path):
    return {
        "task_dir": str(tmp_path),
        "annotation_task_name": "study",
        "training": {"enabled": True},
    }


@pytest.fixture
def usm():
    return FakeUSM({
        "alice": FakeUserState(UserPhase.ANNOTATION),
        "bob": FakeUserState(UserPhase.ANNOTATION),
        "carol": FakeUserState(UserPhase.CONSENT),
    })


class TestEligibility:
    def test_only_annotators_past_the_gate_are_eligible(self, usm):
        """
        Someone still in CONSENT has not been calibrated once. Sending them
        "back" to training would skip the phases in between.
        """
        assert calibration.eligible_users(usm) == ["alice", "bob"]

    def test_finished_annotators_are_still_eligible(self):
        usm = FakeUSM({"dan": FakeUserState(UserPhase.DONE)})
        assert calibration.eligible_users(usm) == ["dan"]


class TestStartingARound:
    def test_recalled_users_land_back_in_training(self, config, usm):
        result = calibration.start_round(config, usm, ["alice"], "admin")
        assert result["recalled"] == ["alice"]
        assert usm.get_user_state("alice").get_phase() == UserPhase.TRAINING

    def test_the_passed_flag_is_cleared(self, config, usm):
        """
        The bug this feature would otherwise ship with. `passed` is sticky, so
        a recalled user is advanced straight back out of TRAINING on their
        next request and the round silently does nothing.
        """
        calibration.start_round(config, usm, ["alice"], "admin")
        training = usm.get_user_state("alice").get_training_state()
        assert training.passed is False
        assert training.failed is False

    def test_progress_counters_are_reset(self, config, usm):
        calibration.start_round(config, usm, ["alice"], "admin")
        training = usm.get_user_state("alice").get_training_state()
        assert training.completed_questions == {}
        assert training.total_correct == 0
        assert training.total_attempts == 0
        assert training.total_mistakes == 0
        assert training.current_question_index == 0
        assert training.feedback_cleared

    def test_the_training_item_list_is_kept(self, config, usm):
        """
        The route only re-seeds an EMPTY list, so clearing it here would
        re-read the training file and could hand out a different set --
        turning a repeat of the exercise into a different exercise.
        """
        calibration.start_round(config, usm, ["alice"], "admin")
        assert usm.get_user_state("alice").get_training_state().training_instances \
            == ["t1", "t2", "t3"]

    def test_assignments_and_annotations_are_untouched(self, config, usm):
        """A calibration round re-does the exercise, not the study."""
        calibration.start_round(config, usm, ["alice"], "admin")
        assert usm.get_user_state("alice").assignments == ["i1", "i2", "i3"]

    def test_an_ineligible_user_is_reported_not_dropped(self, config, usm):
        """
        An admin recalling twelve people needs to know that two of them are
        still on the consent page.
        """
        result = calibration.start_round(config, usm, ["alice", "carol"], "admin")
        assert result["recalled"] == ["alice"]
        assert "carol" in result["skipped"]
        assert usm.get_user_state("carol").get_phase() == UserPhase.CONSENT

    def test_an_unknown_username_is_skipped(self, config, usm):
        result = calibration.start_round(config, usm, ["nobody"], "admin")
        assert result["recalled"] == []
        assert "nobody" in result["skipped"]

    def test_training_must_be_configured(self, config, usm):
        """
        Recalling annotators to a phase that immediately advances past itself
        looks exactly like the feature silently not working.
        """
        config["training"] = {"enabled": False}
        with pytest.raises(ValueError, match="training"):
            calibration.start_round(config, usm, ["alice"], "admin")
        assert usm.get_user_state("alice").get_phase() == UserPhase.ANNOTATION


class TestRoundRecord:
    def test_a_round_is_recorded_and_readable(self, config, usm):
        result = calibration.start_round(config, usm, ["alice", "bob"], "admin",
                                         reason="tone alpha fell 22%")
        history = calibration.round_history(config)
        assert len(history) == 1
        assert history[0]["id"] == result["round_id"]
        assert history[0]["usernames"] == ["alice", "bob"]
        assert history[0]["reason"] == "tone alpha fell 22%"
        assert history[0]["started_by"] == "admin"

    def test_only_the_users_actually_recalled_are_recorded(self, config, usm):
        calibration.start_round(config, usm, ["alice", "carol"], "admin")
        assert calibration.round_history(config)[0]["usernames"] == ["alice"]

    def test_history_is_newest_first(self, config, usm):
        calibration.start_round(config, usm, ["alice"], "admin", reason="first")
        calibration.start_round(config, usm, ["bob"], "admin", reason="second")
        assert [r["reason"] for r in calibration.round_history(config)] == [
            "second", "first"]

    def test_an_unwritable_database_does_not_undo_the_recall(self, usm,
                                                             monkeypatch):
        """
        The annotators have already been moved by the time the row is written.
        A round that ran but was not logged beats an exception after the fact.
        """
        monkeypatch.setattr(calibration, "_db",
                            lambda *_a: (_ for _ in ()).throw(OSError("disk")))
        result = calibration.start_round(
            {"task_dir": "/nonexistent", "training": {"enabled": True}},
            usm, ["alice"], "admin")
        assert result["recalled"] == ["alice"]
        assert result["round_id"] is None
        assert usm.get_user_state("alice").get_phase() == UserPhase.TRAINING


class TestProgress:
    def test_states_are_reported_per_user(self, usm):
        usm.get_user_state("alice").get_training_state().passed = True
        bob = usm.get_user_state("bob").get_training_state()
        bob.passed, bob.failed = False, True
        progress = {p["username"]: p["state"]
                    for p in calibration.round_progress(usm, ["alice", "bob"])}
        assert progress == {"alice": "passed", "bob": "failed"}

    def test_a_partly_done_user_is_in_progress(self, usm):
        training = usm.get_user_state("alice").get_training_state()
        training.passed = training.failed = False
        entry = calibration.round_progress(usm, ["alice"])[0]
        assert entry["state"] == "in_progress"
        assert entry["answered"] == 1
        assert entry["total"] == 3

    def test_an_unknown_user_does_not_raise(self, usm):
        assert calibration.round_progress(usm, ["ghost"])[0]["state"] == "unknown"
