"""
Agent Trace Display Type

Purpose-built rendering for agent traces as a vertical sequence of "step cards".
Each step shows a type badge (Thought / Action / Observation) with color coding,
collapsible tool call parameters, and optional inline screenshot thumbnails.

This display type provides a richer visual alternative to the dialogue display
for agent trace data, with step-type-aware styling and summary headers.
"""

import html
import re
from typing import Dict, Any, List, Optional

from .base import BaseDisplay


# Default colors for step types
DEFAULT_STEP_COLORS = {
    "thought": "#e8f4fd",
    "action": "#fff3e0",
    "observation": "#e8f5e9",
    "system": "#f3e5f5",
    "error": "#ffebee",
}

# Speaker patterns that map to step types
SPEAKER_TYPE_PATTERNS = {
    "thought": re.compile(r"(thought|reasoning|planning|think)", re.IGNORECASE),
    "action": re.compile(r"(action|tool|function|call|execute)", re.IGNORECASE),
    "observation": re.compile(r"(observation|environment|result|output|response)", re.IGNORECASE),
    "system": re.compile(r"(system|info|metadata)", re.IGNORECASE),
    "error": re.compile(r"(error|fail|exception)", re.IGNORECASE),
}


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

        # Normalize data to steps
        steps = self._normalize_steps(data, speaker_key, text_key)

        if not steps:
            return '<div class="agent-trace-placeholder">No trace steps found</div>'

        # Build CSS for step type colors
        css = self._build_css(colors, compact)

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

            card_html = f'''
            <div class="{' '.join(card_classes)}" data-step-index="{i}" data-step-type="{safe_step_type}">
                <div class="step-header">
                    <span class="step-badge badge-{safe_step_type}">{badge_label}</span>
                    {step_num_html}
                    {ts_html}
                </div>
                <div class="step-body">
                    {text_html}
                    {screenshot_html}
                </div>
            </div>
            '''
            step_html_list.append(card_html)

        all_steps_html = "\n".join(step_html_list)

        container_classes = ["agent-trace-display"]
        if is_span_target:
            container_classes.append("span-target-agent-trace")

        return f'''
        <style>{css}</style>
        <div class="{' '.join(container_classes)}" data-field-key="{field_key}">
            {summary_html}
            <div class="agent-trace-steps">
                {all_steps_html}
            </div>
        </div>
        '''

    def _normalize_steps(self, data: Any, speaker_key: str, text_key: str) -> List[Dict[str, str]]:
        """Normalize various trace data formats to a list of step dicts."""
        steps = []

        if isinstance(data, str):
            # Single string - treat as one observation
            return [{"type": "observation", "speaker": "", "text": data}]

        if not isinstance(data, list):
            return steps

        for item in data:
            if isinstance(item, str):
                step_type = self._infer_type_from_text(item)
                steps.append({"type": step_type, "speaker": "", "text": item})
            elif isinstance(item, dict):
                # Format 1: speaker/text (same as dialogue)
                if speaker_key in item and text_key in item:
                    speaker = item[speaker_key]
                    text = item[text_key]
                    step_type = item.get("step_type", self._infer_type_from_speaker(speaker))
                    steps.append({
                        "type": step_type,
                        "speaker": speaker,
                        "text": text,
                        "timestamp": item.get("timestamp", ""),
                        "screenshot": item.get("screenshot", ""),
                    })
                # Format 2: thought/action/observation (one step = multiple turns)
                elif any(k in item for k in ("thought", "action", "observation")):
                    if "thought" in item and item["thought"]:
                        steps.append({
                            "type": "thought",
                            "speaker": "Agent (Thought)",
                            "text": str(item["thought"]),
                            "timestamp": item.get("timestamp", ""),
                        })
                    if "action" in item and item["action"]:
                        action = item["action"]
                        if isinstance(action, dict):
                            tool = action.get("tool", action.get("name", ""))
                            params = action.get("params", action.get("parameters", {}))
                            if params:
                                args = ", ".join(f"{k}={repr(v)}" for k, v in params.items())
                                action_text = f"{tool}({args})"
                            else:
                                action_text = f"{tool}()"
                        else:
                            action_text = str(action)
                        steps.append({
                            "type": "action",
                            "speaker": "Agent (Action)",
                            "text": action_text,
                        })
                    if "observation" in item and item["observation"]:
                        steps.append({
                            "type": "observation",
                            "speaker": "Environment",
                            "text": str(item["observation"]),
                            "screenshot": item.get("screenshot", ""),
                        })
                # Format 3: step_type/content
                elif "step_type" in item:
                    steps.append({
                        "type": item["step_type"],
                        "speaker": item.get("speaker", item.get("step_type", "").capitalize()),
                        "text": item.get("content", item.get("text", "")),
                        "timestamp": item.get("timestamp", ""),
                        "screenshot": item.get("screenshot", ""),
                    })

        return steps

    def _infer_type_from_speaker(self, speaker: str) -> str:
        """Infer step type from speaker name."""
        if not speaker:
            return "observation"
        for type_name, pattern in SPEAKER_TYPE_PATTERNS.items():
            if pattern.search(speaker):
                return type_name
        return "observation"

    def _infer_type_from_text(self, text: str) -> str:
        """Infer step type from text content."""
        lower = text.lower()
        if lower.startswith(("i need to", "i should", "let me think", "my plan")):
            return "thought"
        if "(" in text and ")" in text and any(c.isalpha() for c in text.split("(")[0]):
            return "action"
        return "observation"

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

    def _build_css(self, colors: Dict[str, str], compact: bool) -> str:
        """Build CSS for step type colors and layout."""
        thought_color = colors.get("thought", DEFAULT_STEP_COLORS["thought"])
        action_color = colors.get("action", DEFAULT_STEP_COLORS["action"])
        obs_color = colors.get("observation", DEFAULT_STEP_COLORS["observation"])
        system_color = colors.get("system", DEFAULT_STEP_COLORS["system"])
        error_color = colors.get("error", DEFAULT_STEP_COLORS["error"])

        padding = "8px 12px" if compact else "12px 16px"
        margin = "4px 0" if compact else "8px 0"

        return f'''
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
