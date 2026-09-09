"""Reading a wire key, and reading an answer out of one.

``/updateinstance`` accepts two separators and two payload shapes for the same
selection. The annotation page posts ``{"stance:Sincere": "Sincere"}`` -- the
label in both halves -- while a client posting what the form element actually
holds sends ``{"stance:Sincere": "on"}``, where the answer is in the KEY and
the value is the DOM default. The route's own 400 message asks callers for
``schema:::label``; the browser sends a single colon. Every consumer that
grades, scores or compares an answer therefore has to understand four
combinations, and each one had its own copy of the read:

* ``quality_control`` split on the first colon, so an answer posted as
  ``stance:::Sincere`` was read as the label ``"::Sincere"``. Two annotators
  answering identically and correctly scored 3/3 and 0/3, with byte-identical
  stored annotations and nothing in the log. The separator that fails is the
  one the route's refusal message asks for.
* ``expertise_manager`` compared the stored VALUE, which for a radio is the
  marker ``"on"``. Consensus was ``"on"``, every annotator matched it, and the
  router logged 36 agreements and no disagreement in a run where one annotator
  dissented on every item of a category. Every expertise score climbed to 1.0
  and probabilistic routing stayed uniform -- random assignment reporting
  success.
* ``_check_and_promote`` grouped by wire key rather than by schema, so two
  annotators giving OPPOSITE answers both carried ``"stance": "on"`` and the
  item was promoted to gold as unanimous, with a consensus label asserting
  both answers. Everyone graded against it afterwards was marked wrong.
* ``answer_collapse.is_selected`` -- the module whose docstring says the
  collapse "has to give the same result everywhere" -- recognised ``True``,
  ``1``, ``"true"`` and ``value == label_name``, and not ``"on"``. A radio
  answered by anything other than the annotation page collapsed to the string
  ``"on"`` in conditional display logic and in the export.

Dependency-light on purpose: the storage layer, the export and the QC manager
all import it, and none of them may drag in a loaded server config.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Values a client sends for "this option is selected" where the option itself
#: is carried by the key or the label name. The browser's own default for a
#: checked radio or checkbox is ``"on"``; rooms wrote ``"true"`` until it was
#: aligned; ``"1"`` and ``"checked"`` turn up in hand-written API callers.
SELECTION_MARKERS = frozenset({"on", "true", "yes", "1", "checked", "selected"})

#: Types whose stored value is the answer itself, so a marker-looking value is
#: something the annotator typed rather than a DOM default. A free-text field
#: holding the literal word "on" must not be read as the label name.
SCALAR_ANSWER_TYPES = frozenset({
    "text", "textbox", "number", "slider", "range_slider", "vas",
    "soft_label", "constant_sum", "span", "span_link",
})


def split_annotation_key(key: str) -> Optional[Tuple[str, str]]:
    """Split a wire key into ``(schema, label)``, accepting both separators.

    ``:::`` is tried first because it is the documented form and because a
    ``:::`` key also contains a ``:``: splitting on the first colon turns
    ``stance:::Sincere`` into the label ``"::Sincere"``, which matches nothing
    and says nothing.

    Returns None for a key that names no label -- a phase-page answer such as
    ``{"age_consent": "Yes"}``, where the schema carries the answer in its
    value because the question has no label to name.
    """
    if not isinstance(key, str):
        return None
    if ":::" in key:
        schema, _, label = key.partition(":::")
        return schema, label
    if ":" in key:
        schema, _, label = key.partition(":")
        return schema, label
    return None


def is_selection_marker(value: Any) -> bool:
    """Whether a value means "the key names the answer" rather than being it."""
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in SELECTION_MARKERS
    return False


def answer_from_entries(entries: Sequence[Tuple[str, Any]],
                        annotation_type: Optional[str] = None) -> Any:
    """One comparable answer from a schema's ``[(label_name, value)]`` entries.

    The label name wins whenever the value is a selection marker, because the
    marker is a DOM default and the label is the answer. Otherwise the value
    wins, which is what a free-text, numeric or scaled schema stores.

    Returns None when the schema was not answered.
    """
    markers_ok = annotation_type not in SCALAR_ANSWER_TYPES
    labeled: List[str] = []
    valued: List[Any] = []

    for label_name, value in entries:
        if value is None or value is False:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        if markers_ok and label_name and is_selection_marker(value):
            labeled.append(label_name)
        else:
            valued.append(value)

    if labeled:
        return labeled[0] if len(labeled) == 1 else sorted(labeled)
    if not valued:
        return None
    return valued[0] if len(valued) == 1 else valued


def canonical_wire_answer(payload: Dict[str, Any],
                          schema_types: Optional[Dict[str, str]] = None
                          ) -> Dict[str, Any]:
    """``{schema: answer}`` from an ``/updateinstance`` annotations payload.

    Both key shapes collapse to the same result, which is the point:
    ``{"stance:Sincere": "on"}``, ``{"stance:::Sincere": "on"}`` and
    ``{"stance:Sincere": "Sincere"}`` all read as ``{"stance": "Sincere"}``.

    A key naming no label is carried through unchanged -- that is the phase-page
    shape, where the value IS the answer.
    """
    schema_types = schema_types or {}
    by_schema: Dict[str, List[Tuple[str, Any]]] = {}
    bare: Dict[str, Any] = {}

    for key, value in (payload or {}).items():
        parsed = split_annotation_key(key)
        if parsed is None:
            bare[key] = value
            continue
        schema, label = parsed
        by_schema.setdefault(schema, []).append((label, value))

    canonical = dict(bare)
    for schema, entries in by_schema.items():
        answer = answer_from_entries(entries, schema_types.get(schema))
        if answer is not None:
            canonical[schema] = answer
        elif schema not in canonical:
            canonical[schema] = None
    return {k: v for k, v in canonical.items() if v is not None}
