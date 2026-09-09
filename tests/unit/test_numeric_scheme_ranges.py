"""Three numeric schemes accepted configurations with no valid state.

`number` accepted min > max, in both key spellings, where `slider` and
`range_slider` reject it with "min_value must be less than max_value". The
rendered `<input type="number" min="10" max="1">` cannot be filled -- Chrome
reports every value invalid with its own message, "Minimum value (10) must be
less than the maximum value (1)", which is the check Potato skipped. One such
field makes `form.checkValidity()` false for the whole page, so a scheme nobody
can answer blocks every other scheme beside it.

`constant_sum` accepted `min_per_item x len(labels) > total_points`. Four
labels, 10 points, minimum 5: filling the declared minimum in every box -- the
only thing each input's `min="5"` allows -- gives "Allocated: 20 / 10,
Remaining: -10". Both constraints are enforced and they contradict each other.

`slider.starting_value` outside the range was silently clamped by the browser
while the tooltip was painted with the unclamped number. Declared 99 on a 0..10
slider: input value 10, tooltip "99", thumb at the right end, consistent with
both readings. The disagreement lives in the state the annotator sees FIRST, so
someone who agrees with the default and saves without touching the control
reads 99 and stores 10 -- a wrong value in the dataset with no annotator error
involved.

The first two are refusals because there is no usable widget to keep running.
The third is a clamp with a warning, because there is.
"""

import logging
import re

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError, validate_single_annotation_scheme)

PATH = "annotation_schemes[0]"


def check(scheme):
    validate_single_annotation_scheme(scheme, PATH)


def number(**extra):
    return {"annotation_type": "number", "name": "n", "description": "d",
            **extra}


def constant_sum(**extra):
    scheme = {"annotation_type": "constant_sum", "name": "c",
              "description": "d", "labels": ["a", "b", "c", "d"]}
    scheme.update(extra)
    return scheme


def slider(**extra):
    scheme = {"annotation_type": "slider", "name": "s", "description": "d",
              "min_value": 0, "max_value": 10, "starting_value": 5}
    scheme.update(extra)
    return scheme


class TestNumberRefusesAnInvertedRange:

    @pytest.mark.parametrize("scheme", [
        number(min_value=10, max_value=1),
        number(min=10, max=1),
        number(min_value=10, max=1),
        number(min=10, max_value=1),
    ])
    def test_it_is_refused(self, scheme):
        with pytest.raises(ConfigValidationError, match="minimum above its maximum"):
            check(scheme)

    def test_both_spellings_are_checked(self):
        """The generator reads both, so checking one would leave a way around
        this."""
        with pytest.raises(ConfigValidationError):
            check(number(min=10, max=1))

    @pytest.mark.parametrize("scheme", [
        number(min=1, max=10),
        number(min_value=1, max_value=10),
        number(min=5, max=5),
        number(min=1),
        number(max=10),
        number(),
    ])
    def test_a_usable_range_is_accepted(self, scheme):
        check(scheme)

    def test_a_non_numeric_bound_is_a_different_complaint(self):
        """The browser ignores an unparseable attribute; do not turn that into
        this error."""
        check(number(min="a", max="b"))


class TestConstantSumRefusesAnImpossibleMinimum:

    def test_the_measured_case_is_refused(self):
        with pytest.raises(ConfigValidationError, match="cannot be completed"):
            check(constant_sum(total_points=10, min_per_item=5))

    def test_the_message_names_both_numbers(self):
        with pytest.raises(ConfigValidationError) as caught:
            check(constant_sum(total_points=10, min_per_item=5))
        message = str(caught.value)
        assert "20" in message and "10" in message

    def test_exactly_satisfiable_is_allowed(self):
        check({"annotation_type": "constant_sum", "name": "c",
               "description": "d", "labels": ["a", "b"],
               "total_points": 10, "min_per_item": 5})

    def test_no_minimum_is_allowed(self):
        check(constant_sum(total_points=10))

    def test_the_default_total_is_used_when_none_is_given(self):
        """`total_points` defaults to 100, so an impossible minimum is
        impossible whether or not the total was written down."""
        with pytest.raises(ConfigValidationError):
            check({"annotation_type": "constant_sum", "name": "c",
                   "description": "d", "labels": ["a", "b"],
                   "min_per_item": 60})


class TestSliderStartingValueIsClamped:

    def _rendered(self, starting):
        from potato.server_utils.schemas.slider import generate_slider_layout

        html, _ = generate_slider_layout(
            {"annotation_type": "slider", "name": "s", "description": "d",
             "min_value": 0, "max_value": 10, "starting_value": starting})
        return html

    def _surfaces(self, html):
        """The three places the starting value appears, which disagreed."""
        return {
            "input": re.search(r'value="([^"]*)"', html).group(1),
            "tooltip": re.search(r'slider-tooltip[^>]*>([^<]*)<', html).group(1),
            "script": re.search(r"updateSliderPosition\((\S+?),", html).group(1),
        }

    def test_all_three_surfaces_agree_when_too_high(self):
        surfaces = self._surfaces(self._rendered(99))
        assert set(surfaces.values()) == {"10"}, (
            f"the browser clamps the input to 10 and the annotator was shown "
            f"{surfaces['tooltip']} as the default: {surfaces}")

    def test_all_three_surfaces_agree_when_too_low(self):
        assert set(self._surfaces(self._rendered(-5)).values()) == {"0"}

    def test_an_in_range_value_is_untouched(self):
        assert set(self._surfaces(self._rendered(7)).values()) == {"7"}

    def test_the_boundaries_are_in_range(self):
        assert set(self._surfaces(self._rendered(0)).values()) == {"0"}
        assert set(self._surfaces(self._rendered(10)).values()) == {"10"}

    def test_it_is_reported_rather_than_silent(self, caplog):
        with caplog.at_level(logging.WARNING):
            self._rendered(99)
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "99" in message and "starting_value" in message

    def test_an_in_range_value_says_nothing(self, caplog):
        with caplog.at_level(logging.WARNING):
            self._rendered(7)
        assert not [r for r in caplog.records
                    if r.levelno >= logging.WARNING
                    and "starting_value" in r.getMessage()]

    def test_validate_warns_too(self, caplog):
        """A boot log is not what `potato validate` reads."""
        with caplog.at_level(logging.WARNING):
            check(slider(starting_value=99))
        assert "starting_value" in " ".join(
            r.getMessage() for r in caplog.records)

    def test_validate_does_not_refuse_it(self):
        """The widget works; refusing would stop a task that runs today."""
        check(slider(starting_value=99))

    def test_an_inverted_slider_range_is_still_refused(self):
        with pytest.raises(ConfigValidationError,
                           match="min_value must be less than max_value"):
            check(slider(min_value=10, max_value=1))
