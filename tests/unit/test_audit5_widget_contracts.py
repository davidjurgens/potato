"""Widgets that rendered, accepted clicks, and collected nothing.

The fifth usability audit of the task pack found four schemes that looked like
they worked. Each is pinned here from the server side; the client halves are in
`tests/jest/`.

The thread running through them is narrower than "the widget is broken": in each
case one half of a two-half contract was missing, and nothing on either side
said so. A hidden input without `annotation-input` is written to and never read.
A panel with no control is announced and never filled. A validator that never
compares the labels in one scheme against the labels in another lets a config
boot into a flow that cannot start.
"""

import json
import re

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError,
    _validate_event_annotation_labels,
)
from potato.server_utils.schemas.registry import schema_registry


def generate(scheme):
    html, _ = schema_registry.generate(scheme)
    return html


class TestTreeAnnotationCollectsSomething:
    """`tree_annotation` stored `{}` under every configuration.

    Two independent causes: the hidden inputs carried no `annotation-input`
    class, so `syncAnnotationsFromDOM` -- which collects `.annotation-input` --
    never saw the values conversation-tree.js wrote; and the node panel body was
    emitted empty with nothing anywhere that filled it, so the page advertised
    "Node annotation type: likert" over a blank box.
    """

    SCHEME = {
        "annotation_type": "tree_annotation",
        "name": "thread",
        "description": "Rate each reply and mark the best path.",
        "node_scheme": {
            "annotation_type": "likert", "name": "node_quality",
            "description": "How helpful is this reply?", "size": 5,
            "min_label": "Unhelpful", "max_label": "Helpful",
        },
        "path_selection": {"enabled": True, "description": "Pick the best path."},
    }

    @pytest.fixture(scope="class")
    def html(self):
        return generate(self.SCHEME)

    def test_both_hidden_inputs_are_collectable(self, html):
        for input_id in ("thread_node_annotations", "thread_selected_path_data"):
            tag = re.search(rf'<input[^>]*id="{input_id}"[^>]*>', html)
            assert tag, f"{input_id} not rendered"
            assert "annotation-input" in tag.group(0), (
                f"{input_id} is written by conversation-tree.js and read by "
                "nothing without this class"
            )

    def test_the_inputs_identify_their_schema_and_label(self, html):
        """syncAnnotationsFromDOM keys on these, so both must be distinct."""
        labels = re.findall(r'<input[^>]*class="annotation-input tree-ann[^"]*"[^>]*>', html)
        assert len(labels) == 2
        names = {re.search(r'label_name="([^"]*)"', tag).group(1) for tag in labels}
        assert names == {"node_annotations", "selected_path"}

    def test_neither_input_starts_with_a_value(self, html):
        """An untouched tree is unanswered, not answered with `{}` / `[]`."""
        for input_id in ("thread_node_annotations", "thread_selected_path_data"):
            tag = re.search(rf'<input[^>]*id="{input_id}"[^>]*>', html).group(0)
            assert 'value=""' in tag
            assert "data-modified" not in tag

    def test_the_container_is_a_form(self, html):
        """`.annotation-form` on a div is not a form; grouping keys on it."""
        assert html.strip().startswith('<form')
        assert 'class="tree-ann-container annotation-form"' in html

    def test_the_node_scheme_renders_a_real_control(self, html):
        """Through the same registry every top-level scheme goes through."""
        assert 'id="segment-questions-template-thread"' in html
        template = html[html.index("segment-questions-template-thread"):]
        template = template[:template.index("</template>")]
        assert template.count('type="radio"') == 5, "the likert's five points"
        assert "Unhelpful" in template and "Helpful" in template

    def test_a_tree_without_a_node_scheme_renders_no_template(self):
        scheme = dict(self.SCHEME)
        del scheme["node_scheme"]
        html = generate(scheme)

        assert "segment-questions-template" not in html
        # ...and still collects a path.
        assert 'id="thread_selected_path_data"' in html

    def test_the_node_scheme_description_is_never_empty(self):
        """The registry rejects an empty description; a node_scheme may omit one."""
        scheme = dict(self.SCHEME)
        scheme["node_scheme"] = {"annotation_type": "likert", "name": "q", "size": 3}
        html = generate(scheme)

        assert "segment-questions-template-thread" in html
        assert "Could not render" not in html


class TestToolContentionIsBetweenAgents:
    """One agent's own two overlapping calls were reported as contention.

    The header the annotator reads says "across agents" and the module docstring
    says "two calls touch the same shared resource"; neither describes
    `coder:read <-> coder:read`. With the scheme required, that card had to be
    classified before they could advance.
    """

    @pytest.fixture(scope="class")
    def script(self):
        return generate({
            "annotation_type": "tool_contention", "name": "tc",
            "description": "Flag concurrent tool use across agents.",
        })

    def test_same_agent_pairs_are_skipped(self, script):
        assert "calls[a].agent === calls[b].agent" in script

    def test_the_resource_check_still_runs_first(self, script):
        """Skipping self-pairs must not skip the resource comparison."""
        body = script[script.index("function computeContentions"):]
        body = body[:body.index("out.sort")]
        assert body.index("calls[a].resource !== calls[b].resource") < body.index(
            "calls[a].agent === calls[b].agent")

    def test_untimed_calls_say_so_rather_than_reporting_no_contention(self, script):
        """Overlap needs start/end in seconds.

        With calls carrying neither, every interval is 0-0, nothing overlaps,
        and "No shared-resource contention detected" is indistinguishable from a
        trace that genuinely has none.
        """
        assert "no start/end times" in script
        assert "cannot be computed" in script


class TestCompositeWidgetsDeclareWhatIsMissing:
    """`required` meant "touched once" on any widget behind one hidden input.

    `validateRequiredFields` tests a hidden input with
    `!input.value || input.value.trim() === ''`, so any non-empty JSON passed. An
    agent_scorecard declaring four agents by two dimensions plus two team
    dimensions asks ten questions and was satisfied by one.

    Only the widget knows how many cells it declared, so each one writes
    `data-incomplete-reason` on its form and the validator reads it.
    """

    @pytest.mark.parametrize("scheme,extra", [
        ("agent_scorecard", {"steps_key": "steps"}),
        ("handoff_review", {"steps_key": "steps"}),
        ("failure_attribution", {"steps_key": "steps"}),
        ("consensus_tracking", {"turns_key": "conv"}),
        ("context_attribution", {"turns_key": "conv"}),
    ])
    def test_the_widget_declares_and_clears_the_reason(self, scheme, extra):
        html = generate({"annotation_type": scheme, "name": "x",
                         "description": "d", **extra})

        assert "declareCompleteness" in html
        assert "data-incomplete-reason" in html
        assert "removeAttribute('data-incomplete-reason')" in html, (
            "a widget that only ever sets the attribute can never be satisfied")

    @pytest.mark.parametrize("scheme,extra", [
        ("agent_scorecard", {"steps_key": "steps"}),
        ("handoff_review", {"steps_key": "steps"}),
        ("consensus_tracking", {"turns_key": "conv"}),
    ])
    def test_it_is_declared_on_build_not_only_on_save(self, scheme, extra):
        """Otherwise an untouched widget reports nothing missing."""
        html = generate({"annotation_type": scheme, "name": "x",
                         "description": "d", **extra})
        assert html.count("declareCompleteness") >= 3  # definition + build + save

    def test_handoff_review_omits_an_unrated_quality(self):
        """0 is the widget's "unrated" but the scale starts at 1.

        Writing it out puts a rating in the export the annotator never gave.
        """
        html = generate({"annotation_type": "handoff_review", "name": "h",
                         "description": "d", "steps_key": "steps"})

        assert "if (h.quality) rec.quality = h.quality;" in html
        assert "flags: h.flags, quality: h.quality" not in html


class TestEventAnnotationLabelsAreChecked:
    """`trigger_labels` and `entity_types` must exist in the named span schema.

    With a mismatch the flow cannot start at all: the annotator marks a span,
    clicks a role, and nothing happens, with Create Event staying disabled and no
    message saying which role is missing. Validation was quiet, including under
    --strict.
    """

    SPAN = {"annotation_type": "span", "name": "entities", "description": "d",
            "labels": ["EVENT_TRIGGER", "INTERVENTION", "COMPARATOR"]}

    def _config(self, event_types, span_schema="entities", span=None):
        return {"annotation_schemes": [
            span or self.SPAN,
            {"annotation_type": "event_annotation", "name": "comparisons",
             "description": "d", "span_schema": span_schema,
             "event_types": event_types},
        ]}

    def test_a_matching_config_passes(self):
        _validate_event_annotation_labels(self._config([
            {"type": "COMPARISON", "trigger_labels": ["EVENT_TRIGGER"],
             "arguments": [{"role": "intervention", "entity_types": ["INTERVENTION"]}]}]))

    def test_an_unknown_trigger_label_is_rejected(self):
        with pytest.raises(ConfigValidationError, match="trigger_labels"):
            _validate_event_annotation_labels(self._config([
                {"type": "COMPARISON", "trigger_labels": ["TRIGGER"]}]))

    def test_an_unknown_entity_type_is_rejected(self):
        with pytest.raises(ConfigValidationError, match="entity_types"):
            _validate_event_annotation_labels(self._config([
                {"type": "COMPARISON",
                 "arguments": [{"role": "intervention", "entity_types": ["DRUG"]}]}]))

    def test_the_message_names_the_labels_that_do_exist(self):
        with pytest.raises(ConfigValidationError) as excinfo:
            _validate_event_annotation_labels(self._config([
                {"type": "COMPARISON", "trigger_labels": ["TRIGGER"]}]))

        assert "COMPARATOR, EVENT_TRIGGER, INTERVENTION" in str(excinfo.value)

    def test_a_span_schema_that_does_not_exist_is_rejected(self):
        with pytest.raises(ConfigValidationError, match="no annotation scheme"):
            _validate_event_annotation_labels(
                self._config([{"type": "C"}], span_schema="entites"))

    def test_a_span_scheme_with_no_static_labels_is_left_alone(self):
        """It may build them some other way; guessing would reject working configs."""
        _validate_event_annotation_labels(self._config(
            [{"type": "C", "trigger_labels": ["ANYTHING"]}],
            span=({"annotation_type": "span", "name": "entities", "description": "d"})))

    def test_dict_labels_are_read_by_name(self):
        span = {"annotation_type": "span", "name": "entities", "description": "d",
                "labels": [{"name": "EVENT_TRIGGER", "tooltip": "the verb"}]}
        _validate_event_annotation_labels(self._config(
            [{"type": "C", "trigger_labels": ["EVENT_TRIGGER"]}], span=span))

    def test_a_scheme_without_span_schema_is_not_policed(self):
        _validate_event_annotation_labels({"annotation_schemes": [
            {"annotation_type": "event_annotation", "name": "e", "description": "d",
             "event_types": [{"type": "C", "trigger_labels": ["X"]}]}]})
