"""
A length with a unit was silently dropped.

Audit 27. Six display types built a CSS length by appending `px`
unconditionally, so an author who wrote `max_height: "220px"` got

    inline    max-height: 220pxpx
    computed  605.6px          <- declaration invalid, dropped, field unclamped

The default is an integer, so it works out of the box and only breaks for
someone who writes the unit. That is not an exotic mistake: the same
`instance_display` block takes `layout.grid.gap`, which REQUIRES a unit, so
writing both lengths the same way is what following the documentation
produces. On a long transcript the difference is a scrollable panel versus a
page whose questions cannot be reached.

`video_display` already had the fix written out, one file away from five that
did not -- the same "answered in one place, forgotten in ten" shape as the CV
exporters' dimensions. The answer now lives in one helper.

`gallery` is the odd one: it computes `max_height - 40`, so it needs a number
rather than a length. Its bare `int()` raised on "220px" and was caught into
the default, which is the same silent revert one layer along.
"""

import pytest

from potato.server_utils.displays.base import css_length, css_pixels


class TestCssLength:

    def test_a_bare_number_becomes_pixels(self):
        """The default path, and the one that always worked."""
        assert css_length(500) == "500px"
        assert css_length(12.5) == "12.5px"

    def test_a_number_written_as_a_string_becomes_pixels(self):
        """YAML quotes numbers more often than authors expect."""
        assert css_length("500") == "500px"
        assert css_length(" 500 ") == "500px"

    def test_a_length_that_already_has_a_unit_is_left_alone(self):
        """The finding. `220px` used to become `220pxpx`."""
        assert css_length("220px") == "220px"
        assert css_length("50%") == "50%"
        assert css_length("30rem") == "30rem"
        assert css_length("80vh") == "80vh"

    def test_a_css_keyword_or_function_survives(self):
        """An author reaching for `calc()` is doing something deliberate."""
        assert css_length("auto") == "auto"
        assert css_length("calc(100vh - 200px)") == "calc(100vh - 200px)"
        assert css_length("var(--panel-height)") == "var(--panel-height)"

    def test_nothing_yields_the_fallback(self):
        assert css_length(None) == ""
        assert css_length("") == ""
        assert css_length(None, "500px") == "500px"

    def test_a_boolean_is_not_a_length(self):
        """`True` is an int in Python, so it would otherwise render `1px`."""
        assert css_length(True) == ""
        assert css_length(False) == ""


class TestCssPixels:

    def test_a_length_in_px_yields_its_number(self):
        assert css_pixels("220px", 400) == 220
        assert css_pixels("220", 400) == 220
        assert css_pixels(220, 400) == 220

    def test_something_unusable_falls_back_and_says_so(self, caplog):
        """The silence was the defect. Reverting to 400 is defensible; doing
        it without a word is not, because the layout just looks wrong."""
        with caplog.at_level("WARNING"):
            assert css_pixels("auto", 400) == 400
        assert any("not a usable pixel length" in r.message
                   for r in caplog.records), caplog.records

    def test_a_boolean_is_not_a_count(self):
        assert css_pixels(True, 400) == 400


class TestTheRenderedStyle:
    """The helper is only useful if the displays call it."""

    def _field_style(self, max_height, min_height=100):
        from potato.server_utils.instance_display import InstanceDisplayRenderer
        renderer = InstanceDisplayRenderer({"task_dir": "."})
        html = renderer._wrap_resizable(
            "<p>body</p>",
            {"key": "t", "type": "text",
             "display_options": {"max_height": max_height,
                                 "min_height": min_height}})
        return html

    def test_a_unit_bearing_max_height_reaches_the_style_attribute(self):
        html = self._field_style("220px")
        assert "max-height: 220px;" in html, html
        assert "pxpx" not in html, html

    def test_min_height_has_the_same_exposure_and_the_same_fix(self):
        html = self._field_style(500, "40vh")
        assert "min-height: 40vh;" in html, html
        assert "pxpx" not in html, html

    def test_the_integer_default_still_renders_pixels(self):
        html = self._field_style(500, 100)
        assert "max-height: 500px;" in html, html
        assert "min-height: 100px;" in html, html


class TestTheWrapperOptionsAreAcceptedEverywhere:
    """`resizable`, `max_height` and `min_height` belong to the wrapper.

    Audit 27 addendum. `_wrap_resizable` runs on every display field unless
    `resizable` turns it off, and reads all three -- but the validator checked
    them against one display type's `optional_fields`. `resizable` is declared
    by 0 of 24 types and `min_height` by 0 of 24, so the option that switches
    the wrapper off and the one that sets its floor were both rejected outright:
    an author could not write the documented thing. `max_height` is declared by
    11 types for their own use, so it passed on those and was refused on the
    other 13.

    The schema registry has carried `UNIVERSAL_OPTIONAL_FIELDS` for exactly
    this reason: a key read by shared machinery belongs to the machinery.
    """

    def _validate(self, field_type, options):
        from potato.server_utils.config_module import (
            _reject_unknown_display_options)
        _reject_unknown_display_options(field_type, options, "f[0]")

    @pytest.mark.parametrize("field_type", ["text", "image", "dialogue"])
    @pytest.mark.parametrize("option,value", [
        ("resizable", False),
        ("min_height", 200),
        ("max_height", "220px"),
    ])
    def test_a_wrapper_option_is_accepted_on_any_display_type(
            self, field_type, option, value):
        self._validate(field_type, {option: value})

    def test_an_unknown_option_is_still_rejected(self):
        """The control. Widening the accepted set must not make it accept
        everything -- the check exists because a dead key is invisible."""
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError):
            self._validate("text", {"definitely_not_an_option": 1})

    def test_a_near_miss_still_gets_its_suggestion(self):
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError) as excinfo:
            self._validate("text", {"max_heigth": 200})
        assert "Did you mean" in str(excinfo.value), str(excinfo.value)
