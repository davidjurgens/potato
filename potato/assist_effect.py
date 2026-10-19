"""
Did AI assistance change the answers? The comparison behind the
"AI influence" admin tab.

Annotators are split by `ai_support.holdout` (see assist_holdout.py): a random
share of (annotator, item) pairs saw no assistance. For each categorical
scheme, the two groups are compared on

* **agreement with the model**: how often the answer equals the model's own
  answer for the item (its pre-annotation). Anchoring shows up as a higher
  rate in the assisted group than in the held-out one.
* **gold accuracy**, where the item has a gold label: whether the assistance
  made answers more correct, or only more like the model.
* **inter-annotator alpha** within each group: agreement can rise simply
  because everyone copies the same suggestion, which says nothing about
  reliability.

The difference in model agreement carries a 95% bootstrap interval over
items. Groups below MIN_PAIRS pairs are reported without a comparison.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from potato.assist_holdout import holdout_settings, is_held_out

#: Fewer pairs than this in either group, and the difference is not reported.
MIN_PAIRS = 10
CATEGORICAL = {"radio", "multiselect", "likert", "select"}
#: Label names stored beside a categorical answer that are not part of it.
_NOT_ANSWERS = {"free_response", "bad_text", "text_box"}


def _answer(value: Any) -> Optional[frozenset]:
    """A prediction or gold value as a set of label names."""
    if value is None or value == "" or value == []:
        return None
    if isinstance(value, dict):
        value = [k for k, v in value.items() if v not in (None, False, "", "false")]
    values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
    names = frozenset(str(v) for v in values if v not in (None, ""))
    return names or None


def _user_answer(user_state, instance_id: str, schema: str) -> Optional[frozenset]:
    try:
        labels = user_state.get_label_annotations(instance_id) or {}
    except Exception:
        return None
    names = []
    for label, value in labels.items():
        if getattr(label, "get_schema", lambda: None)() != schema:
            continue
        if value in (None, False, "", "false"):
            continue
        name = label.get_name()
        if name not in _NOT_ANSWERS:
            names.append(name)
    return frozenset(names) or None


def _rate(pairs: List[bool]) -> Optional[float]:
    return sum(pairs) / len(pairs) if pairs else None


def _alpha(rows) -> Optional[float]:
    from potato.server_utils.iaa.alpha import krippendorff_alpha
    import math
    if not rows:
        return None
    value = krippendorff_alpha([(u, i, "|".join(sorted(v))) for u, i, v in rows], "nominal")
    return None if math.isnan(value) else value


def _bootstrap_difference(by_item, rounds: int = 1000, seed: int = 0):
    """95% interval for assisted minus held-out model-agreement, over items."""
    items = [i for i, groups in by_item.items() if groups["assisted"] or groups["held_out"]]
    if len(items) < 2:
        return None
    rng = random.Random(seed)
    diffs = []
    for _ in range(rounds):
        sample = [rng.choice(items) for _ in items]
        a = [x for i in sample for x in by_item[i]["assisted"]]
        h = [x for i in sample for x in by_item[i]["held_out"]]
        if a and h:
            diffs.append(sum(a) / len(a) - sum(h) / len(h))
    if len(diffs) < rounds // 2:
        return None
    diffs.sort()
    return [diffs[int(0.025 * len(diffs))], diffs[int(0.975 * len(diffs)) - 1]]


def assist_effect(config: Dict[str, Any], user_states: Dict[str, Any],
                  items: Dict[str, Dict[str, Any]],
                  gold: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The comparison for every categorical scheme.

    Args:
        config: the study config (for the hold-out and pre_annotation field).
        user_states: ``{user_id: UserState}``.
        items: ``{instance_id: item data dict}``.
        gold: ``{instance_id: gold label}`` (a mapping per scheme, or a single
            value for a one-scheme study).
    """
    fraction, _salt = holdout_settings(config)
    report: Dict[str, Any] = {"holdout_fraction": fraction, "schemas": {}}
    if fraction <= 0:
        report["note"] = ("No comparison group: set ai_support.holdout.fraction "
                          "to hold assistance back from a share of annotators' items.")
        return report

    pa = config.get("pre_annotation") or {}
    field = str(pa.get("field") or "predictions") if isinstance(pa, dict) else "predictions"
    gold = gold or {}
    schemes = [s for s in config.get("annotation_schemes") or []
               if isinstance(s, dict) and s.get("annotation_type") in CATEGORICAL]

    for scheme in schemes:
        name = scheme["name"]
        groups = {g: {"model": [], "gold": [], "rows": []} for g in ("assisted", "held_out")}
        by_item: Dict[str, Dict[str, List[bool]]] = {}
        for user_id, state in user_states.items():
            try:
                annotated = state.get_annotated_instance_ids()
            except Exception:
                continue
            for iid in annotated:
                answer = _user_answer(state, iid, name)
                if answer is None:
                    continue
                group = "held_out" if is_held_out(config, user_id, iid) else "assisted"
                bucket = groups[group]
                bucket["rows"].append((user_id, iid, answer))
                record = items.get(iid) or {}
                predicted = record.get(field) if isinstance(record, dict) else None
                model = _answer(predicted.get(name) if isinstance(predicted, dict) else None)
                if model is not None:
                    hit = answer == model
                    bucket["model"].append(hit)
                    by_item.setdefault(iid, {"assisted": [], "held_out": []})[group].append(hit)
                g = gold.get(iid)
                g = g.get(name) if isinstance(g, dict) else (g if len(schemes) == 1 else None)
                truth = _answer(g)
                if truth is not None:
                    bucket["gold"].append(answer == truth)

        entry: Dict[str, Any] = {}
        for group, bucket in groups.items():
            alpha = _alpha(bucket["rows"])
            entry[group] = {
                "n_pairs": len(bucket["rows"]),
                "model_agreement": _rate(bucket["model"]),
                "n_with_model_answer": len(bucket["model"]),
                "gold_accuracy": _rate(bucket["gold"]),
                "n_with_gold": len(bucket["gold"]),
                "alpha": alpha,
            }
            # A null alpha needs its reason beside it, or it reads as "not
            # computed". Unanimity is the common case: everyone in the group
            # gave the same answer, which is perfect agreement, not a failure.
            if alpha is None and bucket["rows"]:
                distinct = {v for _u, _i, v in bucket["rows"]}
                entry[group]["alpha_note"] = (
                    "every answer in this group is the same, so alpha is undefined "
                    "(perfect agreement, not a failed computation)"
                    if len(distinct) < 2 else
                    "too few items with two or more answers for alpha to be defined")
        a, h = entry["assisted"], entry["held_out"]
        if a["n_with_model_answer"] >= MIN_PAIRS and h["n_with_model_answer"] >= MIN_PAIRS:
            entry["model_agreement_difference"] = a["model_agreement"] - h["model_agreement"]
            entry["difference_ci95"] = _bootstrap_difference(by_item)
        else:
            entry["note"] = (
                f"Too few answers with a model answer to compare yet "
                f"({a['n_with_model_answer']} assisted, {h['n_with_model_answer']} held out; "
                f"{MIN_PAIRS} each needed).")
        report["schemas"][name] = entry
    return report
