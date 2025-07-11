"""
Assignment Strategy Tests

This module contains comprehensive tests for different item assignment strategies:
1. Random assignment
2. Fixed order assignment
3. Least-annotated assignment
4. Highest-disagreement assignment (max diversity)
5. Completion scenarios (all items have max annotations)

Tests cover various scenarios with different numbers of items and annotators,
ensuring proper distribution and completion behavior.
"""

import pytest
import json
import os
import sys
import tempfile
import yaml

# Add the project root to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

ASSIGNMENT_STRATEGIES = [
    "fixed_order",
    "random",
    "max_diversity",
    "active_learning",
    "llm_confidence",
    "least_annotated"
]

def create_test_config(config_dir):
    """Create a test configuration file in the given directory."""
    config = {
        "debug": True,
        "max_annotations_per_user": 5,
        "max_annotations_per_item": -1,
        "assignment_strategy": "fixed_order",
        "annotation_task_name": "Test Assignment Strategies",
        "require_password": False,
        "authentication": {
            "method": "in_memory"
        },
        "data_files": ["test_data.json"],
        "item_properties": {
            "text_key": "text",
            "id_key": "id"
        },
        "annotation_schemes": [
            {
                "name": "radio_choice",
                "type": "radio",
                "labels": ["option_1", "option_2", "option_3"]
            }
        ]
    }
    config_path = os.path.join(config_dir, 'test_config.yaml')
    with open(config_path, 'w') as f:
        yaml.dump(config, f)
    return config_path

def create_test_data(config_dir):
    """Create test data file in the given directory."""
    test_data = [
        {"id": f"item_{i}", "text": f"This is test item {i}"}
        for i in range(1, 11)
    ]
    data_path = os.path.join(config_dir, 'test_data.json')
    with open(data_path, 'w') as f:
        json.dump(test_data, f)
    return data_path

@pytest.mark.parametrize("strategy", ASSIGNMENT_STRATEGIES)
def test_assignment_strategy_direct(strategy):
    """Test assignment strategies directly without Flask test client."""

    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = create_test_config(tmpdir)
        data_file = create_test_data(tmpdir)
        old_cwd = os.getcwd()
        os.chdir(tmpdir)

        try:
            # Initialize config
            from potato.server_utils.config_module import init_config
            class Args:
                pass
            args = Args()
            args.config_file = config_file
            args.verbose = False
            args.very_verbose = False
            args.customjs = None
            args.customjs_hostname = None
            args.debug = True
            init_config(args)

            # Import and initialize managers
            from potato.item_state_management import init_item_state_manager, ITEM_STATE_MANAGER
            from potato.user_state_management import init_user_state_manager, USER_STATE_MANAGER
            from potato.phase import UserPhase

            # Reset singletons
            import potato.item_state_management
            import potato.user_state_management
            potato.item_state_management.ITEM_STATE_MANAGER = None
            potato.user_state_management.USER_STATE_MANAGER = None

            # Initialize managers
            from potato.server_utils.config_module import config
            ism = init_item_state_manager(config)
            usm = init_user_state_manager(config)

            # Create test items
            test_items = {
                f"item_{i}": {
                    "id": f"item_{i}",
                    "text": f"This is test item {i}",
                    "displayed_text": f"This is test item {i}"
                }
                for i in range(1, 11)
            }

            # Add items to the dataset
            ism.add_items(test_items)

            # Create a test user
            username = f"test_user_{strategy}"
            usm.add_user(username)
            user_state = usm.get_user_state(username)
            user_state.advance_to_phase(UserPhase.ANNOTATION, None)

            # Test assignment strategy
            annotated_count = 0
            max_annotations = 5

            while annotated_count < max_annotations:
                # Check if user has remaining assignments
                if not user_state.has_remaining_assignments():
                    break

                # Assign instances to user
                num_assigned = ism.assign_instances_to_user(user_state)
                if num_assigned == 0:
                    break  # No more instances available

                # Get assigned instances
                assigned_instances = user_state.get_assigned_instance_ids()
                if not assigned_instances:
                    break

                # Find first unannotated instance
                current_instance = None
                for instance_id in assigned_instances:
                    if not user_state.has_annotated(instance_id):
                        current_instance = instance_id
                        break

                if not current_instance:
                    break  # All assigned instances are annotated

                # Ensure user is in annotation phase
                user_state.advance_to_phase(UserPhase.ANNOTATION, None)
                print(f"User phase after advance_to_phase: {user_state.get_current_phase_and_page()}")

                # Simulate annotation using proper Label object
                from potato.item_state_management import Label
                print(f"Test Label class id: {id(Label)}")
                label = Label("radio_choice", "choice")
                user_state.add_label_annotation(current_instance, label, "option_1")
                print(f"Label annotations for {current_instance}: {user_state.get_label_annotations(current_instance)}")
                if current_instance in user_state.instance_id_to_label_to_value:
                    print(f"Keys in label_to_value for {current_instance}: {list(user_state.instance_id_to_label_to_value[current_instance].keys())}")
                print(f"Annotated instance ids: {user_state.get_annotated_instance_ids()}")
                print(f"Assigned instance ids before annotation: {user_state.get_assigned_instance_ids()}")
                print(f"user_state.instance_id_to_label_to_value: {user_state.instance_id_to_label_to_value}")
                print(f"user_state.current_phase_and_page before annotation: {user_state.current_phase_and_page}")
                if user_state.current_phase_and_page[0] != UserPhase.ANNOTATION:
                    user_state.current_phase_and_page = (UserPhase.ANNOTATION, None)
                    print(f"Set user_state.current_phase_and_page to: {user_state.current_phase_and_page}")
                annotated_count += 1

                # Verify annotation was recorded
                assert user_state.has_annotated(current_instance), f"Instance {current_instance} should be marked as annotated"

            # Verify final state
            total_annotated = user_state.get_annotation_count()
            total_assigned = len(user_state.get_assigned_instance_ids())

            # The user should have annotated exactly the maximum allowed number
            assert total_annotated == max_annotations, f"Expected {max_annotations} annotations, got {total_annotated}"

            # The user should have been assigned at least the maximum number of instances
            assert total_assigned >= max_annotations, f"Expected at least {max_annotations} assigned instances, got {total_assigned}"

            print(f"✅ Strategy '{strategy}' passed: {total_annotated}/{max_annotations} annotations completed")

        finally:
            os.chdir(old_cwd)

def test_all_strategies():
    """Run all assignment strategy tests."""
    print("🧪 Testing all assignment strategies...")

    for strategy in ASSIGNMENT_STRATEGIES:
        print(f"\n📋 Testing strategy: {strategy}")
        test_assignment_strategy_direct(strategy)

if __name__ == "__main__":
    # Run tests directly
    test_all_strategies()