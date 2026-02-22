"""
Event Annotation Layout

Generates the UI for N-ary event annotation with triggers and typed arguments.
This schema type works in conjunction with a span annotation schema to allow
users to annotate events like "ATTACK(attacker=John, target=Mary, weapon=knife)".
"""

import logging
from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    escape_html_content,
    generate_tooltip_html
)
from .span import get_span_color, SPAN_COLOR_PALETTE

logger = logging.getLogger(__name__)

# Default colors for event types
EVENT_COLOR_PALETTE = [
    "#dc2626",  # Red
    "#2563eb",  # Blue
    "#16a34a",  # Green
    "#9333ea",  # Purple
    "#ea580c",  # Orange
    "#0891b2",  # Cyan
    "#c026d3",  # Fuchsia
    "#ca8a04",  # Yellow
    "#4f46e5",  # Indigo
    "#059669",  # Emerald
]


def _generate_event_annotation_layout_internal(annotation_scheme, horizontal=False):
    """
    Internal function to generate event annotation layout after validation.

    Args:
        annotation_scheme: Configuration dictionary containing:
            - name: Schema name
            - description: Description shown to user
            - span_schema: Name of the span schema for entities
            - event_types: List of event type definitions with:
                - type: Event type name (e.g., "ATTACK", "HIRE")
                - color: Optional color for this event type
                - trigger_labels: Optional list of span labels that can be triggers
                - arguments: List of argument definitions with:
                    - role: Role name (e.g., "attacker", "target")
                    - entity_types: Optional list of allowed entity types
                    - required: Whether this argument is required (default: false)
        horizontal: Whether to display horizontally (not used for events)

    Returns:
        tuple: (HTML string, key bindings list)
    """
    scheme_name = annotation_scheme["name"]
    description = annotation_scheme.get("description", "Annotate events with triggers and arguments")
    span_schema = annotation_scheme.get("span_schema", "")
    event_types = annotation_scheme.get("event_types", [])
    visual_display = annotation_scheme.get("visual_display", {})

    # Build event types HTML
    event_types_html = ""
    key_bindings = []

    for i, event_type in enumerate(event_types):
        type_name = event_type.get("type", f"Event_{i}")
        color = event_type.get("color", EVENT_COLOR_PALETTE[i % len(EVENT_COLOR_PALETTE)])
        trigger_labels = event_type.get("trigger_labels", [])
        arguments = event_type.get("arguments", [])

        # Build arguments data for JavaScript
        args_data = []
        for arg in arguments:
            args_data.append({
                "role": arg.get("role", ""),
                "entity_types": arg.get("entity_types", []),
                "required": arg.get("required", False)
            })

        import json
        args_json = json.dumps(args_data)

        # Tooltip with argument info
        tooltip_parts = []
        if trigger_labels:
            tooltip_parts.append(f"Triggers: {', '.join(trigger_labels)}")
        if arguments:
            arg_strs = []
            for arg in arguments:
                role = arg.get("role", "")
                req = "(required)" if arg.get("required", False) else "(optional)"
                entity_types = arg.get("entity_types", [])
                if entity_types:
                    arg_strs.append(f"{role} {req}: {', '.join(entity_types)}")
                else:
                    arg_strs.append(f"{role} {req}")
            tooltip_parts.append("Arguments: " + "; ".join(arg_strs))

        tooltip_attr = ""
        if tooltip_parts:
            tooltip_text = " | ".join(tooltip_parts)
            tooltip_attr = f'data-toggle="tooltip" data-placement="top" title="{escape_html_content(tooltip_text)}"'

        event_types_html += f"""
            <div class="event-type" data-event-type="{escape_html_content(type_name)}"
                 data-color="{escape_html_content(color)}"
                 data-trigger-labels="{escape_html_content(','.join(trigger_labels))}"
                 data-arguments='{escape_html_content(args_json)}'
                 {tooltip_attr}>
                <input type="radio" name="{escape_html_content(scheme_name)}_event_type"
                       id="{escape_html_content(scheme_name)}_event_{escape_html_content(type_name)}"
                       value="{escape_html_content(type_name)}"
                       class="event-type-radio">
                <label for="{escape_html_content(scheme_name)}_event_{escape_html_content(type_name)}"
                       class="event-type-label"
                       style="--event-color: {color}">
                    <span class="event-color-indicator" style="background-color: {color}"></span>
                    <span class="event-type-name">{escape_html_content(type_name)}</span>
                </label>
            </div>
        """

    # Visual display settings
    show_arcs = visual_display.get("enabled", True)
    arc_position = visual_display.get("arc_position", "above")
    show_labels = visual_display.get("show_labels", True)

    schematic = f"""
    <div id="{escape_html_content(scheme_name)}" class="event-annotation-container annotation-form"
         data-annotation-type="event_annotation"
         data-annotation-id="{annotation_scheme.get('annotation_id', scheme_name)}"
         data-span-schema="{escape_html_content(span_schema)}"
         data-show-arcs="{str(show_arcs).lower()}"
         data-arc-position="{escape_html_content(arc_position)}"
         data-show-labels="{str(show_labels).lower()}">

        <div class="event-annotation-header">
            <h4 class="event-annotation-title">{escape_html_content(description)}</h4>
        </div>

        <!-- Event Type Selector -->
        <div class="event-type-selector">
            <label class="event-section-label">1. Select Event Type:</label>
            <div class="event-types">
                {event_types_html}
            </div>
        </div>

        <!-- Trigger Selection -->
        <div class="event-trigger-section" style="display: none;">
            <label class="event-section-label">2. Select Trigger Span:</label>
            <div class="event-trigger-display" id="{escape_html_content(scheme_name)}_trigger_display">
                <p class="no-trigger-message">Click on a span to set it as the event trigger</p>
            </div>
        </div>

        <!-- Argument Assignment -->
        <div class="event-arguments-section" style="display: none;">
            <label class="event-section-label">3. Assign Arguments:</label>
            <div class="event-arguments-panel" id="{escape_html_content(scheme_name)}_arguments_panel">
                <!-- Argument roles will be populated dynamically -->
            </div>
        </div>

        <!-- Action Buttons -->
        <div class="event-actions">
            <button type="button" class="event-create-btn" id="{escape_html_content(scheme_name)}_create_event"
                    disabled>
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="8" x2="12" y2="16"></line>
                    <line x1="8" y1="12" x2="16" y2="12"></line>
                </svg>
                Create Event
            </button>
            <button type="button" class="event-cancel-btn" id="{escape_html_content(scheme_name)}_cancel_event"
                    title="Cancel event creation (Esc)">
                Cancel
            </button>
        </div>

        <!-- Existing Events Display -->
        <div class="event-existing">
            <label class="event-section-label">Existing Events:</label>
            <div class="event-list" id="{escape_html_content(scheme_name)}_event_list">
                <p class="no-events-message">No events created yet</p>
            </div>
        </div>

        <!-- Visual Display Toggle -->
        <div class="event-visual-toggle">
            <label>
                <input type="checkbox" id="{escape_html_content(scheme_name)}_show_arcs"
                       {'checked' if show_arcs else ''}>
                Show event arcs above text
            </label>
        </div>

        <!-- Hidden input to store event data for form submission -->
        <input type="hidden" name="event_annotation:::{escape_html_content(scheme_name)}"
               id="{escape_html_content(scheme_name)}_event_data" value="[]">
    </div>
    """

    return schematic, key_bindings


def generate_event_annotation_layout(annotation_scheme, horizontal=False):
    """
    Generate event annotation layout HTML for the given annotation scheme.

    Args:
        annotation_scheme (dict): The annotation scheme configuration
        horizontal (bool): Whether to display horizontally

    Returns:
        tuple: (HTML string, key bindings list)
    """
    return safe_generate_layout(annotation_scheme, _generate_event_annotation_layout_internal, horizontal)
