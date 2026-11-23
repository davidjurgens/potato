"""
Answers a participant gave on earlier SurveyFlow pages, read back for later pages.

Two consumers share one reader:

* Survey pages ship every earlier answer to the browser as
  ``window.priorPhaseAnswersRaw`` so cross-page ``display_logic`` can use it.
* Annotation pages show the answers the config's ``prior_answers`` block names,
  rendered on the server. A study that asks "In your own words, how would you
  define X?" in a prestudy can then show each annotator their own definition
  next to every item.

Answers are participant input. Everything that reaches a page goes through
``markupsafe.escape`` here, so the template may emit it with ``| safe``.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from markupsafe import Markup, escape

#: Keys one ``prior_answers`` entry accepts. Mirrors KNOWN_CONFIG_KEYS.
PRIOR_ANSWER_KEYS = frozenset({"schema", "title", "collapsible", "collapsed_default"})

_BOOL_KEYS = ("collapsible", "collapsed_default")


def collect_prior_answers(user_state, exclude: Optional[Tuple[Any, Any]] = None
                          ) -> Dict[str, Dict[str, Any]]:
    """``{schema: {label_name: value}}`` for every SurveyFlow answer the
    participant has stored.

    ``exclude`` is a ``(phase, page)`` pair to leave out: a survey page passes
    its own, because its answers reach the browser through the page's own
    pipeline and must win over the stored copy.
    """
    raw: Dict[str, Dict[str, Any]] = {}
    pages_by_phase = getattr(user_state, "phase_to_page_to_label_to_value", None) or {}
    for phase, pages in pages_by_phase.items():
        for page, labels in pages.items():
            if exclude is not None and (phase, page) == exclude:
                continue
            for label_obj, value in labels.items():
                try:
                    schema = label_obj.get_schema()
                    label = label_obj.get_name()
                except AttributeError:
                    continue
                raw.setdefault(schema, {})[label] = value
    return raw


def surveyflow_scheme_index(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """``{name: scheme}`` for every question on a SurveyFlow phase page."""
    return {s["name"]: s for s in (config.get("_surveyflow_schemes") or [])
            if isinstance(s, dict) and s.get("name")}


def _likert_text(point: str, scheme: Dict[str, Any]) -> str:
    """A likert point with its place on the scale: "4 of 7 (1 = Disagree, 7 = Agree)".

    A bare "4" does not say how big the scale was or which end is which. A
    likert with its own ``labels`` list stores the label name, which already
    reads well, so only the numbered scale gets the context.
    """
    from potato.server_utils.schemas.identifier_utils import bad_text_label_content

    if point == "bad_text":
        return bad_text_label_content(scheme) or point
    size = scheme.get("size")
    if scheme.get("labels") or not isinstance(size, int) or not point.isdigit():
        return point
    text = f"{point} of {size}"
    ends = [f"{n} = {scheme[key]}" for n, key in ((1, "min_label"), (size, "max_label"))
            if scheme.get(key)]
    return f"{text} ({', '.join(ends)})" if ends else text


def _answer_lines(labels: Dict[str, Any], scheme: Dict[str, Any]) -> List[str]:
    """The answer as one or more lines of display text, or ``[]`` when empty."""
    from potato.server_utils.answer_collapse import collapse_entries
    from potato.server_utils.annotation_keys import SCALAR_ANSWER_TYPES

    annotation_type = scheme.get("annotation_type")
    entries = list(labels.items())

    # A text question with several boxes stores one value per box. The collapse
    # keeps only the last one, which would drop the others from view.
    if annotation_type in SCALAR_ANSWER_TYPES:
        filled = [(ln, v) for ln, v in entries
                  if v not in (None, "") and not isinstance(v, bool)]
        if len(filled) > 1:
            return [f"{ln}: {v}" for ln, v in filled]

    value, _winner, _method = collapse_entries(
        entries, schema=scheme.get("name", ""), annotation_type=annotation_type)
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        lines = [str(v) for v in value if v not in (None, "")]
    elif annotation_type == "likert":
        lines = [_likert_text(str(value), scheme)]
    else:
        lines = [str(value)]

    # "Other (please specify)" text rides along with a radio/multiselect choice.
    other = labels.get("free_response")
    if other not in (None, "", False) and str(other) not in lines:
        lines.append(str(other))
    return lines


def render_prior_answer_blocks(config: Dict[str, Any], user_state
                               ) -> List[Dict[str, Any]]:
    """The ``prior_answers`` blocks for one participant, ready for the template.

    Each block is ``{schema, title, answer_html, lines, collapsible, open}``. A block
    whose question the participant left empty is omitted, so an optional
    question does not leave an empty box on every page.
    """
    entries = config.get("prior_answers") or []
    if not entries or user_state is None:
        return []
    schemes = surveyflow_scheme_index(config)
    answers = collect_prior_answers(user_state)

    blocks = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("schema")
        scheme = schemes.get(name) or {"name": name}
        lines = _answer_lines(answers.get(name) or {}, scheme)
        if not lines:
            continue
        title = entry.get("title") or scheme.get("description") or name
        collapsible = entry.get("collapsible", True)
        blocks.append({
            "schema": name,
            "title": str(title),
            "answer_html": Markup("<br>").join(escape(line) for line in lines),
            # Plain text for clients that build the box themselves (Pocket);
            # they set it as textContent, so it is not escaped here.
            "lines": list(lines),
            "collapsible": bool(collapsible),
            "open": not entry.get("collapsed_default", True),
        })
    return blocks


def validate_prior_answers_block(config_data: Dict[str, Any]) -> None:
    """Shape check for ``prior_answers``. Names are checked at boot, once the
    phase files are loaded (see :func:`validate_prior_answer_references`)."""
    from potato.server_utils.config_module import ConfigValidationError

    entries = config_data.get("prior_answers")
    if entries is None:
        return
    if not isinstance(entries, list):
        raise ConfigValidationError(
            "prior_answers must be a list of entries, each with a 'schema' key")
    for i, entry in enumerate(entries):
        where = f"prior_answers[{i}]"
        if not isinstance(entry, dict):
            raise ConfigValidationError(f"{where} must be a mapping with a 'schema' key")
        unknown = set(entry) - PRIOR_ANSWER_KEYS
        if unknown:
            raise ConfigValidationError(
                f"{where} has unknown key(s) {', '.join(sorted(map(str, unknown)))}; "
                f"allowed: {', '.join(sorted(PRIOR_ANSWER_KEYS))}")
        schema = entry.get("schema")
        if not isinstance(schema, str) or not schema.strip():
            raise ConfigValidationError(f"{where}.schema must be a question name")
        if "title" in entry and not isinstance(entry["title"], str):
            raise ConfigValidationError(f"{where}.title must be text")
        for key in _BOOL_KEYS:
            if key in entry and not isinstance(entry[key], bool):
                raise ConfigValidationError(f"{where}.{key} must be true or false")


def validate_prior_answer_references(config: Dict[str, Any],
                                     surveyflow_schemes: Iterable[Dict[str, Any]]) -> None:
    """Every ``prior_answers`` schema must be a question on a SurveyFlow page."""
    from potato.server_utils.config_module import ConfigValidationError

    entries = config.get("prior_answers") or []
    if not entries:
        return
    known = {s.get("name") for s in surveyflow_schemes if isinstance(s, dict)}
    annotation_names = {s.get("name") for s in (config.get("annotation_schemes") or [])
                        if isinstance(s, dict)}
    for i, entry in enumerate(entries):
        name = entry.get("schema") if isinstance(entry, dict) else None
        if name in known and name not in annotation_names:
            continue
        if name in annotation_names:
            raise ConfigValidationError(
                f"prior_answers[{i}].schema '{name}' is an annotation scheme. "
                "prior_answers shows answers from survey pages (consent, prestudy, "
                "poststudy and similar phases) only")
        listed = ", ".join(sorted(n for n in known if n)) or "none"
        raise ConfigValidationError(
            f"prior_answers[{i}].schema '{name}' is not a question on any survey "
            f"page. Survey questions: {listed}")
