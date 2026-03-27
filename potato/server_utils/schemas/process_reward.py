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

    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    esc_schema = escape_html_content(schema_name)

    config_json = json.dumps({
        "steps_key": steps_key,
        "step_text_key": step_text_key,
        "mode": mode,
    })

    html = f"""
    <form id="{esc_schema}" class="annotation-form process-reward-container"
          action="/action_page.php"
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
            var container = document.getElementById(SCHEMA + '-steps');
            if (!container) return;

            container.querySelectorAll('.prm-btn').forEach(function(btn) {{
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

            card.classList.remove('prm-correct', 'prm-incorrect', 'prm-unmarked');
            card.querySelectorAll('.prm-btn').forEach(function(b) {{ b.classList.remove('selected'); }});

            if (reward === 1) {{
                card.classList.add('prm-correct');
                card.querySelector('.prm-btn-correct').classList.add('selected');
                if (status) {{ status.textContent = '\\u2713 correct'; status.className = 'prm-step-status prm-status-correct'; }}
            }} else if (reward === -1) {{
                card.classList.add('prm-incorrect');
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

        // Initialize
        if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', buildCards);
        }} else {{
            buildCards();
        }}

        // Re-build when instance changes (annotation.js fires this)
        document.addEventListener('instanceChanged', buildCards);

        // Expose addStep for live agent integration
        window['_prm_addStep_' + SCHEMA] = function(stepData) {{
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
    </style>
    """

    logger.info(
        f"Successfully generated process_reward layout for {schema_name} "
        f"(mode={mode})"
    )
    return html, []  # No keybindings
