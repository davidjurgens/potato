"""
Conversation Tree Display

Renders branching conversation trees as nested collapsible nodes.
Each node represents a message/turn in a dialogue with possible
multiple branches (e.g., different model responses).

Input data format:
    {"id": "root", "speaker": "User", "text": "Question?",
     "children": [
         {"id": "r1", "speaker": "Bot A", "text": "Answer 1", "children": []},
         {"id": "r2", "speaker": "Bot B", "text": "Answer 2", "children": []}
     ]}
"""

import json
from html import escape
from typing import Dict, Any, List

from .base import BaseDisplay


class ConversationTreeDisplay(BaseDisplay):
    name = "conversation_tree"
    required_fields = ["key"]
    optional_fields = {
        "collapsed_depth": 2,
        "node_style": "card",
        "show_node_ids": False,
        "max_depth": None,
        "show_timestamps": False,
        "turn_meta_fields": None,
        "meta_key": "meta",
    }
    description = "Conversation tree display with collapsible branching nodes"
    supports_span_target = False

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        if not data:
            return '<div class="conv-tree-empty">No conversation tree data</div>'

        # Read through get_display_options() so a nested `display_options:` block
        # works, as it does for every other display and as the docs and config
        # schema imply. Top-level keys stay supported because configs written
        # before this used them and they were the only thing that worked.
        options = self.get_display_options(field_config)

        def get(key, default=None):
            return field_config.get(key, options.get(key, default))

        collapsed_depth = get("collapsed_depth", 2)
        node_style = get("node_style", "card")
        show_ids = get("show_node_ids", False)
        max_depth = get("max_depth")
        show_timestamps = get("show_timestamps", False)
        turn_meta_fields = get("turn_meta_fields", None) or []
        meta_key = get("meta_key", "meta")

        # Turn-level schemes bound to this field, injected by
        # InstanceDisplayRenderer._with_turn_schemes. Node ids double as turn ids,
        # so a tree and a flat dialogue over the same conversation annotate the
        # same turns.
        turn_schemes = field_config.get("_turn_schemes") or []
        field_key = escape(str(field_config.get("key", "")), quote=True)

        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                return f'<div class="conv-tree-error">Invalid tree data</div>'

        config_json = escape(json.dumps({
            "collapsedDepth": collapsed_depth,
            "nodeStyle": node_style,
            "showIds": show_ids,
            "maxDepth": max_depth,
        }))

        # A single mutable counter threaded through the recursion gives every node
        # a stable depth-first pre-order index. Turn bindings that filter on
        # turn_range, and the t{index} fallback for nodes without an id, both need
        # an index that matches the order the annotator reads them in.
        counter = [0]
        tree_html = self._render_node(
            data, 0, collapsed_depth, node_style, show_ids, max_depth,
            turn_schemes=turn_schemes,
            field_key=field_key,
            counter=counter,
            show_timestamps=show_timestamps,
            turn_meta_fields=turn_meta_fields,
            meta_key=meta_key,
        )

        return (
            f'<div class="conv-tree" data-tree-config="{config_json}">'
            f'  <div class="conv-tree-controls">'
            f'    <button type="button" class="conv-tree-btn conv-tree-expand-all" title="Expand all">Expand All</button>'
            f'    <button type="button" class="conv-tree-btn conv-tree-collapse-all" title="Collapse all">Collapse All</button>'
            f'  </div>'
            f'  <div class="conv-tree-root">{tree_html}</div>'
            f'</div>'
        )

    def _render_node(self, node: dict, depth: int, collapsed_depth: int,
                     node_style: str, show_ids: bool, max_depth,
                     turn_schemes=None, field_key: str = "", counter=None,
                     show_timestamps: bool = False, turn_meta_fields=None,
                     meta_key: str = "meta") -> str:
        if not node or not isinstance(node, dict):
            return ""

        if max_depth is not None and depth > max_depth:
            return '<div class="conv-tree-truncated">[depth limit reached]</div>'

        node_index = 0
        if counter is not None:
            node_index = counter[0]
            counter[0] += 1

        node_id = escape(str(node.get("id", f"node_{depth}")))
        speaker = escape(str(node.get("speaker", "")))
        text = escape(str(node.get("text", "")))
        children = node.get("children", [])
        is_collapsed = depth >= collapsed_depth and len(children) > 0

        # Speaker color class based on name hash
        speaker_class = f"conv-tree-speaker-{abs(hash(speaker)) % 6}"

        parts = []
        parts.append(
            f'<div class="conv-tree-node {node_style}" '
            f'data-node-id="{node_id}" data-depth="{depth}">'
        )

        # Node header
        parts.append(f'<div class="conv-tree-node-header {speaker_class}">')
        if children:
            arrow = "▶" if is_collapsed else "▼"
            parts.append(
                f'<span class="conv-tree-toggle" data-collapsed="{str(is_collapsed).lower()}">{arrow}</span>'
            )
        parts.append(f'<span class="conv-tree-speaker">{speaker}</span>')
        if show_ids:
            parts.append(f'<span class="conv-tree-node-id">({node_id})</span>')
        if children:
            parts.append(
                f'<span class="conv-tree-branch-count">{len(children)} '
                f'{"branch" if len(children) == 1 else "branches"}</span>'
            )
        parts.append('</div>')

        # Node text
        parts.append(f'<div class="conv-tree-node-text">{text}</div>')

        # Per-node annotation widgets. The node's own id is used as the turn id,
        # so a tree view and a flat dialogue view of the same conversation store
        # their annotations under the same keys.
        # A node marked ``synthetic`` is scaffolding — a wrapper invented to give
        # a multi-rooted thread a single root — not a real message. Annotating it
        # would store a value under an id that exists nowhere upstream, so it
        # gets no widgets.
        if turn_schemes and not node.get("synthetic"):
            from ..turn_annotations import render_turn_slot

            turn = {
                "turn_id": node.get("id"),
                "speaker": node.get("speaker", ""),
                "text": node.get("text", ""),
                "depth": depth,
            }
            for key in ("agent_id", "role", "step_type", "tool", "addressee", "run_id"):
                if node.get(key) not in (None, ""):
                    turn[key] = node[key]
            slot_html = render_turn_slot(turn_schemes, turn, node_index, field_key)
            if slot_html:
                parts.append(slot_html)

        # Children
        if children:
            display = "none" if is_collapsed else "block"
            parts.append(f'<div class="conv-tree-children" style="display:{display}">')
            for child in children:
                parts.append(self._render_node(
                    child, depth + 1, collapsed_depth, node_style, show_ids, max_depth,
                    turn_schemes=turn_schemes,
                    field_key=field_key,
                    counter=counter,
                    show_timestamps=show_timestamps,
                    turn_meta_fields=turn_meta_fields,
                    meta_key=meta_key,
                ))
            parts.append('</div>')

        parts.append('</div>')
        return "\n".join(parts)

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        classes = super().get_css_classes(field_config)
        classes.append("conv-tree-container")
        return classes

    def get_data_attributes(self, field_config: Dict[str, Any], data: Any) -> Dict[str, str]:
        attrs = super().get_data_attributes(field_config, data)
        attrs["display-type"] = "conversation_tree"
        return attrs
