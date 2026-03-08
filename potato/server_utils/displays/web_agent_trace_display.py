"""
Web Agent Trace Display Type

Interactive step-by-step viewer for web agent browsing traces.
Renders screenshots with SVG overlay visualizations (click markers,
bounding boxes, mouse paths) alongside step details and a filmstrip navigator.

Data format:
{
    "steps": [
        {
            "step_index": 0,
            "screenshot_url": "screenshots/step_000.png",
            "action_type": "click",
            "element": {"tag": "input", "text": "Search", "bbox": [340, 45, 680, 75]},
            "coordinates": {"x": 510, "y": 60},
            "mouse_path": [[200, 300], [350, 200], [510, 60]],
            "thought": "I need to search for blue wool sweaters",
            "observation": "Search box is focused",
            "timestamp": 1.2,
            "viewport": {"width": 1280, "height": 720}
        }
    ],
    "task_description": "Find and add a blue wool sweater under $50 to cart",
    "site": "amazon.com"
}

Supported action_type values: click, type, scroll, hover, select, navigate, wait, done
"""

import html
import json
from typing import Dict, Any, List, Optional

from .base import BaseDisplay


# Action type badge colors
ACTION_TYPE_COLORS = {
    "click": {"bg": "#fff3e0", "border": "#FF9800", "badge": "rgba(255,152,0,0.2)"},
    "type": {"bg": "#e8f4fd", "border": "#2196F3", "badge": "rgba(33,150,243,0.2)"},
    "scroll": {"bg": "#e8f5e9", "border": "#4CAF50", "badge": "rgba(76,175,80,0.2)"},
    "hover": {"bg": "#f3e5f5", "border": "#9C27B0", "badge": "rgba(156,39,176,0.2)"},
    "select": {"bg": "#e0f7fa", "border": "#00BCD4", "badge": "rgba(0,188,212,0.2)"},
    "navigate": {"bg": "#e8eaf6", "border": "#3F51B5", "badge": "rgba(63,81,181,0.2)"},
    "wait": {"bg": "#f5f5f5", "border": "#9E9E9E", "badge": "rgba(158,158,158,0.2)"},
    "done": {"bg": "#e8f5e9", "border": "#388E3C", "badge": "rgba(56,142,60,0.2)"},
}

DEFAULT_ACTION_COLOR = {"bg": "#f5f5f5", "border": "#9E9E9E", "badge": "rgba(158,158,158,0.2)"}


class WebAgentTraceDisplay(BaseDisplay):
    """
    Display type for web agent browsing traces with interactive step navigation,
    SVG overlay visualizations, and filmstrip thumbnails.
    """

    name = "web_agent_trace"
    required_fields = ["key"]
    optional_fields = {
        "show_overlays": True,
        "show_filmstrip": True,
        "show_thought": True,
        "show_observation": True,
        "show_element_info": True,
        "screenshot_max_width": 800,
        "screenshot_max_height": 600,
        "filmstrip_size": 80,
    }
    description = "Web agent trace viewer with screenshots, SVG overlays, and step navigation"
    supports_span_target = False

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        if not data:
            return '<div class="web-agent-placeholder">No trace data provided</div>'

        options = self.get_display_options(field_config)
        field_key = html.escape(field_config.get("key", ""), quote=True)

        # Normalize data
        steps = self._normalize_steps(data)
        if not steps:
            return '<div class="web-agent-placeholder">No trace steps found</div>'

        # Extract task info
        task_desc = ""
        site = ""
        if isinstance(data, dict):
            task_desc = data.get("task_description", "")
            site = data.get("site", "")

        max_w = options.get("screenshot_max_width", 800)
        max_h = options.get("screenshot_max_height", 600)
        filmstrip_size = options.get("filmstrip_size", 80)

        # Serialize steps for JS
        steps_json = html.escape(json.dumps(steps, ensure_ascii=False), quote=True)

        css = self._build_css(max_w, max_h, filmstrip_size)

        # Task header
        task_html = ""
        if task_desc:
            escaped_task = html.escape(str(task_desc))
            task_html = f'<div class="web-agent-task"><strong>Task:</strong> {escaped_task}</div>'
        if site:
            escaped_site = html.escape(str(site))
            task_html += f'<div class="web-agent-site"><strong>Site:</strong> {escaped_site}</div>'

        # Build first step display (JS will handle subsequent navigation)
        first_step = steps[0]
        screenshot_html = self._render_screenshot(first_step, max_w, max_h)
        details_html = self._render_step_details(first_step, 0, len(steps), options)
        filmstrip_html = self._render_filmstrip(steps, filmstrip_size) if options.get("show_filmstrip", True) else ""

        # Per-step annotation container
        per_step_html = '<div class="web-agent-per-step-annotations" data-step-index="0"></div>'

        return f'''
        <style>{css}</style>
        <div class="web-agent-viewer" data-field-key="{field_key}" data-steps="{steps_json}">
            {task_html}
            <div class="web-agent-main">
                <div class="screenshot-panel">
                    <div class="screenshot-container">
                        <img class="step-screenshot" src="{html.escape(first_step.get('screenshot_url', ''), quote=True)}"
                             alt="Step 0 screenshot" />
                        <svg class="overlay-layer" xmlns="http://www.w3.org/2000/svg"></svg>
                    </div>
                    <div class="step-nav">
                        <button class="step-prev" disabled>&laquo; Prev</button>
                        <span class="step-counter">Step 1 of {len(steps)}</span>
                        <button class="step-next" {"disabled" if len(steps) <= 1 else ""}>&raquo; Next</button>
                    </div>
                </div>
                <div class="step-details-panel">
                    {details_html}
                    {per_step_html}
                </div>
            </div>
            {filmstrip_html}
            <div class="overlay-controls">
                <label><input type="checkbox" class="overlay-toggle" data-overlay="click" checked> Clicks</label>
                <label><input type="checkbox" class="overlay-toggle" data-overlay="bbox" checked> Bounding Boxes</label>
                <label><input type="checkbox" class="overlay-toggle" data-overlay="path" checked> Mouse Path</label>
                <label><input type="checkbox" class="overlay-toggle" data-overlay="scroll" checked> Scroll</label>
            </div>
        </div>
        '''

    def _normalize_steps(self, data: Any) -> List[Dict[str, Any]]:
        """Normalize input data to a list of step dicts."""
        if isinstance(data, dict):
            steps = data.get("steps", [])
        elif isinstance(data, list):
            steps = data
        else:
            return []

        normalized = []
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            normalized.append({
                "step_index": step.get("step_index", i),
                "screenshot_url": step.get("screenshot_url", step.get("screenshot", "")),
                "action_type": step.get("action_type", "unknown"),
                "element": step.get("element", {}),
                "coordinates": step.get("coordinates", {}),
                "mouse_path": step.get("mouse_path", []),
                "thought": step.get("thought", ""),
                "observation": step.get("observation", ""),
                "timestamp": step.get("timestamp", ""),
                "viewport": step.get("viewport", {"width": 1280, "height": 720}),
                "typed_text": step.get("typed_text", step.get("value", "")),
                "scroll_direction": step.get("scroll_direction", step.get("direction", "")),
            })
        return normalized

    def _render_screenshot(self, step: Dict, max_w: int, max_h: int) -> str:
        """Render the screenshot image element."""
        url = step.get("screenshot_url", "")
        if not url:
            return '<div class="screenshot-placeholder">No screenshot available</div>'
        escaped_url = html.escape(str(url), quote=True)
        return f'<img class="step-screenshot" src="{escaped_url}" alt="Step screenshot" />'

    def _render_step_details(self, step: Dict, index: int, total: int,
                             options: Dict) -> str:
        """Render the step details panel content."""
        action_type = step.get("action_type", "unknown")
        safe_type = html.escape(str(action_type), quote=True)
        colors = ACTION_TYPE_COLORS.get(action_type, DEFAULT_ACTION_COLOR)

        parts = []

        # Action badge
        parts.append(
            f'<div class="action-badge" style="background:{colors["badge"]}">'
            f'{safe_type.upper()}</div>'
        )

        # Timestamp
        ts = step.get("timestamp", "")
        if ts:
            parts.append(f'<div class="step-timestamp">t={html.escape(str(ts))}s</div>')

        # Thought
        thought = step.get("thought", "")
        if thought and options.get("show_thought", True):
            parts.append(
                f'<div class="step-thought">'
                f'<strong>Thought:</strong> {html.escape(str(thought))}'
                f'</div>'
            )

        # Element info
        element = step.get("element", {})
        if element and options.get("show_element_info", True):
            elem_parts = []
            if isinstance(element, dict):
                for k in ("tag", "text", "id", "class"):
                    if k in element:
                        elem_parts.append(f'{k}="{html.escape(str(element[k]))}"')
            if elem_parts:
                parts.append(
                    f'<div class="step-element">'
                    f'<strong>Element:</strong> <code>{" ".join(elem_parts)}</code>'
                    f'</div>'
                )

        # Coordinates
        coords = step.get("coordinates", {})
        if coords and isinstance(coords, dict):
            x = coords.get("x", "")
            y = coords.get("y", "")
            if x or y:
                parts.append(
                    f'<div class="step-coords">'
                    f'<strong>Coords:</strong> ({html.escape(str(x))}, {html.escape(str(y))})'
                    f'</div>'
                )

        # Typed text (for type actions)
        typed = step.get("typed_text", "")
        if typed:
            parts.append(
                f'<div class="step-typed">'
                f'<strong>Typed:</strong> "{html.escape(str(typed))}"'
                f'</div>'
            )

        # Observation
        obs = step.get("observation", "")
        if obs and options.get("show_observation", True):
            parts.append(
                f'<div class="step-observation">'
                f'<strong>Observation:</strong> {html.escape(str(obs))}'
                f'</div>'
            )

        return f'<div class="step-details-content">{"".join(parts)}</div>'

    def _render_filmstrip(self, steps: List[Dict], thumb_size: int) -> str:
        """Render the filmstrip thumbnail navigation bar."""
        thumbs = []
        for i, step in enumerate(steps):
            url = step.get("screenshot_url", "")
            active = "filmstrip-active" if i == 0 else ""
            if url:
                escaped_url = html.escape(str(url), quote=True)
                thumbs.append(
                    f'<div class="filmstrip-thumb {active}" data-step="{i}">'
                    f'<img src="{escaped_url}" alt="Step {i}" />'
                    f'<span class="filmstrip-label">{i + 1}</span>'
                    f'</div>'
                )
            else:
                thumbs.append(
                    f'<div class="filmstrip-thumb {active}" data-step="{i}">'
                    f'<div class="filmstrip-placeholder">?</div>'
                    f'<span class="filmstrip-label">{i + 1}</span>'
                    f'</div>'
                )
        return f'<div class="filmstrip">{"".join(thumbs)}</div>'

    def _build_css(self, max_w: int, max_h: int, filmstrip_size: int) -> str:
        """Build CSS for the web agent viewer."""
        return f'''
        .web-agent-viewer {{ font-family: inherit; }}
        .web-agent-task, .web-agent-site {{
            padding: 6px 12px; margin-bottom: 8px;
            background: #f8f9fa; border-radius: 4px; font-size: 0.95em;
        }}
        .web-agent-main {{
            display: flex; gap: 16px; margin-bottom: 12px;
        }}
        .screenshot-panel {{
            flex: 0 0 auto; max-width: {max_w}px;
        }}
        .screenshot-container {{
            position: relative; display: inline-block;
            border: 1px solid #ddd; border-radius: 6px; overflow: hidden;
            background: #1a1a1a;
        }}
        .step-screenshot {{
            display: block; max-width: {max_w}px; max-height: {max_h}px;
            width: auto; height: auto;
        }}
        .overlay-layer {{
            position: absolute; top: 0; left: 0;
            width: 100%; height: 100%;
            pointer-events: none;
        }}
        .screenshot-placeholder {{
            width: {max_w}px; height: 300px;
            display: flex; align-items: center; justify-content: center;
            background: #f0f0f0; color: #999; font-size: 0.9em;
        }}
        .step-nav {{
            display: flex; align-items: center; justify-content: center;
            gap: 12px; padding: 8px 0;
        }}
        .step-nav button {{
            padding: 4px 12px; border: 1px solid #ccc; border-radius: 4px;
            background: #fff; cursor: pointer; font-size: 0.85em;
        }}
        .step-nav button:disabled {{
            opacity: 0.4; cursor: default;
        }}
        .step-nav button:not(:disabled):hover {{
            background: #e8f4fd; border-color: #2196F3;
        }}
        .step-counter {{
            font-size: 0.9em; font-weight: 600; color: #555;
        }}
        .step-details-panel {{
            flex: 1; min-width: 250px; max-width: 400px;
            border: 1px solid #e0e0e0; border-radius: 6px;
            padding: 12px; background: #fafafa; overflow-y: auto;
            max-height: {max_h + 50}px;
        }}
        .step-details-content {{
            display: flex; flex-direction: column; gap: 8px;
        }}
        .action-badge {{
            display: inline-block; padding: 4px 12px;
            border-radius: 4px; font-weight: 700;
            font-size: 0.8em; letter-spacing: 0.5px;
        }}
        .step-timestamp {{ color: #888; font-size: 0.8em; }}
        .step-thought {{
            padding: 8px; background: #e8f4fd;
            border-left: 3px solid #2196F3; border-radius: 4px;
            font-size: 0.9em;
        }}
        .step-element {{
            font-size: 0.85em; color: #555;
        }}
        .step-element code {{
            background: #f0f0f0; padding: 2px 4px; border-radius: 2px;
            font-size: 0.9em;
        }}
        .step-coords {{ font-size: 0.85em; color: #666; }}
        .step-typed {{
            padding: 6px 8px; background: #e8f4fd;
            border-radius: 4px; font-size: 0.9em;
        }}
        .step-observation {{
            padding: 8px; background: #e8f5e9;
            border-left: 3px solid #4CAF50; border-radius: 4px;
            font-size: 0.9em;
        }}
        .filmstrip {{
            display: flex; gap: 4px; overflow-x: auto;
            padding: 8px 4px; background: #f5f5f5;
            border-radius: 6px; margin-top: 4px;
        }}
        .filmstrip-thumb {{
            flex: 0 0 auto; width: {filmstrip_size}px;
            cursor: pointer; border: 2px solid transparent;
            border-radius: 4px; overflow: hidden;
            text-align: center; background: #fff;
            transition: border-color 0.2s;
        }}
        .filmstrip-thumb:hover {{ border-color: #90CAF9; }}
        .filmstrip-thumb.filmstrip-active {{ border-color: #2196F3; }}
        .filmstrip-thumb img {{
            width: 100%; height: {int(filmstrip_size * 0.65)}px;
            object-fit: cover; display: block;
        }}
        .filmstrip-placeholder {{
            width: 100%; height: {int(filmstrip_size * 0.65)}px;
            display: flex; align-items: center; justify-content: center;
            background: #eee; color: #999; font-size: 0.8em;
        }}
        .filmstrip-label {{
            font-size: 0.7em; color: #666; padding: 2px 0;
        }}
        .overlay-controls {{
            display: flex; gap: 12px; padding: 6px 0;
            font-size: 0.8em; color: #555;
        }}
        .overlay-controls label {{
            display: flex; align-items: center; gap: 4px; cursor: pointer;
        }}
        .web-agent-per-step-annotations {{
            margin-top: 12px; padding-top: 12px;
            border-top: 1px solid #e0e0e0;
        }}

        /* SVG overlay styles */
        .overlay-click-marker {{ }}
        .overlay-bbox {{ }}
        .overlay-mouse-path {{ }}
        .overlay-scroll {{ }}

        @keyframes pulse-marker {{
            0%, 100% {{ r: 8; opacity: 1; }}
            50% {{ r: 12; opacity: 0.7; }}
        }}

        @media (max-width: 768px) {{
            .web-agent-main {{ flex-direction: column; }}
            .step-details-panel {{ max-width: none; max-height: none; }}
            .screenshot-panel {{ max-width: 100%; }}
            .step-screenshot {{ max-width: 100%; }}
        }}
        '''

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        classes = super().get_css_classes(field_config)
        return classes

    def get_data_attributes(self, field_config: Dict[str, Any], data: Any) -> Dict[str, str]:
        attrs = super().get_data_attributes(field_config, data)
        return attrs
