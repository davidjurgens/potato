"""
Pairwise Comparison Layout

Generates a form interface for comparing two items side by side.
Features include:
- Binary mode: Click on preferred tile
- Scale mode: Slider between items (-N to +N)
- Optional tie/no-preference button
- Keyboard shortcuts (1/2/0)
- Support for items_key or inline items configuration
"""

import logging
from typing import Dict, Any, Tuple, List

from potato.ai.ai_help_wrapper import get_ai_wrapper
from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_validation_attribute,
    escape_html_content,
    generate_layout_attributes
)

logger = logging.getLogger(__name__)


def generate_pairwise_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Generate HTML for a pairwise comparison interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - mode: "binary" (default) or "scale"
            - items_key: Key in instance data containing items to compare
            - items: Inline items config (alternative to items_key)
            - show_labels: Whether to show A/B labels (default: true)
            - labels: Custom labels for A/B (default: ["A", "B"])
            - allow_tie: Show tie/no-preference option (default: false)
            - tie_label: Custom tie button text (default: "No preference")
            - sequential_key_binding: Enable keyboard shortcuts (default: true)
            - label_requirement (dict): Optional validation settings

            For scale mode:
            - scale.min: Minimum value (e.g., -3 for "A much better")
            - scale.max: Maximum value (e.g., +3 for "B much better")
            - scale.step: Step increment (default: 1)
            - scale.labels.min: Label for min value
            - scale.labels.max: Label for max value
            - scale.labels.center: Label for center (default: "Equal")

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the pairwise interface
            key_bindings: List of (key, description) tuples for keyboard shortcuts
    """
    return safe_generate_layout(annotation_scheme, _generate_pairwise_layout_internal)


def _generate_pairwise_layout_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Internal function to generate pairwise layout after validation.
    """
    logger.debug(f"Generating pairwise layout for schema: {annotation_scheme['name']}")

    mode = annotation_scheme.get("mode", "binary")
    schema_name = annotation_scheme["name"]

    if mode == "scale":
        return _generate_scale_mode(annotation_scheme)
    elif mode == "multi_dimension":
        return _generate_multi_dimension_mode(annotation_scheme)
    else:
        return _generate_binary_mode(annotation_scheme)


def _generate_binary_mode(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Generate binary mode pairwise interface (clickable tiles).
    """
    schema_name = annotation_scheme["name"]
    description = annotation_scheme["description"]

    # Get configuration options
    show_labels = annotation_scheme.get("show_labels", True)
    labels = annotation_scheme.get("labels", ["A", "B"])
    if len(labels) < 2:
        labels = ["A", "B"]

    allow_tie = annotation_scheme.get("allow_tie", False)
    tie_label = annotation_scheme.get("tie_label", "No preference")

    # Get items config
    items_key = annotation_scheme.get("items_key", "text")

    # Validation attribute
    validation = generate_validation_attribute(annotation_scheme)

    # Key bindings
    key_bindings = []
    enable_keybindings = annotation_scheme.get("sequential_key_binding", True)

    # Build the HTML
    escaped_schema = escape_html_content(schema_name)
    escaped_description = escape_html_content(description)
    escaped_items_key = escape_html_content(items_key)

    # Data attributes for JavaScript initialization
    data_attrs = f'data-annotation-type="pairwise" data-schema-name="{escaped_schema}" data-mode="binary" data-items-key="{escaped_items_key}"'

    # Layout attributes for grid positioning
    layout_attrs = generate_layout_attributes(annotation_scheme)

    # Tile labels
    label_a = escape_html_content(labels[0])
    label_b = escape_html_content(labels[1])
    shortcut_a = "[1]" if enable_keybindings else ""
    shortcut_b = "[2]" if enable_keybindings else ""
    data_key_a = 'data-key="1"' if enable_keybindings else ""
    data_key_b = 'data-key="2"' if enable_keybindings else ""

    schematic = f"""
    <form id="{escaped_schema}" class="annotation-form pairwise pairwise-binary" action="/action_page.php" data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}" {data_attrs} {layout_attrs}>
        {get_ai_wrapper()}
        <fieldset schema="{escaped_schema}">
            <legend class="pairwise-question">{escaped_description}</legend>

            <!-- Compact selection tiles -->
            <div class="pairwise-selection-container">
                <div class="pairwise-tile" data-value="A" data-schema="{escaped_schema}" tabindex="0" {data_key_a}>
                    <span class="pairwise-tile-label">{label_a}</span>
                    <span class="pairwise-tile-shortcut">{shortcut_a}</span>
                </div>
                <div class="pairwise-tile" data-value="B" data-schema="{escaped_schema}" tabindex="0" {data_key_b}>
                    <span class="pairwise-tile-label">{label_b}</span>
                    <span class="pairwise-tile-shortcut">{shortcut_b}</span>
                </div>
            </div>
    """

    # Optional tie button
    if allow_tie:
        escaped_tie_label = escape_html_content(tie_label)
        shortcut_tie = "[0]" if enable_keybindings else ""
        data_key_tie = 'data-key="0"' if enable_keybindings else ""

        schematic += f"""
            <div class="pairwise-extra-options">
                <button type="button" class="pairwise-tie-btn" data-value="tie" data-schema="{escaped_schema}" {data_key_tie}>
                    {escaped_tie_label} {shortcut_tie}
                </button>
            </div>
        """

    # Hidden input for form submission
    schematic += f"""
            <input type="hidden" class="pairwise-value annotation-input"
                   name="{escaped_schema}"
                   schema="{escaped_schema}"
                   label_name="selection"
                   validation="{validation}"
                   value="">
    """

    # Add justification section if configured
    schematic += _generate_justification_html(annotation_scheme, schema_name)

    schematic += """
        </fieldset>
    </form>
    """

    # Add key bindings
    if enable_keybindings:
        key_bindings.append(("1", f"{schema_name}: {labels[0]}"))
        key_bindings.append(("2", f"{schema_name}: {labels[1]}"))
        if allow_tie:
            key_bindings.append(("0", f"{schema_name}: {tie_label}"))

    logger.info(f"Successfully generated pairwise binary layout for {schema_name}")
    return schematic, key_bindings


def _generate_scale_mode(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Generate scale mode pairwise interface (slider between items).
    """
    schema_name = annotation_scheme["name"]
    description = annotation_scheme["description"]

    # Get configuration options
    show_labels = annotation_scheme.get("show_labels", True)
    labels = annotation_scheme.get("labels", ["A", "B"])
    if len(labels) < 2:
        labels = ["A", "B"]

    # Get scale configuration
    scale_config = annotation_scheme.get("scale", {})
    min_value = scale_config.get("min", -3)
    max_value = scale_config.get("max", 3)
    step = scale_config.get("step", 1)
    default_value = scale_config.get("default", 0)

    # Scale labels
    scale_labels = scale_config.get("labels", {})
    min_label = scale_labels.get("min", f"{labels[0]} is better")
    max_label = scale_labels.get("max", f"{labels[1]} is better")
    center_label = scale_labels.get("center", "Equal")

    # Get items config
    items_key = annotation_scheme.get("items_key", "text")

    # Validation attribute
    validation = generate_validation_attribute(annotation_scheme)

    # Generate identifiers
    identifiers = generate_element_identifier(schema_name, "scale", "range")

    # Build the HTML
    escaped_schema = escape_html_content(schema_name)
    escaped_description = escape_html_content(description)
    escaped_items_key = escape_html_content(items_key)

    # Data attributes for JavaScript initialization
    data_attrs = f'data-annotation-type="pairwise" data-schema-name="{escaped_schema}" data-mode="scale" data-items-key="{escaped_items_key}"'

    # Layout attributes for grid positioning
    layout_attrs = generate_layout_attributes(annotation_scheme)

    # Escaped labels
    label_a = escape_html_content(labels[0])
    label_b = escape_html_content(labels[1])

    schematic = f"""
    <form id="{escaped_schema}" class="annotation-form pairwise pairwise-scale" action="/action_page.php" data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}" {data_attrs} {layout_attrs}>
        {get_ai_wrapper()}
        <fieldset schema="{escaped_schema}">
            <legend class="pairwise-question">{escaped_description}</legend>

            <!-- Compact rating scale slider -->
            <div class="pairwise-scale-widget">
                <div class="pairwise-scale-labels">
                    <span class="pairwise-scale-label-min">{label_a}: {escape_html_content(min_label)}</span>
                    <span class="pairwise-scale-label-center">{escape_html_content(center_label)}</span>
                    <span class="pairwise-scale-label-max">{label_b}: {escape_html_content(max_label)}</span>
                </div>
                <input type="range" class="pairwise-scale-slider annotation-input"
                       name="{escaped_schema}"
                       schema="{escaped_schema}"
                       label_name="scale_value"
                       min="{min_value}" max="{max_value}" step="{step}" value="{default_value}"
                       validation="{validation}"
                       oninput="updatePairwiseScaleDisplay(this);"
                       onchange="registerAnnotation(this);">
                <div class="pairwise-scale-value-display">
                    <span class="pairwise-scale-current-value">{default_value}</span>
                </div>
                <div class="pairwise-scale-ticks">
    """

    # Generate tick marks
    tick_values = []
    val = min_value
    while val <= max_value:
        tick_values.append(val)
        val += step

    for tick in tick_values:
        percent = ((tick - min_value) / (max_value - min_value)) * 100 if max_value != min_value else 0
        is_center = tick == 0
        tick_class = "pairwise-scale-tick center" if is_center else "pairwise-scale-tick"
        schematic += f'<span class="{tick_class}" style="left: {percent}%">{tick}</span>'

    schematic += """
                </div>
            </div>
        </fieldset>
    </form>
    """

    # No keyboard shortcuts for scale mode (uses slider)
    key_bindings = []

    logger.info(f"Successfully generated pairwise scale layout for {schema_name}")
    return schematic, key_bindings


def _generate_justification_html(annotation_scheme: Dict[str, Any], schema_name: str) -> str:
    """
    Generate justification section HTML (reason checkboxes + rationale textarea).

    Used by both binary and multi_dimension modes when ``justification`` config is present.
    """
    justification = annotation_scheme.get("justification")
    if not justification:
        return ""

    reason_categories = justification.get("reason_categories", [])
    min_chars = justification.get("min_rationale_chars", 0)
    placeholder = justification.get("rationale_placeholder", "Explain your preference...")
    required = justification.get("required", False)

    escaped_schema = escape_html_content(schema_name)

    # Reason category checkboxes
    reasons_html = ""
    for reason in reason_categories:
        escaped_reason = escape_html_content(reason)
        reasons_html += f"""
            <label><input type="checkbox" class="pairwise-reason-cb"
                   data-schema="{escaped_schema}" value="{escaped_reason}">
                {escaped_reason}</label>"""

    req_attr = 'data-required="true"' if required else ''

    html = f"""
        <div class="pairwise-justification" data-schema="{escaped_schema}" {req_attr}>
            <div class="pairwise-justification-title">Justification</div>
    """

    if reasons_html:
        html += f"""
            <div class="pairwise-reason-categories">{reasons_html}</div>
        """

    html += f"""
            <textarea class="pairwise-rationale-textarea"
                      data-schema="{escaped_schema}"
                      data-min-chars="{min_chars}"
                      placeholder="{escape_html_content(placeholder)}"
                      oninput="updatePairwiseRationaleCounter(this);"></textarea>
            <div class="pairwise-rationale-counter" data-schema="{escaped_schema}">
                0 / {min_chars} characters
            </div>
            <input type="hidden" class="annotation-input pairwise-justification-value"
                   name="{escaped_schema}:::justification"
                   schema="{escaped_schema}"
                   label_name="justification"
                   value="">
        </div>
    """
    return html


def _generate_multi_dimension_mode(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Generate multi-dimension pairwise interface.

    Each dimension gets its own A/B tile row with a dimension label.
    Hidden inputs use ``{schema}:::{dimension}`` naming.
    """
    schema_name = annotation_scheme["name"]
    description = annotation_scheme["description"]
    dimensions = annotation_scheme.get("dimensions", [])

    if not dimensions:
        raise ValueError(f"pairwise multi_dimension mode requires 'dimensions' list for schema '{schema_name}'")

    labels = annotation_scheme.get("labels", ["A", "B"])
    if len(labels) < 2:
        labels = ["A", "B"]

    items_key = annotation_scheme.get("items_key", "text")
    validation = generate_validation_attribute(annotation_scheme)
    layout_attrs = generate_layout_attributes(annotation_scheme)

    escaped_schema = escape_html_content(schema_name)
    escaped_items_key = escape_html_content(items_key)
    label_a = escape_html_content(labels[0])
    label_b = escape_html_content(labels[1])

    data_attrs = (
        f'data-annotation-type="pairwise" data-schema-name="{escaped_schema}" '
        f'data-mode="multi_dimension" data-items-key="{escaped_items_key}"'
    )

    schematic = f"""
    <form id="{escaped_schema}" class="annotation-form pairwise pairwise-multi-dimension"
          action="/action_page.php"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          {data_attrs} {layout_attrs}>
        {get_ai_wrapper()}
        <fieldset schema="{escaped_schema}">
            <legend class="pairwise-question">{escape_html_content(description)}</legend>
    """

    key_bindings = []

    for i, dim in enumerate(dimensions):
        dim_name = dim.get("name", f"dimension_{i}")
        dim_desc = dim.get("description", "")
        allow_tie = dim.get("allow_tie", annotation_scheme.get("allow_tie", False))
        tie_label = dim.get("tie_label", annotation_scheme.get("tie_label", "Tie"))

        escaped_dim = escape_html_content(dim_name)
        dim_schema_key = f"{escaped_schema}:::{escaped_dim}"

        tie_btn_html = ""
        if allow_tie:
            tie_btn_html = f"""
                <button type="button" class="pairwise-tie-btn"
                        data-value="tie" data-schema="{escaped_schema}"
                        data-dimension="{escaped_dim}">
                    {escape_html_content(tie_label)}
                </button>"""

        schematic += f"""
            <div class="pairwise-dimension-row" data-dimension="{escaped_dim}">
                <div class="pairwise-dimension-label">{escape_html_content(dim_name.replace('_', ' ').title())}</div>
                <div class="pairwise-dimension-description">{escape_html_content(dim_desc)}</div>
                <div class="pairwise-dimension-tiles">
                    <div class="pairwise-tile" data-value="A" data-schema="{escaped_schema}"
                         data-dimension="{escaped_dim}" tabindex="0">
                        <span class="pairwise-tile-label">{label_a}</span>
                    </div>
                    <div class="pairwise-tile" data-value="B" data-schema="{escaped_schema}"
                         data-dimension="{escaped_dim}" tabindex="0">
                        <span class="pairwise-tile-label">{label_b}</span>
                    </div>
                    {tie_btn_html}
                </div>
                <input type="hidden" class="pairwise-value annotation-input pairwise-dim-input"
                       name="{dim_schema_key}"
                       schema="{escaped_schema}"
                       label_name="{escaped_dim}"
                       data-dimension="{escaped_dim}"
                       validation="{validation}"
                       value="">
            </div>
        """

    # Add justification section if configured
    schematic += _generate_justification_html(annotation_scheme, schema_name)

    schematic += """
        </fieldset>
    </form>
    """

    logger.info(f"Successfully generated pairwise multi_dimension layout for {schema_name}")
    return schematic, key_bindings
