"""Shared pieces of the sensitive-question designs (list_experiment.py,
randomized_response.py)."""


from .identifier_utils import escape_html_content

#: The default forced-response rule and its probabilities. Birth months are
#: close to uniform, so Jan-Feb and Mar-Apr each come up about 1/6 of the time.
DEFAULT_RANDOMIZER = (
    "Think of the month your mother was born in, and do not tell anyone. If it "
    "is January or February, answer Yes. If it is March or April, answer No. "
    "Otherwise, answer the question truthfully.")
DEFAULT_P = {"p_truth": 2 / 3, "p_yes": 1 / 6, "p_no": 1 / 6}

CROSSWISE_LABELS = ["Both statements are true, or neither is", "Exactly one statement is true"]


def _wrap(name: str, kind: str, before: str, inner: str) -> str:
    return (f'<div class="survey-experiment survey-experiment-{kind}" '
            f'data-survey-experiment="{escape_html_content(kind)}" '
            f'data-schema-name="{escape_html_content(name)}">{before}{inner}</div>')


