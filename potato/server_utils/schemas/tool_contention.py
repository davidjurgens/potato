"""
Tool / Resource-Contention Timeline Schema (M8).

Visualizes concurrent tool/resource use across agents on a multi-lane timeline and
asks the annotator to flag concurrency failures — deadlock, circular wait, race
conditions, shared-resource collisions (DPBench, 2602.13255). Lanes are agents; each
tool call is placed by its ``start``/``end`` time; **contention regions** are where
two calls touch the **same shared resource** at overlapping times, and are
highlighted for classification.

Input per instance: a ``calls`` list of
``{agent, tool, start, end, resource}`` (seconds). Contentions are computed at render
time (same ``resource``, overlapping interval, different call). Stored as a
hidden-input JSON object ``{"contentions": {idx: label}}`` keyed by a stable index
over the sorted contention list. The IIFE seeds from the server-restored hidden value
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


def generate_tool_contention_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    description = annotation_scheme["description"]
    calls_key = annotation_scheme.get("calls_key", "calls")
    agent_key = annotation_scheme.get("agent_key", "agent")
    resource_key = annotation_scheme.get("resource_key", "resource")
    contention_labels = annotation_scheme.get(
        "contention_labels", ["deadlock", "circular_wait", "race_condition", "benign"])
    esc_schema = escape_html_content(schema_name)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    config_json = json.dumps({
        "calls_key": calls_key, "agent_key": agent_key, "resource_key": resource_key,
        "contention_labels": contention_labels})

    html = f"""
    <form id="{esc_schema}" class="annotation-form tool-contention-container"
          action="javascript:void(0)" data-annotation-type="tool_contention"
          data-schema-name="{esc_schema}" {layout_attrs}>
        <fieldset schema="{esc_schema}">
            <legend class="tc-title">{escape_html_content(description)}</legend>
            <div class="tc-timeline-wrap" id="{esc_schema}-twrap"></div>
            <div class="tc-head" id="{esc_schema}-head" style="display:none;">Resource contentions</div>
            <div class="tc-list" id="{esc_schema}-list"></div>
            <div class="tc-none" id="{esc_schema}-none" style="display:none;">No shared-resource contention detected.</div>
            <input type="hidden" class="annotation-input tool-contention-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>

    <script>
    (function() {{
        var SCHEMA = '{esc_schema}';
        var CONFIG = {config_json};
        var STATE = {{contentions: {{}}}};
        var _cont = [];

        function instanceData() {{
            try {{
                var el = document.querySelector('[data-instance-json]');
                if (el) return JSON.parse(el.getAttribute('data-instance-json'));
            }} catch(e) {{}}
            var t = document.getElementById('text-content') || document.getElementById('instance-text');
            if (t) {{ try {{ return JSON.parse(t.textContent || t.innerText); }} catch(e2) {{}} }}
            return {{}};
        }}

        function getCalls() {{
            var c = instanceData()[CONFIG.calls_key];
            if (!Array.isArray(c)) return [];
            return c.map(function(x, i) {{
                x = (x && typeof x === 'object') ? x : {{}};
                return {{i: i, agent: String(x[CONFIG.agent_key] || x.role || 'agent'),
                         tool: x.tool || x.name || 'tool',
                         resource: x[CONFIG.resource_key] || x.lock || '',
                         start: +(x.start || 0), end: +(x.end || x.start || 0)}};
            }}).filter(function(c) {{ return c.end >= c.start; }});
        }}

        function computeContentions(calls) {{
            var out = [];
            for (var a = 0; a < calls.length; a++) {{
                for (var b = a+1; b < calls.length; b++) {{
                    if (!calls[a].resource || calls[a].resource !== calls[b].resource) continue;
                    var s = Math.max(calls[a].start, calls[b].start);
                    var e = Math.min(calls[a].end, calls[b].end);
                    if (e > s) out.push({{start: s, end: e, resource: calls[a].resource,
                                          aAgent: calls[a].agent, aTool: calls[a].tool,
                                          bAgent: calls[b].agent, bTool: calls[b].tool}});
                }}
            }}
            out.sort(function(p, q) {{ return p.start - q.start; }});
            return out.map(function(o, idx) {{ o.idx = idx; return o; }});
        }}

        function hidden() {{ return document.getElementById(SCHEMA).querySelector('.tool-contention-input'); }}
        function restore() {{
            var h = hidden();
            if (h && h.value) {{ try {{ return JSON.parse(h.value) || {{}}; }} catch(e) {{}} }}
            return {{}};
        }}

        function build() {{
            var calls = getCalls();
            var prev = restore();
            STATE = {{contentions: prev.contentions || {{}}}};

            // Multi-lane timeline (one lane per agent).
            var twrap = document.getElementById(SCHEMA + '-twrap');
            var agents = [];
            calls.forEach(function(c) {{ if (agents.indexOf(c.agent) < 0) agents.push(c.agent); }});
            var maxT = calls.reduce(function(m, c) {{ return Math.max(m, c.end); }}, 0) || 1;
            twrap.innerHTML = agents.map(function(ag) {{
                return '<div class="tc-lane-row"><span class="tc-lane-label">' + esc(ag) +
                    '</span><div class="tc-lane" data-agent="' + esc(ag) + '"></div></div>';
            }}).join('');
            calls.forEach(function(c) {{
                var lane = twrap.querySelector('.tc-lane[data-agent="' + cssEsc(c.agent) + '"]');
                if (!lane) return;
                var blk = document.createElement('div');
                blk.className = 'tc-call';
                blk.style.left = (100 * c.start / maxT) + '%';
                blk.style.width = Math.max(2, 100 * (c.end - c.start) / maxT) + '%';
                blk.title = c.tool + (c.resource ? ' [' + c.resource + ']' : '') + ' ' + c.start + '–' + c.end + 's';
                blk.textContent = c.tool;
                lane.appendChild(blk);
            }});

            _cont = computeContentions(calls);
            var head = document.getElementById(SCHEMA + '-head');
            var none = document.getElementById(SCHEMA + '-none');
            var list = document.getElementById(SCHEMA + '-list');
            if (!_cont.length) {{ list.innerHTML = ''; head.style.display = 'none'; none.style.display = ''; }}
            else {{
                head.style.display = ''; none.style.display = 'none';
                // Contention bands across all lanes.
                _cont.forEach(function(o) {{
                    twrap.querySelectorAll('.tc-lane').forEach(function(lane) {{
                        var band = document.createElement('div');
                        band.className = 'tc-band';
                        band.style.left = (100 * o.start / maxT) + '%';
                        band.style.width = Math.max(1, 100 * (o.end - o.start) / maxT) + '%';
                        lane.appendChild(band);
                    }});
                }});
                list.innerHTML = _cont.map(function(o) {{
                    var pills = CONFIG.contention_labels.map(function(l) {{
                        return '<button type="button" class="tc-lbtn" data-idx="' + o.idx + '" data-l="' + esc(l) + '">' +
                            esc(l.replace(/_/g,' ')) + '</button>'; }}).join('');
                    return '<div class="tc-card" data-idx="' + o.idx + '">' +
                        '<div class="tc-chead"><span class="tc-res">' + esc(o.resource) + '</span>' +
                        '<span class="tc-ctime">' + o.start.toFixed(1) + '–' + o.end.toFixed(1) + 's</span></div>' +
                        '<div class="tc-pair">' + esc(o.aAgent) + ':' + esc(o.aTool) + ' ⟷ ' +
                        esc(o.bAgent) + ':' + esc(o.bTool) + '</div>' +
                        '<div class="tc-pills">' + pills + '</div></div>'; }}).join('');
            }}
            bind(); paint();
        }}

        function bind() {{
            document.getElementById(SCHEMA).querySelectorAll('.tc-lbtn').forEach(function(b) {{
                b.addEventListener('click', function() {{
                    var i = b.getAttribute('data-idx'), l = b.getAttribute('data-l');
                    STATE.contentions[i] = (STATE.contentions[i] === l) ? '' : l;
                    if (!STATE.contentions[i]) delete STATE.contentions[i];
                    paint(); save();
                }});
            }});
        }}

        function paint() {{
            document.getElementById(SCHEMA).querySelectorAll('.tc-card').forEach(function(card) {{
                var i = card.getAttribute('data-idx'), sel = STATE.contentions[i] || '';
                card.classList.toggle('tc-judged', !!sel);
                card.querySelectorAll('.tc-lbtn').forEach(function(b) {{
                    var on = b.getAttribute('data-l') === sel;
                    b.classList.toggle('selected', on);
                    b.classList.toggle('v-benign', on && b.getAttribute('data-l') === 'benign');
                    b.classList.toggle('v-bad', on && b.getAttribute('data-l') !== 'benign');
                }});
            }});
        }}

        function save() {{
            var data = {{}};
            if (Object.keys(STATE.contentions).length) data.contentions = JSON.parse(JSON.stringify(STATE.contentions));
            var h = hidden();
            if (h) {{
                h.value = Object.keys(data).length ? JSON.stringify(data) : '';
                h.setAttribute('data-modified', 'true');
                h.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
        }}

        function esc(t) {{ var d = document.createElement('div'); d.textContent = (t==null?'':t); return d.innerHTML; }}
        function cssEsc(s) {{ return String(s).replace(/["\\\\]/g, '\\\\$&'); }}

        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
        else build();
        document.addEventListener('instanceChanged', build);
    }})();
    </script>

    <style>
    .tool-contention-container {{ font-family: inherit; }}
    .tc-title {{ font-weight: 600; font-size: 1em; margin-bottom: 6px; }}
    .tc-timeline-wrap {{ display: flex; flex-direction: column; gap: 4px; border: 1px solid var(--border, #e4e4e7);
                         border-radius: 6px; padding: 8px; background: var(--card, #fff); }}
    .tc-lane-row {{ display: flex; align-items: center; gap: 8px; }}
    .tc-lane-label {{ width: 90px; flex-shrink: 0; font-size: 0.75em; font-family: ui-monospace, monospace;
                      text-align: right; color: var(--muted-foreground, #71717a); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .tc-lane {{ position: relative; flex: 1; height: 26px; background: var(--secondary, #f4f4f5); border-radius: 4px; overflow: hidden; }}
    .tc-call {{ position: absolute; top: 3px; height: 20px; background: #6e56cf; color: #fff; border-radius: 3px;
                font-size: 0.68em; line-height: 20px; padding: 0 4px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }}
    .tc-band {{ position: absolute; top: 0; bottom: 0; background: rgba(224,49,49,0.22);
                border-left: 1px solid #e03131; border-right: 1px solid #e03131; pointer-events: none; }}
    .tc-head {{ margin: 10px 0 4px; font-size: 0.78em; font-weight: 700; text-transform: uppercase;
                letter-spacing: 0.03em; color: var(--muted-foreground, #71717a); }}
    .tc-list {{ display: flex; flex-direction: column; gap: 8px; }}
    .tc-card {{ border: 1px solid var(--border, #e4e4e7); border-radius: var(--radius, 0.5rem);
                padding: 8px 12px; background: var(--card, #fff); }}
    .tc-card.tc-judged {{ border-color: var(--ring, #6e56cf); }}
    .tc-chead {{ display: flex; justify-content: space-between; align-items: baseline; }}
    .tc-res {{ font-family: ui-monospace, monospace; font-weight: 600; color: #e03131; }}
    .tc-ctime {{ font-size: 0.78em; color: var(--muted-foreground, #71717a); }}
    .tc-pair {{ font-size: 0.85em; margin: 4px 0; font-family: ui-monospace, monospace; }}
    .tc-pills {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    .tc-lbtn {{ padding: 3px 10px; font-size: 0.8em; border: 1px solid var(--border, #e4e4e7);
                border-radius: 999px; background: var(--card, #fff); cursor: pointer; color: var(--foreground, #18181b); }}
    .tc-lbtn:hover {{ background: var(--secondary, #f4f4f5); }}
    .tc-lbtn:focus-visible {{ outline: 2px solid var(--ring, #6e56cf); outline-offset: 1px; }}
    .tc-lbtn.selected {{ font-weight: 600; }}
    .tc-lbtn.selected.v-benign {{ background: #4caf50; color: #fff; border-color: #4caf50; }}
    .tc-lbtn.selected.v-bad {{ background: #e03131; color: #fff; border-color: #e03131; }}
    .tc-none {{ color: var(--muted-foreground, #71717a); font-style: italic; margin: 8px 0; }}
    </style>
    """
    logger.info(f"Successfully generated tool_contention layout for {schema_name}")
    return html, []
