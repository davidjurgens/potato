"""
Threaded rendering for the ``dialogue`` display, and per-node widgets on
``conversation_tree``.

Threading is general Potato functionality, not a ConvoKit feature: any list of
turns where each one names the turn it replies to renders as a thread. These
tests deliberately use plain forum/chat/trace-shaped data with no ConvoKit
involvement, because that generality is the thing worth protecting.

The span-offset invariant that this chrome must not violate is covered
separately and more thoroughly in ``test_dialogue_span_contract.py``.
"""

import re

import pytest

from potato.server_utils.displays.conversation_tree_display import ConversationTreeDisplay
from potato.server_utils.displays.dialogue_display import DialogueDisplay
from potato.server_utils.displays.registry import display_registry


def render(data, **display_options):
    return DialogueDisplay().render(
        {"key": "thread", "display_options": display_options}, data
    )


def depths(html_str):
    return [int(d) for d in re.findall(r'data-depth="(\d+)"', html_str)]


#: A plain forum thread: `id`/`reply_to`, no ConvoKit, no precomputed depth.
FORUM = [
    {"id": "m1", "speaker": "ana", "text": "Anyone tried the new API?"},
    {"id": "m2", "speaker": "ben", "text": "Yes, works fine.", "reply_to": "m1"},
    {"id": "m3", "speaker": "cy", "text": "Not for me.", "reply_to": "m2"},
    {"id": "m4", "speaker": "dee", "text": "Same here.", "reply_to": "m1"},
]


class TestDepthDerivation:
    """Nesting is computed from reply_to when the data does not supply it."""

    def test_derives_depth_from_reply_to(self):
        assert depths(render(FORUM, indent_replies=True)) == [0, 1, 2, 1]

    def test_no_indent_option_means_no_depth_attributes(self):
        assert depths(render(FORUM)) == []

    @pytest.mark.parametrize("identity_key", ["id", "turn_id", "step_id"])
    def test_all_identity_key_conventions_work(self, identity_key):
        """Forum data uses `id`, Potato turns use `turn_id`, traces use `step_id`."""
        data = [
            {identity_key: "a", "speaker": "x", "text": "root"},
            {identity_key: "b", "speaker": "y", "text": "child", "reply_to": "a"},
        ]
        assert depths(render(data, indent_replies=True)) == [0, 1]

    def test_explicit_depth_wins_over_derivation(self):
        """A producer that computed depth may know about parents not rendered here."""
        data = [
            {"id": "a", "text": "sliced out of a bigger thread", "depth": 3},
            {"id": "b", "text": "reply", "reply_to": "a", "depth": 4},
        ]
        assert depths(render(data, indent_replies=True)) == [3, 4]

    def test_parent_outside_the_rendered_turns_is_a_root(self):
        data = [{"id": "a", "text": "orphan", "reply_to": "not-here"}]
        assert depths(render(data, indent_replies=True)) == [0]

    def test_reply_cycle_terminates(self):
        data = [
            {"id": "a", "text": "x", "reply_to": "b"},
            {"id": "b", "text": "y", "reply_to": "a"},
        ]
        result = depths(render(data, indent_replies=True))
        assert len(result) == 2
        assert all(d < 10 for d in result)

    def test_turns_without_any_identity_are_flat(self):
        data = [{"speaker": "a", "text": "one"}, {"speaker": "b", "text": "two"}]
        assert depths(render(data, indent_replies=True)) == [0, 0]

    def test_indentation_depth_is_capped_for_display(self):
        deep = [{"id": "n0", "text": "root"}]
        for i in range(1, 12):
            deep.append({"id": f"n{i}", "text": f"reply {i}", "reply_to": f"n{i-1}"})
        html_out = render(deep, indent_replies=True, max_indent_depth=4)
        # The true depth is reported...
        assert depths(html_out) == list(range(12))
        # ...but the indent custom property is clamped.
        indents = [int(v) for v in re.findall(r"--turn-depth:(\d+)", html_out)]
        assert max(indents) == 4


class TestReplyAndFocusAttributes:
    def test_reply_to_is_exposed_for_parent_highlighting(self):
        html_out = render(FORUM, indent_replies=True)
        assert 'data-reply-to="m1"' in html_out
        assert 'data-reply-to="m2"' in html_out

    def test_focus_turn_is_marked(self):
        data = [
            {"id": "a", "text": "context"},
            {"id": "b", "text": "the one being judged", "is_focus": True},
        ]
        assert render(data).count('data-focus="true"') == 1


class TestTimestamps:
    def test_relative_to_the_first_turn(self):
        data = [
            {"id": "a", "text": "first", "timestamp": 1000},
            {"id": "b", "text": "later", "timestamp": 4600},
        ]
        html_out = render(data, show_timestamps=True)
        assert 'data-timestamp="start"' in html_out
        assert 'data-timestamp="+1h"' in html_out

    def test_absolute_format(self):
        data = [{"id": "a", "text": "x", "timestamp": 1185295934}]
        assert 'data-timestamp="2007-07-24' in render(
            data, show_timestamps=True, timestamp_format="absolute"
        )

    def test_epoch_format_is_passed_through(self):
        data = [{"id": "a", "text": "x", "timestamp": 1185295934}]
        assert 'data-timestamp="1185295934"' in render(
            data, show_timestamps=True, timestamp_format="epoch"
        )

    def test_out_of_order_timestamps_show_a_negative_offset(self):
        """Real corpora contain these; clamping to zero would hide the anomaly."""
        data = [
            {"id": "a", "text": "logged late", "timestamp": 5000},
            {"id": "b", "text": "logged early", "timestamp": 1400},
        ]
        html_out = render(data, show_timestamps=True)
        assert 'data-timestamp="+1h"' in html_out   # a, relative to b's earlier origin

    def test_missing_timestamps_are_simply_absent(self):
        assert "data-timestamp=" not in render(FORUM, show_timestamps=True)

    def test_unparseable_timestamp_does_not_raise(self):
        data = [{"id": "a", "text": "x", "timestamp": "not-a-time"}]
        render(data, show_timestamps=True)


class TestPerTurnMetadataChips:
    def test_selected_fields_are_surfaced(self):
        data = [{"id": "a", "text": "x", "meta": {"score": 0.5, "flag": True, "other": 9}}]
        html_out = render(data, turn_meta_fields=["score", "flag"])
        assert "score: 0.5" in html_out
        assert "flag: true" in html_out
        assert "other" not in html_out.split("data-meta-chips")[1][:60]

    def test_floats_are_shortened(self):
        data = [{"id": "a", "text": "x", "meta": {"toxicity": 0.078140646}}]
        assert "toxicity: 0.0781" in render(data, turn_meta_fields=["toxicity"])

    def test_nested_values_are_skipped(self):
        data = [{"id": "a", "text": "x", "meta": {"parsed": {"a": 1}, "ok": 1}}]
        html_out = render(data, turn_meta_fields=["parsed", "ok"])
        assert "ok: 1" in html_out
        assert "parsed" not in html_out

    def test_custom_meta_key(self):
        data = [{"id": "a", "text": "x", "attributes": {"score": 3}}]
        assert "score: 3" in render(
            data, turn_meta_fields=["score"], meta_key="attributes"
        )

    def test_absent_metadata_is_not_an_error(self):
        assert "data-meta-chips" not in render(FORUM, turn_meta_fields=["score"])


class TestContainerClasses:
    def test_classes_reflect_enabled_chrome(self):
        html_out = render(
            FORUM, indent_replies=True, show_timestamps=True, turn_meta_fields=["x"]
        )
        classes = re.search(r'class="(dialogue-display-content[^"]*)"', html_out).group(1)
        assert "indent-replies" in classes
        assert "show-reply-lines" in classes
        assert "show-timestamps" in classes
        assert "show-meta-chips" in classes

    def test_reply_lines_can_be_disabled(self):
        html_out = render(FORUM, indent_replies=True, show_reply_lines=False)
        classes = re.search(r'class="(dialogue-display-content[^"]*)"', html_out).group(1)
        assert "indent-replies" in classes
        assert "show-reply-lines" not in classes

    def test_defaults_add_no_threading_classes(self):
        classes = re.search(
            r'class="(dialogue-display-content[^"]*)"', render(FORUM)
        ).group(1)
        assert "indent-replies" not in classes
        assert "show-timestamps" not in classes


class TestRegistryStaysInStep:
    def test_registry_lists_every_option_the_class_accepts(self):
        """The class attribute drives behavior; the registry copy drives docs."""
        definition = display_registry.get("dialogue")
        assert set(definition.optional_fields) == set(DialogueDisplay.optional_fields)

    def test_conversation_tree_registry_matches_too(self):
        definition = display_registry.get("conversation_tree")
        assert set(definition.optional_fields) == set(
            ConversationTreeDisplay.optional_fields
        )


TREE = {
    "id": "c0", "speaker": "ana", "text": "root",
    "children": [
        {"id": "c1", "speaker": "ben", "text": "reply", "children": [
            {"id": "c3", "speaker": "ana", "text": "deep", "children": []},
        ]},
        {"id": "c2", "speaker": "cy", "text": "other", "children": []},
    ],
}

SCHEMES = [{
    "name": "node_label",
    "annotation_type": "radio",
    "labels": ["good", "bad"],
    "description": "Label",
    "turn_binding": {},
}]


class TestConversationTreeWidgets:
    def _render(self, **field_config):
        config = {"key": "tree"}
        config.update(field_config)
        return ConversationTreeDisplay().render(config, TREE)

    def test_per_node_widgets_render(self):
        html_out = self._render(_turn_schemes=SCHEMES)
        assert html_out.count("turn-anno-slot") == 4

    def test_node_ids_are_used_as_turn_ids(self):
        """So a tree and a flat dialogue of the same thread annotate the same turns."""
        html_out = self._render(_turn_schemes=SCHEMES)
        ids = re.findall(r'turn-anno-slot"[^>]*data-turn-id="([^"]+)"', html_out)
        assert ids == ["c0", "c1", "c3", "c2"]

    def test_turn_indices_follow_depth_first_preorder(self):
        html_out = self._render(_turn_schemes=SCHEMES)
        indices = re.findall(r'turn-anno-slot"[^>]*data-turn-index="(\d+)"', html_out)
        assert indices == ["0", "1", "2", "3"]

    def test_no_schemes_means_no_widgets(self):
        assert "turn-anno-slot" not in self._render()

    def test_synthetic_nodes_get_no_widgets(self):
        """A wrapper invented for a multi-rooted thread is not an utterance.

        Annotating it would store a value under an id that exists in no corpus
        and could never be exported back.
        """
        wrapped = {
            "id": "c0::roots", "speaker": "", "text": "(2 root messages)",
            "synthetic": True,
            "children": [
                {"id": "r1", "speaker": "a", "text": "one", "children": []},
                {"id": "r2", "speaker": "b", "text": "two", "children": []},
            ],
        }
        html_out = ConversationTreeDisplay().render(
            {"key": "tree", "_turn_schemes": SCHEMES}, wrapped
        )
        ids = re.findall(r'turn-anno-slot"[^>]*data-turn-id="([^"]+)"', html_out)
        assert ids == ["r1", "r2"]
        assert "c0::roots" not in ids

    def test_display_options_block_is_honored(self):
        """Regression: this display read only top-level keys, unlike every other."""
        assert "conv-tree-node-id" in self._render(
            display_options={"show_node_ids": True}
        )

    def test_top_level_keys_still_work(self):
        assert "conv-tree-node-id" in self._render(show_node_ids=True)

    def test_tree_is_not_a_span_target(self):
        """Collapsed subtrees make textContent depend on UI state."""
        assert display_registry.get("conversation_tree").supports_span_target is False
