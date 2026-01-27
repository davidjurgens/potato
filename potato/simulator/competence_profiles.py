"""
Competence profiles for simulated users.

This module defines different competence levels that determine how
accurately a simulated user will annotate items.

When gold standards are available, competence determines the probability
of selecting the gold answer. Without gold standards, competence affects
consistency and selection patterns.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
import random

from .config import CompetenceLevel


class CompetenceProfile(ABC):
    """Abstract base class for competence profiles.

    Competence profiles determine:
    1. Whether to select the correct answer (if gold standard available)
    2. How to select an answer when being incorrect
    """

    @abstractmethod
    def should_be_correct(self) -> bool:
        """Determine if this annotation should be correct.

        Returns:
            True if the annotation should match the gold standard
        """
        pass

    @abstractmethod
    def select_wrong_answer(self, correct: str, options: List[str]) -> str:
        """Select an incorrect answer when making a mistake.

        Args:
            correct: The correct answer (to avoid)
            options: All available options

        Returns:
            A selected incorrect option
        """
        pass

    def get_accuracy(self) -> float:
        """Get the expected accuracy for this profile.

        Returns:
            Expected accuracy as a float between 0 and 1
        """
        return 0.5


class PerfectCompetence(CompetenceProfile):
    """Always correct annotations (100% accuracy).

    Use this for testing gold standard tracking or simulating
    expert annotators.
    """

    def should_be_correct(self) -> bool:
        return True

    def select_wrong_answer(self, correct: str, options: List[str]) -> str:
        # Never called, but return correct just in case
        return correct

    def get_accuracy(self) -> float:
        return 1.0


class GoodCompetence(CompetenceProfile):
    """High-quality annotator (80-90% accuracy).

    Simulates a careful, well-trained annotator who occasionally
    makes mistakes on ambiguous items.
    """

    def __init__(self, accuracy_range: tuple = (0.80, 0.90)):
        self.accuracy = random.uniform(*accuracy_range)

    def should_be_correct(self) -> bool:
        return random.random() < self.accuracy

    def select_wrong_answer(self, correct: str, options: List[str]) -> str:
        wrong_options = [o for o in options if o != correct]
        if wrong_options:
            return random.choice(wrong_options)
        return correct

    def get_accuracy(self) -> float:
        return self.accuracy


class AverageCompetence(CompetenceProfile):
    """Typical annotator (60-70% accuracy).

    Simulates an average crowdworker with moderate attention
    and understanding of the task.
    """

    def __init__(self, accuracy_range: tuple = (0.60, 0.70)):
        self.accuracy = random.uniform(*accuracy_range)

    def should_be_correct(self) -> bool:
        return random.random() < self.accuracy

    def select_wrong_answer(self, correct: str, options: List[str]) -> str:
        wrong_options = [o for o in options if o != correct]
        if wrong_options:
            return random.choice(wrong_options)
        return correct

    def get_accuracy(self) -> float:
        return self.accuracy


class PoorCompetence(CompetenceProfile):
    """Low-quality annotator (40-50% accuracy).

    Simulates an inattentive or untrained annotator who often
    makes mistakes or doesn't fully understand the task.
    """

    def __init__(self, accuracy_range: tuple = (0.40, 0.50)):
        self.accuracy = random.uniform(*accuracy_range)

    def should_be_correct(self) -> bool:
        return random.random() < self.accuracy

    def select_wrong_answer(self, correct: str, options: List[str]) -> str:
        wrong_options = [o for o in options if o != correct]
        if wrong_options:
            return random.choice(wrong_options)
        return correct

    def get_accuracy(self) -> float:
        return self.accuracy


class RandomCompetence(CompetenceProfile):
    """Random selection regardless of correct answer.

    Does not use gold standards at all - simply selects randomly
    from available options. Expected accuracy is ~1/N for N labels.
    """

    def should_be_correct(self) -> bool:
        # Always select randomly - don't use gold standard
        return False

    def select_wrong_answer(self, correct: str, options: List[str]) -> str:
        # Select uniformly at random from all options (including correct)
        return random.choice(options)

    def get_accuracy(self) -> float:
        # Accuracy depends on number of options, estimate ~0.33 for 3 options
        return 0.33


class AdversarialCompetence(CompetenceProfile):
    """Intentionally selects wrong answers.

    Use this for testing quality control systems that should
    detect and flag malicious annotators.
    """

    def should_be_correct(self) -> bool:
        return False

    def select_wrong_answer(self, correct: str, options: List[str]) -> str:
        # Specifically avoid the correct answer
        wrong_options = [o for o in options if o != correct]
        if wrong_options:
            return random.choice(wrong_options)
        # If only one option, have to return it
        return options[0] if options else correct

    def get_accuracy(self) -> float:
        return 0.0


def create_competence_profile(level: CompetenceLevel) -> CompetenceProfile:
    """Factory function to create competence profiles.

    Args:
        level: The competence level enum value

    Returns:
        A CompetenceProfile instance for the specified level
    """
    profiles = {
        CompetenceLevel.PERFECT: PerfectCompetence,
        CompetenceLevel.GOOD: GoodCompetence,
        CompetenceLevel.AVERAGE: AverageCompetence,
        CompetenceLevel.POOR: PoorCompetence,
        CompetenceLevel.RANDOM: RandomCompetence,
        CompetenceLevel.ADVERSARIAL: AdversarialCompetence,
    }

    profile_class = profiles.get(level, AverageCompetence)
    return profile_class()


def create_competence_profile_from_string(level_str: str) -> CompetenceProfile:
    """Create competence profile from string name.

    Args:
        level_str: String name of competence level (e.g., "good", "average")

    Returns:
        A CompetenceProfile instance
    """
    try:
        level = CompetenceLevel(level_str.lower())
    except ValueError:
        level = CompetenceLevel.AVERAGE

    return create_competence_profile(level)
