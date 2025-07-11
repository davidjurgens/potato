"""
slider Layout
"""

# Needed for the fall-back radio layout
from .radio import generate_radio_layout
from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    escape_html_content
)

def test_and_get(key, d):
    val = d[key]
    try:
        return int(val)
    except:
        raise Exception(
            'Slider scale %s\'s value for "%s" is not an int' % (d["name"], key)
        )

def generate_slider_layout(annotation_scheme):
    """
    Generate HTML for a slider input interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - starting_value: Initial slider value
            - min_value: Minimum allowed value
            - max_value: Maximum allowed value
            - show_labels: Whether to show min/max labels
            - labels: If present, fall back to radio layout

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the slider interface
            key_bindings: Empty list (no keyboard shortcuts)
    """
    return safe_generate_layout(annotation_scheme, _generate_slider_layout_internal)

def _generate_slider_layout_internal(annotation_scheme):
    """
    Internal function to generate slider layout after validation.
    """
    # If the user specified the more complicated likert layout, default to the
    # radio layout
    if "labels" in annotation_scheme:
        return generate_radio_layout(annotation_scheme, horizontal=False)

    # Check all the configurations are present
    for required in ["starting_value", "min_value", "max_value"]:
        if required not in annotation_scheme:
            raise Exception(
                'Slider scale for "%s" did not include %s' % (annotation_scheme["name"], required)
            )

    # Check the values make sense
    min_value = test_and_get("min_value", annotation_scheme)
    max_value = test_and_get("max_value", annotation_scheme)
    starting_value = test_and_get("starting_value", annotation_scheme)

    if min_value >= max_value:
        raise Exception(
            'Slider scale for "%s" must have minimum value < max value (%d >= %d)' \
                % (annotation_scheme["name"], min_value, max_value)
        )

    # Optionally show the labels for the ends of the sliders
    show_labels = True if 'show_labels' not in annotation_scheme \
        else annotation_scheme['show_labels']
    min_label = str(min_value) if show_labels else ''
    max_label = str(max_value) if show_labels else ''

    # Generate consistent identifiers
    identifiers = generate_element_identifier(annotation_scheme["name"], "slider", "range")

    schematic = f"""
    <form id="{escape_html_content(annotation_scheme['name'])}" class="annotation-form slider shadcn-slider-container" action="/action_page.php">
        <fieldset schema="{escape_html_content(annotation_scheme['name'])}">
            <legend class="shadcn-slider-title">{escape_html_content(annotation_scheme["description"])}</legend>
            <div class="shadcn-slider-wrapper">
                <div class="shadcn-slider-label">{escape_html_content(min_label)}</div>
                <div class="shadcn-slider-track">
                    <input type="range"
                           min="{min_value}"
                           max="{max_value}"
                           value="{starting_value}"
                           class="shadcn-slider-input annotation-input"
                           onclick="registerAnnotation(this);"
                           label_name="{identifiers['label_name']}"
                           name="{identifiers['name']}"
                           id="{identifiers['id']}"
                           schema="{identifiers['schema']}">
                </div>
                <div class="shadcn-slider-label">{escape_html_content(max_label)}</div>
            </div>
        </fieldset>
    </form>
    """

    key_bindings = []
    return schematic, key_bindings
