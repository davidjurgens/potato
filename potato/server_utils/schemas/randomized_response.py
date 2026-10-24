"""``randomized_response``: see survey_experiments.py."""

from typing import Any, Dict, List, Tuple

from .identifier_utils import escape_html_content, safe_generate_layout
from .survey_experiment_common import CROSSWISE_LABELS, DEFAULT_RANDOMIZER, _wrap


def generate_randomized_response_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List]:
    return safe_generate_layout(annotation_scheme, _rr_internal)


def _rr_internal(scheme: Dict[str, Any]) -> Tuple[str, List]:
    from .radio import generate_radio_layout
    method = scheme.get("method", "forced_response")
    question = str(scheme.get("question") or scheme["description"])
    radio = dict(scheme)
    for key in ("method", "question", "randomizer", "p_truth", "p_yes", "p_no",
                "nonsensitive_statement", "nonsensitive_prevalence"):
        radio.pop(key, None)
    radio["annotation_type"] = "radio"
    if method == "crosswise":
        other = str(scheme.get("nonsensitive_statement") or "")
        before = (f'<p class="survey-experiment-title">{escape_html_content(scheme["description"])}</p>'
                  f'<ol class="survey-experiment-list"><li>{escape_html_content(question)}</li>'
                  f'<li>{escape_html_content(other)}</li></ol>')
        radio["labels"] = list(CROSSWISE_LABELS)
        radio["description"] = "Which is the case for you?"
    else:
        rule = scheme.get("randomizer") or DEFAULT_RANDOMIZER
        before = (f'<p class="survey-experiment-title">{escape_html_content(scheme["description"])}</p>'
                  f'<p class="survey-experiment-randomizer">{escape_html_content(rule)}</p>'
                  f'<p class="survey-experiment-question">{escape_html_content(question)}</p>')
        radio["labels"] = ["Yes", "No"]
        radio["description"] = "Your answer:"
    html, keys = generate_radio_layout(radio, horizontal=True)
    return _wrap(scheme["name"], "rr", before, html), keys
