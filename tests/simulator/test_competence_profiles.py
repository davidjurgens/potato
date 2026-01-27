"""Tests for competence profiles."""

import pytest
from potato.simulator.competence_profiles import (
    CompetenceProfile,
    PerfectCompetence,
    GoodCompetence,
    AverageCompetence,
    PoorCompetence,
    RandomCompetence,
    AdversarialCompetence,
    create_competence_profile,
    create_competence_profile_from_string,
)
from potato.simulator.config import CompetenceLevel


class TestPerfectCompetence:
    """Tests for PerfectCompetence profile."""

    def test_always_correct(self):
        """Perfect competence should always be correct."""
        profile = PerfectCompetence()
        # Run many times to ensure it's always True
        results = [profile.should_be_correct() for _ in range(100)]
        assert all(results)

    def test_accuracy(self):
        """Perfect competence should report 100% accuracy."""
        profile = PerfectCompetence()
        assert profile.get_accuracy() == 1.0


class TestGoodCompetence:
    """Tests for GoodCompetence profile."""

    def test_accuracy_range(self):
        """Good competence should have 80-90% accuracy."""
        profile = GoodCompetence()
        assert 0.80 <= profile.get_accuracy() <= 0.90

    def test_mostly_correct(self):
        """Good competence should be mostly correct."""
        profile = GoodCompetence()
        results = [profile.should_be_correct() for _ in range(1000)]
        correct_rate = sum(results) / len(results)
        # Should be in the 80-90% range with some tolerance
        assert 0.70 <= correct_rate <= 0.95

    def test_select_wrong_answer(self):
        """Should select a different answer than correct."""
        profile = GoodCompetence()
        options = ["positive", "negative", "neutral"]
        wrong = profile.select_wrong_answer("positive", options)
        assert wrong != "positive"
        assert wrong in options


class TestAverageCompetence:
    """Tests for AverageCompetence profile."""

    def test_accuracy_range(self):
        """Average competence should have 60-70% accuracy."""
        profile = AverageCompetence()
        assert 0.60 <= profile.get_accuracy() <= 0.70


class TestPoorCompetence:
    """Tests for PoorCompetence profile."""

    def test_accuracy_range(self):
        """Poor competence should have 40-50% accuracy."""
        profile = PoorCompetence()
        assert 0.40 <= profile.get_accuracy() <= 0.50


class TestRandomCompetence:
    """Tests for RandomCompetence profile."""

    def test_never_correct(self):
        """Random competence should_be_correct always returns False (ignore gold)."""
        profile = RandomCompetence()
        results = [profile.should_be_correct() for _ in range(100)]
        assert all(not r for r in results)

    def test_select_wrong_includes_correct(self):
        """Random selection can include the 'correct' answer."""
        profile = RandomCompetence()
        options = ["positive", "negative", "neutral"]
        selections = [
            profile.select_wrong_answer("positive", options) for _ in range(100)
        ]
        # Should include all options including 'positive'
        assert "positive" in selections


class TestAdversarialCompetence:
    """Tests for AdversarialCompetence profile."""

    def test_never_correct(self):
        """Adversarial competence should never be correct."""
        profile = AdversarialCompetence()
        results = [profile.should_be_correct() for _ in range(100)]
        assert all(not r for r in results)

    def test_avoids_correct_answer(self):
        """Should avoid the correct answer when selecting."""
        profile = AdversarialCompetence()
        options = ["positive", "negative", "neutral"]
        selections = [
            profile.select_wrong_answer("positive", options) for _ in range(100)
        ]
        # Should never select 'positive'
        assert "positive" not in selections

    def test_accuracy(self):
        """Adversarial should report 0% accuracy."""
        profile = AdversarialCompetence()
        assert profile.get_accuracy() == 0.0


class TestCreateCompetenceProfile:
    """Tests for factory functions."""

    @pytest.mark.parametrize(
        "level,expected_class",
        [
            (CompetenceLevel.PERFECT, PerfectCompetence),
            (CompetenceLevel.GOOD, GoodCompetence),
            (CompetenceLevel.AVERAGE, AverageCompetence),
            (CompetenceLevel.POOR, PoorCompetence),
            (CompetenceLevel.RANDOM, RandomCompetence),
            (CompetenceLevel.ADVERSARIAL, AdversarialCompetence),
        ],
    )
    def test_create_from_enum(self, level, expected_class):
        """Should create correct profile type from enum."""
        profile = create_competence_profile(level)
        assert isinstance(profile, expected_class)

    @pytest.mark.parametrize(
        "level_str,expected_class",
        [
            ("perfect", PerfectCompetence),
            ("good", GoodCompetence),
            ("average", AverageCompetence),
            ("poor", PoorCompetence),
            ("random", RandomCompetence),
            ("adversarial", AdversarialCompetence),
            ("GOOD", GoodCompetence),  # Case insensitive
            ("invalid", AverageCompetence),  # Falls back to average
        ],
    )
    def test_create_from_string(self, level_str, expected_class):
        """Should create correct profile type from string."""
        profile = create_competence_profile_from_string(level_str)
        assert isinstance(profile, expected_class)
