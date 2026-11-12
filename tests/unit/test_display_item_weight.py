"""The item under annotation is not boxed in, and its controls are reachable.

UI audit, 2026-10-08, agent-trace example:

* Every display field was wrapped in a 500px scroll pane by default, so an
  agent trace was cut off mid-sentence in a box shorter than the questions
  under it. ``max_height`` now applies only when the config sets it; the
  stylesheet's 80vh cap and a "Show all" control cover the rest.
* Spreadsheet tables drew row checkboxes on read-only metadata ("Trace Info").
  Nothing stores that selection -- it is only emitted as a DOM event -- so an
  annotator could tick rows and lose them on the next item.
* Per-turn ratings were bare ``<span>`` elements: not focusable, no role, so
  the ratings had no keyboard path at all.
"""

import re

from potato.server_utils.displays.dialogue_display import DialogueDisplay
from potato.server_utils.displays.registry import display_registry
from potato.server_utils.instance_display import InstanceDisplayRenderer


def _wrapper_style(display_options):
    renderer = InstanceDisplayRenderer({"task_dir": "."})
    html = renderer._wrap_resizable(
        "<p>body</p>", {"key": "t", "type": "dialogue", "display_options": display_options})
    return re.search(r'class="display-field-resizable" style="([^"]*)"', html).group(1)


class TestFieldHeightCap:

    def test_no_max_height_unless_configured(self):
        style = _wrapper_style({})
        assert "max-height" not in style, style
        assert "min-height: 100px" in style, style

    def test_a_configured_max_height_still_applies(self):
        assert "max-height: 300px" in _wrapper_style({"max_height": 300})


class TestSpreadsheetSelectionIsOptIn:

    DATA = [{"Property": "Steps", "Value": 7}, {"Property": "Tokens", "Value": 2340}]

    def _render(self, display_options):
        return display_registry.render(
            "spreadsheet",
            {"key": "meta", "type": "spreadsheet", "display_options": display_options},
            self.DATA)

    def test_read_only_table_has_no_row_checkboxes(self):
        html = self._render({})
        assert "row-select" not in html
        assert "rows selected" not in html

    def test_selection_can_still_be_turned_on(self):
        html = self._render({"selectable": True})
        assert html.count('class="row-select"') == len(self.DATA)


class TestPerTurnRatingsAreARadioGroup:

    def _html(self):
        field = {
            "key": "conversation",
            "display_options": {
                "per_turn_ratings": {
                    "speakers": ["Agent (Action)"],
                    "schema_name": "action_correctness",
                    "scheme": {"type": "likert", "size": 3, "labels": ["Wrong", "Right"]},
                }
            },
        }
        data = [
            {"speaker": "Agent (Thought)", "text": "I need to search."},
            {"speaker": "Agent (Action)", "text": "search(query='x')"},
        ]
        return DialogueDisplay().render(field, data)

    def test_group_has_role_and_name(self):
        html = self._html()
        group = re.search(r'<div class="ptr-values"([^>]*)>', html).group(1)
        assert 'role="radiogroup"' in group
        assert 'aria-label="Action Correctness, turn 2"' in group

    def test_each_value_is_a_focusable_radio(self):
        values = re.findall(r'<span class="ptr-value"([^>]*)>', self._html())
        assert len(values) == 3
        assert all('role="radio"' in v and 'aria-checked="false"' in v for v in values)
        # One tab stop per group: the first value, the rest reachable by arrows.
        tabindexes = [re.search(r'tabindex="(-?\d)"', v).group(1) for v in values]
        assert tabindexes == ["0", "-1", "-1"]

    def test_end_values_carry_the_scale_labels(self):
        names = re.findall(r'class="ptr-value"[^>]*aria-label="([^"]*)"', self._html())
        assert names == ["1 of 3, Wrong", "2 of 3", "3 of 3, Right"]
