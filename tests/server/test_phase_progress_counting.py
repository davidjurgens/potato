"""
Phase Progress Counting Tests (Issue #87)

This module verifies that instance/question counting works correctly
across all phases of the annotation workflow:
1. Training phase - Question X of Y counting
2. Annotation phase - Instance X/Y counting
3. Prestudy/Poststudy - No interference with annotation counts
4. Phase transitions - Counts don't leak between phases

Tests verify the fix for issue #87 where the counter showed
"2/0 instances finished" after completing pre-study.
"""

import pytest
import json
import os
import sys
import tempfile
import yaml

# Add the project root to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def reset_singletons():
    """Reset all singleton managers for clean test state."""
    import potato.item_state_management
    import potato.user_state_management
    from potato.server_utils.config_module import clear_config

    potato.item_state_management.ITEM_STATE_MANAGER = None
    potato.user_state_management.USER_STATE_MANAGER = None
    clear_config()


def create_multi_phase_config(config_dir, **overrides):
    """Create a test configuration with multiple phases including prestudy."""
    config = {
        "debug": False,
        "max_annotations_per_user": 5,
        "max_annotations_per_item": -1,
        "assignment_strategy": "fixed_order",
        "annotation_task_name": "Phase Counting Test",
        "require_password": False,
        "authentication": {"method": "in_memory"},
        "data_files": ["test_data.json"],
        "item_properties": {
            "text_key": "text",
            "id_key": "id"
        },
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["Positive", "Negative", "Neutral"],
                "description": "Classify sentiment"
            }
        ],
        "training": {
            "enabled": True,
            "data_file": "training_data.json",
            "passing_criteria": {
                "min_correct": 2,
                "max_attempts": 3
            }
        },
        "task_dir": config_dir,
        "output_annotation_dir": config_dir,
        "site_dir": "default",
        "alert_time_each_instance": 10000000,
        "random_seed": 42
    }

    # Apply overrides
    for key, value in overrides.items():
        if isinstance(value, dict) and key in config and isinstance(config[key], dict):
            config[key].update(value)
        else:
            config[key] = value

    config_path = os.path.join(config_dir, 'config.yaml')
    with open(config_path, 'w') as f:
        yaml.dump(config, f)
    return config_path


def create_test_data(config_dir, num_items=10):
    """Create test data file."""
    test_data = [
        {"id": f"item_{i}", "text": f"This is test item {i}"}
        for i in range(1, num_items + 1)
    ]
    data_path = os.path.join(config_dir, 'test_data.json')
    with open(data_path, 'w') as f:
        json.dump(test_data, f)
    return data_path


def create_training_data(config_dir):
    """Create training data file."""
    training_data = {
        "training_instances": [
            {
                "id": "train_1",
                "text": "This is great!",
                "correct_answers": {"sentiment": "Positive"},
                "explanation": "The word 'great' indicates positive sentiment."
            },
            {
                "id": "train_2",
                "text": "This is terrible.",
                "correct_answers": {"sentiment": "Negative"},
                "explanation": "The word 'terrible' indicates negative sentiment."
            },
            {
                "id": "train_3",
                "text": "It is okay.",
                "correct_answers": {"sentiment": "Neutral"},
                "explanation": "The word 'okay' indicates neutral sentiment."
            }
        ]
    }
    data_path = os.path.join(config_dir, 'training_data.json')
    with open(data_path, 'w') as f:
        json.dump(training_data, f)
    return data_path


class TestAnnotationPhaseCounting:
    """Test instance counting in the annotation phase."""

    def test_initial_annotation_count_is_zero(self):
        """Test that annotation count starts at zero for new users."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_multi_phase_config(tmpdir, training={"enabled": False})
            create_test_data(tmpdir, num_items=10)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.item_state_management import init_item_state_manager
                from potato.user_state_management import init_user_state_manager
                from potato.phase import UserPhase

                class Args:
                    config_file = os.path.join(tmpdir, 'config.yaml')
                    verbose = False
                    very_verbose = False
                    customjs = None
                    customjs_hostname = None
                    debug = False
                    persist_sessions = False
                    require_password = None
                    port = None

                init_config(Args())
                ism = init_item_state_manager(config)
                usm = init_user_state_manager(config)

                # Load data
                with open(os.path.join(tmpdir, 'test_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                # Create user and advance to annotation phase
                usm.add_user("test_user")
                user_state = usm.get_user_state("test_user")
                user_state.advance_to_phase(UserPhase.ANNOTATION, None)

                # Verify initial counts
                annotation_count = user_state.get_annotation_count()
                total_assignable = ism.get_total_assignable_items_for_user(user_state)

                assert annotation_count == 0, "Initial annotation count should be 0"
                assert total_assignable == 10, "All 10 items should be assignable"

            finally:
                os.chdir(old_cwd)
                reset_singletons()

    def test_annotation_count_increases_with_annotations(self):
        """Test that annotation count increases as user annotates."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_multi_phase_config(tmpdir, training={"enabled": False})
            create_test_data(tmpdir, num_items=10)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.item_state_management import init_item_state_manager, Label
                from potato.user_state_management import init_user_state_manager
                from potato.phase import UserPhase

                class Args:
                    config_file = os.path.join(tmpdir, 'config.yaml')
                    verbose = False
                    very_verbose = False
                    customjs = None
                    customjs_hostname = None
                    debug = False
                    persist_sessions = False
                    require_password = None
                    port = None

                init_config(Args())
                ism = init_item_state_manager(config)
                usm = init_user_state_manager(config)

                # Load data
                with open(os.path.join(tmpdir, 'test_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                # Create user and advance to annotation phase
                usm.add_user("test_user")
                user_state = usm.get_user_state("test_user")
                user_state.advance_to_phase(UserPhase.ANNOTATION, None)

                # Annotate some instances
                label = Label(schema="sentiment", name="Positive")
                user_state.add_label_annotation("item_1", label, "Positive")
                user_state.add_label_annotation("item_2", label, "Negative")
                user_state.add_label_annotation("item_3", label, "Neutral")

                # Verify counts
                annotation_count = user_state.get_annotation_count()
                total_assignable = ism.get_total_assignable_items_for_user(user_state)

                assert annotation_count == 3, "Should have 3 annotations"
                assert total_assignable == 7, "Should have 7 remaining assignable items"

            finally:
                os.chdir(old_cwd)
                reset_singletons()

    def test_total_count_respects_max_annotations(self):
        """Test that total count considers max_annotations_per_user setting."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_multi_phase_config(tmpdir,
                training={"enabled": False},
                max_annotations_per_user=5
            )
            create_test_data(tmpdir, num_items=10)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.item_state_management import init_item_state_manager
                from potato.user_state_management import init_user_state_manager
                from potato.phase import UserPhase

                class Args:
                    config_file = os.path.join(tmpdir, 'config.yaml')
                    verbose = False
                    very_verbose = False
                    customjs = None
                    customjs_hostname = None
                    debug = False
                    persist_sessions = False
                    require_password = None
                    port = None

                init_config(Args())
                ism = init_item_state_manager(config)
                usm = init_user_state_manager(config)

                # Load data
                with open(os.path.join(tmpdir, 'test_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                # Create user
                usm.add_user("test_user")
                user_state = usm.get_user_state("test_user")
                user_state.advance_to_phase(UserPhase.ANNOTATION, None)

                # Total assignable should still be 10 (user limit is separate)
                total_assignable = ism.get_total_assignable_items_for_user(user_state)
                assert total_assignable == 10

                # But has_remaining_assignments should respect max_annotations_per_user
                user_state.set_max_assignments(5)
                assert user_state.has_remaining_assignments() is True

            finally:
                os.chdir(old_cwd)
                reset_singletons()


class TestTrainingPhaseCounting:
    """Test question counting in the training phase."""

    def test_training_question_count(self):
        """Test that training question counting is accurate."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_multi_phase_config(tmpdir)
            create_test_data(tmpdir)
            create_training_data(tmpdir)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.user_state_management import init_user_state_manager
                from potato.phase import UserPhase

                class Args:
                    config_file = os.path.join(tmpdir, 'config.yaml')
                    verbose = False
                    very_verbose = False
                    customjs = None
                    customjs_hostname = None
                    debug = False
                    persist_sessions = False
                    require_password = None
                    port = None

                init_config(Args())
                usm = init_user_state_manager(config)

                # Create user and set to training phase
                usm.add_user("test_user")
                user_state = usm.get_user_state("test_user")
                user_state.advance_to_phase(UserPhase.TRAINING, None)

                # Get training state
                training_state = user_state.training_state

                # Manually set training instances (normally done by routes.py from flask_server.get_training_instances())
                training_state.set_training_instances(["train_1", "train_2", "train_3"])

                # Verify initial state
                total_questions = len(training_state.training_instances)
                current_index = training_state.get_current_question_index()

                assert total_questions == 3, "Should have 3 training questions"
                assert current_index == 0, "Should start at question 0"

                # Simulate advancing through questions
                training_state.set_current_question_index(1)
                assert training_state.get_current_question_index() == 1

                training_state.set_current_question_index(2)
                assert training_state.get_current_question_index() == 2

            finally:
                os.chdir(old_cwd)
                reset_singletons()

    def test_training_correct_answer_count(self):
        """Test that correct answer counting in training is accurate."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_multi_phase_config(tmpdir)
            create_test_data(tmpdir)
            create_training_data(tmpdir)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.user_state_management import init_user_state_manager
                from potato.phase import UserPhase

                class Args:
                    config_file = os.path.join(tmpdir, 'config.yaml')
                    verbose = False
                    very_verbose = False
                    customjs = None
                    customjs_hostname = None
                    debug = False
                    persist_sessions = False
                    require_password = None
                    port = None

                init_config(Args())
                usm = init_user_state_manager(config)

                usm.add_user("test_user")
                user_state = usm.get_user_state("test_user")
                user_state.advance_to_phase(UserPhase.TRAINING, None)

                training_state = user_state.training_state

                # Manually set training instances
                training_state.set_training_instances(["train_1", "train_2", "train_3"])

                # Initial count should be 0
                assert training_state.get_correct_answer_count() == 0

                # Record some answers
                training_state.add_answer("train_1", is_correct=True, attempts=1)
                assert training_state.get_correct_answer_count() == 1

                training_state.add_answer("train_2", is_correct=False, attempts=1)
                assert training_state.get_correct_answer_count() == 1  # Still 1

                training_state.add_answer("train_3", is_correct=True, attempts=1)
                assert training_state.get_correct_answer_count() == 2

            finally:
                os.chdir(old_cwd)
                reset_singletons()


class TestPhaseTransitionCounting:
    """Test that counts don't leak between phases (Issue #87)."""

    def test_prestudy_does_not_affect_annotation_count(self):
        """Test that prestudy annotations don't affect main annotation count."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_multi_phase_config(tmpdir, training={"enabled": False})
            create_test_data(tmpdir, num_items=10)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.item_state_management import init_item_state_manager, Label
                from potato.user_state_management import init_user_state_manager
                from potato.phase import UserPhase

                class Args:
                    config_file = os.path.join(tmpdir, 'config.yaml')
                    verbose = False
                    very_verbose = False
                    customjs = None
                    customjs_hostname = None
                    debug = False
                    persist_sessions = False
                    require_password = None
                    port = None

                init_config(Args())
                ism = init_item_state_manager(config)
                usm = init_user_state_manager(config)

                # Load data
                with open(os.path.join(tmpdir, 'test_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                # Create user in prestudy phase
                usm.add_user("test_user")
                user_state = usm.get_user_state("test_user")

                # Simulate prestudy annotations (stored in phase_to_page_to_label_to_value)
                # This is how prestudy annotations are stored - keyed by phase and page
                label = Label(schema="prestudy_question", name="answer")
                user_state.phase_to_page_to_label_to_value[UserPhase.PRESTUDY][0][label] = "yes"
                user_state.phase_to_page_to_label_to_value[UserPhase.PRESTUDY][1][label] = "no"

                # The main annotation count should still be 0
                annotation_count = user_state.get_annotation_count()
                assert annotation_count == 0, \
                    f"Prestudy annotations should not affect main annotation count, got {annotation_count}"

                # Total assignable should still be 10
                total_assignable = ism.get_total_assignable_items_for_user(user_state)
                assert total_assignable == 10, \
                    f"Prestudy should not affect assignable count, got {total_assignable}"

            finally:
                os.chdir(old_cwd)
                reset_singletons()

    def test_training_does_not_affect_annotation_count(self):
        """Test that training answers don't affect main annotation count."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_multi_phase_config(tmpdir)
            create_test_data(tmpdir, num_items=10)
            create_training_data(tmpdir)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.item_state_management import init_item_state_manager
                from potato.user_state_management import init_user_state_manager
                from potato.phase import UserPhase

                class Args:
                    config_file = os.path.join(tmpdir, 'config.yaml')
                    verbose = False
                    very_verbose = False
                    customjs = None
                    customjs_hostname = None
                    debug = False
                    persist_sessions = False
                    require_password = None
                    port = None

                init_config(Args())
                ism = init_item_state_manager(config)
                usm = init_user_state_manager(config)

                # Load data
                with open(os.path.join(tmpdir, 'test_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                # Create user in training phase
                usm.add_user("test_user")
                user_state = usm.get_user_state("test_user")
                user_state.advance_to_phase(UserPhase.TRAINING, None)

                # Set up training instances
                training_state = user_state.training_state
                training_state.set_training_instances(["train_1", "train_2", "train_3"])

                # Complete training
                training_state.add_answer("train_1", is_correct=True, attempts=1)
                training_state.add_answer("train_2", is_correct=True, attempts=1)
                training_state.add_answer("train_3", is_correct=True, attempts=1)

                # Main annotation count should still be 0
                annotation_count = user_state.get_annotation_count()
                assert annotation_count == 0, \
                    f"Training answers should not affect main annotation count, got {annotation_count}"

                # Now advance to annotation phase
                user_state.advance_to_phase(UserPhase.ANNOTATION, None)

                # Annotation count should still be 0
                annotation_count = user_state.get_annotation_count()
                assert annotation_count == 0, \
                    f"After training, annotation count should be 0, got {annotation_count}"

                # Total assignable should be 10
                total_assignable = ism.get_total_assignable_items_for_user(user_state)
                assert total_assignable == 10, \
                    f"After training, all items should be assignable, got {total_assignable}"

            finally:
                os.chdir(old_cwd)
                reset_singletons()

    def test_annotation_count_after_full_workflow(self):
        """Test annotation count after completing prestudy -> training -> annotation flow."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_multi_phase_config(tmpdir)
            create_test_data(tmpdir, num_items=10)
            create_training_data(tmpdir)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.item_state_management import init_item_state_manager, Label
                from potato.user_state_management import init_user_state_manager
                from potato.phase import UserPhase

                class Args:
                    config_file = os.path.join(tmpdir, 'config.yaml')
                    verbose = False
                    very_verbose = False
                    customjs = None
                    customjs_hostname = None
                    debug = False
                    persist_sessions = False
                    require_password = None
                    port = None

                init_config(Args())
                ism = init_item_state_manager(config)
                usm = init_user_state_manager(config)

                # Load data
                with open(os.path.join(tmpdir, 'test_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                # Create user
                usm.add_user("test_user")
                user_state = usm.get_user_state("test_user")

                # Phase 1: Prestudy
                user_state.advance_to_phase(UserPhase.PRESTUDY, None)
                prestudy_label = Label(schema="prestudy", name="q1")
                user_state.phase_to_page_to_label_to_value[UserPhase.PRESTUDY][0][prestudy_label] = "answer1"
                user_state.phase_to_page_to_label_to_value[UserPhase.PRESTUDY][1][prestudy_label] = "answer2"

                # Verify annotation count is still 0
                assert user_state.get_annotation_count() == 0, "Prestudy should not affect count"

                # Phase 2: Training
                user_state.advance_to_phase(UserPhase.TRAINING, None)
                training_state = user_state.training_state
                training_state.set_training_instances(["train_1", "train_2", "train_3"])
                training_state.add_answer("train_1", is_correct=True, attempts=1)
                training_state.add_answer("train_2", is_correct=True, attempts=1)

                # Verify annotation count is still 0
                assert user_state.get_annotation_count() == 0, "Training should not affect count"

                # Phase 3: Annotation
                user_state.advance_to_phase(UserPhase.ANNOTATION, None)

                # Verify initial state - THIS IS THE KEY TEST FOR ISSUE #87
                annotation_count = user_state.get_annotation_count()
                total_assignable = ism.get_total_assignable_items_for_user(user_state)

                assert annotation_count == 0, \
                    f"After prestudy+training, annotation count should be 0, got {annotation_count}"
                assert total_assignable == 10, \
                    f"After prestudy+training, total should be 10, got {total_assignable}"

                # Now make some actual annotations
                label = Label(schema="sentiment", name="Positive")
                user_state.add_label_annotation("item_1", label, "Positive")
                user_state.add_label_annotation("item_2", label, "Negative")

                # Verify counts updated correctly
                assert user_state.get_annotation_count() == 2
                assert ism.get_total_assignable_items_for_user(user_state) == 8

            finally:
                os.chdir(old_cwd)
                reset_singletons()


class TestPoststudyCounting:
    """Test that poststudy doesn't affect counts."""

    def test_poststudy_does_not_affect_annotation_count(self):
        """Test that poststudy annotations don't affect main annotation count."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_multi_phase_config(tmpdir, training={"enabled": False})
            create_test_data(tmpdir, num_items=10)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.item_state_management import init_item_state_manager, Label
                from potato.user_state_management import init_user_state_manager
                from potato.phase import UserPhase

                class Args:
                    config_file = os.path.join(tmpdir, 'config.yaml')
                    verbose = False
                    very_verbose = False
                    customjs = None
                    customjs_hostname = None
                    debug = False
                    persist_sessions = False
                    require_password = None
                    port = None

                init_config(Args())
                ism = init_item_state_manager(config)
                usm = init_user_state_manager(config)

                # Load data
                with open(os.path.join(tmpdir, 'test_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                # Create user and complete annotation phase
                usm.add_user("test_user")
                user_state = usm.get_user_state("test_user")
                user_state.advance_to_phase(UserPhase.ANNOTATION, None)

                # Make some annotations
                label = Label(schema="sentiment", name="test")
                user_state.add_label_annotation("item_1", label, "Positive")
                user_state.add_label_annotation("item_2", label, "Negative")

                # Verify count is 2
                assert user_state.get_annotation_count() == 2

                # Move to poststudy
                user_state.advance_to_phase(UserPhase.POSTSTUDY, None)

                # Add poststudy annotations
                poststudy_label = Label(schema="poststudy", name="feedback")
                user_state.phase_to_page_to_label_to_value[UserPhase.POSTSTUDY][0][poststudy_label] = "Good"

                # Main annotation count should still be 2 (not affected by poststudy)
                assert user_state.get_annotation_count() == 2, \
                    "Poststudy should not affect main annotation count"

            finally:
                os.chdir(old_cwd)
                reset_singletons()


class TestEdgeCases:
    """Test edge cases in counting logic."""

    def test_count_with_no_data_loaded(self):
        """Test that counts are 0 when no data is loaded."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create an empty data file
            empty_data_path = os.path.join(tmpdir, 'empty_data.json')
            with open(empty_data_path, 'w') as f:
                json.dump([], f)

            # Config with empty data file
            config = {
                "debug": False,
                "annotation_task_name": "Test",
                "require_password": False,
                "data_files": ["empty_data.json"],
                "item_properties": {"text_key": "text", "id_key": "id"},
                "annotation_schemes": [
                    {"name": "label", "annotation_type": "radio",
                     "labels": ["A", "B"], "description": "Test"}
                ],
                "task_dir": tmpdir,
                "output_annotation_dir": tmpdir,
                "site_dir": "default"
            }
            config_path = os.path.join(tmpdir, 'config.yaml')
            with open(config_path, 'w') as f:
                yaml.dump(config, f)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config as global_config
                from potato.item_state_management import init_item_state_manager
                from potato.user_state_management import init_user_state_manager
                from potato.phase import UserPhase

                class Args:
                    config_file = config_path
                    verbose = False
                    very_verbose = False
                    customjs = None
                    customjs_hostname = None
                    debug = False
                    persist_sessions = False
                    require_password = None
                    port = None

                init_config(Args())
                ism = init_item_state_manager(global_config)
                usm = init_user_state_manager(global_config)

                # Create user
                usm.add_user("test_user")
                user_state = usm.get_user_state("test_user")
                user_state.advance_to_phase(UserPhase.ANNOTATION, None)

                # With no data loaded (empty file), counts should be 0
                annotation_count = user_state.get_annotation_count()
                total_assignable = ism.get_total_assignable_items_for_user(user_state)

                assert annotation_count == 0
                assert total_assignable == 0

            finally:
                os.chdir(old_cwd)
                reset_singletons()

    def test_count_with_max_annotations_per_item_limit(self):
        """Test counting when items have reached their annotation limit."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_multi_phase_config(tmpdir,
                training={"enabled": False},
                max_annotations_per_item=1  # Each item can only be annotated once
            )
            create_test_data(tmpdir, num_items=5)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.item_state_management import init_item_state_manager, Label
                from potato.user_state_management import init_user_state_manager
                from potato.phase import UserPhase

                class Args:
                    config_file = os.path.join(tmpdir, 'config.yaml')
                    verbose = False
                    very_verbose = False
                    customjs = None
                    customjs_hostname = None
                    debug = False
                    persist_sessions = False
                    require_password = None
                    port = None

                init_config(Args())
                ism = init_item_state_manager(config)
                usm = init_user_state_manager(config)

                # Load data
                with open(os.path.join(tmpdir, 'test_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                # Create first user
                usm.add_user("user1")
                user1_state = usm.get_user_state("user1")
                user1_state.advance_to_phase(UserPhase.ANNOTATION, None)

                # User1 annotates all items
                label = Label(schema="sentiment", name="test")
                for i in range(1, 6):
                    user1_state.add_label_annotation(f"item_{i}", label, "Positive")
                    ism.register_annotator(f"item_{i}", "user1")

                # Create second user
                usm.add_user("user2")
                user2_state = usm.get_user_state("user2")
                user2_state.advance_to_phase(UserPhase.ANNOTATION, None)

                # User2 should have 0 assignable items (all at limit)
                total_for_user2 = ism.get_total_assignable_items_for_user(user2_state)
                assert total_for_user2 == 0, \
                    f"All items at limit, user2 should have 0 assignable, got {total_for_user2}"

            finally:
                os.chdir(old_cwd)
                reset_singletons()

    def test_annotated_instance_ids_tracking(self):
        """Test that annotated instance IDs are tracked correctly."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_multi_phase_config(tmpdir, training={"enabled": False})
            create_test_data(tmpdir, num_items=5)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.item_state_management import init_item_state_manager, Label, SpanAnnotation
                from potato.user_state_management import init_user_state_manager
                from potato.phase import UserPhase

                class Args:
                    config_file = os.path.join(tmpdir, 'config.yaml')
                    verbose = False
                    very_verbose = False
                    customjs = None
                    customjs_hostname = None
                    debug = False
                    persist_sessions = False
                    require_password = None
                    port = None

                init_config(Args())
                ism = init_item_state_manager(config)
                usm = init_user_state_manager(config)

                # Load data
                with open(os.path.join(tmpdir, 'test_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                usm.add_user("test_user")
                user_state = usm.get_user_state("test_user")
                user_state.advance_to_phase(UserPhase.ANNOTATION, None)

                # Add label annotation
                label = Label(schema="sentiment", name="Positive")
                user_state.add_label_annotation("item_1", label, "Positive")

                # Add span annotation to different item
                span = SpanAnnotation(schema="span", name="entity", title="Entity",
                                     start=0, end=5, id="span_1")
                user_state.add_span_annotation("item_2", span, "PERSON")

                # Both should be tracked
                annotated_ids = user_state.get_annotated_instance_ids()
                assert "item_1" in annotated_ids
                assert "item_2" in annotated_ids
                assert len(annotated_ids) == 2
                assert user_state.get_annotation_count() == 2

            finally:
                os.chdir(old_cwd)
                reset_singletons()


class TestHasRemainingAssignments:
    """Test the has_remaining_assignments logic."""

    def test_has_remaining_with_unlimited_assignments(self):
        """Test has_remaining_assignments with no limit (max_assignments=-1)."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_multi_phase_config(tmpdir,
                training={"enabled": False},
                max_annotations_per_user=-1  # Unlimited
            )
            create_test_data(tmpdir, num_items=5)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.item_state_management import init_item_state_manager, Label
                from potato.user_state_management import init_user_state_manager
                from potato.phase import UserPhase

                class Args:
                    config_file = os.path.join(tmpdir, 'config.yaml')
                    verbose = False
                    very_verbose = False
                    customjs = None
                    customjs_hostname = None
                    debug = False
                    persist_sessions = False
                    require_password = None
                    port = None

                init_config(Args())
                ism = init_item_state_manager(config)
                usm = init_user_state_manager(config)

                # Load data
                with open(os.path.join(tmpdir, 'test_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                usm.add_user("test_user")
                user_state = usm.get_user_state("test_user")
                user_state.advance_to_phase(UserPhase.ANNOTATION, None)
                user_state.set_max_assignments(-1)  # Unlimited

                # Should always have remaining with unlimited
                assert user_state.has_remaining_assignments() is True

                # Even after annotating
                label = Label(schema="sentiment", name="test")
                for i in range(1, 6):
                    user_state.add_label_annotation(f"item_{i}", label, "Positive")

                # Still has remaining (unlimited mode)
                assert user_state.has_remaining_assignments() is True

            finally:
                os.chdir(old_cwd)
                reset_singletons()

    def test_has_remaining_with_limited_assignments(self):
        """Test has_remaining_assignments with a limit."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_multi_phase_config(tmpdir,
                training={"enabled": False},
                max_annotations_per_user=3
            )
            create_test_data(tmpdir, num_items=10)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.item_state_management import init_item_state_manager, Label
                from potato.user_state_management import init_user_state_manager
                from potato.phase import UserPhase

                class Args:
                    config_file = os.path.join(tmpdir, 'config.yaml')
                    verbose = False
                    very_verbose = False
                    customjs = None
                    customjs_hostname = None
                    debug = False
                    persist_sessions = False
                    require_password = None
                    port = None

                init_config(Args())
                ism = init_item_state_manager(config)
                usm = init_user_state_manager(config)

                # Load data
                with open(os.path.join(tmpdir, 'test_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                usm.add_user("test_user")
                user_state = usm.get_user_state("test_user")
                user_state.advance_to_phase(UserPhase.ANNOTATION, None)
                user_state.set_max_assignments(3)

                # Should have remaining initially
                assert user_state.has_remaining_assignments() is True

                # Annotate up to limit
                label = Label(schema="sentiment", name="test")
                user_state.add_label_annotation("item_1", label, "Positive")
                assert user_state.has_remaining_assignments() is True  # 1/3

                user_state.add_label_annotation("item_2", label, "Positive")
                assert user_state.has_remaining_assignments() is True  # 2/3

                user_state.add_label_annotation("item_3", label, "Positive")
                assert user_state.has_remaining_assignments() is False  # 3/3 - done!

            finally:
                os.chdir(old_cwd)
                reset_singletons()
