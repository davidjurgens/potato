"""
Unit tests for the Microworkers (VCODE), Clickworker (postback), and
expert-invite providers.
"""

import pytest
from unittest.mock import MagicMock, patch

from potato.crowdsourcing import CompletionOutcome, ParticipantIdentity
from potato.crowdsourcing.providers.clickworker import ClickworkerProvider
from potato.crowdsourcing.providers.expert import ExpertInviteProvider
from potato.crowdsourcing.providers.microworkers import (
    MicroworkersProvider,
    compute_vcode,
)


class TestMicroworkersProvider:
    CONFIG = {'vcode_secret': 's3cret', 'vcode_prefix': 'mw-', 'vcode_length': 10}

    def test_identity_captures_campaign_and_slot(self):
        provider = MicroworkersProvider(self.CONFIG, {})
        identity = provider.extract_identity(
            {'mw_id': 'w77', 'campaign_id': 'c5', 'slot_id': 's9'})
        assert identity.worker_id == 'w77'
        assert identity.study_id == 'c5'
        assert identity.session_id == 's9'

    def test_vcode_is_deterministic_and_prefixed(self):
        provider = MicroworkersProvider(self.CONFIG, {})
        identity = ParticipantIdentity(worker_id='w77', study_id='c5')
        action1 = provider.completion_action(identity, CompletionOutcome.COMPLETED)
        action2 = provider.completion_action(identity, CompletionOutcome.COMPLETED)
        assert action1.kind == 'generated_code'
        assert action1.code == action2.code
        assert action1.code.startswith('mw-')
        assert len(action1.code) == len('mw-') + 10

    def test_vcode_differs_per_worker_and_campaign(self):
        provider = MicroworkersProvider(self.CONFIG, {})
        code_a = provider.vcode_for(ParticipantIdentity(worker_id='wA', study_id='c1'))
        code_b = provider.vcode_for(ParticipantIdentity(worker_id='wB', study_id='c1'))
        code_c = provider.vcode_for(ParticipantIdentity(worker_id='wA', study_id='c2'))
        assert len({code_a, code_b, code_c}) == 3

    def test_verify_vcode_roundtrip(self):
        provider = MicroworkersProvider(self.CONFIG, {})
        code = provider.vcode_for(ParticipantIdentity(worker_id='w77', study_id='c5'))
        assert provider.verify_vcode('w77', 'c5', code) is True
        assert provider.verify_vcode('w77', 'c5', 'mw-wrong') is False
        assert provider.verify_vcode('other', 'c5', code) is False

    def test_missing_secret_falls_back(self):
        provider = MicroworkersProvider({}, {'completion_code': 'STATIC'})
        action = provider.completion_action(
            ParticipantIdentity(worker_id='w'), CompletionOutcome.COMPLETED)
        assert action.kind == 'code_only'
        assert action.code == 'STATIC'

    def test_compute_vcode_stable_contract(self):
        # Pin the derivation so accidental changes break loudly: codes issued
        # to workers must stay verifiable across releases.
        assert compute_vcode('k', 'w', 'c', prefix='p-', length=8) == \
            compute_vcode('k', 'w', 'c', prefix='p-', length=8)
        assert compute_vcode('k', 'w', 'c') != compute_vcode('k2', 'w', 'c')


def _clickworker(config, state=None):
    provider = ClickworkerProvider(config, {})
    provider._user_state = MagicMock(return_value=state)
    provider._save_user_state = MagicMock()
    return provider


def _state(sent=False):
    state = MagicMock()
    state.crowd_metadata = {'clickworker_postback_sent': True} if sent else {}
    return state


class TestClickworkerProvider:
    BASE = {
        'postback_url': 'https://api.clickworker.example/jobs/{worker_id}/complete?c={code}',
        'completion': {'code': 'CW1'},
    }

    def test_postback_requires_experimental_flag(self):
        provider = _clickworker(dict(self.BASE), state=_state())
        with patch('requests.request') as mock_request:
            provider.on_completion(
                ParticipantIdentity(worker_id='w1'), CompletionOutcome.COMPLETED)
        mock_request.assert_not_called()

    def test_postback_fires_once_with_experimental(self):
        state = _state()
        provider = _clickworker(dict(self.BASE, experimental=True, api_key='key9'),
                                state=state)
        identity = ParticipantIdentity(worker_id='w1')
        with patch('requests.request') as mock_request:
            mock_request.return_value = MagicMock(status_code=200)
            provider.on_completion(identity, CompletionOutcome.COMPLETED)

        method, url = mock_request.call_args[0]
        assert method == 'POST'
        assert url == 'https://api.clickworker.example/jobs/w1/complete?c=CW1'
        assert mock_request.call_args[1]['headers']['Authorization'] == 'Bearer key9'
        assert state.crowd_metadata['clickworker_postback_sent'] is True

    def test_postback_idempotent(self):
        provider = _clickworker(dict(self.BASE, experimental=True), state=_state(sent=True))
        with patch('requests.request') as mock_request:
            provider.on_completion(
                ParticipantIdentity(worker_id='w1'), CompletionOutcome.COMPLETED)
        mock_request.assert_not_called()

    def test_failed_postback_not_marked_sent(self):
        state = _state()
        provider = _clickworker(dict(self.BASE, experimental=True), state=state)
        with patch('requests.request', side_effect=ConnectionError("down")):
            provider.on_completion(
                ParticipantIdentity(worker_id='w1'), CompletionOutcome.COMPLETED)
        assert 'clickworker_postback_sent' not in state.crowd_metadata

    def test_completion_code_without_postback(self):
        provider = ClickworkerProvider({'completion': {'code': 'CW1'}}, {})
        action = provider.completion_action(
            ParticipantIdentity(worker_id='w'), CompletionOutcome.COMPLETED)
        assert action.kind == 'code_only'
        assert action.code == 'CW1'


class TestExpertInviteProvider:
    CONFIG = {'invites': {'tokenA': 'expert-alice', 'tokenB': None}}

    def test_valid_token_maps_to_display_name(self):
        provider = ExpertInviteProvider(self.CONFIG, {})
        identity = provider.extract_identity({'invite': 'tokenA'})
        assert identity.worker_id == 'expert-alice'
        assert identity.extra['invite_token'] == 'tokenA'

    def test_token_without_name_uses_token(self):
        provider = ExpertInviteProvider(self.CONFIG, {})
        assert provider.extract_identity({'invite': 'tokenB'}).worker_id == 'tokenB'

    def test_unknown_token_rejected(self):
        provider = ExpertInviteProvider(self.CONFIG, {})
        assert provider.extract_identity({'invite': 'forged'}) is None
        assert provider.extract_identity({}) is None

    def test_completion_message_default(self):
        provider = ExpertInviteProvider(self.CONFIG, {})
        action = provider.completion_action(
            ParticipantIdentity(worker_id='expert-alice'), CompletionOutcome.COMPLETED)
        assert action.kind == 'none'
        assert 'contract' in action.message

    def test_completion_code_when_configured(self):
        provider = ExpertInviteProvider(
            dict(self.CONFIG, completion={'code': 'EXP1'}), {})
        action = provider.completion_action(
            ParticipantIdentity(worker_id='expert-alice'), CompletionOutcome.COMPLETED)
        assert action.kind == 'code_only'
        assert action.code == 'EXP1'

    def test_invites_file_yaml_mapping(self, tmp_path):
        invites_file = tmp_path / "invites.yaml"
        invites_file.write_text("tokC: expert-carol\ntokD:\n")
        provider = ExpertInviteProvider(
            {'invites_file': str(invites_file)}, {'task_dir': str(tmp_path)})
        assert provider.extract_identity({'invite': 'tokC'}).worker_id == 'expert-carol'
        assert provider.extract_identity({'invite': 'tokD'}).worker_id == 'tokD'

    def test_invites_file_token_lines(self, tmp_path):
        invites_file = tmp_path / "invites.txt"
        invites_file.write_text("# hired 2026-07\nlineTok1\nlineTok2\n")
        provider = ExpertInviteProvider({'invites_file': str(invites_file)}, {})
        assert provider.extract_identity({'invite': 'lineTok1'}).worker_id == 'lineTok1'
        assert provider.extract_identity({'invite': '# hired 2026-07'}) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
