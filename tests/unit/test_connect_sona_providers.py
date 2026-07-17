"""
Unit tests for the CloudResearch Connect and SONA Systems providers.

SONA's credit grant is the critical path: it must fire exactly once per
participant (the done page is re-renderable) and fall back to the
client-side credit link when the server-side call fails.
"""

import pytest
from unittest.mock import MagicMock, patch

from potato.crowdsourcing import CompletionOutcome, ParticipantIdentity
from potato.crowdsourcing.providers.connect import ConnectProvider
from potato.crowdsourcing.providers.sona import SonaProvider


class TestConnectProvider:
    def test_identity_from_connect_params(self):
        provider = ConnectProvider({}, {})
        identity = provider.extract_identity({
            'participantId': 'cr_worker_1',
            'assignmentId': 'assign_9',
            'projectId': 'proj_4',
        })
        assert identity.worker_id == 'cr_worker_1'
        assert identity.session_id == 'assign_9'
        assert identity.study_id == 'proj_4'

    def test_completion_code(self):
        provider = ConnectProvider({'completion': {'code': 'CR-CODE'}}, {})
        action = provider.completion_action(
            ParticipantIdentity(worker_id='w'), CompletionOutcome.COMPLETED)
        assert action.kind == 'code_only'
        assert action.code == 'CR-CODE'
        assert action.platform_label == 'Connect'

    def test_completion_redirect(self):
        provider = ConnectProvider({'completion': {
            'code': 'CR-CODE',
            'redirect_url': 'https://connect.cloudresearch.com/participant/project/p1/complete',
        }}, {})
        action = provider.completion_action(
            ParticipantIdentity(worker_id='w'), CompletionOutcome.COMPLETED)
        assert action.kind == 'redirect'
        assert action.redirect_url.endswith('/complete')


SONA_CONFIG = {
    'hostname': 'dept.sona-systems.com',
    'experiment_id': 123,
    'credit_token': 'tok123',
}


def make_sona(config=None, state=None):
    provider = SonaProvider(dict(SONA_CONFIG, **(config or {})), {})
    provider._user_state = MagicMock(return_value=state)
    provider._save_user_state = MagicMock()
    return provider


def fake_state(granted=False):
    state = MagicMock()
    state.crowd_metadata = {'sona_credit_granted': True} if granted else {}
    return state


class TestSonaProvider:
    def test_id_param_default(self):
        assert SonaProvider(SONA_CONFIG, {}).id_param() == 'sona_code'

    def test_server_side_credit_grant(self):
        state = fake_state()
        provider = make_sona(state=state)
        identity = ParticipantIdentity(worker_id='SURVEYCODE42')

        with patch('requests.get') as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            provider.on_completion(identity, CompletionOutcome.COMPLETED)

        url = mock_get.call_args[0][0]
        assert url == ('https://dept.sona-systems.com/services/SonaAPI.svc/WebstudyCredit'
                       '?experiment_id=123&credit_token=tok123&survey_code=SURVEYCODE42')
        assert state.crowd_metadata['sona_credit_granted'] is True
        provider._save_user_state.assert_called_once_with(state)

    def test_credit_grant_is_idempotent(self):
        provider = make_sona(state=fake_state(granted=True))
        with patch('requests.get') as mock_get:
            provider.on_completion(
                ParticipantIdentity(worker_id='CODE'), CompletionOutcome.COMPLETED)
        mock_get.assert_not_called()

    def test_failed_grant_leaves_flag_unset(self):
        state = fake_state()
        provider = make_sona(state=state)
        with patch('requests.get') as mock_get:
            mock_get.return_value = MagicMock(status_code=500)
            provider.on_completion(
                ParticipantIdentity(worker_id='CODE'), CompletionOutcome.COMPLETED)
        assert 'sona_credit_granted' not in state.crowd_metadata
        provider._save_user_state.assert_not_called()

    def test_network_error_is_swallowed(self):
        state = fake_state()
        provider = make_sona(state=state)
        with patch('requests.get', side_effect=ConnectionError("down")):
            provider.on_completion(
                ParticipantIdentity(worker_id='CODE'), CompletionOutcome.COMPLETED)
        assert 'sona_credit_granted' not in state.crowd_metadata

    def test_done_page_after_grant_shows_confirmation(self):
        provider = make_sona(state=fake_state(granted=True))
        action = provider.completion_action(
            ParticipantIdentity(worker_id='CODE'), CompletionOutcome.COMPLETED)
        assert action.kind == 'none'
        assert 'credit has been granted' in action.message

    def test_done_page_without_grant_offers_client_link(self):
        provider = make_sona(state=fake_state())
        action = provider.completion_action(
            ParticipantIdentity(worker_id='CODE99'), CompletionOutcome.COMPLETED)
        assert action.kind == 'redirect'
        assert action.redirect_url == (
            'https://dept.sona-systems.com/webstudy_credit.aspx'
            '?experiment_id=123&credit_token=tok123&survey_code=CODE99')

    def test_missing_config_disables_provider(self):
        provider = SonaProvider({'hostname': 'x'}, {})
        with patch('requests.get') as mock_get:
            provider.on_completion(
                ParticipantIdentity(worker_id='CODE'), CompletionOutcome.COMPLETED)
        mock_get.assert_not_called()
        action = provider.completion_action(
            ParticipantIdentity(worker_id='CODE'), CompletionOutcome.COMPLETED)
        assert action.kind == 'none'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
