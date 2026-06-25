"""
Agent-Interaction-Graph Schema (M3).

Renders a multi-agent run as a directed **interaction graph** — nodes are the
agents, edges are the message/handoff transitions between them (weighted by how
often they occur) — and lets the annotator mark the **critical path** (click nodes)
and flag **problematic edges** (click edges → cycle none → critical → problematic).
The biggest differentiator in the M-series: no open competitor offers a clickable
agent-interaction graph (cf. AgentGraph, AAAI 2026).

The graph is derived from the trace's own turns at render time (circular layout, so
it needs no precomputed coordinates). Stored as a hidden-input JSON object::

    {"critical_nodes": ["Planner", ...], "edges": {"Planner->Coder": "problematic", ...}}

Accessibility: every node and edge is keyboard-focusable (tabindex) and activates on
Enter/Space; a live text summary lists critical nodes and flagged edges so the
meaning is never conveyed by color alone. The IIFE seeds from the server-restored
hidden value before wiring events (persistence contract).
"""

import json
import logging
from typing import Any, Dict, List, Tuple

from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_validation_attribute,
    escape_html_content,
    generate_layout_attributes,
)

logger = logging.getLogger(__name__)


def generate_agent_interaction_graph_layout(
    annotation_scheme: Dict[str, Any],
) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(
    annotation_scheme: Dict[str, Any],
) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    description = annotation_scheme["description"]
    steps_key = annotation_scheme.get("steps_key", "steps")
    agent_key = annotation_scheme.get("agent_key", "agent")

    esc_schema = escape_html_content(schema_name)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")

    config_json = json.dumps({"steps_key": steps_key, "agent_key": agent_key})

    html = f"""
    <form id="{esc_schema}" class="annotation-form agent-graph-container"
          action="javascript:void(0)"
          data-annotation-type="agent_interaction_graph"
          data-schema-name="{esc_schema}"
          {layout_attrs}>
        <fieldset schema="{esc_schema}">
            <legend class="aig-title">{escape_html_content(description)}</legend>
            <p class="aig-help">Click an <strong>agent</strong> to mark it on the critical path. Click an
               <strong>edge</strong> to cycle its status: normal → critical → problematic.</p>
            <div class="aig-canvas-wrap">
                <svg class="aig-svg" id="{esc_schema}-svg" viewBox="0 0 420 340"
                     role="group" aria-label="Agent interaction graph"></svg>
            </div>
            <div class="aig-empty" id="{esc_schema}-empty" style="display:none;">No agent interactions in this trace.</div>
            <div class="aig-summary" id="{esc_schema}-summary" aria-live="polite"></div>
            <input type="hidden" class="annotation-input agent-graph-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>

    <script>
    (function() {{
        var SCHEMA = '{esc_schema}';
        var CONFIG = {config_json};
        var SVGNS = 'http://www.w3.org/2000/svg';
        var STATE = {{critical_nodes: [], edges: {{}}}};   // edges: "A->B" -> "critical"|"problematic"
        var EDGE_CYCLE = ['', 'critical', 'problematic'];

        function instanceData() {{
            try {{
                var el = document.querySelector('[data-instance-json]');
                if (el) return JSON.parse(el.getAttribute('data-instance-json'));
            }} catch(e) {{}}
            var t = document.getElementById('text-content') || document.getElementById('instance-text');
            if (t) {{ try {{ return JSON.parse(t.textContent || t.innerText); }} catch(e2) {{}} }}
            return {{}};
        }}

        function agentOf(s, i) {{
            if (s && typeof s === 'object') return s[CONFIG.agent_key] || s.speaker || s.role || ('agent ' + (i+1));
            return 'agent ' + (i+1);
        }}

        function buildGraph() {{
            var steps = instanceData()[CONFIG.steps_key];
            if (!Array.isArray(steps)) return {{nodes: [], edges: []}};
            var nodes = [], seen = {{}}, edgeMap = {{}}, prev = null;
            steps.forEach(function(s, i) {{
                var a = agentOf(s, i);
                if (!seen[a]) {{ seen[a] = true; nodes.push(a); }}
                if (prev !== null && prev !== a) {{
                    var k = prev + '->' + a;
                    edgeMap[k] = (edgeMap[k] || 0) + 1;
                }}
                prev = a;
            }});
            var edges = Object.keys(edgeMap).map(function(k) {{
                var p = k.split('->'); return {{key: k, from: p[0], to: p[1], count: edgeMap[k]}};
            }});
            return {{nodes: nodes, edges: edges}};
        }}

        function hidden() {{ return document.getElementById(SCHEMA).querySelector('.agent-graph-input'); }}

        function restore() {{
            var h = hidden();
            if (h && h.value) {{ try {{ return JSON.parse(h.value) || {{}}; }} catch(e) {{}} }}
            return {{}};
        }}

        function el(tag, attrs) {{
            var n = document.createElementNS(SVGNS, tag);
            for (var k in attrs) n.setAttribute(k, attrs[k]);
            return n;
        }}

        function build() {{
            var g = buildGraph();
            var svg = document.getElementById(SCHEMA + '-svg');
            var empty = document.getElementById(SCHEMA + '-empty');
            if (!svg) return;
            svg.innerHTML = '';
            if (!g.nodes.length) {{ if (empty) empty.style.display = ''; document.getElementById(SCHEMA + '-summary').innerHTML=''; return; }}
            if (empty) empty.style.display = 'none';

            var prev = restore();
            var validNodes = {{}}; g.nodes.forEach(function(n) {{ validNodes[n] = true; }});
            var validEdges = {{}}; g.edges.forEach(function(e) {{ validEdges[e.key] = true; }});
            STATE.critical_nodes = (prev.critical_nodes || []).filter(function(n) {{ return validNodes[n]; }});
            STATE.edges = {{}};
            if (prev.edges) Object.keys(prev.edges).forEach(function(k) {{ if (validEdges[k]) STATE.edges[k] = prev.edges[k]; }});

            // Circular layout.
            var cx = 210, cy = 165, R = g.nodes.length === 1 ? 0 : 120, NR = 30;
            var pos = {{}};
            g.nodes.forEach(function(n, i) {{
                var ang = -Math.PI/2 + (2*Math.PI*i)/g.nodes.length;
                pos[n] = {{x: cx + R*Math.cos(ang), y: cy + R*Math.sin(ang)}};
            }});

            // Arrow markers (one per state).
            var defs = el('defs', {{}});
            [['arrow', '#9ca3af'], ['arrow-critical', '#6e56cf'], ['arrow-problematic', '#e03131']].forEach(function(m) {{
                var mk = el('marker', {{id: SCHEMA + '-' + m[0], viewBox: '0 0 10 10', refX: '9', refY: '5',
                    markerWidth: '7', markerHeight: '7', orient: 'auto-start-reverse'}});
                mk.appendChild(el('path', {{d: 'M0,0 L10,5 L0,10 z', fill: m[1]}}));
                defs.appendChild(mk);
            }});
            svg.appendChild(defs);

            // Edges (drawn first, under nodes).
            g.edges.forEach(function(e) {{
                var a = pos[e.from], b = pos[e.to];
                if (!a || !b) return;
                var dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
                var ux = dx/len, uy = dy/len;
                // Trim to node edges, and offset perpendicular so A->B and B->A don't overlap.
                var ox = -uy * 10, oy = ux * 10;
                var sx = a.x + ux*NR + ox, sy = a.y + uy*NR + oy;
                var ex = b.x - ux*NR + ox, ey = b.y - uy*NR + oy;
                var mx = (sx+ex)/2 + ox*1.2, my = (sy+ey)/2 + oy*1.2;
                var st = STATE.edges[e.key] || '';
                var path = el('path', {{
                    d: 'M' + sx + ',' + sy + ' Q' + mx + ',' + my + ' ' + ex + ',' + ey,
                    class: 'aig-edge aig-edge-' + (st || 'normal'),
                    fill: 'none', 'stroke-width': Math.min(2 + e.count, 6),
                    'marker-end': 'url(#' + SCHEMA + '-' + (st === 'critical' ? 'arrow-critical' : st === 'problematic' ? 'arrow-problematic' : 'arrow') + ')',
                    tabindex: '0', role: 'button',
                    'aria-label': e.from + ' to ' + e.to + ' (' + e.count + ' message' + (e.count>1?'s':'') + '), status: ' + (st || 'normal')
                }});
                path.setAttribute('data-edge', e.key);
                var ttl = el('title', {{}}); ttl.textContent = e.from + ' → ' + e.to + ' ×' + e.count; path.appendChild(ttl);
                svg.appendChild(path);
            }});

            // Nodes.
            g.nodes.forEach(function(n) {{
                var p = pos[n];
                var grp = el('g', {{class: 'aig-node', tabindex: '0', role: 'button',
                    'aria-pressed': STATE.critical_nodes.indexOf(n) >= 0 ? 'true' : 'false',
                    'aria-label': 'Agent ' + n + (STATE.critical_nodes.indexOf(n)>=0 ? ' (on critical path)' : '')}});
                grp.setAttribute('data-node', n);
                var circ = el('circle', {{cx: p.x, cy: p.y, r: NR, class: 'aig-node-circle'}});
                grp.appendChild(circ);
                var label = el('text', {{x: p.x, y: p.y, class: 'aig-node-label',
                    'text-anchor': 'middle', 'dominant-baseline': 'central'}});
                label.textContent = n.length > 8 ? n.slice(0, 7) + '…' : n;
                var ttl = el('title', {{}}); ttl.textContent = n; grp.appendChild(ttl);
                grp.appendChild(label);
                svg.appendChild(grp);
            }});

            wire(svg);
            paint();
            renderSummary(g);
        }}

        function wire(svg) {{
            svg.querySelectorAll('.aig-node').forEach(function(grp) {{
                var n = grp.getAttribute('data-node');
                function toggle() {{
                    var i = STATE.critical_nodes.indexOf(n);
                    if (i >= 0) STATE.critical_nodes.splice(i, 1); else STATE.critical_nodes.push(n);
                    paint(); save(); renderSummary(buildGraph());
                }}
                grp.addEventListener('click', toggle);
                grp.addEventListener('keydown', function(ev) {{
                    if (ev.key === 'Enter' || ev.key === ' ') {{ ev.preventDefault(); toggle(); }}
                }});
            }});
            svg.querySelectorAll('.aig-edge').forEach(function(path) {{
                var k = path.getAttribute('data-edge');
                function cycle() {{
                    var cur = STATE.edges[k] || '';
                    var next = EDGE_CYCLE[(EDGE_CYCLE.indexOf(cur) + 1) % EDGE_CYCLE.length];
                    if (next) STATE.edges[k] = next; else delete STATE.edges[k];
                    // Persist BEFORE re-rendering: build() repopulates STATE from the hidden
                    // value, so it must reflect this change first or the cycle is lost.
                    save();
                    build();   // re-render to refresh the edge marker/colour cleanly
                }}
                path.addEventListener('click', cycle);
                path.addEventListener('keydown', function(ev) {{
                    if (ev.key === 'Enter' || ev.key === ' ') {{ ev.preventDefault(); cycle(); }}
                }});
            }});
        }}

        function paint() {{
            var svg = document.getElementById(SCHEMA + '-svg');
            svg.querySelectorAll('.aig-node').forEach(function(grp) {{
                var n = grp.getAttribute('data-node');
                var on = STATE.critical_nodes.indexOf(n) >= 0;
                grp.classList.toggle('aig-node-critical', on);
                grp.setAttribute('aria-pressed', on ? 'true' : 'false');
            }});
        }}

        function renderSummary(g) {{
            var box = document.getElementById(SCHEMA + '-summary');
            if (!box) return;
            var parts = [];
            if (STATE.critical_nodes.length)
                parts.push('<div class="aig-sum-line"><span class="aig-chip aig-chip-critical">critical path</span> ' +
                    STATE.critical_nodes.map(esc).join(' · ') + '</div>');
            var flagged = Object.keys(STATE.edges);
            if (flagged.length) {{
                parts.push('<div class="aig-sum-line"><span class="aig-chip aig-chip-problematic">flagged edges</span> ' +
                    flagged.map(function(k) {{
                        var label = k.replace('->', ' → ');
                        return esc(label) + ' (' + esc(STATE.edges[k]) + ')';
                    }}).join(' · ') + '</div>');
            }}
            box.innerHTML = parts.length ? parts.join('') : '<span class="aig-sum-none">Nothing marked yet.</span>';
        }}

        function save() {{
            var data = {{}};
            if (STATE.critical_nodes.length) data.critical_nodes = STATE.critical_nodes.slice();
            if (Object.keys(STATE.edges).length) data.edges = JSON.parse(JSON.stringify(STATE.edges));
            var h = hidden();
            if (h) {{
                h.value = Object.keys(data).length ? JSON.stringify(data) : '';
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
    .agent-graph-container {{ font-family: inherit; }}
    .aig-title {{ font-weight: 600; font-size: 1em; margin-bottom: 4px; }}
    .aig-help {{ font-size: 0.82em; color: var(--muted-foreground, #71717a); margin: 0 0 8px; }}
    .aig-canvas-wrap {{ border: 1px solid var(--border, #e4e4e7); border-radius: var(--radius, 0.5rem);
                        background: var(--card, #fff); padding: 4px; }}
    .aig-svg {{ width: 100%; height: auto; display: block; max-height: 340px; }}
    .aig-node {{ cursor: pointer; }}
    .aig-node-circle {{ fill: var(--secondary, #f4f4f5); stroke: var(--border, #c7c7cc); stroke-width: 1.5; transition: fill 0.12s, stroke 0.12s; }}
    .aig-node:hover .aig-node-circle {{ stroke: var(--ring, #6e56cf); }}
    .aig-node:focus-visible {{ outline: none; }}
    .aig-node:focus-visible .aig-node-circle {{ stroke: var(--ring, #6e56cf); stroke-width: 3; }}
    .aig-node-label {{ font-size: 11px; font-family: ui-monospace, monospace; fill: var(--foreground, #18181b); pointer-events: none; }}
    .aig-node-critical .aig-node-circle {{ fill: #6e56cf; stroke: #4c3a9e; }}
    .aig-node-critical .aig-node-label {{ fill: #fff; }}
    .aig-edge {{ stroke: #9ca3af; cursor: pointer; }}
    .aig-edge:hover {{ stroke: var(--ring, #6e56cf); }}
    .aig-edge:focus-visible {{ outline: none; stroke: var(--ring, #6e56cf); stroke-dasharray: 4 3; }}
    .aig-edge-critical {{ stroke: #6e56cf; }}
    .aig-edge-problematic {{ stroke: #e03131; stroke-dasharray: 5 4; }}
    .aig-empty {{ color: var(--muted-foreground, #71717a); font-style: italic; margin-top: 6px; }}
    .aig-summary {{ margin-top: 8px; font-size: 0.85em; }}
    .aig-sum-line {{ margin: 3px 0; }}
    .aig-sum-none {{ color: var(--muted-foreground, #71717a); }}
    .aig-chip {{ display: inline-block; font-size: 0.72em; font-weight: 700; text-transform: uppercase;
                 letter-spacing: 0.03em; padding: 1px 7px; border-radius: 999px; margin-right: 6px; color: #fff; }}
    .aig-chip-critical {{ background: #6e56cf; }}
    .aig-chip-problematic {{ background: #e03131; }}
    </style>
    """
    logger.info(f"Successfully generated agent_interaction_graph layout for {schema_name}")
    return html, []
