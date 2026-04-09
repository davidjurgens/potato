"""
Live Agent Display Type

Dual-mode display:
- When data is empty/None: renders the live agent UI (SSE-connected viewer,
  controls, instruction input, thought panel, filmstrip)
- When data contains a completed trace: delegates to WebAgentTraceDisplay
  for post-hoc review

Configuration example:
    instance_display:
      fields:
        - key: agent_trace
          type: live_agent
          label: "Live Agent Session"
          display_options:
            show_overlays: true
            show_filmstrip: true
            show_thought: true
            show_controls: true
            allow_takeover: true
            allow_instructions: true
            screenshot_max_width: 900
            screenshot_max_height: 650
"""

import html
import json
from typing import Any, Dict, List

from .base import BaseDisplay


class LiveAgentDisplay(BaseDisplay):
    """
    Display type for live AI agent interaction.

    Renders a viewer that connects to the agent SSE stream, showing real-time
    screenshots, overlay visualizations, and providing controls for
    pause/resume/instruct/takeover.
    """

    name = "live_agent"
    required_fields = ["key"]
    optional_fields = {
        "show_overlays": True,
        "show_filmstrip": True,
        "show_thought": True,
        "show_controls": True,
        "allow_takeover": True,
        "allow_instructions": True,
        "screenshot_max_width": 900,
        "screenshot_max_height": 650,
        "filmstrip_size": 80,
    }
    description = "Live AI agent viewer with real-time screenshots, controls, and interaction"
    supports_span_target = False

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        """
        Render live agent UI or delegate to trace viewer.

        If data contains a completed trace (dict with 'steps'), delegates
        to WebAgentTraceDisplay. Otherwise renders the live interaction UI.
        """
        # Check if data is a completed trace (has steps)
        if data and isinstance(data, dict) and data.get("steps"):
            return self._render_review_mode(field_config, data)

        return self._render_live_mode(field_config, data)

    def _render_review_mode(self, field_config: Dict[str, Any], data: dict) -> str:
        """Delegate to WebAgentTraceDisplay for completed traces."""
        from .web_agent_trace_display import WebAgentTraceDisplay

        reviewer = WebAgentTraceDisplay()
        return reviewer.render(field_config, data)

    def _render_live_mode(self, field_config: Dict[str, Any], data: Any) -> str:
        """Render the live agent interaction UI."""
        options = self.get_display_options(field_config)
        field_key = html.escape(field_config.get("key", ""), quote=True)

        max_w = options.get("screenshot_max_width", 900)
        max_h = options.get("screenshot_max_height", 650)
        filmstrip_size = options.get("filmstrip_size", 80)
        show_controls = options.get("show_controls", True)
        show_thought = options.get("show_thought", True)
        show_filmstrip = options.get("show_filmstrip", True)
        show_overlays = options.get("show_overlays", True)
        allow_takeover = options.get("allow_takeover", True)
        allow_instructions = options.get("allow_instructions", True)

        # Encode config as data attributes for JS
        config_json = html.escape(json.dumps({
            "show_overlays": show_overlays,
            "show_filmstrip": show_filmstrip,
            "show_thought": show_thought,
            "show_controls": show_controls,
            "allow_takeover": allow_takeover,
            "allow_instructions": allow_instructions,
        }), quote=True)

        # Extract task info from instance data if available
        task_desc = ""
        start_url = ""
        if isinstance(data, dict):
            task_desc = data.get("task_description", "")
            start_url = data.get("start_url", data.get("url", ""))

        css = self._build_css(max_w, max_h, filmstrip_size)
        html_content = self._build_html(
            field_key, config_json, task_desc, start_url,
            show_controls, show_thought, show_filmstrip,
            show_overlays, allow_takeover, allow_instructions,
            max_w, max_h, filmstrip_size,
        )

        return f"<style>{css}</style>\n{html_content}"

    def _build_css(self, max_w: int, max_h: int, filmstrip_size: int) -> str:
        return f"""
.live-agent-viewer {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    border: 1px solid #ddd;
    border-radius: 8px;
    overflow: hidden;
    background: #fafafa;
}}

/* Status bar */
.live-agent-status {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 16px;
    background: #f0f0f0;
    border-bottom: 1px solid #ddd;
    font-size: 13px;
}}
.live-agent-status-indicator {{
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 8px;
}}
.live-agent-status-indicator.idle {{ background: #9E9E9E; }}
.live-agent-status-indicator.running {{ background: #4CAF50; animation: pulse-dot 1.5s infinite; }}
.live-agent-status-indicator.paused {{ background: #FF9800; }}
.live-agent-status-indicator.takeover {{ background: #2196F3; }}
.live-agent-status-indicator.completed {{ background: #388E3C; }}
.live-agent-status-indicator.error {{ background: #F44336; }}
@keyframes pulse-dot {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.5; }}
}}

/* Main layout */
.live-agent-main {{
    display: flex;
    gap: 0;
}}
.live-agent-screenshot-panel {{
    flex: 1;
    position: relative;
    background: #000;
    min-height: 200px;
    max-width: {max_w}px;
}}
.live-agent-screenshot {{
    width: 100%;
    max-height: {max_h}px;
    object-fit: contain;
    display: block;
}}
/* Collapsed state — shrink screenshot for more annotation space */
.live-agent-viewer.collapsed .live-agent-main {{
    max-height: 220px;
    overflow: hidden;
}}
.live-agent-viewer.collapsed .live-agent-screenshot {{
    max-height: 200px;
}}
.live-agent-viewer.collapsed .live-agent-side-panel {{
    display: none;
}}
/* Collapse toggle */
.live-agent-collapse-toggle {{
    cursor: pointer;
    font-size: 12px;
    color: #666;
    padding: 2px 8px;
    border: 1px solid #ccc;
    border-radius: 4px;
    background: #fff;
}}
.live-agent-collapse-toggle:hover {{ background: #f0f0f0; }}

/* Takeover click feedback */
.live-agent-click-marker {{
    position: absolute;
    width: 24px;
    height: 24px;
    border: 2px solid #F44336;
    border-radius: 50%;
    background: rgba(244, 67, 54, 0.2);
    transform: translate(-50%, -50%);
    pointer-events: none;
    animation: click-pulse 0.6s ease-out forwards;
    z-index: 100;
}}
@keyframes click-pulse {{
    0% {{ transform: translate(-50%, -50%) scale(0.5); opacity: 1; }}
    100% {{ transform: translate(-50%, -50%) scale(2); opacity: 0; }}
}}

/* Takeover action toast */
.live-agent-action-toast {{
    position: absolute;
    bottom: 8px;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(0,0,0,0.8);
    color: #fff;
    padding: 4px 12px;
    border-radius: 4px;
    font-size: 12px;
    pointer-events: none;
    z-index: 100;
    animation: toast-fade 1.5s ease-out forwards;
}}
@keyframes toast-fade {{
    0% {{ opacity: 1; }}
    70% {{ opacity: 1; }}
    100% {{ opacity: 0; }}
}}
.live-agent-screenshot-placeholder {{
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 400px;
    color: #888;
    font-size: 16px;
}}
.live-agent-overlay-layer {{
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
}}

/* Side panel */
.live-agent-side-panel {{
    width: 320px;
    display: flex;
    flex-direction: column;
    border-left: 1px solid #ddd;
    background: #fff;
}}

/* Thought panel */
.live-agent-thought-panel {{
    padding: 12px;
    border-bottom: 1px solid #eee;
    max-height: 200px;
    overflow-y: auto;
}}
.live-agent-thought-panel h4 {{
    margin: 0 0 8px 0;
    font-size: 12px;
    text-transform: uppercase;
    color: #666;
}}
.live-agent-thought-text {{
    font-size: 13px;
    line-height: 1.5;
    color: #333;
    white-space: pre-wrap;
}}

/* Step details */
.live-agent-step-details {{
    padding: 12px;
    flex: 1;
    overflow-y: auto;
    font-size: 13px;
}}
.live-agent-action-badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
}}

/* Controls */
.live-agent-controls {{
    padding: 12px;
    border-top: 1px solid #ddd;
    background: #f8f8f8;
}}
.live-agent-control-buttons {{
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 8px;
}}
.live-agent-btn {{
    padding: 6px 14px;
    border: 1px solid #ddd;
    border-radius: 4px;
    background: #fff;
    cursor: pointer;
    font-size: 13px;
    transition: all 0.15s;
}}
.live-agent-btn:hover {{ background: #f0f0f0; }}
.live-agent-btn.primary {{ background: #2196F3; color: #fff; border-color: #1976D2; }}
.live-agent-btn.primary:hover {{ background: #1976D2; }}
.live-agent-btn.danger {{ background: #F44336; color: #fff; border-color: #D32F2F; }}
.live-agent-btn.danger:hover {{ background: #D32F2F; }}
.live-agent-btn.warning {{ background: #FF9800; color: #fff; border-color: #F57C00; }}
.live-agent-btn.warning:hover {{ background: #F57C00; }}
.live-agent-btn.active {{ background: #4CAF50; color: #fff; border-color: #388E3C; }}
.live-agent-btn:disabled {{ opacity: 0.5; cursor: not-allowed; }}

/* Instruction input */
.live-agent-instruction-input {{
    display: flex;
    gap: 8px;
    margin-top: 8px;
}}
.live-agent-instruction-input input {{
    flex: 1;
    padding: 6px 10px;
    border: 1px solid #ddd;
    border-radius: 4px;
    font-size: 13px;
}}

/* Start form */
.live-agent-start-form {{
    padding: 24px;
    text-align: center;
}}
.live-agent-start-form input {{
    display: block;
    width: 100%;
    max-width: 500px;
    margin: 8px auto;
    padding: 8px 12px;
    border: 1px solid #ddd;
    border-radius: 4px;
    font-size: 14px;
}}

/* Filmstrip */
.live-agent-filmstrip {{
    display: flex;
    gap: 4px;
    padding: 8px;
    overflow-x: auto;
    border-top: 1px solid #ddd;
    background: #f5f5f5;
}}
.live-agent-filmstrip-thumb {{
    width: {filmstrip_size}px;
    height: {int(filmstrip_size * 0.75)}px;
    object-fit: cover;
    border: 2px solid transparent;
    border-radius: 4px;
    cursor: pointer;
    flex-shrink: 0;
    opacity: 0.7;
    transition: all 0.15s;
}}
.live-agent-filmstrip-thumb:hover {{ opacity: 1; }}
.live-agent-filmstrip-thumb.active {{
    border-color: #2196F3;
    opacity: 1;
}}

/* Takeover cursor */
.live-agent-screenshot-panel.takeover-mode {{
    cursor: crosshair;
}}
.live-agent-screenshot-panel.takeover-mode .live-agent-overlay-layer {{
    pointer-events: auto;
}}

/* Overlay controls */
.live-agent-overlay-controls {{
    display: flex;
    gap: 12px;
    padding: 6px 12px;
    background: rgba(0,0,0,0.03);
    border-top: 1px solid #eee;
    font-size: 12px;
}}
.live-agent-overlay-controls label {{
    display: flex;
    align-items: center;
    gap: 4px;
    cursor: pointer;
}}
"""

    def _build_html(
        self, field_key, config_json, task_desc, start_url,
        show_controls, show_thought, show_filmstrip,
        show_overlays, allow_takeover, allow_instructions,
        max_w, max_h, filmstrip_size,
    ) -> str:
        # Build the UI components
        parts = []

        # Main container
        parts.append(
            f'<div class="live-agent-viewer" '
            f'data-field-key="{field_key}" '
            f'data-config="{config_json}">'
        )

        # Status bar
        parts.append("""
<div class="live-agent-status">
    <div>
        <span class="live-agent-status-indicator idle"></span>
        <span class="live-agent-status-text">Ready</span>
        <span class="live-agent-step-counter" style="margin-left: 12px; color: #888;">Step 0</span>
    </div>
    <div style="display:flex;align-items:center;gap:8px;">
        <span class="live-agent-url-display" style="color: #666; font-size: 12px;"></span>
        <button class="live-agent-collapse-toggle" title="Collapse/expand agent view">&#x25B2; Collapse</button>
    </div>
</div>
""")

        # Start form (shown when no session is active)
        task_desc_escaped = html.escape(task_desc, quote=True)
        start_url_escaped = html.escape(start_url, quote=True)
        parts.append(f"""
<div class="live-agent-start-form">
    <h3>Start Agent Session</h3>
    <input type="text" class="live-agent-task-input"
           placeholder="What should the agent do?"
           value="{task_desc_escaped}">
    <input type="url" class="live-agent-url-input"
           placeholder="Starting URL (e.g., https://example.com)"
           value="{start_url_escaped}">
    <button class="live-agent-btn primary live-agent-start-btn" style="margin-top: 12px;">
        Start Agent
    </button>
</div>
""")

        # Main viewer (hidden until session starts)
        parts.append('<div class="live-agent-main" style="display: none;">')

        # Screenshot panel
        parts.append(f"""
<div class="live-agent-screenshot-panel">
    <div class="live-agent-screenshot-placeholder">
        Waiting for agent to start...
    </div>
    <img class="live-agent-screenshot" style="display: none;" alt="Agent screenshot">
    <svg class="live-agent-overlay-layer" viewBox="0 0 {max_w} {max_h}"></svg>
</div>
""")

        # Side panel
        parts.append('<div class="live-agent-side-panel">')

        # Thought panel
        if show_thought:
            parts.append("""
<div class="live-agent-thought-panel">
    <h4>Agent Thinking</h4>
    <div class="live-agent-thought-text">Waiting for agent...</div>
</div>
""")

        # Step details
        parts.append("""
<div class="live-agent-step-details">
    <div class="live-agent-step-details-content"></div>
</div>
""")

        # Controls
        if show_controls:
            parts.append('<div class="live-agent-controls">')
            parts.append('<div class="live-agent-control-buttons">')
            parts.append(
                '<button class="live-agent-btn live-agent-pause-btn" disabled>Pause</button>'
            )
            parts.append(
                '<button class="live-agent-btn live-agent-resume-btn" disabled style="display:none;">Resume</button>'
            )
            if allow_takeover:
                parts.append(
                    '<button class="live-agent-btn warning live-agent-takeover-btn" disabled>Take Over</button>'
                )
            parts.append(
                '<button class="live-agent-btn danger live-agent-stop-btn" disabled>Stop</button>'
            )
            parts.append('</div>')

            if allow_instructions:
                parts.append("""
<div class="live-agent-instruction-input">
    <input type="text" class="live-agent-instruct-text"
           placeholder="Send instruction to agent..." disabled>
    <button class="live-agent-btn live-agent-instruct-btn" disabled>Send</button>
</div>
""")

            # Takeover toolbar — visible only in takeover mode
            if allow_takeover:
                parts.append("""
<div class="live-agent-takeover-toolbar" style="display:none;">
    <div style="font-size:12px;color:#666;margin-bottom:4px;">
        <strong>Manual Control</strong> &mdash;
        Click screenshot to click &bull;
        Scroll wheel to scroll &bull;
        Type to enter text &bull;
        Esc to return
    </div>
    <div style="display:flex;gap:6px;align-items:center;">
        <input type="text" class="live-agent-takeover-type-input"
               placeholder="Type text and press Enter to send..."
               style="flex:1;padding:5px 8px;border:1px solid #2196F3;border-radius:4px;font-size:13px;">
        <input type="url" class="live-agent-takeover-nav-input"
               placeholder="Navigate to URL..."
               style="width:240px;padding:5px 8px;border:1px solid #2196F3;border-radius:4px;font-size:13px;">
    </div>
</div>
""")

            parts.append('</div>')  # controls

        parts.append('</div>')  # side panel
        parts.append('</div>')  # main

        # Overlay controls
        if show_overlays:
            parts.append("""
<div class="live-agent-overlay-controls">
    <label><input type="checkbox" class="live-agent-overlay-toggle" data-overlay="click" checked> Clicks</label>
    <label><input type="checkbox" class="live-agent-overlay-toggle" data-overlay="bbox" checked> Bounding Boxes</label>
    <label><input type="checkbox" class="live-agent-overlay-toggle" data-overlay="mousepath" checked> Mouse Path</label>
    <label><input type="checkbox" class="live-agent-overlay-toggle" data-overlay="scroll" checked> Scroll</label>
</div>
""")

        # Filmstrip
        if show_filmstrip:
            parts.append(
                '<div class="live-agent-filmstrip" style="display: none;"></div>'
            )

        parts.append('</div>')  # viewer

        return "\n".join(parts)
