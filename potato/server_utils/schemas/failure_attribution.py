"""
Failure Attribution Schema (multi-agent).

Captures *which agent* caused a multi-agent system's failure, *which step* was the
decisive error, and *why* — the (agent, step, reason) triple the failure-attribution
literature needs (Zhang et al., "Which Agent Causes Task Failures and When?", ICML
2025; the Who&When dataset). The agent dropdown and step picker are populated from
the trace's own turns at render time, so the annotator chooses from what actually
happened.

Stored as a hidden-input JSON: ``{"responsible_agent", "decisive_step", "reason"}``.
Follows the persistence contract: the IIFE seeds itself from the hidden input's
server-restored value BEFORE rendering, so navigate-away/back restores correctly.
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


def generate_failure_attribution_layout(
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
    # Optional static agent list; otherwise agents are derived from the trace turns.
    static_agents = annotation_scheme.get("agents", [])

    esc_schema = escape_html_content(schema_name)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")

    config_json = json.dumps({
        "steps_key": steps_key, "agent_key": agent_key, "agents": static_agents,
    })

    html = f"""
    <form id="{esc_schema}" class="annotation-form failure-attribution-container"
          action="javascript:void(0)"
          data-annotation-type="failure_attribution"
          data-schema-name="{esc_schema}"
          {layout_attrs}>
        <fieldset schema="{esc_schema}">
            <legend class="fa-title">{escape_html_content(description)}</legend>

            <div class="fa-field">
                <label for="{esc_schema}-agent">Responsible agent</label>
                <select id="{esc_schema}-agent" class="fa-agent"></select>
            </div>
            <div class="fa-field">
                <label for="{esc_schema}-step">Decisive error step</label>
                <select id="{esc_schema}-step" class="fa-step"></select>
            </div>
            <div class="fa-field">
                <label for="{esc_schema}-reason">Why (which decision/handoff went wrong)</label>
                <textarea id="{esc_schema}-reason" class="fa-reason" rows="2"
                          placeholder="Briefly explain the failure"></textarea>
            </div>

            <input type="hidden" class="annotation-input failure-attribution-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>

    <script>
    (function() {{
        var SCHEMA = '{esc_schema}';
        var CONFIG = {config_json};

        function instanceData() {{
            try {{
                var el = document.querySelector('[data-instance-json]');
                if (el) return JSON.parse(el.getAttribute('data-instance-json'));
            }} catch(e) {{}}
            var t = document.getElementById('text-content') || document.getElementById('instance-text');
            if (t) {{ try {{ return JSON.parse(t.textContent || t.innerText); }} catch(e2) {{}} }}
            return {{}};
        }}

        function getSteps() {{
            var d = instanceData();
            var s = d[CONFIG.steps_key];
            return Array.isArray(s) ? s : [];
        }}

        function agentOf(step, idx) {{
            if (step && typeof step === 'object') return step[CONFIG.agent_key] || step.speaker || step.role || ('step ' + (idx+1));
            return 'step ' + (idx+1);
        }}

        function uniqueAgents(steps) {{
            if (CONFIG.agents && CONFIG.agents.length) return CONFIG.agents.slice();
            var seen = [], out = [];
            steps.forEach(function(s, i) {{
                var a = agentOf(s, i);
                if (seen.indexOf(a) < 0) {{ seen.push(a); out.push(a); }}
            }});
            return out;
        }}

        function hidden() {{ return document.getElementById(SCHEMA).querySelector('.failure-attribution-input'); }}

        function build() {{
            var steps = getSteps();
            var agentSel = document.getElementById(SCHEMA + '-agent');
            var stepSel = document.getElementById(SCHEMA + '-step');
            if (!agentSel || !stepSel) return;

            agentSel.innerHTML = '<option value="">— select —</option>' +
                uniqueAgents(steps).map(function(a) {{
                    return '<option value="' + esc(a) + '">' + esc(a) + '</option>'; }}).join('');
            stepSel.innerHTML = '<option value="">— select —</option>' +
                steps.map(function(s, i) {{
                    var label = (i+1) + '. [' + esc(agentOf(s, i)) + '] ' +
                        esc(String(stepText(s)).slice(0, 60));
                    return '<option value="' + i + '">' + label + '</option>'; }}).join('');

            // Restore from the server-populated hidden input BEFORE wiring change events.
            var existing = {{}};
            var h = hidden();
            if (h && h.value) {{ try {{ existing = JSON.parse(h.value) || {{}}; }} catch(e) {{}} }}
            if (existing.responsible_agent) agentSel.value = existing.responsible_agent;
            if (existing.decisive_step !== undefined && existing.decisive_step !== null)
                stepSel.value = String(existing.decisive_step);
            var reason = document.getElementById(SCHEMA + '-reason');
            if (reason && existing.reason) reason.value = existing.reason;

            [agentSel, stepSel, reason].forEach(function(el) {{
                if (el && !el.getAttribute('data-fa-bound')) {{
                    el.setAttribute('data-fa-bound', '1');
                    el.addEventListener('change', save);
                    el.addEventListener('input', save);
                }}
            }});
        }}

        function stepText(s) {{
            if (s && typeof s === 'object') return s.content || s.text || s.action || s.reasoning || '';
            return s == null ? '' : s;
        }}

        function save() {{
            var agentSel = document.getElementById(SCHEMA + '-agent');
            var stepSel = document.getElementById(SCHEMA + '-step');
            var reason = document.getElementById(SCHEMA + '-reason');
            var data = {{
                responsible_agent: agentSel ? agentSel.value : '',
                decisive_step: (stepSel && stepSel.value !== '') ? parseInt(stepSel.value, 10) : null,
                reason: reason ? reason.value : ''
            }};
            var h = hidden();
            if (h) {{
                h.value = (data.responsible_agent || data.decisive_step !== null || data.reason)
                    ? JSON.stringify(data) : '';
                h.setAttribute('data-modified', 'true');
                h.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
        }}

        function esc(t) {{ var d = document.createElement('div'); d.textContent = t; return d.innerHTML; }}

        if (document.readyState === 'loading')
            document.addEventListener('DOMContentLoaded', build);
        else build();
        document.addEventListener('instanceChanged', build);
    }})();
    </script>

    <style>
    .failure-attribution-container {{ font-family: inherit; }}
    .fa-title {{ font-weight: 600; font-size: 1em; margin-bottom: 6px; }}
    .fa-field {{ margin-bottom: 10px; display: flex; flex-direction: column; gap: 3px; }}
    .fa-field label {{ font-size: 0.85em; font-weight: 600; color: var(--muted-foreground, #71717a); }}
    .fa-agent, .fa-step, .fa-reason {{
        padding: 6px 10px; border: 1px solid var(--border, #e4e4e7);
        border-radius: var(--radius, 0.5rem); background: var(--card, #fff);
        font-size: 0.9em; font-family: inherit; width: 100%; box-sizing: border-box;
    }}
    .fa-agent:focus-visible, .fa-step:focus-visible, .fa-reason:focus-visible {{
        outline: 2px solid var(--ring, #6e56cf); outline-offset: 1px;
    }}
    .fa-reason {{ resize: vertical; }}
    </style>
    """
    logger.info(f"Successfully generated failure_attribution layout for {schema_name}")
    return html, []
