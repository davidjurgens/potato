"""
Aligned-Transcript Speech-Error Schema (M13).

Annotates a time-aligned speech transcript segment by segment for ASR/TTS and
speech-quality errors (Speak&Improve 2025, 2412.11986; NVSpeech). Each segment
``{start, end, text, speaker?}`` becomes a card showing its timestamp and text; the
annotator tags speech errors (ASR error / TTS artifact / mispronunciation /
disfluency …) and can type the corrected text. Shares the time model with
:mod:`voice_interaction` (M9) but is segment-level rather than turn-taking.

Stored as a hidden-input JSON list ``[{index, start, end, errors:[...], correction}]``
keyed by ``index`` (saved is a filtered list of only-annotated segments, so it is NOT
read positionally). The IIFE seeds from the server-restored hidden value before
wiring events (persistence contract).
"""

import json
import logging
from typing import Any, Dict, List, Tuple

from .identifier_utils import (
    safe_generate_layout, generate_element_identifier,
    generate_validation_attribute, escape_html_content, generate_layout_attributes,
)

logger = logging.getLogger(__name__)


def generate_speech_transcript_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    description = annotation_scheme["description"]
    segments_key = annotation_scheme.get("segments_key", "segments")
    audio_key = annotation_scheme.get("audio_key", "audio")
    error_types = annotation_scheme.get(
        "error_types", ["asr_error", "tts_artifact", "mispronunciation", "disfluency"])
    allow_correction = annotation_scheme.get("allow_correction", True)
    esc_schema = escape_html_content(schema_name)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    config_json = json.dumps({
        "segments_key": segments_key, "audio_key": audio_key,
        "error_types": error_types, "allow_correction": bool(allow_correction)})

    html = f"""
    <form id="{esc_schema}" class="annotation-form speech-transcript-container"
          action="javascript:void(0)" data-annotation-type="speech_transcript"
          data-schema-name="{esc_schema}" {layout_attrs}>
        <fieldset schema="{esc_schema}">
            <legend class="st-title">{escape_html_content(description)}</legend>
            <div class="st-audio" id="{esc_schema}-audio"></div>
            <div class="st-list" id="{esc_schema}-list"></div>
            <div class="st-empty" id="{esc_schema}-empty" style="display:none;">No transcript segments in this item.</div>
            <input type="hidden" class="annotation-input speech-transcript-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>

    <script>
    (function() {{
        var SCHEMA = '{esc_schema}';
        var CONFIG = {config_json};
        var _segs = [];

        function instanceData() {{
            try {{
                var el = document.querySelector('[data-instance-json]');
                if (el) return JSON.parse(el.getAttribute('data-instance-json'));
            }} catch(e) {{}}
            var t = document.getElementById('text-content') || document.getElementById('instance-text');
            if (t) {{ try {{ return JSON.parse(t.textContent || t.innerText); }} catch(e2) {{}} }}
            return {{}};
        }}

        function getSegments() {{
            var s = instanceData()[CONFIG.segments_key];
            if (!Array.isArray(s)) return [];
            return s.map(function(x, i) {{
                x = (x && typeof x === 'object') ? x : {{text: String(x)}};
                return {{step: i, start: +(x.start || 0), end: +(x.end || x.start || 0),
                         speaker: x.speaker || x.role || '', text: x.text || x.content || ''}};
            }});
        }}

        function hidden() {{ return document.getElementById(SCHEMA).querySelector('.speech-transcript-input'); }}
        function restore() {{
            var h = hidden();
            if (h && h.value) {{ try {{ return JSON.parse(h.value) || []; }} catch(e) {{}} }}
            return [];
        }}

        function build() {{
            var d = instanceData();
            var segs = getSegments();
            var list = document.getElementById(SCHEMA + '-list');
            var empty = document.getElementById(SCHEMA + '-empty');
            if (!list) return;

            var audWrap = document.getElementById(SCHEMA + '-audio');
            var src = d[CONFIG.audio_key];
            audWrap.innerHTML = src ? '<audio controls preload="metadata" src="' + esc(src) + '" style="width:100%"></audio>' : '';

            if (!segs.length) {{ list.innerHTML = ''; if (empty) empty.style.display = ''; return; }}
            if (empty) empty.style.display = 'none';

            var byIndex = {{}};
            restore().forEach(function(s) {{ if (s && s.index !== undefined) byIndex[s.index] = s; }});
            _segs = segs.map(function(c, idx) {{
                var prev = byIndex[idx] || {{}};
                return {{index: idx, step: c.step, start: c.start, end: c.end, speaker: c.speaker, text: c.text,
                         errors: Array.isArray(prev.errors) ? prev.errors.slice() : [],
                         correction: prev.correction || ''}};
            }});

            list.innerHTML = _segs.map(function(c) {{
                var pills = CONFIG.error_types.map(function(e) {{
                    return '<button type="button" class="st-ebtn" data-idx="' + c.index + '" data-e="' + esc(e) + '">' +
                        esc(e.replace(/_/g,' ')) + '</button>'; }}).join('');
                var corr = CONFIG.allow_correction ?
                    '<input type="text" class="st-correction" data-idx="' + c.index +
                    '" placeholder="corrected transcript (optional)" value="' + esc(c.correction) + '">' : '';
                var ts = (c.end > c.start) ? (c.start.toFixed(1) + '–' + c.end.toFixed(1) + 's') : (c.start.toFixed(1) + 's');
                return '<div class="st-card" data-idx="' + c.index + '">' +
                    '<div class="st-head"><span class="st-time">' + ts + '</span>' +
                    (c.speaker ? '<span class="st-speaker">' + esc(c.speaker) + '</span>' : '') + '</div>' +
                    '<div class="st-text">' + esc(c.text) + '</div>' +
                    '<div class="st-errors">' + pills + '</div>' + corr + '</div>'; }}).join('');

            list.querySelectorAll('.st-ebtn').forEach(function(b) {{
                b.addEventListener('click', function() {{
                    var i = parseInt(b.getAttribute('data-idx'), 10), e = b.getAttribute('data-e');
                    var arr = _segs[i].errors, p = arr.indexOf(e);
                    if (p >= 0) arr.splice(p, 1); else arr.push(e);
                    paint(i); save();
                }});
            }});
            list.querySelectorAll('.st-correction').forEach(function(inp) {{
                inp.addEventListener('input', function() {{
                    _segs[parseInt(inp.getAttribute('data-idx'),10)].correction = inp.value; save();
                }});
            }});
            _segs.forEach(function(c) {{ paint(c.index); }});
        }}

        function paint(i) {{
            var c = _segs[i];
            var card = document.querySelector('.st-card[data-idx="' + i + '"]');
            if (!card) return;
            card.classList.toggle('st-flagged', c.errors.length > 0);
            card.querySelectorAll('.st-ebtn').forEach(function(b) {{
                b.classList.toggle('selected', c.errors.indexOf(b.getAttribute('data-e')) >= 0);
            }});
        }}

        function save() {{
            var data = _segs.filter(function(c) {{ return c.errors.length || c.correction; }})
                .map(function(c) {{ return {{index: c.index, start: c.start, end: c.end,
                                            errors: c.errors, correction: c.correction}}; }});
            var h = hidden();
            if (h) {{
                h.value = data.length ? JSON.stringify(data) : '';
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
    .speech-transcript-container {{ font-family: inherit; }}
    .st-title {{ font-weight: 600; font-size: 1em; margin-bottom: 6px; }}
    .st-audio {{ margin-bottom: 8px; }}
    .st-list {{ display: flex; flex-direction: column; gap: 8px; }}
    .st-card {{ border: 1px solid var(--border, #e4e4e7); border-radius: var(--radius, 0.5rem);
                padding: 8px 12px; background: var(--card, #fff); }}
    .st-card.st-flagged {{ border-color: #e8590c; box-shadow: inset 3px 0 0 #e8590c; }}
    .st-head {{ display: flex; gap: 10px; align-items: baseline; margin-bottom: 2px; }}
    .st-time {{ font-family: ui-monospace, monospace; font-size: 0.78em; color: var(--muted-foreground, #71717a); }}
    .st-speaker {{ font-size: 0.78em; font-weight: 600; color: #5f3dc4; }}
    .st-text {{ font-size: 0.92em; margin-bottom: 6px; }}
    .st-errors {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    .st-ebtn {{ padding: 3px 10px; font-size: 0.8em; border: 1px solid var(--border, #e4e4e7);
                border-radius: 999px; background: var(--card, #fff); cursor: pointer; color: var(--foreground, #18181b); }}
    .st-ebtn:hover {{ background: var(--secondary, #f4f4f5); }}
    .st-ebtn:focus-visible {{ outline: 2px solid var(--ring, #6e56cf); outline-offset: 1px; }}
    .st-ebtn.selected {{ background: #e8590c; color: #fff; border-color: #e8590c; font-weight: 600; }}
    .st-correction {{ margin-top: 6px; width: 100%; box-sizing: border-box; padding: 4px 8px;
                      border: 1px solid var(--border, #e4e4e7); border-radius: 6px; font-size: 0.85em; }}
    .st-empty {{ color: var(--muted-foreground, #71717a); font-style: italic; }}
    </style>
    """
    logger.info(f"Successfully generated speech_transcript layout for {schema_name}")
    return html, []
