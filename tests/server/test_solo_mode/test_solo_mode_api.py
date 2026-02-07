"""
Integration tests for Solo Mode API endpoints.

Tests the Solo Mode REST API including:
- Status endpoint
- Prompts endpoint
- Predictions endpoint
- Phase control endpoints
- Export functionality
"""

import json
import os
import pytest
import requests
import time
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


@pytest.mark.skip(reason="Solo Mode server initialization requires additional setup")
class TestSoloModeAPI:
    """Integration tests for Solo Mode API endpoints."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up Flask server with Solo Mode enabled."""
        # Create test directory
        tests_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        test_dir = os.path.join(tests_dir, "output", "solo_mode_api_test")
        os.makedirs(test_dir, exist_ok=True)

        # Create data directory and test data
        data_dir = os.path.join(test_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        test_data = [
            {"id": "api_001", "text": "Great product! Love it."},
            {"id": "api_002", "text": "Terrible. Would not buy again."},
            {"id": "api_003", "text": "It arrived on time."},
        ]
        data_file = os.path.join(data_dir, "test_data.json")
        with open(data_file, 'w') as f:
            json.dump(test_data, f)

        # Create Solo Mode config
        config = {
            'task_dir': '.',
            'verbose': True,
            'annotation_task_name': 'solo_api_test',
            'output_annotation_dir': 'annotations',
            'solo_mode': {
                'enabled': True,
                'labeling_models': [{'endpoint_type': 'ollama', 'model': 'llama3', 'endpoint_url': 'http://localhost:11434'}],
                'revision_models': [{'endpoint_type': 'ollama', 'model': 'llama3', 'endpoint_url': 'http://localhost:11434'}],
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

        # Start server
        port = find_free_port(preferred_port=9200)
        server = FlaskTestServer(port=port, debug=False, config_file=config_file)

        if not server.start_server():
            pytest.fail("Failed to start Flask server for Solo Mode API tests")

        server._wait_for_server_ready(timeout=15)

        # Store for tests
        request.cls.server = server
        request.cls.base_url = f"http://localhost:{port}"
        request.cls.test_dir = test_dir

        yield server

        # Cleanup
        server.stop_server()
        import shutil
        try:
            shutil.rmtree(test_dir)
        except Exception:
            pass

    @pytest.fixture(autouse=True)
    def setup_session(self, flask_server):
        """Set up a session for each test."""
        self.session = requests.Session()

        # Login using the server's actual base_url
        response = self.session.post(
            f"{flask_server.base_url}/auth",
            data={"email": f"api_test_user_{time.time()}", "pass": ""}
        )

        yield

        self.session.close()

    def test_api_status_returns_json(self):
        """Test that /solo/api/status returns valid JSON."""
        response = self.session.get(f"{self.server.base_url}/solo/api/status")

        # Debug: print response if not 200
        if response.status_code != 200:
            print(f"Response status: {response.status_code}")
            print(f"Response text: {response.text}")

        assert response.status_code == 200
        data = response.json()

        assert 'phase' in data
        assert 'phase_name' in data

    def test_api_status_contains_metrics(self):
        """Test that status includes annotation stats and metrics."""
        response = self.session.get(f"{self.server.base_url}/solo/api/status")

        assert response.status_code == 200
        data = response.json()

        # Should have annotation stats
        assert 'annotation_stats' in data
        assert 'agreement_metrics' in data

    def test_api_prompts_endpoint(self):
        """Test that /solo/api/prompts returns prompt data."""
        response = self.session.get(f"{self.server.base_url}/solo/api/prompts")

        assert response.status_code == 200
        data = response.json()

        assert 'current_prompt' in data
        assert 'history' in data

    def test_api_predictions_endpoint(self):
        """Test that /solo/api/predictions returns predictions."""
        response = self.session.get(f"{self.server.base_url}/solo/api/predictions")

        assert response.status_code == 200
        data = response.json()

        assert 'count' in data
        assert 'predictions' in data

    def test_api_disagreements_endpoint(self):
        """Test that /solo/api/disagreements returns data."""
        response = self.session.get(f"{self.server.base_url}/solo/api/disagreements")

        assert response.status_code == 200
        data = response.json()

        assert 'pending' in data
        assert 'resolved' in data

    def test_api_edge_cases_endpoint(self):
        """Test that /solo/api/edge-cases returns data."""
        response = self.session.get(f"{self.server.base_url}/solo/api/edge-cases")

        assert response.status_code == 200
        data = response.json()

        assert 'total_edge_cases' in data

    def test_api_confusion_analysis_endpoint(self):
        """Test that /solo/api/confusion-analysis returns data."""
        response = self.session.get(f"{self.server.base_url}/solo/api/confusion-analysis")

        assert response.status_code == 200
        data = response.json()

        assert 'patterns' in data

    def test_api_export_endpoint(self):
        """Test that /solo/api/export returns export data."""
        response = self.session.get(f"{self.server.base_url}/solo/api/export")

        assert response.status_code == 200
        data = response.json()

        assert 'phase' in data
        assert 'annotations' in data
        assert 'llm_predictions' in data

    def test_api_advance_phase_requires_post(self):
        """Test that advance-phase requires POST method."""
        response = self.session.get(f"{self.server.base_url}/solo/api/advance-phase")

        # Should return 405 Method Not Allowed
        assert response.status_code == 405

    def test_api_advance_phase_requires_phase(self):
        """Test that advance-phase requires phase parameter."""
        response = self.session.post(
            f"{self.server.base_url}/solo/api/advance-phase",
            json={}
        )

        assert response.status_code == 400
        data = response.json()
        assert 'error' in data

    def test_api_advance_phase_rejects_invalid_phase(self):
        """Test that advance-phase rejects invalid phase names."""
        response = self.session.post(
            f"{self.server.base_url}/solo/api/advance-phase",
            json={'phase': 'invalid_phase_name'}
        )

        assert response.status_code == 400
        data = response.json()
        assert 'error' in data

    def test_api_pause_labeling_endpoint(self):
        """Test pause-labeling endpoint."""
        response = self.session.post(f"{self.server.base_url}/solo/api/pause-labeling")

        # Should return 200 or 400 (if no thread running)
        assert response.status_code in [200, 400]
        data = response.json()
        assert 'success' in data or 'error' in data

    def test_api_resume_labeling_endpoint(self):
        """Test resume-labeling endpoint."""
        response = self.session.post(f"{self.server.base_url}/solo/api/resume-labeling")

        # Should return 200 or 400 (if no thread)
        assert response.status_code in [200, 400]
        data = response.json()
        assert 'success' in data or 'error' in data


@pytest.mark.skip(reason="Solo Mode server initialization requires additional setup")
class TestSoloModePhaseTransitions:
    """Integration tests for Solo Mode phase transitions."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up Flask server with Solo Mode enabled."""
        tests_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        test_dir = os.path.join(tests_dir, "output", "solo_mode_phase_test")
        os.makedirs(test_dir, exist_ok=True)

        data_dir = os.path.join(test_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        test_data = [{"id": f"phase_{i}", "text": f"Test text {i}"} for i in range(5)]
        data_file = os.path.join(data_dir, "test_data.json")
        with open(data_file, 'w') as f:
            json.dump(test_data, f)

        config = {
            'task_dir': '.',
            'annotation_task_name': 'solo_phase_test',
            'output_annotation_dir': 'annotations',
            'solo_mode': {
                'enabled': True,
                'labeling_models': [{'endpoint_type': 'ollama', 'model': 'llama3', 'endpoint_url': 'http://localhost:11434'}],
                'revision_models': [{'endpoint_type': 'ollama', 'model': 'llama3', 'endpoint_url': 'http://localhost:11434'}],
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
            },
            'data_files': ['data/test_data.json'],
            'item_properties': {'id_key': 'id', 'text_key': 'text'},
            'annotation_schemes': [{
                'name': 'test',
                'description': 'Test annotation',
                'annotation_type': 'radio',
                'labels': [{'name': 'a'}, {'name': 'b'}]
            }],
            'user_config': {'allow_no_password': True},
            'output': {'annotation_output_format': 'json', 'annotation_output_dir': 'annotations'},
        }

        config_file = os.path.join(test_dir, "config.yaml")
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        port = find_free_port(preferred_port=9201)
        server = FlaskTestServer(port=port, debug=False, config_file=config_file)

        if not server.start_server():
            pytest.fail("Failed to start Flask server")

        server._wait_for_server_ready(timeout=15)

        request.cls.server = server
        request.cls.base_url = f"http://localhost:{port}"
        request.cls.test_dir = test_dir

        yield server

        server.stop_server()
        import shutil
        try:
            shutil.rmtree(test_dir)
        except Exception:
            pass

    @pytest.fixture(autouse=True)
    def setup_session(self):
        """Set up session for each test."""
        self.session = requests.Session()
        self.session.post(
            f"{self.server.base_url}/auth",
            data={"email": f"phase_user_{time.time()}", "pass": ""}
        )
        yield
        self.session.close()

    def test_initial_phase_is_setup(self):
        """Test that initial phase is setup."""
        response = self.session.get(f"{self.server.base_url}/solo/api/status")

        assert response.status_code == 200
        data = response.json()

        # Initial phase should be setup or similar
        phase = data.get('phase', '').lower()
        assert 'setup' in phase or len(phase) > 0

    def test_phase_transition_to_prompt_review(self):
        """Test transitioning to prompt review phase."""
        response = self.session.post(
            f"{self.server.base_url}/solo/api/advance-phase",
            json={'phase': 'prompt_review'}
        )

        # Should succeed or fail with valid transition message
        assert response.status_code in [200, 400]


@pytest.mark.skip(reason="Solo Mode server initialization requires additional setup")
class TestSoloModeFormSubmission:
    """Integration tests for Solo Mode form submissions."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up Flask server with Solo Mode enabled."""
        tests_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        test_dir = os.path.join(tests_dir, "output", "solo_mode_form_test")
        os.makedirs(test_dir, exist_ok=True)

        data_dir = os.path.join(test_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        test_data = [{"id": f"form_{i}", "text": f"Form test {i}"} for i in range(5)]
        data_file = os.path.join(data_dir, "test_data.json")
        with open(data_file, 'w') as f:
            json.dump(test_data, f)

        config = {
            'task_dir': '.',
            'annotation_task_name': 'solo_form_test',
            'output_annotation_dir': 'annotations',
            'solo_mode': {
                'enabled': True,
                'labeling_models': [{'endpoint_type': 'ollama', 'model': 'llama3', 'endpoint_url': 'http://localhost:11434'}],
                'revision_models': [{'endpoint_type': 'ollama', 'model': 'llama3', 'endpoint_url': 'http://localhost:11434'}],
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
            },
            'data_files': ['data/test_data.json'],
            'item_properties': {'id_key': 'id', 'text_key': 'text'},
            'annotation_schemes': [{
                'name': 'test',
                'description': 'Test annotation',
                'annotation_type': 'radio',
                'labels': [{'name': 'label_a'}, {'name': 'label_b'}]
            }],
            'user_config': {'allow_no_password': True},
            'output': {'annotation_output_format': 'json', 'annotation_output_dir': 'annotations'},
        }

        config_file = os.path.join(test_dir, "config.yaml")
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        port = find_free_port(preferred_port=9202)
        server = FlaskTestServer(port=port, debug=False, config_file=config_file)

        if not server.start_server():
            pytest.fail("Failed to start Flask server")

        server._wait_for_server_ready(timeout=15)

        request.cls.server = server
        request.cls.base_url = f"http://localhost:{port}"
        request.cls.test_dir = test_dir

        yield server

        server.stop_server()
        import shutil
        try:
            shutil.rmtree(test_dir)
        except Exception:
            pass

    @pytest.fixture(autouse=True)
    def setup_session(self):
        """Set up session for each test."""
        self.session = requests.Session()
        self.session.post(
            f"{self.server.base_url}/auth",
            data={"email": f"form_user_{time.time()}", "pass": ""}
        )
        yield
        self.session.close()

    def test_setup_page_get(self):
        """Test GET request to setup page."""
        response = self.session.get(f"{self.server.base_url}/solo/setup")

        assert response.status_code == 200
        assert 'Setup' in response.text or 'solo' in response.text.lower()

    def test_setup_form_post(self):
        """Test POST request to setup page with task description."""
        response = self.session.post(
            f"{self.server.base_url}/solo/setup",
            data={'task_description': 'Test task for sentiment classification'}
        )

        # Should redirect or show updated page
        assert response.status_code in [200, 302]

    def test_prompt_page_get(self):
        """Test GET request to prompt editor page."""
        response = self.session.get(f"{self.server.base_url}/solo/prompt")

        assert response.status_code == 200

    def test_prompt_update_post(self):
        """Test updating prompt via POST."""
        response = self.session.post(
            f"{self.server.base_url}/solo/prompt",
            data={
                'action': 'update',
                'prompt': 'Updated test prompt for annotation.'
            }
        )

        # Should return success or redirect
        assert response.status_code in [200, 302]

    def test_annotate_page_get(self):
        """Test GET request to annotate page."""
        response = self.session.get(f"{self.server.base_url}/solo/annotate")

        assert response.status_code == 200

    def test_status_page_get(self):
        """Test GET request to status page."""
        response = self.session.get(f"{self.server.base_url}/solo/status")

        assert response.status_code == 200
        assert 'Status' in response.text or 'phase' in response.text.lower()


@pytest.mark.skip(reason="Solo Mode server initialization requires additional setup")
class TestSoloModeDataPersistence:
    """Integration tests for Solo Mode data persistence."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up Flask server with Solo Mode enabled."""
        tests_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        test_dir = os.path.join(tests_dir, "output", "solo_mode_persist_test")
        os.makedirs(test_dir, exist_ok=True)

        data_dir = os.path.join(test_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        test_data = [{"id": f"persist_{i}", "text": f"Persist test {i}"} for i in range(3)]
        data_file = os.path.join(data_dir, "test_data.json")
        with open(data_file, 'w') as f:
            json.dump(test_data, f)

        config = {
            'task_dir': '.',
            'annotation_task_name': 'solo_persist_test',
            'output_annotation_dir': 'annotations',
            'solo_mode': {
                'enabled': True,
                'labeling_models': [{'endpoint_type': 'ollama', 'model': 'llama3', 'endpoint_url': 'http://localhost:11434'}],
                'revision_models': [{'endpoint_type': 'ollama', 'model': 'llama3', 'endpoint_url': 'http://localhost:11434'}],
                'uncertainty': {'strategy': 'direct_confidence'},
                'thresholds': {
                    'end_human_annotation_agreement': 0.90,
                    'minimum_validation_sample': 2,
                },
                'instance_selection': {
                    'low_confidence_weight': 0.4,
                    'diversity_weight': 0.3,
                    'random_weight': 0.2,
                    'disagreement_weight': 0.1,
                },
                'batches': {'llm_labeling_batch': 5, 'max_parallel_labels': 10},
                'state_dir': 'solo_state',
            },
            'data_files': ['data/test_data.json'],
            'item_properties': {'id_key': 'id', 'text_key': 'text'},
            'annotation_schemes': [{
                'name': 'test',
                'description': 'Test annotation',
                'annotation_type': 'radio',
                'labels': [{'name': 'yes'}, {'name': 'no'}]
            }],
            'user_config': {'allow_no_password': True},
            'output': {'annotation_output_format': 'json', 'annotation_output_dir': 'annotations'},
        }

        config_file = os.path.join(test_dir, "config.yaml")
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        port = find_free_port(preferred_port=9203)
        server = FlaskTestServer(port=port, debug=False, config_file=config_file)

        if not server.start_server():
            pytest.fail("Failed to start Flask server")

        server._wait_for_server_ready(timeout=15)

        request.cls.server = server
        request.cls.base_url = f"http://localhost:{port}"
        request.cls.test_dir = test_dir

        yield server

        server.stop_server()
        import shutil
        try:
            shutil.rmtree(test_dir)
        except Exception:
            pass

    @pytest.fixture(autouse=True)
    def setup_session(self):
        """Set up session for each test."""
        self.session = requests.Session()
        self.session.post(
            f"{self.server.base_url}/auth",
            data={"email": f"persist_user_{time.time()}", "pass": ""}
        )
        yield
        self.session.close()

    def test_export_includes_all_data(self):
        """Test that export endpoint includes complete data."""
        response = self.session.get(f"{self.server.base_url}/solo/api/export")

        assert response.status_code == 200
        data = response.json()

        # Should have all required fields
        assert 'phase' in data
        assert 'annotations' in data
        assert 'llm_predictions' in data
        assert 'disagreements' in data
        assert 'agreement_metrics' in data
        assert 'prompt_history' in data

    def test_status_reflects_state(self):
        """Test that status reflects current state."""
        # Get initial status
        response1 = self.session.get(f"{self.server.base_url}/solo/api/status")
        assert response1.status_code == 200
        data1 = response1.json()

        # Get status again
        response2 = self.session.get(f"{self.server.base_url}/solo/api/status")
        assert response2.status_code == 200
        data2 = response2.json()

        # States should be consistent
        assert data1['phase'] == data2['phase']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
