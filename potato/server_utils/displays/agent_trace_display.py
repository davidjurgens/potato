"""
Agent Trace Display Type

Purpose-built rendering for agent traces as a vertical sequence of "step cards".
Each step shows a type badge (Thought / Action / Observation) with color coding,
collapsible tool call parameters, and optional inline screenshot thumbnails.

This display type provides a richer visual alternative to the dialogue display
for agent trace data, with step-type-aware styling and summary headers.
"""

import html
from typing import Dict, Any, List, Optional

from .base import BaseDisplay
from ._trace_normalize import (
    DEFAULT_STEP_COLORS,
    SPEAKER_TYPE_PATTERNS,
    normalize_steps,
    infer_type_from_speaker,
    infer_type_from_text,
)


class AgentTraceDisplay(BaseDisplay):
    """
    Display type for agent traces rendered as step cards.

    Supports data as:
        - List of dicts with speaker/text keys (same as dialogue)
        - List of dicts with step_type/content keys
        - List of dicts with thought/action/observation keys (one step per dict)
    """

    name = "agent_trace"
    required_fields = ["key"]
    optional_fields = {
        "show_timestamps": False,
        "collapse_observations": False,
        "step_type_colors": DEFAULT_STEP_COLORS,
        "show_screenshots": True,
        "show_step_numbers": True,
        "show_summary": True,
        "compact": False,
        "speaker_key": "speaker",
        "text_key": "text",
        "show_run_tree": True,
    }
    description = "Agent trace display with step cards and type badges"
    supports_span_target = False  # Per-step IDs don't follow .text-content wrapper contract

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        if not data:
            return '<div class="agent-trace-placeholder">No trace data provided</div>'

        options = self.get_display_options(field_config)
        show_timestamps = options.get("show_timestamps", False)
        collapse_obs = options.get("collapse_observations", False)
        colors = options.get("step_type_colors", DEFAULT_STEP_COLORS)
        show_screenshots = options.get("show_screenshots", True)
        show_step_numbers = options.get("show_step_numbers", True)
        show_summary = options.get("show_summary", True)
        compact = options.get("compact", False)
        speaker_key = options.get("speaker_key", "speaker")
        text_key = options.get("text_key", "text")

        field_key = html.escape(field_config.get("key", ""), quote=True)
        is_span_target = field_config.get("span_target", False)

        # Turn-level annotation schemes bound to this field (injected by
        # InstanceDisplayRenderer via the internal _turn_schemes key)
        turn_schemes = field_config.get("_turn_schemes") or []

        # Sub-agent run tree (injected via the internal _run_tree key from
        # the item's run_tree field, produced by trace converters)
        run_tree = field_config.get("_run_tree") or []
        show_run_tree = options.get("show_run_tree", True) and bool(run_tree)

        # Normalize data to steps
        steps = self._normalize_steps(data, speaker_key, text_key)

        if not steps:
            return '<div class="agent-trace-placeholder">No trace steps found</div>'

        # Build CSS for step type colors
        css = self._build_css(colors, compact, show_run_tree)

        # Build summary header
        summary_html = ""
        if show_summary:
            summary_html = self._build_summary(steps)

        # Build step cards
        step_html_list = []
        step_counter = 0
        for i, step in enumerate(steps):
            step_type = step.get("type", "observation")
            speaker = step.get("speaker", "")
            text = step.get("text", "")
            timestamp = step.get("timestamp", "")
            screenshot = step.get("screenshot", "")

            if step_type in ("action", "thought"):
                step_counter += 1

            # Step card - sanitize step_type for use in CSS class names and attributes
            safe_step_type = html.escape(step_type, quote=True)
            type_class = f"step-type-{safe_step_type}"
            card_classes = ["agent-trace-step", type_class]
            if compact:
                card_classes.append("compact")

            # Badge
            badge_label = safe_step_type.capitalize()
            if speaker:
                badge_label = html.escape(str(speaker))

            # Step number
            step_num_html = ""
            if show_step_numbers and step_type in ("action", "thought"):
                step_num_html = f'<span class="step-number">#{step_counter}</span>'

            # Timestamp
            ts_html = ""
            if show_timestamps and timestamp:
                ts_html = f'<span class="step-timestamp">{html.escape(str(timestamp))}</span>'

            # Text content
            escaped_text = html.escape(str(text))
            text_id = ""
            span_attrs = ""
            if is_span_target:
                text_id = f'id="step-text-{field_key}-{i}"'
                span_attrs = f'data-original-text="{escaped_text}" data-step-index="{i}"'

            # Collapsible wrapper for observations
            if collapse_obs and step_type == "observation":
                text_html = (
                    f'<details class="step-collapsible">'
                    f'<summary>Observation (click to expand)</summary>'
                    f'<div class="step-text" {text_id} {span_attrs}>{escaped_text}</div>'
                    f'</details>'
                )
            else:
                text_html = f'<div class="step-text" {text_id} {span_attrs}>{escaped_text}</div>'

            # Screenshot thumbnail
            screenshot_html = ""
            if show_screenshots and screenshot:
                escaped_src = html.escape(str(screenshot), quote=True)
                screenshot_html = (
                    f'<div class="step-screenshot">'
                    f'<img src="{escaped_src}" alt="Step {i} screenshot" '
                    f'class="step-screenshot-img" loading="lazy" />'
                    f'</div>'
                )

            # Turn-level annotation slot (proxy widgets; real state lives in
            # the scheme's hidden anchor input — see turn_annotations.py)
            slot_html = ""
            if turn_schemes:
                from ..turn_annotations import render_turn_slot
                slot_html = render_turn_slot(turn_schemes, step, i, field_key)

            run_id_attr = ""
            if step.get("run_id"):
                run_id_attr = f' data-run-id="{html.escape(str(step["run_id"]), quote=True)}"'

            card_html = f'''
            <div class="{' '.join(card_classes)}" data-step-index="{i}" data-step-type="{safe_step_type}"{run_id_attr}>
                <div class="step-header">
                    <span class="step-badge badge-{safe_step_type}">{badge_label}</span>
                    {step_num_html}
                    {ts_html}
                </div>
                <div class="step-body">
                    {text_html}
                    {screenshot_html}
                    {slot_html}
                </div>
            </div>
            '''
            step_html_list.append(card_html)

        all_steps_html = "\n".join(step_html_list)

        container_classes = ["agent-trace-display"]
        if is_span_target:
            container_classes.append("span-target-agent-trace")

        # Sub-agent run tree sidebar (collapsible; clicking a node filters
        # the step list to that run's turns — see run-tree.js)
        tree_html = ""
        if show_run_tree:
            container_classes.append("has-run-tree")
            tree_html = self._build_run_tree(run_tree)

        return f'''
        <style>{css}</style>
        <div class="{' '.join(container_classes)}" data-field-key="{field_key}">
            {summary_html}
            <div class="agent-trace-body">
                {tree_html}
                <div class="agent-trace-steps">
                    {all_steps_html}
                </div>
            </div>
        </div>
        '''

    def _build_run_tree(self, run_tree: List[Dict[str, Any]]) -> str:
        """Render the run hierarchy as a collapsible tree sidebar.

        Each node button carries its own id plus its descendants' ids
        (data-run-desc) so run-tree.js can filter steps to a whole subtree
        without walking the tree client-side.
        """
        nodes = [n for n in run_tree if isinstance(n, dict) and n.get("id")]
        if not nodes:
            return ""
        by_id = {str(n["id"]): n for n in nodes}
        children: Dict[str, List[Dict[str, Any]]] = {}
        roots: List[Dict[str, Any]] = []
        for n in nodes:
            parent = n.get("parent_id")
            if parent is not None and str(parent) in by_id:
                children.setdefault(str(parent), []).append(n)
            else:
                roots.append(n)

        def descendants(node_id: str) -> List[str]:
            out = []
            for child in children.get(node_id, []):
                cid = str(child["id"])
                out.append(cid)
                out.extend(descendants(cid))
            return out

        def render_node(n: Dict[str, Any]) -> str:
            nid = str(n["id"])
            esc_id = html.escape(nid, quote=True)
            desc = html.escape(",".join(descendants(nid)), quote=True)
            name = html.escape(str(n.get("name", "") or n.get("run_type", "run")))
            run_type = html.escape(str(n.get("run_type", "chain")), quote=True)
            status = str(n.get("status") or "")
            status_html = ""
            if status:
                status_class = "rt-status-error" if status == "error" else "rt-status-ok"
                status_html = f'<span class="rt-status {status_class}" title="{html.escape(status, quote=True)}"></span>'
            turn_range = n.get("turn_range")
            range_html = ""
            if isinstance(turn_range, (list, tuple)) and len(turn_range) == 2:
                lo, hi = turn_range
                label = f"step {lo}" if lo == hi else f"steps {lo}–{hi}"
                range_html = f'<span class="rt-range">{html.escape(label)}</span>'
            kids = children.get(nid, [])
            kids_html = ""
            if kids:
                kids_html = "<ul class='rt-children'>" + "".join(
                    f"<li>{render_node(k)}</li>" for k in kids) + "</ul>"
            return (
                f'<button type="button" class="rt-node" data-run-id="{esc_id}"'
                f' data-run-desc="{desc}" aria-pressed="false">'
                f'<span class="rt-type rt-type-{run_type}">{run_type}</span>'
                f'<span class="rt-name">{name}</span>{status_html}{range_html}'
                f'</button>{kids_html}'
            )

        items = "".join(f"<li>{render_node(r)}</li>" for r in roots)
        return (
            '<nav class="run-tree" aria-label="Sub-agent run tree">'
            '<div class="rt-title">Run tree</div>'
            f'<ul class="rt-root">{items}</ul>'
            '</nav>'
        )

    def _normalize_steps(self, data: Any, speaker_key: str, text_key: str) -> List[Dict[str, str]]:
        """Normalize various trace data formats to a list of step dicts.

        Delegates to the shared :func:`normalize_steps` so ``agent_trace`` and
        ``eval_trace`` parse identical data the same way.
        """
        return normalize_steps(data, speaker_key, text_key)

    def _infer_type_from_speaker(self, speaker: str) -> str:
        """Infer step type from speaker name."""
        return infer_type_from_speaker(speaker)

    def _infer_type_from_text(self, text: str) -> str:
        """Infer step type from text content."""
        return infer_type_from_text(text)

    def _build_summary(self, steps: List[Dict]) -> str:
        """Build a summary header showing step counts."""
        type_counts = {}
        for step in steps:
            t = step.get("type", "observation")
            type_counts[t] = type_counts.get(t, 0) + 1

        badges = []
        for step_type in ["thought", "action", "observation"]:
            count = type_counts.get(step_type, 0)
            if count > 0:
                badges.append(
                    f'<span class="summary-badge badge-{step_type}">'
                    f'{count} {step_type}{"s" if count != 1 else ""}</span>'
                )

        return f'''
        <div class="agent-trace-summary">
            <span class="summary-total">{len(steps)} steps</span>
            {" ".join(badges)}
        </div>
        '''

    def _build_css(self, colors: Dict[str, str], compact: bool,
                   show_run_tree: bool = False) -> str:
        """Build CSS for step type colors and layout.

        Run-tree rules are only emitted when a sub-agent tree is present, so a
        trace without a tree carries no run-tree markup at all.
        """
        thought_color = colors.get("thought", DEFAULT_STEP_COLORS["thought"])
        action_color = colors.get("action", DEFAULT_STEP_COLORS["action"])
        obs_color = colors.get("observation", DEFAULT_STEP_COLORS["observation"])
        system_color = colors.get("system", DEFAULT_STEP_COLORS["system"])
        error_color = colors.get("error", DEFAULT_STEP_COLORS["error"])

        padding = "8px 12px" if compact else "12px 16px"
        margin = "4px 0" if compact else "8px 0"

        base_css = f'''
        .agent-trace-display {{ font-family: inherit; }}
        .agent-trace-summary {{
            display: flex; align-items: center; gap: 8px;
            padding: 8px 12px; margin-bottom: 12px;
            background: #f8f9fa; border-radius: 6px; font-size: 0.9em;
        }}
        .summary-total {{ font-weight: 600; }}
        .summary-badge {{
            padding: 2px 8px; border-radius: 12px; font-size: 0.85em;
        }}
        .agent-trace-step {{
            padding: {padding}; margin: {margin};
            border-radius: 6px; border-left: 4px solid #ccc;
        }}
        .step-type-thought {{ background: {thought_color}; border-left-color: #2196F3; }}
        .step-type-action {{ background: {action_color}; border-left-color: #FF9800; }}
        .step-type-observation {{ background: {obs_color}; border-left-color: #4CAF50; }}
        .step-type-system {{ background: {system_color}; border-left-color: #9C27B0; }}
        .step-type-error {{ background: {error_color}; border-left-color: #f44336; }}
        .step-header {{
            display: flex; align-items: center; gap: 8px; margin-bottom: 4px;
        }}
        .step-badge {{
            padding: 2px 8px; border-radius: 4px; font-size: 0.8em;
            font-weight: 600; color: #333;
        }}
        .badge-thought {{ background: rgba(33,150,243,0.2); }}
        .badge-action {{ background: rgba(255,152,0,0.2); }}
        .badge-observation {{ background: rgba(76,175,80,0.2); }}
        .badge-system {{ background: rgba(156,39,176,0.2); }}
        .badge-error {{ background: rgba(244,67,54,0.2); }}
        .step-number {{ color: #666; font-size: 0.8em; }}
        .step-timestamp {{ color: #999; font-size: 0.75em; margin-left: auto; }}
        .step-text {{ white-space: pre-wrap; word-break: break-word; line-height: 1.5; }}
        .step-screenshot {{ margin-top: 8px; }}
        .step-screenshot-img {{
            max-width: 300px; max-height: 200px; border-radius: 4px;
            border: 1px solid #ddd; cursor: pointer;
        }}
        .step-screenshot-img:hover {{ box-shadow: 0 2px 8px rgba(0,0,0,0.15); }}
        .step-collapsible summary {{
            cursor: pointer; color: #666; font-size: 0.9em; padding: 4px 0;
        }}
        .agent-trace-body {{ display: block; }}
        '''

        if not show_run_tree:
            return base_css

        return base_css + '''
        .has-run-tree .agent-trace-body {
            display: flex; gap: 12px; align-items: flex-start;
        }
        .has-run-tree .agent-trace-steps { flex: 1; min-width: 0; }
        .run-tree {
            flex: 0 0 220px; max-width: 260px; position: sticky; top: 8px;
            border: 1px solid #e0e0e0; border-radius: 6px;
            padding: 8px; background: #fafafa; font-size: 0.85em;
            max-height: 70vh; overflow-y: auto;
        }
        .rt-title { font-weight: 600; margin-bottom: 6px; color: #555; }
        .run-tree ul { list-style: none; margin: 0; padding: 0; }
        .run-tree .rt-children { padding-left: 14px; border-left: 1px dotted #ccc; margin-left: 6px; }
        .rt-node {
            display: flex; align-items: center; gap: 6px; width: 100%;
            text-align: left; background: none; border: none; cursor: pointer;
            padding: 3px 6px; margin: 1px 0; border-radius: 4px; font: inherit;
        }
        .rt-node:hover { background: #eef2f7; }
        .rt-node.rt-active { background: #e3f2fd; outline: 1px solid #90caf9; }
        .rt-type {
            font-size: 0.72em; font-weight: 600; padding: 1px 5px;
            border-radius: 8px; text-transform: uppercase; flex-shrink: 0;
        }
        .rt-type-chain { background: rgba(96,125,139,0.18); color: #455a64; }
        .rt-type-llm { background: rgba(33,150,243,0.18); color: #1565c0; }
        .rt-type-tool { background: rgba(255,152,0,0.22); color: #b26a00; }
        .rt-type-retriever { background: rgba(76,175,80,0.18); color: #2e7d32; }
        .rt-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .rt-status { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
        .rt-status-ok { background: #4CAF50; }
        .rt-status-error { background: #f44336; }
        .rt-range { margin-left: auto; color: #999; font-size: 0.78em; flex-shrink: 0; }
        .agent-trace-step.rt-dim { opacity: 0.25; }
        .agent-trace-step.rt-focus { outline: 2px solid #90caf9; }
        '''

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        classes = super().get_css_classes(field_config)
        if field_config.get("span_target"):
            classes.append("span-target-field")
        return classes

    def get_data_attributes(self, field_config: Dict[str, Any], data: Any) -> Dict[str, str]:
        attrs = super().get_data_attributes(field_config, data)
        if field_config.get("span_target"):
            attrs["span-target"] = "true"
        return attrs
