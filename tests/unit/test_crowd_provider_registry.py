"""
Unit tests for the crowd-provider registry and resolution order.

The resolution contract (potato/crowdsourcing/registry.py):
1. explicit crowdsourcing.provider -> that provider class
2. login.type url_direct/prolific  -> LegacyUrlDirectProvider
3. otherwise                       -> None
"""

import pytest

from potato.crowdsourcing import (
    clear_crowd_provider,
    get_crowd_provider,
    get_supported_providers,
    init_crowd_provider,
)
from potato.crowdsourcing.providers.generic import GenericProvider
from potato.crowdsourcing.providers.legacy import LegacyUrlDirectProvider
from potato.crowdsourcing.providers.mturk import MTurkProvider
from potato.crowdsourcing.providers.prolific import ProlificProvider


@pytest.fixture(autouse=True)
def reset_singleton():
    clear_crowd_provider()
    yield
    clear_crowd_provider()


class TestResolutionOrder:
    def test_explicit_provider_wins(self):
        config = {
            'crowdsourcing': {'provider': 'generic', 'generic': {'id_param': 'pid'}},
            'login': {'type': 'url_direct'},
        }
        provider = init_crowd_provider(config)
        assert isinstance(provider, GenericProvider)
        assert provider.id_param() == 'pid'

    def test_explicit_prolific_provider(self):
        provider = init_crowd_provider({'crowdsourcing': {'provider': 'prolific'}})
        assert isinstance(provider, ProlificProvider)

    def test_explicit_mturk_provider(self):
        provider = init_crowd_provider({'crowdsourcing': {'provider': 'mturk'}})
        assert isinstance(provider, MTurkProvider)
        assert provider.id_param() == 'workerId'

    def test_legacy_url_direct_login(self):
        config = {'login': {'type': 'url_direct', 'url_argument': 'workerId'}}
        provider = init_crowd_provider(config)
        assert isinstance(provider, LegacyUrlDirectProvider)
        assert provider.id_param() == 'workerId'

    def test_legacy_prolific_login(self):
        provider = init_crowd_provider({'login': {'type': 'prolific'}})
        assert isinstance(provider, LegacyUrlDirectProvider)
        assert provider.id_param() == 'PROLIFIC_PID'

    def test_standard_login_gets_no_provider(self):
        assert init_crowd_provider({'login': {'type': 'standard'}}) is None
        assert init_crowd_provider({}) is None

    def test_unknown_provider_name(self):
        provider = init_crowd_provider({'crowdsourcing': {'provider': 'doesnotexist'}})
        assert provider is None

    def test_singleton_roundtrip(self):
        init_crowd_provider({'login': {'type': 'url_direct'}})
        assert isinstance(get_crowd_provider(), LegacyUrlDirectProvider)
        clear_crowd_provider()
        assert get_crowd_provider() is None

    def test_supported_providers_listed(self):
        supported = get_supported_providers()
        for name in ('generic', 'prolific', 'mturk', 'url_direct'):
            assert name in supported


class TestLegacyProviderBehavior:
    """The legacy provider must reproduce the historical dual-platform quirks."""

    def _provider(self, url_argument='PROLIFIC_PID', **app_config):
        config = {'login': {'type': 'url_direct', 'url_argument': url_argument}}
        config.update(app_config)
        return LegacyUrlDirectProvider({}, config)

    def test_captures_prolific_and_mturk_params_together(self):
        provider = self._provider()
        identity = provider.extract_identity({
            'PROLIFIC_PID': 'worker1', 'SESSION_ID': 's1', 'STUDY_ID': 'st1',
            'assignmentId': 'a1', 'hitId': 'h1', 'turkSubmitTo': 'https://www.mturk.com',
        })
        assert identity.worker_id == 'worker1'
        assert identity.session_id == 's1'
        assert identity.study_id == 'st1'
        assert identity.extra['assignmentId'] == 'a1'
        assert identity.extra['turkSubmitTo'] == 'https://www.mturk.com'

    def test_missing_id_param_returns_none(self):
        provider = self._provider(url_argument='workerId')
        assert provider.extract_identity({'PROLIFIC_PID': 'x'}) is None

    def test_mturk_preview_detected(self):
        provider = self._provider(url_argument='workerId')
        assert provider.is_preview({'assignmentId': 'ASSIGNMENT_ID_NOT_AVAILABLE'})
        assert not provider.is_preview({'assignmentId': 'real_assignment'})
        assert not provider.is_preview({})

    def test_mturk_completion_takes_priority(self):
        """With turkSubmitTo present, the done page must POST to MTurk even
        when the url_argument is PROLIFIC_PID (dual-platform config)."""
        from potato.crowdsourcing import CompletionOutcome, ParticipantIdentity
        provider = self._provider(completion_code='CODE1')
        identity = ParticipantIdentity(
            worker_id='w1',
            extra={'assignmentId': 'a1', 'turkSubmitTo': 'https://www.mturk.com'})
        action = provider.completion_action(identity, CompletionOutcome.COMPLETED)
        assert action.kind == 'post_form'
        assert action.form_action == 'https://www.mturk.com/mturk/externalSubmit'
        assert action.form_fields == {'assignmentId': 'a1', 'completionCode': 'CODE1'}

    def test_prolific_redirect_only_for_prolific_pid_argument(self):
        from potato.crowdsourcing import CompletionOutcome, ParticipantIdentity
        identity = ParticipantIdentity(worker_id='w1')

        prolific = self._provider(completion_code='CODE1')
        action = prolific.completion_action(identity, CompletionOutcome.COMPLETED)
        assert action.kind == 'redirect'
        assert action.redirect_url == 'https://app.prolific.com/submissions/complete?cc=CODE1'
        assert action.platform_label == 'Prolific'

        custom = self._provider(url_argument='participantId', completion_code='CODE1')
        action = custom.completion_action(identity, CompletionOutcome.COMPLETED)
        assert action.kind == 'code_only'

    def test_prolific_pid_argument_is_case_insensitive(self):
        from potato.crowdsourcing import CompletionOutcome, ParticipantIdentity
        provider = self._provider(url_argument='prolific_pid', completion_code='CODE1')
        action = provider.completion_action(
            ParticipantIdentity(worker_id='w1'), CompletionOutcome.COMPLETED)
        assert action.kind == 'redirect'

    def test_no_completion_code_renders_plain_page(self):
        from potato.crowdsourcing import CompletionOutcome, ParticipantIdentity
        provider = self._provider()
        action = provider.completion_action(
            ParticipantIdentity(worker_id='w1'), CompletionOutcome.COMPLETED)
        assert action.kind == 'none'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
