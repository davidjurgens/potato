"""
Span Layout
"""

import logging
from collections.abc import Mapping
from collections import defaultdict
from potato.server_utils.config_module import config
from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_element_value,
    generate_validation_attribute,
    escape_html_content
)

from potato.item_state_management import SpanAnnotation

logger = logging.getLogger(__name__)

SPAN_COLOR_PALETTE = [
    "(230, 25, 75)",
    "(60, 180, 75)",
    "(255, 225, 25)",
    "(0, 130, 200)",
    "(245, 130, 48)",
    "(145, 30, 180)",
    "(70, 240, 240)",
    "(240, 50, 230)",
    "(210, 245, 60)",
    "(250, 190, 212)",
    "(0, 128, 128)",
    "(220, 190, 255)",
    "(170, 110, 40)",
    "(255, 250, 200)",
    "(128, 0, 0)",
    "(170, 255, 195)",
    "(128, 128, 0)",
    "(255, 215, 180)",
    "(0, 0, 128)",
    "(128, 128, 128)",
    "(255, 255, 255)",
    "(0, 0, 0)",
]

span_counter = 0
SPAN_COLOR_PALETTE_LENGTH = len(SPAN_COLOR_PALETTE)

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

def render_span_annotations(text, span_annotations: list[SpanAnnotation]):
    print(f"🔍 render_span_annotations called with text: '{text[:50]}...' and {len(span_annotations)} spans")

    rev_order_sa = sorted(span_annotations, key=lambda d: d.get_start(), reverse=True)

    print('🔍 rev_order_sa: ', rev_order_sa)

    ann_wrapper = (
        '<span class="span_container" selection_label="{annotation}" '
        + 'schema="{schema}" style="background-color:rgb{bg_color};">'
        + "{span}"
        + '<div class="span_label" schema="{schema}" name="{annotation}" '
        + 'style="background-color:white;border:2px solid rgb{color};">'
        + "{annotation_title}</div>"
        + "<div class=\"span_close\" style=\"background-color:white;\""
         " onclick=\"deleteSpanAnnotation(this, {schema}, {annotation}, {annotation_title}, {start}, {end});\">×</div>"
        + "</span>"
    )
    for a in rev_order_sa:

        # Spans are colored according to their order in the list and we need to
        # retrofit the color
        color = get_span_color(a.get_schema(), a.get_name())
        if color is None:
            # Default to gray if no color is found
            color = "(128, 128, 128)"
        # The color is an RGB triple like (1,2,3)
        # Convert to hex with alpha for background if test expects it
        rgb = tuple(int(x.strip()) for x in color.strip("() ").split(","))
        hex_color = '#{:02x}{:02x}{:02x}80'.format(*rgb)  # 80 = 50% alpha
        # For border, use rgb as before
        bg_color = hex_color

        # The text above the span is its title and we display whatever its set to
        annotation_title= a.get_title()

        print(text, a)
        span = text[a.get_start():a.get_end()]

        ann = (
            f'<span class="span-highlight" selection_label="{a.get_name()}" '
            f'data-label="{a.get_name()}" '
            f'schema="{a.get_schema()}" style="background-color: {bg_color};" data-annotation-id="{a.get_id()}">'  # new attribute
            f'{span}'
            f'<div class="span_label" schema="{a.get_schema()}" name="{a.get_name()}" '
            f'style="background-color:white;border:2px solid rgb{color};">'
            f'{annotation_title}</div>'
            f'<div class="span_close" style="background-color:white;"'
            f' onclick="deleteSpanAnnotation(this, {a.get_schema()}, {a.get_name()}, {annotation_title}, {a.get_start()}, {a.get_end()});">×</div>'
            f'</span>'
        )
        text = text[:a.get_start()] + ann + text[a.get_end():]

    return text

def render_span_annotations_old(text, span_annotations):
    """
    Retuns a modified version of the text with span annotation overlays inserted
    into the text.

    :text: some instance to be annotated
    :span_annotations: annotations already made by the user that need to be
       re-inserted into the text
    """
    # This code is synchronized with the javascript function
    # surroundSelection(selectionLabel) function in base_template.html which
    # wraps any labeled text with a <div> element indicating its label. We
    # replicate this code here (in python).
    #
    # This synchrony also means that any changes to the UI code for rendering
    # need to be updated here too.

    # We need to go in reverse order to make the string update in the right
    # places, so make sure things are ordered in reverse of start

    rev_order_sa = sorted(span_annotations, key=lambda d: d["start"], reverse=True)

    ann_wrapper = (
        '<span class="span_container" selection_label="{annotation}" '
        + 'schema="{schema}" style="background-color:rgb{bg_color};">'
        + "{span}"
        + '<div class="span_label" schema="{schema}" name="{annotation}" '
        + 'style="background-color:white;border:2px solid rgb{color};">'
        + "{annotation_title}</div></span>"
    )
    for a in rev_order_sa:

        # Spans are colored according to their order in the list and we need to
        # retrofit the color
        color = get_span_color(a["annotation"])
        # The color is an RGB triple like (1,2,3) and we want the background for
        # the text to be somewhat transparent so we switch to RGBA for bg
        bg_color = color.replace(")", ",0.25)")

        # The text above the span is its title and we display whatever its set to
        annotation_title= a["annotation_title"]

        ann = ann_wrapper.format(
            annotation=a["annotation"], annotation_title=annotation_title,
            span=a["span"], color=color, bg_color=bg_color, schema=a["schema"]
        )
        print(text, a)
        text = text[: a["start"]] + ann + text[a["end"] :]

    return text


def generate_span_layout(annotation_scheme, horizontal=False):
    """
    Generate HTML for a span selection interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - labels: List of label options for spans
            - sequential_key_binding: Enable numeric key bindings
            - displaying_score: Show numeric values with labels
            - bad_text_label: Optional configuration for invalid text option
            - tooltip: Optional hover text description

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the span interface
            key_bindings: List of (key, description) tuples for keyboard shortcuts
    """
    return safe_generate_layout(annotation_scheme, _generate_span_layout_internal, horizontal)

def _generate_span_layout_internal(annotation_scheme, horizontal=False):
    """
    Internal function to generate span layout after validation.
    """
    # Initialize form wrapper
    scheme_name = annotation_scheme["name"]
    schematic = f"""
    <form id="{escape_html_content(scheme_name)}" class="annotation-form span shadcn-span-container" action="/action_page.php">
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
            key_value = str(i)
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

        schematic += f"""
            <div class="shadcn-span-option">
                <input class="{escape_html_content(scheme_name)} shadcn-span-checkbox"
                       for_span="true"
                       type="checkbox"
                       id="{escape_html_content(scheme_name)}"
                       name="{escape_html_content(name_with_span)}"
                       value="{escape_html_content(key_value)}"
                       onclick="onlyOne(this); changeSpanLabel(this, '{escape_html_content(scheme_name)}', '{escape_html_content(label)}', '{escape_html_content(span_title)}', '{escape_html_content(span_color)}');"
                       validation="{validation}">
                <label for="{escape_html_content(scheme_name)}" class="shadcn-span-label" {tooltip}>
                    <span style="background-color:rgb{span_color.replace(')', ',0.25)')};">{escape_html_content(label_content)}</span>
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
