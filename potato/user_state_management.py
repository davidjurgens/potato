"""
User State Management Module

This module provides comprehensive user state tracking and management for the Potato
annotation platform. It handles user progress through annotation phases, instance
assignments, annotation storage, and state persistence.

Key Components:
- UserStateManager: Singleton manager for all user states
- UserState: Abstract interface for user state implementations
- InMemoryUserState: In-memory implementation of user state
- MysqlUserState: Database-backed implementation (placeholder)

The system supports:
- Multi-phase annotation workflows (consent, instructions, training, annotation, post-study)
- Instance assignment and navigation
- Annotation storage (labels and spans)
- Progress tracking and statistics
- State persistence to disk
- Active learning integration
- Behavioral data collection

User states track:
- Current phase and page in the annotation workflow
- Assigned instances and current position
- Completed annotations (labels and spans)
- Timing information and statistics
- Pre-study and consent status
- Assignment limits and progress
"""

from __future__ import annotations

import json
import datetime
from collections import defaultdict, OrderedDict
import logging
import os
import threading
from typing import Optional, Dict, Any, List, Tuple, Set

from potato.authentication import UserAuthenticator
from potato.phase import UserPhase
from potato.item_state_management import get_item_state_manager, Item, SpanAnnotation, Label, SpanLink
from potato.annotation_history import AnnotationAction, AnnotationHistoryManager
from dataclasses import dataclass

@dataclass
class TrainingState:
    """
    Data class for tracking training phase state and performance.

    This class encapsulates training metrics for individual users,
    including completed questions, correct answers, attempts, and
    pass/fail status.

    Training Strategies Supported:
    1. min_correct: Pass after N correct answers (regardless of mistakes)
    2. require_all_correct: Must get all questions correct
    3. max_mistakes: Fail after N total mistakes (kicked out)
    4. max_mistakes_per_question: Fail after N mistakes on any single question
    5. allow_retry: Allow retrying incorrect answers
    """
    completed_questions: Dict[str, Dict[str, Any]]  # instance_id -> {correct: bool, attempts: int, explanation: str}
    total_correct: int
    total_attempts: int
    total_mistakes: int  # Track total incorrect answers
    passed: bool
    failed: bool
    current_question_index: int
    training_instances: List[str]  # List of training instance IDs
    show_feedback: bool  # Whether to show feedback on the current question
    feedback_message: str  # The feedback message to display
    allow_retry: bool  # Whether to allow retry for the current question
    max_mistakes: int  # Maximum mistakes allowed before failure (-1 = unlimited)
    max_mistakes_per_question: int  # Maximum mistakes per question before failure (-1 = unlimited)

    def __init__(self, max_mistakes: int = -1, max_mistakes_per_question: int = -1):
        """
        Initialize TrainingState.

        Args:
            max_mistakes: Maximum total mistakes allowed before failure (-1 = unlimited)
            max_mistakes_per_question: Maximum mistakes per question before failure (-1 = unlimited)
        """
        self.completed_questions = {}
        self.total_correct = 0
        self.total_attempts = 0
        self.total_mistakes = 0
        self.passed = False
        self.failed = False
        self.current_question_index = 0
        self.training_instances = []
        self.show_feedback = False
        self.feedback_message = ""
        self.allow_retry = False
        self.max_mistakes = max_mistakes
        self.max_mistakes_per_question = max_mistakes_per_question

        # Per-category performance tracking for category-based assignment
        # Maps category name -> {'correct': int, 'total': int}
        self.category_scores: Dict[str, Dict[str, int]] = {}

    def add_answer(self, instance_id: str, is_correct: bool, attempts: int, explanation: str = "") -> None:
        """Add a training answer and update statistics."""
        # Track previous state for this question
        prev_attempts = 0
        prev_correct = False
        if instance_id in self.completed_questions:
            prev_attempts = self.completed_questions[instance_id].get('attempts', 0)
            prev_correct = self.completed_questions[instance_id].get('correct', False)

        self.completed_questions[instance_id] = {
            'correct': is_correct,
            'attempts': attempts,
            'explanation': explanation
        }

        # Update total correct (only if this is newly correct)
        if is_correct and not prev_correct:
            self.total_correct += 1

        # Update total attempts
        self.total_attempts = attempts - prev_attempts + self.total_attempts

        # Update total mistakes
        if not is_correct:
            self.total_mistakes += 1

    def record_mistake(self, instance_id: str) -> None:
        """Record a mistake for tracking purposes without adding a full answer."""
        self.total_mistakes += 1
        if instance_id in self.completed_questions:
            self.completed_questions[instance_id]['attempts'] = \
                self.completed_questions[instance_id].get('attempts', 0) + 1
        else:
            self.completed_questions[instance_id] = {
                'correct': False,
                'attempts': 1,
                'explanation': ''
            }

    def get_mistakes_for_question(self, instance_id: str) -> int:
        """Get the number of mistakes (incorrect attempts) for a specific question."""
        if instance_id not in self.completed_questions:
            return 0
        question_data = self.completed_questions[instance_id]
        # If correct, mistakes = attempts - 1; if not correct, mistakes = attempts
        if question_data.get('correct', False):
            return question_data.get('attempts', 1) - 1
        return question_data.get('attempts', 0)

    def get_total_mistakes(self) -> int:
        """Get the total number of mistakes across all questions."""
        return self.total_mistakes

    def should_fail_due_to_mistakes(self) -> bool:
        """Check if the user should fail due to too many mistakes."""
        if self.max_mistakes > 0 and self.total_mistakes >= self.max_mistakes:
            return True
        return False

    def should_fail_question_due_to_mistakes(self, instance_id: str) -> bool:
        """Check if the user should fail due to too many mistakes on a single question."""
        if self.max_mistakes_per_question > 0:
            question_mistakes = self.get_mistakes_for_question(instance_id)
            if question_mistakes >= self.max_mistakes_per_question:
                return True
        return False

    def set_max_mistakes(self, max_mistakes: int) -> None:
        """Set the maximum number of total mistakes allowed."""
        self.max_mistakes = max_mistakes

    def set_max_mistakes_per_question(self, max_mistakes_per_question: int) -> None:
        """Set the maximum number of mistakes allowed per question."""
        self.max_mistakes_per_question = max_mistakes_per_question

    def get_question_stats(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a specific training question."""
        return self.completed_questions.get(instance_id)

    def has_completed_question(self, instance_id: str) -> bool:
        """Check if a training question has been completed."""
        return instance_id in self.completed_questions

    def get_correct_answer_count(self) -> int:
        """Get the total number of correct answers."""
        return self.total_correct

    def get_total_attempts(self) -> int:
        """Get the total number of attempts across all questions."""
        return self.total_attempts

    def is_passed(self) -> bool:
        """Check if the user has passed training."""
        return self.passed

    def is_failed(self) -> bool:
        """Check if the user has failed training."""
        return self.failed

    def set_passed(self, passed: bool) -> None:
        """Set the passed status."""
        self.passed = passed

    def set_failed(self, failed: bool) -> None:
        """Set the failed status."""
        self.failed = failed

    def get_current_question_index(self) -> int:
        """Get the current question index."""
        return self.current_question_index

    def set_current_question_index(self, index: int) -> None:
        """Set the current question index."""
        self.current_question_index = index

    def get_training_instances(self) -> List[str]:
        """Get the list of training instance IDs."""
        return self.training_instances

    def set_training_instances(self, instances: List[str]) -> None:
        """Set the list of training instance IDs."""
        self.training_instances = instances

    def set_feedback(self, show_feedback: bool, message: str, allow_retry: bool) -> None:
        """Set feedback state for the current question."""
        self.show_feedback = show_feedback
        self.feedback_message = message
        self.allow_retry = allow_retry

    def clear_feedback(self) -> None:
        """Clear feedback state."""
        self.show_feedback = False
        self.feedback_message = ""
        self.allow_retry = False

    # =========================================================================
    # Category Performance Tracking Methods
    # =========================================================================

    def record_category_answer(self, categories: List[str], is_correct: bool) -> None:
        """
        Record an answer for category performance tracking.

        This should be called when a training question is answered. Each category
        that the training question belongs to will have its score updated.

        Args:
            categories: List of category names the training question belongs to
            is_correct: Whether the answer was correct
        """
        for category in categories:
            if category not in self.category_scores:
                self.category_scores[category] = {'correct': 0, 'total': 0}

            self.category_scores[category]['total'] += 1
            if is_correct:
                self.category_scores[category]['correct'] += 1

    def get_category_score(self, category: str) -> Dict[str, Any]:
        """
        Get the performance score for a specific category.

        Args:
            category: The category name

        Returns:
            Dictionary with 'correct', 'total', and 'accuracy' keys
        """
        if category not in self.category_scores:
            return {'correct': 0, 'total': 0, 'accuracy': 0.0}

        score = self.category_scores[category]
        total = score['total']
        correct = score['correct']
        accuracy = correct / total if total > 0 else 0.0

        return {
            'correct': correct,
            'total': total,
            'accuracy': accuracy
        }

    def get_all_category_scores(self) -> Dict[str, Dict[str, Any]]:
        """
        Get performance scores for all categories.

        Returns:
            Dictionary mapping category names to their scores
        """
        result = {}
        for category in self.category_scores:
            result[category] = self.get_category_score(category)
        return result

    def get_qualified_categories(self, threshold: float = 0.7, min_questions: int = 1) -> List[str]:
        """
        Get list of categories the user has qualified for based on performance.

        Args:
            threshold: Minimum accuracy required to qualify (0.0 to 1.0)
            min_questions: Minimum number of questions answered in category

        Returns:
            List of category names the user qualifies for
        """
        qualified = []
        for category, score in self.category_scores.items():
            if score['total'] >= min_questions:
                accuracy = score['correct'] / score['total'] if score['total'] > 0 else 0.0
                if accuracy >= threshold:
                    qualified.append(category)
        return qualified

    def get_category_qualification_details(self, threshold: float = 0.7, min_questions: int = 1) -> Dict[str, Dict[str, Any]]:
        """
        Get detailed qualification status for all categories.

        Args:
            threshold: Minimum accuracy required to qualify
            min_questions: Minimum number of questions answered in category

        Returns:
            Dictionary mapping category names to qualification details
        """
        result = {}
        for category, score in self.category_scores.items():
            total = score['total']
            correct = score['correct']
            accuracy = correct / total if total > 0 else 0.0
            qualified = total >= min_questions and accuracy >= threshold

            result[category] = {
                'correct': correct,
                'total': total,
                'accuracy': accuracy,
                'qualified': qualified,
                'meets_threshold': accuracy >= threshold,
                'meets_min_questions': total >= min_questions
            }
        return result

    def to_dict(self) -> Dict[str, Any]:
        """Convert training state to dictionary for serialization."""
        return {
            'completed_questions': self.completed_questions,
            'total_correct': self.total_correct,
            'total_attempts': self.total_attempts,
            'total_mistakes': self.total_mistakes,
            'passed': self.passed,
            'failed': self.failed,
            'current_question_index': self.current_question_index,
            'training_instances': self.training_instances,
            'show_feedback': self.show_feedback,
            'feedback_message': self.feedback_message,
            'allow_retry': self.allow_retry,
            'max_mistakes': self.max_mistakes,
            'max_mistakes_per_question': self.max_mistakes_per_question,
            'category_scores': self.category_scores
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TrainingState':
        """Create training state from dictionary."""
        training_state = cls()
        training_state.completed_questions = data.get('completed_questions', {})
        training_state.total_correct = data.get('total_correct', 0)
        training_state.total_attempts = data.get('total_attempts', 0)
        training_state.total_mistakes = data.get('total_mistakes', 0)
        training_state.passed = data.get('passed', False)
        training_state.failed = data.get('failed', False)
        training_state.current_question_index = data.get('current_question_index', 0)
        training_state.training_instances = data.get('training_instances', [])
        training_state.show_feedback = data.get('show_feedback', False)
        training_state.feedback_message = data.get('feedback_message', "")
        training_state.allow_retry = data.get('allow_retry', False)
        training_state.max_mistakes = data.get('max_mistakes', -1)
        training_state.max_mistakes_per_question = data.get('max_mistakes_per_question', -1)
        training_state.category_scores = data.get('category_scores', {})
        return training_state

# Database imports
try:
    from potato.database import DatabaseManager, MysqlUserState
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logging.basicConfig()



# Singleton instance of the user state manager with thread-safe lock
USER_STATE_MANAGER = None
_USER_STATE_MANAGER_LOCK = threading.Lock()

def init_user_state_manager(config: dict) -> UserStateManager:
    """
    Initialize the singleton UserStateManager instance.

    This function creates the global UserStateManager that will be shared
    across all users. It's designed to be called once during application startup.
    Thread-safe initialization using double-checked locking pattern.

    Args:
        config: Configuration dictionary containing user management settings

    Returns:
        UserStateManager: The initialized singleton instance
    """
    global USER_STATE_MANAGER

    # Double-checked locking for thread safety
    if USER_STATE_MANAGER is None:
        with _USER_STATE_MANAGER_LOCK:
            # Check again inside the lock
            if USER_STATE_MANAGER is None:
                USER_STATE_MANAGER = UserStateManager(config)
    return USER_STATE_MANAGER

def clear_user_state_manager():
    """
    Clear the singleton user state manager instance (for testing).

    This function is primarily used for testing purposes to reset the
    global state between test runs. Thread-safe.
    """
    global USER_STATE_MANAGER
    with _USER_STATE_MANAGER_LOCK:
        USER_STATE_MANAGER = None

def get_user_state_manager() -> UserStateManager:
    """
    Get the singleton UserStateManager instance.

    Returns:
        UserStateManager: The singleton instance

    Raises:
        ValueError: If the manager has not been initialized
    """
    global USER_STATE_MANAGER
    if USER_STATE_MANAGER is None:
        raise ValueError('User state manager has not been initialized')
    return USER_STATE_MANAGER

class UserStateManager:
    """
    Manages all user states in the annotation system.

    This singleton class provides centralized management of all user states,
    including user creation, state tracking, phase management, and persistence.
    It coordinates with the ItemStateManager for instance assignments and
    supports various annotation workflows.
    """


    def __init__(self, config: dict):
        """
        Initialize the user state manager.

        Args:
            config: Configuration dictionary containing user management settings
        """
        self.config = config
        self.user_to_annotation_state = {}
        self.task_assignment = {}
        self.prolific_study = None
        self.phase_type_to_name_to_page = defaultdict(OrderedDict)

        # Thread-safe lock for shared state access
        self._state_lock = threading.RLock()

        # TODO: load this from the config
        self.max_annotations_per_user = -1

        # Database support
        self.db_manager = None
        self.use_database = False

        # Initialize database if configured
        if DATABASE_AVAILABLE and 'database' in config:
            db_config = config['database']
            if db_config.get('type') == 'mysql':
                try:
                    self.db_manager = DatabaseManager(config)
                    self.use_database = True
                    self.db_manager.create_tables()
                    logger.info("Initialized MySQL database backend")
                except Exception as e:
                    logger.error(f"Failed to initialize database: {e}")
                    self.use_database = False

        self.logger = logging.getLogger(__name__)
        # setting to debug
        self.logger.setLevel(logging.DEBUG)
        logging.basicConfig()

    def add_phase(self, phase_type: UserPhase, phase_name: str, page_fname: str):
        """
        Add a phase page to the phase mapping.

        Args:
            phase_type: The type of phase (e.g., CONSENT, INSTRUCTIONS)
            phase_name: The name of the page within the phase
            page_fname: The filename of the HTML page
        """
        self.phase_type_to_name_to_page[phase_type][phase_name] = page_fname

    def add_user(self, user_id: str) -> UserState:
        """
        Add a new user to the user state manager (thread-safe).

        Args:
            user_id: Unique identifier for the new user

        Returns:
            UserState: The created user state object

        Raises:
            ValueError: If a user with the same ID already exists
        """
        with self._state_lock:
            logger.debug(f"=== ADD USER START ===")
            logger.debug(f"Adding user: {user_id}")
            logger.debug(f"Current users: {list(self.user_to_annotation_state.keys())}")
            logger.debug(f"User already exists: {user_id in self.user_to_annotation_state}")

            if user_id in self.user_to_annotation_state:
                logger.warning(f'User "{user_id}" already exists in the user state manager')
                raise ValueError(f'User "{user_id}" already exists in the user state manager')

            # Create appropriate user state based on configuration
            if self.use_database and self.db_manager:
                logger.debug(f"Creating MysqlUserState for user: {user_id}")
                user_state = MysqlUserState(user_id, self.db_manager, self.max_annotations_per_user)
            else:
                logger.debug(f"Creating InMemoryUserState for user: {user_id}")
                user_state = InMemoryUserState(user_id, self.max_annotations_per_user)

            self.user_to_annotation_state[user_id] = user_state
            logger.debug(f"User state created and stored: {user_state}")
            logger.debug(f"Users after adding: {list(self.user_to_annotation_state.keys())}")
            logger.debug(f"=== ADD USER END ===")

            return user_state

    def get_or_create_user(self, user_id: str) -> UserState:
        """
        Get a user from the user state manager, creating a new user if they don't exist.

        Args:
            user_id: Unique identifier for the user

        Returns:
            UserState: The user state object (existing or newly created)
        """
        if user_id not in self.user_to_annotation_state:
            self.logger.debug('Previously unknown user "%s"; creating new annotation state' % (user_id))
            user_state = self.add_user(user_id)
        else:
            user_state = self.user_to_annotation_state[user_id]
        return user_state

    def get_max_annotations_per_user(self) -> int:
        """
        Get the maximum number of items that each annotator should annotate.

        Returns:
            int: Maximum annotations per user (-1 for unlimited)
        """
        return self.max_annotations_per_user

    def set_max_annotations_per_user(self, max_annotations_per_user: int) -> None:
        """
        Set the maximum number of items that each annotator should annotate.

        Args:
            max_annotations_per_user: Maximum annotations per user (-1 for unlimited)
        """
        self.max_annotations_per_user = max_annotations_per_user

    def old_get_or_create_user(self, user_id: str) -> UserState:
        if user_id not in self.user_to_annotation_state:
            self.logger.debug('Previously unknown user "%s"; creating new annotation state' % (user_id))

            if "automatic_assignment" in self.config and self.config["automatic_assignment"]["on"]:
                # when pre_annotation is set up, only assign the instance when consent question is answered
                if "prestudy" in self.config and self.config["prestudy"]["on"]:
                    user_state = UserState(generate_initial_user_dataflow(user_id))
                    self.user_to_annotation_state[user_id] = user_state

                # when pre_annotation is set up, only assign the instance when consent question is answered
                elif "pre_annotation" in self.config["automatic_assignment"] \
                        and "pre_annotation" in self.config["automatic_assignment"]["order"]:

                    user_state = UserState(generate_initial_user_dataflow(user_id))
                    self.user_to_annotation_state[user_id] = user_state

                # assign instances to new user when automatic assignment is turned on and there is no pre_annotation or prestudy pages
                else:
                    user_state = UserState(generate_initial_user_dataflow(user_id))
                    self.user_to_annotation_state[user_id] = user_state
                    self.assign_instances_to_user(user_id)

            else:
                # assign all the instance to each user when automatic assignment is turned off
                user_state = UserState(user_id)
                # user_state.real_instance_assigned_count = user_state.get_assigned_instance_count()
                self.user_to_annotation_state[user_id] = user_state
        else:
            user_state = self.user_to_annotation_state[user_id]

    def get_user_state(self, user_id: str) -> UserState:
        '''
        Gets a user from the user state manager or None if the user does not exist (thread-safe).'''
        with self._state_lock:
            if user_id not in self.user_to_annotation_state:
                if self.use_database and self.db_manager:
                    # Try to load from database
                    try:
                        user_state = MysqlUserState(user_id, self.db_manager, self.max_annotations_per_user)
                        self.user_to_annotation_state[user_id] = user_state
                        return user_state
                    except Exception as e:
                        logger.warning(f"Failed to load user state from database for {user_id}: {e}")
                else:
                    # Try to load the user state from disk if it exists
                    try:
                        output_annotation_dir = self.config["output_annotation_dir"]
                        user_dir = os.path.join(output_annotation_dir, user_id)
                        if os.path.exists(user_dir):
                            user_state = InMemoryUserState.load(user_dir)
                            self.user_to_annotation_state[user_id] = user_state
                            return user_state
                    except Exception as e:
                        logger.warning(f"Failed to load user state for {user_id}: {e}")

            return self.user_to_annotation_state.get(user_id)

    def get_all_users(self) -> list[UserState]:
        '''Gets all users from the user state manager (thread-safe).'''
        with self._state_lock:
            return list(self.user_to_annotation_state.values())

    def get_phase_html_fname(self, phase: UserPhase, page: str) -> str:
        '''Returns the filename of the page for the given phase and page name'''
        return self.phase_type_to_name_to_page[phase][page]

    def has_user(self, user_id: str) -> bool:
        '''Checks if a user exists in the user state manager'''
        return user_id in self.user_to_annotation_state

    def advance_phase(self, user_id: str) -> None:
        '''Moves the user to the next page in the current phase or the next phase'''
        phase, page = self.get_next_user_phase_page(user_id)
        # Get the current user's state
        user_state = self.get_user_state(user_id)
        user_state.advance_to_phase(phase, page)

    def get_next_user_phase_page(self, user_id: str) -> tuple[UserPhase,str]:
        '''Returns the name and filename of next the page for the user, either
           in the current phase or next phase. This method handles the
           case of where there are multiple pages within the same phase type'''

        # Get the current user's state
        user_state = self.get_user_state(user_id)

        # Get the current of their phase
        cur_phase, cur_page = user_state.get_current_phase_and_page()
        if cur_phase == UserPhase.DONE:
            return UserPhase.DONE, None

        page2file_for_cur_phase = self.phase_type_to_name_to_page[cur_phase]
        if len(page2file_for_cur_phase) > 1 and cur_page is not None:
            pages_for_cur_phase = list(page2file_for_cur_phase.keys())
            # Handle case where cur_page is not in the list
            if cur_page in pages_for_cur_phase:
                cur_page_index = pages_for_cur_phase.index(cur_page)
                # If there are more pages in this phase, return the next one
                if cur_page_index < len(pages_for_cur_phase) - 1:
                    next_page = pages_for_cur_phase[cur_page_index + 1]
                    return cur_phase, next_page

        # If there are no more pages in this phase, return the next phase.
        # Use the config's phase order instead of the enum order
        if "phases" in self.config and "order" in self.config["phases"]:
            # Use config phase order
            config_phase_order = self.config["phases"]["order"]
            # Convert config phase names to UserPhase enums
            config_phases = []
            for phase_name in config_phase_order:
                if phase_name in self.config["phases"]:
                    phase_type_str = self.config["phases"][phase_name]["type"]
                    phase_type = UserPhase.fromstr(phase_type_str)
                    if phase_type in self.phase_type_to_name_to_page:
                        config_phases.append(phase_type)
                    else:
                        pass # Phase not found in phase_type_to_name_to_page
                else:
                    pass # Phase not found in config phases

            # Add ANNOTATION phase if it's not in config but exists in phase_type_to_name_to_page
            if UserPhase.ANNOTATION in self.phase_type_to_name_to_page and UserPhase.ANNOTATION not in config_phases:
                config_phases.append(UserPhase.ANNOTATION)

            # Find current phase in config order
            if cur_phase in config_phases:
                cur_phase_index = config_phases.index(cur_phase)
                if cur_phase_index < len(config_phases) - 1:
                    next_phase = config_phases[cur_phase_index + 1]
                    # Use the first page in the next phase
                    next_page = list(self.phase_type_to_name_to_page[next_phase].keys())[0]
                    return next_phase, next_page
                else:
                    pass # Current phase is last in config order
            else:
                pass # Current phase not found in config_phases
        else:
            # Fallback to enum order if no config order is specified
            all_phases = [p for p in list(UserPhase) if p in self.phase_type_to_name_to_page]
            cur_phase_index = all_phases.index(cur_phase)
            if cur_phase_index < len(all_phases) - 1:
                next_phase = all_phases[cur_phase_index + 1]
                # Use the first page in the next phase
                next_page = list(self.phase_type_to_name_to_page[next_phase].keys())[0]
                return next_phase, next_page

        return UserPhase.DONE, None

    def get_user_ids(self) -> list[str]:
        '''Gets all user IDs from the user state manager'''
        return [user.user_id for user in self.get_all_users()]

    def get_user_count(self) -> int:
        '''Get the number of users in the user state manager'''
        return len(self.user_to_annotation_state)

    def is_consent_required(self) -> bool:
        return UserPhase.CONSENT in self.phase_type_to_name_to_page

    def is_instructions_required(self) -> bool:
        return UserPhase.INSTRUCTIONS in self.phase_type_to_name_to_page

    def is_prestudy_required(self) -> bool:
        return UserPhase.PRESTUDY in self.phase_type_to_name_to_page

    def is_training_required(self) -> bool:
        return UserPhase.TRAINING in self.phase_type_to_name_to_page

    def is_poststudy_required(self) -> bool:
        return UserPhase.POSTSTUDY in self.phase_type_to_name_to_page

    def save_user_state(self, user_state: UserState) -> None:
        '''Saves the user state for the given user ID'''
        # Figure out where this user's data would be stored on disk
        output_annotation_dir = self.config["output_annotation_dir"]
        username = user_state.get_user_id()

        # NB: Do some kind of sanitizing on the username to improve security
        user_dir = os.path.join(output_annotation_dir, username)

        # Save the user state
        user_state.save(user_dir)

    def load_user_state(self, user_dir: str) -> UserState:
        '''Loads the user state for the given user ID'''

        # Figure out where this user's data would be stored on disk
        output_annotation_dir = self.config["output_annotation_dir"]

        # TODO: make the user state type configurable between in-memory and DB-backed.
        user_state = InMemoryUserState.load(user_dir)


        if user_state.get_user_id() in self.user_to_annotation_state:
            logger.warning(f'User "{user_state.get_user_id()}" already exists in the user state manager, but is being overwritten by load_state()')

        self.user_to_annotation_state[user_state.get_user_id()] = user_state

        return user_state

    def clear(self):
        """Clear all user state (for testing/debugging)."""
        self.user_to_annotation_state.clear()
        self.task_assignment.clear()
        self.prolific_study = None
        self.phase_type_to_name_to_page.clear()
        self.max_annotations_per_user = -1

        # Clear database if using it
        if self.use_database and self.db_manager:
            try:
                self.db_manager.drop_tables()
                self.db_manager.create_tables()
                logger.info("Cleared database tables")
            except Exception as e:
                logger.error(f"Failed to clear database: {e}")

        # Reload phases after clearing to ensure phase_type_to_name_to_page is repopulated
        from potato.flask_server import load_phase_data
        load_phase_data(self.config)


class UserState:
    """
    An interface class for maintaining state on which annotations users have completed.
    """

    def __init__(self, user_id: str):
        pass

    def advance_to_phase(self, phase: UserPhase, page: str) -> None:
        raise NotImplementedError()

    def assign_instance(self, item: Item) -> None:
        raise NotImplementedError()

    def get_current_instance(self) -> Item:
        raise NotImplementedError()

    def get_labeled_instance_ids(self) -> set[str]:
        '''Returns the set of instances ids that this user has labeled'''
        raise NotImplementedError()

    def get_span_annotations(self):
        return self.span_annotations

    def get_current_instance_index(self) -> int:
        raise NotImplementedError()

    def get_user_id(self) -> str:
        '''Returns the user ID for this user'''
        raise NotImplementedError()

    def goto_prev_instance(self) -> None:
        raise NotImplementedError()

    def goto_next_instance(self) -> None:
        raise NotImplementedError()

    def go_to_index(self, instance_index: int) -> None:
        '''Moves the annotator's view to the instance at the specified index'''
        raise NotImplementedError()

    def get_all_annotations(self):
        """
        Returns all annotations (label and span) for all annotated instances
        """
        raise NotImplementedError()

    def get_label_annotations(self, instance_id):
        """
        Returns the label-based annotations for the instance.
        """
        raise NotImplementedError()

    def get_span_annotations(self, instance_id):
        """
        Returns the span annotations for this instance.
        """
        raise NotImplementedError()

    def get_current_phase_and_page(self) -> tuple[UserPhase, str]:
        raise NotImplementedError()

    def get_annotation_count(self) -> int:
        raise NotImplementedError()

    def get_assigned_instance_count(self):
        raise NotImplementedError()

    def get_phase(self) -> UserPhase:
        return self.current_phase_and_page[0]

    def set_phase(self, phase: UserPhase) -> None:
        raise NotImplementedError()

    def move_to_next_phase(self) -> None:
        raise NotImplementedError()

    def set_max_assignments(self) -> None:
        raise NotImplementedError()

    def set_annotation(
        self, instance_id, schema_to_label_to_value, span_annotations, behavioral_data_dict
    ):
        """
        Based on a user's actions, updates the annotation for this particular instance.

        :span_annotations: a list of span annotations, which are each
          represented as dictionary objects/
        :return: True if setting these annotation values changes the previous
          annotation of this instance.
        """

        # Get whatever annotations were present for this instance, or, if the
        # item has not been annotated represent that with empty data structures
        # so we can keep track of whether the state changes
        old_annotation = defaultdict(dict)
        if instance_id in self.instance_id_to_label_to_value:
            old_annotation = self.instance_id_to_label_to_value[instance_id]

        old_span_annotations = []
        if instance_id in self.instance_id_to_span_to_value:
            old_span_annotations = self.instance_id_to_span_to_value[instance_id]

        # Avoid updating with no entries
        if len(schema_to_label_to_value) > 0:
            self.instance_id_to_label_to_value[instance_id] = schema_to_label_to_value
        # If the user didn't label anything (e.g. they unselected items), then
        # we delete the old annotation state
        elif instance_id in self.instance_id_to_label_to_value:
            del self.instance_id_to_label_to_value[instance_id]

        # Handle span annotations - only update if span_annotations is not None
        # This prevents deletion of existing spans during navigation when span_annotations is empty
        if span_annotations is not None:
            # Avoid updating with no entries
            if len(span_annotations) > 0:
                self.instance_id_to_span_to_value[instance_id] = span_annotations
            # If the user didn't label anything (e.g. they unselected items), then
            # we delete the old annotation state
            elif instance_id in self.instance_id_to_span_to_value:
                del self.instance_id_to_span_to_value[instance_id]
        # If span_annotations is None, preserve existing spans (this happens during navigation)

        # TODO: keep track of all the annotation behaviors instead of only
        # keeping the latest one each time when new annotation is updated,
        # we also update the behavioral_data_dict (currently done in the
        # update_annotation_state function)
        #
        # self.instance_id_to_behavioral_data[instance_id] = behavioral_data_dict

        return (
            old_annotation != schema_to_label_to_value or old_span_annotations != span_annotations
        )

    def update(self, annotation_order, annotated_instances):
        """
        Updates the entire state of annotations for this user by inserting
        all the data in annotated_instances into this user's state. Typically
        this data is loaded from a file

        NOTE: This is only used to update the entire list of annotations,
        normally when loading all the saved data

        :annotation_order: a list of string instance IDs in the order that this
        user should see those instances.
        :annotated_instances: a list of dictionary objects detailing the
        annotations on each item.
        """

        self.instance_id_to_label_to_value = {}
        for inst in annotated_instances:

            inst_id = inst["id"]
            label_annotations = inst["label_annotations"]
            span_annotations = inst["span_annotations"]

            self.instance_id_to_label_to_value[inst_id] = label_annotations
            self.instance_id_to_span_to_value[inst_id] = span_annotations

            behavior_dict = inst.get("behavioral_data", {})
            self.instance_id_to_behavioral_data[inst_id] = behavior_dict

            # TODO: move this code somewhere else so consent is organized
            # separately
            if re.search("consent", inst_id):
                consent_key = "I want to participate in this research and continue with the study."
                self.consent_agreed = False
                if label_annotations[consent_key].get("Yes") == "true":
                    self.consent_agreed = True

        self.instance_id_ordering = annotation_order
        self.instance_id_to_order = self.generate_id_order_mapping(self.instance_id_ordering)

        # Set the current item to be the one after the last thing that was
        # annotated
        # self.current_instance_index = min(len(self.instance_id_to_labeling),
        #                           len(self.instance_id_ordering)-1)

        annotated_set = set([it['id'] for it in annotated_instances])
        self.current_instance_index = self.instance_id_to_order[annotated_instances[-1]['id']]
        for in_id in self.instance_id_ordering:
            if in_id[-4:] == 'html':
                continue
            if in_id in annotated_set:
                self.current_instance_index = self.instance_id_to_order[in_id]
            else:
                break

    def reorder_remaining_instances(self, new_id_order, preserve_order):

        # Preserve the ordering the user has seen so far for data they've
        # annotated. This also includes items that *other* users have annotated
        # to ensure all items get the same number of annotations (otherwise
        # these items might get re-ordered farther away)
        new_order = [iid for iid in self.instance_id_ordering if iid in preserve_order]

        # Now add all the other IDs
        for iid in new_id_order:
            if iid not in self.instance_id_to_label_to_value:
                new_order.append(iid)

        assert len(new_order) == len(self.instance_id_ordering)

        # Update the user's state
        self.instance_id_ordering = new_order
        self.instance_id_to_order = self.generate_id_order_mapping(self.instance_id_ordering)

    def parse_time_string(self, time_string):
        """
        Parse the time string generated by front end,
        e.g., 'time_string': 'Time spent: 0d 0h 0m 5s '
        """
        time_dict = {}
        items = time_string.strip().split(" ")
        if len(items) != 6:
            return None
        time_dict["day"] = int(items[2][:-1])
        time_dict["hour"] = int(items[3][:-1])
        time_dict["minute"] = int(items[4][:-1])
        time_dict["second"] = int(items[5][:-1])
        time_dict["total_seconds"] = (
            time_dict["second"] + 60 * time_dict["minute"] + 3600 * time_dict["hour"]
        )

        return time_dict

    def total_working_time(self):
        """
        Calculate the amount of time a user have spend on annotation.

        Handles both legacy dict format (with time_string) and new BehavioralData objects.
        """
        from potato.interaction_tracking import BehavioralData

        total_working_seconds = 0
        for inst_id in self.instance_id_to_behavioral_data:
            bd = self.instance_id_to_behavioral_data[inst_id]

            # Handle BehavioralData objects (new format)
            if isinstance(bd, BehavioralData):
                total_working_seconds += bd.total_time_ms / 1000.0
            # Handle dict format (legacy)
            elif isinstance(bd, dict):
                time_string = bd.get("time_string")
                if time_string:
                    parsed = self.parse_time_string(time_string)
                    if parsed:
                        total_working_seconds += parsed["total_seconds"]

        if total_working_seconds < 60:
            total_working_time_str = str(int(total_working_seconds)) + " seconds"
        elif total_working_seconds < 3600:
            total_working_time_str = str(round(total_working_seconds / 60, 1)) + " minutes"
        else:
            total_working_time_str = str(round(total_working_seconds / 3600, 1)) + " hours"

        return (total_working_seconds, total_working_time_str)

    def generate_user_statistics(self):
        statistics = {
            "Annotated instances": self.get_annotation_count(),
            "Total working time": self.total_working_time()[1],
            "Average time on each instance": "N/A",
        }
        if statistics["Annotated instances"] != 0:
            statistics["Average time on each instance"] = "%s seconds" % str(
                round(self.total_working_time()[0] / statistics["Annotated instances"], 1)
            )
        return statistics

    def to_json(self):

        def pp_to_tuple(pp: tuple[UserPhase,str]) -> tuple[str,str]:
            return (str(pp[0]), pp[1])

        def label_to_dict(l: Label) -> dict[str,any]:
            return {
                "schema": l.get_schema(),
                "name": l.get_name()
            }

        def span_to_dict(s: SpanAnnotation) -> dict[str,any]:
            return {
                "schema": s.get_schema(),
                "name": s.get_name(),
                "start": s.get_start(),
                "end": s.get_end(),
                "title": s.get_title()
            }

        def convert_label_dict(d: dict[Label, any]) -> list[tuple[dict[str], str]]:
            return [(label_to_dict(k), v) for k, v in d.items()]

        def convert_span_dict(d: dict[SpanAnnotation, any]) -> list[tuple[dict[str], str]]:
            return [(span_to_dict(k), v) for k, v in d.items()]

        # Do the easy cases first
        d = {
            'user_id': self.user_id,
            'instance_id_ordering': self.instance_id_ordering,
            'current_instance_index': self.current_instance_index,
            'current_phase_and_page': pp_to_tuple(self.current_phase_and_page),
            'completed_phase_and_pages':
                [ pp_to_tuple(pp) for pp in self.completed_phase_and_pages],
            'max_assignments': self.max_assignments,
        }
        # Serialize behavioral data (used for interaction tracking)
        d['instance_id_to_behavioral_data'] = {}
        for instance_id, bd in self.instance_id_to_behavioral_data.items():
            if hasattr(bd, 'to_dict'):
                d['instance_id_to_behavioral_data'][instance_id] = bd.to_dict()
            elif isinstance(bd, dict):
                d['instance_id_to_behavioral_data'][instance_id] = bd
            else:
                d['instance_id_to_behavioral_data'][instance_id] = {}
        d['instance_id_to_label_to_value'] = {k: convert_label_dict(v) for k,v in self.instance_id_to_label_to_value.items()}
        d['instance_id_to_span_to_value'] = {k: convert_span_dict(v) for k,v in self.instance_id_to_span_to_value.items()}
        d['phase_to_page_to_label_to_value'] = {str(k): {k2: convert_label_dict(v2) for k2, v2 in v.items()} for k, v in self.phase_to_page_to_label_to_value.items()}
        d['phase_to_page_to_span_to_value'] = {str(k): {k2: convert_span_dict(v2) for k2, v2 in v.items()} for k, v in self.phase_to_page_to_span_to_value.items()}

        # Save training state
        d['training_state'] = self.training_state.to_dict()

        # Save keyword highlight state for randomization consistency
        d['instance_id_to_keyword_highlight_state'] = self.instance_id_to_keyword_highlight_state

        return d

    def save(self, user_dir: str) -> None:
        '''Saves the user's state to disk using atomic write (temp file + rename).'''
        import tempfile

        # Convert the state to something JSON serializable
        user_state = self.to_json()

        # Ensure directory exists (use exist_ok to avoid race conditions)
        os.makedirs(user_dir, exist_ok=True)

        # Write atomically: write to temp file, then rename
        state_file = os.path.join(user_dir, 'user_state.json')

        # Create temp file in same directory to ensure atomic rename works
        fd, temp_path = tempfile.mkstemp(dir=user_dir, suffix='.tmp')
        try:
            with os.fdopen(fd, 'wt') as outf:
                json.dump(user_state, outf, indent=2)
                outf.flush()
                os.fsync(outf.fileno())  # Ensure data is written to disk
            # Atomic rename (works on POSIX, best-effort on Windows)
            os.replace(temp_path, state_file)
        except Exception:
            # Clean up temp file if something went wrong
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    @staticmethod
    def load(user_dir: str) -> UserState:
        '''Loads the user's state from disk'''
        state_file = os.path.join(user_dir, 'user_state.json')
        if not os.path.exists(state_file):
            raise ValueError(f'User state file not found for user in directory "{user_dir}"')

        with open(state_file, 'rt') as f:
            j = json.load(f)

        def to_label(d: dict[str,str]) -> Label:
            return Label(d['schema'], d['name'])

        def to_span(d: dict[str,str]) -> SpanAnnotation:
            return SpanAnnotation(d['schema'], d['name'], d['title'], int(d['start']), int(d['end']))

        def to_phase_and_page(t: tuple[str,str]) -> tuple[UserPhase,str]:
            return (UserPhase.fromstr(t[0]), t[1])

        user_state = InMemoryUserState(j['user_id'], j['max_assignments'])

        user_state.instance_id_ordering = j['instance_id_ordering']
        user_state.assigned_instance_ids = set(j['instance_id_ordering'])
        user_state.current_instance_index = j['current_instance_index']

        # Restore behavioral data (used for interaction tracking)
        from potato.interaction_tracking import BehavioralData
        behavioral_data = j.get('instance_id_to_behavioral_data', {})
        for instance_id, bd_dict in behavioral_data.items():
            if isinstance(bd_dict, dict):
                user_state.instance_id_to_behavioral_data[instance_id] = BehavioralData.from_dict(bd_dict)
            else:
                user_state.instance_id_to_behavioral_data[instance_id] = bd_dict

        for iid, l2v in j['instance_id_to_label_to_value'].items():
            user_state.instance_id_to_label_to_value[iid] = {to_label(k): v for k, v in l2v}

        for iid, s2v in j['instance_id_to_span_to_value'].items():
            user_state.instance_id_to_span_to_value[iid] = {to_span(k): v for k, v in s2v}

        for phase, p2l2lv in j['phase_to_page_to_label_to_value'].items():
            phase = UserPhase.fromstr(phase)
            for page, lv_list in p2l2lv.items():
                for lv in lv_list:
                    label = lv[0]
                    label = to_label(label)
                    value = lv[1]
                    user_state.phase_to_page_to_label_to_value[phase][page][label] = value

        for phase, p2s2v in j['phase_to_page_to_span_to_value'].items():
            phase = UserPhase.fromstr(phase)
            for page, sv_list in p2s2v.items():
                for sv in sv_list:
                    span = sv[0]
                    span = to_span(span)
                    value = sv[1]
                    user_state.phase_to_page_to_span_to_value[phase][page][span] = value

        # These require converting the dictionaries back to the original types
        user_state.current_phase_and_page = to_phase_and_page(j['current_phase_and_page'])
        user_state.completed_phase_and_pages = [
            to_phase_and_page(pp) for pp in j['completed_phase_and_pages']
        ]

        # Restore training state if present
        if 'training_state' in j:
            user_state.training_state = TrainingState.from_dict(j['training_state'])

        # Restore category qualification data if present
        if 'qualified_categories' in j:
            user_state.qualified_categories = set(j['qualified_categories'])
        if 'category_qualification_scores' in j:
            user_state.category_qualification_scores = j['category_qualification_scores']

        # Restore keyword highlight state if present
        if 'instance_id_to_keyword_highlight_state' in j:
            user_state.instance_id_to_keyword_highlight_state = j['instance_id_to_keyword_highlight_state']

        # Restore span link annotations if present
        if 'instance_id_to_link_to_value' in j:
            for instance_id, links_dict in j['instance_id_to_link_to_value'].items():
                user_state.instance_id_to_link_to_value[instance_id] = {
                    link_id: SpanLink.from_dict(link_data)
                    for link_id, link_data in links_dict.items()
                }

        return user_state

    def add_annotation(self, instance_id, annotation):
        """Add a label annotation for the given instance."""
        # Store the annotation as a dict under the instance_id
        self.instance_id_to_label_to_value[instance_id].update(annotation)

    # Annotation history implementation
    def add_annotation_action(self, action: AnnotationAction) -> None:
        """Add an annotation action to the history."""
        self.annotation_history.append(action)
        self.instance_action_history[action.instance_id].append(action)

        # Update performance metrics
        self._update_performance_metrics()

        # Update activity time
        self.last_activity_time = action.timestamp

    def _update_performance_metrics(self) -> None:
        """Update performance metrics based on recent actions."""
        if not self.annotation_history:
            return

        # Calculate metrics for last 100 actions (for performance)
        recent_actions = self.annotation_history[-100:]
        metrics = AnnotationHistoryManager.calculate_performance_metrics(recent_actions)

        self.performance_metrics.update(metrics)
        if self.annotation_history:
            self.performance_metrics['last_action_timestamp'] = self.annotation_history[-1].timestamp

    def get_annotation_history(self, instance_id: Optional[str] = None) -> List[AnnotationAction]:
        """Get annotation history, optionally filtered by instance."""
        if instance_id:
            return self.instance_action_history.get(instance_id, [])
        return self.annotation_history.copy()

    def get_recent_actions(self, minutes: int = 5) -> List[AnnotationAction]:
        """Get actions from the last N minutes."""
        cutoff_time = datetime.datetime.now() - datetime.timedelta(minutes=minutes)
        return [action for action in self.annotation_history if action.timestamp >= cutoff_time]

    def get_suspicious_activity(self) -> List[AnnotationAction]:
        """Identify potentially suspicious activity (very fast annotations)."""
        if not self.annotation_history:
            return []

        # Get last 50 actions for analysis
        recent_actions = self.annotation_history[-50:]
        suspicious_analysis = AnnotationHistoryManager.detect_suspicious_activity(recent_actions)
        return suspicious_analysis['suspicious_actions']

    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get current performance metrics."""
        return self.performance_metrics.copy()

    def start_session(self, session_id: str) -> None:
        """Start a new annotation session."""
        self.session_start_time = datetime.datetime.now()
        self.current_session_id = session_id
        self.last_activity_time = self.session_start_time

    def end_session(self) -> None:
        """End the current annotation session."""
        self.session_start_time = None
        self.current_session_id = None

    # Training-related method implementations
    def get_training_state(self) -> TrainingState:
        """Get the current training state."""
        return self.training_state

    def update_training_answer(self, instance_id: str, annotations: Dict[str, Any]) -> None:
        """Update training answer and track attempts."""
        # Count attempts for this question
        attempts = 1
        if instance_id in self.training_state.completed_questions:
            attempts = self.training_state.completed_questions[instance_id]['attempts'] + 1

        # Store the annotations in the phase-specific storage
        if self.current_phase_and_page[0] == UserPhase.TRAINING:
            for schema_name, label_value in annotations.items():
                # Create a Label object for storage
                label = Label(schema_name, schema_name)  # Using schema_name as both schema and name
                self.phase_to_page_to_label_to_value[UserPhase.TRAINING][self.current_phase_and_page[1]][label] = label_value

    def check_training_pass(self, instance_id: str, correct_answers: Dict[str, Any]) -> bool:
        """Check if the user's answer for a specific instance is correct."""
        # Get the user's annotations for this instance
        user_annotations = {}
        if self.current_phase_and_page[0] == UserPhase.TRAINING:
            page = self.current_phase_and_page[1]
            for label, value in self.phase_to_page_to_label_to_value[UserPhase.TRAINING][page].items():
                user_annotations[label.get_schema()] = value

        # Compare user annotations with correct answers
        is_correct = True
        for schema_name, correct_value in correct_answers.items():
            if schema_name not in user_annotations:
                is_correct = False
                break
            if user_annotations[schema_name] != correct_value:
                is_correct = False
                break

        # Update training state with the result
        attempts = 1
        if instance_id in self.training_state.completed_questions:
            attempts = self.training_state.completed_questions[instance_id]['attempts'] + 1

        self.training_state.add_answer(instance_id, is_correct, attempts)
        return is_correct

    def get_current_training_instance(self) -> Optional[Item]:
        """Get the current training instance."""
        if not self.training_state.training_instances:
            return None

        current_index = self.training_state.get_current_question_index()
        if current_index >= len(self.training_state.training_instances):
            return None

        instance_id = self.training_state.training_instances[current_index]
        # Import here to avoid circular imports
        from potato.flask_server import get_training_instances
        training_items = get_training_instances()

        for item in training_items:
            if item.get_id() == instance_id:
                return item
        return None

    def advance_training_question(self) -> bool:
        """Advance to the next training question."""
        current_index = self.training_state.get_current_question_index()
        if current_index < len(self.training_state.training_instances) - 1:
            self.training_state.set_current_question_index(current_index + 1)
            return True
        return False

    def reset_training_state(self) -> None:
        """Reset the training state."""
        self.training_state = TrainingState()

    # =========================================================================
    # Category Qualification Methods
    # =========================================================================

    def add_qualified_category(self, category: str, score: float = 1.0) -> None:
        """
        Add a category that the user has qualified for.

        Args:
            category: The category name
            score: The qualification score (accuracy) for this category
        """
        self.qualified_categories.add(category)
        self.category_qualification_scores[category] = score

    def remove_qualified_category(self, category: str) -> None:
        """Remove a category from the user's qualifications."""
        self.qualified_categories.discard(category)
        self.category_qualification_scores.pop(category, None)

    def get_qualified_categories(self) -> Set[str]:
        """Get the set of categories the user has qualified for."""
        return self.qualified_categories.copy()

    def is_qualified_for_category(self, category: str) -> bool:
        """Check if the user is qualified for a specific category."""
        return category in self.qualified_categories

    def get_category_qualification_score(self, category: str) -> Optional[float]:
        """Get the qualification score for a specific category."""
        return self.category_qualification_scores.get(category)

    def get_all_category_qualification_scores(self) -> Dict[str, float]:
        """Get all category qualification scores."""
        return self.category_qualification_scores.copy()

    def calculate_and_set_qualifications(self, threshold: float = 0.7, min_questions: int = 1) -> List[str]:
        """
        Calculate qualifications from training state and update qualified_categories.

        This method reads the category scores from the training state, determines
        which categories the user qualifies for based on the threshold and minimum
        questions, and updates the qualified_categories set.

        Args:
            threshold: Minimum accuracy required to qualify (0.0 to 1.0)
            min_questions: Minimum number of questions answered in category

        Returns:
            List of newly qualified category names
        """
        newly_qualified = []
        training_state = self.get_training_state()

        for category, score in training_state.category_scores.items():
            total = score['total']
            correct = score['correct']

            if total >= min_questions:
                accuracy = correct / total if total > 0 else 0.0
                if accuracy >= threshold:
                    if category not in self.qualified_categories:
                        newly_qualified.append(category)
                    self.add_qualified_category(category, accuracy)

        return newly_qualified


class InMemoryUserState(UserState):

    def __init__(self, user_id: str, max_assignments: int = -1):

        self.user_id = user_id

        # This data struction records the specific ordering for which instances have been
        # labeled so that, should orderings differ between users, we can still determine
        # the previous and next instances if a user navigates back and forth.
        self.instance_id_ordering = []

        # Utilit data structure for O(1) look up of whether some ID is already in our ordering
        self.assigned_instance_ids = set()

        # This is the index in instance_id_ordering that the user is currently being shown.
        self.current_instance_index = -1

        # TODO: Put behavioral information of each instance with the labels
        # together however, that requires too many changes of the data structure
        # therefore, we contruct a separate dictionary to save all the
        # behavioral information (e.g. time, click, ..)
        self.instance_id_to_behavioral_data = defaultdict(dict)

        # The data structure to save the labels (e.g. multiselect, radio, text) that
        # a user labels for each instance.
        self.instance_id_to_label_to_value = defaultdict(dict)

        # For non-annotation data, we save the responses for each page in separate
        # dictionaries to keep the data organized and make state-tracking easier.
        self.phase_to_page_to_label_to_value = defaultdict(lambda: defaultdict(dict))

        # The data structure to save the span annotations that a user labels for each
        # instance. The key is the instance id and the value is a list of span
        # annotations
        self.instance_id_to_span_to_value = defaultdict(dict)

        # For non-annotation data, we save any span labels for each page in separate
        # dictionaries to keep the data organized and make state-tracking easier.
        self.phase_to_page_to_span_to_value = defaultdict(lambda: defaultdict(dict))

        # This keeps track of which page the user is on in the annotation process.
        # All users start at the LOGIN page.
        self.current_phase_and_page = (UserPhase.LOGIN, None)

        # This data structure keeps track of which phases and pages the user has completed
        # and shouldn't include the current phase (yet)
        self.completed_phase_and_pages = defaultdict(set)

        # How many items a user can be assigned
        self.max_assignments = max_assignments

        # Caches the ai hints
        self.ai_hints = defaultdict(dict)

        # New: Annotation history tracking
        self.annotation_history: List[AnnotationAction] = []
        self.instance_action_history: Dict[str, List[AnnotationAction]] = defaultdict(list)

        # New: Session tracking
        self.session_start_time: Optional[datetime.datetime] = None
        self.last_activity_time: Optional[datetime.datetime] = None
        self.current_session_id: Optional[str] = None

        # New: Performance metrics
        self.performance_metrics: Dict[str, Any] = {
            'total_actions': 0,
            'average_action_time_ms': 0,
            'fastest_action_time_ms': float('inf'),
            'slowest_action_time_ms': 0,
            'actions_per_minute': 0,
            'last_action_timestamp': None
        }

        # New: Training state tracking
        self.training_state = TrainingState()

        # Category qualification tracking for category-based assignment
        self.qualified_categories: Set[str] = set()
        self.category_qualification_scores: Dict[str, float] = {}  # category -> accuracy score

        # ICL verification tracking - stores verification tasks assigned to this user
        # Maps instance_id -> schema_name for instances that are LLM verification tasks
        self.icl_verification_tasks: Dict[str, str] = {}

        # Keyword highlight state per instance for randomization consistency
        # Maps instance_id -> {highlights: [...], seed: int, settings: {...}}
        # This ensures the same user sees the same highlights for an instance across navigation
        self.instance_id_to_keyword_highlight_state: Dict[str, Dict[str, Any]] = {}

        # Span link annotations - stores relationships between spans
        # Maps instance_id -> {link_id -> SpanLink}
        self.instance_id_to_link_to_value: Dict[str, Dict[str, SpanLink]] = defaultdict(dict)

    def hint_exists(self, instance_id: str) -> bool:
        return instance_id in self.ai_hints

    def get_hint(self, instance_id: str) -> str:
        return self.ai_hints.get(instance_id)

    def cache_hint(self, instance_id: str, hint: str) -> None:
        self.ai_hints[instance_id] = hint

    def get_keyword_highlight_state(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Get cached keyword highlight state for an instance.

        Returns the stored randomization state for keyword highlights, or None
        if no state has been cached yet for this instance.

        Args:
            instance_id: The instance ID to get state for

        Returns:
            Dict with 'highlights', 'seed', 'settings' keys, or None
        """
        return self.instance_id_to_keyword_highlight_state.get(instance_id)

    def set_keyword_highlight_state(self, instance_id: str, state: Dict[str, Any]) -> None:
        """Cache keyword highlight state for an instance.

        Stores the randomization state so that the same highlights are shown
        when the user returns to this instance.

        Args:
            instance_id: The instance ID to cache state for
            state: Dict with 'highlights', 'seed', 'settings' keys
        """
        self.instance_id_to_keyword_highlight_state[instance_id] = state

    def add_new_assigned_data(self, new_assigned_data):
        """
        Add new assigned data to the user state
        """
        for key in new_assigned_data:
            self.instance_id_to_data[key] = new_assigned_data[key]
            self.instance_id_ordering.append(key)
        self.instance_id_to_order = self.generate_id_order_mapping(self.instance_id_ordering)

    def advance_to_phase(self, phase: UserPhase, page: str) -> None:
        # print('advancing to', phase, page)
        self.current_phase_and_page = (phase, page)

    def assign_instance(self, item: Item) -> None:
        ''' Assigns an instance to the user for annotation'''

        # check that the item has not already been assigned to the user
        if item.get_id() in self.assigned_instance_ids:
            return
        #print('Assigned %s to %s' % (item.get_id(), self.instance_id_ordering   ))
        self.instance_id_ordering.append(item.get_id())
        self.assigned_instance_ids.add(item.get_id())
        # If this is the first assigned instance, set the current instance to be the first one
        if self.current_instance_index == -1:
            self.current_instance_index = 0

    def get_current_phase_and_page(self) -> tuple[UserPhase, str]:
        return self.current_phase_and_page

    def set_current_phase_and_page(self, phase_and_page: tuple[UserPhase, str]) -> None:
        #print('set phase to', phase_and_page)
        self.current_phase_and_page = phase_and_page

    def get_current_instance(self) -> Item:
        if self.current_instance_index < 0:
            return None

        if self.current_instance_index >= len(self.instance_id_ordering):
            return None
        inst_id = self.instance_id_ordering[self.current_instance_index]
        return get_item_state_manager().get_item(inst_id)

    def get_current_instance_id(self) -> str:
        '''Returns the ID of the instance that the user is currently annotating'''
        return self.get_current_instance().get_id()

    def get_labels(self) -> dict[str, dict[str, str]]:
        return self.labels

    def get_span_annotations(self):
        return self.span_annotations

    def add_label_annotation(self, instance_id: str, label: Label, value: any) -> None:
        if self.current_phase_and_page[0] == UserPhase.ANNOTATION:
            self.instance_id_to_label_to_value[instance_id][label] = value
        else:
            self.phase_to_page_to_label_to_value[self.current_phase_and_page[0]][self.current_phase_and_page[1]][label] = value
        #print('add_labels ->', self.instance_id_to_label_to_value)

    def add_span_annotation(self, instance_id: str, label: SpanAnnotation, value: any) -> None:
        '''Adds a set of span annotations to the instance or if the user is not
           in the annotation phase, to the page associated with the current phase'''

        if self.current_phase_and_page[0] == UserPhase.ANNOTATION:
            # Ensure the instance_id exists in the dictionary
            if instance_id not in self.instance_id_to_span_to_value:
                self.instance_id_to_span_to_value[instance_id] = {}

            self.instance_id_to_span_to_value[instance_id][label] = value
        else:
            # Handle non-annotation phase storage
            phase = self.current_phase_and_page[0]
            page = self.current_phase_and_page[1]

            if phase not in self.phase_to_page_to_span_to_value:
                self.phase_to_page_to_span_to_value[phase] = {}
            if page not in self.phase_to_page_to_span_to_value[phase]:
                self.phase_to_page_to_span_to_value[phase][page] = {}

            self.phase_to_page_to_span_to_value[phase][page][label] = value

    # =========================================================================
    # Span Link Annotation Methods
    # =========================================================================

    def add_link_annotation(self, instance_id: str, link: SpanLink) -> None:
        """
        Add a link annotation connecting multiple spans.

        Args:
            instance_id: The instance ID the link belongs to
            link: The SpanLink object representing the relationship
        """
        if instance_id not in self.instance_id_to_link_to_value:
            self.instance_id_to_link_to_value[instance_id] = {}

        self.instance_id_to_link_to_value[instance_id][link.get_id()] = link

    def get_link_annotations(self, instance_id: str) -> Dict[str, SpanLink]:
        """
        Get all link annotations for an instance.

        Args:
            instance_id: The instance ID to get links for

        Returns:
            Dictionary mapping link_id -> SpanLink
        """
        return self.instance_id_to_link_to_value.get(instance_id, {})

    def get_link_annotation(self, instance_id: str, link_id: str) -> Optional[SpanLink]:
        """
        Get a specific link annotation by ID.

        Args:
            instance_id: The instance ID
            link_id: The link ID to retrieve

        Returns:
            SpanLink if found, None otherwise
        """
        links = self.instance_id_to_link_to_value.get(instance_id, {})
        return links.get(link_id)

    def remove_link_annotation(self, instance_id: str, link_id: str) -> bool:
        """
        Remove a link annotation.

        Args:
            instance_id: The instance ID
            link_id: The link ID to remove

        Returns:
            True if the link was removed, False if not found
        """
        if instance_id in self.instance_id_to_link_to_value:
            if link_id in self.instance_id_to_link_to_value[instance_id]:
                del self.instance_id_to_link_to_value[instance_id][link_id]
                return True
        return False

    def get_links_for_span(self, instance_id: str, span_id: str) -> List[SpanLink]:
        """
        Get all links that include a specific span.

        Args:
            instance_id: The instance ID
            span_id: The span ID to find links for

        Returns:
            List of SpanLink objects that include the given span
        """
        result = []
        links = self.instance_id_to_link_to_value.get(instance_id, {})
        for link in links.values():
            if span_id in link.get_span_ids():
                result.append(link)
        return result

    def clear_link_annotations(self, instance_id: str) -> None:
        """
        Clear all link annotations for an instance.

        Args:
            instance_id: The instance ID to clear links for
        """
        if instance_id in self.instance_id_to_link_to_value:
            self.instance_id_to_link_to_value[instance_id] = {}

    def get_current_instance_index(self):
        '''Returns the index of the item the user is annotating within the list of items
           that the user has currently been assigned to annotate'''

        #print('GET current_instance_index ->', self.current_instance_index)
        return self.current_instance_index

    def go_back(self) -> bool:
        '''Moves the user back to the previous instance and returns True if successful'''
        if self.current_instance_index > 0:
            self.current_instance_index -= 1
            return True
        return False
        #print('GO BACK current_instance_index ->', self.current_instance_index)

    def is_at_end_index(self) -> bool:

        # TODO: Rename this function to be something more descriptive
        return self.current_instance_index == len(self.instance_id_ordering) - 1

    def go_forward(self) -> bool:
        '''Moves the user forward to the next instance and returns True if successful'''
        #print('GO FORWARD current_instance_index ->', self.current_instance_index)
        #print('GO FORWARD instance_id_ordering ->', self.instance_id_ordering)

        # DEBUG: Add detailed logging

        if self.current_instance_index < len(self.instance_id_ordering) - 1:
            self.current_instance_index += 1
            return True
        else:
            return False

    def get_current_phase_and_page(self) -> tuple[UserPhase, str]:
        '''Returns the current phase and page that the user is on'''
        return self.current_phase_and_page

    def go_to_index(self, instance_index: int) -> None:
        '''Moves the annotator's view to the instance at the specified index'''
        if instance_index < len(self.instance_id_ordering) and instance_index >= 0:
            self.current_instance_index = instance_index

    def get_all_annotations(self) -> dict[Item, list[SpanAnnotation|Label]]:
        """
        Returns all annotations (label and span) for all annotated instances
        """
        labeled = set(self.instance_id_to_label_to_value.keys()) | set(
            self.instance_id_to_span_to_value.keys()
        )

        anns = {}
        for iid in labeled:
            labels = {}
            if iid in self.instance_id_to_label_to_value:
                labels = self.instance_id_to_label_to_value[iid]
            spans = {}
            if iid in self.instance_id_to_span_to_value:
                spans = self.instance_id_to_span_to_value[iid]

            anns[iid] = {"labels": labels, "spans": spans}

        return anns

    def get_label_annotations(self, instance_id) -> dict[str,list[Label]]:
        """
        Returns a mapping from each schema to the label-based annotations for the instance.
        """
        # print('get_labels ->', self.instance_id_to_label_to_value)
        if instance_id not in self.instance_id_to_label_to_value:
            return {}
        # NB: Should this be a view/copy?
        return self.instance_id_to_label_to_value[instance_id]

    def get_span_annotations(self, instance_id) -> dict[str,list[SpanAnnotation]]:
        """
        Returns a mapping from each schema to the span annotations for that schema.
        """
        if instance_id not in self.instance_id_to_span_to_value:
            return {}

        return self.instance_id_to_span_to_value[instance_id]

    def get_user_id(self) -> str:
        '''Returns the user ID for this user'''
        return self.user_id

    def get_annotated_instance_ids(self) -> set[str]:
        return set(self.instance_id_to_label_to_value.keys())\
                    | set(self.instance_id_to_span_to_value.keys())

    def get_annotation_count(self) -> int:
        '''Returns the total number of instances annotated by this user.'''
        return len(self.get_annotated_instance_ids())

    def get_assigned_instance_count(self):
        #print('instance_id_ordering ->', self.instance_id_ordering)
        return len(self.instance_id_ordering)

    def get_assigned_instance_ids(self) -> set[str]:
        """Returns the set of assigned instance IDs"""
        return self.assigned_instance_ids.copy()

    def set_prestudy_status(self, whether_passed):
        if self.prestudy_passed is not None:
            return False
        self.prestudy_passed = whether_passed
        return True

    def get_prestudy_status(self):
        """
        Check if the user has passed the prestudy test.
        """
        return self.prestudy_passed

    def get_consent_status(self):
        """
        Check if the user has agreed to participate this study.
        """
        return self.consent_agreed

    def has_assignments(self) -> bool:
        """Returns True if the user has been assigned any instances to annotate"""
        return len(self.instance_id_ordering) > 0

    def has_annotated(self, instance_id: str) -> bool:
        '''Returns True if the user has annotated the instance with the given ID'''
        return instance_id in self.instance_id_to_label_to_value \
            or instance_id in self.instance_id_to_span_to_value

    def clear_all_annotations(self) -> None:
        '''Clears all annotations for this user'''
        self.instance_id_to_label_to_value.clear()
        self.instance_id_to_span_to_value.clear()
        self.instance_id_to_behavioral_data.clear()
        self.ai_hints.clear()

    def has_remaining_assignments(self) -> bool:
        """Returns True if the user has any remaining instances to annotate. If the user
           does not have a maximum number of assignments, this will always return True."""
        return self.max_assignments < 0 or len(self.get_annotated_instance_ids()) < self.max_assignments

    def find_next_unannotated_index(self) -> Optional[int]:
        """
        Find the index of the next unannotated instance after the current position.

        Searches forward from the current position, wrapping around to the beginning
        if necessary. Returns None if all instances have been annotated.

        Returns:
            Optional[int]: Index of the next unannotated instance, or None if all
                          instances are annotated.
        """
        current_idx = self.get_current_instance_index()
        annotated_ids = self.get_annotated_instance_ids()
        total_instances = len(self.instance_id_ordering)

        if total_instances == 0:
            return None

        # Search forward from current position
        for i in range(current_idx + 1, total_instances):
            instance_id = self.instance_id_ordering[i]
            if instance_id not in annotated_ids:
                return i

        # Wrap around and search from beginning to current position
        for i in range(0, current_idx):
            instance_id = self.instance_id_ordering[i]
            if instance_id not in annotated_ids:
                return i

        # Check current position (in case it's the only unannotated item)
        if current_idx < total_instances:
            instance_id = self.instance_id_ordering[current_idx]
            if instance_id not in annotated_ids:
                return current_idx

        return None  # All instances annotated

    def find_prev_unannotated_index(self) -> Optional[int]:
        """
        Find the index of the previous unannotated instance before the current position.

        Searches backward from the current position, wrapping around to the end
        if necessary. Returns None if all instances have been annotated.

        Returns:
            Optional[int]: Index of the previous unannotated instance, or None if all
                          instances are annotated.
        """
        current_idx = self.get_current_instance_index()
        annotated_ids = self.get_annotated_instance_ids()
        total_instances = len(self.instance_id_ordering)

        if total_instances == 0:
            return None

        # Search backward from current position
        for i in range(current_idx - 1, -1, -1):
            instance_id = self.instance_id_ordering[i]
            if instance_id not in annotated_ids:
                return i

        # Wrap around and search from end to current position
        for i in range(total_instances - 1, current_idx, -1):
            instance_id = self.instance_id_ordering[i]
            if instance_id not in annotated_ids:
                return i

        # Check current position (in case it's the only unannotated item)
        if current_idx < total_instances:
            instance_id = self.instance_id_ordering[current_idx]
            if instance_id not in annotated_ids:
                return current_idx

        return None  # All instances annotated

    # === ICL Verification Tracking Methods ===

    def mark_instance_as_verification(self, instance_id: str, schema_name: str) -> None:
        """
        Mark an instance as an ICL verification task.

        This is called when assigning a verification task to the user. The user
        won't see that it's a verification - it appears as a normal annotation task
        (blind labeling). After they annotate it, we compare their label to the LLM's.

        Args:
            instance_id: The instance ID being verified
            schema_name: The schema being verified
        """
        self.icl_verification_tasks[instance_id] = schema_name

    def is_verification_task(self, instance_id: str) -> bool:
        """
        Check if an instance is a verification task.

        Args:
            instance_id: The instance ID to check

        Returns:
            True if this is a verification task
        """
        return instance_id in self.icl_verification_tasks

    def get_verification_schema(self, instance_id: str) -> Optional[str]:
        """
        Get the schema name for a verification task.

        Args:
            instance_id: The instance ID

        Returns:
            Schema name if this is a verification task, None otherwise
        """
        return self.icl_verification_tasks.get(instance_id)

    def complete_verification_task(self, instance_id: str) -> Optional[str]:
        """
        Complete and remove a verification task, returning the schema.

        This should be called after the user annotates a verification task,
        so we can record the verification result.

        Args:
            instance_id: The instance ID

        Returns:
            Schema name if this was a verification task, None otherwise
        """
        return self.icl_verification_tasks.pop(instance_id, None)

    def get_pending_verification_tasks(self) -> Dict[str, str]:
        """
        Get all pending verification tasks for this user.

        Returns:
            Dictionary mapping instance_id -> schema_name
        """
        return self.icl_verification_tasks.copy()

    def set_max_assignments(self, max_assignments: int) -> None:
        '''Sets the maximum number of items that this user can be assigned'''
        self.max_assignments = max_assignments

    def get_max_assignments(self) -> int:
        '''Returns the maximum number of items that this user can be assigned'''
        return self.max_assignments

    def generate_id_order_mapping(self, id_order):
        """Generate a mapping from instance ID to its position in the ordering."""
        return {id_: i for i, id_ in enumerate(id_order)}

    def update(self, annotation_order, annotated_instances):
        """
        Updates the entire state of annotations for this user by inserting
        all the data in annotated_instances into this user's state. Typically
        this data is loaded from a file

        NOTE: This is only used to update the entire list of annotations,
        normally when loading all the saved data

        :annotation_order: a list of string instance IDs in the order that this
        user should see those instances.
        :annotated_instances: a list of dictionary objects detailing the
        annotations on each item.
        """

        self.instance_id_to_label_to_value = {}
        for inst in annotated_instances:

            inst_id = inst["id"]
            label_annotations = inst["label_annotations"]
            span_annotations = inst["span_annotations"]

            self.instance_id_to_label_to_value[inst_id] = label_annotations
            self.instance_id_to_span_to_value[inst_id] = span_annotations

            behavior_dict = inst.get("behavioral_data", {})
            self.instance_id_to_behavioral_data[inst_id] = behavior_dict

            # TODO: move this code somewhere else so consent is organized
            # separately
            if re.search("consent", inst_id):
                consent_key = "I want to participate in this research and continue with the study."
                self.consent_agreed = False
                if label_annotations[consent_key].get("Yes") == "true":
                    self.consent_agreed = True

        self.instance_id_ordering = annotation_order
        self.instance_id_to_order = self.generate_id_order_mapping(self.instance_id_ordering)

        # Set the current item to be the one after the last thing that was
        # annotated
        # self.current_instance_index = min(len(self.instance_id_to_labeling),
        #                           len(self.instance_id_ordering)-1)

        annotated_set = set([it['id'] for it in annotated_instances])
        self.current_instance_index = self.instance_id_to_order[annotated_instances[-1]['id']]
        for in_id in self.instance_id_ordering:
            if in_id[-4:] == 'html':
                continue
            if in_id in annotated_set:
                self.current_instance_index = self.instance_id_to_order[in_id]
            else:
                break

    def reorder_remaining_instances(self, new_id_order, preserve_order):

        # Preserve the ordering the user has seen so far for data they've
        # annotated. This also includes items that *other* users have annotated
        # to ensure all items get the same number of annotations (otherwise
        # these items might get re-ordered farther away)
        new_order = [iid for iid in self.instance_id_ordering if iid in preserve_order]

        # Now add all the other IDs
        for iid in new_id_order:
            if iid not in self.instance_id_to_label_to_value:
                new_order.append(iid)

        assert len(new_order) == len(self.instance_id_ordering)

        # Update the user's state
        self.instance_id_ordering = new_order
        self.instance_id_to_order = self.generate_id_order_mapping(self.instance_id_ordering)

    def parse_time_string(self, time_string):
        """
        Parse the time string generated by front end,
        e.g., 'time_string': 'Time spent: 0d 0h 0m 5s '
        """
        time_dict = {}
        items = time_string.strip().split(" ")
        if len(items) != 6:
            return None
        time_dict["day"] = int(items[2][:-1])
        time_dict["hour"] = int(items[3][:-1])
        time_dict["minute"] = int(items[4][:-1])
        time_dict["second"] = int(items[5][:-1])
        time_dict["total_seconds"] = (
            time_dict["second"] + 60 * time_dict["minute"] + 3600 * time_dict["hour"]
        )

        return time_dict

    def total_working_time(self):
        """
        Calculate the amount of time a user have spend on annotation.

        Handles both legacy dict format (with time_string) and new BehavioralData objects.
        """
        from potato.interaction_tracking import BehavioralData

        total_working_seconds = 0
        for inst_id in self.instance_id_to_behavioral_data:
            bd = self.instance_id_to_behavioral_data[inst_id]

            # Handle BehavioralData objects (new format)
            if isinstance(bd, BehavioralData):
                total_working_seconds += bd.total_time_ms / 1000.0
            # Handle dict format (legacy)
            elif isinstance(bd, dict):
                time_string = bd.get("time_string")
                if time_string:
                    parsed = self.parse_time_string(time_string)
                    if parsed:
                        total_working_seconds += parsed["total_seconds"]

        if total_working_seconds < 60:
            total_working_time_str = str(int(total_working_seconds)) + " seconds"
        elif total_working_seconds < 3600:
            total_working_time_str = str(round(total_working_seconds / 60, 1)) + " minutes"
        else:
            total_working_time_str = str(round(total_working_seconds / 3600, 1)) + " hours"

        return (total_working_seconds, total_working_time_str)

    def generate_user_statistics(self):
        statistics = {
            "Annotated instances": self.get_annotation_count(),
            "Total working time": self.total_working_time()[1],
            "Average time on each instance": "N/A",
        }
        if statistics["Annotated instances"] != 0:
            statistics["Average time on each instance"] = "%s seconds" % str(
                round(self.total_working_time()[0] / statistics["Annotated instances"], 1)
            )
        return statistics

    def to_json(self):

        def pp_to_tuple(pp: tuple[UserPhase,str]) -> tuple[str,str]:
            return (str(pp[0]), pp[1])

        def label_to_dict(l: Label) -> dict[str,any]:
            return {
                "schema": l.get_schema(),
                "name": l.get_name()
            }

        def span_to_dict(s: SpanAnnotation) -> dict[str,any]:
            return {
                "schema": s.get_schema(),
                "name": s.get_name(),
                "start": s.get_start(),
                "end": s.get_end(),
                "title": s.get_title()
            }

        def convert_label_dict(d: dict[Label, any]) -> list[tuple[dict[str], str]]:
            return [(label_to_dict(k), v) for k, v in d.items()]

        def convert_span_dict(d: dict[SpanAnnotation, any]) -> list[tuple[dict[str], str]]:
            return [(span_to_dict(k), v) for k, v in d.items()]

        # Do the easy cases first
        d = {
            'user_id': self.user_id,
            'instance_id_ordering': self.instance_id_ordering,
            'current_instance_index': self.current_instance_index,
            'current_phase_and_page': pp_to_tuple(self.current_phase_and_page),
            'completed_phase_and_pages':
                [ pp_to_tuple(pp) for pp in self.completed_phase_and_pages],
            'max_assignments': self.max_assignments,
        }
        # Serialize behavioral data (used for interaction tracking)
        d['instance_id_to_behavioral_data'] = {}
        for instance_id, bd in self.instance_id_to_behavioral_data.items():
            if hasattr(bd, 'to_dict'):
                d['instance_id_to_behavioral_data'][instance_id] = bd.to_dict()
            elif isinstance(bd, dict):
                d['instance_id_to_behavioral_data'][instance_id] = bd
            else:
                d['instance_id_to_behavioral_data'][instance_id] = {}
        d['instance_id_to_label_to_value'] = {k: convert_label_dict(v) for k,v in self.instance_id_to_label_to_value.items()}
        d['instance_id_to_span_to_value'] = {k: convert_span_dict(v) for k,v in self.instance_id_to_span_to_value.items()}
        d['phase_to_page_to_label_to_value'] = {str(k): {k2: convert_label_dict(v2) for k2, v2 in v.items()} for k, v in self.phase_to_page_to_label_to_value.items()}
        d['phase_to_page_to_span_to_value'] = {str(k): {k2: convert_span_dict(v2) for k2, v2 in v.items()} for k, v in self.phase_to_page_to_span_to_value.items()}

        d['training_state'] = self.training_state.to_dict()

        # Category qualification data
        d['qualified_categories'] = list(self.qualified_categories)
        d['category_qualification_scores'] = self.category_qualification_scores

        # Save keyword highlight state for randomization consistency
        d['instance_id_to_keyword_highlight_state'] = self.instance_id_to_keyword_highlight_state

        # Save span link annotations
        d['instance_id_to_link_to_value'] = {}
        for instance_id, links in self.instance_id_to_link_to_value.items():
            d['instance_id_to_link_to_value'][instance_id] = {
                link_id: link.to_dict() for link_id, link in links.items()
            }

        return d

    def save(self, user_dir: str) -> None:
        '''Saves the user's state to disk using atomic write (temp file + rename).'''
        import tempfile

        # Convert the state to something JSON serializable
        user_state = self.to_json()

        # Ensure directory exists (use exist_ok to avoid race conditions)
        os.makedirs(user_dir, exist_ok=True)

        # Write atomically: write to temp file, then rename
        state_file = os.path.join(user_dir, 'user_state.json')

        # Create temp file in same directory to ensure atomic rename works
        fd, temp_path = tempfile.mkstemp(dir=user_dir, suffix='.tmp')
        try:
            with os.fdopen(fd, 'wt') as outf:
                json.dump(user_state, outf, indent=2)
                outf.flush()
                os.fsync(outf.fileno())  # Ensure data is written to disk
            # Atomic rename (works on POSIX, best-effort on Windows)
            os.replace(temp_path, state_file)
        except Exception:
            # Clean up temp file if something went wrong
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    @staticmethod
    def load(user_dir: str) -> UserState:
        '''Loads the user's state from disk'''
        state_file = os.path.join(user_dir, 'user_state.json')
        if not os.path.exists(state_file):
            raise ValueError(f'User state file not found for user in directory "{user_dir}"')

        with open(state_file, 'rt') as f:
            j = json.load(f)

        def to_label(d: dict[str,str]) -> Label:
            return Label(d['schema'], d['name'])

        def to_span(d: dict[str,str]) -> SpanAnnotation:
            return SpanAnnotation(d['schema'], d['name'], d['title'], int(d['start']), int(d['end']))

        def to_phase_and_page(t: tuple[str,str]) -> tuple[UserPhase,str]:
            return (UserPhase.fromstr(t[0]), t[1])

        user_state = InMemoryUserState(j['user_id'], j['max_assignments'])

        user_state.instance_id_ordering = j['instance_id_ordering']
        user_state.assigned_instance_ids = set(j['instance_id_ordering'])
        user_state.current_instance_index = j['current_instance_index']

        # Restore behavioral data (used for interaction tracking)
        from potato.interaction_tracking import BehavioralData
        behavioral_data = j.get('instance_id_to_behavioral_data', {})
        for instance_id, bd_dict in behavioral_data.items():
            if isinstance(bd_dict, dict):
                user_state.instance_id_to_behavioral_data[instance_id] = BehavioralData.from_dict(bd_dict)
            else:
                user_state.instance_id_to_behavioral_data[instance_id] = bd_dict

        for iid, l2v in j['instance_id_to_label_to_value'].items():
            user_state.instance_id_to_label_to_value[iid] = {to_label(k): v for k, v in l2v}

        for iid, s2v in j['instance_id_to_span_to_value'].items():
            user_state.instance_id_to_span_to_value[iid] = {to_span(k): v for k, v in s2v}

        for phase, p2l2lv in j['phase_to_page_to_label_to_value'].items():
            phase = UserPhase.fromstr(phase)
            for page, lv_list in p2l2lv.items():
                for lv in lv_list:
                    label = lv[0]
                    label = to_label(label)
                    value = lv[1]
                    user_state.phase_to_page_to_label_to_value[phase][page][label] = value

        for phase, p2s2v in j['phase_to_page_to_span_to_value'].items():
            phase = UserPhase.fromstr(phase)
            for page, sv_list in p2s2v.items():
                for sv in sv_list:
                    span = sv[0]
                    span = to_span(span)
                    value = sv[1]
                    user_state.phase_to_page_to_span_to_value[phase][page][span] = value

        # These require converting the dictionaries back to the original types
        user_state.current_phase_and_page = to_phase_and_page(j['current_phase_and_page'])
        user_state.completed_phase_and_pages = [
            to_phase_and_page(pp) for pp in j['completed_phase_and_pages']
        ]

        # Restore training state if present
        if 'training_state' in j:
            user_state.training_state = TrainingState.from_dict(j['training_state'])

        # Restore category qualification data if present
        if 'qualified_categories' in j:
            user_state.qualified_categories = set(j['qualified_categories'])
        if 'category_qualification_scores' in j:
            user_state.category_qualification_scores = j['category_qualification_scores']

        # Restore keyword highlight state if present
        if 'instance_id_to_keyword_highlight_state' in j:
            user_state.instance_id_to_keyword_highlight_state = j['instance_id_to_keyword_highlight_state']

        # Restore span link annotations if present
        if 'instance_id_to_link_to_value' in j:
            for instance_id, links_dict in j['instance_id_to_link_to_value'].items():
                user_state.instance_id_to_link_to_value[instance_id] = {
                    link_id: SpanLink.from_dict(link_data)
                    for link_id, link_data in links_dict.items()
                }

        return user_state

    def add_annotation(self, instance_id, annotation):
        """Add a label annotation for the given instance."""
        # Store the annotation as a dict under the instance_id
        self.instance_id_to_label_to_value[instance_id].update(annotation)

