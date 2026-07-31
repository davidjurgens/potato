"""
Grading for training-phase practice questions.

Lives outside ``routes.py`` so the storage layer can call it without importing the
whole route module — ``user_state_management.check_training_pass`` grades from stored
annotations, and a route-level import there would be circular.

The ``user_answer`` argument is the **collapsed** ``{schema: comparable_value}`` map
from :mod:`potato.server_utils.answer_collapse`, never raw form data. That distinction
is the whole fix: form field names are ``schema`` for radio/likert but
``schema:::label`` for everything else, so grading against raw form keys could only
ever match those two types and scored every multiselect, text, select and number answer
wrong regardless of what the user picked.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def check_training_answer(user_answer: Dict[str, Any],
                          correct_answers: Dict[str, Any]) -> bool:
    """
    Check if the user's answer matches the correct answers.

    Handles different annotation types:
    - Radio/single select: case-insensitive string comparison
    - Multiselect/checkbox: set comparison (order-independent)
    - Likert/number: numeric comparison
    - Text: exact or fuzzy string match

    Args:
        user_answer: Collapsed ``{schema: comparable_value}`` answers.
        correct_answers: Gold answers by schema name, from the training data file.

    Returns:
        True if all answers are correct, False otherwise
    """
    for schema_name, correct_value in correct_answers.items():
        if schema_name not in user_answer:
            return False

        user_value = user_answer[schema_name]

        # Handle multiselect/checkbox (list comparison)
        if isinstance(correct_value, list):
            if isinstance(user_value, list):
                # Compare as strings: the collapse yields label names while a gold
                # answer may be written as numbers (e.g. likert points).
                if {str(v) for v in user_value} != {str(v) for v in correct_value}:
                    return False
            elif isinstance(user_value, str):
                # Single value submitted, check if it's the only correct answer
                if len(correct_value) != 1 or user_value not in correct_value:
                    return False
            else:
                return False
        # Handle numeric values
        elif isinstance(correct_value, (int, float)):
            try:
                if float(user_value) != float(correct_value):
                    return False
            except (ValueError, TypeError):
                return False
        # Handle string comparison (radio, text)
        else:
            if str(user_value).strip().lower() != str(correct_value).strip().lower():
                return False

    return True
