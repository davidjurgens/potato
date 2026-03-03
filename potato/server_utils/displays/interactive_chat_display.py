"""
Interactive Chat Display Type

Renders either a live chat panel (when conversation data is null/empty)
or a completed dialogue (when conversation data is populated).

Before the annotator finishes chatting, this shows the chat UI.
After clicking "Finish & Annotate", the route writes the conversation
into the item data, and this display renders the completed conversation
using DialogueDisplay (which supports per-turn ratings).
"""

import html
from typing import Dict, Any, List

from .base import BaseDisplay
from .dialogue_display import DialogueDisplay

# Reuse the dialogue display for rendering completed conversations
_dialogue_display = DialogueDisplay()


class InteractiveChatDisplay(BaseDisplay):
    """
    Display type for interactive agent chat sessions.

    When data is null/empty: renders a chat panel placeholder
    (the actual chat UI is handled by agent-chat.js).
    When data is populated: delegates to DialogueDisplay for the conversation,
    which supports per-turn ratings for individual turn annotation.
    """

    name = "interactive_chat"
    required_fields = ["key"]
    optional_fields = {
        "placeholder_text": "Start chatting with the agent to begin the task.",
        "per_turn_ratings": None,
        "show_turn_numbers": True,
        "alternating_shading": True,
    }
    description = "Interactive agent chat with post-interaction trace display"
    supports_span_target = True

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        # If conversation data exists, render as dialogue with per-turn ratings
        if data:
            return _dialogue_display.render(field_config, data)

        # Otherwise render the chat panel container
        # The actual chat UI is injected by agent-chat.js
        options = self.get_display_options(field_config)
        placeholder = html.escape(options.get(
            "placeholder_text",
            "Start chatting with the agent to begin the task.",
        ))
        field_key = html.escape(field_config.get("key", ""), quote=True)

        return f'''
        <div class="agent-chat-panel" id="agent-chat-panel" data-field-key="{field_key}">
            <div class="agent-chat-messages" id="agent-chat-messages">
                <div class="agent-chat-placeholder">{placeholder}</div>
            </div>
            <div class="agent-chat-input-area">
                <textarea id="agent-chat-input"
                          class="agent-chat-textarea"
                          placeholder="Type your message..."
                          rows="2"></textarea>
                <div class="agent-chat-controls">
                    <span class="agent-chat-step-counter" id="agent-chat-step-counter"></span>
                    <button type="button" class="btn btn-primary btn-sm" id="agent-chat-send-btn"
                            onclick="agentChatSend()">Send</button>
                    <button type="button" class="btn btn-success btn-sm" id="agent-chat-finish-btn"
                            onclick="agentChatFinish()">Finish &amp; Annotate</button>
                </div>
            </div>
        </div>
        '''

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        classes = super().get_css_classes(field_config)
        # Include display-type-dialogue so dialogue CSS rules apply to
        # the completed conversation rendered by DialogueDisplay
        classes.append("display-type-dialogue")
        if field_config.get("span_target"):
            classes.append("span-target-field")
        return classes

    def get_data_attributes(self, field_config: Dict[str, Any], data: Any) -> Dict[str, str]:
        attrs = super().get_data_attributes(field_config, data)
        if field_config.get("span_target"):
            attrs["span-target"] = "true"
        # Signal to JS whether this is in chat mode or trace mode
        attrs["chat-active"] = "true" if not data else "false"
        return attrs
