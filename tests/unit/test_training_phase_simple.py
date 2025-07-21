"""
Simplified Unit Tests for Training Phase Functionality

This module contains focused unit tests for training phase components.
"""

import pytest
import json
import tempfile
import os
from unittest.mock import Mock, patch

from potato.user_state_management import TrainingState


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
        assert training_state.total_attempts == 3  # 1 + 2 = 3 total attempts

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