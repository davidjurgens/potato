"""
Interlinear glossed text (``annotation_type: interlinear_gloss``).

The item holds a sentence, or a list of words, in ``source_field``. The page
shows one column per word: the word (read-only), its morpheme segmentation and
its gloss (both editable), any extra tiers named in ``tiers``, and a free
translation line under the columns. Columns wrap onto further lines when the
screen is narrow, as printed interlinear examples do.

Optional item fields pre-fill the analysis (``morphemes_field``,
``gloss_field``, ``translation_field``; a tier is pre-filled from an item
field of the same name holding one value per word), which is how the FLExText
and Toolbox importers hand an existing analysis to annotators for review.

The checks follow the Leipzig Glossing Rules: per word, the segmentation and
the gloss must have the same ``-`` and ``=`` boundaries in the same order, and
category labels can be checked against ``abbreviations``. The rules live in
:mod:`potato.igt`; ``static/interlinear-gloss.js`` builds the page and applies
the same checks while the annotator types.

The answer is one hidden input holding JSON::

    {"words": [{"word": ..., "morphemes": ..., "gloss": ..., <tier>: ...}],
     "translation": ...}
"""

import json
import logging
from typing import Any, Dict, List, Tuple

from .identifier_utils import (
    escape_html_content, generate_element_identifier, generate_layout_attributes,
    generate_validation_attribute, safe_generate_layout)

logger = logging.getLogger(__name__)

#: Names a configured tier may not take: they are the fixed keys of a word.
RESERVED_TIERS = frozenset({"word", "morphemes", "gloss"})


def generate_interlinear_gloss_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def page_config(annotation_scheme: Dict[str, Any]) -> Dict[str, Any]:
    """What the page script needs, with the abbreviation list resolved."""
    from potato.igt import resolve_abbreviations
    tiers = [str(t) for t in (annotation_scheme.get("tiers") or [])]
    bad = [t for t in tiers if t in RESERVED_TIERS]
    if bad:
        raise ValueError(f"interlinear_gloss '{annotation_scheme['name']}': tiers may not be named "
                         f"{', '.join(bad)} (those lines are always shown)")
    return {
        "schema": annotation_scheme["name"],
        "sourceField": annotation_scheme.get("source_field") or "text",
        "morphemesField": annotation_scheme.get("morphemes_field") or "",
        "glossField": annotation_scheme.get("gloss_field") or "",
        "translationField": annotation_scheme.get("translation_field") or "",
        "tiers": tiers,
        "abbreviations": resolve_abbreviations(annotation_scheme.get("abbreviations")),
        "language": annotation_scheme.get("language") or "",
        "metalanguage": annotation_scheme.get("metalanguage") or "",
        "translation": annotation_scheme.get("show_translation", True) is not False,
    }


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    esc = escape_html_content(schema_name)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    validation = generate_validation_attribute(annotation_scheme)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    instructions = annotation_scheme.get("instructions", "")
    config = json.dumps(page_config(annotation_scheme))

    html = f"""
    <form id="{esc}" class="annotation-form interlinear-gloss" action="javascript:void(0)"
          data-annotation-type="interlinear_gloss" data-schema-name="{esc}"
          data-igt-config='{escape_html_content(config)}' {layout_attrs}>
        <fieldset schema="{esc}">
            <legend class="igt-title">{escape_html_content(annotation_scheme["description"])}</legend>
            {f'<p class="igt-instructions">{escape_html_content(instructions)}</p>' if instructions else ''}
            <div class="igt-root">
                <p class="igt-loading" role="status">Loading the words…</p>
            </div>
            <input type="hidden" class="annotation-input interlinear-gloss-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>
    """
    return html, []
