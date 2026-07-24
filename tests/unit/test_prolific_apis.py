"""
Unit tests for potato/server_utils/prolific_apis.py.

Covers the ProlificStudy session-tracking regression (add_new_user used to
raise AttributeError on a never-initialized dict) and the workload monitor
pause/resume decisions and thread lifecycle. All HTTP is mocked.
"""

import time

import pytest
from unittest.mock import MagicMock, patch

from potato.server_utils.prolific_apis import ProlificStudy


STUDY_INFO = {
    'id': 'study123', 'name': 'Test Study', 'internal_name': 'test',
    'reward': 100, 'average_reward_per_hour': 900,
    'external_study_url': 'https://example.com', 'status': 'ACTIVE',
    'total_available_places': 10, 'places_taken': 0,
}


def _json_response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


def make_study(tmp_path, **kwargs):
    with patch('potato.server_utils.prolific_apis.requests') as mock_requests:
        mock_requests.get.return_value = _json_response(STUDY_INFO)
        study = ProlificStudy(
            token='tok', study_id='study123', saving_dir=str(tmp_path), **kwargs
        )
    return study


class TestAddNewUser:
    """Regression tests: add_new_user raised AttributeError before the fix."""

    def test_tracks_user_without_error(self, tmp_path):
        study = make_study(tmp_path)
        with patch('potato.server_utils.prolific_apis.requests') as mock_requests:
            mock_requests.get.return_value = _json_response({'status': 'ACTIVE'})
            status = study.add_new_user({'PROLIFIC_PID': 'worker1', 'SESSION_ID': 'sess1'})

        assert status == 'ACTIVE'
        assert study.sessions['sess1'] == {'username': 'worker1', 'status': 'ACTIVE'}
        assert 'worker1' in study.user_status_dict['ACTIVE']
        assert study.user2session['worker1'] == 'sess1'

    def test_api_failure_returns_none(self, tmp_path):
        study = make_study(tmp_path)
        with patch('potato.server_utils.prolific_apis.requests') as mock_requests:
            mock_requests.get.return_value = _json_response({'error': 'nope'}, status_code=404)
            status = study.add_new_user({'PROLIFIC_PID': 'worker1', 'SESSION_ID': 'sess1'})

        assert status is None
        assert 'sess1' not in study.sessions

    def test_status_dict_exists_before_first_poll(self, tmp_path):
        """get_concurrent_sessions_count must work before update_submission_status."""
        study = make_study(tmp_path)
        assert study.get_concurrent_sessions_count() == 0


class TestUpdateSubmissionStatus:
    def test_none_response_keeps_previous_state(self, tmp_path):
        study = make_study(tmp_path)
        study.user_status_dict['ACTIVE'].add('worker1')
        with patch.object(study, 'get_submissions_from_study', return_value=None):
            study.update_submission_status()
        assert 'worker1' in study.user_status_dict['ACTIVE']

    def test_groups_participants_by_status(self, tmp_path):
        study = make_study(tmp_path)
        submissions = [
            {'id': 's1', 'participant_id': 'w1', 'status': 'ACTIVE'},
            {'id': 's2', 'participant_id': 'w2', 'status': 'RETURNED'},
            {'id': 's3', 'participant_id': 'w3', 'status': 'AWAITING REVIEW'},
        ]
        with patch.object(study, 'get_submissions_from_study', return_value=submissions), \
             patch.object(study, 'reclaim_dropped_user_assignments', return_value={}):
            study.update_submission_status()

        assert study.user_status_dict['ACTIVE'] == {'w1'}
        assert study.user_status_dict['RETURNED'] == {'w2'}
        assert study.get_dropped_users() == ['w2']
        assert (tmp_path / 'submissions.json').exists()


class TestWorkloadDecisions:
    def _study_with_active(self, tmp_path, active_count, max_sessions=10):
        study = make_study(tmp_path, max_concurrent_sessions=max_sessions)
        study.user_status_dict['ACTIVE'] = {f'w{i}' for i in range(active_count)}
        return study

    def test_pauses_when_at_capacity(self, tmp_path):
        study = self._study_with_active(tmp_path, active_count=10)
        with patch.object(study, 'update_submission_status'), \
             patch.object(study, 'get_study_status', return_value='ACTIVE'), \
             patch.object(study, 'pause_study') as mock_pause:
            result = study.check_workload_once()

        assert result == 'paused'
        mock_pause.assert_called_once()
        assert study._paused_by_monitor is True

    def test_no_pause_below_capacity(self, tmp_path):
        study = self._study_with_active(tmp_path, active_count=5)
        with patch.object(study, 'update_submission_status'), \
             patch.object(study, 'pause_study') as mock_pause, \
             patch.object(study, 'start_study') as mock_start:
            result = study.check_workload_once()

        assert result is None
        mock_pause.assert_not_called()
        mock_start.assert_not_called()

    def test_resumes_when_load_drops(self, tmp_path):
        study = self._study_with_active(tmp_path, active_count=1)
        study._paused_by_monitor = True
        with patch.object(study, 'update_submission_status'), \
             patch.object(study, 'start_study') as mock_start:
            result = study.check_workload_once()

        assert result == 'resumed'
        mock_start.assert_called_once()
        assert study._paused_by_monitor is False

    def test_never_resumes_manually_paused_study(self, tmp_path):
        """A study the researcher paused (not the monitor) must stay paused."""
        study = self._study_with_active(tmp_path, active_count=0)
        study._paused_by_monitor = False
        with patch.object(study, 'update_submission_status'), \
             patch.object(study, 'start_study') as mock_start:
            result = study.check_workload_once()

        assert result is None
        mock_start.assert_not_called()

    def test_no_resume_until_below_20_percent(self, tmp_path):
        study = self._study_with_active(tmp_path, active_count=3, max_sessions=10)
        study._paused_by_monitor = True
        with patch.object(study, 'update_submission_status'), \
             patch.object(study, 'start_study') as mock_start:
            result = study.check_workload_once()

        assert result is None
        mock_start.assert_not_called()
        assert study._paused_by_monitor is True


class TestWorkloadMonitorThread:
    def test_start_and_stop(self, tmp_path):
        study = make_study(tmp_path, workload_checker_period=1)
        study.start_workload_monitor()
        assert study._monitor_thread.is_alive()
        assert study.workload_checker_on is True

        study.stop_workload_monitor()
        assert study._monitor_thread is None
        assert study.workload_checker_on is False

    def test_start_is_idempotent(self, tmp_path):
        study = make_study(tmp_path, workload_checker_period=1)
        study.start_workload_monitor()
        first_thread = study._monitor_thread
        study.start_workload_monitor()
        assert study._monitor_thread is first_thread
        study.stop_workload_monitor()

    def test_stop_without_start_is_safe(self, tmp_path):
        study = make_study(tmp_path)
        study.stop_workload_monitor()

    def test_loop_calls_check_and_survives_errors(self, tmp_path):
        study = make_study(tmp_path)
        study.checker_period = 0.05
        calls = []

        def failing_check():
            calls.append(1)
            raise RuntimeError("API down")

        with patch.object(study, 'check_workload_once', side_effect=failing_check):
            study.start_workload_monitor()
            deadline = time.time() + 2.0
            while len(calls) < 2 and time.time() < deadline:
                time.sleep(0.02)
            study.stop_workload_monitor()

        assert len(calls) >= 2, "monitor loop should keep polling after an exception"

    def test_legacy_workload_checker_delegates(self, tmp_path):
        study = make_study(tmp_path)
        with patch.object(study, 'start_workload_monitor') as mock_start:
            study.workload_checker()
        mock_start.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
