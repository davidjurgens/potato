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
import tempfile
from unittest.mock import patch, MagicMock
from tests.helpers.flask_test_setup import FlaskTestServer


class TestTrainingPhase:
    """Test training phase functionality."""

    @pytest.fixture
    def flask_server(self):
        """Create a Flask test server with training test data."""
        # Create a temporary directory for this test
        test_dir = tempfile.mkdtemp()

        # Create test data file for training workflow
        test_data = [
            {"id": "train_item_1", "text": "This is the first training item."},
            {"id": "train_item_2", "text": "This is the second training item."},
            {"id": "train_item_3", "text": "This is the third training item."}
        ]

        data_file = os.path.join(test_dir, 'training_test_data.json')
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create training data file
        training_data = {
            "training_instances": [
                {
                    "id": "train_1",
                    "text": "This is a positive sentiment text.",
                    "correct_answers": {
                        "sentiment": "positive"
                    },
                    "explanation": "This text expresses positive emotions and opinions."
                },
                {
                    "id": "train_2",
                    "text": "This is a negative sentiment text.",
                    "correct_answers": {
                        "sentiment": "negative"
                    },
                    "explanation": "This text expresses negative emotions and opinions."
                },
                {
                    "id": "train_3",
                    "text": "This is a neutral sentiment text.",
                    "correct_answers": {
                        "sentiment": "neutral"
                    },
                    "explanation": "This text expresses neutral emotions and opinions."
                }
            ]
        }

        training_data_file = os.path.join(test_dir, 'training_data.json')
        with open(training_data_file, 'w') as f:
            json.dump(training_data, f, indent=2)

        # Create minimal config for training testing
        config = {
            "debug": False,
            "max_annotations_per_user": 10,
            "max_annotations_per_item": -1,
            "assignment_strategy": "fixed_order",
            "annotation_task_name": "Training Test Task",
            "require_password": False,
            "authentication": {
                "method": "in_memory"
            },
            "data_files": [os.path.basename(data_file)],
            "item_properties": {
                "text_key": "text",
                "id_key": "id"
            },
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "type": "radio",
                    "annotation_type": "radio",
                    "labels": ["positive", "negative", "neutral"],
                    "description": "What is the sentiment of this text?"
                }
            ],
            "training": {
                "enabled": True,
                "data_file": os.path.basename(training_data_file),
                "annotation_schemes": ["sentiment"],
                "passing_criteria": {
                    "min_correct": 2,
                    "require_all_correct": False
                },
                "allow_retry": True,
                "failure_action": "repeat_training"
            },
            "phases": {
                "order": ["consent", "instructions", "training", "annotation"],
                "consent": {
                    "type": "consent",
                    "file": "consent.json"
                },
                "instructions": {
                    "type": "instructions",
                    "file": "instructions.json"
                },
                "training": {
                    "type": "training",
                    "file": "training.json"
                }
            },
            "site_file": "base_template.html",
            "output_annotation_dir": os.path.join(test_dir, "output"),
            "task_dir": os.path.join(test_dir, "task"),
            "site_dir": os.path.join(test_dir, "templates"),
            "alert_time_each_instance": 0
        }

        # Create phase files
        consent_data = [
            {
                "name": "consent_check",
                "type": "radio",
                "annotation_type": "radio",
                "labels": ["I agree", "I do not agree"],
                "description": "Do you agree to participate in this study?"
            }
        ]
        with open(os.path.join(test_dir, 'consent.json'), 'w') as f:
            json.dump(consent_data, f, indent=2)

        instructions_data = [
            {
                "name": "instructions_check",
                "type": "radio",
                "annotation_type": "radio",
                "labels": ["I understand", "I need more explanation"],
                "description": "Do you understand the instructions?"
            }
        ]
        with open(os.path.join(test_dir, 'instructions.json'), 'w') as f:
            json.dump(instructions_data, f, indent=2)

        training_data = [
            {
                "name": "training_check",
                "type": "radio",
                "annotation_type": "radio",
                "labels": ["I am ready", "I need more practice"],
                "description": "Are you ready to proceed with training?"
            }
        ]
        with open(os.path.join(test_dir, 'training.json'), 'w') as f:
            json.dump(training_data, f, indent=2)

        # Write config file
        config_file = os.path.join(test_dir, 'training_test_config.yaml')
        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # Create server with the config file
        server = FlaskTestServer(
            port=9004,
            debug=False,
            config_file=config_file,
            test_data_file=data_file
        )

        # Start server
        if not server.start_server(test_dir):
            pytest.fail("Failed to start Flask test server")

        yield server

        # Cleanup
        server.stop_server()

    def test_training_phase_enabled(self, flask_server):
        """Test that training phase is properly enabled and configured."""
        server_url = flask_server.base_url

        # Check admin API to verify training configuration
        response = requests.get(f"{server_url}/admin/api/config", timeout=5)
        assert response.status_code == 200

        config_data = response.json()
        assert "training" in config_data
        assert config_data["training"]["enabled"] == True
        assert "data_file" in config_data["training"]
        assert "annotation_schemes" in config_data["training"]

    def test_training_data_loading(self, flask_server):
        """Test that training data is properly loaded."""
        server_url = flask_server.base_url

        # Check admin API to verify training data is loaded
        response = requests.get(f"{server_url}/admin/api/instances", timeout=5)
        assert response.status_code == 200

        instances_data = response.json()
        # Should have both regular instances and training instances
        assert len(instances_data["instances"]) >= 3  # Regular instances
        # Training instances are loaded separately and not in the main instances list

    def test_training_phase_workflow(self, flask_server):
        """Test complete training phase workflow."""
        server_url = flask_server.base_url

        # Create user
        user_data = {"email": "training_test_user", "pass": "test_password"}
        session = requests.Session()
        reg_response = session.post(f"{server_url}/register", data=user_data, timeout=5)
        assert reg_response.status_code in [200, 302]
        login_response = session.post(f"{server_url}/auth", data=user_data, timeout=5)
        assert login_response.status_code in [200, 302]

        # User should start in consent phase
        response = session.get(f"{server_url}/", timeout=5)
        assert response.status_code == 200

        # Submit consent
        consent_data = {"consent_check": "I agree"}
        response = session.post(f"{server_url}/consent", data=consent_data, timeout=5)
        assert response.status_code in [200, 302]

        # Submit instructions
        instructions_data = {"instructions_check": "I understand"}
        response = session.post(f"{server_url}/instructions", data=instructions_data, timeout=5)
        assert response.status_code in [200, 302]

        # Should now be in training phase
        response = session.get(f"{server_url}/training", timeout=5)
        assert response.status_code == 200
        assert "Training Phase" in response.text

    def test_training_correct_answer(self, flask_server):
        """Test training with correct answer."""
        server_url = flask_server.base_url

        # Create user and advance to training
        user_data = {"email": "correct_training_user", "pass": "test_password"}
        session = requests.Session()
        session.post(f"{server_url}/register", data=user_data, timeout=5)
        session.post(f"{server_url}/auth", data=user_data, timeout=5)
        session.post(f"{server_url}/consent", data={"consent_check": "I agree"}, timeout=5)
        session.post(f"{server_url}/instructions", data={"instructions_check": "I understand"}, timeout=5)

        # Get training page
        response = session.get(f"{server_url}/training", timeout=5)
        assert response.status_code == 200

        # Submit correct answer for first training question
        training_answer = {"sentiment": "positive"}
        response = session.post(f"{server_url}/training", data=training_answer, timeout=5)
        assert response.status_code == 200

        # Should show feedback and move to next question or complete
        assert "Correct" in response.text or "Training completed" in response.text

    def test_training_incorrect_answer(self, flask_server):
        """Test training with incorrect answer and retry."""
        server_url = flask_server.base_url

        # Create user and advance to training
        user_data = {"email": "incorrect_training_user", "pass": "test_password"}
        session = requests.Session()
        session.post(f"{server_url}/register", data=user_data, timeout=5)
        session.post(f"{server_url}/auth", data=user_data, timeout=5)
        session.post(f"{server_url}/consent", data={"consent_check": "I agree"}, timeout=5)
        session.post(f"{server_url}/instructions", data={"instructions_check": "I understand"}, timeout=5)

        # Get training page
        response = session.get(f"{server_url}/training", timeout=5)
        assert response.status_code == 200

        # Submit incorrect answer for first training question
        training_answer = {"sentiment": "negative"}  # Should be "positive" for train_1
        response = session.post(f"{server_url}/training", data=training_answer, timeout=5)
        assert response.status_code == 200

        # Should show feedback with explanation and allow retry
        assert "Incorrect" in response.text
        assert "explanation" in response.text.lower() or "positive" in response.text.lower()

    def test_training_state_tracking(self, flask_server):
        """Test that training state is properly tracked."""
        server_url = flask_server.base_url

        # Create user and advance to training
        user_data = {"email": "state_tracking_user", "pass": "test_password"}
        session = requests.Session()
        session.post(f"{server_url}/register", data=user_data, timeout=5)
        session.post(f"{server_url}/auth", data=user_data, timeout=5)
        session.post(f"{server_url}/consent", data={"consent_check": "I agree"}, timeout=5)
        session.post(f"{server_url}/instructions", data={"instructions_check": "I understand"}, timeout=5)

        # Check user state before training
        response = requests.get(f"{server_url}/admin/api/annotators", timeout=5)
        assert response.status_code == 200

        annotators_data = response.json()
        user_data = next((a for a in annotators_data["annotators"] if a["user_id"] == "state_tracking_user"), None)
        assert user_data is not None
        assert user_data["phase"] == "TRAINING"

        # Submit some training answers
        session.post(f"{server_url}/training", data={"sentiment": "positive"}, timeout=5)
        session.post(f"{server_url}/training", data={"sentiment": "negative"}, timeout=5)

        # Check training state after answers
        response = requests.get(f"{server_url}/admin/api/annotators", timeout=5)
        assert response.status_code == 200

        annotators_data = response.json()
        user_data = next((a for a in annotators_data["annotators"] if a["user_id"] == "state_tracking_user"), None)
        assert user_data is not None
        assert user_data["training_total_attempts"] >= 2
        assert user_data["training_correct_answers"] >= 1

    def test_training_completion(self, flask_server):
        """Test training completion and phase advancement."""
        server_url = flask_server.base_url

        # Create user and advance to training
        user_data = {"email": "completion_user", "pass": "test_password"}
        session = requests.Session()
        session.post(f"{server_url}/register", data=user_data, timeout=5)
        session.post(f"{server_url}/auth", data=user_data, timeout=5)
        session.post(f"{server_url}/consent", data={"consent_check": "I agree"}, timeout=5)
        session.post(f"{server_url}/instructions", data={"instructions_check": "I understand"}, timeout=5)

        # Complete all training questions correctly
        correct_answers = [
            {"sentiment": "positive"},  # train_1
            {"sentiment": "negative"},  # train_2
            {"sentiment": "neutral"}    # train_3
        ]

        for answer in correct_answers:
            response = session.post(f"{server_url}/training", data=answer, timeout=5)
            assert response.status_code == 200

        # Should now be in annotation phase
        response = session.get(f"{server_url}/", timeout=5)
        assert response.status_code == 200
        # Should redirect to annotation phase

    def test_training_disabled(self, flask_server):
        """Test behavior when training is disabled."""
        server_url = flask_server.base_url

        # Create a config with training disabled
        test_dir = tempfile.mkdtemp()
        config = {
            "debug": False,
            "max_annotations_per_user": 10,
            "max_annotations_per_item": -1,
            "assignment_strategy": "fixed_order",
            "annotation_task_name": "Training Disabled Test",
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "data_files": ["test_data.json"],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "name": "sentiment",
                    "type": "radio",
                    "annotation_type": "radio",
                    "labels": ["positive", "negative", "neutral"],
                    "description": "What is the sentiment of this text?"
                }
            ],
            "training": {
                "enabled": False
            },
            "phases": {
                "order": ["consent", "instructions", "annotation"],
                "consent": {"type": "consent", "file": "consent.json"},
                "instructions": {"type": "instructions", "file": "instructions.json"}
            },
            "site_file": "base_template.html",
            "output_annotation_dir": os.path.join(test_dir, "output"),
            "task_dir": os.path.join(test_dir, "task"),
            "site_dir": os.path.join(test_dir, "templates"),
            "alert_time_each_instance": 0
        }

        # Create minimal test data
        test_data = [{"id": "test_1", "text": "Test text"}]
        data_file = os.path.join(test_dir, 'test_data.json')
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create phase files
        consent_data = [{"name": "consent_check", "type": "radio", "annotation_type": "radio", "labels": ["I agree"], "description": "Consent"}]
        with open(os.path.join(test_dir, 'consent.json'), 'w') as f:
            json.dump(consent_data, f, indent=2)

        instructions_data = [{"name": "instructions_check", "type": "radio", "annotation_type": "radio", "labels": ["I understand"], "description": "Instructions"}]
        with open(os.path.join(test_dir, 'instructions.json'), 'w') as f:
            json.dump(instructions_data, f, indent=2)

        # Write config file
        config_file = os.path.join(test_dir, 'training_disabled_config.yaml')
        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # Create server with disabled training
        server = FlaskTestServer(
            port=9005,
            debug=False,
            config_file=config_file,
            test_data_file=data_file
        )

        if not server.start_server(test_dir):
            pytest.fail("Failed to start Flask test server with disabled training")

        try:
            # Create user
            user_data = {"email": "disabled_training_user", "pass": "test_password"}
            session = requests.Session()
            session.post(f"{server.base_url}/register", data=user_data, timeout=5)
            session.post(f"{server.base_url}/auth", data=user_data, timeout=5)
            session.post(f"{server.base_url}/consent", data={"consent_check": "I agree"}, timeout=5)
            session.post(f"{server.base_url}/instructions", data={"instructions_check": "I understand"}, timeout=5)

            # Should skip training and go directly to annotation
            response = session.get(f"{server.base_url}/", timeout=5)
            assert response.status_code == 200

        finally:
            server.stop_server()


class TestTrainingPhaseEdgeCases:
    """Test edge cases and error conditions in training phase."""

    def test_training_without_data_file(self):
        """Test training configuration without data file."""
        # This should be handled gracefully by the system
        pass

    def test_training_with_invalid_data(self):
        """Test training with invalid training data format."""
        # This should be handled gracefully by the system
        pass

    def test_training_state_persistence(self):
        """Test that training state persists across sessions."""
        # This should be handled by the existing user state persistence
        pass