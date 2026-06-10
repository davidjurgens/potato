"""
Trajectory Correction / Editing Layout

Annotators rewrite the steps of an agent trace (reasoning, tool calls,
observations) and optionally the final answer, producing a *corrected*
trajectory alongside the original. The corrected/original pair is exported as
SFT targets and DPO preference pairs (see
``potato/export/trajectory_correction_exporter.py``).

This is the editing counterpart to ``trajectory_eval`` (which *scores* steps).
It reuses ``trajectory_eval``'s data-loading + per-step-card structure and
``text_edit``'s live word/char diff. Each step shows the original text
read-only plus an editable textarea pre-filled with the original; a per-step
"edited" flag is set automatically when the text diverges.

Research / motivation: Labelbox Agent Trajectory Editor; Datadog "edited
outputs"; SFT/DPO post-training from human-corrected trajectories.
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

DEFAULT_EDITABLE_FIELDS = ["action"]


def generate_trajectory_edit_layout(
    annotation_scheme: Dict[str, Any],
) -> Tuple[str, List[Tuple[str, str]]]:
    """Generate HTML for a trajectory correction/editing interface.

    Args:
        annotation_scheme: Configuration dict. Required: ``name``,
            ``description``. Optional: ``steps_key``, ``step_text_key``,
            ``editable_fields``, ``show_diff``, ``show_edit_distance``,
            ``allow_reset``, ``require_reason_on_edit``, ``edit_final_answer``,
            ``final_answer_key``.

    Returns:
        ``(html, keybindings)`` tuple.
    """
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(
    annotation_scheme: Dict[str, Any],
) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    description = annotation_scheme["description"]

    steps_key = annotation_scheme.get("steps_key", "steps")
    step_text_key = annotation_scheme.get("step_text_key", "action")
    editable_fields = annotation_scheme.get("editable_fields") or [step_text_key]
    if not isinstance(editable_fields, list):
        editable_fields = [step_text_key]
    show_diff = annotation_scheme.get("show_diff", True)
    show_edit_distance = annotation_scheme.get("show_edit_distance", True)
    allow_reset = annotation_scheme.get("allow_reset", True)
    require_reason_on_edit = annotation_scheme.get("require_reason_on_edit", False)
    edit_final_answer = annotation_scheme.get("edit_final_answer", False)
    final_answer_key = annotation_scheme.get("final_answer_key", "final_answer")

    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")

    config_json = json.dumps({
        "steps_key": steps_key,
        "step_text_key": step_text_key,
        "editable_fields": editable_fields,
        "show_diff": show_diff,
        "show_edit_distance": show_edit_distance,
        "allow_reset": allow_reset,
        "require_reason_on_edit": require_reason_on_edit,
        "edit_final_answer": edit_final_answer,
        "final_answer_key": final_answer_key,
    })

    esc_schema = escape_html_content(schema_name)

    html = f"""
    <form id="{esc_schema}" class="annotation-form trajectory-edit-container"
          action="javascript:void(0)"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          data-annotation-type="trajectory_edit"
          data-schema-name="{esc_schema}"
          data-steps-key="{escape_html_content(steps_key)}"
          data-step-text-key="{escape_html_content(step_text_key)}"
          {layout_attrs}>
        <fieldset schema="{esc_schema}">
            <legend class="trajedit-title">{escape_html_content(description)}</legend>

            <div class="trajedit-summary" id="{esc_schema}-summary">
                <span class="trajedit-summary-item">Steps edited:
                    <strong id="{esc_schema}-n-edited">0</strong></span>
                <span class="trajedit-summary-item">Total edit distance:
                    <strong id="{esc_schema}-total-dist">0</strong></span>
            </div>

            <!-- Step editors rendered by JS from instance data -->
            <div class="trajedit-steps-container" id="{esc_schema}-steps"></div>

            <input type="hidden"
                   class="annotation-input trajectory-edit-data-input"
                   id="{identifiers['id']}"
                   name="{identifiers['name']}"
                   schema="{identifiers['schema']}"
                   label_name="{identifiers['label_name']}"
                   validation="{validation}"
                   value="">
        </fieldset>
    </form>

    <script>
    (function() {{
        var _trajEditState = {{}};
        var SCHEMA = '{esc_schema}';
        var CONFIG = {config_json};

        function getState() {{
            if (!_trajEditState[SCHEMA]) {{
                _trajEditState[SCHEMA] = {{ entries: {{}}, final_answer: null }};
            }}
            return _trajEditState[SCHEMA];
        }}

        function entryKey(idx, field) {{ return idx + '::' + field; }}

        /* ---- read steps from the embedded instance data ---- */
        function readInstance() {{
            try {{
                var el = document.querySelector('[data-instance-json]');
                if (el) return JSON.parse(el.getAttribute('data-instance-json'));
            }} catch (e) {{}}
            // Fallback: parse displayed text content as JSON
            var textEl = document.getElementById('text-content') ||
                         document.getElementById('instance-text');
            if (textEl) {{
                try {{ return JSON.parse(textEl.textContent || textEl.innerText); }}
                catch (e2) {{}}
            }}
            return {{}};
        }}

        function getStepText(step, field) {{
            if (step == null) return '';
            if (typeof step === 'string') return field === CONFIG.step_text_key ? step : '';
            var v = step[field];
            if (v == null) return '';
            return typeof v === 'string' ? v : JSON.stringify(v);
        }}

        /* ---- build editors ---- */
        function buildEditors() {{
            var container = document.getElementById(SCHEMA + '-steps');
            if (!container) return;

            var instance = readInstance();
            var steps = (instance && instance[CONFIG.steps_key]) || [];

            if (!steps.length) {{
                container.innerHTML = '<div class="trajedit-no-steps">' +
                    'No trace steps found in field "' + escapeHtml(CONFIG.steps_key) +
                    '".</div>';
                return;
            }}

            container.innerHTML = '';
            steps.forEach(function(step, idx) {{
                container.appendChild(buildStepCard(step, idx));
            }});

            if (CONFIG.edit_final_answer) {{
                var fa = instance ? instance[CONFIG.final_answer_key] : null;
                if (fa != null) {{
                    container.appendChild(buildFinalAnswerCard(
                        typeof fa === 'string' ? fa : JSON.stringify(fa)));
                }}
            }}
        }}

        function buildEditorBlock(idx, field, original, edited) {{
            var keyAttr = 'data-step="' + idx + '" data-field="' + escapeHtml(field) + '"';
            var fieldLabel = field.charAt(0).toUpperCase() + field.slice(1);
            var textareaId = SCHEMA + '-editor-' + idx + '-' + field;
            var origId = SCHEMA + '-orig-' + idx + '-' + field;
            // Tool/action fields are code-like → monospace for precise editing.
            var monoCls = (field === CONFIG.step_text_key) ? ' trajedit-mono' : '';
            var resetBtn = CONFIG.allow_reset
                ? '<button type="button" class="trajedit-reset-btn" ' + keyAttr +
                  '>Reset</button>'
                : '';
            var distHtml = CONFIG.show_edit_distance
                ? '<div class="trajedit-stats"><span>Words changed: <strong class="trajedit-word-dist" ' +
                  keyAttr + '>0</strong></span> <span>Chars changed: <strong class="trajedit-char-dist" ' +
                  keyAttr + '>0</strong></span></div>'
                : '';
            var diffHtml = CONFIG.show_diff
                ? '<div class="trajedit-diff"><div class="trajedit-diff-label">Changes:</div>' +
                  '<div class="trajedit-diff-content" ' + keyAttr + '></div></div>'
                : '';
            var reasonHtml = CONFIG.require_reason_on_edit
                ? '<div class="trajedit-reason-block"><label class="trajedit-reason-label">' +
                  'Reason for edit:</label><input type="text" class="trajedit-reason" ' + keyAttr +
                  ' placeholder="why this change?"></div>'
                : '';
            return '<div class="trajedit-field-block">' +
                '<div class="trajedit-field-label">' + escapeHtml(fieldLabel) +
                    ' <span class="trajedit-edited-flag" ' + keyAttr + '></span></div>' +
                '<div class="trajedit-original' + monoCls + '" id="' + origId + '">' +
                    '<span class="trajedit-original-label">Original: </span>' +
                    '<span class="trajedit-original-text" ' + keyAttr + '>' + escapeHtml(original) + '</span></div>' +
                '<label class="trajedit-editor-label" for="' + textareaId + '">Corrected:</label>' +
                '<textarea class="trajedit-textarea' + monoCls + '" id="' + textareaId + '" ' + keyAttr +
                    ' rows="2" aria-describedby="' + origId +
                    '" aria-label="Corrected ' + escapeHtml(fieldLabel) + ' for step ' + (idx + 1) +
                    '">' + escapeHtml(edited) + '</textarea>' +
                distHtml + diffHtml + reasonHtml + resetBtn +
                '</div>';
        }}

        function buildStepCard(step, idx) {{
            var card = document.createElement('div');
            card.className = 'trajedit-step-card';
            card.setAttribute('data-step-index', idx);

            var thought = (step && typeof step === 'object' && step.thought &&
                           CONFIG.editable_fields.indexOf('thought') === -1)
                ? '<div class="trajedit-step-thought"><span class="trajedit-thought-label">Thought:</span> ' +
                  escapeHtml(getStepText(step, 'thought')) + '</div>'
                : '';

            var blocks = '';
            CONFIG.editable_fields.forEach(function(field) {{
                var original = getStepText(step, field);
                // Only render an editor for fields that exist on the step
                if (original === '' && !(step && typeof step === 'object' && field in step)) return;
                var saved = getState().entries[entryKey(idx, field)];
                var edited = saved ? saved.edited_text : original;
                blocks += buildEditorBlock(idx, field, original, edited);
            }});

            card.innerHTML =
                '<div class="trajedit-step-header"><span class="trajedit-step-number">Step ' +
                    (idx + 1) + '</span></div>' + thought + blocks;
            attachBlockHandlers(card);
            return card;
        }}

        function buildFinalAnswerCard(original) {{
            var card = document.createElement('div');
            card.className = 'trajedit-step-card trajedit-final-card';
            card.setAttribute('data-final', 'true');
            var saved = getState().final_answer;
            var edited = saved ? saved.edited_text : original;
            var keyAttr = 'data-final="true"';
            var resetBtn = CONFIG.allow_reset
                ? '<button type="button" class="trajedit-reset-btn" ' + keyAttr + '>Reset</button>' : '';
            var distHtml = CONFIG.show_edit_distance
                ? '<div class="trajedit-stats"><span>Words changed: <strong class="trajedit-word-dist" ' +
                  keyAttr + '>0</strong></span> <span>Chars changed: <strong class="trajedit-char-dist" ' +
                  keyAttr + '>0</strong></span></div>' : '';
            var diffHtml = CONFIG.show_diff
                ? '<div class="trajedit-diff"><div class="trajedit-diff-label">Changes:</div>' +
                  '<div class="trajedit-diff-content" ' + keyAttr + '></div></div>' : '';
            card.innerHTML =
                '<div class="trajedit-step-header"><span class="trajedit-step-number trajedit-final-label">' +
                    'Final Answer</span> <span class="trajedit-edited-flag" ' + keyAttr + '></span></div>' +
                '<div class="trajedit-original"><span class="trajedit-original-label">Original:</span> ' +
                    '<span class="trajedit-original-text" ' + keyAttr + '>' + escapeHtml(original) + '</span></div>' +
                '<label class="trajedit-editor-label">Corrected:</label>' +
                '<textarea class="trajedit-textarea" ' + keyAttr +
                    ' rows="3" aria-label="Corrected final answer">' + escapeHtml(edited) + '</textarea>' +
                distHtml + diffHtml + resetBtn;
            attachBlockHandlers(card);
            return card;
        }}

        /* ---- handlers ---- */
        function blockSelector(el, cls) {{
            var isFinal = el.getAttribute('data-final') === 'true';
            var card = el.closest('.trajedit-step-card');
            if (isFinal) return card.querySelector('.' + cls + '[data-final="true"]');
            var idx = el.getAttribute('data-step');
            var field = el.getAttribute('data-field');
            return card.querySelector('.' + cls + '[data-step="' + idx + '"][data-field="' + field + '"]');
        }}

        function onEdit(textarea) {{
            var isFinal = textarea.getAttribute('data-final') === 'true';
            var card = textarea.closest('.trajedit-step-card');
            var originalEl = blockSelector(textarea, 'trajedit-original-text');
            var original = originalEl ? originalEl.textContent : '';
            var edited = textarea.value;

            var srcWords = original.trim().split(/\\s+/).filter(Boolean);
            var editWords = edited.trim().split(/\\s+/).filter(Boolean);
            var wordDist = levenshtein(srcWords, editWords);
            var charDist = levenshteinStr(original, edited);
            var isEdited = edited !== original;

            if (CONFIG.show_edit_distance) {{
                var w = blockSelector(textarea, 'trajedit-word-dist');
                var c = blockSelector(textarea, 'trajedit-char-dist');
                if (w) w.textContent = wordDist;
                if (c) c.textContent = charDist;
            }}
            if (CONFIG.show_diff) {{
                var d = blockSelector(textarea, 'trajedit-diff-content');
                if (d) d.innerHTML = computeWordDiff(srcWords, editWords);
            }}
            var flag = blockSelector(textarea, 'trajedit-edited-flag');
            if (flag) flag.textContent = isEdited ? '✎ edited' : '';
            // Non-color cue: mark the enclosing block/card edited (border accent).
            var block = textarea.closest('.trajedit-field-block') ||
                        textarea.closest('.trajedit-step-card');
            if (block) block.classList.toggle('trajedit-edited', isEdited);
            // Auto-grow to fit content (capped via CSS max-height).
            textarea.style.height = 'auto';
            textarea.style.height = Math.min(textarea.scrollHeight, 400) + 'px';

            var state = getState();
            if (isFinal) {{
                state.final_answer = {{
                    original_text: original, edited_text: edited, edited: isEdited,
                    edit_distance_chars: charDist, edit_distance_words: wordDist
                }};
            }} else {{
                var idx = parseInt(textarea.getAttribute('data-step'), 10);
                var field = textarea.getAttribute('data-field');
                var reasonEl = blockSelector(textarea, 'trajedit-reason');
                state.entries[entryKey(idx, field)] = {{
                    step_index: idx, field: field, original_text: original,
                    edited_text: edited, edited: isEdited,
                    edit_distance_chars: charDist, edit_distance_words: wordDist,
                    reason: reasonEl ? reasonEl.value : ''
                }};
            }}
            saveState();
        }}

        function attachBlockHandlers(card) {{
            card.querySelectorAll('.trajedit-textarea').forEach(function(ta) {{
                ta.addEventListener('input', function() {{ onEdit(ta); }});
            }});
            card.querySelectorAll('.trajedit-reason').forEach(function(inp) {{
                inp.addEventListener('input', function() {{
                    var ta = blockSelector(inp, 'trajedit-textarea');
                    if (ta) onEdit(ta);
                }});
            }});
            card.querySelectorAll('.trajedit-reset-btn').forEach(function(btn) {{
                btn.addEventListener('click', function() {{
                    var ta = blockSelector(btn, 'trajedit-textarea');
                    var orig = blockSelector(btn, 'trajedit-original-text');
                    if (ta && orig) {{ ta.value = orig.textContent; onEdit(ta); }}
                }});
            }});
        }}

        /* ---- persistence ---- */
        function saveState() {{
            var state = getState();
            var steps = [];
            var nEdited = 0, totalDist = 0;
            Object.keys(state.entries).forEach(function(k) {{
                var e = state.entries[k];
                steps.push(e);
                if (e.edited) {{ nEdited += 1; totalDist += (e.edit_distance_chars || 0); }}
            }});
            if (state.final_answer && state.final_answer.edited) {{
                nEdited += 1; totalDist += (state.final_answer.edit_distance_chars || 0);
            }}
            steps.sort(function(a, b) {{
                return a.step_index - b.step_index || (a.field < b.field ? -1 : 1);
            }});

            var nEl = document.getElementById(SCHEMA + '-n-edited');
            var tEl = document.getElementById(SCHEMA + '-total-dist');
            if (nEl) nEl.textContent = nEdited;
            if (tEl) tEl.textContent = totalDist;

            var data = JSON.stringify({{
                steps: steps,
                final_answer: state.final_answer,
                n_steps_edited: nEdited,
                total_edit_distance: totalDist
            }});
            var input = document.getElementById(SCHEMA).querySelector('.trajectory-edit-data-input');
            if (input) {{
                input.value = data;
                input.setAttribute('data-modified', 'true');
                input.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
        }}

        // CRITICAL (IIFE-overwrite guard): load server-restored value into
        // state BEFORE building editors, so buildStepCard prefills textareas
        // with the saved edited_text rather than clobbering it with originals.
        function restoreFromHiddenInput() {{
            var input = document.getElementById(SCHEMA).querySelector('.trajectory-edit-data-input');
            if (!input) return false;
            if (input.getAttribute('data-server-set') === null &&
                !(input.getAttribute('value') || input.value)) return false;
            var val = input.getAttribute('value') || input.value;
            if (!val) return false;
            try {{
                var data = JSON.parse(val);
                var state = getState();
                (data.steps || []).forEach(function(e) {{
                    state.entries[entryKey(e.step_index, e.field)] = e;
                }});
                state.final_answer = data.final_answer || null;
                return true;
            }} catch (e) {{ return false; }}
        }}

        function restoreVisualState() {{
            // Re-run onEdit for each textarea so diff/flags/stats reflect saved text.
            var container = document.getElementById(SCHEMA + '-steps');
            if (!container) return;
            container.querySelectorAll('.trajedit-textarea').forEach(function(ta) {{
                var isFinal = ta.getAttribute('data-final') === 'true';
                var state = getState();
                var saved = isFinal ? state.final_answer
                    : state.entries[entryKey(parseInt(ta.getAttribute('data-step'), 10),
                                             ta.getAttribute('data-field'))];
                if (saved) ta.value = saved.edited_text;
                if (saved && saved.reason) {{
                    var r = blockSelector(ta, 'trajedit-reason');
                    if (r) r.value = saved.reason;
                }}
                onEdit(ta);
            }});
        }}

        /* ---- diff helpers (from text_edit) ---- */
        function levenshtein(a, b) {{
            var m = a.length, n = b.length;
            var dp = Array.from({{length: m + 1}}, function() {{ return new Array(n + 1).fill(0); }});
            for (var i = 0; i <= m; i++) dp[i][0] = i;
            for (var j = 0; j <= n; j++) dp[0][j] = j;
            for (var i = 1; i <= m; i++)
                for (var j = 1; j <= n; j++)
                    dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1] :
                        1 + Math.min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1]);
            return dp[m][n];
        }}
        function levenshteinStr(a, b) {{
            var m = a.length, n = b.length;
            if (m === 0) return n;
            if (n === 0) return m;
            var prev = new Array(n + 1), curr = new Array(n + 1);
            for (var j = 0; j <= n; j++) prev[j] = j;
            for (var i = 1; i <= m; i++) {{
                curr[0] = i;
                for (var j = 1; j <= n; j++)
                    curr[j] = a[i-1] === b[j-1] ? prev[j-1] :
                        1 + Math.min(prev[j], curr[j-1], prev[j-1]);
                var tmp = prev; prev = curr; curr = tmp;
            }}
            return prev[n];
        }}
        function computeWordDiff(srcWords, editWords) {{
            var html = '', si = 0, ei = 0, li = 0;
            var lcs = lcsWords(srcWords, editWords);
            while (si < srcWords.length || ei < editWords.length) {{
                if (li < lcs.length && si < srcWords.length && ei < editWords.length &&
                    srcWords[si] === lcs[li] && editWords[ei] === lcs[li]) {{
                    html += '<span class="trajedit-diff-same">' + escapeHtml(lcs[li]) + '</span> ';
                    si++; ei++; li++;
                }} else if (li < lcs.length && ei < editWords.length && editWords[ei] === lcs[li]) {{
                    html += '<span class="trajedit-diff-del">' + escapeHtml(srcWords[si]) + '</span> '; si++;
                }} else if (li < lcs.length && si < srcWords.length && srcWords[si] === lcs[li]) {{
                    html += '<span class="trajedit-diff-ins">' + escapeHtml(editWords[ei]) + '</span> '; ei++;
                }} else {{
                    if (si < srcWords.length) {{ html += '<span class="trajedit-diff-del">' + escapeHtml(srcWords[si]) + '</span> '; si++; }}
                    if (ei < editWords.length) {{ html += '<span class="trajedit-diff-ins">' + escapeHtml(editWords[ei]) + '</span> '; ei++; }}
                }}
            }}
            return html;
        }}
        function lcsWords(a, b) {{
            var m = a.length, n = b.length;
            var dp = Array.from({{length: m + 1}}, function() {{ return new Array(n + 1).fill(0); }});
            for (var i = 1; i <= m; i++)
                for (var j = 1; j <= n; j++)
                    dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1] + 1 : Math.max(dp[i-1][j], dp[i][j-1]);
            var result = [], i = m, j = n;
            while (i > 0 && j > 0) {{
                if (a[i-1] === b[j-1]) {{ result.unshift(a[i-1]); i--; j--; }}
                else if (dp[i-1][j] > dp[i][j-1]) i--; else j--;
            }}
            return result;
        }}
        function escapeHtml(str) {{
            var div = document.createElement('div');
            div.textContent = str == null ? '' : str;
            return div.innerHTML;
        }}

        /* ---- init ---- */
        var hadServerData = restoreFromHiddenInput();
        function tryBuild() {{
            buildEditors();
            if (hadServerData) restoreVisualState();
        }}
        if (document.readyState === 'complete') tryBuild();
        else document.addEventListener('DOMContentLoaded', tryBuild);

        // Expose for the annotation.js restore pipeline / tests
        window._trajEditState = _trajEditState;
        window._trajEditBuild = buildEditors;
        window._trajEditRestore = restoreVisualState;
        window._trajEditSave = saveState;
    }})();
    </script>
    """

    logger.info(f"Generated trajectory edit layout for {schema_name}")
    return html, []
