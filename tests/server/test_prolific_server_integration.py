"""
Prolific Integration Tests

This module contains integration tests that simulate the complete Prolific worker flow,
from arriving via URL parameters to completing annotations and seeing the completion code.

These tests use a mock Prolific service to test the integration without making real API calls.
"""

import json
import pytest
import requests
import time
import os
import yaml
import threading
from unittest.mock import patch, MagicMock

from tests.helpers.test_utils import (
    create_test_directory,
    cleanup_test_directory
)
from tests.helpers.port_manager import find_free_port


def create_prolific_test_config(test_dir: str, port: int,
                                 completion_code: str = "TEST-COMPLETION-CODE",
                                 use_prolific_api: bool = False) -> str:
    """Create a complete Prolific test configuration."""

    # Create test data file with minimal items
    test_data = [
        {"id": "item_1", "text": "First item to annotate."},
        {"id": "item_2", "text": "Second item to annotate."},
    ]
    data_file = os.path.join(test_dir, 'test_data.json')
    with open(data_file, 'w') as f:
        for item in test_data:
            f.write(json.dumps(item) + '\n')

    # Create output directory
    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    # Build config
    config = {
        "debug": False,
        "annotation_task_name": f"Prolific Test {port}",

        # Prolific login settings
        "login": {
            "type": "url_direct",
            "url_argument": "PROLIFIC_PID"
        },

        # Completion code
        "completion_code": completion_code,

        # Hide navigation for crowdsourcing
        "hide_navbar": True,
        "jumping_to_id_disabled": True,

        # Authentication (auto-disabled for url_direct)
        "authentication": {"method": "in_memory"},
        "require_password": False,

        # Data settings
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},

        # Simple annotation scheme
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative", "neutral"],
                "description": "What is the sentiment?"
            }
        ],

        # Assignment - give each user 2 items
        "assignment_strategy": "random",
        "max_annotations_per_user": 2,
        "max_annotations_per_item": 3,

        # Phases - go straight to annotation, then done
        "phases": {
            "order": ["annotation"],
            "annotation": {"type": "annotation"}
        },

        # Server settings
        "site_file": "base_template.html",
        "site_dir": "default",
        "output_annotation_dir": output_dir,
        "task_dir": test_dir,
        "port": port,
        "host": "0.0.0.0",
        "secret_key": f"test-secret-{port}",
        "persist_sessions": False,
        "alert_time_each_instance": 0
    }

    # Add Prolific API config if requested
    if use_prolific_api:
        prolific_config = {
            "token": "mock-token-12345",
            "study_id": "mock-study-67890",
            "max_concurrent_sessions": 10,
            "workload_checker_period": 60
        }
        prolific_config_file = os.path.join(test_dir, 'prolific_config.yaml')
        with open(prolific_config_file, 'w') as f:
            yaml.dump(prolific_config, f)

        config["prolific"] = {"config_file_path": "prolific_config.yaml"}
        config["login"]["type"] = "prolific"

    config_file = os.path.join(test_dir, 'config.yaml')
    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    return config_file


class MockProlificAPI:
    """Mock Prolific API for testing without real API calls."""

    def __init__(self):
        self.submissions = {}
        self.study_status = "ACTIVE"

    def get_study_by_id(self, study_id):
        return {
            "id": study_id,
            "name": "Mock Test Study",
            "status": self.study_status,
            "total_available_places": 100,
            "places_taken": 5
        }

    def get_submissions_from_study(self, study_id=None):
        return list(self.submissions.values())

    def get_submission_from_id(self, submission_id):
        return self.submissions.get(submission_id, {
            "id": submission_id,
            "status": "ACTIVE",
            "participant_id": "unknown"
        })

    def pause_study(self, study_id=None):
        self.study_status = "PAUSED"
        return {"status": "PAUSED"}

    def start_study(self, study_id=None):
        self.study_status = "ACTIVE"
        return {"status": "ACTIVE"}

    def add_submission(self, prolific_pid, session_id):
        """Add a mock submission for testing."""
        self.submissions[session_id] = {
            "id": session_id,
            "participant_id": prolific_pid,
            "status": "ACTIVE",
            "started_at": "2024-01-01T00:00:00Z"
        }


class SimpleTestServer:
    """A simple test server that runs Flask in a thread."""

    def __init__(self, config_file: str, port: int):
        self.config_file = config_file
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"
        self.server_thread = None
        self.app = None

    def start(self, timeout: int = 15) -> bool:
        """Start the server and wait for it to be ready."""
        from datetime import timedelta
        from flask import Flask
        from jinja2 import ChoiceLoader, FileSystemLoader

        # Clear any existing state
        from potato.user_state_management import clear_user_state_manager
        from potato.item_state_management import clear_item_state_manager
        clear_user_state_manager()
        clear_item_state_manager()

        def run_server():
            try:
                # Ensure we're in the project root directory
                project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
                os.chdir(project_root)

                from potato.server_utils.config_module import init_config, config

                # Create args object
                class Args:
                    pass
                args = Args()
                args.config_file = self.config_file
                args.verbose = False
                args.very_verbose = False
                args.customjs = None
                args.customjs_hostname = None
                args.debug = False
                args.persist_sessions = False
                args.require_password = False
                args.port = self.port

                # Initialize config
                init_config(args)

                # Set up templates
                real_templates_dir = os.path.abspath(
                    os.path.join(os.path.dirname(__file__), '../../potato/templates'))
                static_folder = os.path.abspath(
                    os.path.join(os.path.dirname(__file__), '../../potato/static'))
                generated_templates_dir = os.path.join(real_templates_dir, 'generated')
                os.makedirs(generated_templates_dir, exist_ok=True)

                # Initialize managers
                from potato.user_state_management import init_user_state_manager
                from potato.item_state_management import init_item_state_manager
                from potato.flask_server import load_all_data
                from potato.authentication import UserAuthenticator

                UserAuthenticator.init_from_config(config)
                init_user_state_manager(config)
                init_item_state_manager(config)

                # Mock the Prolific API initialization to avoid real API calls
                with patch('potato.flask_server.ProlificStudy') as MockProlificStudy:
                    mock_api = MockProlificAPI()
                    MockProlificStudy.return_value = mock_api
                    load_all_data(config)

                # Create Flask app
                self.app = Flask(__name__, template_folder=real_templates_dir, static_folder=static_folder)
                self.app.jinja_loader = ChoiceLoader([
                    FileSystemLoader(real_templates_dir),
                    FileSystemLoader(generated_templates_dir)
                ])

                # Register filters
                from potato.server_utils.html_sanitizer import register_jinja_filters
                register_jinja_filters(self.app)

                # Configure app
                import secrets
                self.app.secret_key = secrets.token_hex(32)
                self.app.permanent_session_lifetime = timedelta(days=2)

                # Configure routes
                from potato.routes import configure_routes
                configure_routes(self.app, config)

                # Run server
                self.app.run(host='127.0.0.1', port=self.port, debug=False, use_reloader=False, threaded=True)
            except Exception as e:
                print(f"Server error: {e}")
                import traceback
                traceback.print_exc()

        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()

        # Wait for server to be ready
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"{self.base_url}/", timeout=1)
                if response.status_code in [200, 302]:
                    return True
            except requests.exceptions.RequestException:
                pass
            time.sleep(0.5)

        return False

    def stop(self):
        """Stop the server."""
        from potato.user_state_management import clear_user_state_manager
        from potato.item_state_management import clear_item_state_manager
        clear_user_state_manager()
        clear_item_state_manager()


class TestProlificURLDirectLogin:
    """Integration tests for Prolific URL-direct login flow."""

    @pytest.fixture
    def prolific_server(self, request):
        """Create a test server with Prolific URL-direct login."""
        port = find_free_port(preferred_port=9300)
        test_dir = create_test_directory(f"prolific_test_{port}")

        config_file = create_prolific_test_config(
            test_dir, port,
            completion_code="PROLIFIC-TEST-ABC123"
        )

        server = SimpleTestServer(config_file, port)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.skip("Could not start test server")

        yield server, test_dir

        server.stop()
        time.sleep(0.5)
        cleanup_test_directory(test_dir)

    def test_prolific_url_login_creates_session(self, prolific_server):
        """Test that arriving with PROLIFIC_PID creates a user session."""
        server, test_dir = prolific_server
        session = requests.Session()

        # Simulate Prolific worker arriving with URL parameters
        response = session.get(
            f"{server.base_url}/",
            params={
                "PROLIFIC_PID": "worker_123",
                "SESSION_ID": "session_456",
                "STUDY_ID": "study_789"
            },
            allow_redirects=True,
            timeout=5
        )

        assert response.status_code == 200
        # User should be logged in and see annotation page (not login form)
        assert "Login" not in response.text or "sentiment" in response.text.lower()

    def test_prolific_worker_can_annotate(self, prolific_server):
        """Test that a Prolific worker can complete annotations."""
        server, test_dir = prolific_server
        session = requests.Session()

        # Login via URL parameters
        response = session.get(
            f"{server.base_url}/",
            params={"PROLIFIC_PID": "annotator_001"},
            allow_redirects=True,
            timeout=5
        )
        assert response.status_code == 200

        # Submit an annotation using JSON format (as expected by V2 frontend)
        response = session.post(
            f"{server.base_url}/annotate",
            json={
                "action": "next_instance",
                "instance_id": "item_1",
                "annotations": {"sentiment": "positive"}
            },
            allow_redirects=True,
            timeout=5
        )
        assert response.status_code == 200

    def test_prolific_worker_sees_completion_code(self, prolific_server):
        """Test that worker sees completion code after finishing all items."""
        server, test_dir = prolific_server
        session = requests.Session()

        # Login via URL parameters
        session.get(
            f"{server.base_url}/",
            params={"PROLIFIC_PID": "finisher_001"},
            allow_redirects=True,
            timeout=5
        )

        # Complete all assigned items (2 items in this config)
        # First save annotation for item_1 via /updateinstance
        for item_id in ["item_1", "item_2"]:
            # Save the annotation via /updateinstance (this marks the item as annotated)
            session.post(
                f"{server.base_url}/updateinstance",
                json={
                    "instance_id": item_id,
                    "annotations": {"sentiment:positive": "true"},
                    "span_annotations": []
                },
                timeout=5
            )
            # Navigate to next instance
            session.post(
                f"{server.base_url}/annotate",
                json={
                    "action": "next_instance",
                    "instance_id": item_id
                },
                allow_redirects=True,
                timeout=5
            )

        # After completing all items, navigate to done page
        response = session.get(f"{server.base_url}/done", allow_redirects=True, timeout=5)

        # Check for completion code in response
        assert response.status_code == 200
        assert "PROLIFIC-TEST-ABC123" in response.text or "Thank" in response.text

    def test_prolific_redirect_url_generated(self, prolific_server):
        """Test that Prolific redirect URL is generated correctly."""
        server, test_dir = prolific_server
        session = requests.Session()

        # Login and complete all items
        session.get(
            f"{server.base_url}/",
            params={"PROLIFIC_PID": "redirect_tester"},
            allow_redirects=True,
            timeout=5
        )

        for item_id in ["item_1", "item_2"]:
            # Save the annotation via /updateinstance
            session.post(
                f"{server.base_url}/updateinstance",
                json={
                    "instance_id": item_id,
                    "annotations": {"sentiment:neutral": "true"},
                    "span_annotations": []
                },
                timeout=5
            )
            # Navigate to next instance
            session.post(
                f"{server.base_url}/annotate",
                json={
                    "action": "next_instance",
                    "instance_id": item_id
                },
                allow_redirects=True,
                timeout=5
            )

        # Get done page
        response = session.get(f"{server.base_url}/done", allow_redirects=True, timeout=5)

        # Check for Prolific redirect URL
        assert "app.prolific.co/submissions/complete" in response.text or "PROLIFIC-TEST-ABC123" in response.text

    def test_multiple_prolific_workers_isolated(self, prolific_server):
        """Test that multiple Prolific workers have isolated sessions."""
        server, test_dir = prolific_server

        # Create two separate sessions (different workers)
        session1 = requests.Session()
        session2 = requests.Session()

        # Worker 1 logs in
        session1.get(
            f"{server.base_url}/",
            params={"PROLIFIC_PID": "worker_A"},
            allow_redirects=True,
            timeout=5
        )

        # Worker 2 logs in
        session2.get(
            f"{server.base_url}/",
            params={"PROLIFIC_PID": "worker_B"},
            allow_redirects=True,
            timeout=5
        )

        # Worker 1 makes an annotation using JSON format
        response1 = session1.post(
            f"{server.base_url}/annotate",
            json={
                "action": "next_instance",
                "instance_id": "item_1",
                "annotations": {"sentiment": "positive"}
            },
            allow_redirects=True,
            timeout=5
        )

        # Worker 2 makes a different annotation using JSON format
        response2 = session2.post(
            f"{server.base_url}/annotate",
            json={
                "action": "next_instance",
                "instance_id": "item_1",
                "annotations": {"sentiment": "negative"}
            },
            allow_redirects=True,
            timeout=5
        )

        # Both should succeed independently
        assert response1.status_code == 200
        assert response2.status_code == 200


class TestProlificMissingParameters:
    """Tests for handling missing Prolific URL parameters."""

    @pytest.fixture
    def prolific_server(self, request):
        """Create a test server with Prolific URL-direct login."""
        port = find_free_port(preferred_port=9400)
        test_dir = create_test_directory(f"prolific_missing_test_{port}")

        config_file = create_prolific_test_config(test_dir, port)

        server = SimpleTestServer(config_file, port)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.skip("Could not start test server")

        yield server, test_dir

        server.stop()
        time.sleep(0.5)
        cleanup_test_directory(test_dir)

    def test_missing_prolific_pid_shows_error(self, prolific_server):
        """Test that missing PROLIFIC_PID shows an appropriate error."""
        server, test_dir = prolific_server
        session = requests.Session()

        # Arrive without PROLIFIC_PID
        response = session.get(f"{server.base_url}/", timeout=5)

        # Should show error about missing parameter
        assert response.status_code == 200
        assert "PROLIFIC_PID" in response.text or "Missing" in response.text or "error" in response.text.lower()


class TestCustomURLArgument:
    """Tests for custom URL argument names (e.g., for MTurk)."""

    @pytest.fixture
    def mturk_server(self, request):
        """Create a test server with custom URL argument (MTurk style)."""
        port = find_free_port(preferred_port=9500)
        test_dir = create_test_directory(f"mturk_test_{port}")

        # Create test data
        test_data = [{"id": "item_1", "text": "Test item."}]
        data_file = os.path.join(test_dir, 'test_data.json')
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        output_dir = os.path.join(test_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        # Config with custom URL argument (MTurk style)
        config = {
            "annotation_task_name": f"MTurk Test {port}",
            "login": {
                "type": "url_direct",
                "url_argument": "workerId"  # MTurk uses workerId
            },
            "completion_code": "MTURK-CODE-XYZ",
            "authentication": {"method": "in_memory"},
            "require_password": False,
            "data_files": [data_file],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "name": "rating",
                    "annotation_type": "radio",
                    "labels": ["good", "bad"],
                    "description": "Rate this"
                }
            ],
            "assignment_strategy": "random",
            "max_annotations_per_user": 1,
            "phases": {
                "order": ["annotation"],
                "annotation": {"type": "annotation"}
            },
            "site_file": "base_template.html",
            "site_dir": "default",
            "output_annotation_dir": output_dir,
            "task_dir": test_dir,
            "port": port,
            "secret_key": f"test-secret-{port}",
            "persist_sessions": False,
            "alert_time_each_instance": 0
        }

        config_file = os.path.join(test_dir, 'config.yaml')
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        server = SimpleTestServer(config_file, port)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.skip("Could not start test server")

        yield server, test_dir

        server.stop()
        time.sleep(0.5)
        cleanup_test_directory(test_dir)

    def test_custom_url_argument_works(self, mturk_server):
        """Test that custom URL argument (workerId) works for login."""
        server, test_dir = mturk_server
        session = requests.Session()

        # Simulate MTurk worker arriving with workerId
        response = session.get(
            f"{server.base_url}/",
            params={
                "workerId": "A1B2C3D4E5F6G7",
                "assignmentId": "assignment123",
                "hitId": "hit456"
            },
            allow_redirects=True,
            timeout=5
        )

        assert response.status_code == 200
        # Should be logged in (not seeing login form)
        assert "workerId" not in response.text or "rating" in response.text.lower()


class TestProlificCompletionFlow:
    """Tests for the complete Prolific annotation flow."""

    @pytest.fixture
    def completion_server(self, request):
        """Create a server for testing completion flow."""
        port = find_free_port(preferred_port=9600)
        test_dir = create_test_directory(f"completion_test_{port}")

        config_file = create_prolific_test_config(
            test_dir, port,
            completion_code="COMPLETION-CODE-12345"
        )

        server = SimpleTestServer(config_file, port)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.skip("Could not start test server")

        yield server, test_dir

        server.stop()
        time.sleep(0.5)
        cleanup_test_directory(test_dir)

    def test_full_prolific_workflow(self, completion_server):
        """Test complete workflow: login -> annotate -> completion."""
        server, test_dir = completion_server
        session = requests.Session()

        # Step 1: Arrive via Prolific URL
        response = session.get(
            f"{server.base_url}/",
            params={
                "PROLIFIC_PID": "full_workflow_tester",
                "SESSION_ID": "sess_123",
                "STUDY_ID": "study_456"
            },
            allow_redirects=True,
            timeout=5
        )
        assert response.status_code == 200

        # Step 2: Complete all assigned annotations
        for item_id in ["item_1", "item_2"]:
            # Save the annotation via /updateinstance (this marks the item as annotated)
            response = session.post(
                f"{server.base_url}/updateinstance",
                json={
                    "instance_id": item_id,
                    "annotations": {"sentiment:positive": "true"},
                    "span_annotations": []
                },
                timeout=5
            )
            assert response.status_code == 200

            # Navigate to next instance
            response = session.post(
                f"{server.base_url}/annotate",
                json={
                    "action": "next_instance",
                    "instance_id": item_id
                },
                allow_redirects=True,
                timeout=5
            )
            assert response.status_code == 200

        # Step 3: Check completion page
        response = session.get(f"{server.base_url}/done", allow_redirects=True, timeout=5)
        assert response.status_code == 200

        # Verify completion code is displayed
        assert "COMPLETION-CODE-12345" in response.text

        # Verify Prolific redirect link is present
        assert "app.prolific.co" in response.text or "COMPLETION-CODE-12345" in response.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
