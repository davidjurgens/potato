"""
Video Temporal-Grounding Schema (M10).

Annotates **event time intervals** in a video for temporal-grounding evaluation
(ET-Bench; TimeScope, 2509.26360). For each event prompt the annotator marks the
gold ``[start, end]`` interval — either by capturing the video playhead ("set in/out")
or by typing seconds — and, when the data supplies a model's *predicted* interval,
sees a live **IoU** (temporal intersection-over-union) of prediction vs. gold plus a
two-bar mini-timeline. Distinct from :mod:`video_annotation` (general segment
labeling): this surface is purpose-built for predicted-vs-gold localization scoring.

Input per instance: a ``video`` URL and an ``events`` list of
``{prompt, predicted: {start, end}}`` (predicted optional). Stored as a hidden-input
JSON object ``{"events": {idx: {start, end}}}``. The IIFE seeds from the
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


def generate_temporal_grounding_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    description = annotation_scheme["description"]
    video_key = annotation_scheme.get("video_key", "video")
    events_key = annotation_scheme.get("events_key", "events")
    duration = annotation_scheme.get("duration", 0)  # optional fixed timeline scale (seconds)
    esc_schema = escape_html_content(schema_name)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    config_json = json.dumps({"video_key": video_key, "events_key": events_key, "duration": duration})

    html = f"""
    <form id="{esc_schema}" class="annotation-form temporal-grounding-container"
          action="javascript:void(0)" data-annotation-type="temporal_grounding"
          data-schema-name="{esc_schema}" {layout_attrs}>
        <fieldset schema="{esc_schema}">
            <legend class="tg-title">{escape_html_content(description)}</legend>
            <div class="tg-video" id="{esc_schema}-video"></div>
            <div class="tg-list" id="{esc_schema}-list"></div>
            <div class="tg-empty" id="{esc_schema}-empty" style="display:none;">No events to ground in this item.</div>
            <input type="hidden" class="annotation-input temporal-grounding-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>

    <script>
    (function() {{
        var SCHEMA = '{esc_schema}';
        var CONFIG = {config_json};
        var STATE = {{events: {{}}}};
        var _events = [];

        function instanceData() {{
            try {{
                var el = document.querySelector('[data-instance-json]');
                if (el) return JSON.parse(el.getAttribute('data-instance-json'));
            }} catch(e) {{}}
            var t = document.getElementById('text-content') || document.getElementById('instance-text');
            if (t) {{ try {{ return JSON.parse(t.textContent || t.innerText); }} catch(e2) {{}} }}
            return {{}};
        }}

        function getEvents() {{
            var e = instanceData()[CONFIG.events_key];
            if (!Array.isArray(e)) return [];
            return e.map(function(x, i) {{
                x = (x && typeof x === 'object') ? x : {{prompt: String(x)}};
                var pred = x.predicted || x.prediction || null;
                if (pred && (pred.start === undefined)) pred = null;
                return {{i: i, prompt: x.prompt || x.text || ('event ' + (i+1)),
                         predicted: pred ? {{start: +pred.start, end: +pred.end}} : null}};
            }});
        }}

        function hidden() {{ return document.getElementById(SCHEMA).querySelector('.temporal-grounding-input'); }}
        function restore() {{
            var h = hidden();
            if (h && h.value) {{ try {{ return JSON.parse(h.value) || {{}}; }} catch(e) {{}} }}
            return {{}};
        }}

        function video() {{ return document.getElementById(SCHEMA + '-video').querySelector('video'); }}

        function timelineMax() {{
            var v = video();
            var vd = (v && v.duration && isFinite(v.duration)) ? v.duration : 0;
            var goldMax = 0, predMax = 0;
            Object.keys(STATE.events).forEach(function(k) {{ goldMax = Math.max(goldMax, STATE.events[k].end || 0); }});
            _events.forEach(function(e) {{ if (e.predicted) predMax = Math.max(predMax, e.predicted.end || 0); }});
            return CONFIG.duration || vd || Math.max(goldMax, predMax, 1);
        }}

        function iou(a, b) {{
            if (!a || !b) return null;
            var inter = Math.max(0, Math.min(a.end, b.end) - Math.max(a.start, b.start));
            var uni = Math.max(a.end, b.end) - Math.min(a.start, b.start);
            return uni > 0 ? inter / uni : 0;
        }}

        function build() {{
            var d = instanceData();
            var events = getEvents();
            var prev = restore();
            STATE = {{events: prev.events || {{}}}};

            var vWrap = document.getElementById(SCHEMA + '-video');
            var src = d[CONFIG.video_key];
            vWrap.innerHTML = src ? '<video controls preload="metadata" src="' + esc(src) +
                '" style="width:100%;max-height:360px;border-radius:6px;"></video>' : '';

            var list = document.getElementById(SCHEMA + '-list');
            var empty = document.getElementById(SCHEMA + '-empty');
            if (!events.length) {{ list.innerHTML = ''; if (empty) empty.style.display = ''; return; }}
            if (empty) empty.style.display = 'none';
            _events = events;

            list.innerHTML = events.map(function(e) {{
                var g = STATE.events[e.i] || {{}};
                var predTxt = e.predicted ? ('predicted ' + e.predicted.start + '–' + e.predicted.end + 's') : 'no prediction';
                return '<div class="tg-card" data-idx="' + e.i + '">' +
                    '<div class="tg-prompt">' + esc(e.prompt) + '</div>' +
                    '<div class="tg-controls">' +
                        '<button type="button" class="tg-setin" data-idx="' + e.i + '">⇤ set in</button>' +
                        '<input type="number" step="0.1" class="tg-start" data-idx="' + e.i + '" placeholder="start" value="' + (g.start !== undefined ? g.start : '') + '">' +
                        '<input type="number" step="0.1" class="tg-end" data-idx="' + e.i + '" placeholder="end" value="' + (g.end !== undefined ? g.end : '') + '">' +
                        '<button type="button" class="tg-setout" data-idx="' + e.i + '">set out ⇥</button>' +
                    '</div>' +
                    '<div class="tg-meta"><span class="tg-pred">' + esc(predTxt) + '</span>' +
                        '<span class="tg-iou" data-idx="' + e.i + '"></span></div>' +
                    '<div class="tg-bars" data-idx="' + e.i + '"></div>' +
                    '</div>'; }}).join('');

            bind();
            events.forEach(function(e) {{ paint(e.i); }});
        }}

        function bind() {{
            var root = document.getElementById(SCHEMA);
            root.querySelectorAll('.tg-start, .tg-end').forEach(function(inp) {{
                inp.addEventListener('input', function() {{
                    var i = inp.getAttribute('data-idx');
                    setField(i, inp.classList.contains('tg-start') ? 'start' : 'end', inp.value);
                }});
            }});
            root.querySelectorAll('.tg-setin').forEach(function(b) {{
                b.addEventListener('click', function() {{ captureFromVideo(b.getAttribute('data-idx'), 'start'); }});
            }});
            root.querySelectorAll('.tg-setout').forEach(function(b) {{
                b.addEventListener('click', function() {{ captureFromVideo(b.getAttribute('data-idx'), 'end'); }});
            }});
        }}

        function captureFromVideo(i, field) {{
            var v = video();
            var t = v ? +v.currentTime.toFixed(1) : 0;
            var inp = document.querySelector('.tg-' + field + '[data-idx="' + i + '"]');
            if (inp) inp.value = t;
            setField(i, field, t);
        }}

        function setField(i, field, val) {{
            STATE.events[i] = STATE.events[i] || {{}};
            if (val === '' || val === null || isNaN(+val)) delete STATE.events[i][field];
            else STATE.events[i][field] = +val;
            if (STATE.events[i].start === undefined && STATE.events[i].end === undefined) delete STATE.events[i];
            paint(i); save();
        }}

        function paint(i) {{
            var e = _events.filter(function(x) {{ return x.i == i; }})[0];
            var g = STATE.events[i];
            var card = document.querySelector('.tg-card[data-idx="' + i + '"]');
            if (!card) return;
            var gold = (g && g.start !== undefined && g.end !== undefined && g.end >= g.start) ? g : null;
            card.classList.toggle('tg-set', !!gold);

            var iouEl = card.querySelector('.tg-iou');
            if (e && e.predicted && gold) {{
                var v = iou(gold, e.predicted);
                iouEl.textContent = 'IoU ' + v.toFixed(2);
                iouEl.className = 'tg-iou ' + (v >= 0.5 ? 'tg-iou-good' : v >= 0.3 ? 'tg-iou-mid' : 'tg-iou-bad');
            }} else {{ iouEl.textContent = ''; iouEl.className = 'tg-iou'; }}

            var bars = card.querySelector('.tg-bars');
            var maxT = timelineMax();
            var html = '';
            if (e && e.predicted) html += bar('predicted', e.predicted, maxT, 'tg-bar-pred');
            if (gold) html += bar('gold', gold, maxT, 'tg-bar-gold');
            bars.innerHTML = html;
        }}

        function bar(label, iv, maxT, cls) {{
            var left = 100 * Math.max(0, iv.start) / maxT;
            var width = Math.max(1, 100 * (iv.end - iv.start) / maxT);
            return '<div class="tg-barrow"><span class="tg-barlbl">' + label + '</span>' +
                '<div class="tg-bartrack"><div class="tg-barfill ' + cls + '" style="left:' + left + '%;width:' + width + '%;"></div></div></div>';
        }}

        function save() {{
            var clean = {{}};
            Object.keys(STATE.events).forEach(function(k) {{
                var g = STATE.events[k];
                if (g && (g.start !== undefined || g.end !== undefined)) clean[k] = g;
            }});
            var data = Object.keys(clean).length ? {{events: clean}} : {{}};
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
    .temporal-grounding-container {{ font-family: inherit; }}
    .tg-title {{ font-weight: 600; font-size: 1em; margin-bottom: 6px; }}
    .tg-video {{ margin-bottom: 10px; }}
    .tg-list {{ display: flex; flex-direction: column; gap: 10px; }}
    .tg-card {{ border: 1px solid var(--border, #e4e4e7); border-radius: var(--radius, 0.5rem);
                padding: 10px 12px; background: var(--card, #fff); }}
    .tg-card.tg-set {{ border-color: var(--ring, #6e56cf); }}
    .tg-prompt {{ font-weight: 600; font-size: 0.92em; margin-bottom: 6px; }}
    .tg-controls {{ display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }}
    .tg-controls input {{ width: 80px; padding: 4px 6px; border: 1px solid var(--border, #e4e4e7);
                          border-radius: 6px; font-size: 0.85em; }}
    .tg-setin, .tg-setout {{ padding: 4px 8px; font-size: 0.78em; border: 1px solid var(--border, #e4e4e7);
                             border-radius: 6px; background: var(--card, #fff); cursor: pointer; color: var(--foreground, #18181b); }}
    .tg-setin:hover, .tg-setout:hover {{ background: var(--secondary, #f4f4f5); }}
    .tg-setin:focus-visible, .tg-setout:focus-visible, .tg-controls input:focus-visible {{
        outline: 2px solid var(--ring, #6e56cf); outline-offset: 1px; }}
    .tg-meta {{ display: flex; justify-content: space-between; align-items: baseline; margin: 6px 0 2px; }}
    .tg-pred {{ font-size: 0.78em; color: var(--muted-foreground, #71717a); font-family: ui-monospace, monospace; }}
    .tg-iou {{ font-size: 0.8em; font-weight: 700; }}
    .tg-iou-good {{ color: #2f9e44; }}
    .tg-iou-mid {{ color: #e8590c; }}
    .tg-iou-bad {{ color: #e03131; }}
    .tg-barrow {{ display: flex; align-items: center; gap: 6px; margin-top: 3px; }}
    .tg-barlbl {{ width: 64px; font-size: 0.72em; color: var(--muted-foreground, #71717a); text-align: right; }}
    .tg-bartrack {{ position: relative; flex: 1; height: 12px; background: var(--secondary, #f4f4f5); border-radius: 3px; }}
    .tg-barfill {{ position: absolute; top: 0; bottom: 0; border-radius: 3px; }}
    .tg-bar-pred {{ background: #adb5bd; }}
    .tg-bar-gold {{ background: #6e56cf; }}
    .tg-empty {{ color: var(--muted-foreground, #71717a); font-style: italic; }}
    </style>
    """
    logger.info(f"Successfully generated temporal_grounding layout for {schema_name}")
    return html, []
