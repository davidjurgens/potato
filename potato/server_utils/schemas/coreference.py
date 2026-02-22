"""
Coreference Chain Annotation Layout

Generates the UI for creating and managing coreference chains —
groupings of text spans that refer to the same entity.

This schema type works in conjunction with a span annotation schema.
A coreference chain is an n-ary undirected link where span_ids lists
all mentions of the same entity. It leverages the existing SpanLink
infrastructure with a specialized chain management UI.
"""

import logging
import json
from .identifier_utils import (
    safe_generate_layout,
    escape_html_content,
)

logger = logging.getLogger(__name__)

# Default colors for coreference chains
CHAIN_COLOR_PALETTE = [
    "#6E56CF",  # Purple
    "#EF4444",  # Red
    "#22C55E",  # Green
    "#3B82F6",  # Blue
    "#F59E0B",  # Amber
    "#EC4899",  # Pink
    "#06B6D4",  # Cyan
    "#F97316",  # Orange
    "#8B5CF6",  # Violet
    "#10B981",  # Emerald
    "#DC2626",  # Dark red
    "#A855F7",  # Light purple
    "#14B8A6",  # Teal
    "#F43F5E",  # Rose
    "#84CC16",  # Lime
]


def _generate_coreference_layout_internal(annotation_scheme, horizontal=False):
    """
    Internal function to generate coreference chain layout.

    Args:
        annotation_scheme: Configuration dictionary containing:
            - name: Schema name
            - description: Description shown to user
            - span_schema: Name of the span schema providing mentions
            - entity_types: Optional list of entity types for chain classification
            - allow_singletons: Whether single-mention chains are allowed (default: True)
            - visual_display:
                - highlight_mode: "bracket" | "background" | "underline" (default: "background")

    Returns:
        tuple: (HTML string, key bindings list)
    """
    scheme_name = annotation_scheme["name"]
    description = annotation_scheme.get("description", "Create coreference chains")
    span_schema = annotation_scheme.get("span_schema", "")
    entity_types = annotation_scheme.get("entity_types", [])
    allow_singletons = annotation_scheme.get("allow_singletons", True)
    visual_display = annotation_scheme.get("visual_display", {})
    highlight_mode = visual_display.get("highlight_mode", "background")

    # Build entity type selector HTML
    entity_types_html = ""
    if entity_types:
        for i, etype in enumerate(entity_types):
            if isinstance(etype, dict):
                etype_name = etype.get("name", f"Entity_{i}")
                etype_color = etype.get("color", CHAIN_COLOR_PALETTE[i % len(CHAIN_COLOR_PALETTE)])
            else:
                etype_name = str(etype)
                etype_color = CHAIN_COLOR_PALETTE[i % len(CHAIN_COLOR_PALETTE)]

            entity_types_html += f"""
                <div class="coref-entity-type" data-entity-type="{escape_html_content(etype_name)}"
                     data-color="{escape_html_content(etype_color)}">
                    <input type="radio" name="{escape_html_content(scheme_name)}_entity_type"
                           id="{escape_html_content(scheme_name)}_etype_{escape_html_content(etype_name)}"
                           value="{escape_html_content(etype_name)}"
                           class="coref-entity-type-radio">
                    <label for="{escape_html_content(scheme_name)}_etype_{escape_html_content(etype_name)}"
                           class="coref-entity-type-label"
                           style="--chain-color: {etype_color}">
                        <span class="coref-color-indicator" style="background-color: {etype_color}"></span>
                        <span class="coref-type-name">{escape_html_content(etype_name)}</span>
                    </label>
                </div>
            """

    # Config data for JS
    config_data = json.dumps({
        "schemaName": scheme_name,
        "spanSchema": span_schema,
        "entityTypes": entity_types if entity_types else [],
        "allowSingletons": allow_singletons,
        "highlightMode": highlight_mode,
        "colors": CHAIN_COLOR_PALETTE,
    })

    entity_type_section = ""
    if entity_types:
        entity_type_section = f"""
        <div class="coref-entity-type-selector">
            <label class="coref-section-label">Entity Type:</label>
            <div class="coref-entity-types">
                {entity_types_html}
            </div>
        </div>
        """

    schematic = f"""
    <div id="{escape_html_content(scheme_name)}" class="coref-container annotation-form"
         data-annotation-type="coreference"
         data-annotation-id="{annotation_scheme.get('annotation_id', scheme_name)}"
         data-span-schema="{escape_html_content(span_schema)}"
         data-allow-singletons="{str(allow_singletons).lower()}"
         data-highlight-mode="{escape_html_content(highlight_mode)}"
         data-coref-config='{escape_html_content(config_data)}'>

        <div class="coref-header">
            <h4 class="coref-title">{escape_html_content(description)}</h4>
            <span class="coref-chain-count" id="{escape_html_content(scheme_name)}_chain_count">0 chains</span>
        </div>

        {entity_type_section}

        <!-- Chain Actions -->
        <div class="coref-actions">
            <button type="button" class="coref-btn coref-new-chain-btn"
                    id="{escape_html_content(scheme_name)}_new_chain"
                    title="Create a new chain from selected mentions">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="12" y1="5" x2="12" y2="19"></line>
                    <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>
                New Chain
            </button>
            <button type="button" class="coref-btn coref-add-to-chain-btn"
                    id="{escape_html_content(scheme_name)}_add_to_chain"
                    disabled title="Add selected mention to active chain">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path>
                    <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path>
                </svg>
                Add to Chain
            </button>
            <button type="button" class="coref-btn coref-merge-btn"
                    id="{escape_html_content(scheme_name)}_merge_chains"
                    disabled title="Merge selected chains">
                Merge Chains
            </button>
            <button type="button" class="coref-btn coref-remove-btn"
                    id="{escape_html_content(scheme_name)}_remove_mention"
                    disabled title="Remove selected mention from its chain">
                Remove Mention
            </button>
        </div>

        <!-- Chain Panel (sidebar-style list of all chains) -->
        <div class="coref-chain-panel" id="{escape_html_content(scheme_name)}_chain_panel">
            <div class="coref-chain-list" id="{escape_html_content(scheme_name)}_chain_list">
                <p class="coref-no-chains-message">No coreference chains created yet.
                Select spans and click "New Chain" to start.</p>
            </div>
        </div>

        <!-- Hidden input to store chain data for form submission -->
        <input type="hidden" name="span_link:::{escape_html_content(scheme_name)}"
               id="{escape_html_content(scheme_name)}_chain_data" value="[]">
    </div>
    """

    key_bindings = []
    return schematic, key_bindings


def generate_coreference_layout(annotation_scheme, horizontal=False):
    """
    Generate coreference chain layout HTML.

    Args:
        annotation_scheme (dict): The annotation scheme configuration
        horizontal (bool): Whether to display horizontally

    Returns:
        tuple: (HTML string, key bindings list)
    """
    return safe_generate_layout(
        annotation_scheme, _generate_coreference_layout_internal, horizontal
    )
