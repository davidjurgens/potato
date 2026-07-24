"""
Multi-Agent Discussion Display Type

Purpose-built rendering for conversations between multiple agents (debates,
crew discussions, agent-to-agent coordination). Compared to the generic
dialogue display it adds:

- an **agent legend**: one chip per agent with a deterministic color,
  doubling as a client-side filter (click to show/hide that agent's turns)
- **per-agent color coding** of turns (left border + avatar chip)
- **addressee chips** ("→ critic") when turns carry an ``addressee`` key
  (populated e.g. by the AutoGen converter from sender/receiver)
- **reply threading**: turns with a ``reply_to`` key referencing another
  turn's ``turn_id`` are indented under a connector
- Phase-A **turn-level annotation slots** (via the ``_turn_schemes``
  injection), like dialogue/agent_trace

Data format: list of turn dicts with ``speaker``/``text`` plus the optional
standardized identity keys (``agent_id``, ``role``, ``addressee``,
``turn_id``, ``reply_to``) documented in trace_converter/base.py. Agent
identity falls back to the speaker string when ``agent_id`` is absent, so
plain dialogue data renders sensibly too.

Client-side behavior (filtering) lives in
potato/static/multi-agent-discussion.js.
"""

import hashlib
import html
from typing import Any, Dict, List

from .base import BaseDisplay
from ._trace_normalize import PASSTHROUGH_KEYS

# Color palette for agent identity (border/avatar). Chosen for contrast on
# white; assignment is deterministic via md5 of the agent id so colors are
# stable across instances and sessions (same convention as span colors).
AGENT_PALETTE = [
    "#2563eb",  # blue
    "#d97706",  # amber
    "#059669",  # emerald
    "#dc2626",  # red
    "#7c3aed",  # violet
    "#0891b2",  # cyan
    "#db2777",  # pink
    "#65a30d",  # lime
    "#ea580c",  # orange
    "#4f46e5",  # indigo
]


def agent_color(agent_id: str) -> str:
    """Deterministic palette color for an agent id."""
    digest = hashlib.md5(str(agent_id).encode("utf-8")).hexdigest()
    return AGENT_PALETTE[int(digest[:8], 16) % len(AGENT_PALETTE)]


def readable_text_on(hex_color: str) -> str:
    """Return black or white — whichever has the higher WCAG contrast on
    ``hex_color``. The avatar initial sits directly on the agent color, and
    several palette entries (amber/emerald/lime/cyan) are too light for white
    text, so pick per-swatch instead of hard-coding ``#fff``."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return "#fff"
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return "#fff"

    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    lum = 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)
    # Contrast against black is (lum+0.05)/0.05; against white is 1.05/(lum+0.05).
    return "#1c1917" if (lum + 0.05) / 0.05 >= 1.05 / (lum + 0.05) else "#fff"


class MultiAgentDiscussionDisplay(BaseDisplay):
    """Display type for multi-agent discussions/debates."""

    name = "multi_agent_discussion"
    required_fields = ["key"]
    optional_fields = {
        "speaker_key": "speaker",
        "text_key": "text",
        "show_turn_numbers": False,
        "show_legend": True,
        "show_addressees": True,
        "thread_replies": True,
        "collapse_environment": False,
    }
    description = "Multi-agent discussion with agent legend, colors, addressees, and filtering"
    supports_span_target = True

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        if not data:
            return '<div class="mad-placeholder">No discussion provided</div>'

        options = self.get_display_options(field_config)
        speaker_key = options.get("speaker_key", "speaker")
        text_key = options.get("text_key", "text")
        show_turn_numbers = options.get("show_turn_numbers", False)
        show_legend = options.get("show_legend", True)
        show_addressees = options.get("show_addressees", True)
        thread_replies = options.get("thread_replies", True)
        collapse_environment = options.get("collapse_environment", False)

        turns = self._normalize(data, speaker_key, text_key)
        if not turns:
            return '<div class="mad-placeholder">No discussion turns found</div>'

        field_key = html.escape(field_config.get("key", ""), quote=True)
        is_span_target = field_config.get("span_target", False)
        turn_schemes = field_config.get("_turn_schemes") or []

        agents = self._agent_roster(turns)
        color_by_agent = {a: agent_color(a) for a in agents}

        # Legend / filter chips
        legend_html = ""
        if show_legend and len(agents) > 1:
            chips = []
            for agent in agents:
                esc_agent = html.escape(agent, quote=True)
                color = color_by_agent[agent]
                chips.append(
                    f'<button type="button" class="mad-legend-chip" data-agent-id="{esc_agent}"'
                    f' aria-pressed="true" style="--agent-color: {color};" '
                    f'title="Click to show/hide {esc_agent}">'
                    f'<span class="mad-avatar" style="background:{color};color:{readable_text_on(color)};">'
                    f'{html.escape(agent[:1].upper())}</span>{html.escape(agent)}</button>'
                )
            legend_html = (
                f'<div class="mad-legend" data-field-key="{field_key}">'
                f'<span class="mad-legend-label">Agents:</span>{"".join(chips)}'
                f'</div>'
            )

        turn_html_list = []
        for i, turn in enumerate(turns):
            speaker = str(turn.get("speaker", ""))
            text = str(turn.get("text", ""))
            raw_agent = str(turn.get("agent_id", "") or "")
            agent_id = raw_agent or speaker or "unknown"
            addressee = str(turn.get("addressee", ""))
            is_env = not raw_agent and speaker.lower() in ("environment", "system")
            color = color_by_agent.get(agent_id, "#9ca3af")

            esc_agent = html.escape(agent_id, quote=True)
            classes = ["mad-turn"]
            style = f'--agent-color: {color};'
            is_reply = thread_replies and turn.get("reply_to")
            if is_reply:
                classes.append("mad-reply")

            turn_number_html = (
                f'<span class="mad-turn-number">[{i + 1}]</span>' if show_turn_numbers else ""
            )

            avatar_html = (
                f'<span class="mad-avatar" style="background:{color};color:{readable_text_on(color)};">'
                f'{html.escape(agent_id[:1].upper())}</span>'
            )

            role = str(turn.get("role", ""))
            role_html = f'<span class="mad-role">{html.escape(role)}</span>' if role else ""

            addressee_html = ""
            if show_addressees and addressee:
                addressee_html = (
                    f'<span class="mad-addressee" title="directed at {html.escape(addressee, quote=True)}">'
                    f'&rarr; {html.escape(addressee)}</span>'
                )

            escaped_text = html.escape(text)
            text_id = ""
            span_attrs = ""
            if is_span_target:
                text_id = f'id="mad-text-{field_key}-{i}"'
                # Per-turn data-original-text (same as dialogue_display): the
                # SpanManager reads it for offset-based overlay positioning.
                span_attrs = f'data-original-text="{escaped_text}" data-turn-index="{i}"'

            if collapse_environment and is_env:
                body_html = (
                    f'<details class="mad-env-collapsible"><summary>Environment output</summary>'
                    f'<span class="mad-text" {text_id} {span_attrs}>{escaped_text}</span></details>'
                )
            else:
                body_html = f'<span class="mad-text" {text_id} {span_attrs}>{escaped_text}</span>'

            # Turn-level annotation slot (Phase A framework)
            slot_html = ""
            if turn_schemes:
                from ..turn_annotations import render_turn_slot
                slot_html = render_turn_slot(turn_schemes, turn, i, field_key)

            reply_connector = '<span class="mad-reply-connector" aria-hidden="true"></span>' if is_reply else ""

            turn_html_list.append(f'''
            <div class="{' '.join(classes)}" data-agent-id="{esc_agent}" data-turn-index="{i}" style="{style}">
                {reply_connector}
                <div class="mad-turn-header">
                    {turn_number_html}
                    {avatar_html}
                    <span class="mad-speaker">{html.escape(speaker)}</span>
                    {role_html}
                    {addressee_html}
                </div>
                {body_html}
                {slot_html}
            </div>
            ''')

        all_turns_html = "\n".join(turn_html_list)

        # Span-target contract: same canonical-text approach as dialogue —
        # omit data-original-text so getCanonicalText() falls back to
        # container.textContent and offsets always agree with selection.
        if is_span_target:
            all_turns_html = (
                f'<div class="text-content" id="text-content-{field_key}"'
                f' style="position: relative; padding-top: 24px;">'
                f'{all_turns_html}'
                f'</div>'
            )

        return f'''
        <div class="multi-agent-discussion" data-field-key="{field_key}">
            {legend_html}
            <div class="mad-turns">
                {all_turns_html}
            </div>
        </div>
        '''

    def _normalize(self, data: Any, speaker_key: str, text_key: str) -> List[Dict[str, Any]]:
        """Normalize to turn dicts, passing through identity keys."""
        turns = []
        if isinstance(data, str):
            for line in data.strip().split("\n"):
                line = line.strip()
                if line:
                    turns.append({"speaker": "", "text": line})
            return turns
        if not isinstance(data, list):
            return turns
        for item in data:
            if isinstance(item, dict):
                turn = {
                    "speaker": item.get(speaker_key, ""),
                    "text": item.get(text_key, str(item)),
                }
                for key in PASSTHROUGH_KEYS + ("reply_to",):
                    if key in item and item[key] not in (None, ""):
                        turn[key] = item[key]
                turns.append(turn)
            else:
                turns.append({"speaker": "", "text": str(item)})
        return turns

    def _agent_roster(self, turns: List[Dict[str, Any]]) -> List[str]:
        """Unique agent ids in order of first appearance (speaker fallback)."""
        seen: List[str] = []
        for turn in turns:
            agent = str(turn.get("agent_id") or turn.get("speaker") or "")
            if agent and agent not in seen:
                seen.append(agent)
        return seen

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
