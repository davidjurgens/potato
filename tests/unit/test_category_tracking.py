"""
Unit tests for category-based assignment functionality.

This module tests the category tracking, indexing, and qualification
features added to support category-based instance assignment.
"""

import pytest
from unittest.mock import MagicMock, patch
from collections import defaultdict

from potato.item_state_management import (
    ItemStateManager, Item, AssignmentStrategy
)
from potato.user_state_management import (
    TrainingState, InMemoryUserState
)


class TestTrainingStateCategories:
    """Tests for per-category score tracking in TrainingState."""

    def test_record_category_answer_single_category(self):
        """Test recording an answer for a single category."""
        training_state = TrainingState()

        # Record a correct answer for economics
        training_state.record_category_answer(['economics'], is_correct=True)

        score = training_state.get_category_score('economics')
        assert score['correct'] == 1
        assert score['total'] == 1
        assert score['accuracy'] == 1.0

    def test_record_category_answer_multiple_categories(self):
        """Test recording an answer for multiple categories."""
        training_state = TrainingState()

        # Record a correct answer for both economics and finance
        training_state.record_category_answer(['economics', 'finance'], is_correct=True)

        econ_score = training_state.get_category_score('economics')
        finance_score = training_state.get_category_score('finance')

        assert econ_score['correct'] == 1
        assert econ_score['total'] == 1
        assert finance_score['correct'] == 1
        assert finance_score['total'] == 1

    def test_record_category_answer_incorrect(self):
        """Test recording an incorrect answer."""
        training_state = TrainingState()

        training_state.record_category_answer(['economics'], is_correct=False)

        score = training_state.get_category_score('economics')
        assert score['correct'] == 0
        assert score['total'] == 1
        assert score['accuracy'] == 0.0

    def test_multiple_answers_same_category(self):
        """Test recording multiple answers for the same category."""
        training_state = TrainingState()

        # 3 correct, 1 incorrect = 75% accuracy
        training_state.record_category_answer(['economics'], is_correct=True)
        training_state.record_category_answer(['economics'], is_correct=True)
        training_state.record_category_answer(['economics'], is_correct=True)
        training_state.record_category_answer(['economics'], is_correct=False)

        score = training_state.get_category_score('economics')
        assert score['correct'] == 3
        assert score['total'] == 4
        assert score['accuracy'] == 0.75

    def test_get_category_score_unknown_category(self):
        """Test getting score for an unknown category."""
        training_state = TrainingState()

        score = training_state.get_category_score('unknown')
        assert score['correct'] == 0
        assert score['total'] == 0
        assert score['accuracy'] == 0.0

    def test_get_qualified_categories_threshold(self):
        """Test getting qualified categories with threshold."""
        training_state = TrainingState()

        # Economics: 80% (qualifies at 0.7)
        training_state.record_category_answer(['economics'], is_correct=True)
        training_state.record_category_answer(['economics'], is_correct=True)
        training_state.record_category_answer(['economics'], is_correct=True)
        training_state.record_category_answer(['economics'], is_correct=True)
        training_state.record_category_answer(['economics'], is_correct=False)

        # Finance: 50% (does not qualify at 0.7)
        training_state.record_category_answer(['finance'], is_correct=True)
        training_state.record_category_answer(['finance'], is_correct=False)

        qualified = training_state.get_qualified_categories(threshold=0.7, min_questions=1)
        assert 'economics' in qualified
        assert 'finance' not in qualified

    def test_get_qualified_categories_min_questions(self):
        """Test that min_questions is respected."""
        training_state = TrainingState()

        # Economics: 100% but only 1 question
        training_state.record_category_answer(['economics'], is_correct=True)

        # Finance: 100% with 3 questions
        training_state.record_category_answer(['finance'], is_correct=True)
        training_state.record_category_answer(['finance'], is_correct=True)
        training_state.record_category_answer(['finance'], is_correct=True)

        # With min_questions=2, only finance qualifies
        qualified = training_state.get_qualified_categories(threshold=0.7, min_questions=2)
        assert 'economics' not in qualified
        assert 'finance' in qualified

    def test_get_all_category_scores(self):
        """Test getting all category scores at once."""
        training_state = TrainingState()

        training_state.record_category_answer(['economics'], is_correct=True)
        training_state.record_category_answer(['finance'], is_correct=False)

        all_scores = training_state.get_all_category_scores()
        assert 'economics' in all_scores
        assert 'finance' in all_scores
        assert all_scores['economics']['accuracy'] == 1.0
        assert all_scores['finance']['accuracy'] == 0.0

    def test_category_scores_serialization(self):
        """Test that category scores are properly serialized."""
        training_state = TrainingState()

        training_state.record_category_answer(['economics'], is_correct=True)
        training_state.record_category_answer(['finance'], is_correct=True)

        data = training_state.to_dict()
        assert 'category_scores' in data
        assert 'economics' in data['category_scores']
        assert 'finance' in data['category_scores']

    def test_category_scores_deserialization(self):
        """Test that category scores are properly deserialized."""
        original = TrainingState()
        original.record_category_answer(['economics'], is_correct=True)
        original.record_category_answer(['economics'], is_correct=True)

        data = original.to_dict()
        restored = TrainingState.from_dict(data)

        assert restored.category_scores == original.category_scores

    def test_get_category_qualification_details(self):
        """Test detailed qualification status."""
        training_state = TrainingState()

        # Economics: 80% with 5 questions
        for _ in range(4):
            training_state.record_category_answer(['economics'], is_correct=True)
        training_state.record_category_answer(['economics'], is_correct=False)

        # Finance: 50% with 2 questions
        training_state.record_category_answer(['finance'], is_correct=True)
        training_state.record_category_answer(['finance'], is_correct=False)

        details = training_state.get_category_qualification_details(threshold=0.7, min_questions=2)

        assert details['economics']['qualified'] is True
        assert details['economics']['meets_threshold'] is True
        assert details['economics']['meets_min_questions'] is True

        assert details['finance']['qualified'] is False
        assert details['finance']['meets_threshold'] is False
        assert details['finance']['meets_min_questions'] is True


class TestUserStateCategories:
    """Tests for user category qualification tracking."""

    def test_add_qualified_category(self):
        """Test adding a qualified category."""
        user_state = InMemoryUserState('test_user')

        user_state.add_qualified_category('economics', 0.85)

        assert user_state.is_qualified_for_category('economics')
        assert user_state.get_category_qualification_score('economics') == 0.85

    def test_remove_qualified_category(self):
        """Test removing a qualified category."""
        user_state = InMemoryUserState('test_user')

        user_state.add_qualified_category('economics', 0.85)
        user_state.remove_qualified_category('economics')

        assert not user_state.is_qualified_for_category('economics')
        assert user_state.get_category_qualification_score('economics') is None

    def test_get_qualified_categories(self):
        """Test getting all qualified categories."""
        user_state = InMemoryUserState('test_user')

        user_state.add_qualified_category('economics', 0.85)
        user_state.add_qualified_category('finance', 0.75)

        qualified = user_state.get_qualified_categories()
        assert 'economics' in qualified
        assert 'finance' in qualified

    def test_get_all_category_qualification_scores(self):
        """Test getting all qualification scores."""
        user_state = InMemoryUserState('test_user')

        user_state.add_qualified_category('economics', 0.85)
        user_state.add_qualified_category('finance', 0.75)

        scores = user_state.get_all_category_qualification_scores()
        assert scores['economics'] == 0.85
        assert scores['finance'] == 0.75

    def test_calculate_and_set_qualifications(self):
        """Test calculating qualifications from training state."""
        user_state = InMemoryUserState('test_user')

        # Add category scores to training state
        training_state = user_state.get_training_state()
        for _ in range(4):
            training_state.record_category_answer(['economics'], is_correct=True)
        training_state.record_category_answer(['economics'], is_correct=False)

        training_state.record_category_answer(['finance'], is_correct=True)
        training_state.record_category_answer(['finance'], is_correct=False)

        # Calculate qualifications with 0.7 threshold
        newly_qualified = user_state.calculate_and_set_qualifications(threshold=0.7, min_questions=1)

        assert 'economics' in newly_qualified
        assert 'finance' not in newly_qualified
        assert user_state.is_qualified_for_category('economics')
        assert not user_state.is_qualified_for_category('finance')


class TestItemStateManagerCategories:
    """Tests for category indexing in ItemStateManager."""

    def get_test_config(self, category_key='category'):
        """Create a test config with category support."""
        return {
            'item_properties': {
                'id_key': 'id',
                'text_key': 'text',
                'category_key': category_key
            },
            'assignment_strategy': 'random',
            'category_assignment': {
                'enabled': True,
                'fallback': 'uncategorized'
            }
        }

    def test_add_item_with_string_category(self):
        """Test adding an item with a string category."""
        config = self.get_test_config()
        ism = ItemStateManager(config)

        ism.add_item('item1', {'id': 'item1', 'text': 'Test', 'category': 'economics'})

        categories = ism.get_categories_for_instance('item1')
        assert 'economics' in categories

        instances = ism.get_instances_by_category('economics')
        assert 'item1' in instances

    def test_add_item_with_list_category(self):
        """Test adding an item with a list of categories."""
        config = self.get_test_config()
        ism = ItemStateManager(config)

        ism.add_item('item1', {'id': 'item1', 'text': 'Test', 'category': ['economics', 'finance']})

        categories = ism.get_categories_for_instance('item1')
        assert 'economics' in categories
        assert 'finance' in categories

        econ_instances = ism.get_instances_by_category('economics')
        assert 'item1' in econ_instances

        finance_instances = ism.get_instances_by_category('finance')
        assert 'item1' in finance_instances

    def test_add_item_without_category(self):
        """Test adding an item without a category."""
        config = self.get_test_config()
        ism = ItemStateManager(config)

        ism.add_item('item1', {'id': 'item1', 'text': 'Test'})

        categories = ism.get_categories_for_instance('item1')
        assert len(categories) == 0

        uncategorized = ism.get_uncategorized_instances()
        assert 'item1' in uncategorized

    def test_add_item_no_category_key_configured(self):
        """Test adding items when no category_key is configured."""
        config = {
            'item_properties': {
                'id_key': 'id',
                'text_key': 'text'
            },
            'assignment_strategy': 'random'
        }
        ism = ItemStateManager(config)

        ism.add_item('item1', {'id': 'item1', 'text': 'Test', 'category': 'economics'})

        # Item should be uncategorized since no category_key is configured
        uncategorized = ism.get_uncategorized_instances()
        assert 'item1' in uncategorized

    def test_get_instances_by_categories(self):
        """Test getting instances by multiple categories."""
        config = self.get_test_config()
        ism = ItemStateManager(config)

        ism.add_item('item1', {'id': 'item1', 'text': 'Test', 'category': 'economics'})
        ism.add_item('item2', {'id': 'item2', 'text': 'Test', 'category': 'finance'})
        ism.add_item('item3', {'id': 'item3', 'text': 'Test', 'category': 'science'})

        instances = ism.get_instances_by_categories({'economics', 'finance'})
        assert 'item1' in instances
        assert 'item2' in instances
        assert 'item3' not in instances

    def test_get_all_categories(self):
        """Test getting all unique categories."""
        config = self.get_test_config()
        ism = ItemStateManager(config)

        ism.add_item('item1', {'id': 'item1', 'text': 'Test', 'category': 'economics'})
        ism.add_item('item2', {'id': 'item2', 'text': 'Test', 'category': ['finance', 'business']})

        all_cats = ism.get_all_categories()
        assert 'economics' in all_cats
        assert 'finance' in all_cats
        assert 'business' in all_cats

    def test_get_category_counts(self):
        """Test getting instance counts per category."""
        config = self.get_test_config()
        ism = ItemStateManager(config)

        ism.add_item('item1', {'id': 'item1', 'text': 'Test', 'category': 'economics'})
        ism.add_item('item2', {'id': 'item2', 'text': 'Test', 'category': 'economics'})
        ism.add_item('item3', {'id': 'item3', 'text': 'Test', 'category': 'finance'})

        counts = ism.get_category_counts()
        assert counts['economics'] == 2
        assert counts['finance'] == 1


class TestAssignmentStrategyEnum:
    """Tests for the AssignmentStrategy enum."""

    def test_category_based_value(self):
        """Test that CATEGORY_BASED has the correct value."""
        assert AssignmentStrategy.CATEGORY_BASED.value == 'category_based'

    def test_category_based_fromstr(self):
        """Test parsing category_based from string."""
        strategy = AssignmentStrategy.fromstr('category_based')
        assert strategy == AssignmentStrategy.CATEGORY_BASED

    def test_category_based_case_insensitive(self):
        """Test that fromstr is case-insensitive."""
        strategy = AssignmentStrategy.fromstr('CATEGORY_BASED')
        assert strategy == AssignmentStrategy.CATEGORY_BASED


class TestCategoryBasedAssignment:
    """Tests for the category-based assignment strategy."""

    def get_test_config(self):
        """Create a test config for category-based assignment."""
        return {
            'item_properties': {
                'id_key': 'id',
                'text_key': 'text',
                'category_key': 'category'
            },
            'assignment_strategy': 'category_based',
            'category_assignment': {
                'enabled': True,
                'fallback': 'uncategorized'
            }
        }

    def test_assignment_strategy_is_category_based(self):
        """Test that the strategy is correctly set."""
        config = self.get_test_config()
        ism = ItemStateManager(config)

        assert ism.assignment_strategy == AssignmentStrategy.CATEGORY_BASED

    def test_assigns_from_qualified_categories(self):
        """Test that instances are assigned from qualified categories."""
        config = self.get_test_config()
        ism = ItemStateManager(config)

        # Add items in different categories
        ism.add_item('econ1', {'id': 'econ1', 'text': 'Test', 'category': 'economics'})
        ism.add_item('econ2', {'id': 'econ2', 'text': 'Test', 'category': 'economics'})
        ism.add_item('sci1', {'id': 'sci1', 'text': 'Test', 'category': 'science'})

        # Create user qualified for economics only
        user_state = InMemoryUserState('test_user')
        user_state.add_qualified_category('economics', 0.85)

        # Mock has_remaining_assignments to return True
        user_state.has_remaining_assignments = MagicMock(return_value=True)
        user_state.get_max_assignments = MagicMock(return_value=-1)

        # Assign instances
        num_assigned = ism.assign_instances_to_user(user_state)

        # Should assign at least 1 instance
        assert num_assigned >= 1

        # Check that assigned instances are from economics
        assigned_ids = user_state.get_assigned_instance_ids()
        for iid in assigned_ids:
            categories = ism.get_categories_for_instance(iid)
            assert 'economics' in categories or iid in ism.get_uncategorized_instances()

    def test_fallback_to_uncategorized(self):
        """Test fallback to uncategorized instances."""
        config = self.get_test_config()
        ism = ItemStateManager(config)

        # Add uncategorized item
        ism.add_item('item1', {'id': 'item1', 'text': 'Test'})  # No category
        # Add categorized item
        ism.add_item('item2', {'id': 'item2', 'text': 'Test', 'category': 'economics'})

        # Create user with no qualifications
        user_state = InMemoryUserState('test_user')
        user_state.has_remaining_assignments = MagicMock(return_value=True)
        user_state.get_max_assignments = MagicMock(return_value=-1)

        # Assign instances - should get uncategorized
        num_assigned = ism.assign_instances_to_user(user_state)

        # Check that assigned instance is uncategorized
        assigned_ids = user_state.get_assigned_instance_ids()
        if num_assigned > 0 and assigned_ids:
            for iid in assigned_ids:
                assert iid in ism.get_uncategorized_instances()

    def test_fallback_random(self):
        """Test fallback to random when configured."""
        config = {
            'item_properties': {
                'id_key': 'id',
                'text_key': 'text',
                'category_key': 'category'
            },
            'assignment_strategy': 'category_based',
            'category_assignment': {
                'enabled': True,
                'fallback': 'random'
            }
        }
        ism = ItemStateManager(config)

        # Add only categorized items
        ism.add_item('item1', {'id': 'item1', 'text': 'Test', 'category': 'economics'})
        ism.add_item('item2', {'id': 'item2', 'text': 'Test', 'category': 'science'})

        # Create user with no qualifications
        user_state = InMemoryUserState('test_user')
        user_state.has_remaining_assignments = MagicMock(return_value=True)
        user_state.get_max_assignments = MagicMock(return_value=-1)

        # Should still assign with random fallback
        num_assigned = ism.assign_instances_to_user(user_state)

        # With random fallback, should still get assignments
        assert num_assigned >= 1
