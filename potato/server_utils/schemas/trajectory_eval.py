"""
Trajectory Evaluation Layout

Per-step error marking for agent traces. For each step the annotator marks:
correctness (correct / incorrect / partially_correct), error type from a
configurable taxonomy, severity, and a free-text rationale.

Research: TRAIL (Trace Reasoning and Agentic Issue Localization),
          AgentRewardBench, Anthropic "Demystifying Evals for AI Agents".
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

DEFAULT_CORRECTNESS = ["correct", "incorrect", "partially_correct"]
DEFAULT_SEVERITIES = [
    {"name": "minor", "weight": -1},
    {"name": "major", "weight": -5},
    {"name": "critical", "weight": -10},
]


def generate_trajectory_eval_layout(
    annotation_scheme: Dict[str, Any],
) -> Tuple[str, List[Tuple[str, str]]]:
    """Generate HTML for a trajectory evaluation interface.

    Args:
        annotation_scheme: Configuration dict.  Required keys: ``name``,
            ``description``.  Optional: ``steps_key``, ``step_text_key``,
            ``correctness_options``, ``error_types``, ``severities``,
            ``show_score``.

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
    correctness_options = annotation_scheme.get("correctness_options", DEFAULT_CORRECTNESS)
    error_types = annotation_scheme.get("error_types", [])
    severities = annotation_scheme.get("severities", DEFAULT_SEVERITIES)
    show_score = annotation_scheme.get("show_score", True)
    max_score = annotation_scheme.get("max_score", 100)

    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")

    # Serialize config for JS IIFE
    config_json = json.dumps({
        "steps_key": steps_key,
        "step_text_key": step_text_key,
        "correctness_options": correctness_options,
        "error_types": error_types,
        "severities": severities,
        "show_score": show_score,
        "max_score": max_score,
    })

    # Build error type <option> elements
    type_options_html = '<option value="">-- select error type --</option>'
    for et in error_types:
        subtypes = et.get("subtypes", [])
        if subtypes:
            type_options_html += f'<optgroup label="{escape_html_content(et["name"])}">'
            for st in subtypes:
                val = f'{escape_html_content(et["name"])}::{escape_html_content(st)}'
                type_options_html += f'<option value="{val}">{escape_html_content(st)}</option>'
            type_options_html += "</optgroup>"
        else:
            type_options_html += (
                f'<option value="{escape_html_content(et["name"])}">'
                f'{escape_html_content(et["name"])}</option>'
            )

    # Build severity radio buttons
    severity_radios_html = ""
    for sev in severities:
        severity_radios_html += f"""
            <label class="traj-severity-option">
                <input type="radio" class="traj-severity-radio"
                       name="traj-severity-STEPIDX-{escape_html_content(schema_name)}"
                       value="{escape_html_content(sev['name'])}">
                <span>{escape_html_content(sev['name'])} ({sev['weight']:+d})</span>
            </label>"""

    # Build correctness buttons
    correctness_btns = ""
    for opt in correctness_options:
        label = opt.replace("_", " ").title()
        css_cls = f"traj-correctness-{opt}"
        correctness_btns += (
            f'<button type="button" class="traj-correctness-btn {css_cls}" '
            f'data-value="{escape_html_content(opt)}">'
            f'{escape_html_content(label)}</button> '
        )

    score_html = ""
    if show_score:
        score_html = f"""
            <div class="traj-score" id="{escape_html_content(schema_name)}-score">
                Score: <strong id="{escape_html_content(schema_name)}-score-value">{max_score}</strong> / {max_score}
            </div>"""

    esc_schema = escape_html_content(schema_name)

    html = f"""
    <form id="{esc_schema}" class="annotation-form trajectory-eval-container"
          action="/action_page.php"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          data-annotation-type="trajectory_eval"
          data-schema-name="{esc_schema}"
          data-steps-key="{escape_html_content(steps_key)}"
          data-step-text-key="{escape_html_content(step_text_key)}"
          {layout_attrs}>
        <fieldset schema="{esc_schema}">
            <legend class="traj-eval-title">{escape_html_content(description)}</legend>

            {score_html}

            <!-- Step cards rendered by JS from instance data -->
            <div class="traj-steps-container" id="{esc_schema}-steps"></div>

            <input type="hidden"
                   class="annotation-input trajectory-eval-data-input"
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
        var _trajState = {{}};
        var SCHEMA = '{esc_schema}';
        var CONFIG = {config_json};
        var TYPE_OPTIONS_HTML = {json.dumps(type_options_html)};
        var SEVERITY_RADIOS_TEMPLATE = {json.dumps(severity_radios_html)};
        var CORRECTNESS_BTNS_TEMPLATE = {json.dumps(correctness_btns)};

        function getState() {{
            if (!_trajState[SCHEMA]) {{
                _trajState[SCHEMA] = {{ steps: [] }};
            }}
            return _trajState[SCHEMA];
        }}

        /* ---- build step cards from instance data ---- */
        function buildStepCards() {{
            var container = document.getElementById(SCHEMA + '-steps');
            if (!container) return;

            // Read steps from the instance data embedded in the page
            var steps = [];
            try {{
                var instanceDataEl = document.querySelector('[data-instance-json]');
                if (instanceDataEl) {{
                    var instanceData = JSON.parse(instanceDataEl.getAttribute('data-instance-json'));
                    steps = instanceData[CONFIG.steps_key] || [];
                }}
            }} catch(e) {{}}

            // Fallback: try reading from the displayed text content
            if (!steps.length) {{
                var textEl = document.getElementById('text-content') || document.getElementById('instance-text');
                if (textEl) {{
                    try {{
                        var parsed = JSON.parse(textEl.textContent || textEl.innerText);
                        if (parsed && parsed[CONFIG.steps_key]) {{
                            steps = parsed[CONFIG.steps_key];
                        }}
                    }} catch(e2) {{}}
                }}
            }}

            if (!steps.length) {{
                // Show waiting state instead of error — steps may arrive
                // dynamically via live agent SSE events
                container.innerHTML = '<div class="traj-no-steps traj-waiting-steps">' +
                    'Waiting for agent steps\u2026 ' +
                    '<span style="font-size:0.85em;color:#999;">(steps will appear here as the agent runs)</span></div>';
                return;
            }}

            var state = getState();
            if (!state.steps.length) {{
                steps.forEach(function(_, i) {{
                    state.steps.push({{ step_index: i, correctness: null }});
                }});
            }}

            container.innerHTML = '';
            steps.forEach(function(step, idx) {{
                _appendStepCard(container, step, idx);
            }});
            attachStepHandlers();
        }}

        /* ---- render a single step card ---- */
        function _buildStepCardHtml(step, idx) {{
            var stepText = typeof step === 'string'
                ? step
                : (step[CONFIG.step_text_key] || step.action_type || JSON.stringify(step));
            // Include the thought if available (VLM chain-of-thought)
            var thoughtHtml = '';
            if (step.thought) {{
                thoughtHtml = '<div class="traj-step-thought">' +
                    '<span class="traj-thought-label">Thought:</span> ' +
                    escapeHtml(step.thought) + '</div>';
            }}
            var corBtns = CORRECTNESS_BTNS_TEMPLATE.replace(/STEPIDX/g, idx);
            var sevRadios = SEVERITY_RADIOS_TEMPLATE.replace(/STEPIDX/g, idx);

            return '<div class="traj-step-card" data-step-index="' + idx + '">' +
                '<div class="traj-step-header">' +
                    '<span class="traj-step-number">Step ' + (idx + 1) + '</span>' +
                    '<span class="traj-step-status" id="' + SCHEMA + '-status-' + idx + '"></span>' +
                '</div>' +
                '<div class="traj-step-text">' + escapeHtml(stepText) + '</div>' +
                thoughtHtml +
                '<div class="traj-correctness-row">' + corBtns + '</div>' +
                '<div class="traj-error-details" id="' + SCHEMA + '-error-' + idx + '" style="display:none;">' +
                    '<div class="traj-field"><label>Error Type:</label>' +
                        '<select class="traj-error-type" data-step="' + idx + '">' + TYPE_OPTIONS_HTML + '</select>' +
                    '</div>' +
                    '<div class="traj-field"><label>Severity:</label>' +
                        '<div class="traj-severity-group">' + sevRadios + '</div>' +
                    '</div>' +
                    '<div class="traj-field"><label>Rationale:</label>' +
                        '<textarea class="traj-rationale" data-step="' + idx + '" rows="2" placeholder="Explain the error..."></textarea>' +
                    '</div>' +
                '</div>' +
            '</div>';
        }}

        function _appendStepCard(container, step, idx) {{
            var div = document.createElement('div');
            div.innerHTML = _buildStepCardHtml(step, idx);
            var card = div.firstElementChild;
            container.appendChild(card);
            _attachSingleCardHandlers(card, idx);
        }}

        /* ---- add a step dynamically (called by live agent SSE) ---- */
        function addStep(stepData) {{
            var container = document.getElementById(SCHEMA + '-steps');
            if (!container) return;

            // Clear the "waiting" message if present
            var waiting = container.querySelector('.traj-waiting-steps');
            if (waiting) waiting.remove();

            var state = getState();
            var idx = state.steps.length;
            state.steps.push({{ step_index: idx, correctness: null }});

            _appendStepCard(container, stepData, idx);
            saveState();
        }}

        /* ---- event handlers ---- */
        function _attachSingleCardHandlers(card, idx) {{
            card.querySelectorAll('.traj-correctness-btn').forEach(function(btn) {{
                btn.addEventListener('click', function() {{
                    var value = btn.getAttribute('data-value');
                    var state = getState();
                    if (state.steps[idx] && state.steps[idx].correctness === value) {{
                        state.steps[idx] = {{ step_index: idx, correctness: null }};
                    }} else {{
                        if (!state.steps[idx]) state.steps[idx] = {{ step_index: idx }};
                        state.steps[idx].correctness = value;
                    }}
                    card.querySelectorAll('.traj-correctness-btn').forEach(function(b) {{
                        b.classList.remove('selected');
                    }});
                    if (state.steps[idx].correctness === value) {{
                        btn.classList.add('selected');
                    }}
                    var errorDiv = document.getElementById(SCHEMA + '-error-' + idx);
                    if (errorDiv) {{
                        errorDiv.style.display = (value === 'correct' || !state.steps[idx].correctness) ? 'none' : 'block';
                    }}
                    updateStepStatus(idx);
                    saveState();
                }});
            }});

            card.querySelectorAll('.traj-error-type').forEach(function(sel) {{
                sel.addEventListener('change', function() {{
                    var state = getState();
                    if (!state.steps[idx]) return;
                    var parts = sel.value.split('::');
                    state.steps[idx].error_type = parts[0] || '';
                    state.steps[idx].error_subtype = parts[1] || '';
                    saveState();
                }});
            }});

            card.querySelectorAll('.traj-severity-group input[type="radio"]').forEach(function(radio) {{
                radio.addEventListener('change', function() {{
                    var state = getState();
                    if (!state.steps[idx]) return;
                    state.steps[idx].severity = radio.value;
                    updateScore();
                    saveState();
                }});
            }});

            card.querySelectorAll('.traj-rationale').forEach(function(ta) {{
                ta.addEventListener('input', function() {{
                    var state = getState();
                    if (!state.steps[idx]) return;
                    state.steps[idx].rationale = ta.value;
                    saveState();
                }});
            }});
        }}

        function attachStepHandlers() {{
            var container = document.getElementById(SCHEMA + '-steps');
            if (!container) return;
            container.querySelectorAll('.traj-step-card').forEach(function(card) {{
                var idx = parseInt(card.getAttribute('data-step-index'), 10);
                _attachSingleCardHandlers(card, idx);
            }});
        }}

        function updateStepStatus(idx) {{
            var statusEl = document.getElementById(SCHEMA + '-status-' + idx);
            if (!statusEl) return;
            var state = getState();
            var s = state.steps[idx];
            if (!s || !s.correctness) {{
                statusEl.textContent = '';
                statusEl.className = 'traj-step-status';
            }} else {{
                statusEl.textContent = s.correctness.replace('_', ' ');
                statusEl.className = 'traj-step-status traj-status-' + s.correctness;
            }}
        }}

        function updateScore() {{
            if (!CONFIG.show_score) return;
            var scoreEl = document.getElementById(SCHEMA + '-score-value');
            if (!scoreEl) return;
            var state = getState();
            var penalty = 0;
            state.steps.forEach(function(s) {{
                if (s.severity) {{
                    var sev = CONFIG.severities.find(function(sv) {{ return sv.name === s.severity; }});
                    if (sev) penalty += Math.abs(sev.weight);
                }}
            }});
            scoreEl.textContent = Math.max(0, CONFIG.max_score - penalty);
        }}

        /* ---- persistence ---- */
        function saveState() {{
            var state = getState();
            var score = CONFIG.max_score;
            state.steps.forEach(function(s) {{
                if (s.severity) {{
                    var sev = CONFIG.severities.find(function(sv) {{ return sv.name === s.severity; }});
                    if (sev) score -= Math.abs(sev.weight);
                }}
            }});
            score = Math.max(0, score);

            var data = JSON.stringify({{ steps: state.steps, score: score }});
            var input = document.getElementById(SCHEMA).querySelector('.trajectory-eval-data-input');
            if (input) {{
                input.value = data;
                input.setAttribute('data-modified', 'true');
                input.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
        }}

        function restoreFromHiddenInput() {{
            var input = document.getElementById(SCHEMA).querySelector('.trajectory-eval-data-input');
            if (!input) return false;
            var val = input.getAttribute('value') || input.value;
            if (!val) return false;
            try {{
                var data = JSON.parse(val);
                if (data && data.steps && data.steps.length) {{
                    var state = getState();
                    state.steps = data.steps;
                    return true;
                }}
            }} catch(e) {{}}
            return false;
        }}

        function restoreVisualState() {{
            var state = getState();
            var container = document.getElementById(SCHEMA + '-steps');
            if (!container) return;

            state.steps.forEach(function(s, idx) {{
                var card = container.querySelector('[data-step-index="' + idx + '"]');
                if (!card) return;

                // Restore correctness button
                if (s.correctness) {{
                    card.querySelectorAll('.traj-correctness-btn').forEach(function(btn) {{
                        if (btn.getAttribute('data-value') === s.correctness) {{
                            btn.classList.add('selected');
                        }}
                    }});
                    // Show error details if not correct
                    var errorDiv = document.getElementById(SCHEMA + '-error-' + idx);
                    if (errorDiv && s.correctness !== 'correct') {{
                        errorDiv.style.display = 'block';
                    }}
                }}

                // Restore error type
                if (s.error_type) {{
                    var typeVal = s.error_subtype ? s.error_type + '::' + s.error_subtype : s.error_type;
                    var sel = card.querySelector('.traj-error-type');
                    if (sel) sel.value = typeVal;
                }}

                // Restore severity
                if (s.severity) {{
                    var radio = card.querySelector('input[type="radio"][value="' + s.severity + '"]');
                    if (radio) radio.checked = true;
                }}

                // Restore rationale
                if (s.rationale) {{
                    var ta = card.querySelector('.traj-rationale');
                    if (ta) ta.value = s.rationale;
                }}

                updateStepStatus(idx);
            }});

            updateScore();
        }}

        function escapeHtml(str) {{
            var div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }}

        /* ---- initialization ---- */
        // CRITICAL: Check hidden input for server-restored value BEFORE
        // building default state (prevents IIFE overwrite bug).
        var hadServerData = restoreFromHiddenInput();

        // Build step cards — uses a MutationObserver to wait for instance data
        // to appear if it hasn't yet (async loading).
        function tryBuildCards() {{
            buildStepCards();
            if (hadServerData) {{
                restoreVisualState();
            }}
        }}

        if (document.readyState === 'complete') {{
            tryBuildCards();
        }} else {{
            document.addEventListener('DOMContentLoaded', tryBuildCards);
        }}

        // Expose for annotation.js restore pipeline
        window._trajState = _trajState;
        window._trajGetState = getState;
        window._trajBuildStepCards = buildStepCards;
        window._trajRestoreVisualState = restoreVisualState;
        window._trajSaveState = saveState;
        window._trajAddStep = addStep;

        // Listen for live agent step events so trajectory cards appear
        // as the agent runs (dispatched by live-agent-viewer.js SSE handler)
        document.addEventListener('live-agent-step', function(e) {{
            if (e.detail) addStep(e.detail);
        }});
    }})();
    </script>
    """

    logger.info(f"Generated trajectory eval layout for {schema_name}")
    return html, []
