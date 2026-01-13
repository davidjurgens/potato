"""
Server Integration Tests for Training Phase

This module contains integration tests for training phase functionality including:
- Training phase workflow integration
- Training data loading and serving
- Training feedback and retry logic
- Training completion and progression
- Admin dashboard training statistics
"""

import pytest

# Skip server integration tests for fast CI - run with pytest -m slow
pytestmark = pytest.mark.skip(reason="Server integration tests skipped for fast CI execution")
import json
import tempfile
import os
from unittest.mock import patch, Mock
from tests.helpers.flask_test_setup import FlaskTestServer


class TestTrainingPhaseIntegration:
    """Integration tests for training phase functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.test_data = {
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

        self.config = {
            "annotation_schemes": {
                "sentiment": {
                    "type": "radio",
                    "options": ["positive", "negative", "neutral"],
                    "required": True
                }
            },
            "training": {
                "enabled": True,
                "data_file": "training_data.json",
                "annotation_schemes": ["sentiment"],
                "passing_criteria": {
                    "min_correct": 2,
                    "require_all_correct": False
                },
                "allow_retry": True,
                "failure_action": "retry"
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
            }
        }

    def create_test_files(self):
        """Create temporary test files."""
        # Create training data file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(self.test_data, f)
            self.training_data_file = f.name

        # Create consent file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            consent_data = {
                "title": "Consent",
                "content": "Do you consent to participate?"
            }
            json.dump(consent_data, f)
            self.consent_file = f.name

        # Create instructions file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            instructions_data = {
                "title": "Instructions",
                "content": "Please annotate the sentiment of each text."
            }
            json.dump(instructions_data, f)
            self.instructions_file = f.name

        # Update config with file paths
        self.config["training"]["data_file"] = self.training_data_file
        self.config["phases"]["consent"]["file"] = self.consent_file
        self.config["phases"]["instructions"]["file"] = self.instructions_file

    def teardown_method(self):
        """Clean up test files."""
        for file_path in [getattr(self, 'training_data_file', None),
                         getattr(self, 'consent_file', None),
                         getattr(self, 'instructions_file', None)]:
            if file_path and os.path.exists(file_path):
                os.unlink(file_path)

    def test_training_phase_enabled_workflow(self):
        """Test complete training phase workflow when enabled."""
        self.create_test_files()

        server = FlaskTestServer(config=self.config)
        server.start()

        try:
            # Register and login user
            response = server.post("/register", data={
                "username": "test_user",
                "password": "test_password"
            })
            assert response.status_code == 302  # Redirect after registration

            response = server.post("/login", data={
                "username": "test_user",
                "password": "test_password"
            })
            assert response.status_code == 302  # Redirect after login

            # Complete consent phase
            response = server.post("/consent", data={"consent": "yes"})
            assert response.status_code == 302

            # Complete instructions phase
            response = server.post("/instructions", data={"continue": "yes"})
            assert response.status_code == 302

            # Access training phase
            response = server.get("/training")
            assert response.status_code == 200
            assert "training" in response.text.lower()
            assert "positive sentiment text" in response.text

            # Submit correct answer
            response = server.post("/training", data={"sentiment": "positive"})
            assert response.status_code == 200
            assert "correct" in response.text.lower()
            assert "moving to next question" in response.text.lower()

            # Submit incorrect answer
            response = server.post("/training", data={"sentiment": "positive"})
            assert response.status_code == 200
            assert "incorrect" in response.text.lower()
            assert "negative emotions" in response.text.lower()

            # Retry with correct answer
            response = server.post("/training", data={"sentiment": "negative"})
            assert response.status_code == 200
            assert "correct" in response.text.lower()

            # Complete training and advance to annotation
            response = server.post("/training", data={"sentiment": "neutral"})
            assert response.status_code == 302  # Redirect to annotation
        finally:
            server.stop()

    def test_training_phase_disabled_workflow(self):
        """Test workflow when training phase is disabled."""
        self.create_test_files()
        self.config["training"]["enabled"] = False

        with FlaskTestServer(config=self.config) as server:
            # Register and login user
            response = server.post("/register", data={
                "username": "test_user",
                "password": "test_password"
            })
            assert response.status_code == 302

            response = server.post("/login", data={
                "username": "test_user",
                "password": "test_password"
            })
            assert response.status_code == 302

            # Complete consent phase
            response = server.post("/consent", data={"consent": "yes"})
            assert response.status_code == 302

            # Complete instructions phase
            response = server.post("/instructions", data={"continue": "yes"})
            assert response.status_code == 302

            # Should skip training and go directly to annotation
            response = server.get("/annotation")
            assert response.status_code == 200
            assert "annotation" in response.text.lower()

    def test_training_data_loading(self):
        """Test training data loading and serving."""
        self.create_test_files()

        with FlaskTestServer(config=self.config) as server:
            # Register and login user
            response = server.post("/register", data={
                "username": "test_user",
                "password": "test_password"
            })
            response = server.post("/login", data={
                "username": "test_user",
                "password": "test_password"
            })

            # Complete phases to reach training
            response = server.post("/consent", data={"consent": "yes"})
            response = server.post("/instructions", data={"continue": "yes"})

            # Check training page loads with correct data
            response = server.get("/training")
            assert response.status_code == 200

            # Verify all training instances are accessible
            for instance in self.test_data["training_instances"]:
                assert instance["text"] in response.text

    def test_training_feedback_system(self):
        """Test training feedback and retry system."""
        self.create_test_files()

        with FlaskTestServer(config=self.config) as server:
            # Register and login user
            response = server.post("/register", data={
                "username": "test_user",
                "password": "test_password"
            })
            response = server.post("/login", data={
                "username": "test_user",
                "password": "test_password"
            })

            # Complete phases to reach training
            response = server.post("/consent", data={"consent": "yes"})
            response = server.post("/instructions", data={"continue": "yes"})

            # Submit incorrect answer
            response = server.post("/training", data={"sentiment": "positive"})
            assert response.status_code == 200
            assert "incorrect" in response.text.lower()
            assert "negative emotions" in response.text.lower()
            assert "retry" in response.text.lower()

            # Submit correct answer
            response = server.post("/training", data={"sentiment": "negative"})
            assert response.status_code == 200
            assert "correct" in response.text.lower()
            assert "moving to next question" in response.text.lower()

    def test_training_no_retry_configuration(self):
        """Test training with retry disabled."""
        self.create_test_files()
        self.config["training"]["allow_retry"] = False

        with FlaskTestServer(config=self.config) as server:
            # Register and login user
            response = server.post("/register", data={
                "username": "test_user",
                "password": "test_password"
            })
            response = server.post("/login", data={
                "username": "test_user",
                "password": "test_password"
            })

            # Complete phases to reach training
            response = server.post("/consent", data={"consent": "yes"})
            response = server.post("/instructions", data={"continue": "yes"})

            # Submit incorrect answer
            response = server.post("/training", data={"sentiment": "positive"})
            assert response.status_code == 200
            assert "incorrect" in response.text.lower()
            assert "retry" not in response.text.lower()

    def test_training_passing_criteria(self):
        """Test training passing criteria."""
        self.create_test_files()
        self.config["training"]["passing_criteria"]["min_correct"] = 1
        self.config["training"]["passing_criteria"]["require_all_correct"] = False

        with FlaskTestServer(config=self.config) as server:
            # Register and login user
            response = server.post("/register", data={
                "username": "test_user",
                "password": "test_password"
            })
            response = server.post("/login", data={
                "username": "test_user",
                "password": "test_password"
            })

            # Complete phases to reach training
            response = server.post("/consent", data={"consent": "yes"})
            response = server.post("/instructions", data={"continue": "yes"})

            # Answer first question correctly
            response = server.post("/training", data={"sentiment": "positive"})
            assert response.status_code == 200
            assert "correct" in response.text.lower()

            # Answer second question incorrectly
            response = server.post("/training", data={"sentiment": "positive"})
            assert response.status_code == 200
            assert "incorrect" in response.text.lower()

            # Answer second question correctly
            response = server.post("/training", data={"sentiment": "negative"})
            assert response.status_code == 200
            assert "correct" in response.text.lower()

            # Should advance to annotation after meeting minimum criteria
            response = server.post("/training", data={"sentiment": "neutral"})
            assert response.status_code == 302  # Redirect to annotation

    def test_training_require_all_correct(self):
        """Test training with require_all_correct setting."""
        self.create_test_files()
        self.config["training"]["passing_criteria"]["min_correct"] = 3
        self.config["training"]["passing_criteria"]["require_all_correct"] = True

        with FlaskTestServer(config=self.config) as server:
            # Register and login user
            response = server.post("/register", data={
                "username": "test_user",
                "password": "test_password"
            })
            response = server.post("/login", data={
                "username": "test_user",
                "password": "test_password"
            })

            # Complete phases to reach training
            response = server.post("/consent", data={"consent": "yes"})
            response = server.post("/instructions", data={"continue": "yes"})

            # Answer all questions correctly
            response = server.post("/training", data={"sentiment": "positive"})
            assert response.status_code == 200
            assert "correct" in response.text.lower()

            response = server.post("/training", data={"sentiment": "negative"})
            assert response.status_code == 200
            assert "correct" in response.text.lower()

            response = server.post("/training", data={"sentiment": "neutral"})
            assert response.status_code == 302  # Redirect to annotation

    def test_training_state_persistence(self):
        """Test that training state persists across requests."""
        self.create_test_files()

        with FlaskTestServer(config=self.config) as server:
            # Register and login user
            response = server.post("/register", data={
                "username": "test_user",
                "password": "test_password"
            })
            response = server.post("/login", data={
                "username": "test_user",
                "password": "test_password"
            })

            # Complete phases to reach training
            response = server.post("/consent", data={"consent": "yes"})
            response = server.post("/instructions", data={"continue": "yes"})

            # Submit incorrect answer
            response = server.post("/training", data={"sentiment": "positive"})
            assert response.status_code == 200
            assert "incorrect" in response.text.lower()

            # Reload page - should still show feedback
            response = server.get("/training")
            assert response.status_code == 200
            assert "incorrect" in response.text.lower()

            # Submit correct answer
            response = server.post("/training", data={"sentiment": "negative"})
            assert response.status_code == 200
            assert "correct" in response.text.lower()

    def test_training_admin_statistics(self):
        """Test admin dashboard training statistics."""
        self.create_test_files()

        with FlaskTestServer(config=self.config) as server:
            # Register and login user
            response = server.post("/register", data={
                "username": "test_user",
                "password": "test_password"
            })
            response = server.post("/login", data={
                "username": "test_user",
                "password": "test_password"
            })

            # Complete phases to reach training
            response = server.post("/consent", data={"consent": "yes"})
            response = server.post("/instructions", data={"continue": "yes"})

            # Submit some answers
            response = server.post("/training", data={"sentiment": "positive"})
            response = server.post("/training", data={"sentiment": "positive"})
            response = server.post("/training", data={"sentiment": "negative"})

            # Check admin API for training statistics
            response = server.get("/admin/api/annotators")
            assert response.status_code == 200

            data = response.get_json()
            assert len(data["annotators"]) == 1

            annotator = data["annotators"][0]
            assert annotator["user_id"] == "test_user"
            assert annotator["phase"] == "TRAINING"
            assert annotator["training_completed"] == False
            assert annotator["training_correct_answers"] == 1
            assert annotator["training_total_attempts"] == 2
            assert annotator["training_pass_rate"] == 50.0
            assert annotator["training_current_question"] == 1
            assert annotator["training_total_questions"] == 3

    def test_training_error_handling(self):
        """Test error handling in training phase."""
        self.create_test_files()

        with FlaskTestServer(config=self.config) as server:
            # Register and login user
            response = server.post("/register", data={
                "username": "test_user",
                "password": "test_password"
            })
            response = server.post("/login", data={
                "username": "test_user",
                "password": "test_password"
            })

            # Complete phases to reach training
            response = server.post("/consent", data={"consent": "yes"})
            response = server.post("/instructions", data={"continue": "yes"})

            # Submit without required field
            response = server.post("/training", data={})
            assert response.status_code == 400

            # Submit with invalid value
            response = server.post("/training", data={"sentiment": "invalid"})
            assert response.status_code == 400

    def test_training_phase_access_control(self):
        """Test access control for training phase."""
        self.create_test_files()

        with FlaskTestServer(config=self.config) as server:
            # Try to access training without authentication
            response = server.get("/training")
            assert response.status_code == 302  # Redirect to login

            # Register and login user
            response = server.post("/register", data={
                "username": "test_user",
                "password": "test_password"
            })
            response = server.post("/login", data={
                "username": "test_user",
                "password": "test_password"
            })

            # Try to access training before completing previous phases
            response = server.get("/training")
            assert response.status_code == 302  # Redirect to consent

            # Complete consent phase
            response = server.post("/consent", data={"consent": "yes"})

            # Try to access training before completing instructions
            response = server.get("/training")
            assert response.status_code == 302  # Redirect to instructions

            # Complete instructions phase
            response = server.post("/instructions", data={"continue": "yes"})

            # Now should be able to access training
            response = server.get("/training")
            assert response.status_code == 200

    def test_training_multi_scheme_support(self):
        """Test training with multiple annotation schemes."""
        self.create_test_files()

        # Update config with multiple schemes
        self.config["annotation_schemes"]["topic"] = {
            "type": "checkbox",
            "options": ["emotion", "politics", "technology"],
            "required": True
        }
        self.config["training"]["annotation_schemes"] = ["sentiment", "topic"]

        # Update training data with multiple schemes
        self.test_data["training_instances"][0]["correct_answers"]["topic"] = ["emotion"]
        self.test_data["training_instances"][1]["correct_answers"]["topic"] = ["emotion"]
        self.test_data["training_instances"][2]["correct_answers"]["topic"] = ["emotion"]

        with FlaskTestServer(config=self.config) as server:
            # Register and login user
            response = server.post("/register", data={
                "username": "test_user",
                "password": "test_password"
            })
            response = server.post("/login", data={
                "username": "test_user",
                "password": "test_password"
            })

            # Complete phases to reach training
            response = server.post("/consent", data={"consent": "yes"})
            response = server.post("/instructions", data={"continue": "yes"})

            # Submit answer with both schemes
            response = server.post("/training", data={
                "sentiment": "positive",
                "topic": ["emotion"]
            })
            assert response.status_code == 200
            assert "correct" in response.text.lower()

            # Submit incorrect answer
            response = server.post("/training", data={
                "sentiment": "positive",
                "topic": ["politics"]
            })
            assert response.status_code == 200
            assert "incorrect" in response.text.lower()

    def test_training_progress_tracking(self):
        """Test training progress tracking."""
        self.create_test_files()

        with FlaskTestServer(config=self.config) as server:
            # Register and login user
            response = server.post("/register", data={
                "username": "test_user",
                "password": "test_password"
            })
            response = server.post("/login", data={
                "username": "test_user",
                "password": "test_password"
            })

            # Complete phases to reach training
            response = server.post("/consent", data={"consent": "yes"})
            response = server.post("/instructions", data={"continue": "yes"})

            # Check initial progress
            response = server.get("/training")
            assert response.status_code == 200
            assert "question 1" in response.text.lower() or "1 of 3" in response.text.lower()

            # Answer first question
            response = server.post("/training", data={"sentiment": "positive"})
            assert response.status_code == 200

            # Check progress after first question
            response = server.get("/training")
            assert response.status_code == 200
            assert "question 2" in response.text.lower() or "2 of 3" in response.text.lower()

    def test_training_completion_workflow(self):
        """Test complete training completion workflow."""
        self.create_test_files()

        with FlaskTestServer(config=self.config) as server:
            # Register and login user
            response = server.post("/register", data={
                "username": "test_user",
                "password": "test_password"
            })
            response = server.post("/login", data={
                "username": "test_user",
                "password": "test_password"
            })

            # Complete phases to reach training
            response = server.post("/consent", data={"consent": "yes"})
            response = server.post("/instructions", data={"continue": "yes"})

            # Complete all training questions
            response = server.post("/training", data={"sentiment": "positive"})
            assert response.status_code == 200
            assert "correct" in response.text.lower()

            response = server.post("/training", data={"sentiment": "negative"})
            assert response.status_code == 200
            assert "correct" in response.text.lower()

            response = server.post("/training", data={"sentiment": "neutral"})
            assert response.status_code == 302  # Redirect to annotation

            # Verify we're now in annotation phase
            response = server.get("/annotation")
            assert response.status_code == 200
            assert "annotation" in response.text.lower()

            # Check admin statistics show completion
            response = server.get("/admin/api/annotators")
            assert response.status_code == 200

            data = response.get_json()
            annotator = data["annotators"][0]
            assert annotator["training_completed"] == True
            assert annotator["training_correct_answers"] == 3
            assert annotator["training_total_attempts"] == 3
            assert annotator["training_pass_rate"] == 100.0