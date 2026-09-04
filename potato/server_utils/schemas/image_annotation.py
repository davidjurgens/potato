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

from potato import model_zoo
from .identifier_utils import (
    safe_generate_layout,
    escape_html_content,
    generate_layout_attributes,
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
#: Segmentation models the schema will accept, straight from the model zoo.
#: Sourced rather than duplicated: a second hand-maintained list is how
#: `VALID_TOOLS` ended up defined in two files disagreeing with each other.
#: The zoo imports nothing heavier than dataclasses, so config validation —
#: which runs on every boot — pays nothing for this.
VALID_SEGMENTATION_MODELS = tuple(
    spec.key for spec in model_zoo.by_task(
        model_zoo.ModelTask.INTERACTIVE_SEGMENTATION))

DEFAULT_SEGMENTATION_MODEL = model_zoo.DEFAULT_BY_TASK[
    model_zoo.ModelTask.INTERACTIVE_SEGMENTATION]

#: Detectors the text-prompt box will accept.
VALID_TEXT_PROMPT_MODELS = tuple(
    spec.key for spec in model_zoo.by_task(model_zoo.ModelTask.TEXT_DETECTION))

DEFAULT_TEXT_PROMPT_MODEL = model_zoo.DEFAULT_BY_TASK[
    model_zoo.ModelTask.TEXT_DETECTION]


def _segmentation_config(annotation_scheme, tools):
    """
    Client config for the magic-wand tool, or None when it is not configured.

    Returning None rather than a disabled-looking dict matters: the client uses
    its presence to decide whether to load a 13 MB runtime at all.
    """
    if "sam" not in (tools or []):
        return None

    raw = annotation_scheme.get("segmentation") or {}
    model = raw.get("model", DEFAULT_SEGMENTATION_MODEL)
    if model not in VALID_SEGMENTATION_MODELS:
        logger.warning(
            "Unknown segmentation model %r; falling back to %s. Valid models: %s",
            model, DEFAULT_SEGMENTATION_MODEL,
            ", ".join(VALID_SEGMENTATION_MODELS))
        model = DEFAULT_SEGMENTATION_MODEL

    return {
        "model": model,
        # Served by the /models route, not /static: the weights live outside
        # the package's static tree because they are a per-install download.
        "modelBaseUrl": raw.get("model_base_url", "/models"),
        "runtimeUrl": raw.get("runtime_url",
                              "/models/onnxruntime/ort.wasm.min.js"),
        "wasmBaseUrl": raw.get("wasm_base_url", "/models/onnxruntime/"),
        # How many image embeddings to keep. Each is ~4 MB, so the default
        # trades ~16 MB for never re-encoding an image the annotator revisits.
        "embeddingLimit": int(raw.get("embedding_limit", 4)),
    }


def _text_prompt_config(annotation_scheme):
    """
    Client config for the text-prompt box, or None when it is off.

    Off by default and returning None rather than a disabled dict, for the same
    reason segmentation does: the client uses presence to decide whether to
    fetch 145 MB of detector. A project that never asked for open-vocabulary
    labelling must never pay for it.
    """
    raw = annotation_scheme.get("text_prompt")
    if not raw:
        return None
    if isinstance(raw, bool):
        raw = {}
    if raw.get("enabled") is False:
        return None

    model = raw.get("model", DEFAULT_TEXT_PROMPT_MODEL)
    if model not in VALID_TEXT_PROMPT_MODELS:
        logger.warning(
            "Unknown text-prompt model %r; falling back to %s. Valid models: %s",
            model, DEFAULT_TEXT_PROMPT_MODEL,
            ", ".join(VALID_TEXT_PROMPT_MODELS))
        model = DEFAULT_TEXT_PROMPT_MODEL

    # Everything the browser needs to run this model comes from the zoo, so a
    # model swap is one registry edit rather than a hunt through JavaScript.
    config = model_zoo.client_config(
        model, raw.get("model_base_url", "/models"))

    # A project may override the thresholds; the model's own defaults stand
    # otherwise. Named `box_threshold` / `text_threshold` because that is what
    # the Grounding DINO literature calls them, and an annotator reading a
    # paper should find the same words in the config.
    for key in ("box_threshold", "text_threshold"):
        if key in raw:
            config[key] = float(raw[key])

    return {
        "model": model,
        "config": config,
        # Phrases the prompt box starts with. Handy for a study where every
        # annotator should search the same vocabulary.
        "phrases": [str(p) for p in (raw.get("phrases") or [])],
        # When true, an accepted box is handed to the SAM decoder and stored as
        # a mask instead. Needs the `sam` tool, so it is refused without it —
        # silently storing boxes when a project asked for masks would be worse.
        "segment": bool(raw.get("segment", False)),
        "runtimeUrl": raw.get("runtime_url",
                              "/models/onnxruntime/ort.wasm.min.js"),
        "wasmBaseUrl": raw.get("wasm_base_url", "/models/onnxruntime/"),
    }


#: Viewers an image_annotation schema can use. `fabric` draws the whole image
#: on the canvas; `deepzoom` serves a tile pyramid and is what makes a source
#: larger than a browser can hold annotatable at all.
VALID_VIEWERS = ["fabric", "deepzoom"]

VALID_TOOLS = ["bbox", "polygon", "polyline", "ellipse", "freeform", "landmark",
               "keypoint_set", "cuboid_2d", "fill", "eraser", "brush",
               # Interactive segmentation. Needs a downloaded model; the tool
               # renders regardless and reports what is missing, because a
               # button that silently does nothing is worse than an error.
               "sam"]


# Tool keyboard shortcuts, by profile.
#
# "v7" matches the conventions V7 Darwin and CVAT use, so an annotator moving
# from either is productive immediately: b=brush, e=eraser, f=fill, r=rectangle,
# k=keypoint, plus [ and ] for brush size. "legacy" preserves the bindings
# Potato shipped before, for projects already collecting data whose annotators
# have trained muscle memory.
#
# Adding a tool means adding it to BOTH profiles; the unit tests assert that.
KEYBINDING_PROFILES = {
    "v7": {
        "brush": "b",
        "eraser": "e",
        "fill": "f",
        "bbox": "r",       # r for rectangle
        "polygon": "p",
        "landmark": "k",   # k for keypoint
        "freeform": "d",   # d for draw; V7 has no direct equivalent
        "polyline": "n",   # CVAT's polyline key
        "ellipse": "i",    # CVAT uses ellipse; e is already the eraser
        "keypoint_set": "s",  # s for skeleton; k is the single keypoint
        "cuboid_2d": "c",
        "sam": "w",        # w for wand; free in both profiles
    },
    "legacy": {
        "bbox": "b",
        "polygon": "p",
        "freeform": "f",
        "landmark": "l",
        "brush": "m",
        "fill": "g",
        "eraser": "e",
        "polyline": "n",
        "ellipse": "i",
        "keypoint_set": "s",
        "cuboid_2d": "c",
        "sam": "w",
    },
}

DEFAULT_KEYBINDING_PROFILE = "v7"

#: Shortcuts that are the same in every profile.
COMMON_KEYBINDINGS = {
    "select": "v",
    "hide": "h",
    "brush_size_down": "[",
    "brush_size_up": "]",
}


def get_tool_keys(profile: str = DEFAULT_KEYBINDING_PROFILE) -> dict:
    """Return the {tool: key} map for a keybinding profile."""
    return dict(KEYBINDING_PROFILES.get(profile, KEYBINDING_PROFILES[DEFAULT_KEYBINDING_PROFILE]))


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

    # Segmentation mask configuration
    brush_size = annotation_scheme.get("brush_size", 20)
    eraser_size = annotation_scheme.get("eraser_size", 20)
    mask_opacity = annotation_scheme.get("mask_opacity", 0.5)

    # Fill behaviour. "region" grows across pixels of similar colour in the
    # source image (what a fill tool is normally expected to do); "empty" grows
    # across unpainted mask area regardless of image content, which is useful
    # for closing a hole inside an existing mask.
    fill_mode = annotation_scheme.get("fill_mode", "region")
    fill_tolerance = annotation_scheme.get("fill_tolerance", 32)
    fill_max_pixels = annotation_scheme.get("fill_max_pixels", 4000000)

    # AI support configuration
    ai_support = annotation_scheme.get("ai_support", {})
    ai_enabled = ai_support.get("enabled", False)

    # source_field: Links this annotation schema to a display field from instance_display
    source_field = annotation_scheme.get("source_field", "")

    # Keyboard profile. Defaults to V7/CVAT conventions; projects already
    # collecting data set "legacy" to keep the bindings their annotators learned.
    keybinding_profile = annotation_scheme.get(
        "keybinding_profile", DEFAULT_KEYBINDING_PROFILE)
    tool_keys = get_tool_keys(keybinding_profile)

    # viewer: "fabric" (default) draws the whole image on the canvas;
    # "deepzoom" serves a tile pyramid through OpenSeadragon, which is the only
    # way to annotate a source too large to send to a browser as one file.
    viewer = str(annotation_scheme.get("viewer", "fabric")).lower()
    if viewer not in VALID_VIEWERS:
        raise ValueError(
            f"Invalid viewer {viewer!r} in schema {schema_name!r}. "
            f"Valid viewers are: {VALID_VIEWERS}")
    tiles_cfg = annotation_scheme.get("tiles") or {}
    tile_options = {
        "tileSize": int(tiles_cfg.get("tile_size") or 254),
        "overlap": int(tiles_cfg.get("overlap")
                       if tiles_cfg.get("overlap") is not None else 1),
        "maxPixels": int(tiles_cfg.get("max_pixels") or 640000000),
        "page": int(tiles_cfg.get("page") or 0),
        "showNavigator": bool(tiles_cfg.get("navigator", True)),
    }

    # carry_over: false | "prompt" | "auto"
    #   false   - no carry-over at all (default; the previous item is arbitrary
    #             unless the data is a sequence)
    #   prompt  - show a "Copy previous" button the annotator can press
    #   auto    - additionally pre-fill on load when the item has no annotations
    carry_over = annotation_scheme.get("carry_over", False)
    if carry_over is True:
        carry_over = "prompt"

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
        "brushSize": brush_size,
        "eraserSize": eraser_size,
        "maskOpacity": mask_opacity,
        "fillMode": fill_mode,
        "fillTolerance": fill_tolerance,
        "fillMaxPixels": fill_max_pixels,
        # The client reads its shortcuts from here rather than hardcoding a
        # switch, so a profile change is a config change and the two can never
        # drift from the tooltips and the docs table.
        "viewer": viewer,
        "tiles": tile_options,
        "keybindingProfile": keybinding_profile,
        "toolKeys": tool_keys,
        "commonKeys": COMMON_KEYBINDINGS,
        "carryOver": carry_over,
        "aiSupport": ai_enabled,
        "aiFeatures": ai_support.get("features", {}) if ai_enabled else {},
        "sourceField": source_field,
        "skeletons": annotation_scheme.get("skeletons", {}) or {},
        "maskMode": annotation_scheme.get("mask_mode", "semantic"),
        # Interactive segmentation. Only meaningful when the `sam` tool is
        # configured; the client checks that before loading anything, so a
        # project without it never fetches the runtime.
        "segmentation": _segmentation_config(annotation_scheme, tools),
        # Open-vocabulary detection from a typed phrase. Independent of the
        # `sam` tool: a project can have text prompting without click-to-
        # segment, or both, and asking for masks needs both.
        "textPrompt": _text_prompt_config(annotation_scheme),
    }

    if js_config["textPrompt"] and js_config["textPrompt"]["segment"] \
            and "sam" not in tools:
        logger.warning(
            "text_prompt.segment is on but the 'sam' tool is not configured, "
            "so there is no decoder to turn a box into a mask. Detections will "
            "be stored as boxes. Add 'sam' to tools to get masks.")
        js_config["textPrompt"]["segment"] = False

    # Generate HTML
    html = _generate_html(annotation_scheme, js_config, schema_name, labels, tools, ai_enabled, ai_support)

    # Generate keybindings
    keybindings = _generate_keybindings(labels, tools, tool_keys, schema_name,
                                        carry_over)

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
    # The grid reads data-grid-columns; without this the scheme's
    # `layout:` block is silently discarded and it renders at one column.
    layout_attrs = generate_layout_attributes(annotation_scheme)
    escaped_name = escape_html_content(schema_name)

    # Read from js_config rather than the scheme: the validation and the
    # defaulting both happened there, and re-reading the raw scheme here is how
    # a template and its client config come to disagree about which viewer is
    # in use.
    viewer = (js_config or {}).get("viewer", "fabric")
    deepzoom_class = " deepzoom" if viewer == "deepzoom" else ""
    deepzoom_host_html = (
        f'<div id="deepzoom-{escaped_name}" class="deepzoom-host"'
        f' aria-hidden="true"></div>' if viewer == "deepzoom" else "")
    description = escape_html_content(annotation_scheme.get('description', ''))
    config_json = json.dumps(js_config)

    # source_field attribute for linking to display fields
    source_field = annotation_scheme.get("source_field", "")
    source_field_attr = f' data-source-field="{escape_html_content(source_field)}"' if source_field else ""

    # Generate tool buttons, with key hints from the active profile.
    tool_buttons = _generate_tool_buttons(tools, js_config.get("toolKeys"))
    segmentation_html = _generate_segmentation_controls(
        js_config.get("segmentation"), escaped_name)
    text_prompt_html = _generate_text_prompt_controls(
        js_config.get("textPrompt"), escaped_name)

    # Carry-over ("copy from previous image") is off unless asked for: on an
    # unordered image set the previous item is arbitrary and the button would
    # invite nonsense. It earns its place on sequences -- video frames,
    # satellite time series, z-stacks.
    carry_over_button = ""
    if js_config.get("carryOver") in ("prompt", "auto"):
        carry_over_button = (
            '<button type="button" class="edit-btn carry-over-btn" '
            'data-action="carry-over" '
            'title="Copy annotations from the previous image (Ctrl+D)">'
            'Copy previous</button>'
        )

    # Generate label selector
    label_selector = _generate_label_selector(labels)

    # Generate AI toolbar if enabled.
    #
    # The TOOLBAR is server-backed — every button on it calls an endpoint — so
    # it appears only when this project configured one. The INIT SCRIPT is not:
    # it builds the accept/reject review panel, which text prompting needs even
    # with no server-side AI anywhere, because that model runs in the browser.
    ai_toolbar_html = ""
    ai_init_script = ""
    if ai_enabled:
        ai_features = ai_support.get("features", {}) if ai_support else {}
        ai_toolbar_html = _generate_ai_toolbar(ai_features)
    if ai_enabled or js_config.get("textPrompt"):
        ai_init_script = _generate_ai_init_script(escaped_name)

    html = f'''
    <form id="{escaped_name}" class="annotation-form image-annotation" action="javascript:void(0)" data-annotation-type="image_annotation" data-schema-name="{escaped_name}" {layout_attrs}{source_field_attr}>
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
                        {carry_over_button}
                    </div>

                    <!-- Brush size control (shown when brush/eraser selected).
                         The readout is aria-live because [ and ] change the size
                         from anywhere on the page: without it a screen-reader
                         user resizing the brush gets no feedback at all
                         (WCAG 4.1.3). The label is a real <label for=...> so the
                         slider has a programmatic name, not just a title. -->
                    <div class="brush-size-group" style="display: none;">
                        <label class="tool-group-label" for="brush-size-{escaped_name}">Size:</label>
                        <input type="range" id="brush-size-{escaped_name}" class="brush-size-slider"
                               min="1" max="100" value="20"
                               aria-describedby="brush-size-value-{escaped_name}"
                               title="Brush size (adjust with [ and ])">
                        <span class="brush-size-value" id="brush-size-value-{escaped_name}"
                              aria-live="polite" aria-atomic="true">20</span>
                    </div>

                    {segmentation_html}

                    {text_prompt_html}

                    <!-- Annotation count -->
                    <div class="count-group">
                        <!-- aria-live: drawing and deleting are otherwise
                             confirmed only visually, on a canvas a screen
                             reader cannot see at all. -->
                        <span class="annotation-count" aria-live="polite" aria-atomic="true">Annotations: <span class="count-value">0</span></span>
                    </div>
                </div>

                {ai_toolbar_html}

                <!-- Canvas wrapper -->
                <div class="canvas-wrapper{deepzoom_class}">
                    <!-- The tiled image renders here, BEHIND the fabric canvas.
                         Present only under `viewer: deepzoom`; the ordinary
                         viewer draws its image on the canvas itself. -->
                    {deepzoom_host_html}
                    <!-- role/aria-label/tabindex give the drawing surface an
                         identity: without them the entire annotation area is
                         unreachable by keyboard and unannounced by assistive
                         tech, even though the tool hotkeys work. -->
                    <canvas id="canvas-{escaped_name}" class="annotation-canvas"
                            role="application" tabindex="0"
                            aria-label="Image annotation canvas. Use the tool buttons above, or the keyboard shortcuts listed on each tool, to draw and edit annotations."></canvas>
                    <!-- Mask canvas for segmentation (overlaid on top) -->
                    <canvas id="mask-canvas-{escaped_name}" class="mask-canvas" aria-hidden="true" style="display: none;"></canvas>
                </div>

                <!-- Hidden input for storing annotation data -->
                <input type="hidden"
                       name="{escaped_name}"
                       id="input-{escaped_name}"
                       class="annotation-data-input"
                       value="">
                <!-- Hidden input for storing mask data (RLE encoded) -->
                <input type="hidden"
                       name="{escaped_name}_masks"
                       id="mask-input-{escaped_name}"
                       class="mask-data-input"
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
                        // Priority: 1) data-image-url on #text-content, 2) img src, 3) text content itself
                        var instanceContainer = document.getElementById('instance-text');
                        console.log('[ImageAnnotation] Instance container:', instanceContainer);
                        var textContent = instanceContainer ? instanceContainer.querySelector('#text-content') : null;
                        console.log('[ImageAnnotation] Text content element:', textContent);

                        var imageUrl = null;

                        // The template stamps data-image-url with the rendered
                        // instance whether or not that instance is a URL. On an
                        // annotation page it is (text_key points at the image
                        // field); on a phase page -- training, consent, a survey
                        // -- it can be the practice question's prose, and taking
                        // it on faith made the canvas fetch a sentence and blame
                        // CORS. Every candidate is shape-checked before use.
                        function looksLikeImageUrl(value) {{
                            if (!value) return false;
                            var v = String(value).trim();
                            if (!v || /\\s/.test(v) || v.indexOf('<') !== -1) return false;
                            if (/^(https?:\\/\\/|data:image\\/|blob:|file:\\/\\/)/i.test(v)) return true;
                            // Relative and rooted paths: require an image extension so
                            // a bare word is not mistaken for a filename.
                            return /^[.\\/]?[^?#]*\\.(jpg|jpeg|png|gif|webp|svg|bmp|tif|tiff|avif)(\\?|#|$)/i.test(v);
                        }}

                        // Method 1: Check data-image-url attribute (set by template when has_image_annotation=true)
                        if (textContent) {{
                            var declaredUrl = textContent.getAttribute('data-image-url');
                            if (looksLikeImageUrl(declaredUrl)) {{
                                imageUrl = declaredUrl;
                                console.log('[ImageAnnotation] Found URL from data-image-url:', imageUrl);
                            }} else if (declaredUrl) {{
                                console.log('[ImageAnnotation] Ignoring non-URL data-image-url:', declaredUrl);
                            }}
                        }}

                        // Method 2: Fallback to looking for an img element with data-source-url or src
                        if (!imageUrl && instanceContainer) {{
                            var imgElement = instanceContainer.querySelector('img');
                            if (imgElement) {{
                                imageUrl = imgElement.getAttribute('data-source-url') || imgElement.src;
                                console.log('[ImageAnnotation] Found URL from img element:', imageUrl);
                            }}
                        }}

                        // Method 3: If text content looks like a URL, use it directly
                        if (!imageUrl && textContent) {{
                            var textVal = textContent.textContent.trim();
                            if (looksLikeImageUrl(textVal)) {{
                                imageUrl = textVal;
                                console.log('[ImageAnnotation] Found URL from text content:', imageUrl);
                            }}
                        }}

                        // Method 4: Check source_field in instance data (via display fields)
                        if (!imageUrl && config.sourceField) {{
                            var displayFields = document.querySelectorAll('[data-field-key="' + config.sourceField + '"]');
                            displayFields.forEach(function(field) {{
                                var url = field.getAttribute('data-source-url') || field.getAttribute('src');
                                if (url && !imageUrl) {{
                                    imageUrl = url;
                                    console.log('[ImageAnnotation] Found URL from source_field display:', imageUrl);
                                }}
                            }});
                        }}

                        if (!imageUrl) {{
                            console.error('[ImageAnnotation] No image URL found! Check that the instance data contains an image URL.');
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
                            // Say what actually happened. Falling through silently
                            // left an empty canvas that reads as a broken tool.
                            if (typeof manager._showCanvasMessage === 'function') {{
                                manager._showCanvasMessage(
                                    'No image URL for this item. Check that the item data has an image URL '
                                    + 'under text_key or source_field.');
                            }}
                        }}

                        // Wire up toolbar buttons
                        container.querySelectorAll('.tool-btn').forEach(function(btn) {{
                            btn.addEventListener('click', function() {{
                                var tool = this.dataset.tool;
                                manager.setTool(tool);
                                container.querySelectorAll('.tool-btn').forEach(function(b) {{
                                    b.classList.remove('active');
                                    b.setAttribute('aria-pressed', 'false');
                                }});
                                this.classList.add('active');
                                this.setAttribute('aria-pressed', 'true');

                                // Show/hide brush size control for brush/eraser tools
                                var brushSizeGroup = container.querySelector('.brush-size-group');
                                if (brushSizeGroup) {{
                                    brushSizeGroup.style.display = (tool === 'brush' || tool === 'eraser') ? 'flex' : 'none';
                                }}
                                var segGroup = container.querySelector('.segmentation-group');
                                if (segGroup) {{
                                    segGroup.style.display = (tool === 'sam') ? 'flex' : 'none';
                                }}
                            }});
                        }});

                        // Interactive segmentation controls. The buttons stay
                        // disabled until a preview actually exists, so Accept
                        // can never commit nothing.
                        var segAccept = container.querySelector('.segmentation-accept');
                        var segCancel = container.querySelector('.segmentation-cancel');
                        function syncSegButtons() {{
                            var has = !!(manager.samTool && manager.samTool.hasPreview());
                            if (segAccept) segAccept.disabled = !has;
                            if (segCancel) segCancel.disabled = !has;
                        }}
                        manager.onSegmentationStatus = syncSegButtons;
                        if (segAccept) {{
                            segAccept.addEventListener('click', function() {{
                                manager.acceptSegmentation();
                                syncSegButtons();
                            }});
                        }}
                        if (segCancel) {{
                            segCancel.addEventListener('click', function() {{
                                manager.cancelSegmentation();
                                syncSegButtons();
                            }});
                        }}
                        document.addEventListener('keydown', function(e) {{
                            if (manager.currentTool !== 'sam') return;
                            // Same text-field guard every other handler uses:
                            // Enter in a free-text answer must not commit a mask.
                            var el = document.activeElement || {{}};
                            if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA'
                                || el.tagName === 'SELECT' || el.isContentEditable === true) {{
                                return;
                            }}
                            if (e.key === 'Enter' && manager.samTool
                                && manager.samTool.hasPreview()) {{
                                e.preventDefault();
                                manager.acceptSegmentation();
                                syncSegButtons();
                            }} else if (e.key === 'Escape' && manager.samTool) {{
                                manager.cancelSegmentation();
                                syncSegButtons();
                            }}
                        }});

                        // Wire up brush size slider
                        var brushSlider = container.querySelector('.brush-size-slider');
                        var brushSizeValue = container.querySelector('.brush-size-value');
                        if (brushSlider) {{
                            brushSlider.addEventListener('input', function() {{
                                var size = parseInt(this.value);
                                if (brushSizeValue) brushSizeValue.textContent = size;
                                manager.setBrushSize(size);
                            }});
                        }}

                        container.querySelectorAll('.label-btn').forEach(function(btn) {{
                            btn.addEventListener('click', function() {{
                                var label = this.dataset.label;
                                var color = this.dataset.color;
                                manager.setLabel(label, color);
                                container.querySelectorAll('.label-btn').forEach(function(b) {{
                                    b.classList.remove('active');
                                    b.setAttribute('aria-pressed', 'false');
                                }});
                                this.classList.add('active');
                                this.setAttribute('aria-pressed', 'true');
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
                                else if (action === 'carry-over') manager.copyFromPrevious(false);
                            }});
                        }});

                        // Ctrl/Cmd+D: copy from the previous image. Bound here
                        // rather than in the manager's own handler because the
                        // browser's bookmark shortcut has to be suppressed.
                        if (config.carryOver === 'prompt' || config.carryOver === 'auto') {{
                            document.addEventListener('keydown', function(e) {{
                                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'd') {{
                                    if (!container.offsetParent) return;
                                    e.preventDefault();
                                    manager.copyFromPrevious(false);
                                }}
                            }});
                        }}

                        // Per-class show/hide. The shared manager owns the
                        // persisted state; the image manager only knows how to
                        // hide fabric objects and masks.
                        if (typeof LabelVisibilityManager !== 'undefined') {{
                            manager.labelVisibility = new LabelVisibilityManager({{
                                schemaName: config.schemaName,
                                projectKey: (window.config || {{}}).annotation_task_name,
                                container: container,
                                onChange: function(hidden) {{
                                    manager.applyLabelVisibility(hidden);
                                }},
                            }});
                        }}

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

    # Critique reviews what the annotator has already drawn, rather than
    # producing more of it, so it sits after the generative buttons.
    if ai_features.get("critique", True):
        buttons.append(
            '<button type="button" class="ai-btn" data-action="critique" '
            'title="Ask a vision model to review the regions you have drawn">'
            '<span class="ai-btn-icon">🧐</span> Review</button>'
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
                        // The assistant owns the accept/reject review panel, so
                        // text prompting needs it even when no server-side AI is
                        // configured at all — the model runs in the browser.
                        if ((config.aiSupport || config.textPrompt)
                            && typeof VisualAIAssistantManager !== 'undefined') {{
                            var annotationId = Array.from(document.querySelectorAll('.annotation-form')).indexOf(
                                document.getElementById('{escaped_name}')
                            );
                            container.aiAssistant = new VisualAIAssistantManager({{
                                annotationType: 'image_annotation',
                                annotationId: annotationId >= 0 ? annotationId : 0,
                                annotationManager: manager,
                                // Without a configured endpoint the server-backed
                                // buttons can only produce an error, so they are
                                // left out and the review controls stay.
                                serverAssists: !!config.aiSupport
                            }});
                        }}
    '''


#: Human-readable names, used by tooltips and the generated keybinding table.
TOOL_DESCRIPTIONS = {
    "bbox": "Bounding Box",
    "polygon": "Polygon",
    "polyline": "Polyline (open path)",
    "ellipse": "Ellipse",
    "keypoint_set": "Skeleton / Keypoint Set",
    "cuboid_2d": "Projected 3D Cuboid",
    "freeform": "Freeform Draw",
    "landmark": "Landmark Point",
    "brush": "Segmentation Brush",
    "fill": "Flood Fill",
    "eraser": "Eraser",
}

#: Decorative glyphs. Kept apart from TOOL_DESCRIPTIONS because they are
#: aria-hidden and carry no meaning.
TOOL_ICONS = {
    "bbox": "□",
    "polygon": "⬡",
    "polyline": "⌇",
    "ellipse": "⬭",
    "keypoint_set": "⛹",
    "cuboid_2d": "⬛",
    "freeform": "✎",
    "landmark": "◉",
    "brush": "🖌️",
    "fill": "🪣",
    "eraser": "⌫",
    "sam": "🪄",
}

#: Short button labels.
TOOL_LABELS = {
    "bbox": "Box",
    "polygon": "Polygon",
    "polyline": "Polyline",
    "ellipse": "Ellipse",
    "keypoint_set": "Skeleton",
    "cuboid_2d": "Cuboid",
    "freeform": "Draw",
    "landmark": "Point",
    "brush": "Brush",
    "fill": "Fill",
    "eraser": "Eraser",
    "sam": "Magic wand",
}


def _generate_segmentation_controls(segmentation, escaped_name):
    """
    Status line and accept/discard controls for the magic wand.

    Rendered only when the tool is configured. The status line is `aria-live`
    because every meaningful event here — the model loading, a mask appearing,
    a click finding nothing — happens on a canvas a screen reader cannot see,
    and several of them take seconds.
    """
    if not segmentation:
        return ""
    return f"""
                    <div class="segmentation-group" style="display: none;">
                        <span class="segmentation-status" role="status"
                              aria-live="polite" aria-atomic="true"
                              data-kind="info"></span>
                        <button type="button" class="segmentation-accept"
                                disabled
                                title="Accept this mask (Enter)">Accept</button>
                        <button type="button" class="segmentation-cancel"
                                disabled
                                title="Discard this mask (Escape)">Discard</button>
                    </div>"""


def _generate_text_prompt_controls(text_prompt, escaped_name):
    """
    The prompt box: type a phrase, get every match boxed as a suggestion.

    Rendered only when configured, and marked with `data-text-prompt` so the
    asset gate can see it — the detector is a 145 MB download that no other
    project should pay for.

    The results are SUGGESTIONS, never annotations. They go through the same
    accept/reject path as any other model output, because a model that labels
    an image wholesale produces a dataset that agrees with itself, and every
    quality measure Potato has looks better rather than worse when that
    happens.
    """
    if not text_prompt:
        return ""
    phrases = ", ".join(text_prompt.get("phrases") or [])
    return f"""
                    <div class="text-prompt-group" data-text-prompt="{escaped_name}">
                        <label class="text-prompt-label"
                               for="{escaped_name}_text_prompt">Find</label>
                        <input type="text" class="text-prompt-input"
                               id="{escaped_name}_text_prompt"
                               value="{escape_html_content(phrases)}"
                               placeholder="traffic cone, person"
                               aria-describedby="{escaped_name}_text_prompt_help">
                        <button type="button" class="text-prompt-run"
                                title="Find these in the image">Find</button>
                        <span class="text-prompt-help visually-hidden"
                              id="{escaped_name}_text_prompt_help">Separate
                              several things with commas. Results appear as
                              suggestions you accept or reject.</span>
                        <span class="text-prompt-status" role="status"
                              aria-live="polite" aria-atomic="true"></span>
                    </div>"""


def _generate_tool_buttons(tools, tool_keys=None):
    """
    Generate HTML for tool selection buttons.

    The tooltip's key hint comes from the active profile rather than a hardcoded
    letter. It used to say "(B)" for bbox regardless, which was wrong the moment
    the bindings became configurable -- and was already wrong for brush, fill and
    eraser, whose documented "(M)/(G)/(E)" hints had no handler at all.
    """
    if tool_keys is None:
        tool_keys = get_tool_keys()

    buttons = []
    for tool in tools:
        key = tool_keys.get(tool)
        info = {
            "label": TOOL_LABELS.get(tool, tool),
            "icon": TOOL_ICONS.get(tool, "?"),
            "title": (f"{TOOL_DESCRIPTIONS.get(tool, tool)} ({key.upper()})"
                      if key else TOOL_DESCRIPTIONS.get(tool, tool)),
        }
        # These are toggles, not plain buttons: `aria-pressed` is what tells a
        # screen reader which tool is armed. Without it the active state is
        # carried only by a CSS class and is invisible to assistive tech --
        # and picking the wrong tool silently produces the wrong annotation.
        #
        # The icon is decorative and aria-hidden: it is a stand-in glyph, not a
        # word, and it would otherwise be read out as part of the button's name
        # ("broom brush", "backspace eraser").
        buttons.append(
            f'<button type="button" class="tool-btn" data-tool="{tool}" '
            f'aria-pressed="false" title="{info["title"]}">'
            f'<span aria-hidden="true">{info["icon"]}</span> {info["label"]}</button>'
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
            f'aria-pressed="false" title="{name}{key_hint}" style="--label-color: {color};">'
            f'<span class="label-color-dot" aria-hidden="true" '
            f'style="background-color: {color};"></span>'
            f'{name}</button>'
        )

    return "\n".join(buttons)


def _generate_keybindings(labels, tools, tool_keys=None, schema_name="",
                          carry_over=False):
    """
    Generate keybinding list for the schema.

    Args:
        labels: Processed label dicts
        tools: Enabled tool names
        tool_keys: {tool: key} from the active profile; defaults to the default profile
        schema_name: Used only to make collision warnings locatable
    """
    if tool_keys is None:
        tool_keys = get_tool_keys()

    keybindings = []
    used = {}

    for tool in tools:
        key = tool_keys.get(tool)
        if not key:
            continue
        keybindings.append((key, f"{TOOL_DESCRIPTIONS.get(tool, tool)} tool"))
        used[key] = f"{tool} tool"

    # Label shortcuts. A label whose key_value collides with a tool key would
    # fire both actions on one press. Warn and keep the label, per the project
    # convention -- dropping it silently would leave an annotator with a label
    # they cannot reach.
    for label in labels:
        key = label.get("key_value")
        if not key:
            continue
        if key in used:
            logger.warning(
                "Keybinding conflict in image_annotation schema '%s': key '%s' is "
                "bound to %s and also to label '%s'. Both will fire. Change the "
                "label's key_value, or set keybinding_profile to move the tool keys.",
                schema_name, key, used[key], label["name"],
            )
        else:
            used[key] = f"label {label['name']}"
        keybindings.append((key, f"Select label: {label['name']}"))

    keybindings.extend([
        (COMMON_KEYBINDINGS["select"], "Select/move mode"),
        (COMMON_KEYBINDINGS["hide"], "Hide/show the current label"),
        (f'Shift+{COMMON_KEYBINDINGS["hide"].upper()}',
         "Show only the current label"),
        ("Del", "Delete selected"),
        ("+/-", "Zoom in/out"),
        ("0", "Fit to view"),
    ])

    if carry_over in ("prompt", "auto"):
        keybindings.append(("Ctrl+D", "Copy annotations from the previous image"))

    # Brush size only makes sense when a size-using tool is enabled.
    if any(t in tools for t in ("brush", "eraser")):
        keybindings.append((
            f'{COMMON_KEYBINDINGS["brush_size_down"]}/{COMMON_KEYBINDINGS["brush_size_up"]}',
            "Decrease/increase brush size",
        ))

    return keybindings
