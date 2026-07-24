"""
Consensus-Tracking Schema.

For multi-agent discussions/debates: tag each turn with a discussion act
(proposal / agreement / disagreement / decision / concession) and — for acts
that respond to something — link the turn to the proposal turn it references.
This captures the *structure* of group deliberation (who proposed what, who
agreed/objected, where the decision landed), which per-turn ratings alone
cannot express.

Turns are read from the instance data at render time (``turns_key``,
default "conversation"). Stored as a hidden-input JSON list::

    [{"turn": 4, "act": "agreement", "ref": 1, "agent_id": "critic"}]

Link interaction: choosing a link-requiring act arms link mode; the next
click on another turn card records the reference. The IIFE seeds from the
server-restored hidden value before wiring events (persistence contract).
"""

import json
import logging
from typing import Any, Dict, List, Tuple

from .identifier_utils import (
    safe_generate_layout, generate_element_identifier,
    generate_validation_attribute, escape_html_content, generate_layout_attributes,
)

logger = logging.getLogger(__name__)

DEFAULT_ACTS = ["proposal", "agreement", "disagreement", "decision", "concession"]
DEFAULT_LINKED_ACTS = ["agreement", "disagreement", "concession"]


def generate_consensus_tracking_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    description = annotation_scheme["description"]
    turns_key = annotation_scheme.get("turns_key", "conversation")
    acts = annotation_scheme.get("acts", DEFAULT_ACTS)
    linked_acts = annotation_scheme.get("linked_acts", DEFAULT_LINKED_ACTS)
    hint = annotation_scheme.get(
        "hint",
        "Tag turns with discussion acts. Acts like <em>agreement</em> then ask you to "
        "click the proposal turn they refer to.",
    )
    esc_schema = escape_html_content(schema_name)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    config_json = json.dumps({
        "turns_key": turns_key, "acts": acts, "linked_acts": linked_acts,
    })

    html = f"""
    <form id="{esc_schema}" class="annotation-form consensus-tracking-container"
          action="javascript:void(0)" data-annotation-type="consensus_tracking"
          data-schema-name="{esc_schema}" {layout_attrs}>
        <fieldset schema="{esc_schema}">
            <legend class="ct-title">{escape_html_content(description)}</legend>
            <div class="ct-hint" id="{esc_schema}-hint">{hint}</div>
            <div class="ct-list" id="{esc_schema}-list"></div>
            <div class="ct-empty" id="{esc_schema}-empty" style="display:none;">No turns in this instance.</div>
            <input type="hidden" class="annotation-input consensus-tracking-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>

    <script>
    (function() {{
        var SCHEMA = '{esc_schema}';
        var CONFIG = {config_json};
        var _turns = [];
        var _tags = [];       // [{{turn, act, ref, agent_id}}]
        var _linking = null;  // {{turn, act}} while awaiting a ref click

        function instanceData() {{
            try {{
                var el = document.querySelector('[data-instance-json]');
                if (el) return JSON.parse(el.getAttribute('data-instance-json'));
            }} catch(e) {{}}
            var t = document.getElementById('text-content') || document.getElementById('instance-text');
            if (t) {{ try {{ return JSON.parse(t.textContent || t.innerText); }} catch(e2) {{}} }}
            return {{}};
        }}

        function extractTurns() {{
            var turns = instanceData()[CONFIG.turns_key];
            if (!Array.isArray(turns)) return [];
            return turns.map(function(t, i) {{
                if (typeof t === 'string') return {{index: i, speaker: '', agent_id: '', text: t}};
                return {{index: i, speaker: t.speaker || '', agent_id: t.agent_id || t.speaker || '',
                         text: String(t.text == null ? '' : t.text)}};
            }});
        }}

        function hidden() {{ return document.getElementById(SCHEMA).querySelector('.consensus-tracking-input'); }}

        function restore() {{
            var h = hidden();
            if (h && h.value) {{ try {{ return JSON.parse(h.value) || []; }} catch(e) {{}} }}
            return [];
        }}

        function tagFor(i) {{
            for (var k = 0; k < _tags.length; k++) if (_tags[k].turn === i) return _tags[k];
            return null;
        }}

        function build() {{
            _turns = extractTurns();
            var list = document.getElementById(SCHEMA + '-list');
            var empty = document.getElementById(SCHEMA + '-empty');
            if (!list) return;
            if (!_turns.length) {{ list.innerHTML = ''; if (empty) empty.style.display = ''; return; }}
            if (empty) empty.style.display = 'none';

            // Seed from the server-restored hidden value BEFORE wiring events.
            _tags = restore();
            _linking = null;

            list.innerHTML = _turns.map(function(t) {{
                var snippet = t.text.length > 140 ? t.text.slice(0, 140) + '…' : t.text;
                var actBtns = CONFIG.acts.map(function(a) {{
                    return '<button type="button" class="ct-act" data-turn="' + t.index +
                        '" data-act="' + esc(a) + '">' + esc(a) + '</button>'; }}).join('');
                return '<div class="ct-card" data-turn="' + t.index + '">' +
                    '<div class="ct-head"><span class="ct-idx">#' + (t.index + 1) + '</span>' +
                    '<span class="ct-speaker">' + esc(t.speaker) + '</span>' +
                    '<span class="ct-tag-badge" data-turn="' + t.index + '"></span></div>' +
                    '<div class="ct-text">' + esc(snippet) + '</div>' +
                    '<div class="ct-acts">' + actBtns + '</div>' +
                    '</div>'; }}).join('');

            list.querySelectorAll('.ct-act').forEach(function(b) {{
                b.addEventListener('click', function() {{
                    var i = parseInt(b.getAttribute('data-turn'), 10);
                    var act = b.getAttribute('data-act');
                    var existing = tagFor(i);
                    if (existing && existing.act === act) {{
                        // toggle off
                        _tags = _tags.filter(function(t) {{ return t.turn !== i; }});
                        _linking = null;
                        paint(); save(); return;
                    }}
                    _tags = _tags.filter(function(t) {{ return t.turn !== i; }});
                    var tag = {{turn: i, act: act, agent_id: (_turns[i] || {{}}).agent_id || ''}};
                    _tags.push(tag);
                    if (CONFIG.linked_acts.indexOf(act) !== -1) {{
                        _linking = tag;  // next card click sets ref
                    }} else {{
                        _linking = null;
                    }}
                    paint(); save();
                }});
            }});

            list.querySelectorAll('.ct-card').forEach(function(card) {{
                card.addEventListener('click', function(ev) {{
                    if (!_linking) return;
                    if (ev.target.closest('.ct-act')) return;  // act buttons handled above
                    var i = parseInt(card.getAttribute('data-turn'), 10);
                    if (i === _linking.turn) return;
                    _linking.ref = i;
                    _linking = null;
                    paint(); save();
                }});
            }});

            paint();
        }}

        function paint() {{
            var list = document.getElementById(SCHEMA + '-list');
            if (!list) return;
            list.classList.toggle('ct-link-mode', !!_linking);
            list.querySelectorAll('.ct-card').forEach(function(card) {{
                var i = parseInt(card.getAttribute('data-turn'), 10);
                var tag = tagFor(i);
                card.classList.toggle('ct-tagged', !!tag);
                card.classList.toggle('ct-awaiting-ref', !!(_linking && _linking.turn === i));
                var badge = card.querySelector('.ct-tag-badge');
                if (badge) {{
                    if (tag) {{
                        var label = tag.act + (tag.ref !== undefined ? ' → #' + (tag.ref + 1) : '');
                        if (_linking && _linking.turn === i) label = tag.act + ' → click the referenced turn';
                        badge.textContent = label;
                        badge.className = 'ct-tag-badge ct-badge-' + tag.act;
                    }} else {{
                        badge.textContent = '';
                        badge.className = 'ct-tag-badge';
                    }}
                }}
                card.querySelectorAll('.ct-act').forEach(function(b) {{
                    b.classList.toggle('selected', !!(tag && tag.act === b.getAttribute('data-act')));
                }});
            }});
        }}

        function save() {{
            var h = hidden();
            if (h) {{
                h.value = _tags.length ? JSON.stringify(_tags) : '';
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
    .consensus-tracking-container {{ font-family: inherit; }}
    .ct-title {{ font-weight: 600; font-size: 1em; margin-bottom: 4px; }}
    .ct-hint {{ font-size: 0.85em; color: var(--muted-foreground, #71717a); margin-bottom: 8px; }}
    .ct-list {{ display: flex; flex-direction: column; gap: 8px; }}
    .ct-card {{ border: 1px solid var(--border, #e4e4e7); border-radius: var(--radius, 0.5rem);
                padding: 8px 12px; background: var(--card, #fff); }}
    .ct-card.ct-tagged {{ border-color: var(--ring, #6e56cf); }}
    .ct-link-mode .ct-card {{ cursor: crosshair; }}
    .ct-card.ct-awaiting-ref {{ outline: 2px dashed var(--ring, #6e56cf); outline-offset: 2px; }}
    .ct-head {{ display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }}
    .ct-idx {{ font-size: 0.75em; color: var(--muted-foreground, #71717a); }}
    .ct-speaker {{ font-weight: 600; }}
    .ct-tag-badge {{ font-size: 0.75em; padding: 1px 8px; border-radius: 999px; margin-left: auto; }}
    .ct-badge-proposal {{ background: #dbeafe; color: #1d4ed8; }}
    .ct-badge-agreement {{ background: #dcfce7; color: #15803d; }}
    .ct-badge-disagreement {{ background: #fee2e2; color: #b91c1c; }}
    .ct-badge-decision {{ background: #ede9fe; color: #6d28d9; }}
    .ct-badge-concession {{ background: #fef9c3; color: #a16207; }}
    .ct-text {{ font-size: 0.85em; color: #3f3f46; margin: 4px 0; white-space: pre-wrap; }}
    .ct-acts {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    .ct-act {{ padding: 2px 10px; font-size: 0.8em; border: 1px solid var(--border, #e4e4e7);
               border-radius: 999px; background: var(--card, #fff); cursor: pointer; }}
    .ct-act:hover {{ background: var(--secondary, #f4f4f5); }}
    .ct-act:focus-visible {{ outline: 2px solid var(--ring, #6e56cf); outline-offset: 1px; }}
    .ct-act.selected {{ background: var(--ring, #6e56cf); color: #fff; border-color: var(--ring, #6e56cf);
                        font-weight: 600; }}
    .ct-empty {{ color: var(--muted-foreground, #71717a); font-style: italic; }}
    </style>
    """
    logger.info(f"Successfully generated consensus_tracking layout for {schema_name}")
    return html, []
