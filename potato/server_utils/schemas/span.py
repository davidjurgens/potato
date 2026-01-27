"""
Span Layout
"""

import logging
from collections.abc import Mapping
from collections import defaultdict
from ai.ai_help_wrapper import get_ai_wrapper, get_dynamic_ai_help
from server_utils.config_module import config
from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_element_value,
    generate_validation_attribute,
    escape_html_content
)


from item_state_management import SpanAnnotation

logger = logging.getLogger(__name__)

SPAN_COLOR_PALETTE = [
    "(110, 86, 207)",   # Primary purple #6E56CF
    "(239, 68, 68)",    # Destructive red #EF4444
    "(113, 113, 122)",  # Gray #71717A
    "(245, 158, 11)",   # Amber #F59E0B
    "(16, 185, 129)",   # Success green #10B981
    "(59, 130, 246)",   # Blue #3B82F6
    "(220, 38, 38)",    # Red #DC2626
    "(139, 92, 246)",   # Purple #8B5CF6
    "(156, 163, 175)",  # Light gray #9CA3AF
    "(107, 114, 128)",  # Medium gray #6B7280
    "(55, 65, 81)",     # Dark gray #374151
    "(249, 115, 22)",   # Orange #F97316
    "(6, 182, 212)",    # Cyan #06B6D4
    "(236, 72, 153)",   # Pink #EC4899
    "(5, 150, 105)",    # Dark green #059669
    "(124, 58, 237)",   # Violet #7C3AED
    "(22, 163, 74)",    # Green #16A34A
    "(234, 88, 12)",    # Dark orange #EA580C
    "(37, 99, 235)",    # Blue #2563EB
    "(127, 29, 29)",    # Dark red #7F1D1D
    "(168, 85, 247)",   # Purple #A855F7
    "(34, 197, 94)",    # Green #22C55E
]

span_counter = 0
SPAN_COLOR_PALETTE_LENGTH = len(SPAN_COLOR_PALETTE)


def reset_span_counter():
    """Reset the span color counter to 0. Used for test isolation."""
    global span_counter
    span_counter = 0

def get_span_color(schema, span_label):
    """
    Returns the color of a span with this label as a string with an RGB triple
    in parentheses, or None if the span is unmapped.
    """

    if "ui" not in config or "spans" not in config["ui"]:
        return None

    span_ui = config["ui"]["spans"]

    if "span_colors" not in span_ui:
        return None

    if schema in span_ui["span_colors"]:
        schema_colors = span_ui["span_colors"][schema]
        if span_label in schema_colors:
            return schema_colors[span_label]

    return None


def set_span_color(schema, span_label, color):
    """
    Sets the color of a span with this label as a string with an RGB triple in parentheses.

    :color: a string containing an RGB triple in parentheses
    """
    if "ui" not in config:
        ui = {}
        config["ui"] = ui
    else:
        ui = config["ui"]

    if "spans" not in ui:
        span_ui = {}
        ui["spans"] = span_ui
    else:
        span_ui = ui["spans"]

    if "span_colors" not in span_ui:
        span_colors = defaultdict(dict)
        span_ui["span_colors"] = span_colors
    else:
        span_colors = span_ui["span_colors"]

    span_colors[schema][span_label] = color

def _generate_span_layout_internal(annotation_scheme, horizontal=False):
    """
    Internal function to generate span layout after validation.
    """
    # Initialize form wrapper
    scheme_name = annotation_scheme["name"]
    schematic = f"""
    <form id="{escape_html_content(scheme_name)}" class="annotation-form span shadcn-span-container" action="/action_page.php" data-annotation-id="{annotation_scheme["annotation_id"]}" >
            {get_ai_wrapper()}
        <fieldset schema="{escape_html_content(scheme_name)}">
            <legend class="shadcn-span-title">{escape_html_content(annotation_scheme["description"])}</legend>
            <div class="shadcn-span-options">
    """

    if isinstance(annotation_scheme["labels"], list) and len(annotation_scheme["labels"]) > 0:
        labels = annotation_scheme["labels"]
    else:
        labels = [annotation_scheme["labels"]]

    # Initialize keyboard shortcuts
    key2label = {}
    label2key = {}
    key_bindings = []
    span_title = annotation_scheme.get("title", "")

    # Setup validation
    validation = generate_validation_attribute(annotation_scheme)
    span_color = "var(--primary-color)"

    # Generate checkbox inputs for each label
    for i, label_data in enumerate(labels, 1):
        # Extract label information
        if isinstance(label_data, str):
            label = label_data
            key_value = label  # Use label name as value
            tooltip = ""
        else:
            label = label_data["name"]
            key_value = label_data.get("key_value", str(i))
            tooltip = _generate_tooltip(label_data)

        # Check for color mappings
        custom_color = get_span_color(scheme_name, label)
        if custom_color:
            span_color = custom_color
        else:
            # Assign a color from palette
            global span_counter
            idx = span_counter % SPAN_COLOR_PALETTE_LENGTH
            span_color = SPAN_COLOR_PALETTE[idx]
            span_counter += 1
            set_span_color(scheme_name, label, span_color)

        # Handle sequential key bindings
        if (
            "sequential_key_binding" in annotation_scheme
            and annotation_scheme["sequential_key_binding"]
            and len(annotation_scheme["labels"]) <= 10
        ):
            key_value = str(i % 10)
            key2label[key_value] = label
            label2key[label] = key_value
            key_bindings.append((key_value, f"{scheme_name}: {label}"))

        # Format label content
        if "displaying_score" in annotation_scheme and annotation_scheme["displaying_score"]:
            label_content = f"{key_value}.{label}"
        else:
            label_content = label

        # Generate name with span prefix so ingestion code can skip this
        name_with_span = f"span_label:::{scheme_name}"

        # Support abbreviation for label display (from master branch fix)
        # Users can specify an abbreviation for the label shown above the span
        if isinstance(label_data, dict) and label_data.get('abbreviation'):
            label_title = label_data['abbreviation']
        else:
            label_title = label_content

        # Use label as title if span_title is empty
        effective_title = span_title if span_title else label

        schematic += f"""
            <div class="shadcn-span-option">
                <input class="{escape_html_content(scheme_name)} shadcn-span-checkbox"
                       for_span="true"
                       type="checkbox"
                       id="{escape_html_content(scheme_name)}_{escape_html_content(label)}"
                       name="{escape_html_content(name_with_span)}"
                       value="{escape_html_content(key_value)}"
                       onclick="onlyOne(this); changeSpanLabel(this, '{escape_html_content(scheme_name)}', '{escape_html_content(label)}', '{escape_html_content(effective_title)}', '{escape_html_content(span_color)}');"
                       validation="{validation}">
                <label for="{escape_html_content(scheme_name)}_{escape_html_content(label)}" class="shadcn-span-label" {tooltip}>
                    <span style="background-color:rgb{span_color.replace(')', ',0.4)')};">{escape_html_content(label_content)}</span>
                </label>
            </div>
        """

    schematic += "</div>"

    # Add optional bad text option
    if "label_content" in annotation_scheme.get("bad_text_label", {}):
        bad_text_identifiers = generate_element_identifier(annotation_scheme['name'], "bad_text", "checkbox")

        schematic += f"""
            <div class="shadcn-span-bad-text">
                <input class="{bad_text_identifiers['schema']} shadcn-span-checkbox"
                       for_span="true"
                       type="checkbox"
                       id="{bad_text_identifiers['id']}"
                       name="{bad_text_identifiers['name']}"
                       value="0"
                       onclick="onlyOne(this)"
                       validation="{validation}">
                <label for="{bad_text_identifiers['id']}" class="shadcn-span-label">
                    {escape_html_content(annotation_scheme["bad_text_label"]["label_content"])}
                </label>
            </div>
        """

        if (
            "sequential_key_binding" in annotation_scheme
            and annotation_scheme["sequential_key_binding"]
            and len(annotation_scheme["labels"]) <= 10
        ):
            key_bindings.append(
                (0, f"{scheme_name}: {annotation_scheme['bad_text_label']['label_content']}")
            )

    schematic += "</fieldset></form>"
    return schematic, key_bindings

def _generate_tooltip(label_data):
    """
    Generate tooltip HTML attribute from label data.

    Args:
        label_data (dict): Label configuration containing tooltip information

    Returns:
        str: Tooltip HTML attribute or empty string if no tooltip
    """
    tooltip_text = ""
    if "tooltip" in label_data:
        tooltip_text = label_data["tooltip"]
    elif "tooltip_file" in label_data:
        try:
            with open(label_data["tooltip_file"], "rt") as f:
                tooltip_text = "".join(f.readlines())
        except Exception as e:
            logger.error(f"Failed to read tooltip file: {e}")
            return ""

    if tooltip_text:
        escaped_tooltip = escape_html_content(tooltip_text)
        return f'data-toggle="tooltip" data-html="true" data-placement="top" title="{escaped_tooltip}"'
    return ""


def generate_span_layout(annotation_scheme, horizontal=False):
    """
    Generate span layout HTML for the given annotation scheme.

    Args:
        annotation_scheme (dict): The annotation scheme configuration
        horizontal (bool): Whether to display horizontally

    Returns:
        tuple: (HTML string, key bindings list)
    """
    return safe_generate_layout(annotation_scheme, _generate_span_layout_internal, horizontal)


def render_span_annotations(text, span_annotations):
    """
    Render span annotations into HTML with boundary-based algorithm.
    Args:
        text (str): The original text to annotate
        span_annotations: Dictionary of span_id -> span data, or list of SpanAnnotation objects
    Returns:
        str: HTML with span annotations rendered
    """
    if not span_annotations:
        return text

    # Handle both dict and list inputs
    if isinstance(span_annotations, dict):
        # Convert dictionary to list of tuples (span_id, span_data)
        sorted_spans = sorted(
            span_annotations.items(),
            key=lambda x: x[1].get('start', 0)
        )
    else:
        # Convert list of SpanAnnotation objects to list of tuples
        spans_as_tuples = []
        for span in span_annotations:
            if hasattr(span, 'get_id'):
                # SpanAnnotation object with methods
                span_id = span.get_id()
                span_data = {
                    'schema': span.get_schema() if hasattr(span, 'get_schema') else getattr(span, 'schema', ''),
                    'name': span.get_name() if hasattr(span, 'get_name') else getattr(span, 'name', ''),
                    'title': span.get_title() if hasattr(span, 'get_title') else getattr(span, 'title', ''),
                    'start': span.get_start() if hasattr(span, 'get_start') else getattr(span, 'start', 0),
                    'end': span.get_end() if hasattr(span, 'get_end') else getattr(span, 'end', 0),
                }
            elif isinstance(span, dict):
                span_id = span.get('id', f"span_{span.get('start', 0)}_{span.get('end', 0)}")
                span_data = span
            else:
                continue
            spans_as_tuples.append((span_id, span_data))
        sorted_spans = sorted(spans_as_tuples, key=lambda x: x[1].get('start', 0))
    
    # Create boundary points
    boundaries = []
    for span_id, span_data in sorted_spans:
        boundaries.append((span_data['start'], 'start', span_id, span_data))
        boundaries.append((span_data['end'], 'end', span_id, span_data))
    
    # Sort boundaries by position
    boundaries.sort(key=lambda x: x[0])
    
    # Build the rendered text
    result = ""
    current_pos = 0
    active_spans = []
    
    for pos, boundary_type, span_id, span_data in boundaries:
        # Add text before this boundary
        if pos > current_pos:
            result += text[current_pos:pos]
        
        if boundary_type == 'start':
            # Start a new span
            active_spans.append(span_id)
            # Get color for this span
            color = get_span_color(span_data['schema'], span_data['name'])
            if not color:
                color = "(128, 128, 128)"  # Default gray
            # Convert RGB to hex with alpha
            color_parts = color.strip("()").split(", ")
            r, g, b = int(color_parts[0]), int(color_parts[1]), int(color_parts[2])
            hex_color = f"#{r:02x}{g:02x}{b:02x}66"  # 66 = 40% alpha to match label background
            result += f'<span class="span-highlight" data-annotation-id="{span_id}" data-label="{span_data["name"]}" schema="{span_data["schema"]}" style="background-color: {hex_color};">'
        elif boundary_type == 'end':
            # End the span
            result += "</span>"
            # Remove from active spans
            active_spans = [s for s in active_spans if s != span_id]
        
        current_pos = pos
    
    # Add remaining text
    if current_pos < len(text):
        result += text[current_pos:]
    
    return result