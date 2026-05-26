"""
Process Reward Schema

Binary per-step correct/incorrect signals for Process Reward Model (PRM)
training. Two modes:
- "per_step": annotate each step independently with thumbs-up/down
- "first_error": click the first wrong step, all subsequent auto-marked wrong

Research: AgentPRM, ToolRM, ToolRL, SPORT
"""

import json
import logging
from typing import Dict, Any, Tuple, List

from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_validation_attribute,
    escape_html_content,
    generate_layout_attributes,
)

logger = logging.getLogger(__name__)


def generate_process_reward_layout(
    annotation_scheme: Dict[str, Any],
) -> Tuple[str, List[Tuple[str, str]]]:
    """Generate HTML for a process reward annotation interface.

    Args:
        annotation_scheme: Configuration dict.  Required keys: ``name``,
            ``description``.  Optional: ``steps_key``, ``mode``.

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
    mode = annotation_scheme.get("mode", "first_error")  # "first_error" or "per_step"
    # When true, the per-step Correct/Wrong control is injected to the right
    # of each rendered trace step (a [data-turn-index] element) rather than a
    # separate card list at the bottom. Falls back to the card list if no
    # trace step elements are present (e.g. non-trace displays).
    inline_with_trace = bool(annotation_scheme.get("inline_with_trace", False))

    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    esc_schema = escape_html_content(schema_name)

    config_json = json.dumps({
        "steps_key": steps_key,
        "step_text_key": step_text_key,
        "mode": mode,
        "inline_with_trace": inline_with_trace,
    })

    container_class = "process-reward-container"
    if inline_with_trace:
        container_class += " prm-inline-mode"

    html = f"""
    <form id="{esc_schema}" class="annotation-form {container_class}"
          action="javascript:void(0)"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          data-annotation-type="process_reward"
          data-schema-name="{esc_schema}"
          data-steps-key="{escape_html_content(steps_key)}"
          {layout_attrs}>
        <fieldset schema="{esc_schema}">
            <legend class="prm-title">{escape_html_content(description)}</legend>

            <div class="prm-mode-label">
                Mode: <strong>{escape_html_content(mode.replace('_', ' ').title())}</strong>
                {' &mdash; click the first incorrect step' if mode == 'first_error' else ' &mdash; rate each step independently'}
            </div>

            <div class="prm-steps-container" id="{esc_schema}-steps"></div>

            <div class="prm-footer">
                <div class="prm-count" id="{esc_schema}-count"></div>
                <button type="button" class="prm-reset-btn" id="{esc_schema}-reset">Reset All</button>
            </div>

            <input type="hidden"
                   class="annotation-input process-reward-data-input"
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
        var SCHEMA = '{esc_schema}';
        var CONFIG = {config_json};
        var _steps = [];

        function getSteps() {{
            var steps = [];
            try {{
                var el = document.querySelector('[data-instance-json]');
                if (el) {{
                    var d = JSON.parse(el.getAttribute('data-instance-json'));
                    steps = d[CONFIG.steps_key] || [];
                }}
            }} catch(e) {{}}
            if (!steps.length) {{
                var textEl = document.getElementById('text-content') || document.getElementById('instance-text');
                if (textEl) {{
                    try {{
                        var p = JSON.parse(textEl.textContent || textEl.innerText);
                        if (p && p[CONFIG.steps_key]) steps = p[CONFIG.steps_key];
                    }} catch(e2) {{}}
                }}
            }}
            return steps;
        }}

        var INLINE = !!CONFIG.inline_with_trace;

        // Trace step elements, ordered by data-turn-index, scoped to a
        // coding/agent trace so we don't grab unrelated indexed nodes.
        function getStepEls() {{
            var scope = document.querySelector('.coding-trace-display')
                || document.querySelector('.live-coding-agent-viewer')
                || document;
            var els = Array.prototype.slice.call(
                scope.querySelectorAll('[data-turn-index]'));
            els.sort(function(a, b) {{
                return parseInt(a.getAttribute('data-turn-index'), 10)
                     - parseInt(b.getAttribute('data-turn-index'), 10);
            }});
            return els;
        }}

        function initStepModel(steps) {{
            var input = document.getElementById(SCHEMA)
                .querySelector('.process-reward-data-input');
            var existingData = null;
            if (input && input.value) {{
                try {{ existingData = JSON.parse(input.value); }} catch(e) {{}}
            }}
            _steps = [];
            steps.forEach(function(_, i) {{
                var reward = 0;
                if (existingData && existingData.steps && existingData.steps[i]) {{
                    reward = existingData.steps[i].reward || 0;
                }}
                _steps.push({{ index: i, reward: reward }});
            }});
        }}

        function controlHtml(idx) {{
            return '<span class="prm-step-status" id="' + SCHEMA + '-st-' + idx + '"></span>' +
                '<div class="prm-step-btns">' +
                    '<button type="button" class="prm-btn prm-btn-correct" data-step="' + idx + '" data-value="1" title="Correct">&#10003;</button>' +
                    '<button type="button" class="prm-btn prm-btn-incorrect" data-step="' + idx + '" data-value="-1" title="Incorrect">&#10007;</button>' +
                '</div>';
        }}

        // Inline mode: inject a compact control to the right of each rendered
        // trace step. Reuses .prm-step-card markup so attachHandlers() and
        // updateStepVisual() work unchanged.
        // The user prompt turn is not an agent step and must not be rated.
        function isUserTurn(el, stepObj) {{
            if (el && el.classList && el.classList.contains('ct-turn-user')) return true;
            if (stepObj && typeof stepObj === 'object'
                && (stepObj.role === 'user' || stepObj.speaker === 'user')) return true;
            return false;
        }}

        function buildInline() {{
            var bottom = document.getElementById(SCHEMA + '-steps');
            var stepEls = getStepEls();
            var steps = getSteps();
            if (!stepEls.length || !steps.length) return false;

            // Pair each trace element with its step object (by data-turn-index)
            // and keep only ratable agent steps -- the user prompt turn is
            // skipped entirely so it carries no rating control or reward.
            // Keep the structured-turns index ('data-turn-index', which the
            // coding_trace display sets per turn) as the canonical step
            // index. This MUST match buildCards' index space so saved data,
            // first_error cascade and downstream consumers stay consistent
            // across inline/card modes (previously inline used a dense
            // user-filtered counter, corrupting persistence).
            var ratable = [];
            stepEls.forEach(function(el) {{
                var ti = parseInt(el.getAttribute('data-turn-index'), 10);
                if (isNaN(ti)) return;
                var stepObj = (ti < steps.length) ? steps[ti] : null;
                if (isUserTurn(el, stepObj)) return;
                ratable.push({{ el: el, ti: ti }});
            }});
            if (!ratable.length) return false;

            // _steps spans the full step list (same as buildCards) so
            // existingData restore by index aligns; user/non-ratable turns
            // simply carry no card.
            initStepModel(steps);

            ratable.forEach(function(r) {{
                if (r.el.querySelector('.prm-step-card')) return; // already injected
                var card = document.createElement('div');
                card.className = 'prm-step-card prm-inline';
                card.setAttribute('data-step-index', r.ti);
                card.innerHTML = controlHtml(r.ti);
                r.el.classList.add('prm-turn-ratable');
                r.el.appendChild(card);
            }});
            if (bottom) bottom.innerHTML = '';
            attachHandlers();
            _steps.forEach(function(s) {{ updateStepVisual(s.index); }});
            updateCount();
            return true;
        }}

        function buildCards() {{
            var container = document.getElementById(SCHEMA + '-steps');
            if (!container) return;
            var steps = getSteps();
            if (!steps.length) {{
                container.innerHTML = '<div class="prm-no-steps">Waiting for steps\u2026</div>';
                return;
            }}

            // Check for existing value from server (persistence)
            var input = document.getElementById(SCHEMA).querySelector('.process-reward-data-input');
            var existingValue = input ? input.value : '';
            var existingData = null;
            if (existingValue) {{
                try {{ existingData = JSON.parse(existingValue); }} catch(e) {{}}
            }}

            _steps = [];
            steps.forEach(function(_, i) {{
                var reward = 0; // 0 = unmarked, 1 = correct, -1 = incorrect
                if (existingData && existingData.steps && existingData.steps[i]) {{
                    reward = existingData.steps[i].reward || 0;
                }}
                _steps.push({{ index: i, reward: reward }});
            }});

            container.innerHTML = '';
            steps.forEach(function(step, idx) {{
                var stepText = typeof step === 'string'
                    ? step
                    : (step[CONFIG.step_text_key] || step.content || step.reasoning || JSON.stringify(step));

                var card = document.createElement('div');
                card.className = 'prm-step-card';
                card.setAttribute('data-step-index', idx);
                card.innerHTML =
                    '<div class="prm-step-header">' +
                        '<span class="prm-step-num">Step ' + (idx + 1) + '</span>' +
                        '<span class="prm-step-status" id="' + SCHEMA + '-st-' + idx + '"></span>' +
                    '</div>' +
                    '<div class="prm-step-text">' + escapeHtml(stepText) + '</div>' +
                    '<div class="prm-step-btns">' +
                        '<button type="button" class="prm-btn prm-btn-correct" data-step="' + idx + '" data-value="1" title="Correct">&#10003; Correct</button>' +
                        '<button type="button" class="prm-btn prm-btn-incorrect" data-step="' + idx + '" data-value="-1" title="Incorrect">&#10007; Wrong</button>' +
                    '</div>';
                container.appendChild(card);
            }});

            attachHandlers();
            // Restore visual state from _steps
            _steps.forEach(function(s) {{ updateStepVisual(s.index); }});
            updateCount();
        }}

        function attachHandlers() {{
            var btns = [];
            var container = document.getElementById(SCHEMA + '-steps');
            if (container) {{
                btns = btns.concat(Array.prototype.slice.call(
                    container.querySelectorAll('.prm-btn')));
            }}
            // Inline-mode buttons live inside the trace turns, not the
            // bottom container.
            btns = btns.concat(Array.prototype.slice.call(
                document.querySelectorAll('.prm-step-card.prm-inline .prm-btn')));

            btns.forEach(function(btn) {{
                if (btn.getAttribute('data-prm-bound') === '1') return;
                btn.setAttribute('data-prm-bound', '1');
                btn.addEventListener('click', function() {{
                    var idx = parseInt(btn.getAttribute('data-step'), 10);
                    var val = parseInt(btn.getAttribute('data-value'), 10);

                    if (CONFIG.mode === 'first_error') {{
                        handleFirstError(idx, val);
                    }} else {{
                        // per_step mode: toggle
                        if (_steps[idx].reward === val) {{
                            _steps[idx].reward = 0;
                        }} else {{
                            _steps[idx].reward = val;
                        }}
                        updateStepVisual(idx);
                    }}
                    saveState();
                }});
            }});

            var resetBtn = document.getElementById(SCHEMA + '-reset');
            if (resetBtn) {{
                resetBtn.addEventListener('click', function() {{
                    _steps.forEach(function(s) {{
                        s.reward = 0;
                    }});
                    _steps.forEach(function(s) {{ updateStepVisual(s.index); }});
                    saveState();
                }});
            }}
        }}

        function handleFirstError(clickIdx, val) {{
            if (val === 1) {{
                // Marking as correct: only mark this step
                _steps[clickIdx].reward = (_steps[clickIdx].reward === 1) ? 0 : 1;
                updateStepVisual(clickIdx);
            }} else {{
                // Marking as incorrect: this is the first error
                // Toggle off if clicking the same step
                if (_steps[clickIdx].reward === -1) {{
                    // Clear all marks
                    _steps.forEach(function(s) {{
                        s.reward = 0;
                    }});
                }} else {{
                    // All steps before are correct, this and after are incorrect
                    _steps.forEach(function(s) {{
                        if (s.index < clickIdx) {{
                            s.reward = 1;
                        }} else {{
                            s.reward = -1;
                        }}
                    }});
                }}
                _steps.forEach(function(s) {{ updateStepVisual(s.index); }});
            }}
        }}

        function updateStepVisual(idx) {{
            var card = document.querySelector('.prm-step-card[data-step-index="' + idx + '"]');
            if (!card) return;
            var status = document.getElementById(SCHEMA + '-st-' + idx);
            var reward = _steps[idx].reward;
            // In inline mode also tint the surrounding trace step.
            var host = card.closest('[data-turn-index]');

            card.classList.remove('prm-correct', 'prm-incorrect', 'prm-unmarked');
            if (host) host.classList.remove('prm-turn-correct', 'prm-turn-incorrect');
            card.querySelectorAll('.prm-btn').forEach(function(b) {{ b.classList.remove('selected'); }});

            if (reward === 1) {{
                card.classList.add('prm-correct');
                if (host) host.classList.add('prm-turn-correct');
                card.querySelector('.prm-btn-correct').classList.add('selected');
                if (status) {{ status.textContent = '\\u2713 correct'; status.className = 'prm-step-status prm-status-correct'; }}
            }} else if (reward === -1) {{
                card.classList.add('prm-incorrect');
                if (host) host.classList.add('prm-turn-incorrect');
                card.querySelector('.prm-btn-incorrect').classList.add('selected');
                if (status) {{ status.textContent = '\\u2717 incorrect'; status.className = 'prm-step-status prm-status-incorrect'; }}
            }} else {{
                card.classList.add('prm-unmarked');
                if (status) {{ status.textContent = ''; status.className = 'prm-step-status'; }}
            }}
        }}

        function updateCount() {{
            var el = document.getElementById(SCHEMA + '-count');
            if (!el) return;
            var correct = 0, incorrect = 0, total = _steps.length;
            _steps.forEach(function(s) {{
                if (s.reward === 1) correct++;
                else if (s.reward === -1) incorrect++;
            }});
            var unmarked = total - correct - incorrect;
            var parts = [];
            if (correct > 0) parts.push('<span class="prm-count-correct">' + correct + ' correct</span>');
            if (incorrect > 0) parts.push('<span class="prm-count-incorrect">' + incorrect + ' incorrect</span>');
            if (unmarked > 0) parts.push('<span class="prm-count-unmarked">' + unmarked + ' unmarked</span>');
            el.innerHTML = parts.join(' &middot; ') + ' of ' + total + ' steps';
        }}

        function saveState() {{
            var data = JSON.stringify({{ steps: _steps, mode: CONFIG.mode }});
            var input = document.getElementById(SCHEMA).querySelector('.process-reward-data-input');
            if (input) {{
                input.value = data;
                input.setAttribute('data-modified', 'true');
                input.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
            updateCount();
        }}

        function escapeHtml(text) {{
            var d = document.createElement('div');
            d.textContent = text;
            return d.innerHTML;
        }}

        // Dispatcher: inline mode injects controls into the rendered trace;
        // if the trace isn't present yet, retry briefly, then fall back to
        // the bottom card list so non-trace displays still work.
        function build() {{
            if (INLINE) {{
                if (buildInline()) return;
            }}
            buildCards();
        }}

        function buildWithRetry() {{
            if (!INLINE) {{ buildCards(); return; }}
            var tries = 0;
            (function attempt() {{
                if (buildInline()) return;
                if (++tries < 20) {{ setTimeout(attempt, 150); return; }}
                buildCards(); // give up waiting for trace, use bottom list
            }})();
        }}

        // Initialize
        if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', buildWithRetry);
        }} else {{
            buildWithRetry();
        }}

        // Re-build when instance changes (annotation.js fires this)
        document.addEventListener('instanceChanged', buildWithRetry);

        // Expose addStep for live agent integration
        window['_prm_addStep_' + SCHEMA] = function(stepData) {{
            if (INLINE) {{ build(); return; }}
            var container = document.getElementById(SCHEMA + '-steps');
            if (!container) return;
            var waiting = container.querySelector('.prm-no-steps');
            if (waiting) waiting.remove();
            var idx = _steps.length;
            _steps.push({{ index: idx, reward: 0 }});
            // Rebuild to include new step
            buildCards();
        }};
    }})();
    </script>

    <style>
    .process-reward-container {{ font-family: inherit; }}
    .prm-title {{ font-weight: 600; font-size: 1em; margin-bottom: 4px; }}
    .prm-mode-label {{
        font-size: 0.85em; color: var(--muted-foreground, #71717a); margin-bottom: 8px;
        padding: 4px 8px; background: var(--secondary, #f4f4f5); border-radius: var(--radius, 0.5rem);
    }}
    .prm-steps-container {{ display: flex; flex-direction: column; gap: 4px; }}
    .prm-step-card {{
        display: flex; align-items: center; gap: 8px;
        padding: 10px 14px; border: 1px solid var(--border, #e4e4e7); border-radius: var(--radius, 0.5rem);
        background: var(--card, #fff); transition: background 0.15s, border-color 0.15s;
    }}
    .prm-step-card.prm-correct {{
        background: #e8f5e9; border-color: #66bb6a;
    }}
    .prm-step-card.prm-incorrect {{
        background: #ffebee; border-color: #ef5350;
    }}
    .prm-step-header {{
        display: flex; flex-direction: column; align-items: center;
        min-width: 60px; flex: 0 0 auto;
    }}
    .prm-step-num {{
        font-size: 0.8em; font-weight: 600; color: var(--muted-foreground, #71717a);
    }}
    .prm-step-status {{ font-size: 0.75em; margin-top: 2px; }}
    .prm-status-correct {{ color: #2e7d32; }}
    .prm-status-incorrect {{ color: #c62828; }}
    .prm-step-text {{
        flex: 1; font-size: 0.9em; white-space: pre-wrap;
        word-break: break-word; line-height: 1.4;
        max-height: 80px; overflow-y: auto;
    }}
    .prm-step-btns {{
        display: flex; gap: 6px; flex: 0 0 auto;
    }}
    .prm-btn {{
        height: 36px; border: 1px solid var(--border, #e4e4e7); border-radius: var(--radius, 0.5rem);
        background: var(--card, #fff); cursor: pointer; font-size: 13px;
        padding: 0 12px; transition: all 0.15s; display: inline-flex;
        align-items: center; gap: 4px; white-space: nowrap;
    }}
    .prm-btn:hover {{ border-color: #999; background: var(--secondary, #f4f4f5); }}
    .prm-btn:focus-visible {{ outline: 2px solid var(--ring, #6e56cf); outline-offset: 2px; }}
    .prm-btn-correct.selected {{
        background: #4caf50; color: #fff; border-color: #4caf50;
    }}
    .prm-btn-incorrect.selected {{
        background: #f44336; color: #fff; border-color: #f44336;
    }}
    .prm-footer {{
        margin-top: 10px; display: flex; align-items: center; gap: 12px;
    }}
    .prm-count {{
        font-size: 0.85em; color: var(--muted-foreground, #71717a); flex: 1;
    }}
    .prm-count-correct {{ color: #2e7d32; font-weight: 500; }}
    .prm-count-incorrect {{ color: #c62828; font-weight: 500; }}
    .prm-count-unmarked {{ color: var(--muted-foreground, #71717a); }}
    .prm-reset-btn {{
        padding: 4px 12px; font-size: 0.85em; border: 1px solid var(--border, #e4e4e7);
        border-radius: var(--radius, 0.5rem); background: var(--card, #fff);
        cursor: pointer; color: var(--muted-foreground, #71717a);
    }}
    .prm-reset-btn:hover {{ background: var(--secondary, #f4f4f5); }}
    .prm-reset-btn:focus-visible {{ outline: 2px solid var(--ring, #6e56cf); outline-offset: 2px; }}
    .prm-no-steps {{
        padding: 12px; color: var(--muted-foreground, #71717a); font-style: italic; text-align: center;
    }}

    /* ---- Inline mode: control sits to the right of each trace step ---- */
    .prm-inline-mode .prm-steps-container {{ display: none; }}
    .prm-inline-mode .prm-mode-label {{ margin-bottom: 4px; }}
    .prm-inline-mode .prm-footer {{ margin-top: 6px; }}

    /* Host trace step gets room on the right for the control. */
    [data-turn-index].prm-turn-ratable {{
        position: relative;
        padding-right: 84px;
    }}
    .prm-step-card.prm-inline {{
        position: absolute;
        top: 8px;
        right: 8px;
        display: flex;
        align-items: center;
        gap: 4px;
        padding: 0;
        border: 0;
        background: transparent;
        z-index: 2;
    }}
    .prm-step-card.prm-inline .prm-step-btns {{ gap: 4px; }}
    .prm-step-card.prm-inline .prm-btn {{
        height: 26px; min-width: 26px; padding: 0 7px; font-size: 13px;
        line-height: 1; border-radius: 6px;
    }}
    .prm-step-card.prm-inline .prm-step-status {{
        font-size: 0.7em; margin-right: 2px; white-space: nowrap;
    }}
    /* Subtle tint on the rated step (kept light so diffs stay readable). */
    [data-turn-index].prm-turn-correct {{
        box-shadow: inset 3px 0 0 #4caf50; background: rgba(76, 175, 80, 0.05);
    }}
    [data-turn-index].prm-turn-incorrect {{
        box-shadow: inset 3px 0 0 #f44336; background: rgba(244, 67, 54, 0.05);
    }}
    </style>
    """

    logger.info(
        f"Successfully generated process_reward layout for {schema_name} "
        f"(mode={mode})"
    )
    return html, []  # No keybindings
