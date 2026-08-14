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


#: Minimum geometric similarity for a training answer to count as correct.
#: 0.5 IoU is the COCO detection convention: close enough that the annotator
#: clearly found and outlined the right thing, loose enough that a few pixels
#: of boundary difference is not a failure.
DEFAULT_GEOMETRY_TOLERANCE = 0.5


def looks_like_geometry(value: Any) -> bool:
    """True if a value is (or parses to) a list of annotation objects."""
    import json as _json

    parsed = value
    if isinstance(parsed, str):
        try:
            parsed = _json.loads(parsed)
        except (ValueError, TypeError):
            return False
    if not isinstance(parsed, list) or not parsed:
        return False
    return all(isinstance(o, dict) and "type" in o for o in parsed)


def geometry_answer_is_correct(user_value: Any, correct_value: Any,
                                tolerance: float) -> bool:
    """
    Grade a drawn answer by overlap rather than equality.

    Exact comparison is the wrong test for geometry: two people never produce
    byte-identical shapes, so a string match scored EVERY image training answer
    wrong and no trainee could pass a practice image question no matter how
    well they drew.

    Grading is stricter than the agreement measure in ``annotation_values``,
    and deliberately so. Agreement gives partial credit for "right place, wrong
    label", because that IS partial agreement. Training is pass/fail against a
    known answer, and calling a cat a dog is exactly the mistake training
    exists to catch — so every gold shape must be matched by a user shape of
    the SAME label at or above ``tolerance``, with no extras.
    """
    from potato.server_utils import annotation_values
    from potato.server_utils.iaa import geometry

    scheme = {"annotation_type": "image_annotation"}

    def _objects(value):
        return annotation_values.comparable_value(
            scheme, {"_data": value} if isinstance(value, str) else value)

    user_objects = _objects(user_value)
    gold_objects = _objects(correct_value)

    if not gold_objects:
        return not user_objects
    # Drawing extra shapes is as wrong as missing one; a trainee who boxes
    # everything on the image would otherwise always "find" the gold object.
    if len(user_objects) != len(gold_objects):
        return False

    matches, unmatched_gold, unmatched_user = geometry.match_instances(
        gold_objects, user_objects, threshold=tolerance)
    if unmatched_gold or unmatched_user:
        return False

    return all(gold_objects[i].get("label") == user_objects[j].get("label")
               for i, j, _ in matches)


def check_training_answer(user_answer: Dict[str, Any],
                          correct_answers: Dict[str, Any],
                          geometry_tolerance: float = DEFAULT_GEOMETRY_TOLERANCE) -> bool:
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

        # Drawn answers (boxes, polygons, masks, points) are graded by overlap.
        # Checked before the list branch below, because a geometry answer IS a
        # list and would otherwise be set-compared as if the objects were
        # labels — which no two annotators ever match exactly.
        if looks_like_geometry(correct_value):
            if not geometry_answer_is_correct(user_value, correct_value,
                                               geometry_tolerance):
                return False
            continue

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
