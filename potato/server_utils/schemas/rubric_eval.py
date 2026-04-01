"""
Multi-Criteria Rubric Evaluation Layout

Rate items on multiple criteria simultaneously in a structured grid.
THE missing schema for LLM evaluation — enables MT-Bench-style multi-dimensional scoring.

Research: Zheng et al. (2023) "Judging LLM-as-a-judge with MT-Bench"; Ke et al. (2024) "CritiqueLLM".
"""

import logging

from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    generate_validation_attribute,
    escape_html_content,
    generate_layout_attributes
)


logger = logging.getLogger(__name__)

DEFAULT_SCALE_POINTS = 5
DEFAULT_SCALE_LABELS = ["Poor", "Below Average", "Average", "Good", "Excellent"]


def generate_rubric_eval_layout(annotation_scheme):
    """
    Generate HTML for a Multi-Criteria Rubric Evaluation interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - scale_points: Number of scale points (default 5)
            - scale_labels: Labels for each scale point
            - criteria: List of {name, description} dicts
            - show_overall: Whether to include an "Overall" row

    Returns:
        tuple: (html_string, key_bindings)
    """
    return safe_generate_layout(annotation_scheme, _generate_rubric_eval_layout_internal)


def _generate_rubric_eval_layout_internal(annotation_scheme):
    schema_name = annotation_scheme['name']
    description = annotation_scheme['description']
    scale_points = annotation_scheme.get('scale_points', DEFAULT_SCALE_POINTS)
    scale_labels = annotation_scheme.get('scale_labels', DEFAULT_SCALE_LABELS[:scale_points])
    criteria = annotation_scheme.get('criteria', [])
    show_overall = annotation_scheme.get('show_overall', False)

    if not criteria:
        raise ValueError(f"rubric_eval schema '{schema_name}' requires at least one criterion in 'criteria'")

    # Pad or trim scale_labels to match scale_points
    while len(scale_labels) < scale_points:
        scale_labels.append(f"{len(scale_labels) + 1}")
    scale_labels = scale_labels[:scale_points]

    layout_attrs = generate_layout_attributes(annotation_scheme)
    validation = generate_validation_attribute(annotation_scheme)

    # Build header row
    header_cells = '<th class="rubric-criterion-header">Criterion</th>'
    for i, label in enumerate(scale_labels):
        header_cells += f'<th class="rubric-scale-header">{escape_html_content(label)}<br><span class="rubric-scale-number">{i + 1}</span></th>'

    # Build criterion rows
    rows_html = ""
    all_criteria = list(criteria)
    if show_overall:
        all_criteria.append({"name": "overall", "description": "Overall quality"})

    for criterion in all_criteria:
        crit_name = criterion['name']
        crit_desc = criterion.get('description', '')
        crit_label = f"{schema_name}:{crit_name}"

        identifiers = generate_element_identifier(schema_name, crit_name, "radio")
        # Override name: each criterion row needs its own radio group
        # (generate_element_identifier uses schema-only name for radios,
        # but rubric_eval needs per-criterion groups)
        row_group_name = f"{escape_html_content(schema_name)}:::{escape_html_content(crit_name)}"

        cells = f"""
            <td class="rubric-criterion-cell">
                <div class="rubric-criterion-name">{escape_html_content(crit_name)}</div>
                {f'<div class="rubric-criterion-desc">{escape_html_content(crit_desc)}</div>' if crit_desc else ''}
            </td>
        """

        for i in range(scale_points):
            value = str(i + 1)
            radio_id = f"{identifiers['id']}-{value}"
            cells += f"""
                <td class="rubric-radio-cell">
                    <input type="radio"
                           class="rubric-radio annotation-input"
                           id="{radio_id}"
                           name="{row_group_name}"
                           schema="{identifiers['schema']}"
                           label_name="{identifiers['label_name']}"
                           validation="{validation}"
                           value="{value}"
                           onclick="this.blur();">
                </td>
            """

        is_overall_class = " rubric-overall-row" if crit_name == "overall" else ""
        rows_html += f'<tr class="rubric-criterion-row{is_overall_class}">{cells}</tr>'

    html = f"""
    <form id="{escape_html_content(schema_name)}" class="annotation-form shadcn-rubric-eval-container"
          action="/action_page.php"
          data-annotation-id="{escape_html_content(str(annotation_scheme.get('annotation_id', '')))}"
          data-annotation-type="rubric_eval"
          data-schema-name="{escape_html_content(schema_name)}"
          {layout_attrs}>
        <fieldset schema_name="{escape_html_content(schema_name)}">
            <legend class="shadcn-rubric-eval-title">{escape_html_content(description)}</legend>
            <div class="rubric-table-wrapper">
                <table class="rubric-table">
                    <thead>
                        <tr>{header_cells}</tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
        </fieldset>
    </form>
    """

    logger.info(f"Generated rubric eval layout for {schema_name} with {len(criteria)} criteria")
    return html, []
