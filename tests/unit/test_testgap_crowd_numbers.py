"""
Crowd-tab counts and payment paths, against the values the server writes.

The crowd tab compared phases with "Phase.DONE" while `str(UserPhase.DONE)` is
"done", so completed and in-progress were always 0, and it decided platform by
the first letter of the username. Auto-approve paid workers quality control had
blocked. The Prolific screen-out was re-sent on every reload of the done page.
Bonus rows were joined into a CSV unchecked.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from potato.phase import UserPhase


# ---------------------------------------------------------------------------
# Crowd tab
# ---------------------------------------------------------------------------

class _State:
    def __init__(self, phase):
        self.phase = phase


def _crowd(workers):
    """workers: {username: (UserPhase, stored auth data)}."""
    from potato.admin import AdminDashboard
    dashboard = AdminDashboard()
    dashboard.check_admin_access = lambda: True
    dashboard._get_annotator_timing_data = lambda u: SimpleNamespace(
        total_annotations=1, phase=str(workers[u][0]), total_seconds=10.0,
        annotations_per_hour=360.0, suspicious_level="Normal")
    dashboard._calculate_completion_percentage = lambda u: 100.0
    auth = SimpleNamespace(auth_backend=SimpleNamespace(
        user_data={u: data for u, (_p, data) in workers.items()}))
    usm = SimpleNamespace(get_user_state=lambda u: _State(workers[u][0]))
    with patch("potato.admin.get_user_state_manager", return_value=usm), \
         patch("potato.admin.get_users", return_value=list(workers)), \
         patch("potato.authentication.UserAuthenticator.get_instance", return_value=auth):
        return dashboard.get_crowdsourcing_data()


class TestCrowdTab:
    def test_finished_and_working_workers_are_counted(self):
        data = _crowd({
            "p1": (UserPhase.DONE, {"crowd_provider": "prolific"}),
            "p2": (UserPhase.ANNOTATION, {"crowd_provider": "prolific"}),
            "p3": (UserPhase.POSTSTUDY, {"crowd_provider": "prolific"}),
        })
        assert data["prolific"]["stats"]["completed_count"] == 1
        assert data["prolific"]["stats"]["in_progress_count"] == 2

    def test_the_username_does_not_choose_the_platform(self):
        data = _crowd({"Paul": (UserPhase.DONE, {}), "Alice": (UserPhase.DONE, {})})
        assert data["summary"]["prolific_workers"] == 0
        assert data["summary"]["mturk_workers"] == 0

    def test_the_recorded_arrival_platform_is_used(self):
        data = _crowd({"A1B2": (UserPhase.DONE, {
            "crowd_provider": "mturk", "prolific_study_id": "carried-over"})})
        assert data["summary"]["mturk_workers"] == 1
        assert data["summary"]["prolific_workers"] == 0

    def test_legacy_arrivals_are_classified_by_their_ids(self):
        data = _crowd({"5f00": (UserPhase.DONE, {
            "crowd_provider": "url_direct", "prolific_session_id": "s1"})})
        assert data["summary"]["prolific_workers"] == 1


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

class TestAutoApprove:
    def _approve(self, blocked):
        from potato.crowdsourcing import webhooks
        client = MagicMock()
        qc = SimpleNamespace(is_user_blocked=lambda pid: blocked)
        with patch("potato.crowdsourcing.prolific_api.ProlificClient", return_value=client), \
             patch("potato.quality_control.get_quality_control_manager", return_value=qc):
            result = webhooks._handle_submission_change(
                {"status": "AWAITING REVIEW", "participant_id": "pid1",
                 "resource_id": "sub1"},
                {"token": "t"}, {"auto_approve": True})
        return result, client

    def test_a_blocked_participant_is_not_paid(self):
        result, client = self._approve(blocked=True)
        client.approve_submission.assert_not_called()
        assert result["auto_approved"] is False

    def test_a_participant_in_good_standing_is(self):
        result, client = self._approve(blocked=False)
        client.approve_submission.assert_called_once_with("sub1")
        assert result["auto_approved"] is True


class TestScreenOutOnce:
    def test_reloading_the_done_page_screens_out_once(self):
        from potato.crowdsourcing.base import CompletionOutcome, ParticipantIdentity
        from potato.crowdsourcing.providers.prolific import ProlificProvider
        provider = ProlificProvider({"screen_out_on_block": True, "token": "t",
                                     "study_id": "st"}, {})
        identity = ParticipantIdentity(worker_id="w", session_id="sess", study_id="st")
        client = MagicMock()
        with patch("potato.crowdsourcing.prolific_api.ProlificClient", return_value=client):
            for _ in range(3):
                provider.on_completion(identity, CompletionOutcome.FAILED_CHECKS)
        assert client.screen_out_submissions.call_count == 1


class TestBonusRows:
    @pytest.mark.parametrize("rows", [
        [["p1,p2", 1.0]],          # a comma adds a CSV row
        [["p1\np2", 1.0]],         # so does a newline
        [["p1", -5]],
        [["p1", 0]],
        [["p1", float("nan")]],
        [["p1", "lots"]],
        [["p1", True]],
        [["p1", 1.0], ["p1", 2.0]],
    ])
    def test_bad_rows_are_refused(self, rows):
        from potato.crowdsourcing.prolific_api import validate_bonus_rows
        with pytest.raises(ValueError):
            validate_bonus_rows(rows)

    def test_the_csv_holds_one_row_per_participant(self):
        from potato.crowdsourcing.prolific_api import ProlificClient
        client = ProlificClient("t")
        with patch.object(client, "_post", return_value={"id": "b"}) as post:
            client.set_up_bonuses("st", [["5f1a", 1.5], ["5f1b", "2"]])
        assert post.call_args[0][1]["csv_bonuses"] == "5f1a,1.5\n5f1b,2"


# ---------------------------------------------------------------------------
# Behavioural analytics
# ---------------------------------------------------------------------------

class TestAiAcceptRate:
    def test_undecided_suggestions_are_not_rejections(self):
        from potato.admin import AdminDashboard
        from potato.interaction_tracking import AIUsageEvent, BehavioralData
        dashboard = AdminDashboard()
        dashboard.check_admin_access = lambda: True
        bd = BehavioralData(instance_id="i1")
        bd.ai_usage = [
            AIUsageEvent(request_timestamp=1.0, schema_name="s", suggestion_accepted="0",
                         time_to_decision_ms=900),
            AIUsageEvent(request_timestamp=2.0, schema_name="s",
                         final_annotation="neg", time_to_decision_ms=1200),
            AIUsageEvent(request_timestamp=3.0, schema_name="s"),  # still open
        ]
        state = SimpleNamespace(instance_id_to_behavioral_data={"i1": bd})
        usm = SimpleNamespace(get_user_state=lambda u: state)
        with patch("potato.admin.get_user_state_manager", return_value=usm), \
             patch("potato.admin.get_users", return_value=["u"]), \
             patch.object(dashboard, "get_writing_process_data", return_value={}), \
             patch.object(dashboard, "get_drawing_process_data", return_value={}, create=True):
            result = dashboard.get_behavioral_analytics_data()
        ai = result["ai_usage"]
        assert (ai["total_accepts"], ai["total_rejects"], ai["total_pending"]) == (1, 1, 1)
        assert ai["accept_rate"] == 0.5
        assert result["users"][0]["ai_accept_rate"] == 0.5


class TestActiveTime:
    def _bd(self, offsets, kinds=None):
        from potato.interaction_tracking import BehavioralData, InteractionEvent
        bd = BehavioralData(instance_id="i1")
        kinds = kinds or ["click"] * len(offsets)
        for o, k in zip(offsets, kinds):
            target = "instance_load" if k == "navigation" else "x"
            bd.interactions.append(InteractionEvent(
                event_type=k, timestamp=1000.0 + o, target=target, instance_id="i1",
                client_timestamp=(1000.0 + o) * 1000))
        return bd

    def test_gaps_are_summed(self):
        assert self._bd([0, 3, 8]).active_time_ms() == 8000

    def test_a_long_idle_gap_is_capped(self):
        from potato.interaction_tracking import IDLE_GAP_CAP_SECONDS
        assert self._bd([0, 2, 2 + 3600]).active_time_ms() == int(
            (2 + IDLE_GAP_CAP_SECONDS) * 1000)

    def test_time_away_between_visits_is_not_counted(self):
        bd = self._bd([0, 5, 600, 604], ["navigation", "click", "navigation", "click"])
        assert bd.active_time_ms() == 9000

    def test_one_event_measures_nothing(self):
        assert self._bd([0]).active_time_ms() == 0

    def test_an_old_state_gets_its_time_on_load(self):
        from potato.interaction_tracking import BehavioralData
        saved = self._bd([0, 4]).to_dict()
        saved["total_time_ms"] = 0
        assert BehavioralData.from_dict(saved).total_time_ms == 4000
