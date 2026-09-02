"""
Collapse stored answers to a single comparable value.

Conditional display logic asks a simple question — "what did the participant answer for
schema X?" — but answers are stored as ``{Label(schema, label_name): value}``, one entry
per selected option. Reducing that to something an ``equals``/``contains`` condition can
be evaluated against is the *collapse*, and it has to give the same result everywhere:
in the browser (which shows or hides the question), in the export (which decides whether
an answer is included), and in training grading (which compares against a gold answer).

Before this module those were three separate implementations that disagreed. The rules
are now written down here once.

Rules, applied per schema to its ``[(label_name, value)]`` entries in persisted order:

1. **Exempt labels are set aside.** ``free_response`` is the "Other (please specify)"
   text that ``radio``/``multiselect`` attach to the *same* schema; it is a companion
   answer, not a competing option, so it must not out-vote the chosen option. It is
   used only when there is nothing else.
2. **Deduplicate by label name, last write wins.** A schema answered on two pages of one
   phase is one answer, not two. Without this the same reply on two pages collapses to
   ``['Yes', 'Yes']`` server-side while the browser sees ``'Yes'`` — the condition then
   fails server-side only, and the answer is silently dropped from the export.
3. **An entry counts as "selected"** if its value is ``True`` / ``1`` / ``"true"``
   (the legacy v1-template boolean payload) **or if the value equals the label name**.
   The second clause matters: the current frontend stores a checked box as
   ``{"en": "en"}``, so without it no multiselect entry is ever recognised as selected
   and a ``contains`` condition silently evaluates against one arbitrary label.
4. **The collapsed value is the label NAME for selections**, the raw value for scalars.
   Names are stable; ``value`` is not (a likert's value diverges from its label under
   ``key_value``/``sequential_key_binding``).
5. **A single-select schema holding several selections** — only reachable in data written
   before the GH #167 fix — resolves through
   :func:`potato.export.single_select.resolve_final_label`, so the collapse and the
   export's "which value won" decision cannot disagree.

Deliberately dependency-light (typing + logging only) so the export path and the storage
layer can both import it without a loaded server config.
"""

import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: Labels that coexist with a schema's real answer instead of competing with it.
#: This is the single definition; ``schema_exclusivity`` and ``export.single_select``
#: both re-export it so there is one list, not three.
EXEMPT_LABEL_NAMES = frozenset({"free_response"})

#: Types that render one input per option but may keep only one.
SINGLE_SELECT_TYPES = frozenset({"radio", "likert", "confidence"})

#: Types that legitimately keep several labels at once.
MULTI_SELECT_TYPES = frozenset({"multiselect"})


def is_selected(label_name: str, value: Any) -> bool:
    """Whether an entry represents a chosen option (see rule 3)."""
    if value is True:
        return True
    if isinstance(value, bool):          # False is not a selection
        return False
    if value == 1:
        return True
    if isinstance(value, str):
        if value.lower() == "true":
            return True
        if label_name and value == label_name:
            return True
    return False


def _dedupe(entries: Sequence[Tuple[str, Any]]) -> List[Tuple[str, Any]]:
    """Collapse repeated labels to their last occurrence, preserving first-seen order."""
    seen: Dict[str, Any] = {}
    for label_name, value in entries:
        seen[label_name or ""] = value
    return list(seen.items())


def collapse_entries(entries: Sequence[Tuple[str, Any]],
                     schema: str = "",
                     annotation_type: Optional[str] = None,
                     changes: Optional[List[Dict[str, Any]]] = None
                     ) -> Tuple[Any, Optional[str], str]:
    """Collapse one schema's entries to a comparable value.

    Args:
        entries: ``[(label_name, value)]`` in persisted order.
        schema: Schema name, used only for resolution and logging.
        annotation_type: When known, enables the type-aware branches (rule 5 and the
            multiselect list). When None the generic rules 1-4 apply.
        changes: ``annotation_changes`` records, used to resolve a pre-#167
            single-select schema that holds several values.

    Returns:
        ``(value, winner_label, method)``. ``value`` is None when there is nothing to
        compare. ``method`` is one of ``"empty"``, ``"single"``, ``"multi"``,
        ``"scalar"``, ``"behavioral"``, ``"order"`` or ``"exempt"``.
    """
    deduped = _dedupe(entries)
    exempt = [(ln, v) for ln, v in deduped if ln in EXEMPT_LABEL_NAMES]
    main = [(ln, v) for ln, v in deduped if ln not in EXEMPT_LABEL_NAMES]

    if not main:
        # Nothing but free-text: the prose IS the answer.
        for _ln, value in exempt:
            if value not in (None, "", False):
                return value, None, "exempt"
        return None, None, "empty"

    selected = [ln for ln, v in main if is_selected(ln, v)]

    if annotation_type in MULTI_SELECT_TYPES:
        # Presence means checked — syncAnnotationsFromDOM deletes unchecked boxes
        # rather than storing them false. Keep the 1-element case scalar so existing
        # `operator: equals` conditions on a single-ticked multiselect keep working.
        names = selected or [ln for ln, _v in main]
        if not names:
            return None, None, "empty"
        if len(names) == 1:
            return names[0], names[0], "single"
        return names, None, "multi"

    if annotation_type in SINGLE_SELECT_TYPES and len(selected) > 1:
        from potato.export.single_select import resolve_final_label
        winner, method = resolve_final_label(schema, selected, changes)
        return winner, winner, method

    if len(selected) == 1:
        return selected[0], selected[0], "single"
    if len(selected) > 1:
        return selected, None, "multi"

    scalars = [v for _ln, v in main
               if isinstance(v, (str, int, float))
               and not isinstance(v, bool) and v != ""]
    if not scalars:
        return None, None, "empty"
    if len(scalars) == 1:
        return scalars[0], None, "scalar"

    # Several scalar values for one schema: only reachable in pre-#167 data.
    if annotation_type in SINGLE_SELECT_TYPES or annotation_type is None:
        labels = [ln for ln, v in main
                  if isinstance(v, (str, int, float)) and not isinstance(v, bool) and v != ""]
        from potato.export.single_select import resolve_final_label
        winner, method = resolve_final_label(schema, labels, changes)
        if winner is not None:
            by_label = dict(main)
            return by_label.get(winner), winner, method
    return scalars[-1], None, "order"


def collapse_answers(entries_by_schema: Dict[str, Sequence[Tuple[str, Any]]],
                     schema_types: Optional[Dict[str, str]] = None,
                     changes: Optional[List[Dict[str, Any]]] = None
                     ) -> Dict[str, Any]:
    """Collapse every schema's entries. Schemas with no comparable value are omitted."""
    schema_types = schema_types or {}
    result: Dict[str, Any] = {}
    for schema, entries in entries_by_schema.items():
        if not schema:
            continue
        value, _winner, _method = collapse_entries(
            entries, schema=schema,
            annotation_type=schema_types.get(schema), changes=changes)
        if value is not None:
            result[schema] = value
    return result
