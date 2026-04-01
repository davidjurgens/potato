"""
Confidence-Calibrated Annotation Layout

Generates a confidence rating that pairs with a primary annotation scheme.
Supports both Likert-style discrete scale and continuous slider.

Research basis:
- Kutlu et al. (2020) "Annotator Rationales for Labeling Tasks in Crowdsourcing" JAIR
- Sheng et al. (2008) "Get Another Label?" KDD
"""

import logging

from potato.ai.ai_help_wrapper import get_ai_wrapper
from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_validation_attribute,
    escape_html_content,
    generate_layout_attributes,
)

logger = logging.getLogger(__name__)

DEFAULT_SCALE_POINTS = 5
DEFAULT_SCALE_TYPE = "likert"
DEFAULT_LABELS = [
    "Guessing",
    "Somewhat confident",
    "Fairly confident",
    "Confident",
    "Certain",
]


def generate_confidence_layout(annotation_scheme):
    """
    Generate HTML for a confidence-calibrated annotation interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - target_schema: Name of the primary schema this confidence is for (optional)
            - scale_type: "likert" or "slider" (default "likert")
            - scale_points: Number of points (default 5, for likert)
            - labels: Custom scale labels (optional)

    Returns:
        tuple: (html_string, key_bindings)
    """
    return safe_generate_layout(annotation_scheme, _generate_confidence_layout_internal)


def _generate_confidence_layout_internal(annotation_scheme):
    schema_name = annotation_scheme["name"]
    safe_schema = escape_html_content(schema_name)
    description = annotation_scheme["description"]
    scale_type = annotation_scheme.get("scale_type", DEFAULT_SCALE_TYPE)
    scale_points = annotation_scheme.get("scale_points", DEFAULT_SCALE_POINTS)
    custom_labels = annotation_scheme.get("labels", None)
    target_schema = annotation_scheme.get("target_schema", "")
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)

    if scale_type == "likert":
        labels = custom_labels if custom_labels else DEFAULT_LABELS[:scale_points]
        # Pad labels if fewer than scale points
        while len(labels) < scale_points:
            labels.append(f"Level {len(labels) + 1}")
    else:
        labels = []

    html = f"""
    <form id="{safe_schema}" class="annotation-form confidence shadcn-confidence-container"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          data-annotation-type="confidence"
          data-schema-name="{safe_schema}"
          data-target-schema="{escape_html_content(target_schema)}"
          {layout_attrs}>
        {get_ai_wrapper()}
        <fieldset schema="{safe_schema}">
            <legend class="shadcn-confidence-title">{escape_html_content(description)}</legend>
    """

    if scale_type == "likert":
        html += '<div class="confidence-likert-scale">'
        for i, label_text in enumerate(labels):
            if isinstance(label_text, dict):
                label_text = label_text.get("name", f"Level {i+1}")
            safe_label = escape_html_content(str(label_text))
            value = str(i + 1)
            identifiers = generate_element_identifier(schema_name, value, "radio")

            html += f"""
                <label class="confidence-likert-option" for="{identifiers['id']}">
                    <input class="{identifiers['schema']} confidence-radio annotation-input"
                           type="radio"
                           id="{identifiers['id']}"
                           name="{identifiers['name']}"
                           value="{value}"
                           schema="{identifiers['schema']}"
                           label_name="{identifiers['label_name']}"
                           validation="{validation}"
                           onclick="onlyOne(this);registerAnnotation(this);">
                    <span class="confidence-likert-button">{value}</span>
                    <span class="confidence-likert-label">{safe_label}</span>
                </label>
            """
        html += "</div>"
    else:
        # Slider mode
        identifiers = generate_element_identifier(schema_name, "confidence_level", "range")
        min_val = annotation_scheme.get("min_value", 0)
        max_val = annotation_scheme.get("max_value", 100)
        step = annotation_scheme.get("step", 1)
        left_label = annotation_scheme.get("left_label", "Not confident")
        right_label = annotation_scheme.get("right_label", "Very confident")

        html += f"""
            <div class="confidence-slider-wrapper">
                <span class="confidence-slider-label-left">{escape_html_content(left_label)}</span>
                <div class="confidence-slider-track-wrapper">
                    <input type="range"
                           min="{min_val}"
                           max="{max_val}"
                           step="{step}"
                           value="{(min_val + max_val) // 2}"
                           class="confidence-slider annotation-input"
                           id="{identifiers['id']}"
                           name="{identifiers['name']}"
                           schema="{identifiers['schema']}"
                           label_name="{identifiers['label_name']}"
                           validation="{validation}">
                    <span class="confidence-slider-value" id="confidence-val-{identifiers['id']}">
                        {(min_val + max_val) // 2}
                    </span>
                </div>
                <span class="confidence-slider-label-right">{escape_html_content(right_label)}</span>
            </div>
        """

        html += f"""
        <script>
        (function() {{
            const slider = document.getElementById("{identifiers['id']}");
            const valDisplay = document.getElementById("confidence-val-{identifiers['id']}");
            if (slider && valDisplay) {{
                slider.addEventListener('input', function() {{
                    valDisplay.textContent = this.value;
                }});
            }}
        }})();
        </script>
        """

    html += """
        </fieldset>
    </form>
    """

    key_bindings = []
    logger.info(f"Generated confidence layout for {schema_name} (type={scale_type})")
    return html, key_bindings
