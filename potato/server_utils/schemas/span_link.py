"""
Span Link Layout

Generates the UI for creating and managing relationships/links between spans.
This schema type works in conjunction with a span annotation schema to allow
users to annotate relationships like "PERSON works_for ORGANIZATION".
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

# Default colors for link types
LINK_COLOR_PALETTE = [
    "#dc2626",  # Red
    "#22c55e",  # Green
    "#a855f7",  # Purple
    "#f59e0b",  # Amber
    "#3b82f6",  # Blue
    "#ec4899",  # Pink
    "#06b6d4",  # Cyan
    "#f97316",  # Orange
    "#8b5cf6",  # Violet
    "#10b981",  # Emerald
]


def _generate_span_link_layout_internal(annotation_scheme, horizontal=False):
    """
    Internal function to generate span link layout after validation.

    Args:
        annotation_scheme: Configuration dictionary containing:
            - name: Schema name
            - description: Description shown to user
            - span_schema: Name of the span schema to link
            - link_types: List of link type definitions with:
                - name: Link type name (e.g., "WORKS_FOR")
                - directed: Whether the link is directed (default: false)
                - allowed_source_labels: Optional list of allowed source span labels
                - allowed_target_labels: Optional list of allowed target span labels
                - max_spans: Maximum spans in a link (default: 2, higher for n-ary)
                - color: Optional color for this link type
        horizontal: Whether to display horizontally (not used for links)

    Returns:
        tuple: (HTML string, key bindings list)
    """
    scheme_name = annotation_scheme["name"]
    description = annotation_scheme.get("description", "Create relationships between spans")
    span_schema = annotation_scheme.get("span_schema", "")
    link_types = annotation_scheme.get("link_types", [])
    visual_display = annotation_scheme.get("visual_display", {})

    # Build link types HTML
    link_types_html = ""
    key_bindings = []

    for i, link_type in enumerate(link_types):
        link_name = link_type.get("name", f"Link_{i}")
        directed = link_type.get("directed", False)
        max_spans = link_type.get("max_spans", 2)
        color = link_type.get("color", LINK_COLOR_PALETTE[i % len(LINK_COLOR_PALETTE)])

        # Direction indicator
        direction_icon = "→" if directed else "↔"
        direction_class = "directed" if directed else "undirected"

        # Tooltip with constraints
        tooltip_parts = []
        if link_type.get("allowed_source_labels"):
            tooltip_parts.append(f"Source: {', '.join(link_type['allowed_source_labels'])}")
        if link_type.get("allowed_target_labels"):
            tooltip_parts.append(f"Target: {', '.join(link_type['allowed_target_labels'])}")
        if max_spans > 2:
            tooltip_parts.append(f"N-ary: up to {max_spans} spans")

        tooltip_attr = ""
        if tooltip_parts:
            tooltip_text = "; ".join(tooltip_parts)
            tooltip_attr = f'data-toggle="tooltip" data-placement="top" title="{escape_html_content(tooltip_text)}"'

        link_types_html += f"""
            <div class="span-link-type" data-link-type="{escape_html_content(link_name)}"
                 data-directed="{str(directed).lower()}"
                 data-max-spans="{max_spans}"
                 data-color="{escape_html_content(color)}"
                 data-source-labels="{escape_html_content(','.join(link_type.get('allowed_source_labels', [])))}"
                 data-target-labels="{escape_html_content(','.join(link_type.get('allowed_target_labels', [])))}"
                 {tooltip_attr}>
                <input type="radio" name="{escape_html_content(scheme_name)}_link_type"
                       id="{escape_html_content(scheme_name)}_link_{escape_html_content(link_name)}"
                       value="{escape_html_content(link_name)}"
                       class="span-link-type-radio">
                <label for="{escape_html_content(scheme_name)}_link_{escape_html_content(link_name)}"
                       class="span-link-type-label {direction_class}"
                       style="--link-color: {color}">
                    <span class="link-color-indicator" style="background-color: {color}"></span>
                    <span class="link-type-name">{escape_html_content(link_name)}</span>
                    <span class="link-direction-icon">{direction_icon}</span>
                </label>
            </div>
        """

    # Visual display settings
    show_arcs = visual_display.get("enabled", True)
    arc_position = visual_display.get("arc_position", "above")
    show_labels = visual_display.get("show_labels", True)
    # Multi-line arc mode: "single_line" (horizontal scroll) or "bracket" (wrapped text with bracket arcs)
    multi_line_mode = visual_display.get("multi_line_mode", "bracket")

    schematic = f"""
    <div id="{escape_html_content(scheme_name)}" class="span-link-container annotation-form"
         data-annotation-type="span_link"
         data-annotation-id="{annotation_scheme.get('annotation_id', scheme_name)}"
         data-span-schema="{escape_html_content(span_schema)}"
         data-show-arcs="{str(show_arcs).lower()}"
         data-arc-position="{escape_html_content(arc_position)}"
         data-show-labels="{str(show_labels).lower()}"
         data-multi-line-mode="{escape_html_content(multi_line_mode)}">

        <div class="span-link-header">
            <h4 class="span-link-title">{escape_html_content(description)}</h4>
        </div>

        <!-- Link Type Selector -->
        <div class="span-link-type-selector">
            <label class="span-link-section-label">Select Link Type:</label>
            <div class="span-link-types">
                {link_types_html}
            </div>
        </div>

        <!-- Selected Spans Display -->
        <div class="span-link-selection">
            <label class="span-link-section-label">Selected Spans:</label>
            <div class="span-link-selected-spans" id="{escape_html_content(scheme_name)}_selected_spans">
                <p class="no-selection-message">Click on highlighted spans to select them for linking</p>
            </div>
        </div>

        <!-- Action Buttons -->
        <div class="span-link-actions">
            <button type="button" class="span-link-create-btn" id="{escape_html_content(scheme_name)}_create_link"
                    disabled>
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path>
                    <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path>
                </svg>
                Create Link
            </button>
            <button type="button" class="span-link-clear-btn" id="{escape_html_content(scheme_name)}_clear_selection"
                    title="Exit link mode to create new span annotations (Esc)">
                Exit Link Mode
            </button>
        </div>

        <!-- Existing Links Display -->
        <div class="span-link-existing">
            <label class="span-link-section-label">Existing Links:</label>
            <div class="span-link-list" id="{escape_html_content(scheme_name)}_link_list">
                <p class="no-links-message">No links created yet</p>
            </div>
        </div>

        <!-- Visual Display Toggle -->
        <div class="span-link-visual-toggle">
            <label>
                <input type="checkbox" id="{escape_html_content(scheme_name)}_show_arcs"
                       {'checked' if show_arcs else ''}>
                Show link arcs above text
            </label>
        </div>

        <!-- Hidden input to store link data for form submission -->
        <input type="hidden" name="span_link:::{escape_html_content(scheme_name)}"
               id="{escape_html_content(scheme_name)}_link_data" value="[]">
    </div>
    """

    return schematic, key_bindings


def generate_span_link_layout(annotation_scheme, horizontal=False):
    """
    Generate span link layout HTML for the given annotation scheme.

    Args:
        annotation_scheme (dict): The annotation scheme configuration
        horizontal (bool): Whether to display horizontally

    Returns:
        tuple: (HTML string, key bindings list)
    """
    return safe_generate_layout(annotation_scheme, _generate_span_link_layout_internal, horizontal)


def render_link_arcs(links, span_positions):
    """
    Generate SVG arcs for visualizing links between spans.

    Args:
        links: List of SpanLink objects
        span_positions: Dictionary mapping span_id -> {x, y, width, height} positions

    Returns:
        str: SVG markup for the link arcs
    """
    if not links or not span_positions:
        return ""

    svg_paths = []

    for link in links:
        span_ids = link.get_span_ids()
        if len(span_ids) < 2:
            continue

        # Get color for this link type
        link_color = link.get_properties().get("color", "#dc2626")

        # For binary links, draw a simple arc
        if len(span_ids) == 2:
            span1_id, span2_id = span_ids
            if span1_id not in span_positions or span2_id not in span_positions:
                continue

            pos1 = span_positions[span1_id]
            pos2 = span_positions[span2_id]

            # Calculate arc endpoints (center of each span)
            x1 = pos1["x"] + pos1["width"] / 2
            y1 = pos1["y"]
            x2 = pos2["x"] + pos2["width"] / 2
            y2 = pos2["y"]

            # Calculate control point for the arc
            mid_x = (x1 + x2) / 2
            arc_height = min(abs(x2 - x1) / 3, 50)  # Arc height proportional to distance

            # Create SVG path
            if link.is_directed():
                # Directed link with arrow
                svg_paths.append(f"""
                    <path d="M {x1} {y1} Q {mid_x} {y1 - arc_height} {x2} {y2}"
                          fill="none" stroke="{link_color}" stroke-width="2"
                          marker-end="url(#arrowhead)"
                          class="span-link-arc" data-link-id="{link.get_id()}" />
                """)
            else:
                # Undirected link
                svg_paths.append(f"""
                    <path d="M {x1} {y1} Q {mid_x} {y1 - arc_height} {x2} {y2}"
                          fill="none" stroke="{link_color}" stroke-width="2"
                          class="span-link-arc" data-link-id="{link.get_id()}" />
                """)

        # For n-ary links, connect all spans to a central point
        else:
            # Calculate center point
            valid_positions = [span_positions[sid] for sid in span_ids if sid in span_positions]
            if len(valid_positions) < 2:
                continue

            center_x = sum(p["x"] + p["width"] / 2 for p in valid_positions) / len(valid_positions)
            center_y = min(p["y"] for p in valid_positions) - 30  # Above the spans

            # Draw lines from each span to center
            for span_id in span_ids:
                if span_id not in span_positions:
                    continue
                pos = span_positions[span_id]
                x = pos["x"] + pos["width"] / 2
                y = pos["y"]
                svg_paths.append(f"""
                    <line x1="{x}" y1="{y}" x2="{center_x}" y2="{center_y}"
                          stroke="{link_color}" stroke-width="2"
                          class="span-link-arc" data-link-id="{link.get_id()}" />
                """)

            # Draw central node
            svg_paths.append(f"""
                <circle cx="{center_x}" cy="{center_y}" r="6"
                        fill="{link_color}"
                        class="span-link-node" data-link-id="{link.get_id()}" />
            """)

    # Wrap in SVG with defs for arrow markers
    svg = f"""
    <svg class="span-link-arcs-layer" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; overflow: visible;">
        <defs>
            <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                <polygon points="0 0, 10 3.5, 0 7" fill="currentColor" />
            </marker>
        </defs>
        {''.join(svg_paths)}
    </svg>
    """

    return svg
