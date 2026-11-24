"""
`min_chars` on a `text` scheme is a rule, not only a counter.

Before this, `min_chars` only rendered "N/200 min characters" below the box.
Next and Submit did not look at it, and on phase pages the counter did not
update while the participant typed. A study that needs a 200-character
definition had to add its own footer script for both.

Now the page treats text below the minimum as incomplete (tested in
tests/jest/text-min-chars.test.js), and the server refuses it too:
`_instance_meets_required_annotation_rules` on annotation pages and
`_unmet_required_labels` on phase pages. The counter text and the reason in
the error come from `ui_language`.
"""

from unittest.mock import patch

import pytest

from potato.server_utils.schemas import textbox
from potato.server_utils.schemas.textbox import (
    short_text_labels,
    text_min_chars,
)


class FakeLabel:
    def __init__(self, schema, name):
        self._schema = schema
        self._name = name

    def get_schema(self):
        return self._schema

    def get_name(self):
        return self._name


def scheme(**extra):
    base = {"annotation_type": "text", "name": "definition",
            "description": "Define populism", "min_chars": 20}
    base.update(extra)
    return base


LONG = "x" * 20
SHORT = "x" * 5


class TestMinChars:
    @pytest.mark.parametrize("raw, expected", [
        (20, 20), ("20", 20), (0, 0), (-3, 0), (None, 0),
        ("many", 0), (True, 0),
    ])
    def test_a_bad_value_means_no_minimum(self, raw, expected):
        assert text_min_chars({"min_chars": raw}) == expected

    def test_missing_means_no_minimum(self):
        assert text_min_chars({}) == 0


class TestShortTextLabels:
    def test_text_below_the_minimum_is_short(self):
        assert short_text_labels(scheme(), {"text_box": SHORT}, False) == ["text_box"]

    def test_text_at_the_minimum_is_not_short(self):
        assert short_text_labels(scheme(), {"text_box": LONG}, False) == []

    def test_the_length_is_the_trimmed_length(self):
        padded = "   " + "x" * 19 + "   "
        assert short_text_labels(scheme(), {"text_box": padded}, False) == ["text_box"]

    def test_an_optional_empty_box_is_not_short(self):
        assert short_text_labels(scheme(), {}, False) == []
        assert short_text_labels(scheme(), {"text_box": "   "}, False) == []

    def test_a_required_empty_box_is_short(self):
        assert short_text_labels(scheme(), {}, True) == ["text_box"]

    def test_each_box_of_a_multi_box_scheme_is_checked(self):
        multi = scheme(labels=["Pro", "Contra"])
        assert short_text_labels(multi, {"Pro": LONG, "Contra": SHORT}, False) == ["Contra"]
        assert short_text_labels(multi, {"Pro": LONG}, False) == []
        assert short_text_labels(multi, {"Pro": LONG}, True) == ["Contra"]

    def test_no_minimum_never_short(self):
        assert short_text_labels(scheme(min_chars=0), {"text_box": "x"}, True) == []


def _unsatisfied(schemes, annotations):
    from potato import flask_server

    class State:
        instance_id_to_label_to_value = annotations
        instance_id_to_span_to_value = {}

    with patch.object(flask_server, "config", {"annotation_schemes": schemes}):
        return flask_server._instance_meets_required_annotation_rules(State(), "item1")


class TestAnnotationPageServerCheck:
    def test_short_text_blocks_navigation(self):
        answers = {"item1": {FakeLabel("definition", "text_box"): SHORT}}
        assert _unsatisfied([scheme()], answers) == ["definition"]

    def test_long_enough_text_passes(self):
        answers = {"item1": {FakeLabel("definition", "text_box"): LONG}}
        assert _unsatisfied([scheme()], answers) == []

    def test_an_optional_scheme_left_empty_passes(self):
        assert _unsatisfied([scheme()], {"item1": {}}) == []

    def test_a_required_scheme_is_named_once(self):
        req = scheme(label_requirement={"required": True})
        assert _unsatisfied([req], {"item1": {}}) == ["definition"]
        answers = {"item1": {FakeLabel("definition", "text_box"): SHORT}}
        assert _unsatisfied([req], answers) == ["definition"]

    def test_textarea_and_multi_box_schemes_are_checked(self):
        area = scheme(textarea={"on": True, "rows": 4})
        answers = {"item1": {FakeLabel("definition", "text_box"): SHORT}}
        assert _unsatisfied([area], answers) == ["definition"]

        multi = scheme(labels=["Pro", "Contra"])
        answers = {"item1": {FakeLabel("definition", "Pro"): LONG,
                             FakeLabel("definition", "Contra"): SHORT}}
        assert _unsatisfied([multi], answers) == ["definition"]

    def test_other_schemes_ignore_min_chars(self):
        radio = {"annotation_type": "radio", "name": "r", "labels": ["a"], "min_chars": 50}
        assert _unsatisfied([radio], {"item1": {FakeLabel("r", "a"): True}}) == []


def _phase_unmet(schemes, stored):
    from potato import routes

    class State:
        phase_to_page_to_label_to_value = {"prestudy": {"survey": stored}}

        def get_current_phase_and_page(self):
            return "prestudy", "survey"

    with patch.object(routes, "config", {"_phase_page_schemes": {"survey": schemes}}):
        return routes._unmet_required_labels(State())


class TestPhasePageServerCheck:
    def test_short_text_keeps_the_participant_on_the_page(self):
        stored = {FakeLabel("definition", "text_box"): SHORT}
        assert _phase_unmet([scheme()], stored) == ["definition"]

    def test_long_enough_text_lets_them_go(self):
        stored = {FakeLabel("definition", "text_box"): LONG}
        assert _phase_unmet([scheme()], stored) == []

    def test_an_optional_empty_text_lets_them_go(self):
        assert _phase_unmet([scheme()], {}) == []


class TestRendering:
    def _render(self, ui_language=None, **extra):
        with patch.object(textbox, "config", {"ui_language": ui_language} if ui_language else {}):
            html, _ = textbox.generate_textbox_layout(scheme(**extra))
        return html

    def test_the_form_carries_the_minimum_and_the_reason_template(self):
        html = self._render()
        assert 'data-min-chars="20"' in html
        assert 'data-too-short-text="{count} of {min} characters"' in html

    def test_the_counter_holds_a_live_count_span(self):
        html = self._render()
        assert '<span class="shadcn-textbox-char-count">0</span>/20 min characters' in html

    def test_the_counter_without_a_minimum(self):
        html = self._render(min_chars=0, show_char_count=True)
        assert '<span class="shadcn-textbox-char-count">0</span> characters' in html
        assert "data-too-short-text" not in html

    def test_german_strings_come_from_ui_language(self):
        html = self._render("de")
        assert '<span class="shadcn-textbox-char-count">0</span> / mind. 20 Zeichen' in html
        assert 'data-too-short-text="{count} von {min} Zeichen"' in html

    def test_an_inline_override_wins(self):
        html = self._render({"_base": "de", "text_too_short": "nur {count}/{min}"})
        assert 'data-too-short-text="nur {count}/{min}"' in html

    def test_every_box_of_a_multi_box_scheme_gets_a_counter(self):
        html = self._render(labels=["Pro", "Contra"])
        assert html.count('class="shadcn-textbox-char-counter"') == 2
