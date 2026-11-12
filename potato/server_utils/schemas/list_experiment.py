"""``list_experiment``: see survey_experiments.py."""

from typing import Any, Dict, List, Tuple

from .identifier_utils import escape_html_content, safe_generate_layout
from .survey_experiment_common import _wrap


def generate_list_experiment_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List]:
    return safe_generate_layout(annotation_scheme, _list_internal)


def _list_internal(scheme: Dict[str, Any]) -> Tuple[str, List]:
    from .number import generate_number_layout
    items = [str(i) for i in scheme.get("items") or []]
    if not items:
        raise ValueError(f"list_experiment '{scheme['name']}' needs `items`")
    sensitive = str(scheme.get("sensitive_item") or "")
    if not sensitive:
        raise ValueError(f"list_experiment '{scheme['name']}' needs `sensitive_item`")
    treatment = scheme.get("treatment") or {}
    gate = f'{treatment.get("factor", "")}={treatment.get("level", "")}'
    position = int(scheme.get("sensitive_position", len(items)))
    position = max(0, min(position, len(items)))
    rows = [f"<li>{escape_html_content(t)}</li>" for t in items]
    # Removed from the page server-side for participants not in the treatment
    # condition (phase_flow.apply_condition_markup), so it is not in their HTML.
    rows.insert(position, f'<li data-condition-only="{escape_html_content(gate)}">'
                          f"{escape_html_content(sensitive)}</li>")
    listing = f'<ul class="survey-experiment-list">{"".join(rows)}</ul>'
    number = dict(scheme)
    number.update({"annotation_type": "number", "min": 0, "max": len(items) + 1, "step": 1,
                   "description": scheme.get("count_prompt") or "Number of statements:"})
    for key in ("items", "sensitive_item", "treatment", "sensitive_position", "count_prompt"):
        number.pop(key, None)
    html, keys = generate_number_layout(number)
    title = f'<p class="survey-experiment-title">{escape_html_content(scheme["description"])}</p>'
    note = ('<p class="survey-experiment-note">Give only the number. Do not say which '
            'ones.</p>')
    return _wrap(scheme["name"], "list", title + listing + note, html), keys
