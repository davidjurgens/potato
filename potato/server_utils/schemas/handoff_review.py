"""
Handoff Review Schema (M2).

Makes the **handoff** — one agent passing control/information to another — a
first-class annotatable object. Each point in the trace where the acting agent
changes becomes a handoff card A→B; the annotator flags inter-agent misalignment
(MAST: information loss, dropped constraints, garbling, goal drift) and rates the
handoff quality. Grounded in MAST's inter-agent failure modes, LACP (2510.13821),
and "Echoing" (2511.09710).

Handoffs are derived from the trace steps at render time: a handoff is recorded
whenever ``agent_key`` differs between consecutive steps. Stored as a hidden-input
JSON list::

    [{"index", "step", "from", "to", "flags": [...], "quality": int}]

The IIFE seeds from the server-restored hidden value before wiring events, and
restores each card by its ``index`` (saved is a filtered list of only-flagged
handoffs, so it is NOT read positionally).
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


def generate_handoff_review_layout(
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
    flags = annotation_scheme.get(
        "flags", ["info_loss", "dropped_constraint", "garbling", "goal_drift"]
    )
    quality_scale = int(annotation_scheme.get("quality_scale", 5))

    esc_schema = escape_html_content(schema_name)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")

    config_json = json.dumps({
        "steps_key": steps_key, "agent_key": agent_key,
        "flags": flags, "quality_scale": quality_scale,
    })

    html = f"""
    <form id="{esc_schema}" class="annotation-form handoff-review-container"
          action="javascript:void(0)"
          data-annotation-type="handoff_review"
          data-schema-name="{esc_schema}"
          {layout_attrs}>
        <fieldset schema="{esc_schema}">
            <legend class="hr-title">{escape_html_content(description)}</legend>
            <div class="hr-list" id="{esc_schema}-list"></div>
            <div class="hr-empty" id="{esc_schema}-empty" style="display:none;">No agent-to-agent handoffs in this trace.</div>
            <input type="hidden" class="annotation-input handoff-review-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>

    <script>
    (function() {{
        var SCHEMA = '{esc_schema}';
        var CONFIG = {config_json};
        var _handoffs = [];

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

        function extractHandoffs() {{
            var steps = instanceData()[CONFIG.steps_key];
            if (!Array.isArray(steps)) return [];
            var out = [], prev = null, prevIdx = -1;
            steps.forEach(function(s, i) {{
                var a = agentOf(s, i);
                if (prev !== null && a !== prev) out.push({{step: i, from: prev, to: a, fromStep: prevIdx}});
                prev = a; prevIdx = i;
            }});
            return out;
        }}

        function hidden() {{ return document.getElementById(SCHEMA).querySelector('.handoff-review-input'); }}

        function restore() {{
            var h = hidden();
            if (h && h.value) {{ try {{ return JSON.parse(h.value) || []; }} catch(e) {{}} }}
            return [];
        }}

        function build() {{
            var handoffs = extractHandoffs();
            var list = document.getElementById(SCHEMA + '-list');
            var empty = document.getElementById(SCHEMA + '-empty');
            if (!list) return;
            if (!handoffs.length) {{ list.innerHTML = ''; if (empty) empty.style.display = ''; return; }}
            if (empty) empty.style.display = 'none';

            var byIndex = {{}};
            restore().forEach(function(s) {{ if (s && s.index !== undefined) byIndex[s.index] = s; }});
            _handoffs = handoffs.map(function(h, idx) {{
                var prev = byIndex[idx] || {{}};
                return {{index: idx, step: h.step, from: h.from, to: h.to,
                         flags: Array.isArray(prev.flags) ? prev.flags.slice() : [],
                         quality: prev.quality || 0}};
            }});

            list.innerHTML = _handoffs.map(function(h) {{
                var flagPills = CONFIG.flags.map(function(f) {{
                    return '<button type="button" class="hr-flag" data-idx="' + h.index + '" data-f="' + esc(f) + '">' +
                        esc(f.replace(/_/g,' ')) + '</button>'; }}).join('');
                var q = '';
                for (var v = 1; v <= CONFIG.quality_scale; v++) {{
                    q += '<button type="button" class="hr-qbtn" data-idx="' + h.index + '" data-v="' + v + '">' + v + '</button>';
                }}
                return '<div class="hr-card" data-idx="' + h.index + '">' +
                    '<div class="hr-head"><span class="hr-edge"><span class="hr-from">' + esc(h.from) +
                    '</span><span class="hr-arrow" aria-hidden="true">→</span><span class="hr-to">' + esc(h.to) +
                    '</span></span><span class="hr-step">step ' + (h.step+1) + '</span></div>' +
                    '<div class="hr-flags-row"><span class="hr-lbl">Issues:</span>' + flagPills + '</div>' +
                    '<div class="hr-quality-row"><span class="hr-lbl">Quality:</span><div class="hr-quality">' + q + '</div></div>' +
                    '</div>'; }}).join('');

            list.querySelectorAll('.hr-flag').forEach(function(b) {{
                b.addEventListener('click', function() {{
                    var i = parseInt(b.getAttribute('data-idx'), 10), f = b.getAttribute('data-f');
                    var arr = _handoffs[i].flags, p = arr.indexOf(f);
                    if (p >= 0) arr.splice(p, 1); else arr.push(f);
                    paint(i); save();
                }});
            }});
            list.querySelectorAll('.hr-qbtn').forEach(function(b) {{
                b.addEventListener('click', function() {{
                    var i = parseInt(b.getAttribute('data-idx'), 10), v = parseInt(b.getAttribute('data-v'), 10);
                    _handoffs[i].quality = (_handoffs[i].quality === v) ? 0 : v;
                    paint(i); save();
                }});
            }});
            _handoffs.forEach(function(h) {{ paint(h.index); }});
        }}

        function paint(i) {{
            var h = _handoffs[i];
            var card = document.querySelector('.hr-card[data-idx="' + i + '"]');
            if (!card) return;
            card.classList.toggle('hr-flagged', h.flags.length > 0);
            card.querySelectorAll('.hr-flag').forEach(function(b) {{
                b.classList.toggle('selected', h.flags.indexOf(b.getAttribute('data-f')) >= 0);
            }});
            card.querySelectorAll('.hr-qbtn').forEach(function(b) {{
                b.classList.toggle('selected', parseInt(b.getAttribute('data-v'), 10) === h.quality);
            }});
        }}

        function save() {{
            var data = _handoffs.filter(function(h) {{ return h.flags.length || h.quality; }})
                .map(function(h) {{ return {{index: h.index, step: h.step, from: h.from, to: h.to,
                                             flags: h.flags, quality: h.quality}}; }});
            var hid = hidden();
            if (hid) {{
                hid.value = data.length ? JSON.stringify(data) : '';
                hid.setAttribute('data-modified', 'true');
                hid.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
        }}

        function esc(t) {{ var d = document.createElement('div'); d.textContent = (t==null?'':t); return d.innerHTML; }}

        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
        else build();
        document.addEventListener('instanceChanged', build);
    }})();
    </script>

    <style>
    .handoff-review-container {{ font-family: inherit; }}
    .hr-title {{ font-weight: 600; font-size: 1em; margin-bottom: 6px; }}
    .hr-list {{ display: flex; flex-direction: column; gap: 8px; }}
    .hr-card {{ border: 1px solid var(--border, #e4e4e7); border-radius: var(--radius, 0.5rem);
                padding: 8px 12px; background: var(--card, #fff); }}
    .hr-card.hr-flagged {{ border-color: #e0a800; box-shadow: inset 3px 0 0 #e0a800; }}
    .hr-head {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }}
    .hr-edge {{ font-family: ui-monospace, monospace; font-weight: 600; }}
    .hr-arrow {{ margin: 0 6px; color: var(--muted-foreground, #71717a); }}
    .hr-step {{ font-size: 0.75em; color: var(--muted-foreground, #71717a); }}
    .hr-flags-row, .hr-quality-row {{ display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 4px; }}
    .hr-lbl {{ font-size: 0.78em; color: var(--muted-foreground, #71717a); min-width: 48px; }}
    .hr-flag {{ padding: 3px 10px; font-size: 0.8em; border: 1px solid var(--border, #e4e4e7);
                border-radius: 999px; background: var(--card, #fff); cursor: pointer; color: var(--foreground, #18181b); }}
    .hr-flag:hover {{ background: var(--secondary, #f4f4f5); }}
    .hr-flag:focus-visible, .hr-qbtn:focus-visible {{ outline: 2px solid var(--ring, #6e56cf); outline-offset: 1px; }}
    .hr-flag.selected {{ background: #f59f00; color: #fff; border-color: #f59f00; font-weight: 600; }}
    .hr-quality {{ display: flex; gap: 4px; }}
    .hr-qbtn {{ width: 26px; height: 26px; border: 1px solid var(--border, #e4e4e7); border-radius: 6px;
                background: var(--card, #fff); cursor: pointer; font-size: 0.8em; color: var(--foreground, #18181b); }}
    .hr-qbtn:hover {{ background: var(--secondary, #f4f4f5); }}
    .hr-qbtn.selected {{ background: var(--ring, #6e56cf); color: #fff; border-color: var(--ring, #6e56cf); font-weight: 600; }}
    .hr-empty {{ color: var(--muted-foreground, #71717a); font-style: italic; }}
    </style>
    """
    logger.info(f"Successfully generated handoff_review layout for {schema_name}")
    return html, []
