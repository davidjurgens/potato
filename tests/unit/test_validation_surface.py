"""A config that cannot work is refused by `config_module`, not by a generator.

A generator is not a validation surface. `identifier_utils.safe_generate_layout`
catches everything a layout function raises, logs it, and returns an error card
-- which is right for the page, since one broken scheme must not take the whole
task down, and is exactly why a check placed in a generator fails open.
`potato validate --strict` still reports "OK" and the study ships with one
question replaced by a red box.

Three separate checks in one week existed somewhere that could not refuse:

  * an inverted `number` range raised in the generator; validate said OK
  * `require_fully_annotated` was accepted, typed, published and read by
    nothing at top level
  * `min_response_time` was measured by the client being measured

This pins the rule for the cases we know about: a scheme with no valid state is
refused by `validate_single_annotation_scheme`, which is the surface `potato
validate` reads. It is not a claim that every generator raise has a config-level
twin -- that would need every generator enumerated -- but it fails if any of
these particular refusals moves back into a generator.
"""

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError, validate_single_annotation_scheme)


#: Schemes with no state an annotator could reach, and why.
UNREACHABLE = [
    pytest.param(
        {"annotation_type": "number", "name": "n", "description": "d",
         "min_value": 10, "max_value": 1},
        id="number-inverted-range"),
    pytest.param(
        {"annotation_type": "number", "name": "n", "description": "d",
         "min": 10, "max": 1},
        id="number-inverted-range-short-spelling"),
    pytest.param(
        {"annotation_type": "constant_sum", "name": "c", "description": "d",
         "labels": ["a", "b", "c", "d"], "total_points": 10,
         "min_per_item": 5},
        id="constant-sum-impossible-minimum"),
    pytest.param(
        {"annotation_type": "slider", "name": "s", "description": "d",
         "min_value": 10, "max_value": 1, "starting_value": 5},
        id="slider-inverted-range"),
]


class TestTheSurfaceValidateReadsRefusesThem:

    @pytest.mark.parametrize("scheme", UNREACHABLE)
    def test_it_is_refused(self, scheme):
        with pytest.raises(ConfigValidationError):
            validate_single_annotation_scheme(scheme, "annotation_schemes[0]")

    @pytest.mark.parametrize("scheme", UNREACHABLE)
    def test_the_refusal_names_the_scheme_path(self, scheme):
        """A message that does not say which scheme sends the author hunting."""
        with pytest.raises(ConfigValidationError) as caught:
            validate_single_annotation_scheme(scheme, "annotation_schemes[3]")
        assert "annotation_schemes[3]" in str(caught.value)


class TestAGeneratorRaiseIsNotARefusal:
    """The property that makes the rule necessary, asserted rather than
    assumed: a layout function that raises produces a page, not a failure."""

    def test_a_raising_generator_yields_an_error_card(self):
        from potato.server_utils.schemas.identifier_utils import (
            safe_generate_layout)

        def boom(_scheme):
            raise ValueError("this would be a config error")

        html, keybindings = safe_generate_layout(
            {"name": "explodes", "description": "d"}, boom)
        assert "annotation-error" in html, (
            "a generator raise has to degrade to a card; if it propagated, "
            "the rule this file documents would be unnecessary")
        assert keybindings == []

    def test_the_message_reaches_the_page(self):
        from potato.server_utils.schemas.identifier_utils import (
            safe_generate_layout)

        def boom(_scheme):
            raise ValueError("MARKER_TEXT")

        html, _ = safe_generate_layout({"name": "explodes",
                                        "description": "d"}, boom)
        assert "MARKER_TEXT" in html

    def test_a_working_generator_is_untouched(self):
        from potato.server_utils.schemas.identifier_utils import (
            safe_generate_layout)

        html, keys = safe_generate_layout(
            {"name": "ok", "description": "d"},
            lambda _s: ("<p>fine</p>", ["a"]))
        assert html == "<p>fine</p>" and keys == ["a"]
