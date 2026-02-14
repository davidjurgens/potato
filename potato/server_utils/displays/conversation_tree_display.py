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
    }
    description = "Conversation tree display with collapsible branching nodes"
    supports_span_target = False

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        if not data:
            return '<div class="conv-tree-empty">No conversation tree data</div>'

        collapsed_depth = field_config.get("collapsed_depth", 2)
        node_style = field_config.get("node_style", "card")
        show_ids = field_config.get("show_node_ids", False)
        max_depth = field_config.get("max_depth")

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

        tree_html = self._render_node(data, 0, collapsed_depth, node_style, show_ids, max_depth)

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
                     node_style: str, show_ids: bool, max_depth) -> str:
        if not node or not isinstance(node, dict):
            return ""

        if max_depth is not None and depth > max_depth:
            return '<div class="conv-tree-truncated">[depth limit reached]</div>'

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

        # Children
        if children:
            display = "none" if is_collapsed else "block"
            parts.append(f'<div class="conv-tree-children" style="display:{display}">')
            for child in children:
                parts.append(self._render_node(
                    child, depth + 1, collapsed_depth, node_style, show_ids, max_depth
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
