"""
Unit Tests for Training Phase Functionality

This module contains unit tests for training phase components including:
- TrainingState dataclass
- Training configuration validation
- Training data loading and validation
- User state training methods
"""

import pytest
import json
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass

from potato.user_state_management import TrainingState
from potato.server_utils.config_module import validate_training_config, validate_training_data_file
from potato.flask_server import load_training_data, get_training_instances, get_training_correct_answers, get_training_explanation


class TestTrainingState:
    """Test TrainingState dataclass functionality."""

    def test_training_state_initialization(self):
        """Test TrainingState initialization with default values."""
        training_state = TrainingState()

        assert training_state.completed_questions == {}
        assert training_state.total_correct == 0
        assert training_state.total_attempts == 0
        assert training_state.passed == False
        assert training_state.failed == False
        assert training_state.current_question_index == 0
        assert training_state.training_instances == []
        assert training_state.show_feedback == False
        assert training_state.feedback_message == ""
        assert training_state.allow_retry == False

    def test_add_answer_correct(self):
        """Test adding a correct answer."""
        training_state = TrainingState()

        training_state.add_answer("train_1", True, 1, "Good job!")

        assert training_state.completed_questions["train_1"]["correct"] == True
        assert training_state.completed_questions["train_1"]["attempts"] == 1
        assert training_state.completed_questions["train_1"]["explanation"] == "Good job!"
        assert training_state.total_correct == 1
        assert training_state.total_attempts == 1

    def test_add_answer_incorrect(self):
        """Test adding an incorrect answer."""
        training_state = TrainingState()

        training_state.add_answer("train_1", False, 2, "Try again")

        assert training_state.completed_questions["train_1"]["correct"] == False
        assert training_state.completed_questions["train_1"]["attempts"] == 2
        assert training_state.completed_questions["train_1"]["explanation"] == "Try again"
        assert training_state.total_correct == 0
        assert training_state.total_attempts == 2

    def test_add_answer_multiple_attempts(self):
        """Test adding answers with multiple attempts."""
        training_state = TrainingState()

        # First attempt - incorrect
        training_state.add_answer("train_1", False, 1, "Wrong")
        # Second attempt - correct
        training_state.add_answer("train_1", True, 2, "Correct!")

        assert training_state.completed_questions["train_1"]["correct"] == True
        assert training_state.completed_questions["train_1"]["attempts"] == 2
        assert training_state.total_correct == 1
        assert training_state.total_attempts == 3

    def test_get_question_stats(self):
        """Test getting statistics for a specific question."""
        training_state = TrainingState()
        training_state.add_answer("train_1", True, 1, "Good job!")

        stats = training_state.get_question_stats("train_1")
        assert stats["correct"] == True
        assert stats["attempts"] == 1
        assert stats["explanation"] == "Good job!"

        # Test non-existent question
        stats = training_state.get_question_stats("nonexistent")
        assert stats is None

    def test_has_completed_question(self):
        """Test checking if a question has been completed."""
        training_state = TrainingState()

        assert training_state.has_completed_question("train_1") == False

        training_state.add_answer("train_1", True, 1, "Good job!")
        assert training_state.has_completed_question("train_1") == True

    def test_get_correct_answer_count(self):
        """Test getting the total number of correct answers."""
        training_state = TrainingState()

        assert training_state.get_correct_answer_count() == 0

        training_state.add_answer("train_1", True, 1, "Good job!")
        training_state.add_answer("train_2", False, 1, "Wrong")
        training_state.add_answer("train_3", True, 1, "Good job!")

        assert training_state.get_correct_answer_count() == 2

    def test_get_total_attempts(self):
        """Test getting the total number of attempts."""
        training_state = TrainingState()

        assert training_state.get_total_attempts() == 0

        training_state.add_answer("train_1", True, 1, "Good job!")
        training_state.add_answer("train_2", False, 3, "Wrong")
        training_state.add_answer("train_3", True, 1, "Good job!")

        assert training_state.get_total_attempts() == 5

    def test_passed_failed_status(self):
        """Test setting and checking passed/failed status."""
        training_state = TrainingState()

        assert training_state.is_passed() == False
        assert training_state.is_failed() == False

        training_state.set_passed(True)
        assert training_state.is_passed() == True
        assert training_state.is_failed() == False

        training_state.set_failed(True)
        assert training_state.is_passed() == True  # Should not change
        assert training_state.is_failed() == True

    def test_current_question_index(self):
        """Test setting and getting current question index."""
        training_state = TrainingState()

        assert training_state.get_current_question_index() == 0

        training_state.set_current_question_index(2)
        assert training_state.get_current_question_index() == 2

    def test_training_instances(self):
        """Test setting and getting training instances."""
        training_state = TrainingState()

        assert training_state.get_training_instances() == []

        instances = ["train_1", "train_2", "train_3"]
        training_state.set_training_instances(instances)
        assert training_state.get_training_instances() == instances

    def test_feedback_management(self):
        """Test setting and clearing feedback."""
        training_state = TrainingState()

        # Test setting feedback
        training_state.set_feedback(True, "Incorrect answer", True)
        assert training_state.show_feedback == True
        assert training_state.feedback_message == "Incorrect answer"
        assert training_state.allow_retry == True

        # Test clearing feedback
        training_state.clear_feedback()
        assert training_state.show_feedback == False
        assert training_state.feedback_message == ""
        assert training_state.allow_retry == False

    def test_to_dict_serialization(self):
        """Test converting training state to dictionary."""
        training_state = TrainingState()
        training_state.add_answer("train_1", True, 1, "Good job!")
        training_state.set_training_instances(["train_1", "train_2"])
        training_state.set_current_question_index(1)
        training_state.set_passed(True)
        training_state.set_feedback(True, "Test feedback", False)

        data = training_state.to_dict()

        assert data["completed_questions"]["train_1"]["correct"] == True
        assert data["total_correct"] == 1
        assert data["total_attempts"] == 1
        assert data["passed"] == True
        assert data["failed"] == False
        assert data["current_question_index"] == 1
        assert data["training_instances"] == ["train_1", "train_2"]
        assert data["show_feedback"] == True
        assert data["feedback_message"] == "Test feedback"
        assert data["allow_retry"] == False

    def test_from_dict_deserialization(self):
        """Test creating training state from dictionary."""
        data = {
            "completed_questions": {"train_1": {"correct": True, "attempts": 1, "explanation": "Good job!"}},
            "total_correct": 1,
            "total_attempts": 1,
            "passed": True,
            "failed": False,
            "current_question_index": 1,
            "training_instances": ["train_1", "train_2"],
            "show_feedback": True,
            "feedback_message": "Test feedback",
            "allow_retry": False
        }

        training_state = TrainingState.from_dict(data)

        assert training_state.completed_questions["train_1"]["correct"] == True
        assert training_state.total_correct == 1
        assert training_state.total_attempts == 1
        assert training_state.passed == True
        assert training_state.failed == False
        assert training_state.current_question_index == 1
        assert training_state.training_instances == ["train_1", "train_2"]
        assert training_state.show_feedback == True
        assert training_state.feedback_message == "Test feedback"
        assert training_state.allow_retry == False


class TestTrainingConfigurationValidation:
    """Test training configuration validation."""

    def test_validate_training_config_enabled(self):
        """Test validation of enabled training configuration."""
        config = {
            "training": {
                "enabled": True,
                "data_file": "training_data.json",
                "annotation_schemes": ["sentiment"],
                "passing_criteria": {
                    "min_correct": 3,
                    "require_all_correct": False
                },
                "allow_retry": True,
                "failure_action": "repeat_training"
            }
        }

        # Should not raise an exception (data file validation is separate)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"training_instances": []}, f)
            data_file_path = f.name

        try:
            with patch('potato.server_utils.config_module.validate_path_security', return_value=data_file_path):
                validate_training_config(config, "/tmp")
        finally:
            os.unlink(data_file_path)

    def test_validate_training_config_disabled(self):
        """Test validation of disabled training configuration."""
        config = {
            "training": {
                "enabled": False
            }
        }

        # Should not raise an exception
        validate_training_config(config, "/tmp")

    def test_validate_training_config_missing_enabled(self):
        """Test validation when enabled field is missing."""
        config = {
            "training": {
                "data_file": "training_data.json"
            }
        }

        # Should not raise an exception (enabled defaults to False)
        validate_training_config(config, "/tmp")

    def test_validate_training_config_enabled_no_data_file(self):
        """Test validation when training is enabled but no data file is specified."""
        config = {
            "training": {
                "enabled": True
            }
        }

        # Should raise an exception (data_file is required when enabled)
        with pytest.raises(Exception, match="training.data_file is required when training is enabled"):
            validate_training_config(config, "/tmp")

    def test_validate_training_config_invalid_passing_criteria(self):
        """Test validation with invalid passing criteria."""
        config = {
            "training": {
                "enabled": True,
                "data_file": "training_data.json",
                "passing_criteria": {
                    "min_correct": -1,  # Invalid negative value
                    "require_all_correct": False
                }
            }
        }

        # Should raise an exception (validation is now stricter)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"training_instances": []}, f)
            data_file_path = f.name

        try:
            with patch('potato.server_utils.config_module.validate_path_security', return_value=data_file_path):
                with pytest.raises(Exception, match="training.passing_criteria.min_correct must be a positive integer"):
                    validate_training_config(config, "/tmp")
        finally:
            os.unlink(data_file_path)

    def test_validate_training_config_invalid_failure_action(self):
        """Test validation with invalid failure action."""
        config = {
            "training": {
                "enabled": True,
                "data_file": "training_data.json",
                "failure_action": "invalid_action"
            }
        }

        # Should raise an exception (validation is now stricter)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"training_instances": []}, f)
            data_file_path = f.name

        try:
            with patch('potato.server_utils.config_module.validate_path_security', return_value=data_file_path):
                with pytest.raises(Exception, match="training.failure_action must be one of"):
                    validate_training_config(config, "/tmp")
        finally:
            os.unlink(data_file_path)


class TestTrainingDataValidation:
    """Test training data file validation."""

    def test_validate_training_data_file_valid(self):
        """Test validation of valid training data file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            training_data = {
                "training_instances": [
                    {
                        "id": "train_1",
                        "text": "This is a positive sentiment text.",
                        "correct_answers": {
                            "sentiment": "positive"
                        },
                        "explanation": "This text expresses positive emotions."
                    }
                ]
            }
            json.dump(training_data, f)
            file_path = f.name

        try:
            # Should not raise an exception
            annotation_schemes = [{"name": "sentiment", "type": "radio", "labels": ["positive", "negative", "neutral"]}]
            validate_training_data_file(file_path, annotation_schemes)
        finally:
            os.unlink(file_path)

    def test_validate_training_data_file_missing(self):
        """Test validation of missing training data file."""
        with pytest.raises(Exception, match="Training data file not found"):
            annotation_schemes = [{"name": "sentiment", "type": "radio", "labels": ["positive", "negative", "neutral"]}]
            validate_training_data_file("nonexistent_file.json", annotation_schemes)

    def test_validate_training_data_file_invalid_json(self):
        """Test validation of invalid JSON file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("invalid json content")
            file_path = f.name

        try:
            with pytest.raises(Exception, match="Training data file is not valid JSON"):
                annotation_schemes = [{"name": "sentiment", "type": "radio", "labels": ["positive", "negative", "neutral"]}]
                validate_training_data_file(file_path, annotation_schemes)
        finally:
            os.unlink(file_path)

    def test_validate_training_data_file_missing_training_instances(self):
        """Test validation of training data file missing training_instances field."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            training_data = {
                "other_field": "value"
            }
            json.dump(training_data, f)
            file_path = f.name

        try:
            with pytest.raises(Exception, match="Training data must contain 'training_instances' field"):
                annotation_schemes = [{"name": "sentiment", "type": "radio", "labels": ["positive", "negative", "neutral"]}]
                validate_training_data_file(file_path, annotation_schemes)
        finally:
            os.unlink(file_path)

    def test_validate_training_data_file_empty_instances(self):
        """Test validation of training data file with empty instances."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            training_data = {
                "training_instances": []
            }
            json.dump(training_data, f)
            file_path = f.name

        try:
            with pytest.raises(Exception, match="training_instances cannot be empty"):
                annotation_schemes = [{"name": "sentiment", "type": "radio", "labels": ["positive", "negative", "neutral"]}]
                validate_training_data_file(file_path, annotation_schemes)
        finally:
            os.unlink(file_path)

    def test_validate_training_data_file_invalid_instance_format(self):
        """Test validation of training data file with invalid instance format."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            training_data = {
                "training_instances": [
                    {
                        "id": "train_1"
                        # Missing required fields
                    }
                ]
            }
            json.dump(training_data, f)
            file_path = f.name

        try:
            with pytest.raises(Exception, match="Training instance 0 missing required fields"):
                annotation_schemes = [{"name": "sentiment", "type": "radio", "labels": ["positive", "negative", "neutral"]}]
                validate_training_data_file(file_path, annotation_schemes)
        finally:
            os.unlink(file_path)


class TestTrainingDataLoading:
    """Test training data loading functions."""

    def test_load_training_data_success(self):
        """Test successful training data loading."""
        config = {
            "training": {
                "enabled": True,
                "data_file": "training_data.json",
                "annotation_schemes": ["sentiment"]
            },
            "annotation_schemes": [
                {"name": "sentiment", "type": "radio", "labels": ["positive", "negative", "neutral"]}
            ]
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            training_data = {
                "training_instances": [
                    {
                        "id": "train_1",
                        "text": "This is a positive sentiment text.",
                        "correct_answers": {
                            "sentiment": "positive"
                        },
                        "explanation": "This text expresses positive emotions."
                    }
                ]
            }
            json.dump(training_data, f)
            file_path = f.name

        try:
            # Mock the path resolution function
            with patch('potato.flask_server.get_abs_or_rel_path', return_value=file_path):
                with patch('potato.flask_server.Item') as mock_item:
                    mock_item_instance = Mock()
                    mock_item.return_value = mock_item_instance

                    load_training_data(config)

                    # Verify that training items were created
                    from potato.flask_server import get_training_instances
                    instances = get_training_instances()
                    assert len(instances) == 1
                    mock_item.assert_called_once()
        finally:
            os.unlink(file_path)

    def test_load_training_data_disabled(self):
        """Test training data loading when training is disabled."""
        # Clear any existing training items
        from potato.flask_server import training_items
        training_items.clear()

        config = {
            "training": {
                "enabled": False
            }
        }

        load_training_data(config)

        # Should not load any training data
        from potato.flask_server import get_training_instances
        instances = get_training_instances()
        assert len(instances) == 0

    def test_get_training_instances(self):
        """Test getting training instances."""
        # Clear and set up training items
        from potato.flask_server import training_items
        training_items.clear()
        training_items.extend([Mock(), Mock(), Mock()])

        instances = get_training_instances()
        assert len(instances) == 3

    def test_get_training_instances_empty(self):
        """Test getting training instances when none exist."""
        # Clear training items
        from potato.flask_server import training_items
        training_items.clear()

        instances = get_training_instances()
        assert instances == []

    @patch('potato.flask_server.get_training_instances')
    def test_get_training_correct_answers(self, mock_get_instances):
        """Test getting correct answers for a training instance."""
        mock_item = Mock()
        mock_item.get_id.return_value = "train_1"
        mock_item.get_data.return_value = {
            "correct_answers": {
                "sentiment": "positive",
                "topic": "emotion"
            }
        }
        mock_get_instances.return_value = [mock_item]

        correct_answers = get_training_correct_answers("train_1")
        assert correct_answers["sentiment"] == "positive"
        assert correct_answers["topic"] == "emotion"

    @patch('potato.flask_server.get_training_instances')
    def test_get_training_correct_answers_not_found(self, mock_get_instances):
        mock_get_instances.return_value = []
        """Test getting correct answers for non-existent training instance."""
        correct_answers = get_training_correct_answers("nonexistent")
        assert correct_answers == {}

    @patch('potato.flask_server.get_training_instances')
    def test_get_training_explanation(self, mock_get_instances):
        """Test getting explanation for a training instance."""
        mock_item = Mock()
        mock_item.get_id.return_value = "train_1"
        mock_item.get_data.return_value = {
            "explanation": "This text expresses positive emotions."
        }
        mock_get_instances.return_value = [mock_item]

        explanation = get_training_explanation("train_1")
        assert explanation == "This text expresses positive emotions."

    @patch('potato.flask_server.get_training_instances')
    def test_get_training_explanation_not_found(self, mock_get_instances):
        mock_get_instances.return_value = []
        """Test getting explanation for non-existent training instance."""
        explanation = get_training_explanation("nonexistent")
        assert explanation == ""


class TestUserStateTrainingMethods:
    """Test user state training methods."""

    def test_get_training_state(self):
        """Test getting training state from user state."""
        from potato.user_state_management import InMemoryUserState

        user_state = InMemoryUserState("test_user")
        training_state = user_state.get_training_state()

        assert isinstance(training_state, TrainingState)
        assert training_state.total_correct == 0
        assert training_state.total_attempts == 0

    def test_update_training_answer(self):
        """Test updating training answer."""
        from potato.user_state_management import InMemoryUserState
        from potato.phase import UserPhase

        user_state = InMemoryUserState("test_user")
        user_state.current_phase_and_page = (UserPhase.TRAINING, "training_page")

        annotations = {"sentiment": "positive"}
        user_state.update_training_answer("train_1", annotations)

        # Verify that annotations were stored in phase-specific storage
        assert len(user_state.phase_to_page_to_label_to_value[UserPhase.TRAINING]["training_page"]) > 0

    def test_check_training_pass_correct(self):
        """Test checking training pass with correct answer."""
        from potato.user_state_management import InMemoryUserState
        from potato.phase import UserPhase

        user_state = InMemoryUserState("test_user")
        user_state.current_phase_and_page = (UserPhase.TRAINING, "training_page")

        # Add a correct annotation
        from potato.item_state_management import Label
        label = Label("sentiment", "sentiment")
        user_state.phase_to_page_to_label_to_value[UserPhase.TRAINING]["training_page"][label] = "positive"

        correct_answers = {"sentiment": "positive"}
        is_correct = user_state.check_training_pass("train_1", correct_answers)

        assert is_correct == True
        assert user_state.get_training_state().total_correct == 1

    def test_check_training_pass_incorrect(self):
        """Test checking training pass with incorrect answer."""
        from potato.user_state_management import InMemoryUserState
        from potato.phase import UserPhase

        user_state = InMemoryUserState("test_user")
        user_state.current_phase_and_page = (UserPhase.TRAINING, "training_page")

        # Add an incorrect annotation
        from potato.item_state_management import Label
        label = Label("sentiment", "sentiment")
        user_state.phase_to_page_to_label_to_value[UserPhase.TRAINING]["training_page"][label] = "negative"

        correct_answers = {"sentiment": "positive"}
        is_correct = user_state.check_training_pass("train_1", correct_answers)

        assert is_correct == False
        assert user_state.get_training_state().total_correct == 0
        assert user_state.get_training_state().total_attempts == 1

    def test_get_current_training_instance(self):
        """Test getting current training instance."""
        from potato.user_state_management import InMemoryUserState

        user_state = InMemoryUserState("test_user")

        # Set up training instances
        training_state = user_state.get_training_state()
        training_state.set_training_instances(["train_1", "train_2", "train_3"])
        training_state.set_current_question_index(1)

        # Mock the get_training_instances function
        with patch('potato.flask_server.get_training_instances') as mock_get_instances:
            mock_item = Mock()
            mock_item.get_id.return_value = "train_2"
            mock_get_instances.return_value = [mock_item]

            current_instance = user_state.get_current_training_instance()
            assert current_instance is not None
            assert current_instance.get_id() == "train_2"

    def test_advance_training_question(self):
        """Test advancing to next training question."""
        from potato.user_state_management import InMemoryUserState

        user_state = InMemoryUserState("test_user")

        # Set up training instances
        training_state = user_state.get_training_state()
        training_state.set_training_instances(["train_1", "train_2", "train_3"])
        training_state.set_current_question_index(0)

        # Advance to next question
        has_more = user_state.advance_training_question()
        assert has_more == True
        assert training_state.get_current_question_index() == 1

        # Advance to last question
        has_more = user_state.advance_training_question()
        assert has_more == True
        assert training_state.get_current_question_index() == 2

        # Try to advance past last question
        has_more = user_state.advance_training_question()
        assert has_more == False
        assert training_state.get_current_question_index() == 2

    def test_reset_training_state(self):
        """Test resetting training state."""
        from potato.user_state_management import InMemoryUserState

        user_state = InMemoryUserState("test_user")

        # Add some training data
        training_state = user_state.get_training_state()
        training_state.add_answer("train_1", True, 1, "Good job!")
        training_state.set_training_instances(["train_1", "train_2"])
        training_state.set_current_question_index(1)
        training_state.set_passed(True)

        # Reset training state
        user_state.reset_training_state()

        # Verify state was reset
        new_training_state = user_state.get_training_state()
        assert new_training_state.total_correct == 0
        assert new_training_state.total_attempts == 0
        assert new_training_state.passed == False
        assert new_training_state.current_question_index == 0
        assert new_training_state.training_instances == []