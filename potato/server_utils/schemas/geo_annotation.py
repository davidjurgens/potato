"""
Geographic annotation on a map (``annotation_type: geo_annotation``).

Three tasks:

================  ============================================================
draw (default)    points, lines, polygons and freehand polygons, each with a
                  label (and optionally a typed name) -- the draw-a-map task
pin               one point per label ("Where were you born?")
classify_region   click regions of the basemap outline to give them a label
                  (a choropleth)
================  ============================================================

The map is OpenLayers (potato/static/vendor/ol-10.9.0, BSD-2-Clause), driven
by ``static/geo-annotation.js``. The basemap is whatever the project supplies:
a GeoJSON outline (read here from ``basemap.geojson`` and embedded in the
page), a georeferenced image, a GeoTIFF, or tiles from a URL the
administrator configured. Nothing is fetched from a third party otherwise.

The answer is one hidden input holding a GeoJSON FeatureCollection in
EPSG:4326 (RFC 7946: ``[lon, lat]``, right-hand winding). Each feature's
``properties`` has ``label`` and, when ``feature_text`` is on, ``text``;
classify_region features have ``geometry: null`` and a ``region`` id.
"""

import html
import json
import logging
import os
from typing import Any, Dict, List, Tuple

from .identifier_utils import (
    escape_html_content, generate_element_identifier, generate_layout_attributes,
    generate_validation_attribute, safe_generate_layout)

logger = logging.getLogger(__name__)

DEFAULT_TOOLS = ["point", "line", "polygon", "freehand"]


def generate_geo_annotation_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _attr_json(obj: Any) -> str:
    """JSON for an HTML attribute. Braces become entities as well, so a ``{#``
    or ``{{`` inside a region name cannot reach Jinja when the generated
    layout is rendered as a template; the browser decodes them back."""
    text = html.escape(json.dumps(obj, separators=(",", ":"), ensure_ascii=False), quote=True)
    return text.replace("{", "&#123;").replace("}", "&#125;")


def _task_dir() -> str:
    from potato.server_utils.config_module import config
    return config.get("task_dir") or os.getcwd()


def _client_basemap(annotation_scheme: Dict[str, Any]) -> Tuple[Dict[str, Any], Any]:
    """(basemap settings for the page, inline GeoJSON outline or None)."""
    from potato.geo.scheme import scheme_regions
    basemap = dict(annotation_scheme.get("basemap") or {})
    inline = None
    gj = basemap.get("geojson")
    if gj:
        if gj.startswith(("http://", "https://", "//", "/")):
            basemap["geojson_url"] = gj
        else:
            inline = scheme_regions(annotation_scheme, _task_dir())
        basemap.pop("geojson", None)
    return basemap, inline


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    from potato.geo.scheme import feature_text_config, label_list, validate_geo_scheme
    schema_name = annotation_scheme["name"]
    validate_geo_scheme(annotation_scheme, f"geo_annotation '{schema_name}'")
    task = annotation_scheme.get("task", "draw")
    esc = escape_html_content(schema_name)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    validation = generate_validation_attribute(annotation_scheme)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    instructions = annotation_scheme.get("instructions", "")
    basemap, inline = _client_basemap(annotation_scheme)
    height = int(annotation_scheme.get("height", 440))
    cfg = {
        "schema": schema_name,
        "task": task,
        "labels": label_list(annotation_scheme),
        "tools": annotation_scheme.get("tools") or DEFAULT_TOOLS,
        "feature_text": feature_text_config(annotation_scheme),
        "basemap": basemap,
        "basemap_field": annotation_scheme.get("basemap_field"),
        "preannotation_field": annotation_scheme.get("preannotation_field"),
        "coordinate_order": annotation_scheme.get("coordinate_order", "lonlat"),
        "projection": annotation_scheme.get("projection", "EPSG:3857"),
        "center": annotation_scheme.get("center"),
        "zoom": annotation_scheme.get("zoom"),
        "snapping": bool(annotation_scheme.get("snapping", False)),
        "min_features": annotation_scheme.get("min_features"),
        "max_features": annotation_scheme.get("max_features"),
        "require_all_regions": bool(annotation_scheme.get("require_all_regions", False)),
        "required": bool(validation),
    }
    inline_attr = f' data-geo-basemap="{_attr_json(inline)}"' if inline else ""
    map_label = {"draw": "Map. Arrow keys pan, plus and minus zoom.",
                 "pin": "Map. Arrow keys pan, plus and minus zoom. Click to place the selected pin.",
                 "classify_region": "Map of regions. Arrow keys pan, plus and minus zoom."}[task]

    html_out = f"""
    <form id="{esc}" class="annotation-form geo-annotation" action="javascript:void(0)"
          data-annotation-type="geo_annotation" data-schema-name="{esc}" data-geo-task="{task}"
          data-geo-config="{_attr_json(cfg)}"{inline_attr} {layout_attrs}>
        <fieldset schema="{esc}">
            <legend class="geo-title">{escape_html_content(annotation_scheme["description"])}</legend>
            {f'<p class="geo-instructions">{escape_html_content(instructions)}</p>' if instructions else ''}
            <div class="geo-toolbar" role="toolbar" aria-label="Map tools"></div>
            <div class="geo-map" tabindex="0" role="application" aria-label="{map_label}"
                 style="height: {height}px"><p class="geo-loading" role="status">Loading map…</p></div>
            <p class="geo-status" role="status" aria-live="polite"></p>
            <div class="geo-features"></div>
            <input type="hidden" class="annotation-input geo-annotation-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>
    """
    return html_out, []
