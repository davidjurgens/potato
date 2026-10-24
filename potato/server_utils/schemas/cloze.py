"""
Cloze (fill-in-the-blank) Layout

A passage with blanks the participant types into:

.. code-block:: yaml

    - annotation_type: cloze
      name: cloze_1
      description: Fill in the missing words.
      text: "The [[cat|kitten]] sat on the [[mat]]."
      scoring: case_insensitive     # exact | case_insensitive | normalized
      input_width: 10               # width of each blank, in characters

Each ``[[...]]`` is one blank. The text inside is the answer key, with ``|``
between accepted answers; ``[[]]`` is a blank with no key. The key is removed
before the passage is rendered and is used only to score the export, so it
never reaches the browser.

Item-driven passages: each item carries its own passage and key.

.. code-block:: yaml

    - annotation_type: cloze
      name: ctest
      description: Complete the words.
      source_field: passage          # item field; blanks written as [[]]
      answer_field: answers          # item field; one entry per blank, str or list

The answer field is removed from everything the page receives. Text inside a
``[[...]]`` in an item passage is ignored, so a key typed into the passage by
mistake is never shown either -- the blank renders empty.

Each blank is an ordinary text input named ``<schema>:::blank_<i>``, so it
saves, restores and validates like any text field.
"""

import logging
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

from .identifier_utils import (
    escape_html_content,
    generate_element_identifier,
    generate_layout_attributes,
    generate_validation_attribute,
    safe_generate_layout,
)

logger = logging.getLogger(__name__)

BLANK = re.compile(r"\[\[(.*?)\]\]", re.S)
SCORING_MODES = ("exact", "case_insensitive", "normalized")


def parse_passage(text: str) -> Tuple[List[object], List[List[str]]]:
    """Split a passage into text pieces and blank indices, plus the answer key.

    Returns ``(segments, answers)``: ``segments`` alternates strings and ints
    (the blank's index); ``answers[i]`` is the list of accepted answers for
    blank ``i`` (empty when the blank has no key).
    """
    segments: List[object] = []
    answers: List[List[str]] = []
    pos = 0
    for m in BLANK.finditer(text or ""):
        if m.start() > pos:
            segments.append(text[pos:m.start()])
        key = [a.strip() for a in m.group(1).split("|") if a.strip()]
        segments.append(len(answers))
        answers.append(key)
        pos = m.end()
    if pos < len(text or ""):
        segments.append(text[pos:])
    return segments, answers


def public_text(text: str) -> str:
    """The passage with every answer key removed (``[[cat]]`` -> ``[[]]``),
    for anything that sends the scheme to a participant."""
    return BLANK.sub("[[]]", text or "")


def blank_label(index: int) -> str:
    return f"blank_{index + 1}"


def _normalize(value: str, mode: str) -> str:
    value = (value or "").strip()
    if mode == "exact":
        return value
    value = value.casefold()
    if mode == "normalized":
        value = unicodedata.normalize("NFKD", value)
        value = "".join(c for c in value if not unicodedata.combining(c))
        value = re.sub(r"[^\w\s]", "", value)
        value = re.sub(r"\s+", " ", value).strip()
    return value


def item_answers(scheme: dict, item_data: Optional[dict]) -> List[List[str]]:
    """The key for an item-driven passage, one list of accepted answers per blank."""
    raw = (item_data or {}).get(scheme.get("answer_field") or "") if item_data else None
    if isinstance(raw, str):
        # One blank's key ("cat|kitten"), the common case for one-blank items.
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out = []
    for entry in raw:
        if isinstance(entry, list):
            out.append([str(a).strip() for a in entry if str(a).strip()])
        elif entry is None:
            out.append([])
        else:
            out.append([a.strip() for a in str(entry).split("|") if a.strip()])
    return out


def answer_fields(config: dict) -> List[str]:
    """Item fields that hold cloze answer keys; never sent to the browser."""
    fields = []
    for scheme in (config or {}).get("annotation_schemes") or []:
        if isinstance(scheme, dict) and scheme.get("annotation_type") == "cloze" \
                and scheme.get("answer_field"):
            fields.append(str(scheme["answer_field"]))
    # A listening test's files and conditions (the page plays opaque slots).
    from potato.listening.blind import private_item_fields as listening_fields
    fields.extend(f for f in listening_fields(config) if f not in fields)
    # A LexTALE-style vocabulary test's word/nonword key.
    from potato.lextale import private_item_fields as lextale_fields
    fields.extend(lextale_fields(config))
    # Outcomes and pre-drawn prices that settle incentive payments.
    from potato.incentives import private_item_fields
    fields.extend(private_item_fields(config))
    return fields


def source_fields(config: dict) -> List[str]:
    return [str(s["source_field"]) for s in (config or {}).get("annotation_schemes") or []
            if isinstance(s, dict) and s.get("annotation_type") == "cloze" and s.get("source_field")]


def strip_answer_fields(config: dict, record):
    """``record`` without cloze answer keys: the answer fields are dropped, and
    any text typed inside ``[[...]]`` in a passage field is blanked."""
    fields = answer_fields(config)
    passages = source_fields(config)
    if not (fields or passages) or not isinstance(record, dict):
        return record
    out = {k: v for k, v in record.items() if k not in fields}
    for name in passages:
        if isinstance(out.get(name), str):
            out[name] = public_text(out[name])
    return out


def score_responses(scheme: dict, responses: Dict[str, str],
                    item_data: Optional[dict] = None) -> Optional[Dict[str, object]]:
    """``{blank_<i>_correct: 0/1, ..., score: n, scored_blanks: m}``, or None
    when there is no answer key. ``responses`` maps blank labels to text."""
    if scheme.get("source_field"):
        answers = item_answers(scheme, item_data)
        passage = (item_data or {}).get(scheme["source_field"])
        blanks = len(parse_passage(passage)[1]) if isinstance(passage, str) else 0
        if len(answers) != blanks:
            logger.warning("cloze '%s': item has %d blanks and %d answers; scoring %d",
                           scheme.get("name"), blanks, len(answers), min(blanks, len(answers)))
        answers = answers[:blanks]
    else:
        _, answers = parse_passage(scheme.get("text", ""))
    mode = scheme.get("scoring", "case_insensitive")
    out: Dict[str, object] = {}
    score = scored = 0
    for i, key in enumerate(answers):
        if not key:
            continue
        scored += 1
        given = _normalize(str(responses.get(blank_label(i), "")), mode)
        ok = any(given == _normalize(k, mode) for k in key)
        out[f"{blank_label(i)}_correct"] = int(ok)
        score += int(ok)
    if not scored:
        return None
    out["score"] = score
    out["scored_blanks"] = scored
    return out


def blank_count(scheme: dict, item_data: Optional[dict] = None) -> int:
    if scheme.get("source_field"):
        passage = (item_data or {}).get(scheme["source_field"])
        return len(parse_passage(passage)[1]) if isinstance(passage, str) else 0
    return len(parse_passage(scheme.get("text", ""))[1])


def all_blanks_filled(scheme: dict, labels: Dict[str, object],
                      item_data: Optional[dict] = None) -> bool:
    """Every blank holds non-whitespace text (the required-answer rule)."""
    n = blank_count(scheme, item_data)
    return n > 0 and all(str(labels.get(blank_label(i), "") or "").strip() for i in range(n))


def generate_cloze_layout(annotation_scheme):
    """Generate the cloze passage with one text input per blank."""
    return safe_generate_layout(annotation_scheme, _generate_cloze_layout_internal)


def _width(annotation_scheme) -> int:
    try:
        return max(2, min(60, int(annotation_scheme.get("input_width", 10))))
    except (TypeError, ValueError):
        return 10


def _passage_html(schema_name: str, segments: List[object], total: int,
                  width: int, validation: str) -> str:
    parts = []
    for seg in segments:
        if isinstance(seg, int):
            ids = generate_element_identifier(schema_name, blank_label(seg), "text")
            parts.append(
                f'<input class="{ids["schema"]} cloze-blank annotation-input" type="text" '
                f'id="{ids["id"]}" name="{ids["name"]}" schema="{ids["schema"]}" '
                f'label_name="{ids["label_name"]}" validation="{validation}" '
                f'autocomplete="off" autocapitalize="off" spellcheck="false" '
                f'aria-label="Blank {seg + 1} of {total}" style="width: {width}ch;">'
            )
        else:
            parts.append(escape_html_content(seg))
    return "".join(parts)


def fill_item_passages(soup, config: dict, item_data: Optional[dict]) -> int:
    """Put each item-driven passage into its placeholder in the rendered page.

    Runs before the page restores saved answers, so the blanks are real inputs
    by then. Returns the number of passages filled.
    """
    from bs4 import BeautifulSoup
    filled = 0
    schemes = {s.get("name"): s for s in (config or {}).get("annotation_schemes") or []
               if isinstance(s, dict) and s.get("annotation_type") == "cloze"
               and s.get("source_field")}
    for holder in soup.find_all(attrs={"data-cloze-source": True}):
        scheme = schemes.get(holder.get("data-cloze-schema"))
        if scheme is None:
            continue
        passage = (item_data or {}).get(scheme["source_field"])
        if not isinstance(passage, str) or not BLANK.search(passage):
            holder.string = "This item has no passage to complete."
            logger.warning("cloze '%s': item field '%s' has no [[ ]] blanks",
                           scheme["name"], scheme["source_field"])
            continue
        segments, answers = parse_passage(passage)
        if any(answers):
            logger.warning("cloze '%s': item passage has text inside [[ ]]; it is not "
                           "shown and not used as the key (use answer_field)", scheme["name"])
        inner = _passage_html(scheme["name"], segments, len(answers), _width(scheme),
                              generate_validation_attribute(scheme))
        holder.clear()
        holder.append(BeautifulSoup(inner, "html.parser"))
        filled += 1
    return filled


def _generate_cloze_layout_internal(annotation_scheme):
    schema_name = annotation_scheme["name"]
    validation = generate_validation_attribute(annotation_scheme)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    width = _width(annotation_scheme)

    source_field = annotation_scheme.get("source_field")
    text = annotation_scheme.get("text")
    if source_field:
        if text:
            raise ValueError(f"cloze scheme '{schema_name}' has both `text` and `source_field`")
        # Filled per item at render time (fill_item_passages).
        passage = (f'<p class="cloze-passage" data-cloze-source="{escape_html_content(str(source_field))}" '
                   f'data-cloze-schema="{escape_html_content(schema_name)}"></p>')
    else:
        if not isinstance(text, str) or not BLANK.search(text):
            raise ValueError(f"cloze scheme '{schema_name}' needs a `text` with at least "
                             "one [[blank]], or a `source_field`")
        segments, answers = parse_passage(text)
        passage = (f'<p class="cloze-passage">'
                   f'{_passage_html(schema_name, segments, len(answers), width, validation)}</p>')

    html = f"""
    <form id="{escape_html_content(schema_name)}" class="annotation-form cloze" action="javascript:void(0)" data-annotation-id="{escape_html_content(str(annotation_scheme.get("annotation_id", "")))}" data-annotation-type="cloze" data-schema-name="{escape_html_content(schema_name)}" {layout_attrs}>
        <fieldset schema_name="{escape_html_content(schema_name)}">
            <legend class="cloze-title">{escape_html_content(annotation_scheme.get("description", ""))}</legend>
            {passage}
        </fieldset>
    </form>
    """
    return html, []


def key_mismatches(scheme: dict, items: Dict[str, dict]) -> List[str]:
    """Item ids whose answer key has a different number of entries than the
    passage has blanks (item-driven passages only)."""
    if not scheme.get("source_field") or not scheme.get("answer_field"):
        return []
    out = []
    for iid, data in (items or {}).items():
        if not isinstance(data, dict) or scheme["answer_field"] not in data:
            continue
        if len(item_answers(scheme, data)) != blank_count(scheme, data):
            out.append(str(iid))
    return out
