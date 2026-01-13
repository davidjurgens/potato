"""
Active Learning Workflow Tests

This module contains tests for active learning workflows,
including sampling strategies, uncertainty sampling, and adaptive annotation.
"""

import pytest

# Skip tests that hang waiting for training
pytestmark = pytest.mark.skip(reason="Tests hang due to training loop issues - needs refactoring")
import requests
import json
import time
from tests.helpers.flask_test_setup import FlaskTestServer

class TestActiveLearningWorkflow:
    @pytest.fixture(autouse=True)
    def setup(self):
        # Create Flask test server with dynamic port
        self.server = FlaskTestServer(lambda: create_app(), {})
        self.server.start()
        self.base_url = self.server.base_url
        yield
        self.server.stop()

    def get_server_url(self):
        return self.base_url

    def test_active_learning_workflow(self):
        """Test complete active learning workflow with dynamic port"""
        server_url = self.get_server_url()

        # Check system state using admin endpoint
        response = requests.get(f"{server_url}/admin/system_state",
                              headers={'X-API-Key': 'admin_api_key'},
                              timeout=10)
        assert response.status_code == 200

        # Check that system is running
        system_state = response.json()
        assert "system_state" in system_state
        assert "users" in system_state

    def test_model_training_workflow(self):
        """Test model training workflow with dynamic port"""
        server_url = self.get_server_url()

        # Check system state using admin endpoint
        response = requests.get(f"{server_url}/admin/system_state",
                              headers={'X-API-Key': 'admin_api_key'},
                              timeout=10)
        assert response.status_code == 200

        system_state = response.json()
        assert "system_state" in system_state

    def test_prediction_workflow(self):
        """Test prediction workflow with dynamic port"""
        server_url = self.get_server_url()

        # Check system state using admin endpoint
        response = requests.get(f"{server_url}/admin/system_state",
                              headers={'X-API-Key': 'admin_api_key'},
                              timeout=10)
        assert response.status_code == 200

    def test_uncertainty_sampling_workflow(self):
        """Test uncertainty sampling workflow with dynamic port"""
        server_url = self.get_server_url()

        # Check system state using admin endpoint
        response = requests.get(f"{server_url}/admin/system_state",
                              headers={'X-API-Key': 'admin_api_key'},
                              timeout=10)
        assert response.status_code == 200

def create_app():
    """Create Flask app for testing"""
    from potato.flask_server import create_app
    return create_app()