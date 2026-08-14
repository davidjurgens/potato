"""
Spatial (3D) Annotation Layout

Annotates a point cloud with oriented 3D boxes, points, polylines, and
per-point segments. Rendered by ``potato/static/pointcloud/pc-viewer.js`` over
three.js.

## What is shared with image annotation, and what is not

**Shared on purpose:** the ``.label-btn`` / ``data-label`` / ``data-color``
convention. That is the exact markup ``label-visibility.js`` keys on, so
hide-by-class works here with no new wiring — the third modality to inherit it
after image and video. The hidden ``.annotation-data-input`` is the same too,
so the four save/restore functions in ``annotation.js`` need no special case.

**Deliberately not shared:** the coordinate contract. A cuboid is in metres in a
sensor frame with an orientation; there is no image to normalize against. See
``potato/export/spatial_utils.py`` for the full reasoning and the client shape.

## Tool names are the annotation types

``VALID_SPATIAL_TOOLS`` is ``SPATIAL_TYPES`` from the contract module, not a
second list that happens to agree with it. ``VALID_TOOLS`` for 2D was defined in
two places and drifted; there is no reason to make that mistake twice.
"""

import json
import logging

from potato.export.spatial_utils import SPATIAL_TYPES

from .identifier_utils import escape_html_content, safe_generate_layout
from .image_annotation import DEFAULT_COLORS, _process_labels

logger = logging.getLogger(__name__)

#: The tools a spatial schema may enable. Same names as the stored annotation
#: types, and the same object — see the module docstring.
VALID_SPATIAL_TOOLS = SPATIAL_TYPES

#: Keyboard shortcuts. Chosen not to collide with the viewer's own navigation
#: (which uses the mouse) or with the shared `h` / `Shift+H` class-visibility
#: keys that label-visibility.js binds.
TOOL_KEYS = {
    "cuboid_3d": "c",
    "point_3d": "k",
    "polyline_3d": "n",
    "segment_3d": "g",
}

TOOL_LABELS = {
    "cuboid_3d": ("3D box", "▧"),
    "point_3d": ("Point", "⬤"),
    "polyline_3d": ("Polyline", "⤳"),
    "segment_3d": ("Paint points", "▦"),
}

#: How a cloud is coloured when no per-point RGB is present.
VALID_COLOR_MODES = ("height", "intensity", "rgb", "uniform")


def generate_spatial_annotation_layout(annotation_scheme):
    """
    Generate HTML for a point cloud annotation interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - tools: Which of cuboid_3d / point_3d / polyline_3d / segment_3d
            - labels: Label definitions (strings or {name, color, key_value})
            - source_field: Item field holding the cloud path
              (default: "point_cloud")
            - calibration_field: Item field holding camera calibration, which
              turns on the 2D verification panels (default: "calibration")
            - color_mode: height | intensity | rgb | uniform
            - point_size: Rendered point size in pixels (default 1.5)
            - max_points: Decimation cap requested from the server
            - default_box_height: Height a new box starts at, in metres
              (default 1.7 — roughly a person, and a sane default for traffic)
            - fit_box_height: Snap a new box's vertical extent to the points
              inside its footprint (default true)
            - min_annotations / max_annotations

    Returns:
        tuple: (html_string, key_bindings)
    """
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme):
    schema_name = annotation_scheme.get("name", "spatial_annotation")
    logger.debug("Generating spatial annotation layout for schema: %s",
                 schema_name)

    if "labels" not in annotation_scheme:
        raise ValueError(f"Missing labels in schema: {schema_name}")
    if "tools" not in annotation_scheme:
        raise ValueError(f"Missing tools in schema: {schema_name}")

    tools = annotation_scheme["tools"]
    if not isinstance(tools, list) or not tools:
        raise ValueError(f"tools must be a non-empty list in schema: {schema_name}")

    invalid = [t for t in tools if t not in VALID_SPATIAL_TOOLS]
    if invalid:
        raise ValueError(
            f"Invalid tools: {invalid}. Valid tools are: "
            f"{list(VALID_SPATIAL_TOOLS)}")

    color_mode = annotation_scheme.get("color_mode", "height")
    if color_mode not in VALID_COLOR_MODES:
        raise ValueError(
            f"color_mode must be one of {list(VALID_COLOR_MODES)}, "
            f"got '{color_mode}'")

    labels = _process_labels(annotation_scheme["labels"])
    escaped_name = escape_html_content(schema_name)
    description = escape_html_content(annotation_scheme.get("description", ""))

    config = {
        "schema": schema_name,
        "tools": tools,
        "toolKeys": {t: TOOL_KEYS[t] for t in tools},
        "labels": labels,
        "sourceField": annotation_scheme.get("source_field", "point_cloud"),
        "calibrationField": annotation_scheme.get("calibration_field",
                                                  "calibration"),
        "colorMode": color_mode,
        "pointSize": float(annotation_scheme.get("point_size", 1.5)),
        "maxPoints": annotation_scheme.get("max_points"),
        "defaultBoxHeight": float(
            annotation_scheme.get("default_box_height", 1.7)),
        "fitBoxHeight": annotation_scheme.get("fit_box_height", True),
        "minAnnotations": annotation_scheme.get("min_annotations", 0),
        "maxAnnotations": annotation_scheme.get("max_annotations"),
    }

    html = f"""
    <div class="pointcloud-annotation-container" data-schema="{escaped_name}">
        <fieldset>
            <legend>{description}</legend>

            <div class="pc-toolbar" role="toolbar"
                 aria-label="Point cloud annotation tools">
                {_tool_buttons(tools)}
            </div>

            <div class="pc-labels" role="group" aria-label="Annotation classes">
                {_label_buttons(labels)}
            </div>

            <div class="pc-viewport">
                <canvas id="pc-canvas-{escaped_name}" class="pc-canvas"
                        role="application" tabindex="0"
                        aria-label="Point cloud viewer. Drag to orbit, right-drag
                                    to pan, scroll to zoom. Use the tool buttons
                                    above, or their keyboard shortcuts, to
                                    annotate."></canvas>
                <!-- The viewer reports what it is showing here. A decimated
                     cloud presented without saying so is a cloud the annotator
                     believes is complete. -->
                <p class="pc-status" id="pc-status-{escaped_name}"
                   aria-live="polite"></p>
            </div>

            <!-- Camera verification panels, filled in only when the item
                 carries calibration. A box placed on a few dozen lidar returns
                 is close to a guess; the same box drawn on the photograph that
                 saw the object is checkable at a glance. -->
            <div class="pc-cameras" data-schema="{escaped_name}"
                 role="group" aria-label="Camera verification views"></div>

            <input type="hidden"
                   name="{escaped_name}"
                   id="input-{escaped_name}"
                   class="annotation-data-input"
                   value="">
        </fieldset>
    </div>

    <script>
        (function() {{
            function initWhenReady() {{
                if (typeof PointCloudAnnotationManager === 'undefined') {{
                    setTimeout(initWhenReady, 100);
                    return;
                }}
                var container = document.querySelector(
                    '.pointcloud-annotation-container[data-schema="{escaped_name}"]');
                if (!container || container.annotationManager) return;

                var manager = new PointCloudAnnotationManager(
                    'pc-canvas-{escaped_name}',
                    'input-{escaped_name}',
                    {json.dumps(config)});
                container.annotationManager = manager;
                manager.init();
            }}
            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', initWhenReady);
            }} else {{
                initWhenReady();
            }}
        }})();
    </script>
    """

    return html, _keybindings(labels, tools, schema_name)


def _tool_buttons(tools):
    out = []
    for tool in tools:
        label, icon = TOOL_LABELS[tool]
        key = TOOL_KEYS[tool]
        out.append(
            f'<button type="button" class="tool-btn" data-tool="{tool}" '
            f'aria-pressed="false" title="{label} ({key})">'
            f'<span aria-hidden="true">{icon}</span> {label}</button>')
    return "\n".join(out)


def _label_buttons(labels):
    """
    The same markup image and video annotation render.

    Not a coincidence and not worth "improving": ``label-visibility.js`` is
    gated on the ``label-btn`` marker, so matching it is what gives this schema
    per-class show/hide for free.
    """
    out = []
    for label in labels:
        name = escape_html_content(label["name"])
        color = label["color"]
        key_hint = f' ({label["key_value"]})' if label.get("key_value") else ""
        out.append(
            f'<button type="button" class="label-btn" data-label="{name}" '
            f'data-color="{color}" aria-pressed="false" '
            f'title="{name}{key_hint}" style="--label-color: {color};">'
            f'<span class="label-color-dot" aria-hidden="true" '
            f'style="background-color: {color};"></span>{name}</button>')
    return "\n".join(out)


def _keybindings(labels, tools, schema_name):
    """
    Shortcuts, with tool keys taking precedence over label keys.

    A label whose ``key_value`` collides with a tool key keeps its label and the
    collision is logged — the project convention is to warn and continue rather
    than silently drop one binding, because a dropped shortcut is discovered by
    an annotator mid-task.
    """
    bindings = []
    taken = set()
    for tool in tools:
        key = TOOL_KEYS[tool]
        taken.add(key)
        bindings.append({"key": key, "description": TOOL_LABELS[tool][0]})

    for label in labels:
        key = label.get("key_value")
        if not key:
            continue
        if key in taken:
            logger.warning(
                "Schema '%s': label '%s' uses key '%s', which is already a "
                "tool shortcut. The label keeps the binding; press the tool "
                "button instead.", schema_name, label["name"], key)
        taken.add(key)
        bindings.append({"key": key, "description": f'Select {label["name"]}'})

    return bindings
