"""
Agreement on links, coreference chains and events.

``span_link``, ``coreference`` and ``event_annotation`` do not store spans of
their own. Their answer is links (or chains, or events) between spans drawn
under another scheme, the one named by ``span_schema``, and the links live in
the user state's link and event stores rather than with the spans. These
schemes were classified as span schemes, so the span gatherer looked for
spans under the link scheme's name, found none, and the schemes were never
scored.

Each annotator's answer is rewritten into the canonical form the trainers
use (:func:`potato.training.structured.canonical_answer`), which refers to
spans by offsets rather than by browser-assigned ids, and every pair of
annotators is scored with the training metrics: CoNLL F1 (MUC, B-cubed,
CEAF-e) for chains, link and mention F1 for links, trigger and argument F1
for events. Each pair is pooled over the items both saved, and the report is
the mean over pairs. F1 is symmetric, so which annotator plays the reference
does not matter. None of these are chance-corrected.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable

#: annotation kind -> (canonical answer kind, structure key in that answer,
#: [(reported name, scorer's name)])
_SPECS = {
    "relation": ("relation", "links",
                 [("link_f1", "f1"), ("mention_f1", "mention_f1")]),
    "coreference": ("coreference", "clusters",
                    [("conll_f1", "conll_f1"), ("muc_f1", "muc_f1"),
                     ("b3_f1", "b3_f1"), ("ceafe_f1", "ceafe_f1")]),
    "event": ("event", "events",
              [("trigger_f1", "trigger_f1"), ("argument_f1", "argument_f1")]),
}

NOTE = ("Mean over annotator pairs of F1 pooled over the items both saved. "
        "Not chance-corrected.")


def _as_dicts(records: Iterable[Any]) -> list:
    out = []
    for record in records or ():
        if isinstance(record, dict):
            out.append(record)
        elif hasattr(record, "to_dict"):
            out.append(record.to_dict())
    return out


def _records(ustate, method: str, iid: str):
    getter = getattr(ustate, method, None)
    if not callable(getter):
        return []
    try:
        found = getter(iid) or {}
    except Exception:
        return []
    return list(found.values()) if isinstance(found, dict) else list(found)


def gather_links(instance_ids: Iterable[str], user_states: Dict[str, Any],
                 scheme: Dict[str, Any], kind: str):
    """``{item: {annotator: canonical answer}}`` for one link scheme.

    An annotator who saved the item and drew nothing for the scheme counts
    with an empty answer, as in the span gatherer, so "A linked two mentions,
    B linked none" is a disagreement rather than an item with one annotator.
    Items nobody answered are left out.
    """
    from potato.server_utils.iaa.dispatcher import _saved_item
    from potato.training.structured import canonical_answer, span_schema_of

    answer_kind, structure, _ = _SPECS[kind]
    span_schema = span_schema_of(scheme)
    rows: Dict[str, Dict[str, Any]] = {}
    for iid in instance_ids:
        per_user: Dict[str, Any] = {}
        for uid, ustate in user_states.items():
            spans_by = getattr(ustate, "get_span_annotations", None)
            try:
                flat = spans_by(iid) if callable(spans_by) else {}
            except Exception:
                flat = {}
            spans = [s for s in _as_dicts(flat or {})
                     if str(s.get("schema", "")) == span_schema]
            answer = canonical_answer(
                answer_kind, scheme, spans=spans,
                links=_as_dicts(_records(ustate, "get_link_annotations", iid)),
                events=_as_dicts(_records(ustate, "get_event_annotations", iid)))
            if answer is not None:
                per_user[uid] = answer
            elif _saved_item(ustate, iid):
                per_user[uid] = {"spans": [], structure: []}
        if any(_answered(a) for a in per_user.values()):
            rows[iid] = per_user
    return rows


def _answered(answer: Any) -> bool:
    return isinstance(answer, dict) and any(
        answer.get(key) for key in ("spans", "links", "clusters", "events"))


def link_report(rows: Dict[str, Dict[str, Any]], kind: str) -> Dict[str, Any]:
    """Mean pairwise F1 for one link, chain or event scheme."""
    from potato.training import structured_metrics

    _, _, names = _SPECS[kind]
    users = sorted({uid for per_user in rows.values() for uid in per_user},
                   key=str)
    collected = {name: [] for name, _ in names}
    items, annotators = set(), set()
    n_pairs = 0
    for i, a in enumerate(users):
        for b in users[i + 1:]:
            shared = [iid for iid in sorted(rows, key=str)
                      if a in rows[iid] and b in rows[iid]
                      and (_answered(rows[iid][a]) or _answered(rows[iid][b]))]
            if not shared:
                continue
            ga = [rows[iid][a] for iid in shared]
            gb = [rows[iid][b] for iid in shared]
            def score(x, y):
                if kind == "relation":
                    # trees=False: UAS and LAS are measured over the
                    # reference's spans, so they would change with which
                    # annotator is the reference.
                    return structured_metrics.score_relations(x, y, trees=False)
                if kind == "coreference":
                    return structured_metrics.score_coreference(x, y)
                return structured_metrics.score_events(x, y)

            scores = score(ga, gb)
            # An annotator scored against themselves gets 0 on a measure only
            # when they have nothing it counts (no links, no chain of two). Two
            # such annotators agree on that measure; scored as F1 it read 0,
            # as total disagreement.
            alone_a, alone_b = score(ga, ga), score(gb, gb)
            n_pairs += 1
            items.update(shared)
            annotators.update((a, b))
            pair = {}
            for name, source in names:
                value = float(scores.get(source, 0.0))
                if (not value and not float(alone_a.get(source, 0.0))
                        and not float(alone_b.get(source, 0.0))):
                    value = 1.0
                pair[name] = value
            if kind == "coreference":
                # CoNLL F1 is the mean of the three, as corrected here.
                pair["conll_f1"] = (pair["muc_f1"] + pair["b3_f1"] + pair["ceafe_f1"]) / 3.0
            for name, value in pair.items():
                collected[name].append(value)

    metrics: Dict[str, Any] = {
        name: (sum(values) / len(values) if values else math.nan)
        for name, values in collected.items()}
    metrics["n_items"] = len(items)
    metrics["n_annotators"] = len(annotators)
    metrics["n_pairs"] = n_pairs
    metrics["note"] = NOTE if n_pairs else (
        "No two annotators saved the same item with an answer for this "
        "scheme, so there is nothing to compare.")
    return metrics
