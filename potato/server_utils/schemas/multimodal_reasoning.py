"""
Interleaved Multimodal-Reasoning Schema (M15).

Rates an interleaved text↔image↔action reasoning trace step by step (Multimodal
RewardBench 2, 2512.16899; Zebra-CoT). Each step is a typed block — ``text``
(reasoning), ``image`` (a visual the model produced or attended to), ``tool`` (a
call), or ``action`` — rendered in-line; the annotator judges each step's coherence
(does the reasoning follow from the image/previous step? is the visual grounded, or
hallucinated?). Extends the agent-trace display to mixed-media reasoning.

Steps are read from the trace at render time; each step's ``type`` selects its
renderer. Stored as a hidden-input JSON list ``[{index, verdict, notes}]`` keyed by
``index`` (saved is a filtered list of only-judged steps, so it is NOT read
positionally). The IIFE seeds from the server-restored hidden value before wiring
events (persistence contract).
"""

import json
import logging
from typing import Any, Dict, List, Tuple

from .identifier_utils import (
    safe_generate_layout, generate_element_identifier,
    generate_validation_attribute, escape_html_content, generate_layout_attributes,
)

logger = logging.getLogger(__name__)


def generate_multimodal_reasoning_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    description = annotation_scheme["description"]
    steps_key = annotation_scheme.get("steps_key", "steps")
    type_key = annotation_scheme.get("type_key", "type")
    verdict_options = annotation_scheme.get(
        "verdict_options", ["coherent", "incoherent", "visual_hallucination", "uncertain"])
    esc_schema = escape_html_content(schema_name)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    config_json = json.dumps({
        "steps_key": steps_key, "type_key": type_key, "verdict_options": verdict_options})

    html = f"""
    <form id="{esc_schema}" class="annotation-form mmr-container"
          action="javascript:void(0)" data-annotation-type="multimodal_reasoning"
          data-schema-name="{esc_schema}" {layout_attrs}>
        <fieldset schema="{esc_schema}">
            <legend class="mmr-title">{escape_html_content(description)}</legend>
            <div class="mmr-list" id="{esc_schema}-list"></div>
            <div class="mmr-empty" id="{esc_schema}-empty" style="display:none;">No reasoning steps in this trace.</div>
            <input type="hidden" class="annotation-input mmr-input"
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

        function typeOf(s) {{
            var t = (s[CONFIG.type_key] || '').toLowerCase();
            if (t) return t;
            if (s.image || s.image_url) return 'image';
            if (s.tool || s.tool_calls || s.tool_call) return 'tool';
            if (s.action) return 'action';
            return 'text';
        }}

        function extractSteps() {{
            var steps = instanceData()[CONFIG.steps_key];
            if (!Array.isArray(steps)) return [];
            return steps.map(function(s, i) {{
                s = (s && typeof s === 'object') ? s : {{text: String(s)}};
                return {{step: i, type: typeOf(s), raw: s}};
            }});
        }}

        function hidden() {{ return document.getElementById(SCHEMA).querySelector('.mmr-input'); }}
        function restore() {{
            var h = hidden();
            if (h && h.value) {{ try {{ return JSON.parse(h.value) || []; }} catch(e) {{}} }}
            return [];
        }}

        function blockHtml(c) {{
            var s = c.raw, t = c.type;
            if (t === 'image') {{
                var src = s.image || s.image_url || '';
                return '<div class="mmr-block mmr-image">' + (src ?
                    '<img class="mmr-img" src="' + esc(src) + '" alt="Reasoning image at step ' + (c.step+1) + '">' :
                    '<span class="mmr-missing">missing image</span>') +
                    (s.caption ? '<div class="mmr-caption">' + esc(s.caption) + '</div>' : '') + '</div>';
            }}
            if (t === 'tool') {{
                var name = s.tool || s.name || (s.tool_call && s.tool_call.name) || 'tool';
                var args = s.args || s.arguments || (s.tool_call && s.tool_call.args) || s.input || {{}};
                return '<div class="mmr-block mmr-tool"><span class="mmr-tool-name">' + esc(name) +
                    '</span><pre class="mmr-args">' + esc(pretty(args)) + '</pre></div>';
            }}
            if (t === 'action') {{
                return '<div class="mmr-block mmr-action">' + esc(s.action || s.text || s.content || '') + '</div>';
            }}
            return '<div class="mmr-block mmr-text">' + esc(s.text || s.content || s.reasoning || '') + '</div>';
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
                return {{index: idx, step: c.step, type: c.type, raw: c.raw,
                         verdict: prev.verdict || '', notes: prev.notes || ''}};
            }});

            list.innerHTML = _steps.map(function(c) {{
                var opts = CONFIG.verdict_options.map(function(o) {{
                    return '<button type="button" class="mmr-vbtn" data-idx="' + c.index +
                        '" data-v="' + esc(o) + '">' + esc(o.replace(/_/g,' ')) + '</button>'; }}).join('');
                return '<div class="mmr-card" data-idx="' + c.index + '">' +
                    '<div class="mmr-head"><span class="mmr-step">Step ' + (c.step+1) +
                    '</span><span class="mmr-type mmr-type-' + esc(c.type) + '">' + esc(c.type) + '</span></div>' +
                    blockHtml(c) +
                    '<div class="mmr-verdicts">' + opts + '</div>' +
                    '<input type="text" class="mmr-notes" data-idx="' + c.index +
                    '" placeholder="notes (optional)" value="' + esc(c.notes) + '">' +
                    '</div>'; }}).join('');

            list.querySelectorAll('.mmr-vbtn').forEach(function(b) {{
                b.addEventListener('click', function() {{
                    var i = parseInt(b.getAttribute('data-idx'), 10);
                    _steps[i].verdict = (_steps[i].verdict === b.getAttribute('data-v')) ? '' : b.getAttribute('data-v');
                    paint(); save();
                }});
            }});
            list.querySelectorAll('.mmr-notes').forEach(function(inp) {{
                inp.addEventListener('input', function() {{
                    _steps[parseInt(inp.getAttribute('data-idx'),10)].notes = inp.value; save();
                }});
            }});
            paint();
        }}

        function paint() {{
            _steps.forEach(function(c) {{
                var card = document.querySelector('.mmr-card[data-idx="' + c.index + '"]');
                if (!card) return;
                card.classList.toggle('mmr-judged', !!c.verdict);
                card.querySelectorAll('.mmr-vbtn').forEach(function(b) {{
                    var on = b.getAttribute('data-v') === c.verdict;
                    b.classList.toggle('selected', on);
                    b.classList.toggle('v-good', on && b.getAttribute('data-v') === 'coherent');
                    b.classList.toggle('v-bad', on && b.getAttribute('data-v') !== 'coherent' && b.getAttribute('data-v') !== 'uncertain');
                }});
            }});
        }}

        function save() {{
            var data = _steps.filter(function(c) {{ return c.verdict || c.notes; }})
                .map(function(c) {{ return {{index: c.index, step: c.step, type: c.type, verdict: c.verdict, notes: c.notes}}; }});
            var h = hidden();
            if (h) {{
                h.value = data.length ? JSON.stringify(data) : '';
                h.setAttribute('data-modified', 'true');
                h.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
        }}

        function pretty(a) {{ try {{ return typeof a === 'string' ? a : JSON.stringify(a, null, 2); }} catch(e) {{ return String(a); }} }}
        function esc(t) {{ var d = document.createElement('div'); d.textContent = (t==null?'':t); return d.innerHTML; }}

        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
        else build();
        document.addEventListener('instanceChanged', build);
    }})();
    </script>

    <style>
    .mmr-container {{ font-family: inherit; }}
    .mmr-title {{ font-weight: 600; font-size: 1em; margin-bottom: 6px; }}
    .mmr-list {{ display: flex; flex-direction: column; gap: 10px; }}
    .mmr-card {{ border: 1px solid var(--border, #e4e4e7); border-radius: var(--radius, 0.5rem);
                 padding: 10px 12px; background: var(--card, #fff); }}
    .mmr-card.mmr-judged {{ border-color: var(--ring, #6e56cf); }}
    .mmr-head {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }}
    .mmr-step {{ font-weight: 600; }}
    .mmr-type {{ font-size: 0.68em; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
                 padding: 1px 7px; border-radius: 999px; background: var(--secondary, #f4f4f5); color: var(--muted-foreground, #71717a); }}
    .mmr-type-image {{ background: #e7f5ff; color: #1971c2; }}
    .mmr-type-tool {{ background: #f3f0ff; color: #5f3dc4; }}
    .mmr-type-action {{ background: #fff4e6; color: #e8590c; }}
    .mmr-block {{ font-size: 0.9em; margin-bottom: 8px; }}
    .mmr-text {{ white-space: pre-wrap; }}
    .mmr-img {{ max-width: 100%; height: auto; border: 1px solid var(--border, #e4e4e7); border-radius: 6px; display: block; }}
    .mmr-caption {{ font-size: 0.8em; color: var(--muted-foreground, #71717a); margin-top: 3px; }}
    .mmr-tool-name {{ font-family: ui-monospace, monospace; font-weight: 600; }}
    .mmr-args {{ margin: 4px 0 0; padding: 6px 8px; background: var(--secondary, #f4f4f5); border-radius: 6px;
                 font-size: 0.8em; max-height: 140px; overflow: auto; white-space: pre-wrap; }}
    .mmr-action {{ font-style: italic; }}
    .mmr-missing {{ color: var(--muted-foreground, #71717a); font-style: italic; }}
    .mmr-verdicts {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    .mmr-vbtn {{ padding: 3px 10px; font-size: 0.8em; border: 1px solid var(--border, #e4e4e7);
                 border-radius: 999px; background: var(--card, #fff); cursor: pointer; color: var(--foreground, #18181b); }}
    .mmr-vbtn:hover {{ background: var(--secondary, #f4f4f5); }}
    .mmr-vbtn:focus-visible {{ outline: 2px solid var(--ring, #6e56cf); outline-offset: 1px; }}
    .mmr-vbtn.selected {{ font-weight: 600; }}
    .mmr-vbtn.selected.v-good {{ background: #4caf50; color: #fff; border-color: #4caf50; }}
    .mmr-vbtn.selected.v-bad {{ background: #e03131; color: #fff; border-color: #e03131; }}
    .mmr-notes {{ margin-top: 6px; width: 100%; box-sizing: border-box; padding: 4px 8px;
                  border: 1px solid var(--border, #e4e4e7); border-radius: 6px; font-size: 0.85em; }}
    .mmr-empty {{ color: var(--muted-foreground, #71717a); font-style: italic; }}
    </style>
    """
    logger.info(f"Successfully generated multimodal_reasoning layout for {schema_name}")
    return html, []
