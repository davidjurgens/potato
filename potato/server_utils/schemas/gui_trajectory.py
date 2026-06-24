"""
GUI / Computer-Use Trajectory Schema (M11).

Evaluates a computer-use / GUI / OS agent step by step (OSWorld, NeurIPS 2024;
ScreenSpot-Pro; AndroidWorld). Each step shows the **screenshot** the agent saw and
the **action** it took (click / type / scroll / key); the annotator judges the
action and, when the action has click coordinates, sees a grounding marker overlaid
on the screenshot so they can check whether the click landed on the right element.
Generalizes the web-agent display beyond browsing to any pixel/DOM GUI agent.

Steps are read from the trace at render time. Each step may provide:
``screenshot`` (image URL/data-URI), ``action`` (text), and optional ``x``/``y``
(0..1 normalized, or pixels with ``coord_space: pixels``) for the grounding marker.
Stored as a hidden-input JSON list ``[{index, verdict, notes}]`` keyed by ``index``
(saved is a filtered list of only-judged steps, so it is NOT read positionally). The
IIFE seeds from the server-restored hidden value before wiring events.
"""

import json
import logging
from typing import Any, Dict, List, Tuple

from .identifier_utils import (
    safe_generate_layout, generate_element_identifier,
    generate_validation_attribute, escape_html_content, generate_layout_attributes,
)

logger = logging.getLogger(__name__)


def generate_gui_trajectory_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    description = annotation_scheme["description"]
    steps_key = annotation_scheme.get("steps_key", "steps")
    screenshot_key = annotation_scheme.get("screenshot_key", "screenshot")
    action_key = annotation_scheme.get("action_key", "action")
    coord_space = annotation_scheme.get("coord_space", "normalized")  # normalized | pixels
    verdict_options = annotation_scheme.get(
        "verdict_options", ["correct", "wrong_element", "wrong_action", "hallucinated"])
    esc_schema = escape_html_content(schema_name)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    config_json = json.dumps({
        "steps_key": steps_key, "screenshot_key": screenshot_key, "action_key": action_key,
        "coord_space": coord_space, "verdict_options": verdict_options,
    })

    html = f"""
    <form id="{esc_schema}" class="annotation-form gui-trajectory-container"
          action="javascript:void(0)" data-annotation-type="gui_trajectory"
          data-schema-name="{esc_schema}" {layout_attrs}>
        <fieldset schema="{esc_schema}">
            <legend class="gt-title">{escape_html_content(description)}</legend>
            <div class="gt-list" id="{esc_schema}-list"></div>
            <div class="gt-empty" id="{esc_schema}-empty" style="display:none;">No GUI steps in this trace.</div>
            <input type="hidden" class="annotation-input gui-trajectory-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>

    <script>
    (function() {{
        var SCHEMA = '{esc_schema}';
        var CONFIG = {config_json};
        var _steps = [];

        function instanceData() {{
            try {{
                var el = document.querySelector('[data-instance-json]');
                if (el) return JSON.parse(el.getAttribute('data-instance-json'));
            }} catch(e) {{}}
            var t = document.getElementById('text-content') || document.getElementById('instance-text');
            if (t) {{ try {{ return JSON.parse(t.textContent || t.innerText); }} catch(e2) {{}} }}
            return {{}};
        }}

        function extractSteps() {{
            var steps = instanceData()[CONFIG.steps_key];
            if (!Array.isArray(steps)) return [];
            return steps.map(function(s, i) {{
                s = (s && typeof s === 'object') ? s : {{}};
                var coord = null;
                if (s.x !== undefined && s.y !== undefined) coord = {{x: +s.x, y: +s.y}};
                else if (s.click && s.click.x !== undefined) coord = {{x: +s.click.x, y: +s.click.y}};
                return {{step: i, shot: s[CONFIG.screenshot_key] || s.image || '',
                         action: s[CONFIG.action_key] || s.text || s.content || '', coord: coord}};
            }});
        }}

        function hidden() {{ return document.getElementById(SCHEMA).querySelector('.gui-trajectory-input'); }}
        function restore() {{
            var h = hidden();
            if (h && h.value) {{ try {{ return JSON.parse(h.value) || []; }} catch(e) {{}} }}
            return [];
        }}

        function build() {{
            var steps = extractSteps();
            var list = document.getElementById(SCHEMA + '-list');
            var empty = document.getElementById(SCHEMA + '-empty');
            if (!list) return;
            if (!steps.length) {{ list.innerHTML = ''; if (empty) empty.style.display = ''; return; }}
            if (empty) empty.style.display = 'none';

            var byIndex = {{}};
            restore().forEach(function(s) {{ if (s && s.index !== undefined) byIndex[s.index] = s; }});
            _steps = steps.map(function(c, idx) {{
                var prev = byIndex[idx] || {{}};
                return {{index: idx, step: c.step, shot: c.shot, action: c.action, coord: c.coord,
                         verdict: prev.verdict || '', notes: prev.notes || ''}};
            }});

            list.innerHTML = _steps.map(function(c) {{
                var marker = '';
                if (c.coord) {{
                    var left = CONFIG.coord_space === 'pixels' ? null : (c.coord.x * 100) + '%';
                    var top = CONFIG.coord_space === 'pixels' ? null : (c.coord.y * 100) + '%';
                    if (left !== null) marker = '<span class="gt-marker" style="left:' + left + ';top:' + top + ';" aria-hidden="true"></span>';
                }}
                var img = c.shot ? '<div class="gt-shot-wrap"><img class="gt-shot" src="' + esc(c.shot) +
                    '" alt="Screenshot at step ' + (c.step+1) + '">' + marker + '</div>'
                    : '<div class="gt-shot-missing">no screenshot</div>';
                var opts = CONFIG.verdict_options.map(function(o) {{
                    return '<button type="button" class="gt-vbtn" data-idx="' + c.index +
                        '" data-v="' + esc(o) + '">' + esc(o.replace(/_/g,' ')) + '</button>'; }}).join('');
                return '<div class="gt-card" data-idx="' + c.index + '">' +
                    '<div class="gt-head"><span class="gt-step">Step ' + (c.step+1) + '</span>' +
                    (c.coord ? '<span class="gt-coord">click @ ' + esc(fmtCoord(c.coord)) + '</span>' : '') + '</div>' +
                    img +
                    '<div class="gt-action"><span class="gt-action-lbl">Action:</span> ' + esc(c.action) + '</div>' +
                    '<div class="gt-verdicts">' + opts + '</div>' +
                    '<input type="text" class="gt-notes" data-idx="' + c.index +
                    '" placeholder="notes (optional)" value="' + esc(c.notes) + '">' +
                    '</div>'; }}).join('');

            list.querySelectorAll('.gt-vbtn').forEach(function(b) {{
                b.addEventListener('click', function() {{
                    var i = parseInt(b.getAttribute('data-idx'), 10);
                    _steps[i].verdict = (_steps[i].verdict === b.getAttribute('data-v')) ? '' : b.getAttribute('data-v');
                    paint(); save();
                }});
            }});
            list.querySelectorAll('.gt-notes').forEach(function(inp) {{
                inp.addEventListener('input', function() {{
                    _steps[parseInt(inp.getAttribute('data-idx'),10)].notes = inp.value; save();
                }});
            }});
            paint();
        }}

        function paint() {{
            _steps.forEach(function(c) {{
                var card = document.querySelector('.gt-card[data-idx="' + c.index + '"]');
                if (!card) return;
                card.classList.toggle('gt-judged', !!c.verdict);
                card.querySelectorAll('.gt-vbtn').forEach(function(b) {{
                    var on = b.getAttribute('data-v') === c.verdict;
                    b.classList.toggle('selected', on);
                    b.classList.toggle('v-correct', on && b.getAttribute('data-v') === 'correct');
                    b.classList.toggle('v-bad', on && b.getAttribute('data-v') !== 'correct');
                }});
            }});
        }}

        function save() {{
            var data = _steps.filter(function(c) {{ return c.verdict || c.notes; }})
                .map(function(c) {{ return {{index: c.index, step: c.step, verdict: c.verdict, notes: c.notes}}; }});
            var h = hidden();
            if (h) {{
                h.value = data.length ? JSON.stringify(data) : '';
                h.setAttribute('data-modified', 'true');
                h.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
        }}

        function fmtCoord(c) {{
            return CONFIG.coord_space === 'pixels' ? (c.x + ',' + c.y)
                : (Math.round(c.x*100) + '%, ' + Math.round(c.y*100) + '%');
        }}
        function esc(t) {{ var d = document.createElement('div'); d.textContent = (t==null?'':t); return d.innerHTML; }}

        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
        else build();
        document.addEventListener('instanceChanged', build);
    }})();
    </script>

    <style>
    .gui-trajectory-container {{ font-family: inherit; }}
    .gt-title {{ font-weight: 600; font-size: 1em; margin-bottom: 6px; }}
    .gt-list {{ display: flex; flex-direction: column; gap: 12px; }}
    .gt-card {{ border: 1px solid var(--border, #e4e4e7); border-radius: var(--radius, 0.5rem);
                padding: 10px 12px; background: var(--card, #fff); }}
    .gt-card.gt-judged {{ border-color: var(--ring, #6e56cf); }}
    .gt-head {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }}
    .gt-step {{ font-weight: 600; }}
    .gt-coord {{ font-size: 0.75em; font-family: ui-monospace, monospace; color: var(--muted-foreground, #71717a); }}
    .gt-shot-wrap {{ position: relative; display: inline-block; max-width: 100%; border: 1px solid var(--border, #e4e4e7);
                     border-radius: 6px; overflow: hidden; }}
    .gt-shot {{ display: block; max-width: 100%; height: auto; }}
    .gt-shot-missing {{ font-size: 0.85em; color: var(--muted-foreground, #71717a); font-style: italic; padding: 8px 0; }}
    .gt-marker {{ position: absolute; width: 18px; height: 18px; margin: -9px 0 0 -9px;
                  border: 2px solid #e03131; border-radius: 50%; background: rgba(224,49,49,0.25);
                  box-shadow: 0 0 0 2px rgba(255,255,255,0.7); }}
    .gt-action {{ margin: 8px 0; font-size: 0.9em; }}
    .gt-action-lbl {{ font-weight: 600; color: var(--muted-foreground, #71717a); }}
    .gt-verdicts {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    .gt-vbtn {{ padding: 3px 10px; font-size: 0.8em; border: 1px solid var(--border, #e4e4e7);
                border-radius: 999px; background: var(--card, #fff); cursor: pointer; color: var(--foreground, #18181b); }}
    .gt-vbtn:hover {{ background: var(--secondary, #f4f4f5); }}
    .gt-vbtn:focus-visible {{ outline: 2px solid var(--ring, #6e56cf); outline-offset: 1px; }}
    .gt-vbtn.selected {{ font-weight: 600; }}
    .gt-vbtn.selected.v-correct {{ background: #4caf50; color: #fff; border-color: #4caf50; }}
    .gt-vbtn.selected.v-bad {{ background: #e03131; color: #fff; border-color: #e03131; }}
    .gt-notes {{ margin-top: 6px; width: 100%; box-sizing: border-box; padding: 4px 8px;
                 border: 1px solid var(--border, #e4e4e7); border-radius: 6px; font-size: 0.85em; }}
    .gt-empty {{ color: var(--muted-foreground, #71717a); font-style: italic; }}
    </style>
    """
    logger.info(f"Successfully generated gui_trajectory layout for {schema_name}")
    return html, []
