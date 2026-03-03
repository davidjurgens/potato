"""
Integration tests for Solo Mode API endpoints.

Tests the Solo Mode REST API including:
- Status endpoint
- Prompts endpoint
- Predictions endpoint
- Phase control endpoints
- Export functionality
- Page routes (setup, prompt, annotate, status)
"""

import json
import os
import pytest
import requests
import time
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


def _create_solo_mode_test_config(test_dir):
    """Create a Solo Mode config that works without external LLM services."""
    data_dir = os.path.join(test_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    test_data = [
        {"id": f"api_{i:03d}", "text": f"Test text number {i}."}
        for i in range(10)
    ]
    data_file = os.path.join(data_dir, "test_data.json")
    with open(data_file, 'w') as f:
        json.dump(test_data, f)

    config = {
        'task_dir': '.',
        'verbose': True,
        'annotation_task_name': 'solo_api_test',
        'output_annotation_dir': 'annotations',
        'solo_mode': {
            'enabled': True,
            # Dummy model — passes config validation but never used by API tests
            'labeling_models': [{
                'endpoint_type': 'ollama',
                'model': 'test-dummy',
                'endpoint_url': 'http://127.0.0.1:1',
            }],
            'uncertainty': {'strategy': 'direct_confidence'},
            'thresholds': {
                'end_human_annotation_agreement': 0.90,
                'minimum_validation_sample': 3,
            },
            'instance_selection': {
                'low_confidence_weight': 0.4,
                'diversity_weight': 0.3,
                'random_weight': 0.2,
                'disagreement_weight': 0.1,
            },
            'batches': {
                'llm_labeling_batch': 5,
                'max_parallel_labels': 10,
            },
            'state_dir': 'solo_state',
        },
        'data_files': ['data/test_data.json'],
        'item_properties': {'id_key': 'id', 'text_key': 'text'},
        'annotation_schemes': [{
            'name': 'sentiment',
            'description': 'Classify the sentiment',
            'annotation_type': 'radio',
            'labels': [
                {'name': 'positive', 'key_value': '1'},
                {'name': 'negative', 'key_value': '2'},
                {'name': 'neutral', 'key_value': '3'},
            ]
        }],
        'user_config': {'allow_no_password': True},
        'output': {
            'annotation_output_format': 'json',
            'annotation_output_dir': 'annotations',
        },
    }

    config_file = os.path.join(test_dir, "config.yaml")
    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    return config_file


@pytest.fixture(scope="module")
def solo_server():
    """Start a single Flask server with Solo Mode for all tests in the module."""
    tests_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    test_dir = os.path.join(tests_dir, "output", "solo_mode_api_test")
    os.makedirs(test_dir, exist_ok=True)

    config_file = _create_solo_mode_test_config(test_dir)
    port = find_free_port(preferred_port=9200)
    server = FlaskTestServer(port=port, debug=False, config_file=config_file)

    if not server.start_server():
        pytest.skip("Failed to start Flask server for Solo Mode API tests")

    server._wait_for_server_ready(timeout=15)
    yield server
    server.stop_server()

    import shutil
    try:
        shutil.rmtree(test_dir)
    except Exception:
        pass


@pytest.fixture
def authed_session(solo_server):
    """Provide an authenticated requests.Session."""
    session = requests.Session()
    session.post(
        f"{solo_server.base_url}/auth",
        data={"email": f"test_user_{time.time()}", "pass": ""}
    )
    yield session
    session.close()


class TestSoloModeAPIStatus:
    """Tests for /solo/api/status endpoint."""

    def test_returns_json(self, solo_server):
        response = requests.get(f"{solo_server.base_url}/solo/api/status")
        assert response.status_code == 200
        data = response.json()
        assert 'phase' in data
        assert 'phase_name' in data

    def test_contains_annotation_stats(self, solo_server):
        response = requests.get(f"{solo_server.base_url}/solo/api/status")
        assert response.status_code == 200
        data = response.json()
        assert 'annotation_stats' in data
        assert 'agreement_metrics' in data

    def test_contains_llm_stats(self, solo_server):
        data = requests.get(f"{solo_server.base_url}/solo/api/status").json()
        assert 'llm_stats' in data
        assert 'labeled_count' in data['llm_stats']

    def test_contains_validation_progress(self, solo_server):
        data = requests.get(f"{solo_server.base_url}/solo/api/status").json()
        assert 'validation_progress' in data


class TestSoloModeAPIPrompts:
    """Tests for /solo/api/prompts endpoint."""

    def test_returns_prompt_data(self, solo_server):
        response = requests.get(f"{solo_server.base_url}/solo/api/prompts")
        assert response.status_code == 200
        data = response.json()
        assert 'current_prompt' in data
        assert 'history' in data
        assert 'current_version' in data

    def test_history_is_list(self, solo_server):
        data = requests.get(f"{solo_server.base_url}/solo/api/prompts").json()
        assert isinstance(data['history'], list)


class TestSoloModeAPIPredictions:
    """Tests for /solo/api/predictions endpoint."""

    def test_returns_predictions(self, solo_server):
        response = requests.get(f"{solo_server.base_url}/solo/api/predictions")
        assert response.status_code == 200
        data = response.json()
        assert 'count' in data
        assert 'predictions' in data

    def test_predictions_is_dict(self, solo_server):
        data = requests.get(f"{solo_server.base_url}/solo/api/predictions").json()
        assert isinstance(data['predictions'], dict)


class TestSoloModeAPIAdvancePhase:
    """Tests for /solo/api/advance-phase endpoint."""

    def test_get_not_allowed(self, solo_server):
        response = requests.get(f"{solo_server.base_url}/solo/api/advance-phase")
        assert response.status_code == 405

    def test_missing_phase_returns_400(self, solo_server):
        response = requests.post(
            f"{solo_server.base_url}/solo/api/advance-phase",
            json={}
        )
        assert response.status_code == 400
        assert 'error' in response.json()

    def test_invalid_phase_returns_400(self, solo_server):
        response = requests.post(
            f"{solo_server.base_url}/solo/api/advance-phase",
            json={'phase': 'nonexistent_phase'}
        )
        assert response.status_code == 400
        assert 'error' in response.json()


class TestSoloModeAPIDisagreements:
    """Tests for /solo/api/disagreements endpoint."""

    def test_returns_disagreement_data(self, solo_server):
        response = requests.get(f"{solo_server.base_url}/solo/api/disagreements")
        assert response.status_code == 200
        data = response.json()
        assert 'pending' in data
        assert 'resolved' in data


class TestSoloModeAPIEdgeCases:
    """Tests for /solo/api/edge-cases endpoint."""

    def test_returns_edge_case_data(self, solo_server):
        response = requests.get(f"{solo_server.base_url}/solo/api/edge-cases")
        assert response.status_code == 200
        data = response.json()
        assert 'total_edge_cases' in data


class TestSoloModeAPIRules:
    """Tests for /solo/api/rules endpoints."""

    def test_rules_endpoint(self, solo_server):
        response = requests.get(f"{solo_server.base_url}/solo/api/rules")
        assert response.status_code == 200
        data = response.json()
        assert 'rules' in data
        assert 'stats' in data

    def test_rules_categories_endpoint(self, solo_server):
        response = requests.get(f"{solo_server.base_url}/solo/api/rules/categories")
        assert response.status_code == 200
        data = response.json()
        assert 'categories' in data
        assert isinstance(data['categories'], list)


class TestSoloModeAPIConfusionAnalysis:
    """Tests for /solo/api/confusion-analysis endpoint."""

    def test_returns_patterns(self, solo_server):
        response = requests.get(f"{solo_server.base_url}/solo/api/confusion-analysis")
        assert response.status_code == 200
        data = response.json()
        assert 'patterns' in data


class TestSoloModeAPIExport:
    """Tests for /solo/api/export endpoint."""

    def test_returns_export_data(self, solo_server):
        response = requests.get(f"{solo_server.base_url}/solo/api/export")
        assert response.status_code == 200
        data = response.json()
        assert 'phase' in data
        assert 'annotations' in data
        assert 'llm_predictions' in data


class TestSoloModeAPILabeling:
    """Tests for labeling control endpoints."""

    def test_pause_labeling(self, solo_server):
        response = requests.post(f"{solo_server.base_url}/solo/api/pause-labeling")
        # 200 if thread exists, 400 if not
        assert response.status_code in [200, 400]

    def test_resume_labeling(self, solo_server):
        response = requests.post(f"{solo_server.base_url}/solo/api/resume-labeling")
        assert response.status_code in [200, 400]

    def test_start_labeling(self, solo_server):
        response = requests.post(f"{solo_server.base_url}/solo/api/start-labeling")
        assert response.status_code == 200
        data = response.json()
        assert 'success' in data


class TestSoloModePageRoutes:
    """Tests for Solo Mode page routes (require login)."""

    def test_setup_page(self, solo_server, authed_session):
        response = authed_session.get(f"{solo_server.base_url}/solo/setup")
        assert response.status_code == 200

    def test_prompt_page(self, solo_server, authed_session):
        response = authed_session.get(f"{solo_server.base_url}/solo/prompt")
        assert response.status_code == 200

    def test_annotate_page(self, solo_server, authed_session):
        response = authed_session.get(f"{solo_server.base_url}/solo/annotate")
        assert response.status_code == 200

    def test_status_page(self, solo_server, authed_session):
        response = authed_session.get(f"{solo_server.base_url}/solo/status")
        assert response.status_code == 200


class TestSoloModePhaseTransitions:
    """Tests for phase transition via API."""

    def test_initial_phase(self, solo_server):
        data = requests.get(f"{solo_server.base_url}/solo/api/status").json()
        phase = data.get('phase_name', '').upper()
        # Initial phase should be SETUP
        assert 'SETUP' in phase

    def test_transition_to_prompt_review(self, solo_server):
        response = requests.post(
            f"{solo_server.base_url}/solo/api/advance-phase",
            json={'phase': 'prompt_review'}
        )
        # Should succeed or fail with valid transition message
        assert response.status_code in [200, 400]
        data = response.json()
        assert 'success' in data or 'error' in data


class TestSoloModeSetupForm:
    """Tests for setup form submission."""

    def test_setup_post_with_description(self, solo_server, authed_session):
        response = authed_session.post(
            f"{solo_server.base_url}/solo/setup",
            data={'task_description': 'Classify sentiment of product reviews'}
        )
        # Should redirect or return 200
        assert response.status_code in [200, 302]

    def test_prompt_update(self, solo_server, authed_session):
        response = authed_session.post(
            f"{solo_server.base_url}/solo/prompt",
            data={
                'action': 'update',
                'prompt': 'Classify the following text as positive, negative, or neutral.'
            }
        )
        assert response.status_code in [200, 302]


class TestSoloModeDataConsistency:
    """Tests that state is consistent across API calls."""

    def test_status_is_consistent(self, solo_server):
        data1 = requests.get(f"{solo_server.base_url}/solo/api/status").json()
        data2 = requests.get(f"{solo_server.base_url}/solo/api/status").json()
        assert data1['phase'] == data2['phase']

    def test_export_has_required_fields(self, solo_server):
        data = requests.get(f"{solo_server.base_url}/solo/api/export").json()
        assert 'phase' in data
        assert 'annotations' in data
        assert 'llm_predictions' in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
