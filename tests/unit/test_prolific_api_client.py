"""
Unit tests for the v2 Prolific API client (potato/crowdsourcing/prolific_api.py).

Every test asserts the CURRENT API model's payload shapes — completion_codes
arrays, filters, transition actions — with all HTTP mocked.
"""

import pytest
from unittest.mock import MagicMock, patch

from potato.crowdsourcing.prolific_api import (
    API_BASE,
    ProlificAPIError,
    ProlificClient,
)


@pytest.fixture
def client():
    return ProlificClient('tok-123')


def ok_response(payload=None, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.content = b'{}'
    response.json.return_value = payload if payload is not None else {}
    return response


class TestPlumbing:
    def test_token_header(self, client):
        assert client.headers == {'Authorization': 'Token tok-123'}

    def test_error_raises_with_payload(self, client):
        response = ok_response({'error': {'detail': 'bad'}}, status_code=400)
        with patch('potato.crowdsourcing.prolific_api.requests.request',
                   return_value=response):
            with pytest.raises(ProlificAPIError) as excinfo:
                client.get_study('s1')
        assert excinfo.value.status_code == 400

    def test_network_error_wrapped(self, client):
        import requests as requests_lib
        with patch('potato.crowdsourcing.prolific_api.requests.request',
                   side_effect=requests_lib.ConnectionError("down")):
            with pytest.raises(ProlificAPIError):
                client.list_studies()


class TestStudies:
    def test_create_study_rejects_legacy_fields(self, client):
        for legacy in ('completion_code', 'failed_attention_code',
                       'eligibility_requirements', 'completion_option'):
            with pytest.raises(ValueError):
                client.create_study({legacy: 'x'})

    def test_create_study_posts_new_model(self, client):
        spec = {
            'name': 'S', 'description': 'd',
            'external_study_url': 'https://x?PROLIFIC_PID={{%PROLIFIC_PID%}}',
            'prolific_id_option': 'url_parameters',
            'completion_codes': [
                {'code': 'C1', 'code_type': 'COMPLETED', 'actor': 'participant',
                 'actions': [{'action': 'AUTOMATICALLY_APPROVE'}]},
                {'code': 'F1', 'code_type': 'FAILED_ATTENTION_CHECK',
                 'actor': 'participant',
                 'actions': [{'action': 'REQUEST_RETURN', 'return_reason': 'failed checks'}]},
            ],
            'total_available_places': 30,
            'estimated_completion_time': 10,
            'reward': 150,
        }
        with patch('potato.crowdsourcing.prolific_api.requests.request',
                   return_value=ok_response({'id': 'new_study'})) as mock_request:
            result = client.create_study(spec)
        method, url = mock_request.call_args[0]
        assert (method, url) == ('POST', f'{API_BASE}/studies/')
        assert mock_request.call_args[1]['json'] == spec
        assert result == {'id': 'new_study'}

    def test_publish_and_stop_are_transitions(self, client):
        with patch('potato.crowdsourcing.prolific_api.requests.request',
                   return_value=ok_response()) as mock_request:
            client.publish_study('s1')
            client.stop_study('s1')
        calls = mock_request.call_args_list
        assert calls[0][0] == ('POST', f'{API_BASE}/studies/s1/transition/')
        assert calls[0][1]['json'] == {'action': 'PUBLISH'}
        assert calls[1][1]['json'] == {'action': 'STOP'}

    def test_increase_places_only_grows(self, client):
        study = {'id': 's1', 'total_available_places': 50}
        with patch('potato.crowdsourcing.prolific_api.requests.request',
                   return_value=ok_response(study)) as mock_request:
            result = client.increase_places('s1', 40)  # below current -> no PATCH
        assert result == study
        assert len(mock_request.call_args_list) == 1  # only the GET

        with patch('potato.crowdsourcing.prolific_api.requests.request',
                   return_value=ok_response(study)) as mock_request:
            client.increase_places('s1', 80)
        patch_call = mock_request.call_args_list[1]
        assert patch_call[0] == ('PATCH', f'{API_BASE}/studies/s1/')
        assert patch_call[1]['json'] == {'total_available_places': 80}


class TestSubmissions:
    def test_approve(self, client):
        with patch('potato.crowdsourcing.prolific_api.requests.request',
                   return_value=ok_response()) as mock_request:
            client.approve_submission('sub1')
        assert mock_request.call_args[0] == \
            ('POST', f'{API_BASE}/submissions/sub1/transition/')
        assert mock_request.call_args[1]['json'] == {'action': 'APPROVE'}

    def test_reject_requires_100_char_message(self, client):
        with pytest.raises(ValueError):
            client.reject_submission('sub1', 'too short', 'LOW_EFFORT')

        long_message = 'x' * 120
        with patch('potato.crowdsourcing.prolific_api.requests.request',
                   return_value=ok_response()) as mock_request:
            client.reject_submission('sub1', long_message, 'FAILED_CHECK')
        body = mock_request.call_args[1]['json']
        assert body == {'action': 'REJECT', 'message': long_message,
                        'rejection_category': 'FAILED_CHECK'}

    def test_bulk_approve(self, client):
        with patch('potato.crowdsourcing.prolific_api.requests.request',
                   return_value=ok_response()) as mock_request:
            client.bulk_approve('s1', ['a', 'b'])
        assert mock_request.call_args[0] == \
            ('POST', f'{API_BASE}/submissions/bulk-approve/')
        assert mock_request.call_args[1]['json'] == \
            {'study_id': 's1', 'submission_ids': ['a', 'b']}

    def test_screen_out(self, client):
        with patch('potato.crowdsourcing.prolific_api.requests.request',
                   return_value=ok_response()) as mock_request:
            client.screen_out_submissions('s1', ['sub9'], increase_places=True)
        assert mock_request.call_args[0] == \
            ('POST', f'{API_BASE}/studies/s1/screen-out-submissions/')
        assert mock_request.call_args[1]['json'] == \
            {'submission_ids': ['sub9'], 'increase_places': True}


class TestBonusesGroupsMisc:
    def test_bonus_setup_csv_format(self, client):
        with patch('potato.crowdsourcing.prolific_api.requests.request',
                   return_value=ok_response({'id': 'bulk1'})) as mock_request:
            client.set_up_bonuses('s1', [('p1', 1.5), ('p2', 0.75)])
        body = mock_request.call_args[1]['json']
        assert body == {'study_id': 's1', 'csv_bonuses': 'p1,1.5\np2,0.75'}

    def test_pay_bonuses(self, client):
        with patch('potato.crowdsourcing.prolific_api.requests.request',
                   return_value=ok_response()) as mock_request:
            client.pay_bonuses('bulk1')
        assert mock_request.call_args[0] == \
            ('POST', f'{API_BASE}/bulk-bonus-payments/bulk1/pay/')

    def test_participant_group_lifecycle(self, client):
        with patch('potato.crowdsourcing.prolific_api.requests.request',
                   return_value=ok_response({'id': 'g1'})) as mock_request:
            client.create_participant_group('proj1', 'annotated-wave-1')
            client.add_to_group('g1', ['p1', 'p2'])
            client.remove_from_group('g1', ['p1'])
        calls = mock_request.call_args_list
        assert calls[0][0] == ('POST', f'{API_BASE}/participant-groups/')
        assert calls[1][0] == ('POST', f'{API_BASE}/participant-groups/g1/participants/')
        assert calls[1][1]['json'] == {'participant_ids': ['p1', 'p2']}
        assert calls[2][0] == ('DELETE', f'{API_BASE}/participant-groups/g1/participants/')

    def test_cost_calculator(self, client):
        with patch('potato.crowdsourcing.prolific_api.requests.request',
                   return_value=ok_response()) as mock_request:
            client.calculate_cost(150, 30)
        assert mock_request.call_args[0] == ('POST', f'{API_BASE}/study-cost-calculator/')
        assert mock_request.call_args[1]['json'] == \
            {'reward': 150, 'total_available_places': 30}

    def test_test_participant_flow(self, client):
        with patch('potato.crowdsourcing.prolific_api.requests.request',
                   return_value=ok_response()) as mock_request:
            client.create_test_participant()
            client.make_test_study('s1')
        calls = mock_request.call_args_list
        assert calls[0][0] == ('POST', f'{API_BASE}/researchers/participants/')
        assert calls[1][0] == ('POST', f'{API_BASE}/studies/s1/test-study')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
