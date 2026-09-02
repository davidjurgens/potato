"""Per-segment question forms for the temporal media widgets.

`segment_schemes` lets an audio or video scheme ask ordinary annotation
questions about each region the annotator marks. The key was accepted by the
config schema, required by the validator for audio's questions/both modes, and
passed to the browser as `segmentSchemes` -- and then nothing rendered it.
audio-annotation.js drew a placeholder paragraph where the fields belonged and
video-annotation.js ignored the key entirely, so every segment was stored with
an empty `annotations` object.

This module supplies the missing half: it renders each sub-scheme once, through
the same `schema_registry` every top-level scheme goes through, into a hidden
`<template>`. The client clones that template per segment.

Rendering through the registry rather than hand-writing inputs is the whole
point -- all 61 annotation types work inside a segment, including the ones added
after this file, and each one's tooltips, keybind labels and layout come out
identical to its top-level form.

## Why the clone is stripped

A generated form carries `class="annotation-input"` plus `schema` and
`label_name` attributes, which is exactly what `syncAnnotationsFromDOM` and the
display-logic collector look for. Cloned into the page unchanged, a segment's
answer would be read as a top-level answer for a scheme that does not exist,
and several segments would fight over the same key. The client renames those
attributes to `data-segment-*` on clone, making the fields proxy widgets whose
only home is `segment.annotations` -- the same pattern the turn-level annotation
framework uses for its per-turn slots.
"""

import html
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


#: Attributes and classes that make an input visible to the page-level
#: collectors. The client strips these on clone; they are listed here so the
#: two halves cannot drift.
PROXY_STRIPPED_ATTRIBUTES = ("schema", "label_name", "validation")
PROXY_STRIPPED_CLASS = "annotation-input"


def render_segment_question_template(
    segment_schemes: List[Dict[str, Any]], parent_schema_name: str
) -> Tuple[str, List[Tuple[str, str]]]:
    """Render `segment_schemes` into a hidden `<template>` for the client to clone.

    Args:
        segment_schemes: The sub-scheme dicts from the config.
        parent_schema_name: The audio/video scheme these belong to, used to
            build the template's id and to namespace the cloned fields.

    Returns:
        (html, keybindings). The keybindings list is always empty: a segment's
        fields only exist while a segment is selected, so binding a global key
        to one of them would fire against whichever segment happened to be open,
        or against none.
    """
    if not segment_schemes:
        return "", []

    # Imported here rather than at module scope: registry.py imports every
    # schema module, and this module is imported by two of them.
    from potato.server_utils.schemas.registry import schema_registry

    escaped_parent = html.escape(str(parent_schema_name), quote=True)
    blocks = []

    for index, sub_scheme in enumerate(segment_schemes):
        if not isinstance(sub_scheme, dict):
            logger.warning(
                "segment_schemes[%d] on '%s' is not a mapping; skipping",
                index, parent_schema_name)
            continue

        scheme = dict(sub_scheme)
        name = scheme.get("name") or f"segment_question_{index}"
        scheme.setdefault("name", name)
        scheme.setdefault("description", name)
        # A segment form is rebuilt on every selection, so a server-assigned
        # annotation_id would be stale the moment the annotator picks another
        # segment. The client namespaces ids by segment instead.
        scheme["annotation_id"] = f"{parent_schema_name}_segment_{index}"

        try:
            field_html, _ = schema_registry.generate(scheme)
        except Exception as exc:
            # One bad sub-scheme must not take the whole media widget with it.
            logger.error(
                "Failed to generate segment question '%s' on '%s': %s",
                name, parent_schema_name, exc)
            field_html = (
                '<p class="segment-question-error">'
                f'Could not render segment question "{html.escape(str(name))}": '
                f'{html.escape(str(exc))}</p>'
            )

        blocks.append(
            f'<div class="segment-question" data-segment-scheme="{html.escape(str(name), quote=True)}">'
            f'{field_html}</div>'
        )

    if not blocks:
        return "", []

    template = (
        f'<template id="segment-questions-template-{escaped_parent}" '
        f'class="segment-questions-template">'
        f'{"".join(blocks)}'
        f'</template>'
    )
    return template, []


def segment_scheme_names(segment_schemes: List[Dict[str, Any]]) -> List[str]:
    """The names the client will key `segment.annotations` by."""
    names = []
    for index, sub_scheme in enumerate(segment_schemes or []):
        if isinstance(sub_scheme, dict):
            names.append(sub_scheme.get("name") or f"segment_question_{index}")
    return names
