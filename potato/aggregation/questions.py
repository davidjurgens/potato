"""
Vote fractions for question schemes.

Per item and question:

* ``n_classifiers``: annotators with an answer to this question on this item;
* per answer, ``count`` (annotators who gave it) and ``fraction``
  (``count / n_classifiers``). For a single-answer question the fractions sum
  to 1; for multiselect each is the share of classifiers who ticked that box,
  so they can sum to more than 1;
* ``top_answer``, ``top_count`` and ``top_fraction``; ``tied`` lists every
  answer sharing the top count when there is more than one;
* ``status``: ``retired`` or ``needs_review``, with ``reason``.

Status rules (``agreement_threshold`` T, ``min_classifiers`` N):

* fewer than N classifiers -> needs_review;
* radio, select, likert: retired when the top answer's fraction is at least T
  and no other answer ties it;
* multiselect: retired when every option is decided, i.e. ticked by at least
  T of the classifiers or left unticked by at least T of them.

Slider and number questions get ``n``, mean, median, standard deviation
(sample, n - 1), min and max instead (:func:`numeric_consensus`).
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from potato.server_utils.answer_collapse import EXEMPT_LABEL_NAMES, is_selected

#: annotation_type -> how its answer is read.
CATEGORICAL_TYPES = {"radio": "single", "likert": "single", "select": "value",
                     "multiselect": "multi"}
NUMERIC_TYPES = {"slider", "number"}

RETIRED = "retired"
NEEDS_REVIEW = "needs_review"


def _label_name(label: Any) -> Optional[str]:
    if isinstance(label, Mapping):
        name = label.get("name", label.get("value"))
        return None if name is None else str(name)
    if label is None:
        return None
    return str(label)


def answer_order(scheme: Mapping[str, Any]) -> List[str]:
    """The options in the order the scheme declares them."""
    labels = scheme.get("labels")
    if isinstance(labels, (list, tuple)) and labels:
        return [n for n in (_label_name(l) for l in labels) if n is not None]
    if scheme.get("annotation_type") == "likert":
        try:
            size = int(scheme.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        return [str(i) for i in range(1, size + 1)]
    return []


def read_answer(scheme: Mapping[str, Any], labels: Any,
                changes: Optional[List[dict]] = None):
    """One annotator's answer: a string, a frozenset (multiselect), a float
    (slider/number), or None when the record holds no answer to this question."""
    if not isinstance(labels, Mapping) or not labels:
        return None
    kind = scheme.get("annotation_type")
    if kind in NUMERIC_TYPES:
        for value in labels.values():
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                return number
        return None
    mode = CATEGORICAL_TYPES.get(kind)
    if mode == "value":
        for name, value in labels.items():
            if name in EXEMPT_LABEL_NAMES or value in (None, "", False):
                continue
            return str(value)
        return None
    chosen = [str(name) for name, value in labels.items()
              if name not in EXEMPT_LABEL_NAMES and is_selected(str(name), value)]
    if mode == "multi":
        return frozenset(chosen)
    if not chosen:
        return None
    if len(chosen) > 1:
        # Only reachable in data saved before the GH #167 fix.
        from potato.export.single_select import resolve_final_label
        winner, _ = resolve_final_label(scheme.get("name", ""), chosen, changes)
        return winner
    return chosen[0]


def _ordered(counts: Mapping[str, int], order: Sequence[str]) -> List[str]:
    extra = sorted(a for a in counts if a not in order)
    return [a for a in order] + extra


def categorical_consensus(scheme: Mapping[str, Any], answers: Mapping[str, Any],
                          agreement_threshold: float, min_classifiers: int) -> Dict[str, Any]:
    """Vote counts for one item and question. ``answers``: user -> answer."""
    kind = scheme.get("annotation_type")
    multi = CATEGORICAL_TYPES.get(kind) == "multi"
    given = {u: a for u, a in answers.items() if a is not None}
    n = len(given)
    counts: Counter = Counter()
    for answer in given.values():
        if multi:
            counts.update(answer)
        else:
            counts[answer] += 1
    order = _ordered(counts, answer_order(scheme))
    rows = [{"answer": a, "count": int(counts.get(a, 0)),
             "fraction": (counts.get(a, 0) / n) if n else 0.0} for a in order]

    top_count = max(counts.values()) if counts else 0
    leaders = [r["answer"] for r in rows if top_count and r["count"] == top_count]
    top = leaders[0] if leaders else None
    top_fraction = (top_count / n) if n else 0.0

    reason = ""
    if n < min_classifiers:
        reason = (f"{n} classifier{'s' if n != 1 else ''}, fewer than "
                  f"min_classifiers ({min_classifiers})")
    elif multi:
        undecided = [r["answer"] for r in rows
                     if not (_at_least(r["fraction"], agreement_threshold)
                             or _at_least(1.0 - r["fraction"], agreement_threshold))]
        if undecided:
            reason = ("no agreement on " + ", ".join(undecided) +
                      f" (ticked by more than {_pct(1 - agreement_threshold)} and fewer "
                      f"than {_pct(agreement_threshold)} of classifiers)")
    elif len(leaders) > 1:
        reason = "tie between " + ", ".join(leaders)
    elif not _at_least(top_fraction, agreement_threshold):
        reason = (f"top answer has {_pct(top_fraction)} of votes, below "
                  f"agreement_threshold ({_pct(agreement_threshold)})")
    return {
        "type": kind,
        "n_classifiers": n,
        "answers": rows,
        "top_answer": top,
        "top_count": int(top_count),
        "top_fraction": top_fraction,
        "tied": leaders if len(leaders) > 1 else [],
        "status": NEEDS_REVIEW if reason else RETIRED,
        "reason": reason,
        "classifiers": sorted(given),
    }


def _at_least(value: float, threshold: float) -> bool:
    """``value >= threshold``, tolerant of rounding in ``count / n`` (in
    binary, 1 - 4/5 is 0.19999999999999996, not 0.2)."""
    return value >= threshold - 1e-9


def _pct(x: float) -> str:
    return f"{round(100 * x, 1):g}%"


def numeric_consensus(scheme: Mapping[str, Any], answers: Mapping[str, Any]) -> Dict[str, Any]:
    values = sorted(float(v) for v in answers.values() if v is not None)
    n = len(values)
    out: Dict[str, Any] = {"type": scheme.get("annotation_type"), "n": n,
                           "mean": None, "median": None, "sd": None,
                           "min": None, "max": None,
                           "classifiers": sorted(u for u, v in answers.items() if v is not None)}
    if not n:
        return out
    mean = sum(values) / n
    mid = n // 2
    median = values[mid] if n % 2 else (values[mid - 1] + values[mid]) / 2
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) if n > 1 else None
    out.update(mean=mean, median=median, sd=sd, min=values[0], max=values[-1])
    return out


def gather_answers(scheme: Mapping[str, Any],
                   records: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """instance id -> user -> answer, for one question, from export records."""
    name = scheme.get("name")
    out: Dict[str, Dict[str, Any]] = {}
    for record in records:
        labels = (record.get("labels") or {}).get(name)
        answer = read_answer(scheme, labels, record.get("_changes"))
        if answer is None:
            continue
        out.setdefault(str(record.get("instance_id")), {})[str(record.get("user_id"))] = answer
    return out
