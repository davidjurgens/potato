"""
Voice / Full-Duplex Interaction Schema (M9).

Annotates a spoken human↔agent conversation for turn-taking quality and
barge-in/interruption handling (Full-Duplex-Bench v1–v3, 2503.04721…; τ-Voice,
2603.13686). Renders a **dual-track timeline** (user lane + agent lane) with each
turn placed by its start/end time, highlights **overlap regions** where the two
speakers talk at once (barge-ins), and lets the annotator classify each overlap
(agent should RESPOND / should RESUME / backchannel / uncertain) plus give an
overall turn-taking rating. Optionally plays the source audio.

Input per instance: an optional ``audio`` URL and a ``turns`` list of
``{speaker, start, end, text}`` (seconds). Overlaps between turns of *different*
speakers are computed at render time. Stored as a hidden-input JSON object::

    {"overlaps": {idx: label}, "rating": int}

Overlaps are keyed by a stable index over the sorted overlap list. The IIFE seeds
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


def generate_voice_interaction_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    description = annotation_scheme["description"]
    turns_key = annotation_scheme.get("turns_key", "turns")
    audio_key = annotation_scheme.get("audio_key", "audio")
    speaker_key = annotation_scheme.get("speaker_key", "speaker")
    user_speakers = annotation_scheme.get("user_speakers", ["user", "human", "caller"])
    overlap_labels = annotation_scheme.get(
        "overlap_labels", ["agent_should_respond", "agent_should_resume", "backchannel", "uncertain"])
    rating_scale = int(annotation_scheme.get("rating_scale", 5))
    esc_schema = escape_html_content(schema_name)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    config_json = json.dumps({
        "turns_key": turns_key, "audio_key": audio_key, "speaker_key": speaker_key,
        "user_speakers": [s.lower() for s in user_speakers],
        "overlap_labels": overlap_labels, "rating_scale": rating_scale,
    })

    html = f"""
    <form id="{esc_schema}" class="annotation-form voice-interaction-container"
          action="javascript:void(0)" data-annotation-type="voice_interaction"
          data-schema-name="{esc_schema}" {layout_attrs}>
        <fieldset schema="{esc_schema}">
            <legend class="vi-title">{escape_html_content(description)}</legend>
            <div class="vi-audio" id="{esc_schema}-audio"></div>
            <div class="vi-timeline-wrap">
                <div class="vi-lane-labels"><span>user</span><span>agent</span></div>
                <div class="vi-timeline" id="{esc_schema}-timeline"></div>
            </div>
            <div class="vi-overlaps-head" id="{esc_schema}-oh" style="display:none;">Barge-ins / overlaps</div>
            <div class="vi-overlaps" id="{esc_schema}-overlaps"></div>
            <div class="vi-none" id="{esc_schema}-none" style="display:none;">No overlaps detected — turn-taking is clean.</div>
            <div class="vi-rating-row">
                <span class="vi-rating-lbl">Overall turn-taking</span>
                <div class="vi-rating" id="{esc_schema}-rating"></div>
            </div>
            <input type="hidden" class="annotation-input voice-interaction-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>

    <script>
    (function() {{
        var SCHEMA = '{esc_schema}';
        var CONFIG = {config_json};
        var STATE = {{overlaps: {{}}, rating: 0}};
        var _overlaps = [];

        function instanceData() {{
            try {{
                var el = document.querySelector('[data-instance-json]');
                if (el) return JSON.parse(el.getAttribute('data-instance-json'));
            }} catch(e) {{}}
            var t = document.getElementById('text-content') || document.getElementById('instance-text');
            if (t) {{ try {{ return JSON.parse(t.textContent || t.innerText); }} catch(e2) {{}} }}
            return {{}};
        }}

        function getTurns() {{
            var d = instanceData();
            var t = d[CONFIG.turns_key];
            if (!Array.isArray(t)) return [];
            return t.map(function(x, i) {{
                x = (x && typeof x === 'object') ? x : {{}};
                var sp = String(x[CONFIG.speaker_key] || x.role || 'agent').toLowerCase();
                return {{i: i, speaker: sp, isUser: CONFIG.user_speakers.indexOf(sp) >= 0,
                         start: +(x.start || 0), end: +(x.end || x.start || 0),
                         text: x.text || x.content || ''}};
            }}).filter(function(t) {{ return t.end >= t.start; }});
        }}

        function computeOverlaps(turns) {{
            var out = [];
            for (var a = 0; a < turns.length; a++) {{
                for (var b = a+1; b < turns.length; b++) {{
                    if (turns[a].isUser === turns[b].isUser) continue;
                    var s = Math.max(turns[a].start, turns[b].start);
                    var e = Math.min(turns[a].end, turns[b].end);
                    if (e > s) {{
                        var u = turns[a].isUser ? turns[a] : turns[b];
                        var g = turns[a].isUser ? turns[b] : turns[a];
                        out.push({{start: s, end: e, userText: u.text, agentText: g.text}});
                    }}
                }}
            }}
            out.sort(function(p, q) {{ return p.start - q.start; }});
            return out.map(function(o, idx) {{ o.idx = idx; return o; }});
        }}

        function hidden() {{ return document.getElementById(SCHEMA).querySelector('.voice-interaction-input'); }}
        function restore() {{
            var h = hidden();
            if (h && h.value) {{ try {{ return JSON.parse(h.value) || {{}}; }} catch(e) {{}} }}
            return {{}};
        }}

        function build() {{
            var d = instanceData();
            var turns = getTurns();
            var prev = restore();
            STATE = {{overlaps: prev.overlaps || {{}}, rating: prev.rating || 0}};

            // Audio player (optional).
            var audWrap = document.getElementById(SCHEMA + '-audio');
            var src = d[CONFIG.audio_key];
            audWrap.innerHTML = src ? '<audio controls preload="metadata" src="' + esc(src) + '" style="width:100%"></audio>' : '';

            // Dual-track timeline.
            var tl = document.getElementById(SCHEMA + '-timeline');
            var maxT = turns.reduce(function(m, t) {{ return Math.max(m, t.end); }}, 0) || 1;
            tl.innerHTML = '<div class="vi-lane vi-lane-user"></div><div class="vi-lane vi-lane-agent"></div>';
            var userLane = tl.querySelector('.vi-lane-user'), agentLane = tl.querySelector('.vi-lane-agent');
            turns.forEach(function(t) {{
                var blk = document.createElement('div');
                blk.className = 'vi-turn ' + (t.isUser ? 'vi-turn-user' : 'vi-turn-agent');
                blk.style.left = (100 * t.start / maxT) + '%';
                blk.style.width = Math.max(1.5, 100 * (t.end - t.start) / maxT) + '%';
                blk.title = t.speaker + ' ' + t.start + '–' + t.end + 's: ' + t.text;
                (t.isUser ? userLane : agentLane).appendChild(blk);
            }});

            _overlaps = computeOverlaps(turns);
            var oh = document.getElementById(SCHEMA + '-oh');
            var none = document.getElementById(SCHEMA + '-none');
            var box = document.getElementById(SCHEMA + '-overlaps');
            if (!_overlaps.length) {{ box.innerHTML = ''; oh.style.display = 'none'; none.style.display = ''; }}
            else {{
                oh.style.display = ''; none.style.display = 'none';
                // Overlap bands on the timeline.
                _overlaps.forEach(function(o) {{
                    var band = document.createElement('div');
                    band.className = 'vi-overlap-band';
                    band.style.left = (100 * o.start / maxT) + '%';
                    band.style.width = Math.max(1, 100 * (o.end - o.start) / maxT) + '%';
                    tl.appendChild(band);
                }});
                box.innerHTML = _overlaps.map(function(o) {{
                    var pills = CONFIG.overlap_labels.map(function(l) {{
                        return '<button type="button" class="vi-lbtn" data-idx="' + o.idx + '" data-l="' + esc(l) + '">' +
                            esc(l.replace(/_/g,' ')) + '</button>'; }}).join('');
                    return '<div class="vi-ocard" data-idx="' + o.idx + '">' +
                        '<div class="vi-ohead"><span class="vi-otime">' + o.start.toFixed(1) + '–' + o.end.toFixed(1) + 's</span></div>' +
                        '<div class="vi-oturns"><span class="vi-ou">user:</span> ' + esc(clip(o.userText)) +
                        ' <span class="vi-og">agent:</span> ' + esc(clip(o.agentText)) + '</div>' +
                        '<div class="vi-opills">' + pills + '</div></div>'; }}).join('');
            }}

            // Rating.
            var rb = document.getElementById(SCHEMA + '-rating');
            var rh = '';
            for (var v = 1; v <= CONFIG.rating_scale; v++) rh += '<button type="button" class="vi-rbtn" data-v="' + v + '">' + v + '</button>';
            rb.innerHTML = rh;

            bind(); paint();
        }}

        function bind() {{
            var root = document.getElementById(SCHEMA);
            root.querySelectorAll('.vi-lbtn').forEach(function(b) {{
                b.addEventListener('click', function() {{
                    var i = b.getAttribute('data-idx'), l = b.getAttribute('data-l');
                    STATE.overlaps[i] = (STATE.overlaps[i] === l) ? '' : l;
                    if (!STATE.overlaps[i]) delete STATE.overlaps[i];
                    paint(); save();
                }});
            }});
            root.querySelectorAll('.vi-rbtn').forEach(function(b) {{
                b.addEventListener('click', function() {{
                    var v = parseInt(b.getAttribute('data-v'), 10);
                    STATE.rating = (STATE.rating === v) ? 0 : v; paint(); save();
                }});
            }});
        }}

        function paint() {{
            var root = document.getElementById(SCHEMA);
            root.querySelectorAll('.vi-ocard').forEach(function(card) {{
                var i = card.getAttribute('data-idx'), sel = STATE.overlaps[i] || '';
                card.classList.toggle('vi-judged', !!sel);
                card.querySelectorAll('.vi-lbtn').forEach(function(b) {{
                    b.classList.toggle('selected', b.getAttribute('data-l') === sel);
                }});
            }});
            root.querySelectorAll('.vi-rbtn').forEach(function(b) {{
                b.classList.toggle('selected', parseInt(b.getAttribute('data-v'), 10) === STATE.rating);
            }});
        }}

        function save() {{
            var data = {{}};
            if (Object.keys(STATE.overlaps).length) data.overlaps = JSON.parse(JSON.stringify(STATE.overlaps));
            if (STATE.rating) data.rating = STATE.rating;
            var h = hidden();
            if (h) {{
                h.value = Object.keys(data).length ? JSON.stringify(data) : '';
                h.setAttribute('data-modified', 'true');
                h.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
        }}

        function clip(t) {{ t = String(t || ''); return t.length > 50 ? t.slice(0, 49) + '…' : t; }}
        function esc(t) {{ var d = document.createElement('div'); d.textContent = (t==null?'':t); return d.innerHTML; }}

        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
        else build();
        document.addEventListener('instanceChanged', build);
    }})();
    </script>

    <style>
    .voice-interaction-container {{ font-family: inherit; }}
    .vi-title {{ font-weight: 600; font-size: 1em; margin-bottom: 6px; }}
    .vi-audio {{ margin-bottom: 8px; }}
    .vi-timeline-wrap {{ display: flex; align-items: stretch; gap: 8px; }}
    .vi-lane-labels {{ display: flex; flex-direction: column; justify-content: space-around;
                       font-size: 0.72em; color: var(--muted-foreground, #71717a); text-align: right; width: 42px; }}
    .vi-timeline {{ position: relative; flex: 1; height: 64px; border: 1px solid var(--border, #e4e4e7);
                    border-radius: 6px; background: var(--card, #fff); overflow: hidden; }}
    .vi-lane {{ position: absolute; left: 0; right: 0; height: 50%; }}
    .vi-lane-user {{ top: 0; border-bottom: 1px dashed var(--border, #e4e4e7); }}
    .vi-lane-agent {{ top: 50%; }}
    .vi-turn {{ position: absolute; top: 14%; height: 72%; border-radius: 3px; }}
    .vi-turn-user {{ background: #4dabf7; }}
    .vi-turn-agent {{ background: #6e56cf; }}
    .vi-overlap-band {{ position: absolute; top: 0; bottom: 0; background: rgba(224,49,49,0.22);
                        border-left: 1px solid #e03131; border-right: 1px solid #e03131; pointer-events: none; }}
    .vi-overlaps-head {{ margin: 10px 0 4px; font-size: 0.78em; font-weight: 700; text-transform: uppercase;
                         letter-spacing: 0.03em; color: var(--muted-foreground, #71717a); }}
    .vi-overlaps {{ display: flex; flex-direction: column; gap: 8px; }}
    .vi-ocard {{ border: 1px solid var(--border, #e4e4e7); border-radius: var(--radius, 0.5rem);
                 padding: 8px 12px; background: var(--card, #fff); }}
    .vi-ocard.vi-judged {{ border-color: var(--ring, #6e56cf); }}
    .vi-otime {{ font-family: ui-monospace, monospace; font-size: 0.8em; color: #e03131; font-weight: 600; }}
    .vi-oturns {{ font-size: 0.85em; margin: 4px 0; }}
    .vi-ou {{ color: #1971c2; font-weight: 600; }}
    .vi-og {{ color: #5f3dc4; font-weight: 600; }}
    .vi-opills {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    .vi-lbtn, .vi-rbtn {{ border: 1px solid var(--border, #e4e4e7); background: var(--card, #fff);
                          cursor: pointer; color: var(--foreground, #18181b); }}
    .vi-lbtn {{ padding: 3px 10px; font-size: 0.8em; border-radius: 999px; }}
    .vi-lbtn:hover, .vi-rbtn:hover {{ background: var(--secondary, #f4f4f5); }}
    .vi-lbtn:focus-visible, .vi-rbtn:focus-visible {{ outline: 2px solid var(--ring, #6e56cf); outline-offset: 1px; }}
    .vi-lbtn.selected, .vi-rbtn.selected {{ background: var(--ring, #6e56cf); color: #fff; border-color: var(--ring, #6e56cf); font-weight: 600; }}
    .vi-none {{ color: var(--muted-foreground, #71717a); font-style: italic; margin: 8px 0; }}
    .vi-rating-row {{ display: flex; align-items: center; gap: 8px; margin-top: 12px; }}
    .vi-rating-lbl {{ font-size: 0.85em; color: var(--muted-foreground, #71717a); }}
    .vi-rating {{ display: flex; gap: 4px; }}
    .vi-rbtn {{ width: 26px; height: 26px; border-radius: 6px; font-size: 0.8em; }}
    </style>
    """
    logger.info(f"Successfully generated voice_interaction layout for {schema_name}")
    return html, []
