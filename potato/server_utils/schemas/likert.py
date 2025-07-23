"""
Likert Scale Layout

Generates a likert scale rating interface with radio buttons arranged horizontally.
Each button represents a point on the scale between min_label and max_label.

This module provides functionality for creating HTML-based Likert scale interfaces
that can be used for collecting ordinal data responses. The scale supports:
- Customizable number of points
- Optional numeric display
- Keyboard shortcuts
- Required/optional validation
- Bad text option for invalid inputs
"""

import logging

logger = logging.getLogger(__name__)

def generate_likert_layout(annotation_scheme):
    print("using likert")
    print(annotation_scheme)
    """
    Generate HTML for a likert scale annotation interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - size: Number of scale points
            - min_label: Label for minimum value
            - max_label: Label for maximum value
            - sequential_key_binding: Enable number key bindings (1-9)
            - displaying_score: Show numeric values on buttons
            - label_requirement: Validation settings
                - required (bool): Whether response is mandatory
            - bad_text_label (dict): Optional configuration for invalid text option
                - label_content (str): Label text for bad text option
            - annotation_id (int): match the config schema index

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the likert scale interface
            key_bindings: List of (key, description) tuples for keyboard shortcuts

    Raises:
        Exception: If required fields are missing from annotation_scheme
    """
    logger.debug(f"Generating likert layout for schema: {annotation_scheme['name']}")

    # Use radio layout if complex labels specified
    if "labels" in annotation_scheme:
        logger.info(f"Complex labels detected for {annotation_scheme['name']}, using radio layout")
        return generate_radio_layout(annotation_scheme, horizontal=False)

    # Validate required fields
    required_fields = ["size", "min_label", "max_label"]
    for required in required_fields:
        if required not in annotation_scheme:
            error_msg = f'Likert scale for "{annotation_scheme["name"]}" missing required field: {required}'
            logger.error(error_msg)
            raise Exception(error_msg)

    logger.debug(f"Creating {annotation_scheme['size']}-point likert scale")

    # Setup validation and key bindings
    key_bindings = []
    validation = ""
    if annotation_scheme.get("label_requirement", {}).get("required"):
        validation = "required"
        logger.debug(f"Setting required validation for {annotation_scheme['name']}")

    # Initialize styles and container
    schematic = f"""
    <style>

        .shadcn-likert-container {{
            border: 1px solid #E5E5EA;
            border-radius: 18px 0 18px 18px;
            padding: 1rem;
            display: flex;
            flex-direction: column;
            align-items: center;
            width: fit-content;
            max-width: 100%;
            margin: 1.5rem auto;
            font-family: ui-sans-serif, system-ui, sans-serif;
            position: relative;
        }}

        .shadcn-likert-title {{
            font-size: 1rem;
            font-weight: 500;
            color: black;
            text-align: left;
            width: 100%;
        }}

        .shadcn-likert-scale {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            width: 100%;
        }}

        .shadcn-likert-endpoint {{
            display: flex;
            align-items: center;
            height: 2.5rem;
            flex: 0 0 auto;
            font-size: 0.875rem;
            color: var(--muted-foreground);
            padding: 0 0.5rem;
            max-width: 30%;
            text-align: center;
            word-wrap: break-word;
            overflow-wrap: break-word;
            hyphens: auto;
        }}

        .shadcn-likert-options {{
            display: flex;
            flex: 1;
            justify-content: space-between;
            position: relative;
            padding: 0 0.5rem;
            gap: 0.5rem;
        }}

        .shadcn-likert-track {{
            position: absolute;
            height: 2px;
            background-color: var(--border);
            left: 0.5rem;
            right: 0.5rem;
            top: 0.625rem;
            transform: none;
            z-index: 0;
        }}

        .shadcn-likert-option {{
            display: flex;
            flex-direction: column;
            align-items: center;
            position: relative;
            z-index: 1;
        }}

        .shadcn-likert-input {{
            opacity: 0;
            position: absolute;
            width: 0;
            height: 0;
        }}

        .shadcn-likert-button {{
            width: 1.25rem;
            height: 1.25rem;
            border-radius: 50%;
            background-color: var(--secondary);
            border: 2px solid var(--border);
            margin-bottom: 0.5rem;
            cursor: pointer;
            transition: var(--transition);
        }}

        .shadcn-likert-input:checked + .shadcn-likert-button {{
            background-color: var(--primary);
            border-color: var(--primary);
            transform: scale(1.1);
            box-shadow: 0 0 0 3px rgba(110, 86, 207, 0.2);
        }}

        .shadcn-likert-input:focus + .shadcn-likert-button {{
            box-shadow: 0 0 0 3px rgba(110, 86, 207, 0.2);
        }}

        .shadcn-likert-input:hover + .shadcn-likert-button {{
            border-color: var(--primary);
        }}

        .shadcn-likert-label {{
            font-size: 0.75rem;
            color: var(--muted-foreground);
            margin-top: 0.25rem;
            text-align: center;
        }}

        .shadcn-likert-input:checked ~ .shadcn-likert-label {{
            color: var(--primary);
            font-weight: 500;
        }}

        .shadcn-likert-bad-text {{
            display: flex;
            align-items: center;
            margin-top: 0.75rem;
            padding: 0.5rem 0;
        }}

        .shadcn-likert-bad-text-label {{
            margin-left: 0.5rem;
            font-size: 0.875rem;
            color: var(--text-color);
            word-wrap: break-word;
            overflow-wrap: break-word;
            flex: 1;
        }}

        fieldset[schema] {{
            width: fit-content;
            max-width: 100%;
            overflow: visible;
        }}

        .ai-help {{
            width: 9.375rem;
            height: 2.063rem;
            border: 1px solid #E5E5EA;
            border-radius: 18px;
            position: absolute;
            top: -0.75rem;
            right: -0.05rem;
            background-color: white;
            display: flex; 
            justify-content: center;
            align-items: center;
        }}
        
        .ai-help-word {{
            font-size: 1rem;
            margin: 0;
        }}

        .hint {{
            cursor: pointer;
        }}

        .hint:hover {{
            color: #6E56CF;
        }}

        .tooltip {{
            position: absolute;
            top: 120%;
            left: 50%;
            transform: translateX(-50%);
            background-color: white;
            padding: 1rem;
            border-radius: .5rem;
            white-space: nowrap;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            z-index: 1000;
            opacity: 0;       
            visibility: hidden; 
            transition: opacity 0.3s, visibility 0.3s;
            min-width: 20rem;
            max-width: 24rem; 
            overflow-wrap: break-word;
            word-wrap: break-word;
            white-space: normal; 
            max-height: 15rem;
            overflow: auto;
        }}

        .tooltip.active {{
            opacity: 1;
            visibility: visible;
        }}

        .reasoning {{
            font-weight: bold;
        }}

        .tooltip-text{{
            margin: 0;
        }}

    </style>

    <form id="{annotation_scheme['name']}" class="annotation-form likert shadcn-likert-container" action="/action_page.php" data-annotation-id="{annotation_scheme["annotation_id"]}">
        <div class="ai-help">
    <h3 class="ai-help-word"><span class="hint">Hint</span> | <span>Keyword</span></h3>
    <div class="tooltip"> 
            <p class="tooltip-text">
                <span class="reasoning">Reasoning:</span> {{ai}} 
            </p>
        </div>
    </div>


        <fieldset schema="{annotation_scheme['name']}" style="border: none; padding: 0; margin: 0; width: auto; min-width: fit-content;">
            <legend class="shadcn-likert-title">{annotation_scheme['description']}</legend>
            <div class="shadcn-likert-scale" style="max-width: min(100%, calc(300px + {annotation_scheme['size']} * 40px + 250px));">
                <div class="shadcn-likert-endpoint">{annotation_scheme['min_label']}</div>
                <div class="shadcn-likert-options">
                    <div class="shadcn-likert-track"></div>
    """

    # Generate scale points
    for i in range(1, annotation_scheme["size"] + 1):
        label = f"{i}"
        name = f"{annotation_scheme['name']}:::{label}"
        key_value = str(i % 10)

        # Handle key bindings for scales with less than 10 points
        if (annotation_scheme.get("sequential_key_binding")
            and annotation_scheme["size"] < 10):
            key_bindings.append((key_value, f"{annotation_scheme['name']}: {key_value}"))
            logger.debug(f"Added key binding '{key_value}' for point {i}")

        # Format label content - show numbers if displaying_score is enabled
        label_content = str(i) if annotation_scheme.get("displaying_score") else ""

        # Generate radio input for each scale point
        schematic += f"""
                    <div class="shadcn-likert-option">
                        <input class="{annotation_scheme['name']} shadcn-likert-input"
                               type="radio"
                               id="{name}"
                               name="{name}"
                               value="{key_value}"
                               schema="{annotation_scheme['name']}"
                               label_name="{key_value}"
                               selection_constraint="single"
                               validation="{validation}"
                               onclick="onlyOne(this);registerAnnotation(this);">
                        <label class="shadcn-likert-button" for="{name}"></label>
                        {f'<span class="shadcn-likert-label">{label_content}</span>' if label_content else ''}
                    </div>
        """

    # Add max label to complete the scale
    schematic += f"""
                </div>
                <div class="shadcn-likert-endpoint">{annotation_scheme['max_label']}</div>
            </div>
    """

    # Add optional bad text input for invalid/problematic cases
    if "label_content" in annotation_scheme.get("bad_text_label", {}):
        logger.debug(f"Adding bad text option for {annotation_scheme['name']}")
        name = f"{annotation_scheme['name']}:::bad_text"
        schematic += f"""
            <div class="shadcn-likert-bad-text" style="width: 100%;">
                <input class="{annotation_scheme['name']} shadcn-likert-input"
                       type="radio"
                       id="{name}"
                       name="{name}"
                       value="0"
                       validation="{validation}"
                       onclick="onlyOne(this);registerAnnotation(this);">
                <label class="shadcn-likert-button" for="{name}"></label>
                <span class="shadcn-likert-bad-text-label">
                    {annotation_scheme['bad_text_label']['label_content']}
                </span>
            </div>
        """
    schematic += """
        </fieldset></form>
    """
    
    logger.info(f"Successfully generated likert layout for {annotation_scheme['name']} "
                f"with {annotation_scheme['size']} points")
    return schematic, key_bindings
