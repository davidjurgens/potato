"""
A second annotation phase validated and was never served.

`phases.order` takes the author's own names, so nothing stopped two entries
declaring `type: annotation`, and `potato validate --strict` reported "OK — no
issues found". Driven end to end, the annotator reaches "Complete" after the
first pass: the annotation flow owns the item queue and ends the study when it
is empty, so the second phase never runs and nothing says so.

That is the shape this loop keeps finding -- a config accepted, a feature
declared, and silence where the feature should be. It is warned rather than
refused, because the study still works as a single-pass one; an author who
wanted two passes needs to know that is not what they have.

Found while checking the hazard before the auditor drove it: progress counting
across two annotation phases, which is the thing that had already been fixed
twice this session.
"""

import logging

import pytest

from potato.server_utils.config_module import validate_phase_order


def _config(order, blocks):
    return {"phases": dict({"order": order}, **blocks)}


class TestTwoAnnotationPhases:

    def test_two_named_annotation_phases_warn(self, caplog):
        config = _config(
            ["first_pass", "second_pass"],
            {"first_pass": {"type": "annotation"},
             "second_pass": {"type": "annotation"}})
        with caplog.at_level(logging.WARNING):
            validate_phase_order(config)
        messages = [r.getMessage() for r in caplog.records]
        assert any("2 annotation phases" in m for m in messages), messages
        assert any("first_pass" in m and "second_pass" in m
                   for m in messages), messages

    def test_the_bare_annotation_name_counts_too(self, caplog):
        """`annotation` is sequenced through the order with no phase block --
        the main flow owns it -- so a config mixing the bare name with a named
        one is the same mistake."""
        config = _config(
            ["annotation", "second_pass"],
            {"second_pass": {"type": "annotation"}})
        with caplog.at_level(logging.WARNING):
            validate_phase_order(config)
        assert any("annotation phases" in r.getMessage()
                   for r in caplog.records), caplog.records


class TestOneAnnotationPhaseIsSilent:
    """Controls. A warning that fires on ordinary configs is noise, and every
    real study has exactly one annotation phase."""

    @pytest.mark.parametrize("order,blocks", [
        (["annotation"], {}),
        (["consent", "annotation", "poststudy"],
         {"consent": {"type": "consent"}, "poststudy": {"type": "poststudy"}}),
        (["intro", "annotation"], {"intro": {"type": "instructions"}}),
        (["first", "second"],
         {"first": {"type": "instructions"}, "second": {"type": "instructions"}}),
    ])
    def test_no_warning(self, caplog, order, blocks):
        with caplog.at_level(logging.WARNING):
            validate_phase_order(_config(order, blocks))
        messages = [r.getMessage() for r in caplog.records]
        assert not [m for m in messages if "annotation phases" in m], messages

    def test_two_instructions_phases_are_fine(self, caplog):
        """Repeatable names are a real feature: two instructions pages with a
        Previous button between them is the obvious way to split long
        guidelines, and only `annotation` is special."""
        with caplog.at_level(logging.WARNING):
            validate_phase_order(_config(
                ["page_one", "page_two", "annotation"],
                {"page_one": {"type": "instructions"},
                 "page_two": {"type": "instructions"}}))
        messages = [r.getMessage() for r in caplog.records]
        assert not messages, messages


class TestNoPhases:

    @pytest.mark.parametrize("config", [
        {}, {"phases": None}, {"phases": {}}, {"phases": {"order": "annotation"}},
    ])
    def test_nothing_to_check_does_not_raise(self, config):
        validate_phase_order(config)
