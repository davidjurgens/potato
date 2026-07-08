"""
Multi-Document Event Annotation Layout

Renders the annotator-facing form for cross-document event annotation. Unlike
`event_annotation` (single-instance trigger+argument events), this schema works
with the Event Registry: events are first-class objects that span documents.

The form lets an annotator:
  - see events the current document belongs to (fetched from the registry API),
  - create a new event (if allowed),
  - fill admin-defined template slots,
  - attach the current document to an event,
  - cite evidence for a slot by selecting a span in the reading pane.

Persistence note (IIFE-overwrite gotcha): the authoritative store is the Event
Registry (server-side, via /corpus/api/*). The hidden input here is initialized
from its server-restored ``value`` attribute and is only a lightweight mirror of
this document's event memberships — the frontend JS reads ``input.value`` on load
(never hardcoded defaults) before refreshing from the API.
"""

import json
import logging

from .identifier_utils import (
    safe_generate_layout,
    escape_html_content,
)

logger = logging.getLogger(__name__)


def _generate_multi_document_event_layout_internal(annotation_scheme, horizontal=False):
    scheme_name = annotation_scheme["name"]
    description = annotation_scheme.get(
        "description", "Annotate events that span multiple documents"
    )
    slots = annotation_scheme.get("slots", [])
    allow_create = annotation_scheme.get("allow_annotator_create", True)

    # Slot metadata is emitted for the JS to render inputs + cite buttons.
    slots_json = json.dumps(
        [
            {
                "name": s.get("name", ""),
                "description": s.get("description", ""),
                "type": s.get("type", "text"),
            }
            for s in slots
        ]
    )

    schematic = f"""
    <div id="{escape_html_content(scheme_name)}" class="mde-container annotation-form"
         data-annotation-type="multi_document_event"
         data-scheme-name="{escape_html_content(scheme_name)}"
         data-allow-create="{str(bool(allow_create)).lower()}"
         data-slots='{escape_html_content(slots_json)}'>

        <div class="mde-header">
            <h4 class="mde-title">{escape_html_content(description)}</h4>
        </div>

        <!-- Events this document belongs to / can be added to -->
        <div class="mde-events-section">
            <div class="mde-section-header">
                <label class="mde-section-label">Events</label>
                <button type="button" class="mde-create-btn" data-role="create-event"
                        {'' if allow_create else 'style="display:none"'}>
                    + New event
                </button>
            </div>
            <div class="mde-event-list" data-role="event-list">
                <p class="mde-empty">Loading events…</p>
            </div>
        </div>

        <!-- Active event editor: slots + evidence -->
        <div class="mde-editor" data-role="editor" style="display:none;">
            <div class="mde-editor-head">
                <input type="text" class="mde-editor-title" data-role="editor-title"
                       placeholder="Event name…">
                <label class="mde-membership">
                    <input type="checkbox" data-role="membership-toggle">
                    This document belongs to this event
                </label>
            </div>
            <div class="mde-slots" data-role="slots"></div>
        </div>

        <!-- Cite-evidence hint (shown while awaiting a span selection) -->
        <div class="mde-cite-hint" data-role="cite-hint" style="display:none;">
            Select text in the document to cite it as evidence for
            <strong data-role="cite-slot"></strong>.
            <button type="button" data-role="cite-cancel">Cancel</button>
        </div>

        <!-- Lightweight per-instance mirror of memberships. Initialized from the
             server-restored value; JS reads this before refreshing from API. -->
        <input type="hidden" name="multi_document_event:::{escape_html_content(scheme_name)}"
               id="{escape_html_content(scheme_name)}_mde_data" value="">
    </div>
    """

    return schematic, []


def generate_multi_document_event_layout(annotation_scheme, horizontal=False):
    """Generate multi-document event annotation layout.

    Returns:
        tuple: (HTML string, key bindings list)
    """
    return safe_generate_layout(
        annotation_scheme, _generate_multi_document_event_layout_internal, horizontal
    )
