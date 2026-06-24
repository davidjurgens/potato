"""
Tool-Call Review Schema (M12).

Renders each tool/function call in an agent trace as a structured card — name +
arguments (pretty-printed) — and lets the annotator judge it: was the **right tool**
chosen, were the **arguments correct**, and (optionally) was the **call order** right?
Mirrors function-calling benchmarks (BFCL v4, MCPMark). Reusable across any agent
trace that records tool calls.

Tool calls are read from the trace steps at render time: each step whose
``tool_calls``/``tool_call``/``action`` indicates a call becomes a card. Stored as a
hidden-input JSON list: ``[{index, tool, verdict, args_ok, notes}]``. The IIFE seeds
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


def generate_tool_call_review_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    description = annotation_scheme["description"]
    steps_key = annotation_scheme.get("steps_key", "steps")
    verdict_options = annotation_scheme.get("verdict_options", ["correct", "wrong_tool", "wrong_args"])
    esc_schema = escape_html_content(schema_name)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    config_json = json.dumps({"steps_key": steps_key, "verdict_options": verdict_options})

    html = f"""
    <form id="{esc_schema}" class="annotation-form tool-call-review-container"
          action="javascript:void(0)" data-annotation-type="tool_call_review"
          data-schema-name="{esc_schema}" {layout_attrs}>
        <fieldset schema="{esc_schema}">
            <legend class="tcr-title">{escape_html_content(description)}</legend>
            <div class="tcr-list" id="{esc_schema}-list"></div>
            <div class="tcr-empty" id="{esc_schema}-empty" style="display:none;">No tool calls in this trace.</div>
            <input type="hidden" class="annotation-input tool-call-review-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>

    <script>
    (function() {{
        var SCHEMA = '{esc_schema}';
        var CONFIG = {config_json};
        var _calls = [];

        function instanceData() {{
            try {{
                var el = document.querySelector('[data-instance-json]');
                if (el) return JSON.parse(el.getAttribute('data-instance-json'));
            }} catch(e) {{}}
            var t = document.getElementById('text-content') || document.getElementById('instance-text');
            if (t) {{ try {{ return JSON.parse(t.textContent || t.innerText); }} catch(e2) {{}} }}
            return {{}};
        }}

        function extractCalls() {{
            var steps = instanceData()[CONFIG.steps_key];
            if (!Array.isArray(steps)) return [];
            var calls = [];
            steps.forEach(function(s, i) {{
                if (!s || typeof s !== 'object') return;
                var tcs = s.tool_calls || (s.tool_call ? [s.tool_call] : null);
                if (tcs && tcs.length) {{
                    tcs.forEach(function(tc) {{
                        calls.push({{step: i, tool: tc.name || tc.tool || 'tool',
                                     args: tc.args || tc.arguments || tc.input || {{}}}});
                    }});
                }} else if (s.tool || s.action_type === 'tool') {{
                    calls.push({{step: i, tool: s.tool || s.name || 'tool',
                                 args: s.args || s.arguments || s.input || {{}}}});
                }}
            }});
            return calls;
        }}

        function hidden() {{ return document.getElementById(SCHEMA).querySelector('.tool-call-review-input'); }}

        function restore() {{
            var h = hidden();
            if (h && h.value) {{ try {{ return JSON.parse(h.value) || []; }} catch(e) {{}} }}
            return [];
        }}

        function build() {{
            var calls = extractCalls();
            var list = document.getElementById(SCHEMA + '-list');
            var empty = document.getElementById(SCHEMA + '-empty');
            if (!list) return;
            if (!calls.length) {{ list.innerHTML = ''; if (empty) empty.style.display = ''; return; }}
            if (empty) empty.style.display = 'none';

            // Restore by matching the saved 'index' (saved is a filtered list of
            // only-judged calls, so it must NOT be read positionally).
            var byIndex = {{}};
            restore().forEach(function(s) {{ if (s && s.index !== undefined) byIndex[s.index] = s; }});
            _calls = calls.map(function(c, idx) {{
                var prev = byIndex[idx] || {{}};
                return {{index: idx, step: c.step, tool: c.tool, args: c.args,
                         verdict: prev.verdict || '', notes: prev.notes || ''}};
            }});

            list.innerHTML = _calls.map(function(c) {{
                var opts = CONFIG.verdict_options.map(function(o) {{
                    return '<button type="button" class="tcr-vbtn" data-idx="' + c.index +
                        '" data-v="' + esc(o) + '">' + esc(o.replace(/_/g,' ')) + '</button>'; }}).join('');
                return '<div class="tcr-card" data-idx="' + c.index + '">' +
                    '<div class="tcr-head"><span class="tcr-tool">' + esc(c.tool) +
                    '</span><span class="tcr-step">step ' + (c.step+1) + '</span></div>' +
                    '<pre class="tcr-args">' + esc(pretty(c.args)) + '</pre>' +
                    '<div class="tcr-verdicts">' + opts + '</div>' +
                    '<input type="text" class="tcr-notes" data-idx="' + c.index +
                    '" placeholder="notes (optional)" value="' + esc(c.notes) + '">' +
                    '</div>'; }}).join('');

            list.querySelectorAll('.tcr-vbtn').forEach(function(b) {{
                b.addEventListener('click', function() {{
                    var i = parseInt(b.getAttribute('data-idx'), 10);
                    _calls[i].verdict = (_calls[i].verdict === b.getAttribute('data-v')) ? '' : b.getAttribute('data-v');
                    paint(); save();
                }});
            }});
            list.querySelectorAll('.tcr-notes').forEach(function(inp) {{
                inp.addEventListener('input', function() {{
                    _calls[parseInt(inp.getAttribute('data-idx'),10)].notes = inp.value; save();
                }});
            }});
            paint();
        }}

        function paint() {{
            _calls.forEach(function(c) {{
                var card = document.querySelector('.tcr-card[data-idx="' + c.index + '"]');
                if (!card) return;
                card.classList.toggle('tcr-judged', !!c.verdict);
                card.querySelectorAll('.tcr-vbtn').forEach(function(b) {{
                    var on = b.getAttribute('data-v') === c.verdict;
                    b.classList.toggle('selected', on);
                    b.classList.toggle('v-' + b.getAttribute('data-v'), on);
                }});
            }});
        }}

        function save() {{
            var data = _calls.filter(function(c) {{ return c.verdict || c.notes; }})
                .map(function(c) {{ return {{index: c.index, step: c.step, tool: c.tool,
                                            verdict: c.verdict, notes: c.notes}}; }});
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
    .tool-call-review-container {{ font-family: inherit; }}
    .tcr-title {{ font-weight: 600; font-size: 1em; margin-bottom: 6px; }}
    .tcr-list {{ display: flex; flex-direction: column; gap: 8px; }}
    .tcr-card {{ border: 1px solid var(--border, #e4e4e7); border-radius: var(--radius, 0.5rem);
                 padding: 8px 12px; background: var(--card, #fff); }}
    .tcr-card.tcr-judged {{ border-color: var(--ring, #6e56cf); }}
    .tcr-head {{ display: flex; justify-content: space-between; align-items: baseline; }}
    .tcr-tool {{ font-weight: 600; font-family: ui-monospace, monospace; }}
    .tcr-step {{ font-size: 0.75em; color: var(--muted-foreground, #71717a); }}
    .tcr-args {{ margin: 6px 0; padding: 6px 8px; background: var(--secondary, #f4f4f5);
                 border-radius: 6px; font-size: 0.8em; max-height: 140px; overflow: auto; white-space: pre-wrap; }}
    .tcr-verdicts {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    .tcr-vbtn {{ padding: 3px 10px; font-size: 0.8em; border: 1px solid var(--border, #e4e4e7);
                 border-radius: 999px; background: var(--card, #fff); cursor: pointer; }}
    .tcr-vbtn:hover {{ background: var(--secondary, #f4f4f5); }}
    .tcr-vbtn:focus-visible {{ outline: 2px solid var(--ring, #6e56cf); outline-offset: 1px; }}
    .tcr-vbtn.selected {{ font-weight: 600; }}
    .tcr-vbtn.selected.v-correct {{ background: #4caf50; color: #fff; border-color: #4caf50; }}
    .tcr-vbtn.selected.v-wrong_tool, .tcr-vbtn.selected.v-wrong_args {{ background: #f44336; color: #fff; border-color: #f44336; }}
    .tcr-notes {{ margin-top: 6px; width: 100%; box-sizing: border-box; padding: 4px 8px;
                  border: 1px solid var(--border, #e4e4e7); border-radius: 6px; font-size: 0.85em; }}
    .tcr-empty {{ color: var(--muted-foreground, #71717a); font-style: italic; }}
    </style>
    """
    logger.info(f"Successfully generated tool_call_review layout for {schema_name}")
    return html, []
