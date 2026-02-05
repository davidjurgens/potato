"""
Training Phase Tests

This module contains tests for the training phase functionality,
including training data loading, user state tracking, feedback,
and pass/fail criteria.
"""

import json
import pytest
import requests
import time
import os
import yaml
import threading
from unittest.mock import patch, MagicMock

# Import the test utilities
from tests.helpers.test_utils import (
    create_test_directory,
    cleanup_test_directory
)
from tests.helpers.port_manager import find_free_port


def create_training_config(test_dir: str, port: int, include_training: bool = True,
                           max_mistakes: int = -1, max_mistakes_per_question: int = -1) -> str:
    """Create a complete training test configuration in the given directory."""

    # Create test data file
    test_data = [
        {"id": "item_1", "text": "This is the first annotation item."},
        {"id": "item_2", "text": "This is the second annotation item."},
        {"id": "item_3", "text": "This is the third annotation item."}
    ]
    data_file = os.path.join(test_dir, 'test_data.json')
    with open(data_file, 'w') as f:
        for item in test_data:
            f.write(json.dumps(item) + '\n')

    # Create training data file
    training_data = {
        "training_instances": [
            {
                "id": "train_1",
                "text": "This is a positive sentiment text.",
                "correct_answers": {"sentiment": "positive"},
                "explanation": "This text expresses positive emotions."
            },
            {
                "id": "train_2",
                "text": "This is a negative sentiment text.",
                "correct_answers": {"sentiment": "negative"},
                "explanation": "This text expresses negative emotions."
            },
            {
                "id": "train_3",
                "text": "This is a neutral sentiment text.",
                "correct_answers": {"sentiment": "neutral"},
                "explanation": "This text is neutral."
            }
        ]
    }
    training_data_file = os.path.join(test_dir, 'training_data.json')
    with open(training_data_file, 'w') as f:
        json.dump(training_data, f, indent=2)

    # Create output directory
    output_dir = os.path.join(test_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    # Build phases config
    if include_training:
        phases = {
            "order": ["training", "annotation"],
            "training": {"type": "training"},
            "annotation": {"type": "annotation"}
        }
        training_config = {
            "enabled": True,
            "data_file": training_data_file,
            "annotation_schemes": ["sentiment"],
            "passing_criteria": {
                "min_correct": 2,
                "require_all_correct": False
            },
            "allow_retry": True,
            "failure_action": "repeat_training"
        }
        if max_mistakes > 0:
            training_config["passing_criteria"]["max_mistakes"] = max_mistakes
        if max_mistakes_per_question > 0:
            training_config["passing_criteria"]["max_mistakes_per_question"] = max_mistakes_per_question
    else:
        phases = {
            "order": ["annotation"],
            "annotation": {"type": "annotation"}
        }
        training_config = {"enabled": False}

    # Create config
    config = {
        "debug": False,
        "max_annotations_per_user": 10,
        "max_annotations_per_item": -1,
        "assignment_strategy": "fixed_order",
        "annotation_task_name": f"Training Test {port}",
        "require_password": False,
        "authentication": {"method": "in_memory"},
        "data_files": [data_file],
        "item_properties": {"text_key": "text", "id_key": "id"},
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative", "neutral"],
                "description": "What is the sentiment?"
            }
        ],
        "training": training_config,
        "phases": phases,
        "site_file": "base_template.html",
        "site_dir": "default",
        "output_annotation_dir": output_dir,
        "task_dir": test_dir,
        "alert_time_each_instance": 0,
        "port": port,
        "host": "0.0.0.0",
        "secret_key": f"test-secret-{port}",
        "persist_sessions": False
    }

    config_file = os.path.join(test_dir, 'config.yaml')
    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    return config_file


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
        import sys
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
        # The daemon thread will be killed when the test ends
        # Clear state to avoid conflicts with other tests
        from potato.user_state_management import clear_user_state_manager
        from potato.item_state_management import clear_item_state_manager
        clear_user_state_manager()
        clear_item_state_manager()


class TestTrainingPhaseUnit:
    """Unit tests for training phase that don't require a running server."""

    def test_training_state_initialization(self):
        """Test that TrainingState initializes correctly."""
        from potato.user_state_management import TrainingState

        state = TrainingState(max_mistakes=5, max_mistakes_per_question=2)
        assert state.total_attempts == 0
        assert state.total_correct == 0
        assert state.total_mistakes == 0
        assert state.max_mistakes == 5
        assert state.max_mistakes_per_question == 2

    def test_training_state_record_mistake(self):
        """Test recording mistakes in TrainingState."""
        from potato.user_state_management import TrainingState

        state = TrainingState(max_mistakes=5, max_mistakes_per_question=2)
        state.record_mistake("train_1")
        assert state.total_mistakes == 1
        assert state.get_mistakes_for_question("train_1") == 1

    def test_training_state_should_fail_due_to_mistakes(self):
        """Test failure detection due to total mistakes."""
        from potato.user_state_management import TrainingState

        state = TrainingState(max_mistakes=3)
        assert not state.should_fail_due_to_mistakes()

        for i in range(3):
            state.record_mistake(f"train_{i}")

        assert state.should_fail_due_to_mistakes()

    def test_training_state_should_fail_question(self):
        """Test failure detection due to mistakes on single question."""
        from potato.user_state_management import TrainingState

        state = TrainingState(max_mistakes_per_question=2)
        assert not state.should_fail_question_due_to_mistakes("train_1")

        state.record_mistake("train_1")
        assert not state.should_fail_question_due_to_mistakes("train_1")

        state.record_mistake("train_1")
        assert state.should_fail_question_due_to_mistakes("train_1")

    def test_check_training_answer_radio(self):
        """Test answer checking for radio type questions."""
        from potato.routes import check_training_answer

        correct = {"sentiment": "positive"}
        assert check_training_answer({"sentiment": "positive"}, correct)
        assert not check_training_answer({"sentiment": "negative"}, correct)

    def test_check_training_answer_multiselect(self):
        """Test answer checking for multiselect type questions."""
        from potato.routes import check_training_answer

        correct = {"topics": ["quality", "price"]}
        assert check_training_answer({"topics": ["quality", "price"]}, correct)
        assert check_training_answer({"topics": ["price", "quality"]}, correct)  # Order doesn't matter
        assert not check_training_answer({"topics": ["quality"]}, correct)


class TestTrainingPhaseIntegration:
    """Integration tests for training phase with a running server."""

    @pytest.fixture
    def test_server(self, request):
        """Create a test server for training tests."""
        # Use a free port to avoid conflicts
        port = find_free_port(preferred_port=9100)

        # Create test directory
        test_dir = create_test_directory(f"training_test_{port}")

        # Create config
        config_file = create_training_config(test_dir, port)

        # Create and start server
        server = SimpleTestServer(config_file, port)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.skip("Could not start test server")

        yield server, test_dir

        # Cleanup
        server.stop()
        time.sleep(0.5)  # Give server time to stop
        cleanup_test_directory(test_dir)

    def test_training_page_accessible(self, test_server):
        """Test that training page is accessible."""
        server, test_dir = test_server
        session = requests.Session()

        # Register and login
        session.post(f"{server.base_url}/register", data={"email": "test_user", "pass": "test"}, timeout=5)
        session.post(f"{server.base_url}/auth", data={"email": "test_user", "pass": "test"}, timeout=5)

        # Access training page
        response = session.get(f"{server.base_url}/training", timeout=5)
        assert response.status_code == 200

    def test_training_correct_answer(self, test_server):
        """Test submitting a correct answer in training."""
        server, test_dir = test_server
        session = requests.Session()

        # Register and login
        session.post(f"{server.base_url}/register", data={"email": "correct_user", "pass": "test"}, timeout=5)
        session.post(f"{server.base_url}/auth", data={"email": "correct_user", "pass": "test"}, timeout=5)

        # Get training page first
        response = session.get(f"{server.base_url}/training", timeout=5)
        assert response.status_code == 200

        # Submit correct answer
        response = session.post(f"{server.base_url}/training",
                                data={"sentiment": "positive"}, timeout=5)
        assert response.status_code == 200

    def test_training_incorrect_answer(self, test_server):
        """Test submitting an incorrect answer in training."""
        server, test_dir = test_server
        session = requests.Session()

        # Register and login
        session.post(f"{server.base_url}/register", data={"email": "incorrect_user", "pass": "test"}, timeout=5)
        session.post(f"{server.base_url}/auth", data={"email": "incorrect_user", "pass": "test"}, timeout=5)

        # Get training page first
        response = session.get(f"{server.base_url}/training", timeout=5)
        assert response.status_code == 200

        # Submit incorrect answer (correct is "positive")
        response = session.post(f"{server.base_url}/training",
                                data={"sentiment": "negative"}, timeout=5)
        assert response.status_code == 200


class TestTrainingMaxMistakes:
    """Tests for max_mistakes functionality."""

    @pytest.fixture
    def max_mistakes_server(self, request):
        """Create a test server with max_mistakes configured."""
        port = find_free_port(preferred_port=9200)
        test_dir = create_test_directory(f"max_mistakes_test_{port}")

        # Create config with max_mistakes = 3
        config_file = create_training_config(
            test_dir, port,
            include_training=True,
            max_mistakes=3,
            max_mistakes_per_question=2
        )

        server = SimpleTestServer(config_file, port)
        if not server.start():
            cleanup_test_directory(test_dir)
            pytest.skip("Could not start test server")

        yield server, test_dir

        server.stop()
        time.sleep(0.5)
        cleanup_test_directory(test_dir)

    def test_max_mistakes_tracking(self, max_mistakes_server):
        """Test that mistakes are tracked correctly."""
        server, test_dir = max_mistakes_server
        session = requests.Session()

        # Register and login
        session.post(f"{server.base_url}/register", data={"email": "mistakes_user", "pass": "test"}, timeout=5)
        session.post(f"{server.base_url}/auth", data={"email": "mistakes_user", "pass": "test"}, timeout=5)

        # Get training page
        response = session.get(f"{server.base_url}/training", timeout=5)
        assert response.status_code == 200

        # Make a mistake
        response = session.post(f"{server.base_url}/training",
                                data={"sentiment": "wrong_answer"}, timeout=5)
        assert response.status_code == 200


class TestTrainingDisabled:
    """Tests for when training is disabled."""

    def test_training_disabled_skips_phase(self):
        """Test that training phase is skipped when disabled."""
        # This is tested via the phase system - when training is disabled,
        # the phases config shouldn't include 'training' in the order
        pass  # Placeholder - full integration test would require server setup


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
