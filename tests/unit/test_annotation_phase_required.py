"""A study needs an annotation phase, and the validator says so.

With no annotation schemes the server crashed at startup. Leaving
`annotation` out of `phases.order` did not skip it: it ran after the last
page listed, after the debrief.
"""

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError, validate_annotation_phase_present)

RADIO = [{"annotation_type": "radio", "name": "q", "description": "Q", "labels": ["a", "b"]}]


def test_no_annotation_schemes_is_refused_with_the_workaround():
    with pytest.raises(ConfigValidationError, match="single label"):
        validate_annotation_phase_present({"annotation_schemes": []})
    with pytest.raises(ConfigValidationError, match="annotation_schemes"):
        validate_annotation_phase_present({})


def test_phases_order_without_annotation_is_refused():
    config = {"annotation_schemes": RADIO,
              "phases": {"order": ["consent", "survey"],
                         "consent": {"type": "consent", "file": "c.json"},
                         "survey": {"type": "poststudy", "file": "s.json"}}}
    with pytest.raises(ConfigValidationError, match="no annotation phase"):
        validate_annotation_phase_present(config)


@pytest.mark.parametrize("order", [["consent", "annotation"],
                                   ["consent", "main"]])
def test_an_annotation_phase_by_name_or_type_is_fine(order):
    config = {"annotation_schemes": RADIO,
              "phases": {"order": order, "consent": {"type": "consent", "file": "c.json"},
                         "main": {"type": "annotation"}}}
    validate_annotation_phase_present(config)


def test_no_phases_block_is_fine():
    validate_annotation_phase_present({"annotation_schemes": RADIO})
