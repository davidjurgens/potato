"""
Multichannel microscopy schema (``annotation_type: microscopy``).

Shows an OME-Zarr or OME-TIFF image named by the item, with a channel list
(colour, visibility, contrast limits), z-slice and time-point sliders when the
image has them, and the file's own pyramid for zooming. The annotator draws
regions of interest (rectangles, polygons, points) and, when the image has a
label image, clicks cells and gives each a class.

Tiles are composited on the server (``potato/science/microscopy.py``) and
shown with OpenSeadragon; see docs/annotation-types/science/microscopy.md for
why this does not use Viv.

The answer is one hidden input holding JSON::

    {"image": {"width": 2048, "height": 2048},
     "rois": [{"type": "polygon", "label": "tumour", "color": "#c2255c",
               "coordinates": [{"x": 0.1, "y": 0.2}, ...], "z": 2, "t": 0}],
     "cells": [{"label_id": 17, "class": "T cell", "z": 2, "t": 0}],
     "label_image": "cells"}

ROI entries use image_annotation's region format (``bbox`` ->
``{x, y, width, height}``, ``polygon`` -> ``[{x, y}]``, ``landmark`` ->
``{x, y}``, all as fractions of the full-resolution image), so the
``potato.export.cv_utils`` helpers read them, plus the z-slice and time point
they were drawn on.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Tuple

from .identifier_utils import (
    escape_html_content, generate_element_identifier, generate_layout_attributes,
    generate_validation_attribute, safe_generate_layout)

logger = logging.getLogger(__name__)

#: Drawing tools, named as image_annotation names them. Cell picking needs no
#: tool: a click on a cell selects it whenever the image has a label image.
VALID_TOOLS = ("bbox", "polygon", "landmark")
DEFAULT_TOOLS = ("bbox", "polygon", "landmark")

LABEL_COLOURS = ("#c2255c", "#e8590c", "#f2c94c", "#2b8a3e", "#1c7ed6", "#7048e8",
                 "#0ca678", "#a61e4d")


def _labels(raw: Any) -> List[Dict[str, str]]:
    out = []
    for i, item in enumerate(raw or []):
        if isinstance(item, dict):
            name, colour = item.get("name"), item.get("color")
        else:
            name, colour = item, None
        out.append({"name": str(name),
                    "color": str(colour or LABEL_COLOURS[i % len(LABEL_COLOURS)])})
    return out


def client_config(scheme: Dict[str, Any]) -> Dict[str, Any]:
    labels = _labels(scheme.get("labels"))
    cell_labels = _labels(scheme.get("cell_labels")) if scheme.get("cell_labels") else labels
    return {
        "schema": scheme["name"],
        "labels": labels,
        "cellLabels": cell_labels,
        "tools": list(scheme["tools"] if scheme.get("tools") is not None else DEFAULT_TOOLS),
        "minRois": int(scheme.get("min_rois") or 0),
        "minCells": int(scheme.get("min_cells") or 0),
        "height": int(scheme.get("height") or 520),
    }


def generate_microscopy_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    esc = escape_html_content(schema_name)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    validation = generate_validation_attribute(annotation_scheme)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    instructions = annotation_scheme.get("instructions", "")
    config = json.dumps(client_config(annotation_scheme))
    html = f"""
    <form id="{esc}" class="annotation-form microscopy" action="javascript:void(0)"
          data-annotation-type="microscopy" data-schema-name="{esc}"
          data-microscopy-config='{escape_html_content(config)}' {layout_attrs}>
        <fieldset schema="{esc}">
            <legend class="mic-title">{escape_html_content(annotation_scheme["description"])}</legend>
            {f'<p class="mic-instructions">{escape_html_content(instructions)}</p>' if instructions else ''}
            <div class="mic-root">
                <p class="mic-status" role="status">Loading image…</p>
            </div>
            <input type="hidden" class="annotation-input microscopy-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>
    """
    return html, []


def validate_scheme(scheme: Dict[str, Any]) -> List[str]:
    """Problems with one microscopy scheme, as messages naming the key."""
    errors: List[str] = []

    def _label_list(key: str, required: bool) -> None:
        raw = scheme.get(key)
        if raw is None:
            if required:
                errors.append(f"{key} is required: the classes an annotator gives regions and cells")
            return
        if not isinstance(raw, list) or not raw:
            errors.append(f"{key} must be a non-empty list of class names")
            return
        names = []
        for item in raw:
            name = item.get("name") if isinstance(item, dict) else item
            if not isinstance(name, str) or not name.strip():
                errors.append(f"{key} entries must be names, or {{name, color}} mappings")
                return
            if isinstance(item, dict) and item.get("color") is not None and not _is_colour(item["color"]):
                errors.append(f"{key}: '{item['color']}' is not a #rrggbb colour")
            names.append(name)
        if len(set(names)) != len(names):
            errors.append(f"{key} has duplicate names")

    _label_list("labels", True)
    _label_list("cell_labels", False)

    for key in ("image_key", "labels_key", "label_image"):
        if key in scheme and not (isinstance(scheme[key], str) and scheme[key].strip()):
            errors.append(f"{key} must be a non-empty string")

    tools = scheme.get("tools")
    if tools is not None:
        if not isinstance(tools, list):
            errors.append(f"tools must be a list drawn from {', '.join(VALID_TOOLS)} "
                          "([] for a cells-only task)")
        else:
            bad = [t for t in tools if t not in VALID_TOOLS]
            if bad:
                errors.append(f"tools: {', '.join(map(str, bad))} not supported; use "
                              f"{', '.join(VALID_TOOLS)}")

    for key, low, high in (("min_rois", 0, 10000), ("min_cells", 0, 100000),
                           ("tile_size", 64, 1024), ("height", 240, 2000),
                           ("label_max_side", 256, 8192),
                           ("max_pixels", 1_000_000, 4_000_000_000)):
        if key in scheme:
            value = scheme[key]
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                errors.append(f"{key} must be a whole number from {low} to {high}")

    channels = scheme.get("channels")
    if channels is not None:
        if not isinstance(channels, list):
            errors.append("channels must be a list of {index or name, label, color, contrast, visible}")
        else:
            for i, entry in enumerate(channels):
                where = f"channels[{i}]"
                if not isinstance(entry, dict):
                    errors.append(f"{where} must be a mapping")
                    continue
                unknown = set(entry) - {"index", "name", "label", "color", "contrast", "visible"}
                if unknown:
                    errors.append(f"{where} has unknown keys: {', '.join(sorted(unknown))}")
                if "index" not in entry and "name" not in entry:
                    errors.append(f"{where} needs an index or a name to say which channel it sets")
                if "index" in entry and (not isinstance(entry["index"], int)
                                         or isinstance(entry["index"], bool) or entry["index"] < 0):
                    errors.append(f"{where}.index must be a channel number from 0")
                if "color" in entry and not _is_colour(entry["color"]):
                    errors.append(f"{where}.color must be #rrggbb")
                contrast = entry.get("contrast")
                if contrast is not None and not (
                        isinstance(contrast, list) and len(contrast) == 2
                        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in contrast)
                        and contrast[1] > contrast[0]):
                    errors.append(f"{where}.contrast must be [low, high] with high above low")
                if "visible" in entry and not isinstance(entry["visible"], bool):
                    errors.append(f"{where}.visible must be true or false")
    return errors


def _is_colour(value: Any) -> bool:
    text = str(value or "")
    return (len(text) == 7 and text.startswith("#")
            and all(ch in "0123456789abcdefABCDEF" for ch in text[1:]))
