"""
Per-Agent + Per-Team Scorecard Schema (M5).

Scores a multi-agent run on two levels at once (MultiAgentBench, ACL 2025,
2503.01935): each **agent** gets per-dimension scores (role fidelity, contribution,
coordination), the **team** gets shared-dimension scores, and optional **milestones**
are checked off. Agent rows are derived from the trace's own turns at render time, so
the matrix matches who actually participated.

Stored as a hidden-input JSON object::

    {"agents": {name: {dim: score}}, "team": {dim: score}, "milestones": {name: bool}}

The IIFE seeds itself from the server-restored hidden value BEFORE wiring change
events (persistence contract), so navigate-away/back restores correctly.
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


def generate_agent_scorecard_layout(
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
    static_agents = annotation_scheme.get("agents", [])
    agent_dimensions = annotation_scheme.get(
        "agent_dimensions", ["role fidelity", "contribution", "coordination"]
    )
    team_dimensions = annotation_scheme.get(
        "team_dimensions", ["coordination", "communication", "efficiency"]
    )
    milestones = annotation_scheme.get("milestones", [])
    scale = int(annotation_scheme.get("scale", 5))

    esc_schema = escape_html_content(schema_name)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")

    config_json = json.dumps({
        "steps_key": steps_key, "agent_key": agent_key, "agents": static_agents,
        "agent_dimensions": agent_dimensions, "team_dimensions": team_dimensions,
        "milestones": milestones, "scale": scale,
    })

    html = f"""
    <form id="{esc_schema}" class="annotation-form agent-scorecard-container"
          action="javascript:void(0)"
          data-annotation-type="agent_scorecard"
          data-schema-name="{esc_schema}"
          {layout_attrs}>
        <fieldset schema="{esc_schema}">
            <legend class="asc-title">{escape_html_content(description)}</legend>

            <div class="asc-section">
                <h4 class="asc-heading">Per-agent scores</h4>
                <div class="asc-agent-grid" id="{esc_schema}-agents"></div>
                <div class="asc-empty" id="{esc_schema}-empty" style="display:none;">No agents in this trace.</div>
            </div>

            <div class="asc-section asc-team">
                <h4 class="asc-heading">Team</h4>
                <div class="asc-team-grid" id="{esc_schema}-team"></div>
            </div>

            <div class="asc-section asc-milestones" id="{esc_schema}-ms-wrap" style="display:none;">
                <h4 class="asc-heading">Milestones reached</h4>
                <div id="{esc_schema}-milestones"></div>
            </div>

            <input type="hidden" class="annotation-input agent-scorecard-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>

    <script>
    (function() {{
        var SCHEMA = '{esc_schema}';
        var CONFIG = {config_json};
        var STATE = {{agents: {{}}, team: {{}}, milestones: {{}}}};

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

        function uniqueAgents() {{
            if (CONFIG.agents && CONFIG.agents.length) return CONFIG.agents.slice();
            var steps = instanceData()[CONFIG.steps_key];
            if (!Array.isArray(steps)) return [];
            var seen = [], out = [];
            steps.forEach(function(s, i) {{
                var a = agentOf(s, i);
                if (seen.indexOf(a) < 0) {{ seen.push(a); out.push(a); }}
            }});
            return out;
        }}

        function hidden() {{ return document.getElementById(SCHEMA).querySelector('.agent-scorecard-input'); }}

        function restore() {{
            var h = hidden();
            if (h && h.value) {{ try {{ return JSON.parse(h.value) || {{}}; }} catch(e) {{}} }}
            return {{}};
        }}

        function scaleButtons(group, key, dim, current) {{
            var out = '';
            for (var v = 1; v <= CONFIG.scale; v++) {{
                var on = current === v ? ' selected' : '';
                out += '<button type="button" class="asc-sbtn' + on + '" data-group="' + group +
                    '" data-key="' + esc(key) + '" data-dim="' + esc(dim) + '" data-v="' + v + '">' + v + '</button>';
            }}
            return out;
        }}

        function build() {{
            var prev = restore();
            STATE = {{agents: prev.agents || {{}}, team: prev.team || {{}}, milestones: prev.milestones || {{}}}};
            var agents = uniqueAgents();
            var agWrap = document.getElementById(SCHEMA + '-agents');
            var empty = document.getElementById(SCHEMA + '-empty');

            if (!agents.length) {{ if (agWrap) agWrap.innerHTML=''; if (empty) empty.style.display=''; }}
            else {{
                if (empty) empty.style.display = 'none';
                agWrap.innerHTML = agents.map(function(a) {{
                    var rows = CONFIG.agent_dimensions.map(function(d) {{
                        var cur = (STATE.agents[a] || {{}})[d] || 0;
                        return '<div class="asc-row"><span class="asc-dim">' + esc(d) + '</span>' +
                            '<div class="asc-scale">' + scaleButtons('agents', a, d, cur) + '</div></div>';
                    }}).join('');
                    return '<div class="asc-card"><div class="asc-agent-name">' + esc(a) + '</div>' + rows + '</div>';
                }}).join('');
            }}

            var teamWrap = document.getElementById(SCHEMA + '-team');
            teamWrap.innerHTML = CONFIG.team_dimensions.map(function(d) {{
                var cur = STATE.team[d] || 0;
                return '<div class="asc-row"><span class="asc-dim">' + esc(d) + '</span>' +
                    '<div class="asc-scale">' + scaleButtons('team', '_team', d, cur) + '</div></div>';
            }}).join('');

            if (CONFIG.milestones && CONFIG.milestones.length) {{
                document.getElementById(SCHEMA + '-ms-wrap').style.display = '';
                var msWrap = document.getElementById(SCHEMA + '-milestones');
                msWrap.innerHTML = CONFIG.milestones.map(function(m, i) {{
                    var on = !!STATE.milestones[m];
                    return '<label class="asc-ms"><input type="checkbox" class="asc-ms-cb" data-m="' + esc(m) + '"' +
                        (on ? ' checked' : '') + '> ' + esc(m) + '</label>';
                }}).join('');
            }}

            bind();
        }}

        function bind() {{
            var root = document.getElementById(SCHEMA);
            root.querySelectorAll('.asc-sbtn').forEach(function(b) {{
                b.addEventListener('click', function() {{
                    var group = b.getAttribute('data-group'), key = b.getAttribute('data-key'),
                        dim = b.getAttribute('data-dim'), v = parseInt(b.getAttribute('data-v'), 10);
                    var bucket = group === 'team' ? STATE.team : (STATE.agents[key] = STATE.agents[key] || {{}});
                    var target = group === 'team' ? STATE.team : bucket;
                    if (target[dim] === v) target[dim] = 0; else target[dim] = v;
                    paintGroup(group, key, dim); save();
                }});
            }});
            root.querySelectorAll('.asc-ms-cb').forEach(function(cb) {{
                cb.addEventListener('change', function() {{
                    STATE.milestones[cb.getAttribute('data-m')] = cb.checked; save();
                }});
            }});
        }}

        function paintGroup(group, key, dim) {{
            var bucket = group === 'team' ? STATE.team : (STATE.agents[key] || {{}});
            var cur = bucket[dim] || 0;
            document.getElementById(SCHEMA).querySelectorAll(
                '.asc-sbtn[data-group="' + group + '"][data-key="' + cssEsc(key) + '"][data-dim="' + cssEsc(dim) + '"]'
            ).forEach(function(b) {{
                b.classList.toggle('selected', parseInt(b.getAttribute('data-v'), 10) === cur);
            }});
        }}

        function save() {{
            var data = {{agents: {{}}, team: {{}}, milestones: {{}}}};
            Object.keys(STATE.agents).forEach(function(a) {{
                var dims = {{}}; var any = false;
                Object.keys(STATE.agents[a]).forEach(function(d) {{ if (STATE.agents[a][d]) {{ dims[d] = STATE.agents[a][d]; any = true; }} }});
                if (any) data.agents[a] = dims;
            }});
            Object.keys(STATE.team).forEach(function(d) {{ if (STATE.team[d]) data.team[d] = STATE.team[d]; }});
            Object.keys(STATE.milestones).forEach(function(m) {{ if (STATE.milestones[m]) data.milestones[m] = true; }});
            var empty = !Object.keys(data.agents).length && !Object.keys(data.team).length && !Object.keys(data.milestones).length;
            var h = hidden();
            if (h) {{
                h.value = empty ? '' : JSON.stringify(data);
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
    .agent-scorecard-container {{ font-family: inherit; }}
    .asc-title {{ font-weight: 600; font-size: 1em; margin-bottom: 8px; }}
    .asc-section {{ margin-bottom: 14px; }}
    .asc-heading {{ font-size: 0.8em; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
                    color: var(--muted-foreground, #71717a); margin: 0 0 6px; }}
    .asc-agent-grid {{ display: flex; flex-direction: column; gap: 8px; }}
    .asc-card {{ border: 1px solid var(--border, #e4e4e7); border-radius: var(--radius, 0.5rem);
                 padding: 8px 12px; background: var(--card, #fff); }}
    .asc-agent-name {{ font-weight: 600; font-family: ui-monospace, monospace; margin-bottom: 6px; }}
    .asc-row {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 2px 0; }}
    .asc-dim {{ font-size: 0.85em; color: var(--foreground, #18181b); }}
    .asc-scale {{ display: flex; gap: 4px; }}
    .asc-sbtn {{ width: 28px; height: 28px; border: 1px solid var(--border, #e4e4e7);
                 border-radius: 6px; background: var(--card, #fff); cursor: pointer; font-size: 0.85em;
                 color: var(--foreground, #18181b); }}
    .asc-sbtn:hover {{ background: var(--secondary, #f4f4f5); }}
    .asc-sbtn:focus-visible {{ outline: 2px solid var(--ring, #6e56cf); outline-offset: 1px; }}
    .asc-sbtn.selected {{ background: var(--ring, #6e56cf); color: #fff; border-color: var(--ring, #6e56cf); font-weight: 600; }}
    .asc-team-grid {{ border: 1px solid var(--border, #e4e4e7); border-radius: var(--radius, 0.5rem);
                      padding: 8px 12px; background: var(--secondary, #f9f9fb); }}
    .asc-ms {{ display: block; font-size: 0.9em; padding: 3px 0; cursor: pointer; }}
    .asc-ms input {{ margin-right: 6px; }}
    .asc-empty {{ color: var(--muted-foreground, #71717a); font-style: italic; }}
    </style>
    """
    logger.info(f"Successfully generated agent_scorecard layout for {schema_name}")
    return html, []
