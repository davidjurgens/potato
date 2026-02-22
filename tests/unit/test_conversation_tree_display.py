"""
Tests for conversation tree display.
"""

import pytest
import json


class TestConversationTreeDisplayRegistration:
    def test_registered_in_display_registry(self):
        from potato.server_utils.displays.registry import display_registry
        assert display_registry.is_registered("conversation_tree")

    def test_display_metadata(self):
        from potato.server_utils.displays.registry import display_registry
        display_def = display_registry.get("conversation_tree")
        assert display_def is not None
        assert display_def.name == "conversation_tree"
        assert display_def.supports_span_target is False


class TestConversationTreeDisplayRendering:
    def _get_renderer(self):
        from potato.server_utils.displays.conversation_tree_display import ConversationTreeDisplay
        return ConversationTreeDisplay()

    def test_render_simple_tree(self):
        renderer = self._get_renderer()
        tree = {
            "id": "root",
            "speaker": "User",
            "text": "Hello?",
            "children": [
                {"id": "r1", "speaker": "Bot A", "text": "Hi!", "children": []},
                {"id": "r2", "speaker": "Bot B", "text": "Hey!", "children": []},
            ]
        }
        html = renderer.render({"key": "tree"}, tree)
        assert "conv-tree" in html
        assert "User" in html
        assert "Hello?" in html
        assert "Bot A" in html
        assert "Hi!" in html
        assert "Bot B" in html
        assert "Hey!" in html

    def test_render_empty_data(self):
        renderer = self._get_renderer()
        html = renderer.render({"key": "tree"}, None)
        assert "conv-tree-empty" in html

    def test_render_string_data(self):
        renderer = self._get_renderer()
        tree = json.dumps({
            "id": "root", "speaker": "User", "text": "Q",
            "children": []
        })
        html = renderer.render({"key": "tree"}, tree)
        assert "User" in html
        assert "Q" in html

    def test_render_invalid_json_string(self):
        renderer = self._get_renderer()
        html = renderer.render({"key": "tree"}, "not json")
        assert "conv-tree-error" in html

    def test_render_collapsed_depth(self):
        renderer = self._get_renderer()
        tree = {
            "id": "root", "speaker": "User", "text": "Q",
            "children": [{
                "id": "c1", "speaker": "Bot", "text": "A",
                "children": [{
                    "id": "c2", "speaker": "User", "text": "Follow-up",
                    "children": [{"id": "c3", "speaker": "Bot", "text": "Deep", "children": []}]
                }]
            }]
        }
        # collapsed_depth=1: depth >= 1 should be collapsed
        html = renderer.render({"key": "tree", "collapsed_depth": 1}, tree)
        assert 'data-collapsed="true"' in html

    def test_render_show_node_ids(self):
        renderer = self._get_renderer()
        tree = {"id": "node_42", "speaker": "User", "text": "Q", "children": []}
        html = renderer.render({"key": "tree", "show_node_ids": True}, tree)
        assert "node_42" in html
        assert "conv-tree-node-id" in html

    def test_render_expand_collapse_buttons(self):
        renderer = self._get_renderer()
        tree = {"id": "root", "speaker": "User", "text": "Q",
                "children": [{"id": "c1", "speaker": "Bot", "text": "A", "children": []}]}
        html = renderer.render({"key": "tree"}, tree)
        assert "conv-tree-expand-all" in html
        assert "conv-tree-collapse-all" in html

    def test_branch_count(self):
        renderer = self._get_renderer()
        tree = {
            "id": "root", "speaker": "User", "text": "Q",
            "children": [
                {"id": "c1", "speaker": "Bot", "text": "A", "children": []},
                {"id": "c2", "speaker": "Bot", "text": "B", "children": []},
                {"id": "c3", "speaker": "Bot", "text": "C", "children": []},
            ]
        }
        html = renderer.render({"key": "tree"}, tree)
        assert "3 branches" in html

    def test_render_via_registry(self):
        from potato.server_utils.displays.registry import display_registry
        tree = {"id": "root", "speaker": "User", "text": "Q", "children": []}
        html = display_registry.render("conversation_tree", {"key": "tree"}, tree)
        assert "conv-tree" in html
