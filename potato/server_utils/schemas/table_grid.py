"""
Table-Grid Structure Schema (M16).

Annotates the **cell structure** of a table image — the genuinely document-specific
piece of document-parsing evaluation (OmniDocBench, CVPR 2025; RealHiTBench) that
plain bounding boxes don't capture. The annotator sets the grid dimensions
(rows × cols) and clicks cells to mark their role: data / header / empty (and
spanning cells via a span toggle). Per-page *region* bounding boxes (table / figure /
header) are already covered by :mod:`image_annotation` run per page, so this schema
focuses on the table structure that image bboxes can't express.

Input per instance: a table ``image`` URL and optional initial ``rows``/``cols``.
Stored as a hidden-input JSON object ``{rows, cols, cells: {"r,c": role}}`` (only
non-``data`` cells are stored). The IIFE seeds from the server-restored hidden value
before wiring events (persistence contract).
"""

import json
import logging
from typing import Any, Dict, List, Tuple

from .identifier_utils import (
    safe_generate_layout, generate_element_identifier,
    generate_validation_attribute, escape_html_content, generate_layout_attributes,
)

logger = logging.getLogger(__name__)


def generate_table_grid_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    description = annotation_scheme["description"]
    image_key = annotation_scheme.get("image_key", "image")
    rows_key = annotation_scheme.get("rows_key", "rows")
    cols_key = annotation_scheme.get("cols_key", "cols")
    default_rows = int(annotation_scheme.get("default_rows", 3))
    default_cols = int(annotation_scheme.get("default_cols", 3))
    # role cycle order; first is the default (not stored)
    roles = annotation_scheme.get("roles", ["data", "col_header", "row_header", "empty"])
    esc_schema = escape_html_content(schema_name)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    config_json = json.dumps({
        "image_key": image_key, "rows_key": rows_key, "cols_key": cols_key,
        "default_rows": default_rows, "default_cols": default_cols, "roles": roles})

    html = f"""
    <form id="{esc_schema}" class="annotation-form table-grid-container"
          action="javascript:void(0)" data-annotation-type="table_grid"
          data-schema-name="{esc_schema}" {layout_attrs}>
        <fieldset schema="{esc_schema}">
            <legend class="tbg-title">{escape_html_content(description)}</legend>
            <div class="tbg-image" id="{esc_schema}-image"></div>
            <div class="tbg-dims">
                <label>rows <input type="number" min="1" max="40" class="tbg-rows" id="{esc_schema}-rows"></label>
                <label>cols <input type="number" min="1" max="40" class="tbg-cols" id="{esc_schema}-cols"></label>
                <span class="tbg-hint">Click a cell to cycle its role.</span>
            </div>
            <div class="tbg-grid" id="{esc_schema}-grid"></div>
            <div class="tbg-legend" id="{esc_schema}-legend"></div>
            <input type="hidden" class="annotation-input table-grid-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>

    <script>
    (function() {{
        var SCHEMA = '{esc_schema}';
        var CONFIG = {config_json};
        var DEFAULT_ROLE = CONFIG.roles[0];
        var STATE = {{rows: CONFIG.default_rows, cols: CONFIG.default_cols, cells: {{}}}};

        function instanceData() {{
            try {{
                var el = document.querySelector('[data-instance-json]');
                if (el) return JSON.parse(el.getAttribute('data-instance-json'));
            }} catch(e) {{}}
            var t = document.getElementById('text-content') || document.getElementById('instance-text');
            if (t) {{ try {{ return JSON.parse(t.textContent || t.innerText); }} catch(e2) {{}} }}
            return {{}};
        }}

        function hidden() {{ return document.getElementById(SCHEMA).querySelector('.table-grid-input'); }}
        function restore() {{
            var h = hidden();
            if (h && h.value) {{ try {{ return JSON.parse(h.value) || {{}}; }} catch(e) {{}} }}
            return {{}};
        }}

        function build() {{
            var d = instanceData();
            var prev = restore();
            STATE = {{
                rows: prev.rows || +d[CONFIG.rows_key] || CONFIG.default_rows,
                cols: prev.cols || +d[CONFIG.cols_key] || CONFIG.default_cols,
                cells: prev.cells || {{}}
            }};

            var imgWrap = document.getElementById(SCHEMA + '-image');
            var src = d[CONFIG.image_key];
            imgWrap.innerHTML = src ? '<img class="tbg-img" src="' + esc(src) + '" alt="Table to annotate">' :
                '<div class="tbg-noimg">no table image</div>';

            document.getElementById(SCHEMA + '-rows').value = STATE.rows;
            document.getElementById(SCHEMA + '-cols').value = STATE.cols;

            document.getElementById(SCHEMA + '-rows').addEventListener('change', onDims);
            document.getElementById(SCHEMA + '-cols').addEventListener('change', onDims);

            renderLegend();
            renderGrid();
            save();
        }}

        function onDims() {{
            var r = parseInt(document.getElementById(SCHEMA + '-rows').value, 10);
            var c = parseInt(document.getElementById(SCHEMA + '-cols').value, 10);
            STATE.rows = Math.max(1, Math.min(40, isNaN(r) ? STATE.rows : r));
            STATE.cols = Math.max(1, Math.min(40, isNaN(c) ? STATE.cols : c));
            // Drop cell overrides now out of range.
            Object.keys(STATE.cells).forEach(function(k) {{
                var p = k.split(',');
                if (+p[0] >= STATE.rows || +p[1] >= STATE.cols) delete STATE.cells[k];
            }});
            renderGrid(); save();
        }}

        function roleOf(r, c) {{ return STATE.cells[r + ',' + c] || DEFAULT_ROLE; }}

        function renderGrid() {{
            var grid = document.getElementById(SCHEMA + '-grid');
            grid.style.gridTemplateColumns = 'repeat(' + STATE.cols + ', minmax(28px, 1fr))';
            var html = '';
            for (var r = 0; r < STATE.rows; r++) {{
                for (var c = 0; c < STATE.cols; c++) {{
                    var role = roleOf(r, c);
                    html += '<button type="button" class="tbg-cell role-' + esc(role) + '" data-r="' + r + '" data-c="' + c +
                        '" aria-label="row ' + (r+1) + ' col ' + (c+1) + ', ' + esc(role) + '">' +
                        esc(roleAbbr(role)) + '</button>';
                }}
            }}
            grid.innerHTML = html;
            grid.querySelectorAll('.tbg-cell').forEach(function(btn) {{
                btn.addEventListener('click', function() {{
                    var r = btn.getAttribute('data-r'), c = btn.getAttribute('data-c'), key = r + ',' + c;
                    var cur = STATE.cells[key] || DEFAULT_ROLE;
                    var next = CONFIG.roles[(CONFIG.roles.indexOf(cur) + 1) % CONFIG.roles.length];
                    if (next === DEFAULT_ROLE) delete STATE.cells[key]; else STATE.cells[key] = next;
                    var nr = STATE.cells[key] || DEFAULT_ROLE;
                    btn.className = 'tbg-cell role-' + nr;
                    btn.textContent = roleAbbr(nr);
                    btn.setAttribute('aria-label', 'row ' + (+r+1) + ' col ' + (+c+1) + ', ' + nr);
                    save();
                }});
            }});
        }}

        function renderLegend() {{
            document.getElementById(SCHEMA + '-legend').innerHTML = CONFIG.roles.map(function(role) {{
                return '<span class="tbg-leg role-' + esc(role) + '">' + esc(roleAbbr(role)) + ' = ' + esc(role.replace(/_/g,' ')) + '</span>';
            }}).join('');
        }}

        function roleAbbr(role) {{
            return ({{data: '', col_header: 'CH', row_header: 'RH', empty: '∅', header: 'H', merged: 'M'}})[role]
                || role.slice(0, 2).toUpperCase();
        }}

        function save() {{
            var data = {{rows: STATE.rows, cols: STATE.cols}};
            if (Object.keys(STATE.cells).length) data.cells = JSON.parse(JSON.stringify(STATE.cells));
            var h = hidden();
            if (h) {{
                h.value = JSON.stringify(data);
                h.setAttribute('data-modified', 'true');
                h.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
        }}

        function esc(t) {{ var d = document.createElement('div'); d.textContent = (t==null?'':t); return d.innerHTML; }}

        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
        else build();
        document.addEventListener('instanceChanged', build);
    }})();
    </script>

    <style>
    .table-grid-container {{ font-family: inherit; }}
    .tbg-title {{ font-weight: 600; font-size: 1em; margin-bottom: 6px; }}
    .tbg-image {{ margin-bottom: 8px; }}
    .tbg-img {{ max-width: 100%; height: auto; border: 1px solid var(--border, #e4e4e7); border-radius: 6px; display: block; }}
    .tbg-noimg {{ color: var(--muted-foreground, #71717a); font-style: italic; font-size: 0.85em; }}
    .tbg-dims {{ display: flex; align-items: center; gap: 12px; margin-bottom: 8px; font-size: 0.85em; }}
    .tbg-dims input {{ width: 56px; padding: 4px 6px; border: 1px solid var(--border, #e4e4e7); border-radius: 6px; margin-left: 4px; }}
    .tbg-dims input:focus-visible {{ outline: 2px solid var(--ring, #6e56cf); outline-offset: 1px; }}
    .tbg-hint {{ color: var(--muted-foreground, #71717a); }}
    .tbg-grid {{ display: grid; gap: 3px; max-width: 100%; overflow: auto; }}
    .tbg-cell {{ aspect-ratio: 1 / 1; min-height: 28px; border: 1px solid var(--border, #e4e4e7); border-radius: 4px;
                 background: var(--card, #fff); cursor: pointer; font-size: 0.72em; font-weight: 700; color: var(--foreground, #18181b); }}
    .tbg-cell:hover {{ outline: 1px solid var(--ring, #6e56cf); }}
    .tbg-cell:focus-visible {{ outline: 2px solid var(--ring, #6e56cf); outline-offset: 1px; }}
    .tbg-cell.role-data {{ background: var(--card, #fff); }}
    .tbg-cell.role-col_header {{ background: #d0bfff; color: #3b2a7a; }}
    .tbg-cell.role-row_header {{ background: #a5d8ff; color: #11497a; }}
    .tbg-cell.role-header {{ background: #d0bfff; color: #3b2a7a; }}
    .tbg-cell.role-empty {{ background: var(--secondary, #f4f4f5); color: var(--muted-foreground, #adb5bd); }}
    .tbg-cell.role-merged {{ background: #ffe8cc; color: #a8500c; }}
    .tbg-legend {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 8px; font-size: 0.75em; }}
    .tbg-leg {{ padding: 1px 8px; border-radius: 4px; }}
    .tbg-leg.role-data {{ border: 1px solid var(--border, #e4e4e7); }}
    .tbg-leg.role-col_header {{ background: #d0bfff; color: #3b2a7a; }}
    .tbg-leg.role-row_header {{ background: #a5d8ff; color: #11497a; }}
    .tbg-leg.role-header {{ background: #d0bfff; color: #3b2a7a; }}
    .tbg-leg.role-empty {{ background: var(--secondary, #f4f4f5); color: var(--muted-foreground, #71717a); }}
    .tbg-leg.role-merged {{ background: #ffe8cc; color: #a8500c; }}
    </style>
    """
    logger.info(f"Successfully generated table_grid layout for {schema_name}")
    return html, []
