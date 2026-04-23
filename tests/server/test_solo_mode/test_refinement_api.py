"""
API integration tests for validated refinement endpoints.

Tests the HTTP endpoints for approval/reject/strategies/log/pending
against a live FlaskTestServer.
"""
import json
import os
import shutil

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


def _create_config_with_require_approval(test_dir, port):
    data_dir = os.path.join(test_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    test_data = [
        {"id": f"a_{i:03d}", "text": f"Test text {i}."} for i in range(30)
    ]
    data_file = os.path.join(data_dir, "test_data.json")
    with open(data_file, 'w') as f:
        json.dump(test_data, f)

    config = {
        'task_dir': '.',
        'port': port,
        'annotation_task_name': 'refinement_api_test',
        'output_annotation_dir': 'annotations',
        'solo_mode': {
            'enabled': True,
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
            'batches': {'llm_labeling_batch': 5, 'max_parallel_labels': 10},
            'state_dir': 'solo_state',
            'refinement_loop': {
                'enabled': True,
                'trigger_interval': 100,
                'refinement_strategy': 'validated_focused_edit',
                'dry_run': False,
                'require_approval': True,
            },
        },
        'data_files': ['data/test_data.json'],
        'item_properties': {'id_key': 'id', 'text_key': 'text'},
        'annotation_schemes': [{
            'name': 'sentiment',
            'description': 'Classify',
            'annotation_type': 'radio',
            'labels': [{'name': 'positive'}, {'name': 'negative'}],
        }],
        'user_config': {'allow_no_password': True},
    }
    config_file = os.path.join(test_dir, "config.yaml")
    with open(config_file, 'w') as f:
        yaml.dump(config, f)
    return config_file


@pytest.fixture(scope="module")
def api_server():
    tests_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    test_dir = os.path.join(tests_dir, "output", "refinement_api_test")
    os.makedirs(test_dir, exist_ok=True)

    port = find_free_port(preferred_port=9350)
    config_file = _create_config_with_require_approval(test_dir, port)
    server = FlaskTestServer(port=port, debug=False, config_file=config_file)

    if not server.start_server():
        pytest.skip("Could not start Flask server")
    server._wait_for_server_ready(timeout=15)
    yield server
    server.stop_server()
    shutil.rmtree(test_dir, ignore_errors=True)


class TestRefinementAPI:
    """Smoke tests for new API endpoints."""

    def test_strategies_endpoint_lists_strategies(self, api_server):
        r = requests.get(f"{api_server.base_url}/solo/api/refinement/strategies")
        assert r.status_code == 200
        data = r.json()
        assert 'strategies' in data
        names = {s['name'] for s in data['strategies']}
        assert 'validated_focused_edit' in names
        assert 'principle_icl' in names
        assert 'hybrid_dual_track' in names

    def test_log_endpoint_returns_empty_initially(self, api_server):
        r = requests.get(f"{api_server.base_url}/solo/api/refinement/log")
        assert r.status_code == 200
        data = r.json()
        assert data['count'] == 0
        assert data['log'] == []

    def test_pending_endpoint_returns_empty_initially(self, api_server):
        r = requests.get(f"{api_server.base_url}/solo/api/refinement/pending")
        assert r.status_code == 200
        data = r.json()
        assert data['count'] == 0

    def test_approve_requires_index(self, api_server):
        r = requests.post(
            f"{api_server.base_url}/solo/api/refinement/approve",
            json={},
        )
        assert r.status_code == 400
        assert 'Missing' in r.json().get('error', '')

    def test_approve_invalid_index(self, api_server):
        r = requests.post(
            f"{api_server.base_url}/solo/api/refinement/approve",
            json={'index': 999},
        )
        # No pending items so index is invalid
        assert r.status_code == 400

    def test_reject_invalid_index(self, api_server):
        r = requests.post(
            f"{api_server.base_url}/solo/api/refinement/reject",
            json={'index': 999},
        )
        assert r.status_code == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
