"""
Image Annotation Layout

Generates a form interface for annotating images with:
- Bounding boxes (rectangular regions)
- Polygons (arbitrary shapes)
- Freeform drawing (brush strokes)
- Landmarks (point annotations)

Uses Fabric.js for canvas-based annotation with zoom/pan support.
"""

import logging
import json
from .identifier_utils import (
    safe_generate_layout,
    escape_html_content
)

logger = logging.getLogger(__name__)

# Default colors for labels if not specified
DEFAULT_COLORS = [
    "#FF6B6B",  # Red
    "#4ECDC4",  # Teal
    "#45B7D1",  # Blue
    "#96CEB4",  # Green
    "#FFEAA7",  # Yellow
    "#DDA0DD",  # Plum
    "#98D8C8",  # Mint
    "#F7DC6F",  # Gold
    "#BB8FCE",  # Purple
    "#85C1E9",  # Light Blue
]

# Valid annotation tools
VALID_TOOLS = ["bbox", "polygon", "freeform", "landmark"]


def generate_image_annotation_layout(annotation_scheme):
    """
    Generate HTML for an image annotation interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - tools: List of tools to enable (bbox, polygon, freeform, landmark)
            - labels: List of label definitions with name and optional color
            - zoom_enabled: Whether to enable zoom (default: True)
            - pan_enabled: Whether to enable pan (default: True)
            - min_annotations: Minimum required annotations (default: 0)
            - max_annotations: Maximum allowed annotations (default: null/unlimited)
            - freeform_brush_size: Brush size for freeform tool (default: 5)
            - freeform_simplify: Whether to simplify freeform paths (default: True)

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the image annotation interface
            key_bindings: List of keyboard shortcuts

    Raises:
        ValueError: If required fields are missing or invalid
    """
    return safe_generate_layout(annotation_scheme, _generate_image_annotation_layout_internal)


def _generate_image_annotation_layout_internal(annotation_scheme):
    """
    Internal function to generate image annotation layout after validation.
    """
    schema_name = annotation_scheme.get('name', 'image_annotation')
    logger.debug(f"Generating image annotation layout for schema: {schema_name}")

    # Validate required fields
    if "labels" not in annotation_scheme:
        error_msg = f"Missing labels in schema: {schema_name}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    if "tools" not in annotation_scheme:
        error_msg = f"Missing tools in schema: {schema_name}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Validate tools
    tools = annotation_scheme["tools"]
    if not isinstance(tools, list) or not tools:
        error_msg = f"tools must be a non-empty list in schema: {schema_name}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    invalid_tools = [t for t in tools if t not in VALID_TOOLS]
    if invalid_tools:
        error_msg = f"Invalid tools: {invalid_tools}. Valid tools are: {VALID_TOOLS}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Process labels with colors
    labels = _process_labels(annotation_scheme["labels"])

    # Get configuration options
    zoom_enabled = annotation_scheme.get("zoom_enabled", True)
    pan_enabled = annotation_scheme.get("pan_enabled", True)
    min_annotations = annotation_scheme.get("min_annotations", 0)
    max_annotations = annotation_scheme.get("max_annotations", None)
    freeform_brush_size = annotation_scheme.get("freeform_brush_size", 5)
    freeform_simplify = annotation_scheme.get("freeform_simplify", True)

    # AI support configuration
    ai_support = annotation_scheme.get("ai_support", {})
    ai_enabled = ai_support.get("enabled", False)

    # Build config object for JavaScript
    js_config = {
        "schemaName": schema_name,
        "tools": tools,
        "labels": labels,
        "zoomEnabled": zoom_enabled,
        "panEnabled": pan_enabled,
        "minAnnotations": min_annotations,
        "maxAnnotations": max_annotations,
        "freeformBrushSize": freeform_brush_size,
        "freeformSimplify": freeform_simplify,
        "aiSupport": ai_enabled,
        "aiFeatures": ai_support.get("features", {}) if ai_enabled else {},
    }

    # Generate HTML
    html = _generate_html(annotation_scheme, js_config, schema_name, labels, tools, ai_enabled, ai_support)

    # Generate keybindings
    keybindings = _generate_keybindings(labels, tools)

    logger.info(f"Successfully generated image annotation layout for {schema_name}")
    return html, keybindings


def _process_labels(labels_config):
    """
    Process label configuration and assign colors.

    Args:
        labels_config: List of label configs (strings or dicts)

    Returns:
        List of processed label dicts with name, color, and optional key_value
    """
    processed = []
    for i, label in enumerate(labels_config):
        if isinstance(label, str):
            processed.append({
                "name": label,
                "color": DEFAULT_COLORS[i % len(DEFAULT_COLORS)],
            })
        elif isinstance(label, dict):
            processed.append({
                "name": label.get("name", f"label_{i}"),
                "color": label.get("color", DEFAULT_COLORS[i % len(DEFAULT_COLORS)]),
                "key_value": label.get("key_value"),
            })
        else:
            processed.append({
                "name": str(label),
                "color": DEFAULT_COLORS[i % len(DEFAULT_COLORS)],
            })
    return processed


def _generate_html(annotation_scheme, js_config, schema_name, labels, tools, ai_enabled=False, ai_support=None):
    """
    Generate the HTML for the image annotation interface.
    """
    escaped_name = escape_html_content(schema_name)
    description = escape_html_content(annotation_scheme.get('description', ''))
    config_json = json.dumps(js_config)

    # Generate tool buttons
    tool_buttons = _generate_tool_buttons(tools)

    # Generate label selector
    label_selector = _generate_label_selector(labels)

    # Generate AI toolbar if enabled
    ai_toolbar_html = ""
    ai_init_script = ""
    if ai_enabled:
        ai_features = ai_support.get("features", {}) if ai_support else {}
        ai_toolbar_html = _generate_ai_toolbar(ai_features)
        ai_init_script = _generate_ai_init_script(escaped_name)

    html = f'''
    <form id="{escaped_name}" class="annotation-form image-annotation" action="/action_page.php">
        <fieldset schema="{escaped_name}">
            <legend>{description}</legend>

            <!-- Image Annotation Container -->
            <div class="image-annotation-container" data-schema="{escaped_name}" data-ai-enabled="{str(ai_enabled).lower()}">
                <!-- Toolbar -->
                <div class="image-annotation-toolbar">
                    <!-- Tool buttons -->
                    <div class="tool-group">
                        <span class="tool-group-label">Tools:</span>
                        {tool_buttons}
                    </div>

                    <!-- Label selector -->
                    <div class="label-group">
                        <span class="tool-group-label">Label:</span>
                        {label_selector}
                    </div>

                    <!-- Zoom controls -->
                    <div class="zoom-group">
                        <button type="button" class="zoom-btn" data-action="zoom-in" title="Zoom In (+)">+</button>
                        <button type="button" class="zoom-btn" data-action="zoom-out" title="Zoom Out (-)">-</button>
                        <button type="button" class="zoom-btn" data-action="zoom-fit" title="Fit to View (0)">Fit</button>
                        <button type="button" class="zoom-btn" data-action="zoom-reset" title="Reset Zoom">100%</button>
                    </div>

                    <!-- Edit controls -->
                    <div class="edit-group">
                        <button type="button" class="edit-btn" data-action="undo" title="Undo (Ctrl+Z)">Undo</button>
                        <button type="button" class="edit-btn" data-action="redo" title="Redo (Ctrl+Shift+Z)">Redo</button>
                        <button type="button" class="edit-btn delete-btn" data-action="delete" title="Delete Selected (Del)">Delete</button>
                    </div>

                    <!-- Annotation count -->
                    <div class="count-group">
                        <span class="annotation-count">Annotations: <span class="count-value">0</span></span>
                    </div>
                </div>

                {ai_toolbar_html}

                <!-- Canvas wrapper -->
                <div class="canvas-wrapper">
                    <canvas id="canvas-{escaped_name}" class="annotation-canvas"></canvas>
                </div>

                <!-- Hidden input for storing annotation data -->
                <input type="hidden"
                       name="{escaped_name}"
                       id="input-{escaped_name}"
                       class="annotation-data-input"
                       value="">
            </div>

            <!-- Initialize the annotation manager -->
            <script>
                (function() {{
                    // Wait for DOM and dependencies
                    function initWhenReady() {{
                        if (typeof ImageAnnotationManager === 'undefined') {{
                            setTimeout(initWhenReady, 100);
                            return;
                        }}
                        var container = document.querySelector('.image-annotation-container[data-schema="{escaped_name}"]');
                        if (!container) return;

                        var config = {config_json};
                        var canvasId = 'canvas-{escaped_name}';
                        var inputId = 'input-{escaped_name}';

                        // Get image URL from the instance display
                        var instanceContainer = document.getElementById('instance-text');
                        console.log('Instance container:', instanceContainer);
                        var textContent = instanceContainer ? instanceContainer.querySelector('#text-content') : null;
                        console.log('Text content element:', textContent);
                        var imageUrl = textContent ? textContent.getAttribute('data-image-url') : null;
                        console.log('Image URL from data-image-url:', imageUrl);
                        // Fallback to looking for an img element
                        if (!imageUrl) {{
                            var imgElement = instanceContainer ? instanceContainer.querySelector('img') : null;
                            imageUrl = imgElement ? imgElement.src : null;
                            console.log('Image URL from img element:', imageUrl);
                        }}

                        // Initialize manager
                        console.log('Initializing ImageAnnotationManager with canvas:', canvasId);
                        var manager = new ImageAnnotationManager(canvasId, inputId, config);

                        // Store reference on container
                        container.annotationManager = manager;

                        // Load image if available
                        if (imageUrl) {{
                            console.log('Calling loadImage with:', imageUrl);
                            manager.loadImage(imageUrl);
                        }} else {{
                            console.warn('No image URL found for annotation');
                        }}

                        // Wire up toolbar buttons
                        container.querySelectorAll('.tool-btn').forEach(function(btn) {{
                            btn.addEventListener('click', function() {{
                                var tool = this.dataset.tool;
                                manager.setTool(tool);
                                container.querySelectorAll('.tool-btn').forEach(function(b) {{
                                    b.classList.remove('active');
                                }});
                                this.classList.add('active');
                            }});
                        }});

                        container.querySelectorAll('.label-btn').forEach(function(btn) {{
                            btn.addEventListener('click', function() {{
                                var label = this.dataset.label;
                                var color = this.dataset.color;
                                manager.setLabel(label, color);
                                container.querySelectorAll('.label-btn').forEach(function(b) {{
                                    b.classList.remove('active');
                                }});
                                this.classList.add('active');
                            }});
                        }});

                        container.querySelectorAll('.zoom-btn').forEach(function(btn) {{
                            btn.addEventListener('click', function() {{
                                var action = this.dataset.action;
                                if (action === 'zoom-in') manager.zoom(1.2);
                                else if (action === 'zoom-out') manager.zoom(0.8);
                                else if (action === 'zoom-fit') manager.zoomFit();
                                else if (action === 'zoom-reset') manager.zoomReset();
                            }});
                        }});

                        container.querySelectorAll('.edit-btn').forEach(function(btn) {{
                            btn.addEventListener('click', function() {{
                                var action = this.dataset.action;
                                if (action === 'undo') manager.undo();
                                else if (action === 'redo') manager.redo();
                                else if (action === 'delete') manager.deleteSelected();
                            }});
                        }});

                        // Set default tool and label
                        var firstToolBtn = container.querySelector('.tool-btn');
                        if (firstToolBtn) firstToolBtn.click();
                        var firstLabelBtn = container.querySelector('.label-btn');
                        if (firstLabelBtn) firstLabelBtn.click();

                        // Update count display
                        manager.onAnnotationChange = function(count) {{
                            var countEl = container.querySelector('.count-value');
                            if (countEl) countEl.textContent = count;
                        }};

                        {ai_init_script}
                    }}

                    if (document.readyState === 'loading') {{
                        document.addEventListener('DOMContentLoaded', initWhenReady);
                    }} else {{
                        initWhenReady();
                    }}
                }})();
            </script>
        </fieldset>
    </form>
    '''

    return html


def _generate_ai_toolbar(ai_features):
    """
    Generate HTML for the AI assistance toolbar.
    """
    # Determine which buttons to show based on features
    detection_enabled = ai_features.get("detection", True)
    pre_annotate_enabled = ai_features.get("pre_annotate", True)
    classification_enabled = ai_features.get("classification", False)
    hint_enabled = ai_features.get("hint", True)

    buttons = []

    if detection_enabled:
        buttons.append(
            '<button type="button" class="ai-btn" data-action="detect" title="Detect objects in the image">'
            '<span class="ai-btn-icon">🔍</span> Detect</button>'
        )

    if pre_annotate_enabled:
        buttons.append(
            '<button type="button" class="ai-btn" data-action="pre_annotate" title="Auto-detect and pre-annotate all objects">'
            '<span class="ai-btn-icon">⚡</span> Auto</button>'
        )

    if classification_enabled:
        buttons.append(
            '<button type="button" class="ai-btn" data-action="classification" title="Classify selected region">'
            '<span class="ai-btn-icon">🏷️</span> Classify</button>'
        )

    if hint_enabled:
        buttons.append(
            '<button type="button" class="ai-btn" data-action="hint" title="Get a hint for annotation">'
            '<span class="ai-btn-icon">💡</span> Hint</button>'
        )

    if not buttons:
        return ""

    return f'''
                <!-- AI Assistance Toolbar -->
                <div class="ai-toolbar">
                    <div class="ai-toolbar-group">
                        <span class="ai-toolbar-label">AI Assist:</span>
                        {" ".join(buttons)}
                    </div>
                    <div class="ai-suggestion-controls" style="display: none;">
                        <span class="suggestion-count">0 suggestions</span>
                        <button type="button" class="ai-btn ai-btn-accept" data-action="accept-all" title="Accept all suggestions">
                            Accept All
                        </button>
                        <button type="button" class="ai-btn ai-btn-clear" data-action="clear" title="Clear all suggestions">
                            Clear
                        </button>
                    </div>
                    <div class="ai-loading-indicator" style="display: none;">
                        <span class="spinner"></span> Loading...
                    </div>
                </div>
                <!-- AI Tooltip Container -->
                <div class="ai-tooltip-container" style="display: none;"></div>
    '''


def _generate_ai_init_script(escaped_name):
    """
    Generate JavaScript initialization code for AI assistant.
    """
    return f'''
                        // Initialize AI assistant if enabled and VisualAIAssistantManager is available
                        if (config.aiSupport && typeof VisualAIAssistantManager !== 'undefined') {{
                            var annotationId = Array.from(document.querySelectorAll('.annotation-form')).indexOf(
                                document.getElementById('{escaped_name}')
                            );
                            container.aiAssistant = new VisualAIAssistantManager({{
                                annotationType: 'image_annotation',
                                annotationId: annotationId >= 0 ? annotationId : 0,
                                annotationManager: manager
                            }});
                        }}
    '''


def _generate_tool_buttons(tools):
    """
    Generate HTML for tool selection buttons.
    """
    tool_info = {
        "bbox": {"label": "Box", "title": "Bounding Box (B)", "icon": "□"},
        "polygon": {"label": "Polygon", "title": "Polygon (P)", "icon": "⬡"},
        "freeform": {"label": "Draw", "title": "Freeform Draw (F)", "icon": "✎"},
        "landmark": {"label": "Point", "title": "Landmark Point (L)", "icon": "◉"},
    }

    buttons = []
    for tool in tools:
        info = tool_info.get(tool, {"label": tool, "title": tool, "icon": "?"})
        buttons.append(
            f'<button type="button" class="tool-btn" data-tool="{tool}" title="{info["title"]}">'
            f'{info["icon"]} {info["label"]}</button>'
        )

    return "\n".join(buttons)


def _generate_label_selector(labels):
    """
    Generate HTML for label selection buttons.
    """
    buttons = []
    for label in labels:
        name = escape_html_content(label["name"])
        color = label["color"]
        key_hint = f' ({label["key_value"]})' if label.get("key_value") else ""
        buttons.append(
            f'<button type="button" class="label-btn" data-label="{name}" data-color="{color}" '
            f'title="{name}{key_hint}" style="--label-color: {color};">'
            f'<span class="label-color-dot" style="background-color: {color};"></span>'
            f'{name}</button>'
        )

    return "\n".join(buttons)


def _generate_keybindings(labels, tools):
    """
    Generate keybinding list for the schema.
    """
    keybindings = []

    # Tool shortcuts
    tool_keys = {
        "bbox": ("b", "Bounding Box tool"),
        "polygon": ("p", "Polygon tool"),
        "freeform": ("f", "Freeform draw tool"),
        "landmark": ("l", "Landmark point tool"),
    }
    for tool in tools:
        if tool in tool_keys:
            keybindings.append(tool_keys[tool])

    # Label shortcuts
    for label in labels:
        if label.get("key_value"):
            keybindings.append((label["key_value"], f"Select label: {label['name']}"))

    # Common shortcuts
    keybindings.extend([
        ("Del", "Delete selected"),
        ("+/-", "Zoom in/out"),
        ("0", "Fit to view"),
    ])

    return keybindings
