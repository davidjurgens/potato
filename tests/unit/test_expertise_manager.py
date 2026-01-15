"""
Unit tests for the ExpertiseManager and dynamic category assignment.

Tests cover:
- CategoryExpertise score updates
- UserExpertiseProfile management
- ExpertiseManager singleton pattern
- Agreement calculation methods
- Probabilistic category selection
- Config validation for dynamic mode
"""

import pytest
import time
from unittest.mock import MagicMock, patch

from potato.expertise_manager import (
    CategoryExpertise,
    UserExpertiseProfile,
    ExpertiseManager,
    AgreementMethod,
    init_expertise_manager,
    get_expertise_manager,
    clear_expertise_manager,
)


class TestCategoryExpertise:
    """Tests for CategoryExpertise dataclass."""

    def test_initial_values(self):
        """Test default initial values."""
        expertise = CategoryExpertise(category="economics")
        assert expertise.category == "economics"
        assert expertise.agreements == 0
        assert expertise.disagreements == 0
        assert expertise.total_evaluated == 0
        assert expertise.expertise_score == 0.5

    def test_update_score_agreement(self):
        """Test score increases on agreement."""
        expertise = CategoryExpertise(category="test")
        initial_score = expertise.expertise_score

        expertise.update_score(agreed=True, learning_rate=0.1)

        assert expertise.agreements == 1
        assert expertise.disagreements == 0
        assert expertise.total_evaluated == 1
        assert expertise.expertise_score > initial_score
        assert expertise.expertise_score <= 1.0

    def test_update_score_disagreement(self):
        """Test score decreases on disagreement."""
        expertise = CategoryExpertise(category="test")
        initial_score = expertise.expertise_score

        expertise.update_score(agreed=False, learning_rate=0.1)

        assert expertise.agreements == 0
        assert expertise.disagreements == 1
        assert expertise.total_evaluated == 1
        assert expertise.expertise_score < initial_score
        assert expertise.expertise_score >= 0.0

    def test_score_capped_at_one(self):
        """Test score cannot exceed 1.0."""
        expertise = CategoryExpertise(category="test", expertise_score=0.95)

        # High learning rate should still cap at 1.0
        expertise.update_score(agreed=True, learning_rate=0.5)

        assert expertise.expertise_score <= 1.0

    def test_score_floored_at_zero(self):
        """Test score cannot go below 0.0."""
        expertise = CategoryExpertise(category="test", expertise_score=0.05)

        # High learning rate should still floor at 0.0
        expertise.update_score(agreed=False, learning_rate=0.5)

        assert expertise.expertise_score >= 0.0

    def test_get_accuracy_no_data(self):
        """Test accuracy returns 0.5 when no data."""
        expertise = CategoryExpertise(category="test")
        assert expertise.get_accuracy() == 0.5

    def test_get_accuracy_with_data(self):
        """Test accuracy calculation."""
        expertise = CategoryExpertise(
            category="test",
            agreements=7,
            disagreements=3,
            total_evaluated=10
        )
        assert expertise.get_accuracy() == 0.7

    def test_to_dict(self):
        """Test serialization to dictionary."""
        expertise = CategoryExpertise(
            category="economics",
            agreements=5,
            disagreements=2,
            total_evaluated=7,
            expertise_score=0.75
        )

        data = expertise.to_dict()

        assert data['category'] == "economics"
        assert data['agreements'] == 5
        assert data['disagreements'] == 2
        assert data['total_evaluated'] == 7
        assert data['expertise_score'] == 0.75

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            'category': 'science',
            'agreements': 10,
            'disagreements': 5,
            'total_evaluated': 15,
            'expertise_score': 0.8
        }

        expertise = CategoryExpertise.from_dict(data)

        assert expertise.category == 'science'
        assert expertise.agreements == 10
        assert expertise.disagreements == 5
        assert expertise.total_evaluated == 15
        assert expertise.expertise_score == 0.8


class TestUserExpertiseProfile:
    """Tests for UserExpertiseProfile dataclass."""

    def test_initial_values(self):
        """Test default initial values."""
        profile = UserExpertiseProfile(user_id="user1")
        assert profile.user_id == "user1"
        assert profile.category_expertise == {}
        assert profile.evaluated_instances == set()
        assert profile.last_updated == 0.0

    def test_get_expertise_creates_new(self):
        """Test get_expertise creates new CategoryExpertise if missing."""
        profile = UserExpertiseProfile(user_id="user1")

        expertise = profile.get_expertise("economics")

        assert "economics" in profile.category_expertise
        assert expertise.category == "economics"
        assert expertise.expertise_score == 0.5

    def test_get_expertise_returns_existing(self):
        """Test get_expertise returns existing CategoryExpertise."""
        profile = UserExpertiseProfile(user_id="user1")
        profile.category_expertise["science"] = CategoryExpertise(
            category="science",
            expertise_score=0.9
        )

        expertise = profile.get_expertise("science")

        assert expertise.expertise_score == 0.9

    def test_get_expertise_score_unknown(self):
        """Test get_expertise_score returns 0.5 for unknown category."""
        profile = UserExpertiseProfile(user_id="user1")
        assert profile.get_expertise_score("unknown") == 0.5

    def test_get_expertise_score_known(self):
        """Test get_expertise_score returns correct score for known category."""
        profile = UserExpertiseProfile(user_id="user1")
        profile.category_expertise["tech"] = CategoryExpertise(
            category="tech",
            expertise_score=0.85
        )

        assert profile.get_expertise_score("tech") == 0.85

    def test_get_all_expertise_scores(self):
        """Test getting all expertise scores."""
        profile = UserExpertiseProfile(user_id="user1")
        profile.category_expertise["cat1"] = CategoryExpertise(category="cat1", expertise_score=0.6)
        profile.category_expertise["cat2"] = CategoryExpertise(category="cat2", expertise_score=0.8)

        scores = profile.get_all_expertise_scores()

        assert scores == {"cat1": 0.6, "cat2": 0.8}

    def test_to_dict(self):
        """Test serialization to dictionary."""
        profile = UserExpertiseProfile(user_id="user1")
        profile.category_expertise["test"] = CategoryExpertise(category="test")
        profile.evaluated_instances.add("instance1")
        profile.last_updated = 12345.0

        data = profile.to_dict()

        assert data['user_id'] == "user1"
        assert "test" in data['category_expertise']
        assert "instance1" in data['evaluated_instances']
        assert data['last_updated'] == 12345.0

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            'user_id': 'user2',
            'category_expertise': {
                'cat1': {
                    'category': 'cat1',
                    'agreements': 5,
                    'disagreements': 2,
                    'total_evaluated': 7,
                    'expertise_score': 0.7
                }
            },
            'evaluated_instances': ['inst1', 'inst2'],
            'last_updated': 9999.0
        }

        profile = UserExpertiseProfile.from_dict(data)

        assert profile.user_id == 'user2'
        assert 'cat1' in profile.category_expertise
        assert profile.category_expertise['cat1'].expertise_score == 0.7
        assert profile.evaluated_instances == {'inst1', 'inst2'}
        assert profile.last_updated == 9999.0


class TestExpertiseManager:
    """Tests for ExpertiseManager class."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clear singleton before and after each test."""
        clear_expertise_manager()
        yield
        clear_expertise_manager()

    def test_singleton_pattern(self):
        """Test ExpertiseManager uses singleton pattern."""
        config = {'category_assignment': {'dynamic': {}}}
        em1 = ExpertiseManager(config)
        em2 = ExpertiseManager(config)

        assert em1 is em2

    def test_init_config_defaults(self):
        """Test default configuration values."""
        config = {}
        em = ExpertiseManager(config)

        assert em.min_annotations_for_consensus == 2
        assert em.agreement_method == AgreementMethod.MAJORITY_VOTE
        assert em.learning_rate == 0.1
        assert em.update_interval_seconds == 60
        assert em.base_probability == 0.1

    def test_init_config_custom(self):
        """Test custom configuration values."""
        config = {
            'category_assignment': {
                'dynamic': {
                    'min_annotations_for_consensus': 3,
                    'agreement_method': 'super_majority',
                    'learning_rate': 0.2,
                    'update_interval_seconds': 120,
                    'base_probability': 0.05
                }
            }
        }
        em = ExpertiseManager(config)

        assert em.min_annotations_for_consensus == 3
        assert em.agreement_method == AgreementMethod.SUPER_MAJORITY
        assert em.learning_rate == 0.2
        assert em.update_interval_seconds == 120
        assert em.base_probability == 0.05

    def test_get_user_profile_creates_new(self):
        """Test get_user_profile creates new profile if missing."""
        em = ExpertiseManager({})
        profile = em.get_user_profile("newuser")

        assert profile.user_id == "newuser"
        assert "newuser" in em.user_profiles

    def test_get_user_profile_returns_existing(self):
        """Test get_user_profile returns existing profile."""
        em = ExpertiseManager({})
        em.user_profiles["existinguser"] = UserExpertiseProfile(user_id="existinguser")
        em.user_profiles["existinguser"].last_updated = 12345.0

        profile = em.get_user_profile("existinguser")

        assert profile.last_updated == 12345.0

    def test_update_user_expertise_agreement(self):
        """Test updating user expertise when they agree."""
        em = ExpertiseManager({})

        agreed = em.update_user_expertise(
            user_id="user1",
            instance_id="inst1",
            category="science",
            user_annotation="correct",
            consensus_value="correct"
        )

        assert agreed is True
        profile = em.get_user_profile("user1")
        assert profile.get_expertise_score("science") > 0.5
        assert "inst1:science" in profile.evaluated_instances

    def test_update_user_expertise_disagreement(self):
        """Test updating user expertise when they disagree."""
        em = ExpertiseManager({})

        agreed = em.update_user_expertise(
            user_id="user1",
            instance_id="inst1",
            category="science",
            user_annotation="wrong",
            consensus_value="correct"
        )

        assert agreed is False
        profile = em.get_user_profile("user1")
        assert profile.get_expertise_score("science") < 0.5

    def test_update_user_expertise_skip_duplicate(self):
        """Test that already-evaluated instances are skipped."""
        em = ExpertiseManager({})

        # First evaluation
        em.update_user_expertise("user1", "inst1", "cat1", "val", "val")

        profile = em.get_user_profile("user1")
        initial_score = profile.get_expertise_score("cat1")

        # Second evaluation of same instance should be skipped
        result = em.update_user_expertise("user1", "inst1", "cat1", "val", "val")

        assert result is False  # Skipped, returns False
        assert profile.get_expertise_score("cat1") == initial_score

    def test_get_category_probabilities_empty(self):
        """Test get_category_probabilities with empty categories."""
        em = ExpertiseManager({})
        probs = em.get_category_probabilities("user1", set())
        assert probs == {}

    def test_get_category_probabilities_uniform(self):
        """Test uniform probabilities for new user."""
        em = ExpertiseManager({'category_assignment': {'dynamic': {'base_probability': 0.5}}})
        probs = em.get_category_probabilities("newuser", {"cat1", "cat2", "cat3"})

        # All categories should have equal probability (0.5 each, normalized)
        assert len(probs) == 3
        assert abs(sum(probs.values()) - 1.0) < 0.001

    def test_get_category_probabilities_weighted(self):
        """Test weighted probabilities based on expertise."""
        em = ExpertiseManager({'category_assignment': {'dynamic': {'base_probability': 0.0}}})
        profile = em.get_user_profile("user1")
        profile.category_expertise["high"] = CategoryExpertise(category="high", expertise_score=0.9)
        profile.category_expertise["low"] = CategoryExpertise(category="low", expertise_score=0.1)

        probs = em.get_category_probabilities("user1", {"high", "low"})

        # Higher expertise should have higher probability
        assert probs["high"] > probs["low"]

    def test_select_category_probabilistically_empty(self):
        """Test select_category returns None for empty categories."""
        em = ExpertiseManager({})
        selected = em.select_category_probabilistically("user1", set())
        assert selected is None

    def test_select_category_probabilistically_single(self):
        """Test select_category with single category."""
        em = ExpertiseManager({})
        selected = em.select_category_probabilistically("user1", {"only_cat"})
        assert selected == "only_cat"

    def test_select_category_probabilistically_weighted(self):
        """Test that selection is weighted by expertise."""
        import random

        em = ExpertiseManager({'category_assignment': {'dynamic': {'base_probability': 0.0}}})
        profile = em.get_user_profile("user1")
        profile.category_expertise["high"] = CategoryExpertise(category="high", expertise_score=0.99)
        profile.category_expertise["low"] = CategoryExpertise(category="low", expertise_score=0.01)

        rng = random.Random(42)
        selections = {"high": 0, "low": 0}

        for _ in range(100):
            selected = em.select_category_probabilistically(
                "user1",
                {"high", "low"},
                random_instance=rng
            )
            selections[selected] += 1

        # High should be selected much more often
        assert selections["high"] > selections["low"]

    def test_to_dict(self):
        """Test serialization of all expertise data."""
        em = ExpertiseManager({})
        em.user_profiles["user1"] = UserExpertiseProfile(user_id="user1")
        em.user_profiles["user2"] = UserExpertiseProfile(user_id="user2")

        data = em.to_dict()

        assert "user_profiles" in data
        assert "user1" in data["user_profiles"]
        assert "user2" in data["user_profiles"]

    def test_from_dict(self):
        """Test deserialization of expertise data."""
        em = ExpertiseManager({})
        data = {
            'user_profiles': {
                'user1': {
                    'user_id': 'user1',
                    'category_expertise': {},
                    'evaluated_instances': [],
                    'last_updated': 100.0
                }
            }
        }

        em.from_dict(data)

        assert "user1" in em.user_profiles
        assert em.user_profiles["user1"].last_updated == 100.0


class TestModuleFunctions:
    """Tests for module-level functions."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clear singleton before and after each test."""
        clear_expertise_manager()
        yield
        clear_expertise_manager()

    def test_init_expertise_manager(self):
        """Test init_expertise_manager creates global instance."""
        config = {'category_assignment': {'dynamic': {'learning_rate': 0.3}}}
        em = init_expertise_manager(config)

        assert em is not None
        assert em.learning_rate == 0.3
        assert get_expertise_manager() is em

    def test_get_expertise_manager_none(self):
        """Test get_expertise_manager returns None before init."""
        assert get_expertise_manager() is None

    def test_clear_expertise_manager(self):
        """Test clear_expertise_manager removes instance."""
        init_expertise_manager({})
        assert get_expertise_manager() is not None

        clear_expertise_manager()
        assert get_expertise_manager() is None


class TestConfigValidation:
    """Tests for dynamic mode config validation."""

    def test_validate_dynamic_enabled_boolean(self):
        """Test that enabled must be a boolean."""
        from potato.server_utils.config_module import validate_category_assignment_config, ConfigValidationError

        config = {
            'category_assignment': {
                'dynamic': {
                    'enabled': 'yes'  # Should be boolean
                }
            }
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_category_assignment_config(config)

        assert "enabled must be a boolean" in str(exc_info.value)

    def test_validate_agreement_method(self):
        """Test that agreement_method must be valid."""
        from potato.server_utils.config_module import validate_category_assignment_config, ConfigValidationError

        config = {
            'category_assignment': {
                'dynamic': {
                    'enabled': True,
                    'agreement_method': 'invalid_method'
                }
            }
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_category_assignment_config(config)

        assert "agreement_method must be one of" in str(exc_info.value)

    def test_validate_min_annotations_for_consensus(self):
        """Test that min_annotations_for_consensus must be >= 2."""
        from potato.server_utils.config_module import validate_category_assignment_config, ConfigValidationError

        config = {
            'category_assignment': {
                'dynamic': {
                    'enabled': True,
                    'min_annotations_for_consensus': 1
                }
            }
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_category_assignment_config(config)

        assert "min_annotations_for_consensus must be an integer >= 2" in str(exc_info.value)

    def test_validate_learning_rate(self):
        """Test that learning_rate must be between 0 and 1."""
        from potato.server_utils.config_module import validate_category_assignment_config, ConfigValidationError

        config = {
            'category_assignment': {
                'dynamic': {
                    'enabled': True,
                    'learning_rate': 1.5
                }
            }
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_category_assignment_config(config)

        assert "learning_rate must be a number between 0.0" in str(exc_info.value)

    def test_validate_update_interval_seconds(self):
        """Test that update_interval_seconds must be >= 1."""
        from potato.server_utils.config_module import validate_category_assignment_config, ConfigValidationError

        config = {
            'category_assignment': {
                'dynamic': {
                    'enabled': True,
                    'update_interval_seconds': 0.5
                }
            }
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_category_assignment_config(config)

        assert "update_interval_seconds must be a number >= 1" in str(exc_info.value)

    def test_validate_base_probability(self):
        """Test that base_probability must be between 0 and 1."""
        from potato.server_utils.config_module import validate_category_assignment_config, ConfigValidationError

        config = {
            'category_assignment': {
                'dynamic': {
                    'enabled': True,
                    'base_probability': -0.1
                }
            }
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_category_assignment_config(config)

        assert "base_probability must be a number between 0.0 and 1.0" in str(exc_info.value)

    def test_validate_valid_config(self):
        """Test that valid config passes validation."""
        from potato.server_utils.config_module import validate_category_assignment_config

        config = {
            'category_assignment': {
                'dynamic': {
                    'enabled': True,
                    'agreement_method': 'majority_vote',
                    'min_annotations_for_consensus': 2,
                    'learning_rate': 0.1,
                    'update_interval_seconds': 60,
                    'base_probability': 0.1
                }
            }
        }

        # Should not raise
        validate_category_assignment_config(config)
