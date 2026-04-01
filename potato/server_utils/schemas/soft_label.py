"""
Soft Label / Probability Distribution Layout

Generates a set of constrained sliders where annotators distribute probability
mass across labels. All sliders are constrained to sum to a fixed total (default 100).

Research basis:
- Fornaciari et al. (2021) "Beyond Black & White: Leveraging Annotator Disagreement
  via Soft-Label Multi-Task Learning" ACL
- Plank et al. (2014) "Linguistically Debatable or Just Plain Wrong?" ACL
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

# Defaults
DEFAULT_TOTAL = 100
DEFAULT_MIN_PER_LABEL = 0


def generate_soft_label_layout(annotation_scheme):
    """
    Generate HTML for a soft label / probability distribution interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - labels: List of label names (strings or dicts with 'name')
            - total: Sum constraint (default 100)
            - min_per_label: Minimum per label (default 0)
            - show_distribution_chart: Show bar chart (default true)

    Returns:
        tuple: (html_string, key_bindings)
    """
    return safe_generate_layout(annotation_scheme, _generate_soft_label_layout_internal)


def _generate_soft_label_layout_internal(annotation_scheme):
    schema_name = annotation_scheme["name"]
    safe_schema = escape_html_content(schema_name)
    description = annotation_scheme["description"]
    labels = annotation_scheme.get("labels", [])
    total = annotation_scheme.get("total", DEFAULT_TOTAL)
    min_per_label = annotation_scheme.get("min_per_label", DEFAULT_MIN_PER_LABEL)
    show_chart = annotation_scheme.get("show_distribution_chart", True)

    if not labels:
        raise ValueError(f"soft_label schema '{schema_name}' requires 'labels'")

    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)

    # Normalize labels
    label_names = []
    for lbl in labels:
        if isinstance(lbl, str):
            label_names.append(lbl)
        elif isinstance(lbl, dict) and "name" in lbl:
            label_names.append(lbl["name"])
        else:
            raise ValueError(f"Invalid label format: {lbl}")

    # Calculate initial equal distribution
    initial_value = total // len(label_names)
    remainder = total - (initial_value * len(label_names))

    html = f"""
    <form id="{safe_schema}" class="annotation-form soft_label shadcn-soft-label-container"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          data-annotation-type="soft_label"
          data-schema-name="{safe_schema}"
          data-soft-label-total="{total}"
          {layout_attrs}>
        {get_ai_wrapper()}
        <fieldset schema="{safe_schema}">
            <legend class="shadcn-soft-label-title">{escape_html_content(description)}</legend>
            <div class="soft-label-status">
                <span class="soft-label-allocated" id="soft-label-allocated-{safe_schema}">
                    Allocated: <strong>{total}</strong> / {total}
                </span>
                <span class="soft-label-remaining" id="soft-label-remaining-{safe_schema}">
                    Remaining: <strong>0</strong>
                </span>
            </div>
    """

    if show_chart:
        html += f'<div class="soft-label-chart" id="soft-label-chart-{safe_schema}">'
        for i, lbl in enumerate(label_names):
            safe_lbl = escape_html_content(lbl)
            html += f"""
                <div class="soft-label-chart-bar-wrapper">
                    <div class="soft-label-chart-bar" id="soft-label-bar-{safe_schema}-{i}"
                         style="width: 0%;" data-label="{safe_lbl}"></div>
                    <span class="soft-label-chart-label">{safe_lbl}</span>
                </div>
            """
        html += "</div>"

    html += '<div class="soft-label-sliders">'

    for i, lbl in enumerate(label_names):
        safe_lbl = escape_html_content(lbl)
        identifiers = generate_element_identifier(schema_name, lbl, "range")
        init_val = initial_value + (1 if i < remainder else 0)

        tooltip_html = ""
        if isinstance(labels[i], dict):
            tooltip_html = generate_tooltip_html(labels[i])

        html += f"""
            <div class="soft-label-slider-row" {tooltip_html}>
                <label class="soft-label-label" for="{identifiers['id']}">{safe_lbl}</label>
                <input type="range"
                       min="{min_per_label}"
                       max="{total}"
                       step="1"
                       value="{init_val}"
                       class="soft-label-slider annotation-input"
                       id="{identifiers['id']}"
                       name="{identifiers['name']}"
                       schema="{identifiers['schema']}"
                       label_name="{identifiers['label_name']}"
                       validation="{validation}"
                       data-soft-label-group="{safe_schema}">
                <span class="soft-label-value" id="soft-label-val-{identifiers['id']}">{init_val}</span>
            </div>
        """

    html += """
            </div>
        </fieldset>
    </form>
    """

    # Inline JS for sum constraint
    html += f"""
    <script>
    (function() {{
        const schema = "{safe_schema}";
        const total = {total};
        const minPerLabel = {min_per_label};
        const sliders = document.querySelectorAll('[data-soft-label-group="' + schema + '"]');

        function updateSoftLabel(changedSlider) {{
            const values = [];
            sliders.forEach(s => values.push(parseInt(s.value)));
            const currentSum = values.reduce((a, b) => a + b, 0);
            const diff = currentSum - total;

            if (diff !== 0) {{
                // Proportionally adjust other sliders
                const otherSliders = Array.from(sliders).filter(s => s !== changedSlider);
                const otherSum = otherSliders.reduce((acc, s) => acc + parseInt(s.value), 0);

                if (otherSum > 0) {{
                    let remaining = diff;
                    for (const s of otherSliders) {{
                        const oldVal = parseInt(s.value);
                        const proportion = oldVal / otherSum;
                        let adjustment = Math.round(proportion * diff);
                        const newVal = Math.max(minPerLabel, oldVal - adjustment);
                        const actualAdj = oldVal - newVal;
                        s.value = newVal;
                        remaining -= actualAdj;
                    }}
                    // Fix rounding errors
                    if (remaining !== 0) {{
                        for (const s of otherSliders) {{
                            const oldVal = parseInt(s.value);
                            const newVal = Math.max(minPerLabel, oldVal - remaining);
                            remaining -= (oldVal - newVal);
                            s.value = newVal;
                            if (remaining === 0) break;
                        }}
                    }}
                }} else if (diff > 0) {{
                    changedSlider.value = parseInt(changedSlider.value) - diff;
                }}
            }}

            // Update displays
            sliders.forEach(s => {{
                const valEl = document.getElementById('soft-label-val-' + s.id);
                if (valEl) valEl.textContent = s.value;
            }});

            // Update chart
            sliders.forEach((s, idx) => {{
                const bar = document.getElementById('soft-label-bar-' + schema + '-' + idx);
                if (bar) {{
                    const pct = (parseInt(s.value) / total) * 100;
                    bar.style.width = pct + '%';
                }}
            }});

            // Update allocated/remaining indicators
            const newSum = Array.from(sliders).reduce((acc, s) => acc + parseInt(s.value), 0);
            const allocEl = document.getElementById('soft-label-allocated-' + schema);
            const remEl = document.getElementById('soft-label-remaining-' + schema);
            if (allocEl) {{
                allocEl.innerHTML = 'Allocated: <strong>' + newSum + '</strong> / ' + total;
            }}
            if (remEl) {{
                const remaining = total - newSum;
                remEl.innerHTML = 'Remaining: <strong>' + remaining + '</strong>';
            }}
        }}

        sliders.forEach(s => {{
            s.addEventListener('input', function() {{
                updateSoftLabel(this);
            }});
        }});

        // Initialize
        if (sliders.length > 0) updateSoftLabel(sliders[0]);
    }})();
    </script>
    """

    key_bindings = []
    logger.info(f"Generated soft_label layout for {schema_name} with {len(label_names)} labels")
    return html, key_bindings
