"""
Constant Sum / Points Allocation Layout

Generates number inputs (or sliders) constrained to sum to a fixed total.
Forces annotators to make relative comparisons between categories.

Research basis:
- Louviere et al. (2015) "Best-Worst Scaling: Theory, Methods and Applications"
  Cambridge University Press
- Thurstone (1927) paired-comparison law of comparative judgment
"""

import logging

from potato.ai.ai_help_wrapper import get_ai_wrapper
from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_validation_attribute,
    escape_html_content,
    generate_layout_attributes,
    generate_tooltip_html,
)

logger = logging.getLogger(__name__)

DEFAULT_TOTAL_POINTS = 100
DEFAULT_MIN_PER_ITEM = 0
DEFAULT_INPUT_TYPE = "number"


def generate_constant_sum_layout(annotation_scheme):
    """
    Generate HTML for a constant sum / points allocation interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - labels: List of category names
            - total_points: Sum budget (default 100)
            - min_per_item: Minimum per item (default 0)
            - input_type: "number" or "slider" (default "number")

    Returns:
        tuple: (html_string, key_bindings)
    """
    return safe_generate_layout(annotation_scheme, _generate_constant_sum_layout_internal)


def _generate_constant_sum_layout_internal(annotation_scheme):
    schema_name = annotation_scheme["name"]
    safe_schema = escape_html_content(schema_name)
    description = annotation_scheme["description"]
    labels = annotation_scheme.get("labels", [])
    total_points = annotation_scheme.get("total_points", DEFAULT_TOTAL_POINTS)
    min_per_item = annotation_scheme.get("min_per_item", DEFAULT_MIN_PER_ITEM)
    input_type = annotation_scheme.get("input_type", DEFAULT_INPUT_TYPE)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)

    if not labels:
        raise ValueError(f"constant_sum schema '{schema_name}' requires 'labels'")

    # Normalize labels
    label_names = []
    for lbl in labels:
        if isinstance(lbl, str):
            label_names.append(lbl)
        elif isinstance(lbl, dict) and "name" in lbl:
            label_names.append(lbl["name"])
        else:
            raise ValueError(f"Invalid label format: {lbl}")

    html = f"""
    <form id="{safe_schema}" class="annotation-form constant_sum shadcn-constant-sum-container"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          data-annotation-type="constant_sum"
          data-schema-name="{safe_schema}"
          data-constant-sum-total="{total_points}"
          {layout_attrs}>
        {get_ai_wrapper()}
        <fieldset schema="{safe_schema}">
            <legend class="shadcn-constant-sum-title">{escape_html_content(description)}</legend>
            <div class="constant-sum-status">
                <span class="constant-sum-allocated" id="constant-sum-allocated-{safe_schema}">
                    Allocated: <strong>0</strong> / {total_points}
                </span>
                <span class="constant-sum-remaining" id="constant-sum-remaining-{safe_schema}">
                    Remaining: <strong>{total_points}</strong>
                </span>
            </div>
            <div class="constant-sum-items">
    """

    for i, lbl in enumerate(label_names):
        safe_lbl = escape_html_content(lbl)
        identifiers = generate_element_identifier(schema_name, lbl, "number")

        tooltip_html = ""
        if isinstance(labels[i], dict):
            tooltip_html = generate_tooltip_html(labels[i])

        if input_type == "slider":
            html += f"""
                <div class="constant-sum-item" {tooltip_html}>
                    <label class="constant-sum-label" for="{identifiers['id']}">{safe_lbl}</label>
                    <input type="range"
                           min="{min_per_item}"
                           max="{total_points}"
                           step="1"
                           value="{min_per_item}"
                           class="constant-sum-slider annotation-input"
                           id="{identifiers['id']}"
                           name="{identifiers['name']}"
                           schema="{identifiers['schema']}"
                           label_name="{identifiers['label_name']}"
                           validation="{validation}"
                           data-constant-sum-group="{safe_schema}">
                    <span class="constant-sum-value" id="constant-sum-val-{identifiers['id']}">{min_per_item}</span>
                </div>
            """
        else:
            html += f"""
                <div class="constant-sum-item" {tooltip_html}>
                    <label class="constant-sum-label" for="{identifiers['id']}">{safe_lbl}</label>
                    <input type="number"
                           min="{min_per_item}"
                           max="{total_points}"
                           step="1"
                           value=""
                           class="constant-sum-number annotation-input"
                           id="{identifiers['id']}"
                           name="{identifiers['name']}"
                           schema="{identifiers['schema']}"
                           label_name="{identifiers['label_name']}"
                           validation="{validation}"
                           data-constant-sum-group="{safe_schema}"
                           placeholder="0">
                </div>
            """

    html += f"""
            </div>
        </fieldset>
    </form>
    <script>
    (function() {{
        const schema = "{safe_schema}";
        const total = {total_points};
        const minVal = {min_per_item};
        const inputs = document.querySelectorAll('[data-constant-sum-group="' + schema + '"]');

        function getSum(exclude) {{
            let sum = 0;
            inputs.forEach(inp => {{
                if (inp !== exclude) sum += (parseInt(inp.value) || 0);
            }});
            return sum;
        }}

        function clampInput(inp) {{
            let val = parseInt(inp.value);
            if (isNaN(val) || val < minVal) {{
                val = minVal;
                inp.value = val || '';
            }}
            // Cap so total is not exceeded
            const othersSum = getSum(inp);
            const maxAllowed = total - othersSum;
            if (val > maxAllowed) {{
                val = Math.max(minVal, maxAllowed);
                inp.value = val;
            }}
            return val;
        }}

        function updateConstantSum() {{
            let sum = 0;
            inputs.forEach(inp => {{
                const val = parseInt(inp.value) || 0;
                sum += val;
                const valEl = document.getElementById('constant-sum-val-' + inp.id);
                if (valEl) valEl.textContent = val;
            }});

            const allocEl = document.getElementById('constant-sum-allocated-' + schema);
            const remEl = document.getElementById('constant-sum-remaining-' + schema);
            const remaining = total - sum;

            if (allocEl) {{
                allocEl.innerHTML = 'Allocated: <strong>' + sum + '</strong> / ' + total;
                allocEl.className = 'constant-sum-allocated ' +
                    (sum === total ? 'valid' : sum > total ? 'over' : '');
            }}
            if (remEl) {{
                remEl.innerHTML = 'Remaining: <strong>' + remaining + '</strong>';
                remEl.className = 'constant-sum-remaining ' +
                    (remaining === 0 ? 'valid' : remaining < 0 ? 'over' : '');
            }}
        }}

        inputs.forEach(inp => {{
            inp.addEventListener('input', function() {{
                clampInput(this);
                updateConstantSum();
            }});
            // Also clamp on blur for pasted/typed values
            inp.addEventListener('blur', function() {{
                clampInput(this);
                updateConstantSum();
            }});
        }});

        updateConstantSum();
    }})();
    </script>
    """

    key_bindings = []
    logger.info(f"Generated constant_sum layout for {schema_name} with {len(label_names)} categories")
    return html, key_bindings
