"""
Two annotation schemes with the same `name` silently destroyed an answer.

    - {annotation_type: radio, name: verdict, labels: [alpha, beta]}
    - {annotation_type: radio, name: verdict, labels: [gamma, delta]}

`potato validate --strict` said "OK — no issues found", the boot log was quiet,
and both questions rendered looking independent. But storage is keyed by scheme
name and so is the rendered form: all four inputs come out as `name="verdict"`,
which in HTML is ONE mutually exclusive radio group. Driven end to end:

    click alpha (question 1)   alpha = true
    click gamma (question 2)   alpha = FALSE, gamma = true
    stored                     {"verdict": ["gamma"]}

The annotator answers two questions, watches the first clear itself, and one
answer is not in the dataset.

Raised rather than warned, unlike the two-annotation-phase case where the study
still works as a single-pass one. Here there is no configuration in which this
is what the author meant -- the second scheme cannot store anything of its own
-- so the study is not degraded, it is broken, and it loses data while
appearing to work.

The idea already existed one level down: duplicate LABELS inside one scheme are
caught at render time and reported on the page by name. Same check, one level
up, where the consequence is worse and nothing was looking.
"""

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError,
    validate_annotation_schemes,
)


def _radio(name, labels):
    return {"annotation_type": "radio", "name": name,
            "description": f"{name} question", "labels": labels}


class TestDuplicateSchemeNames:

    def test_two_schemes_with_one_name_are_refused(self):
        with pytest.raises(ConfigValidationError) as excinfo:
            validate_annotation_schemes({"annotation_schemes": [
                _radio("verdict", ["alpha", "beta"]),
                _radio("verdict", ["gamma", "delta"]),
            ]})
        message = str(excinfo.value)
        assert "verdict" in message, message
        assert "annotation_schemes[1]" in message, message
        assert "annotation_schemes[0]" in message, message

    def test_the_message_says_what_goes_wrong(self):
        """An author who reads "duplicate name" may well think it is
        cosmetic. The reason it destroys an answer is the part that makes
        them fix it rather than work around it."""
        with pytest.raises(ConfigValidationError) as excinfo:
            validate_annotation_schemes({"annotation_schemes": [
                _radio("verdict", ["a"]), _radio("verdict", ["b"])]})
        message = str(excinfo.value)
        assert "clears the first" in message or "only one answer" in message, message

    def test_a_third_duplicate_still_names_the_first_collision(self):
        with pytest.raises(ConfigValidationError) as excinfo:
            validate_annotation_schemes({"annotation_schemes": [
                _radio("a", ["x"]), _radio("b", ["x"]), _radio("a", ["y"])]})
        assert "annotation_schemes[2]" in str(excinfo.value), str(excinfo.value)

    def test_schemes_of_different_types_collide_too(self):
        """The collision is the storage key, not the widget: a radio and a
        multiselect sharing a name overwrite each other just the same."""
        with pytest.raises(ConfigValidationError):
            validate_annotation_schemes({"annotation_schemes": [
                _radio("shared", ["a"]),
                {"annotation_type": "multiselect", "name": "shared",
                 "description": "d", "labels": ["b"]}]})


class TestOrdinaryConfigsAreUnaffected:
    """Controls. Every real study has distinct scheme names, and a check that
    fires on those is worse than the bug."""

    def test_distinct_names_pass(self):
        validate_annotation_schemes({"annotation_schemes": [
            _radio("first", ["a"]), _radio("second", ["b"])]})

    def test_one_scheme_passes(self):
        validate_annotation_schemes({"annotation_schemes": [_radio("only", ["a"])]})

    def test_names_differing_only_in_case_are_allowed(self):
        """Storage keys are case-sensitive, so these genuinely are two
        schemes. Refusing them would be inventing a rule."""
        validate_annotation_schemes({"annotation_schemes": [
            _radio("Verdict", ["a"]), _radio("verdict", ["b"])]})


class TestPhaseScopedSchemes:
    """Phases carry their own scheme lists, and the same collision applies
    inside one."""

    def test_duplicate_inside_a_dict_phase_is_refused(self):
        with pytest.raises(ConfigValidationError) as excinfo:
            validate_annotation_schemes({"phases": {
                "main": {"annotation_schemes": [
                    _radio("verdict", ["a"]), _radio("verdict", ["b"])]}}})
        assert "phases.main.annotation_schemes" in str(excinfo.value), \
            str(excinfo.value)

    def test_duplicate_inside_a_list_phase_is_refused(self):
        with pytest.raises(ConfigValidationError) as excinfo:
            validate_annotation_schemes({"phases": [
                {"name": "main", "annotation_schemes": [
                    _radio("verdict", ["a"]), _radio("verdict", ["b"])]}]})
        assert "phases[0].annotation_schemes" in str(excinfo.value), \
            str(excinfo.value)

    def test_the_same_name_in_two_different_phases_is_allowed(self):
        """Different phases store separately -- a `confidence` question on the
        prestudy and another during annotation is a normal thing to want."""
        validate_annotation_schemes({"phases": {
            "one": {"annotation_schemes": [_radio("confidence", ["a"])]},
            "two": {"annotation_schemes": [_radio("confidence", ["b"])]}}})
