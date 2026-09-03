"""The server and the client have to agree on what a restored answer looks like.

A range input always reports a value -- `slider`, `vas`, `soft_label` and
`constant_sum` in slider mode all render at a starting position -- so
`loadAnnotations()` and `validateRequiredFields()` treat one as an answer only
when `data-server-set` or `data-modified` says where the value came from.

`render_page_with_annotations()` set the value attribute on a restored range and
stopped there. The two halves disagreed, with a visible result: a *required*
slider the annotator had already answered blocked Next for good the moment they
navigated back to that item. It rendered at the right position and read as
unanswered.

These pin the contract from both ends.
"""

import re
from pathlib import Path

import pytest

import potato
from potato.server_utils.schemas.select import generate_select_layout


SERVER = (Path(potato.__file__).parent / "flask_server.py").read_text(encoding="utf-8")
CLIENT = (Path(potato.__file__).parent / "static" / "annotation.js").read_text(encoding="utf-8")


def _restore_block(marker, end_marker):
    """The body of one of the two restore loops."""
    start = SERVER.index(marker)
    return SERVER[start:SERVER.index(end_marker, start)]


class TestRangeInputsAreMarkedServerSet:
    def test_the_server_stamps_the_flag_when_it_restores_a_range(self):
        block = _restore_block(
            "# If it's a range input", "if input_field.get('type') == 'checkbox'")

        assert "input_field['value'] = value" in block
        assert "input_field['data-server-set'] = 'true'" in block, (
            "A restored slider that is not marked server-set is rendered but not "
            "adopted, so a required slider the annotator already answered blocks "
            "Next after they navigate back to it."
        )

    def test_the_client_still_requires_the_flag(self):
        """If this stops being true the stamp above is pointless, not harmless."""
        block = CLIENT[CLIENT.index('const sliderInputs = document.querySelectorAll(\'input[type="range"]\');',
                                    CLIENT.index("async function loadAnnotations")):]
        block = block[:block.index("// Read select dropdown state")]

        assert "if (!input.hasAttribute('data-server-set')) return;" in block

    def test_requiredness_reads_the_same_two_marks(self):
        block = CLIENT[CLIENT.index("function validateRequiredFields"):]
        block = block[:block.index("function updateRequiredFieldsError")]

        assert "data-modified" in block and "data-server-set" in block


class TestBothRenderPathsRestoreTheSameInputTypes:
    """CLAUDE.md: a feature wired into one render path does nothing on the other.

    `render_page_with_annotations()` serves annotation pages;
    `get_current_page_html()` serves consent, instructions, training and the
    survey pages. The phase-page loop handled checkbox, radio, text, number,
    textarea and select, and nothing else -- so a `slider` or a `ranking`
    answered on a survey page was stored server-side and rendered back at its
    default. Re-showing that page put the default in front of the respondent,
    and a resubmit overwrote the real answer.
    """

    PHASE_LOOP = ("    phase_annotations = user_state.phase_to_page_to_label_to_value",
                  "    # Cross-page conditional display_logic")

    def _phase_loop(self):
        start = SERVER.index(self.PHASE_LOOP[0])
        return SERVER[start:SERVER.index(self.PHASE_LOOP[1], start)]

    def test_the_phase_page_restores_ranges(self):
        block = self._phase_loop()

        assert "if input_field.get('type') == 'range':" in block
        assert "input_field['data-server-set'] = 'true'" in block

    def test_the_phase_page_restores_hidden_inputs(self):
        """bws, ranking, triage, range_slider and the media schemas all use them."""
        block = self._phase_loop()

        assert "if input_field.get('type') == 'hidden':" in block

    def test_a_ranking_puts_its_own_rows_back(self):
        """Reordering the rows is the widget's job, so it holds on every path.

        The annotation page also runs restoreRankingAnnotations(); phase pages
        run no such pass, so without this the input held the saved order while
        the rows on screen showed the config order.
        """
        from potato.server_utils.schemas.ranking import generate_ranking_layout

        html, _ = generate_ranking_layout({
            "annotation_type": "ranking", "name": "r", "description": "d",
            "labels": ["a", "b", "c"]})

        assert "applyStoredOrder" in html
        # Read-only: it must not claim the annotator touched anything.
        block = html[html.index("applyStoredOrder"):html.index("Deliberately NOT calling")]
        assert "data-modified" not in block
        assert "dispatchEvent" not in block


class TestSelectRestoreClearsThePlaceholder:
    """Both render paths, because there are two of them (see CLAUDE.md)."""

    MARKERS = [
        ("# Handle select elements - set the 'selected' attribute on matching option",
         "if False:"),
        ("            if input_field.name == 'select':",
         "    # Cross-page conditional display_logic"),
    ]

    @pytest.mark.parametrize("marker,end", MARKERS)
    def test_other_options_are_deselected_explicitly(self, marker, end):
        block = _restore_block(marker, end)

        assert 'del other["selected"]' in block, (
            "The placeholder is rendered `selected`. Leaving it and relying on "
            "'the last selected option wins' makes correctness depend on document "
            "order."
        )
        assert 'options[0]["selected"] = "selected"' in block

    def test_the_placeholder_the_restore_has_to_clear_really_is_rendered(self):
        html, _ = generate_select_layout({
            "annotation_type": "select", "name": "s", "description": "d",
            "labels": ["a", "b"],
        })

        first = re.search(r"<option\b[^>]*>", html).group(0)
        assert "selected" in first and 'value=""' in first
