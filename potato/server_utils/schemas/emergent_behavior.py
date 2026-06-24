"""
Cross-Lane Emergent-Behavior Schema (M7).

Tags **collective / emergent behaviors** that span multiple turns and agents —
collusion, groupthink, cascading errors, role drift (collective-behavior work,
2604.05339). Unlike a contiguous text span, an emergent behavior is a *set* of
participating turns (possibly from different agents / lanes), so this schema lets the
annotator check the turns that participate in each behavior and add a note — a
"cross-lane span" expressed as a turn-set rather than a character range, which keeps
it independent of (and safe for) the core span engine.

Turns are read from the trace at render time. Stored as a hidden-input JSON object
``{behavior: {turns: [idx...], note}}`` (only non-empty behaviors). The IIFE seeds
from the server-restored hidden value before wiring events (persistence contract).
"""

import json
import logging
from typing import Any, Dict, List, Tuple

from .identifier_utils import (
    safe_generate_layout, generate_element_identifier,
    generate_validation_attribute, escape_html_content, generate_layout_attributes,
)

logger = logging.getLogger(__name__)


def generate_emergent_behavior_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    description = annotation_scheme["description"]
    steps_key = annotation_scheme.get("steps_key", "steps")
    agent_key = annotation_scheme.get("agent_key", "agent")
    behaviors = annotation_scheme.get(
        "behaviors", ["collusion", "groupthink", "cascading_error", "role_drift"])
    allow_note = annotation_scheme.get("allow_note", True)
    esc_schema = escape_html_content(schema_name)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    config_json = json.dumps({
        "steps_key": steps_key, "agent_key": agent_key,
        "behaviors": behaviors, "allow_note": bool(allow_note)})

    html = f"""
    <form id="{esc_schema}" class="annotation-form emergent-behavior-container"
          action="javascript:void(0)" data-annotation-type="emergent_behavior"
          data-schema-name="{esc_schema}" {layout_attrs}>
        <fieldset schema="{esc_schema}">
            <legend class="eb-title">{escape_html_content(description)}</legend>
            <div class="eb-list" id="{esc_schema}-list"></div>
            <div class="eb-empty" id="{esc_schema}-empty" style="display:none;">No turns in this trace.</div>
            <input type="hidden" class="annotation-input emergent-behavior-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>

    <script>
    (function() {{
        var SCHEMA = '{esc_schema}';
        var CONFIG = {config_json};
        var STATE = {{}};   // behavior -> {{turns:[], note}}
        var _turns = [];

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
        function textOf(s) {{
            if (s && typeof s === 'object') return s.content || s.text || s.action || '';
            return s == null ? '' : String(s);
        }}

        function getTurns() {{
            var s = instanceData()[CONFIG.steps_key];
            if (!Array.isArray(s)) return [];
            return s.map(function(x, i) {{ return {{i: i, agent: agentOf(x, i), text: textOf(x)}}; }});
        }}

        function hidden() {{ return document.getElementById(SCHEMA).querySelector('.emergent-behavior-input'); }}
        function restore() {{
            var h = hidden();
            if (h && h.value) {{ try {{ return JSON.parse(h.value) || {{}}; }} catch(e) {{}} }}
            return {{}};
        }}

        function build() {{
            _turns = getTurns();
            var prev = restore();
            STATE = {{}};
            CONFIG.behaviors.forEach(function(b) {{
                var p = prev[b] || {{}};
                STATE[b] = {{turns: Array.isArray(p.turns) ? p.turns.slice() : [], note: p.note || ''}};
            }});

            var list = document.getElementById(SCHEMA + '-list');
            var empty = document.getElementById(SCHEMA + '-empty');
            if (!_turns.length) {{ list.innerHTML = ''; if (empty) empty.style.display = ''; return; }}
            if (empty) empty.style.display = 'none';

            list.innerHTML = CONFIG.behaviors.map(function(b) {{
                var checks = _turns.map(function(t) {{
                    var on = STATE[b].turns.indexOf(t.i) >= 0;
                    return '<label class="eb-turn' + (on ? ' eb-turn-on' : '') + '" title="' + esc(t.text) + '">' +
                        '<input type="checkbox" class="eb-cb" data-b="' + esc(b) + '" data-t="' + t.i + '"' + (on ? ' checked' : '') + '>' +
                        '<span class="eb-turn-n">' + (t.i+1) + '</span>' +
                        '<span class="eb-turn-a">' + esc(t.agent) + '</span></label>'; }}).join('');
                var note = CONFIG.allow_note ?
                    '<input type="text" class="eb-note" data-b="' + esc(b) + '" placeholder="note (optional)" value="' + esc(STATE[b].note) + '">' : '';
                return '<div class="eb-block" data-b="' + esc(b) + '">' +
                    '<div class="eb-bhead"><span class="eb-bname">' + esc(b.replace(/_/g,' ')) + '</span>' +
                    '<span class="eb-count" data-b="' + esc(b) + '"></span></div>' +
                    '<div class="eb-turns">' + checks + '</div>' + note + '</div>'; }}).join('');

            var root = document.getElementById(SCHEMA);
            root.querySelectorAll('.eb-cb').forEach(function(cb) {{
                cb.addEventListener('change', function() {{
                    var b = cb.getAttribute('data-b'), t = parseInt(cb.getAttribute('data-t'), 10);
                    var arr = STATE[b].turns, p = arr.indexOf(t);
                    if (cb.checked && p < 0) arr.push(t);
                    else if (!cb.checked && p >= 0) arr.splice(p, 1);
                    cb.closest('.eb-turn').classList.toggle('eb-turn-on', cb.checked);
                    paint(b); save();
                }});
            }});
            root.querySelectorAll('.eb-note').forEach(function(inp) {{
                inp.addEventListener('input', function() {{
                    STATE[inp.getAttribute('data-b')].note = inp.value; save();
                }});
            }});
            CONFIG.behaviors.forEach(paint);
        }}

        function paint(b) {{
            var n = STATE[b].turns.length;
            var block = document.querySelector('.eb-block[data-b="' + cssEsc(b) + '"]');
            if (block) block.classList.toggle('eb-active', n > 0);
            var c = document.querySelector('.eb-count[data-b="' + cssEsc(b) + '"]');
            if (c) c.textContent = n ? (n + ' turn' + (n>1?'s':'')) : '';
        }}

        function save() {{
            var data = {{}};
            CONFIG.behaviors.forEach(function(b) {{
                var s = STATE[b];
                if (s.turns.length || s.note) data[b] = {{turns: s.turns.slice().sort(function(x,y){{return x-y;}}), note: s.note}};
            }});
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
    .emergent-behavior-container {{ font-family: inherit; }}
    .eb-title {{ font-weight: 600; font-size: 1em; margin-bottom: 6px; }}
    .eb-list {{ display: flex; flex-direction: column; gap: 8px; }}
    .eb-block {{ border: 1px solid var(--border, #e4e4e7); border-radius: var(--radius, 0.5rem);
                 padding: 8px 12px; background: var(--card, #fff); }}
    .eb-block.eb-active {{ border-color: var(--ring, #6e56cf); box-shadow: inset 3px 0 0 var(--ring, #6e56cf); }}
    .eb-bhead {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }}
    .eb-bname {{ font-weight: 600; text-transform: capitalize; }}
    .eb-count {{ font-size: 0.75em; color: var(--ring, #6e56cf); font-weight: 600; }}
    .eb-turns {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    .eb-turn {{ display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border: 1px solid var(--border, #e4e4e7);
                border-radius: 999px; cursor: pointer; font-size: 0.78em; background: var(--card, #fff); }}
    .eb-turn:hover {{ background: var(--secondary, #f4f4f5); }}
    .eb-turn input {{ margin: 0; }}
    .eb-turn-on {{ background: #ede9fe; border-color: var(--ring, #6e56cf); }}
    .eb-turn-n {{ font-weight: 700; font-family: ui-monospace, monospace; }}
    .eb-turn-a {{ color: var(--muted-foreground, #71717a); }}
    .eb-turn:focus-within {{ outline: 2px solid var(--ring, #6e56cf); outline-offset: 1px; }}
    .eb-note {{ margin-top: 6px; width: 100%; box-sizing: border-box; padding: 4px 8px;
                border: 1px solid var(--border, #e4e4e7); border-radius: 6px; font-size: 0.85em; }}
    .eb-empty {{ color: var(--muted-foreground, #71717a); font-style: italic; }}
    </style>
    """
    logger.info(f"Successfully generated emergent_behavior layout for {schema_name}")
    return html, []
