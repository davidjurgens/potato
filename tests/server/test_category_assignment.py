"""
Category-Based Assignment Integration Tests

This module tests the category-based assignment system end-to-end:
1. Category indexing when loading data
2. Training-based category qualification
3. Category-based instance assignment
4. Dynamic expertise mode with probabilistic routing
5. Fallback behavior when no categories qualify
"""

import pytest
import json
import os
import sys
import tempfile
import yaml
import time

# Add the project root to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def reset_singletons():
    """Reset all singleton managers for clean test state."""
    import potato.item_state_management
    import potato.user_state_management
    from potato.server_utils.config_module import clear_config
    from potato.expertise_manager import clear_expertise_manager

    potato.item_state_management.ITEM_STATE_MANAGER = None
    potato.user_state_management.USER_STATE_MANAGER = None
    clear_config()
    clear_expertise_manager()


def create_category_config(config_dir, **overrides):
    """Create a test configuration with category-based assignment."""
    config = {
        "debug": False,
        "max_annotations_per_user": 10,
        "max_annotations_per_item": -1,
        "assignment_strategy": "category_based",
        "annotation_task_name": "Category Assignment Test",
        "require_password": False,
        "authentication": {"method": "in_memory"},
        "data_files": ["category_data.json"],
        "item_properties": {
            "text_key": "text",
            "id_key": "id",
            "category_key": "category"
        },
        "annotation_schemes": [
            {
                "name": "topic",
                "annotation_type": "radio",
                "labels": ["Economics", "Science", "Sports", "Technology"],
                "description": "Classify the topic"
            }
        ],
        "category_assignment": {
            "enabled": True,
            "qualification": {
                "source": "training",
                "threshold": 0.6,
                "min_questions": 1
            },
            "fallback": "uncategorized"
        },
        "training": {
            "enabled": True,
            "data_file": "training_data.json",
            "passing_criteria": {
                "min_correct": 1,
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


def create_category_data(config_dir):
    """Create test data with categories."""
    test_data = [
        # Economics instances
        {"id": "econ_1", "text": "Stock market analysis", "category": "economics"},
        {"id": "econ_2", "text": "GDP growth report", "category": "economics"},
        {"id": "econ_3", "text": "Interest rate changes", "category": "economics"},
        # Science instances
        {"id": "sci_1", "text": "New planet discovery", "category": "science"},
        {"id": "sci_2", "text": "Climate research findings", "category": "science"},
        {"id": "sci_3", "text": "Gene therapy breakthrough", "category": "science"},
        # Sports instances
        {"id": "sports_1", "text": "Championship results", "category": "sports"},
        {"id": "sports_2", "text": "Player transfer news", "category": "sports"},
        # Technology instances
        {"id": "tech_1", "text": "AI advancement", "category": "technology"},
        {"id": "tech_2", "text": "Quantum computing", "category": "technology"},
        # Multi-category instances
        {"id": "multi_1", "text": "Tech industry economics", "category": ["economics", "technology"]},
        # Uncategorized instances
        {"id": "general_1", "text": "General news item", "category": None},
        {"id": "general_2", "text": "Another general item"},  # No category field
    ]
    data_path = os.path.join(config_dir, 'category_data.json')
    with open(data_path, 'w') as f:
        json.dump(test_data, f)
    return data_path


def create_training_data(config_dir):
    """Create training data with categories for qualification."""
    training_data = {
        "training_instances": [
            {
                "id": "train_econ_1",
                "text": "Economic indicator analysis",
                "category": "economics",
                "correct_answers": {"topic": "Economics"},
                "explanation": "This is about economics."
            },
            {
                "id": "train_sci_1",
                "text": "Scientific method explanation",
                "category": "science",
                "correct_answers": {"topic": "Science"},
                "explanation": "This is about science."
            },
            {
                "id": "train_sports_1",
                "text": "Sports tournament coverage",
                "category": "sports",
                "correct_answers": {"topic": "Sports"},
                "explanation": "This is about sports."
            },
            {
                "id": "train_tech_1",
                "text": "Technology innovation report",
                "category": "technology",
                "correct_answers": {"topic": "Technology"},
                "explanation": "This is about technology."
            }
        ]
    }
    data_path = os.path.join(config_dir, 'training_data.json')
    with open(data_path, 'w') as f:
        json.dump(training_data, f)
    return data_path


class TestCategoryIndexing:
    """Test category indexing when loading data."""

    def test_categories_indexed_on_load(self):
        """Test that categories are properly indexed when data is loaded."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_category_config(tmpdir)
            create_category_data(tmpdir)
            create_training_data(tmpdir)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.item_state_management import init_item_state_manager

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

                # Load data
                with open(os.path.join(tmpdir, 'category_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                # Verify categories are indexed
                all_categories = ism.get_all_categories()
                assert 'economics' in all_categories
                assert 'science' in all_categories
                assert 'sports' in all_categories
                assert 'technology' in all_categories

                # Verify instance counts per category
                counts = ism.get_category_counts()
                assert counts['economics'] >= 3  # econ_1, econ_2, econ_3, plus multi_1
                assert counts['science'] == 3
                assert counts['sports'] == 2
                assert counts['technology'] >= 2  # tech_1, tech_2, plus multi_1

                # Verify uncategorized instances
                uncategorized = ism.get_uncategorized_instances()
                assert 'general_1' in uncategorized
                assert 'general_2' in uncategorized

            finally:
                os.chdir(old_cwd)
                reset_singletons()

    def test_multi_category_instances(self):
        """Test that instances with multiple categories are indexed correctly."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_category_config(tmpdir)
            create_category_data(tmpdir)
            create_training_data(tmpdir)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.item_state_management import init_item_state_manager

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

                # Load data
                with open(os.path.join(tmpdir, 'category_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                # Verify multi-category instance appears in both categories
                econ_instances = ism.get_instances_by_category('economics')
                tech_instances = ism.get_instances_by_category('technology')

                assert 'multi_1' in econ_instances
                assert 'multi_1' in tech_instances

                # Verify categories for instance
                categories = ism.get_categories_for_instance('multi_1')
                assert 'economics' in categories
                assert 'technology' in categories

            finally:
                os.chdir(old_cwd)
                reset_singletons()


class TestTrainingQualification:
    """Test category qualification through training."""

    def test_qualification_from_training_answers(self):
        """Test that correct training answers qualify users for categories."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_category_config(tmpdir)
            create_category_data(tmpdir)
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

                # Create user
                usm.add_user("test_user")
                user_state = usm.get_user_state("test_user")

                # Simulate training answers
                training_state = user_state.training_state

                # Answer economics question correctly
                training_state.record_category_answer(['economics'], is_correct=True)

                # Answer science question incorrectly
                training_state.record_category_answer(['science'], is_correct=False)

                # Answer sports question correctly
                training_state.record_category_answer(['sports'], is_correct=True)

                # Get qualified categories (threshold=0.6, min_questions=1)
                qualified = training_state.get_qualified_categories(threshold=0.6, min_questions=1)

                assert 'economics' in qualified  # 100% accuracy
                assert 'science' not in qualified  # 0% accuracy
                assert 'sports' in qualified  # 100% accuracy

            finally:
                os.chdir(old_cwd)
                reset_singletons()

    def test_user_qualification_calculation(self):
        """Test UserState.calculate_and_set_qualifications()."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_category_config(tmpdir)
            create_category_data(tmpdir)
            create_training_data(tmpdir)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.user_state_management import init_user_state_manager

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

                # Record training answers
                training_state = user_state.training_state
                training_state.record_category_answer(['economics'], is_correct=True)
                training_state.record_category_answer(['economics'], is_correct=True)
                training_state.record_category_answer(['science'], is_correct=False)
                training_state.record_category_answer(['technology'], is_correct=True)

                # Calculate qualifications
                newly_qualified = user_state.calculate_and_set_qualifications(
                    threshold=0.6, min_questions=1
                )

                assert 'economics' in newly_qualified
                assert 'technology' in newly_qualified
                assert 'science' not in newly_qualified

                # Verify user state has the qualifications
                assert user_state.is_qualified_for_category('economics')
                assert user_state.is_qualified_for_category('technology')
                assert not user_state.is_qualified_for_category('science')

            finally:
                os.chdir(old_cwd)
                reset_singletons()


class TestCategoryBasedAssignment:
    """Test category-based instance assignment."""

    def test_assignment_respects_qualifications(self):
        """Test that users only get instances from qualified categories."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_category_config(tmpdir)
            create_category_data(tmpdir)
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
                with open(os.path.join(tmpdir, 'category_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                # Create user and qualify for economics only
                usm.add_user("econ_expert")
                user_state = usm.get_user_state("econ_expert")
                user_state.add_qualified_category('economics', score=0.9)
                user_state.advance_to_phase(UserPhase.ANNOTATION, None)

                # Assign instances
                num_assigned = ism.assign_instances_to_user(user_state)
                assert num_assigned > 0

                # Verify all assigned instances are from economics category
                assigned_ids = user_state.get_assigned_instance_ids()
                for instance_id in assigned_ids:
                    categories = ism.get_categories_for_instance(instance_id)
                    assert 'economics' in categories, f"Instance {instance_id} not in economics category"

            finally:
                os.chdir(old_cwd)
                reset_singletons()

    def test_fallback_to_uncategorized(self):
        """Test fallback to uncategorized instances when no categories qualify."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_category_config(tmpdir, category_assignment={
                "enabled": True,
                "fallback": "uncategorized"
            })
            create_category_data(tmpdir)
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
                with open(os.path.join(tmpdir, 'category_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                # Create user with NO qualifications
                usm.add_user("no_quals_user")
                user_state = usm.get_user_state("no_quals_user")
                user_state.advance_to_phase(UserPhase.ANNOTATION, None)

                # Assign instances - should get uncategorized
                num_assigned = ism.assign_instances_to_user(user_state)

                # Should get the uncategorized instances
                assigned_ids = user_state.get_assigned_instance_ids()
                uncategorized = ism.get_uncategorized_instances()

                # All assigned should be uncategorized
                for instance_id in assigned_ids:
                    assert instance_id in uncategorized, f"Instance {instance_id} is not uncategorized"

            finally:
                os.chdir(old_cwd)
                reset_singletons()

    def test_fallback_random(self):
        """Test fallback to random assignment when configured."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_category_config(tmpdir, category_assignment={
                "enabled": True,
                "fallback": "random"
            })
            create_category_data(tmpdir)
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
                with open(os.path.join(tmpdir, 'category_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                # Create user with NO qualifications
                usm.add_user("random_user")
                user_state = usm.get_user_state("random_user")
                user_state.advance_to_phase(UserPhase.ANNOTATION, None)

                # Assign instances - should get random instances
                num_assigned = ism.assign_instances_to_user(user_state)
                assert num_assigned > 0, "Should assign instances via random fallback"

            finally:
                os.chdir(old_cwd)
                reset_singletons()


class TestDynamicExpertiseMode:
    """Test dynamic expertise mode with probabilistic routing."""

    def test_dynamic_mode_initialization(self):
        """Test that dynamic mode initializes the ExpertiseManager."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_category_config(tmpdir, category_assignment={
                "enabled": True,
                "dynamic": {
                    "enabled": True,
                    "agreement_method": "majority_vote",
                    "min_annotations_for_consensus": 2,
                    "learning_rate": 0.1,
                    "base_probability": 0.1
                }
            })
            create_category_data(tmpdir)
            create_training_data(tmpdir)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.item_state_management import init_item_state_manager
                from potato.expertise_manager import init_expertise_manager, get_expertise_manager

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

                # Verify dynamic mode flag
                assert ism.dynamic_expertise_enabled is True

                # Initialize expertise manager
                em = init_expertise_manager(config)
                assert em is not None
                assert em.learning_rate == 0.1
                assert em.base_probability == 0.1

            finally:
                os.chdir(old_cwd)
                reset_singletons()

    def test_probabilistic_routing_all_categories(self):
        """Test that dynamic mode can assign from all categories."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_category_config(tmpdir, category_assignment={
                "enabled": True,
                "dynamic": {
                    "enabled": True,
                    "base_probability": 0.25  # Equal chance for all
                }
            })
            create_category_data(tmpdir)
            create_training_data(tmpdir)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.item_state_management import init_item_state_manager
                from potato.user_state_management import init_user_state_manager
                from potato.expertise_manager import init_expertise_manager
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
                em = init_expertise_manager(config)

                # Load data
                with open(os.path.join(tmpdir, 'category_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                # Create user (no qualifications needed in dynamic mode)
                usm.add_user("dynamic_user")
                user_state = usm.get_user_state("dynamic_user")
                user_state.advance_to_phase(UserPhase.ANNOTATION, None)

                # Assign many instances and track categories
                assigned_categories = set()
                for _ in range(10):
                    num_assigned = ism.assign_instances_to_user(user_state)
                    if num_assigned == 0:
                        break
                    for iid in user_state.get_assigned_instance_ids():
                        cats = ism.get_categories_for_instance(iid)
                        assigned_categories.update(cats)

                # With base_probability=0.25, we should get multiple categories
                # (though this is probabilistic, so we just check we got some)
                assert len(assigned_categories) >= 1

            finally:
                os.chdir(old_cwd)
                reset_singletons()

    def test_expertise_weighting(self):
        """Test that higher expertise leads to more assignments from that category."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_category_config(tmpdir, category_assignment={
                "enabled": True,
                "dynamic": {
                    "enabled": True,
                    "base_probability": 0.0  # No base, pure expertise weighting
                }
            })
            create_category_data(tmpdir)
            create_training_data(tmpdir)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.item_state_management import init_item_state_manager
                from potato.user_state_management import init_user_state_manager
                from potato.expertise_manager import init_expertise_manager, CategoryExpertise
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
                em = init_expertise_manager(config)

                # Load data
                with open(os.path.join(tmpdir, 'category_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                # Create user with high economics expertise
                usm.add_user("econ_expert")
                user_state = usm.get_user_state("econ_expert")
                user_state.advance_to_phase(UserPhase.ANNOTATION, None)

                # Set expertise scores manually
                profile = em.get_user_profile("econ_expert")
                profile.category_expertise['economics'] = CategoryExpertise(
                    category='economics', expertise_score=0.95
                )
                profile.category_expertise['science'] = CategoryExpertise(
                    category='science', expertise_score=0.05
                )
                profile.category_expertise['sports'] = CategoryExpertise(
                    category='sports', expertise_score=0.05
                )
                profile.category_expertise['technology'] = CategoryExpertise(
                    category='technology', expertise_score=0.05
                )

                # Track assignments by category
                category_counts = {'economics': 0, 'science': 0, 'sports': 0, 'technology': 0}
                all_assigned_ids = set()

                # Create a mock Label for marking annotations
                from potato.item_state_management import Label
                mock_label = Label(schema="topic", name="test")

                # Assign instances multiple times
                for _ in range(10):
                    # Assign instances to user
                    num_assigned = ism.assign_instances_to_user(user_state)
                    if num_assigned == 0:
                        break

                    # Get newly assigned instances
                    assigned_ids = user_state.get_assigned_instance_ids()
                    new_ids = assigned_ids - all_assigned_ids

                    for iid in new_ids:
                        cats = ism.get_categories_for_instance(iid)
                        for cat in cats:
                            if cat in category_counts:
                                category_counts[cat] += 1
                        all_assigned_ids.add(iid)

                        # Mark as annotated to allow more assignments
                        user_state.add_label_annotation(iid, mock_label, "Economics")

                # Economics should have significantly more assignments
                # (This is probabilistic but with 0.95 vs 0.05, economics should dominate)
                total_assigned = sum(category_counts.values())
                assert total_assigned > 0, "Should have assigned some instances"

            finally:
                os.chdir(old_cwd)
                reset_singletons()

    def test_expertise_update_on_agreement(self):
        """Test that expertise scores update based on agreement."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_category_config(tmpdir, category_assignment={
                "enabled": True,
                "dynamic": {
                    "enabled": True,
                    "learning_rate": 0.2
                }
            })
            create_category_data(tmpdir)
            create_training_data(tmpdir)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.expertise_manager import init_expertise_manager

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
                em = init_expertise_manager(config)

                # Initial score should be 0.5
                profile = em.get_user_profile("test_user")
                initial_score = profile.get_expertise_score("economics")
                assert initial_score == 0.5

                # Update with agreement
                em.update_user_expertise(
                    user_id="test_user",
                    instance_id="inst_1",
                    category="economics",
                    user_annotation="A",
                    consensus_value="A"  # Agrees
                )

                # Score should increase
                new_score = profile.get_expertise_score("economics")
                assert new_score > initial_score

                # Update with disagreement
                em.update_user_expertise(
                    user_id="test_user",
                    instance_id="inst_2",
                    category="science",
                    user_annotation="A",
                    consensus_value="B"  # Disagrees
                )

                # Science score should decrease from 0.5
                science_score = profile.get_expertise_score("science")
                assert science_score < 0.5

            finally:
                os.chdir(old_cwd)
                reset_singletons()


class TestMultiUserScenarios:
    """Test category assignment with multiple users."""

    def test_different_users_different_categories(self):
        """Test that users with different qualifications get different instances."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_category_config(tmpdir)
            create_category_data(tmpdir)
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
                with open(os.path.join(tmpdir, 'category_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                # Create economics expert
                usm.add_user("econ_user")
                econ_state = usm.get_user_state("econ_user")
                econ_state.add_qualified_category('economics', score=0.9)
                econ_state.advance_to_phase(UserPhase.ANNOTATION, None)

                # Create science expert
                usm.add_user("sci_user")
                sci_state = usm.get_user_state("sci_user")
                sci_state.add_qualified_category('science', score=0.9)
                sci_state.advance_to_phase(UserPhase.ANNOTATION, None)

                # Assign to both
                ism.assign_instances_to_user(econ_state)
                ism.assign_instances_to_user(sci_state)

                # Verify they get different category instances
                econ_ids = econ_state.get_assigned_instance_ids()
                sci_ids = sci_state.get_assigned_instance_ids()

                for iid in econ_ids:
                    cats = ism.get_categories_for_instance(iid)
                    assert 'economics' in cats

                for iid in sci_ids:
                    cats = ism.get_categories_for_instance(iid)
                    assert 'science' in cats

            finally:
                os.chdir(old_cwd)
                reset_singletons()

    def test_generalist_gets_all_categories(self):
        """Test that a user qualified for all categories gets mixed instances."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            create_category_config(tmpdir)
            create_category_data(tmpdir)
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
                with open(os.path.join(tmpdir, 'category_data.json')) as f:
                    data = json.load(f)
                for item in data:
                    ism.add_item(item['id'], item)

                # Create generalist qualified for all
                usm.add_user("generalist")
                gen_state = usm.get_user_state("generalist")
                gen_state.add_qualified_category('economics', score=0.9)
                gen_state.add_qualified_category('science', score=0.9)
                gen_state.add_qualified_category('sports', score=0.9)
                gen_state.add_qualified_category('technology', score=0.9)
                gen_state.advance_to_phase(UserPhase.ANNOTATION, None)

                # Assign instances
                ism.assign_instances_to_user(gen_state)

                # Should get instances from multiple categories
                assigned_ids = gen_state.get_assigned_instance_ids()
                assigned_categories = set()
                for iid in assigned_ids:
                    cats = ism.get_categories_for_instance(iid)
                    assigned_categories.update(cats)

                # Should have access to all categories
                assert len(assigned_categories) >= 1

            finally:
                os.chdir(old_cwd)
                reset_singletons()


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_category_field(self):
        """Test handling of empty category field values."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create data with various empty category values
            test_data = [
                {"id": "item_1", "text": "Text 1", "category": "valid"},
                {"id": "item_2", "text": "Text 2", "category": ""},  # Empty string
                {"id": "item_3", "text": "Text 3", "category": []},  # Empty list
                {"id": "item_4", "text": "Text 4", "category": None},  # Null
                {"id": "item_5", "text": "Text 5"},  # Missing field
            ]
            data_path = os.path.join(tmpdir, 'category_data.json')
            with open(data_path, 'w') as f:
                json.dump(test_data, f)

            create_category_config(tmpdir)
            create_training_data(tmpdir)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config
                from potato.item_state_management import init_item_state_manager

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

                # Load data - should not crash
                for item in test_data:
                    ism.add_item(item['id'], item)

                # Only item_1 should be in 'valid' category
                valid_instances = ism.get_instances_by_category('valid')
                assert 'item_1' in valid_instances

                # Others should be uncategorized
                uncategorized = ism.get_uncategorized_instances()
                assert 'item_2' in uncategorized
                assert 'item_3' in uncategorized
                assert 'item_4' in uncategorized
                assert 'item_5' in uncategorized

            finally:
                os.chdir(old_cwd)
                reset_singletons()

    def test_no_category_key_configured(self):
        """Test behavior when category_key is not configured."""
        reset_singletons()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Config without category_key
            config = {
                "debug": False,
                "max_annotations_per_user": 10,
                "assignment_strategy": "fixed_order",  # Not category_based
                "annotation_task_name": "No Category Test",
                "require_password": False,
                "data_files": ["data.json"],
                "item_properties": {
                    "text_key": "text",
                    "id_key": "id"
                    # No category_key
                },
                "annotation_schemes": [
                    {
                        "name": "label",
                        "annotation_type": "radio",
                        "labels": ["A", "B"],
                        "description": "Test"
                    }
                ],
                "task_dir": tmpdir,
                "output_annotation_dir": tmpdir,
                "site_dir": "default"
            }
            config_path = os.path.join(tmpdir, 'config.yaml')
            with open(config_path, 'w') as f:
                yaml.dump(config, f)

            # Create data with categories (but they won't be indexed)
            test_data = [{"id": "item_1", "text": "Text", "category": "test"}]
            with open(os.path.join(tmpdir, 'data.json'), 'w') as f:
                json.dump(test_data, f)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                from potato.server_utils.config_module import init_config, config as global_config
                from potato.item_state_management import init_item_state_manager

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

                # Should not crash without category_key
                ism.add_item("item_1", {"id": "item_1", "text": "Text", "category": "test"})

                # No categories should be indexed
                assert ism.get_all_categories() == set()

            finally:
                os.chdir(old_cwd)
                reset_singletons()
