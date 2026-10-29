"""
volume_annotation: label 3D medical volumes (DICOM series, NIfTI) slice by slice.

Three linked views (axial, coronal, sagittal), window/level presets, and
per-label brush, eraser, box and polygon tools. Brush masks are stored per
axial slice in canonical voxel space (potato/media/volume_masks.py) and export
to a NIfTI label volume or a DICOM SEG; boxes and polygons are stored as voxel
coordinates. Masks between painted slices can be interpolated, and an
RTSTRUCT on the item can seed the masks.

DICOM headers carry patient information: only ``display_tags`` reach the
annotator, and identifying ones only if also in ``allow_identifying_tags``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Tuple

from .identifier_utils import (escape_html_content, generate_layout_attributes,
                               safe_generate_layout)

logger = logging.getLogger(__name__)

VALID_TOOLS = ("navigate", "brush", "eraser", "box", "polygon")
DEFAULT_TOOLS = ["navigate", "brush", "eraser", "box", "polygon"]
TOOL_KEYS = {"navigate": "n", "brush": "b", "eraser": "e", "box": "x", "polygon": "p"}
TOOL_LABELS = {"navigate": "Navigate", "brush": "Brush", "eraser": "Eraser",
               "box": "Box", "polygon": "Polygon"}
VIEWS = ("axial", "coronal", "sagittal")
PALETTE = ["#e6553a", "#3a8ee6", "#2bb673", "#e6b93a", "#a35ce6", "#e63a9b",
           "#3ad4e6", "#8bc34a"]


#: Coded concepts a DICOM SEG segment and an SR finding carry when a label's
#: config gives none: SNOMED CT 85756007 "Tissue" for both the category and
#: the type. Generic on purpose; a label that means something specific should
#: say so under ``dicom:``.
DEFAULT_DICOM_CODES = {
    "category": {"code": "85756007", "scheme": "SCT", "meaning": "Tissue"},
    "type": {"code": "85756007", "scheme": "SCT", "meaning": "Tissue"},
}
_DICOM_CODE_KEYS = ("category", "type", "anatomic_region")


def _coded(value, where: str) -> Dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be a mapping with code, scheme and meaning")
    unknown = sorted(set(value) - {"code", "scheme", "meaning"})
    if unknown:
        raise ValueError(f"{where} has unknown keys {unknown}; use code, scheme and meaning")
    out = {}
    for key, limit in (("code", 64), ("scheme", 16), ("meaning", 64)):
        text = value.get(key)
        if isinstance(text, bool) or not isinstance(text, (str, int)) or not str(text).strip():
            raise ValueError(f"{where}.{key} is required (a SNOMED CT or DCM "
                             f"code, e.g. code: '52988006', scheme: SCT, meaning: Lesion)")
        text = str(text).strip()
        if len(text) > limit or "\\" in text:
            raise ValueError(f"{where}.{key} must be at most {limit} characters "
                             f"with no backslash")
        out[key] = text
    return out


def dicom_codes(label) -> Dict[str, Dict[str, str]]:
    """The coded concepts for one label's DICOM SEG segment and SR finding.

    A label may carry::

        dicom:
          category: {code: "49755003", scheme: SCT, meaning: Morphologically Altered Structure}
          type: {code: "52988006", scheme: SCT, meaning: Lesion}
          anatomic_region: {code: "39607008", scheme: SCT, meaning: Lung}   # optional

    ``category`` and ``type`` default to DEFAULT_DICOM_CODES each.
    """
    raw = label.get("dicom") if isinstance(label, dict) else None
    name = label.get("name") if isinstance(label, dict) else label
    where = f"label '{name}' dicom"
    if raw is None:
        return {k: dict(v) for k, v in DEFAULT_DICOM_CODES.items()}
    if not isinstance(raw, dict):
        raise ValueError(f"{where} must be a mapping of category, type and anatomic_region")
    unknown = sorted(set(raw) - set(_DICOM_CODE_KEYS))
    if unknown:
        raise ValueError(f"{where} has unknown keys {unknown}; valid: {', '.join(_DICOM_CODE_KEYS)}")
    out = {k: dict(v) for k, v in DEFAULT_DICOM_CODES.items()}
    for key in _DICOM_CODE_KEYS:
        if key in raw:
            out[key] = _coded(raw[key], f"{where}.{key}")
    return out


def label_dicom_codes(scheme) -> Dict[str, Dict[str, Dict[str, str]]]:
    """``{label name: dicom_codes(label)}`` for a volume_annotation scheme."""
    out = {}
    for item in scheme.get("labels") or []:
        name = item if isinstance(item, str) else (item or {}).get("name")
        if name:
            out[str(name)] = dicom_codes(item if isinstance(item, dict) else {"name": name})
    return out


def _labels(raw) -> List[Dict[str, Any]]:
    if not raw:
        raise ValueError("volume_annotation needs at least one label")
    out = []
    for index, item in enumerate(raw):
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict) or not item.get("name"):
            raise ValueError("each volume_annotation label needs a name")
        if "dicom" in item:
            dicom_codes(item)       # raises on a malformed code
        out.append({"name": str(item["name"]),
                    "color": item.get("color") or PALETTE[index % len(PALETTE)],
                    "key_value": item.get("key_value")})
    names = [label["name"] for label in out]
    if len(set(names)) != len(names):
        raise ValueError("volume_annotation label names must be unique")
    if len(out) > 254:
        raise ValueError("volume_annotation supports at most 254 labels")
    return out


def _window_presets(raw) -> List[Dict[str, Any]]:
    out = []
    for item in raw or []:
        try:
            out.append({"name": str(item["name"]), "center": float(item["center"]),
                        "width": float(item["width"])})
        except (KeyError, TypeError, ValueError):
            raise ValueError("volume_annotation window_presets entries need name, "
                             "center and width")
        if out[-1]["width"] <= 0:
            raise ValueError("volume_annotation window_presets width must be positive")
    return out


def generate_volume_annotation_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, list]:
    """Rendered through safe_generate_layout so a config error shows on the page."""
    return safe_generate_layout(annotation_scheme, _generate)


def _generate(annotation_scheme: Dict[str, Any]) -> Tuple[str, list]:
    schema_name = annotation_scheme["name"]
    escaped_name = escape_html_content(schema_name)
    labels = _labels(annotation_scheme.get("labels"))

    tools = annotation_scheme.get("tools") or DEFAULT_TOOLS
    invalid = [t for t in tools if t not in VALID_TOOLS]
    if invalid:
        raise ValueError(f"Invalid volume_annotation tools {invalid}; valid: {list(VALID_TOOLS)}")
    if "navigate" not in tools:
        tools = ["navigate"] + list(tools)
    views = annotation_scheme.get("views") or list(VIEWS)
    bad_views = [v for v in views if v not in VIEWS]
    if bad_views:
        raise ValueError(f"Invalid volume_annotation views {bad_views}; valid: {list(VIEWS)}")

    display_tags = [str(t) for t in annotation_scheme.get("display_tags") or []]
    allowed = [str(t) for t in annotation_scheme.get("allow_identifying_tags") or []]
    from potato.media.volumes import IDENTIFYING_TAGS
    for tag in display_tags:
        if tag in IDENTIFYING_TAGS and tag not in allowed:
            logger.warning(
                "volume_annotation '%s': display tag %s identifies a patient and is "
                "not in allow_identifying_tags, so annotators will not see it",
                schema_name, tag)

    config = {
        "schema": schema_name,
        "labels": labels,
        "tools": list(tools),
        "toolKeys": {t: TOOL_KEYS[t] for t in tools},
        "views": list(views),
        "sourceField": annotation_scheme.get("source_field", "volume"),
        "prefillField": annotation_scheme.get("prefill_rtstruct_field"),
        "defaultWindow": annotation_scheme.get("default_window"),
        "windowPresets": _window_presets(annotation_scheme.get("window_presets")),
        "brushSize": float(annotation_scheme.get("brush_size", 2.0)),
    }
    layout_attrs = generate_layout_attributes(annotation_scheme)
    description = escape_html_content(annotation_scheme.get("description", ""))

    tool_buttons = "".join(
        f'<button type="button" class="tool-btn" data-tool="{t}" aria-pressed="false" '
        f'title="{TOOL_LABELS[t]} ({TOOL_KEYS[t]})">{TOOL_LABELS[t]}</button>'
        for t in tools)
    label_buttons = "".join(
        f'<button type="button" class="vol-label-btn" data-label="{escape_html_content(l["name"])}" '
        f'aria-pressed="false" style="--vol-label-color: {escape_html_content(l["color"])}">'
        f'<span class="vol-label-dot" aria-hidden="true"></span>{escape_html_content(l["name"])}'
        f'</button>' for l in labels)
    view_panels = "".join(
        f'<div class="vol-view" data-axis="{v}">'
        f'<div class="vol-view-head"><span class="vol-view-name">{v.capitalize()}</span>'
        f'<span class="vol-slice-label" data-slice-label="{v}"></span></div>'
        f'<div class="vol-stage" tabindex="0" role="application" '
        f'aria-label="{v.capitalize()} view. Scroll or use Up and Down arrows to change '
        f'slice; draw with the selected tool.">'
        f'<canvas class="vol-image"></canvas><canvas class="vol-overlay"></canvas></div>'
        f'<input type="range" class="vol-slider" data-axis="{v}" min="0" max="0" value="0" '
        f'aria-label="{v.capitalize()} slice"></div>'
        for v in views)

    html = f"""
    <div class="volume-annotation-container annotation-form" data-schema="{escaped_name}"
         data-annotation-type="volume_annotation" data-schema-name="{escaped_name}" {layout_attrs}>
        <fieldset>
            <legend>{description}</legend>
            <div class="vol-toolbar" role="toolbar" aria-label="Volume tools">
                {tool_buttons}
                <label class="vol-brush">Brush
                    <input type="range" class="vol-brush-size" min="1" max="15" step="0.5"
                           value="{config['brushSize']}" aria-label="Brush size in voxels">
                </label>
                <label class="vol-window">Window
                    <select class="vol-window-select" aria-label="Window preset"></select>
                </label>
                <button type="button" class="tool-btn" data-action="interpolate"
                        title="Fill the slices between painted slices of the selected label (i)">
                    Interpolate</button>
                <button type="button" class="tool-btn" data-action="undo"
                        title="Undo the last edit (Ctrl+Z)">Undo</button>
            </div>
            <div class="vol-labels" role="group" aria-label="Labels">{label_buttons}</div>
            <div class="vol-views">{view_panels}</div>
            <dl class="vol-tags" hidden></dl>
            <ul class="vol-shapes" aria-label="Boxes and polygons"></ul>
            <p class="vol-status" role="status" aria-live="polite"></p>
            <p class="vol-help">Scroll or <kbd>&uarr;</kbd>/<kbd>&darr;</kbd> to change slice.
               Right-drag on an image adjusts the window. In Navigate mode a click moves the
               other views to that point. Polygon: click points, double-click or <kbd>Enter</kbd>
               to close, <kbd>Esc</kbd> to cancel.</p>
            <input type="hidden" name="{escaped_name}" id="input-{escaped_name}"
                   class="annotation-data-input" value="">
        </fieldset>
    </div>
    <script>
        (function() {{
            function initWhenReady() {{
                if (typeof VolumeAnnotationManager === 'undefined') {{
                    setTimeout(initWhenReady, 100);
                    return;
                }}
                var container = document.querySelector(
                    '.volume-annotation-container[data-schema="{escaped_name}"]');
                if (!container || container.annotationManager) return;
                var manager = new VolumeAnnotationManager(container,
                    'input-{escaped_name}', {json.dumps(config)});
                container.annotationManager = manager;
                manager.init().catch(function (err) {{
                    var status = container.querySelector('.vol-status');
                    if (status) {{
                        status.textContent = 'Volume viewer failed to start: ' + err.message;
                        status.setAttribute('data-kind', 'error');
                    }}
                    console.error('[volume] init failed', err);
                }});
            }}
            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', initWhenReady);
            }} else {{
                initWhenReady();
            }}
        }})();
    </script>
    """

    keybindings = [{"key": TOOL_KEYS[t], "description": TOOL_LABELS[t]} for t in tools]
    keybindings += [{"key": "Up / Down", "description": "Next / previous slice"},
                    {"key": "i", "description": "Interpolate the selected label"},
                    {"key": "Ctrl+Z", "description": "Undo"}]
    for label in labels:
        if label.get("key_value"):
            keybindings.append({"key": str(label["key_value"]),
                                "description": f"Select {label['name']}"})
    return html, keybindings
