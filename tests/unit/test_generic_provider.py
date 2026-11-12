"""
Unit tests for the config-driven GenericProvider: URL-parameter capture,
redirect templating, and outcome-to-code mapping.
"""

import pytest

from potato.crowdsourcing import CompletionOutcome, ParticipantIdentity
from potato.crowdsourcing.providers.generic import GenericProvider


def make_provider(provider_config=None, app_config=None):
    return GenericProvider(provider_config or {}, app_config or {})


class TestIdentityCapture:
    def test_custom_id_param(self):
        provider = make_provider({'id_param': 'response_id'})
        identity = provider.extract_identity({'response_id': 'r42'})
        assert identity.worker_id == 'r42'

    def test_missing_id_param(self):
        provider = make_provider({'id_param': 'response_id'})
        assert provider.extract_identity({'other': 'x'}) is None

    def test_capture_params_go_to_extra(self):
        provider = make_provider({
            'id_param': 'response_id',
            'capture_params': ['study', 'session'],
        })
        identity = provider.extract_identity(
            {'response_id': 'r42', 'study': 'st9', 'ignored': 'zzz'})
        assert identity.extra == {'study': 'st9'}

    def test_never_previews(self):
        provider = make_provider()
        assert provider.is_preview({'assignmentId': 'ASSIGNMENT_ID_NOT_AVAILABLE'}) is False


class TestCompletionAction:
    def test_static_code_only(self):
        provider = make_provider({'completion': {'code': 'ABC-1'}})
        action = provider.completion_action(
            ParticipantIdentity(worker_id='w1'), CompletionOutcome.COMPLETED)
        assert action.kind == 'code_only'
        assert action.code == 'ABC-1'

    def test_falls_back_to_app_completion_code(self):
        provider = make_provider({}, {'completion_code': 'TOPLEVEL'})
        action = provider.completion_action(
            ParticipantIdentity(worker_id='w1'), CompletionOutcome.COMPLETED)
        assert action.code == 'TOPLEVEL'

    def test_redirect_url_templating(self):
        provider = make_provider({
            'completion': {
                'code': 'ABC-1',
                'redirect_url': 'https://panel.example/done?rid={worker_id}&c={code}&s={session_id}',
            },
        })
        identity = ParticipantIdentity(worker_id='r42', session_id='sess7')
        action = provider.completion_action(identity, CompletionOutcome.COMPLETED)
        assert action.kind == 'redirect'
        assert action.redirect_url == 'https://panel.example/done?rid=r42&c=ABC-1&s=sess7'

    def test_template_missing_keys_become_empty(self):
        provider = make_provider({
            'completion': {'code': 'C', 'redirect_url': 'https://x.example/{unknown}/{study_id}'},
        })
        action = provider.completion_action(
            ParticipantIdentity(worker_id='w'), CompletionOutcome.COMPLETED)
        assert action.redirect_url == 'https://x.example//'

    def test_failed_code_used_for_failed_checks(self):
        provider = make_provider({'completion': {'code': 'GOOD', 'failed_code': 'BAD'}})
        action = provider.completion_action(
            ParticipantIdentity(worker_id='w'), CompletionOutcome.FAILED_CHECKS)
        assert action.code == 'BAD'

    def test_screened_out_falls_back_to_failed_code(self):
        provider = make_provider({'completion': {'code': 'GOOD', 'failed_code': 'BAD'}})
        action = provider.completion_action(
            ParticipantIdentity(worker_id='w'), CompletionOutcome.SCREENED_OUT)
        assert action.code == 'BAD'

        provider = make_provider({'completion': {
            'code': 'GOOD', 'failed_code': 'BAD', 'screened_out_code': 'SCREEN'}})
        action = provider.completion_action(
            ParticipantIdentity(worker_id='w'), CompletionOutcome.SCREENED_OUT)
        assert action.code == 'SCREEN'

    def test_no_code_no_redirect_is_plain_page(self):
        provider = make_provider({})
        action = provider.completion_action(
            ParticipantIdentity(worker_id='w'), CompletionOutcome.COMPLETED)
        assert action.kind == 'none'

    def test_auto_redirect_settings(self):
        provider = make_provider(
            {'completion': {'code': 'C', 'redirect_url': 'https://x.example/?c={code}',
                            'auto_redirect': True}},
            {'auto_redirect_delay': 1234})
        action = provider.completion_action(
            ParticipantIdentity(worker_id='w'), CompletionOutcome.COMPLETED)
        assert action.auto_redirect is True
        assert action.auto_redirect_delay == 1234

    def test_platform_label(self):
        provider = make_provider({'platform_label': 'Besample'})
        assert provider.platform_label() == 'Besample'
        assert make_provider().platform_label() == 'your crowdsourcing platform'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
