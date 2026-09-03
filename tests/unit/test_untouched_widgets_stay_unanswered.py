"""Widgets must not answer themselves.

Three schemas rendered a usable-looking default and reported it as the
annotator's answer: `select` preselected its first option, `ranking` wrote the
config order into its hidden input and stamped `data-modified='true'`, and
`range_slider` drew a band between the 25th and 75th percentile. Walking past an
item without touching anything stored a label for it, and on a `ranking` the
same mechanism overwrote an answer the annotator had already given.

The rule these tests pin: a widget nobody has touched reports an empty value and
carries no "touched" mark. Everything downstream keys on that -- the DOM sync
that builds the save payload, the requiredness check, and the restore path.
"""

import re

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError,
    validate_yaml_structure,
)
from potato.server_utils.schemas.ranking import generate_ranking_layout
from potato.server_utils.schemas.range_slider import generate_range_slider_layout
from potato.server_utils.schemas.select import SELECT_PLACEHOLDER, generate_select_layout


def _inputs(html, needle):
    return [m for m in re.findall(r"<input\b[^>]*>", html, re.S) if needle in m]


class TestSelectOpensUnanswered:
    """`syncAnnotationsFromDOM` records any select whose value is non-empty."""

    SCHEME = {
        "annotation_type": "select",
        "name": "dominant_frame",
        "description": "Which single frame dominates?",
        "labels": ["Economic consequences", "Fairness and equality", "No dominant frame"],
    }

    def test_the_first_option_is_an_empty_placeholder(self):
        html, _ = generate_select_layout(self.SCHEME)

        first = re.search(r"<option\b[^>]*>", html).group(0)
        assert 'value=""' in first
        assert "selected" in first
        assert "disabled" in first

    def test_the_placeholder_carries_the_shared_wording(self):
        html, _ = generate_select_layout(self.SCHEME)

        assert SELECT_PLACEHOLDER in html

    def test_no_real_label_is_preselected(self):
        html, _ = generate_select_layout(self.SCHEME)

        selected = re.findall(r"<option\b[^>]*selected[^>]*>", html)
        assert len(selected) == 1
        assert 'value=""' in selected[0]

    def test_every_label_still_renders(self):
        html, _ = generate_select_layout(self.SCHEME)

        for label in self.SCHEME["labels"]:
            assert f'value="{label}"' in html

    def test_a_required_select_can_actually_fail(self):
        """`validation="required"` was a no-op: a select's value is never empty."""
        scheme = dict(self.SCHEME, label_requirement={"required": True})
        html, _ = generate_select_layout(scheme)

        assert 'validation="required"' in html
        # The value the browser reports on arrival, which the requiredness check
        # tests for emptiness.
        first = re.search(r"<option\b[^>]*>", html).group(0)
        assert 'value=""' in first

    @pytest.mark.parametrize("predefined", ["country", "ethnicity", "religion"])
    def test_the_predefined_lists_are_not_given_a_second_placeholder(self, predefined):
        """Those three files have always opened with their own empty option."""
        html, _ = generate_select_layout({
            "annotation_type": "select", "name": "s", "description": "d",
            "labels": ["unused"], "use_predefined_labels": predefined,
        })

        empties = re.findall(r'<option[^>]*value=""[^>]*>', html)
        assert len(empties) == 1


class TestRankingOpensUnanswered:
    SCHEME = {
        "annotation_type": "ranking",
        "name": "difficulty_drivers",
        "description": "Rank what makes the hardest passage hard",
        "labels": ["Vocabulary", "Sentence length", "Abstractness", "Background knowledge"],
    }

    def test_the_hidden_input_starts_empty(self):
        html, _ = generate_ranking_layout(self.SCHEME)

        hidden = _inputs(html, "ranking-order-input")[0]
        assert 'value=""' in hidden

    def test_the_hidden_input_is_not_marked_modified(self):
        html, _ = generate_ranking_layout(self.SCHEME)

        hidden = _inputs(html, "ranking-order-input")[0]
        assert "data-modified" not in hidden

    def test_the_config_order_is_kept_for_resetting_between_instances(self):
        """clearAllFormInputs() puts the rows back in this order."""
        html, _ = generate_ranking_layout(self.SCHEME)

        hidden = _inputs(html, "ranking-order-input")[0]
        assert ('data-placeholder-order="Vocabulary,Sentence length,'
                'Abstractness,Background knowledge"') in hidden

    def test_updateorder_is_not_called_on_load(self):
        """The load-time call wrote the config order in as the annotator's own.

        On a return visit it ran after the server had injected the saved order,
        overwrote it, and the `change` it dispatched replaced currentAnnotations
        before restoreRankingAnnotations() could read it.
        """
        html, _ = generate_ranking_layout(self.SCHEME)

        script = html[html.index("<script>"):]
        # Every remaining call sits inside an event handler.
        tail = script[script.rindex("updateOrder();"):]
        assert "}" in tail, "updateOrder() should be the last thing in some handler"
        # Nothing calls it at the IIFE's top level, i.e. right before its close.
        assert not re.search(r"updateOrder\(\);\s*\}\)\(\);", script)

    def test_the_rows_are_numbered_server_side(self):
        """Which is why nothing needs to run before the first edit."""
        html, _ = generate_ranking_layout(self.SCHEME)

        ranks = re.findall(r'<span class="ranking-rank">(\d+)</span>', html)
        assert ranks == ["1", "2", "3", "4"]


class TestRangeSliderOpensUnanswered:
    SCHEME = {
        "annotation_type": "range_slider",
        "name": "difficulty_range",
        "description": "Plausible difficulty range",
        "min_value": 1,
        "max_value": 16,
    }

    def test_both_hidden_inputs_start_empty(self):
        html, _ = generate_range_slider_layout(self.SCHEME)

        for hidden in _inputs(html, "range-slider-hidden-input"):
            assert 'value=""' in hidden

    def test_neither_is_marked_modified_at_render(self):
        """`data-modified` means the annotator touched it. Nobody had."""
        html, _ = generate_range_slider_layout(self.SCHEME)

        for hidden in _inputs(html, "range-slider-hidden-input"):
            assert "data-modified" not in hidden

    def test_the_track_opens_in_the_unset_state(self):
        html, _ = generate_range_slider_layout(self.SCHEME)

        assert "range-slider-unset" in html

    def test_the_thumbs_announce_the_ends_not_a_quartile(self):
        html, _ = generate_range_slider_layout(self.SCHEME)

        assert re.findall(r'aria-valuenow="(\d+)"', html) == ["1", "16"]

    def test_there_is_a_hint_in_place_of_invented_numbers(self):
        html, _ = generate_range_slider_layout(self.SCHEME)

        assert "range-slider-unset-hint" in html

    def test_a_screen_reader_is_told_the_same_thing_the_screen_says(self):
        """`aria-valuenow` cannot be empty, so unset it necessarily reads as an
        end of the scale. Without an override a screen reader announces "1" --
        indistinguishable from an annotator who chose 1."""
        html, _ = generate_range_slider_layout(self.SCHEME)

        assert html.count('aria-valuetext="No range set"') == 2

    def test_the_script_clears_that_text_once_a_range_is_set(self):
        html, _ = generate_range_slider_layout(self.SCHEME)

        assert "removeAttribute('aria-valuetext')" in html


class TestBwsNeedsATupleSource:
    """`bws` does not read candidates off the item; it needs the generator block."""

    def _config(self, **extra):
        config = {
            "annotation_task_name": "t",
            "item_properties": {"id_key": "id", "text_key": "text"},
            "task_dir": ".",
            "output_annotation_dir": "out/",
            "data_files": ["d.json"],
            "annotation_schemes": [{
                "annotation_type": "bws",
                "name": "difficulty_bws",
                "description": "Which is easiest and which is hardest?",
                "tuple_size": 4,
            }],
        }
        config.update(extra)
        return config

    def test_a_bws_scheme_without_a_config_block_fails(self):
        with pytest.raises(ConfigValidationError, match="bws_config"):
            validate_yaml_structure(self._config())

    def test_the_message_names_the_scheme(self):
        with pytest.raises(ConfigValidationError, match="difficulty_bws"):
            validate_yaml_structure(self._config())

    def test_bws_config_satisfies_it(self):
        validate_yaml_structure(self._config(bws_config={"tuple_size": 4}))

    def test_ibws_config_satisfies_it_too(self):
        validate_yaml_structure(self._config(ibws_config={"tuple_size": 4}))

    def test_a_config_with_no_bws_scheme_is_untouched(self):
        validate_yaml_structure({
            "annotation_task_name": "t",
            "item_properties": {"id_key": "id", "text_key": "text"},
            "task_dir": ".",
            "output_annotation_dir": "out/",
            "data_files": ["d.json"],
            "annotation_schemes": [{
                "annotation_type": "radio", "name": "r",
                "description": "d", "labels": ["a", "b"]}],
        })
