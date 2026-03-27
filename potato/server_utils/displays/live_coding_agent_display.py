"""
Live Coding Agent Display

Dual-mode display for live coding agent sessions:
- Live mode (no data): Shows start form + streaming viewer with controls
- Review mode (data present): Delegates to CodingTraceDisplay

Usage:
    fields:
      - key: structured_turns
        type: live_coding_agent
        display_options:
          show_file_tree: true
          show_reasoning: true
          collapse_long_outputs: true
"""

import html
from typing import Dict, Any, List, Optional

from .base import BaseDisplay
from .coding_trace_display import CodingTraceDisplay


class LiveCodingAgentDisplay(BaseDisplay):
    """Display type for live coding agent sessions."""

    name = "live_coding_agent"
    required_fields = ["key"]
    optional_fields = {
        "show_file_tree": True,
        "show_reasoning": True,
        "collapse_long_outputs": True,
        "max_output_lines": 50,
        "show_controls": True,
        "allow_instructions": True,
    }
    description = "Live coding agent viewer with real-time streaming and intervention controls"
    supports_span_target = False

    def __init__(self):
        self._coding_trace_display = CodingTraceDisplay()

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        # If data has structured turns, delegate to CodingTraceDisplay (review mode)
        if data and isinstance(data, (list, dict)):
            if isinstance(data, list) and len(data) > 0:
                return self._coding_trace_display.render(field_config, data)
            if isinstance(data, dict) and data.get("structured_turns"):
                return self._coding_trace_display.render(
                    field_config, data["structured_turns"]
                )

        # Live mode: render the viewer UI
        field_key = html.escape(field_config.get("key", ""), quote=True)
        options = self.get_display_options(field_config)

        show_controls = options.get("show_controls", True)
        allow_instructions = options.get("allow_instructions", True)

        controls_html = ""
        if show_controls:
            controls_html = f'''
            <div class="lca-controls" id="lca-controls-{field_key}">
                <button type="button" class="lca-btn lca-btn-pause" data-action="pause" title="Pause agent">
                    Pause
                </button>
                <button type="button" class="lca-btn lca-btn-resume" data-action="resume" title="Resume agent" style="display:none">
                    Resume
                </button>
                <button type="button" class="lca-btn lca-btn-stop" data-action="stop" title="Stop agent">
                    Stop
                </button>
            </div>
            '''

        instruction_html = ""
        if allow_instructions:
            instruction_html = f'''
            <div class="lca-instruction" id="lca-instruction-{field_key}">
                <input type="text" class="lca-instruction-input"
                       placeholder="Send instruction to agent..."
                       id="lca-instruction-input-{field_key}">
                <button type="button" class="lca-btn lca-btn-send" data-action="instruct">
                    Send
                </button>
            </div>
            '''

        return f'''
        <div class="live-coding-agent-viewer" id="lca-viewer-{field_key}"
             data-field-key="{field_key}">

            <!-- Start form (shown when no session active) -->
            <div class="lca-start-form" id="lca-start-{field_key}">
                <div class="lca-start-header">Start Coding Agent</div>
                <textarea class="lca-task-input" id="lca-task-{field_key}"
                          rows="3" placeholder="Describe the coding task..."></textarea>
                <button type="button" class="lca-btn lca-btn-start" data-action="start">
                    Start Agent
                </button>
            </div>

            <!-- Live session view (hidden until session starts) -->
            <div class="lca-session" id="lca-session-{field_key}" style="display:none">
                <!-- Status bar -->
                <div class="lca-status-bar">
                    <span class="lca-status-indicator" id="lca-status-{field_key}"></span>
                    <span class="lca-status-text" id="lca-status-text-{field_key}">Connecting...</span>
                    <span class="lca-turn-counter" id="lca-counter-{field_key}">0 turns</span>
                    {controls_html}
                </div>

                {instruction_html}

                <!-- Thinking indicator -->
                <div class="lca-thinking" id="lca-thinking-{field_key}" style="display:none">
                    <span class="lca-thinking-dot"></span>
                    <span class="lca-thinking-text" id="lca-thinking-text-{field_key}">Thinking...</span>
                </div>

                <!-- Streaming turns (same structure as CodingTraceDisplay) -->
                <div class="lca-turns coding-trace-display" id="lca-turns-{field_key}">
                </div>
            </div>
        </div>
        '''

    def has_inline_label(self, field_config: Dict[str, Any]) -> bool:
        return False

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        classes = super().get_css_classes(field_config)
        return classes
