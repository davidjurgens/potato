"""
Aggregate human annotations across annotators into a single reference output.

Used when curating dataset examples from the live task: the majority human
annotation for each instance becomes the example's ``reference_outputs`` (gold),
so curated examples can be scored by evaluators / exported for fine-tuning.

Aggregation is exact-match majority vote per scheme over the annotator's full
``{label: value}`` map (well-defined for every schema type: radio, multiselect,
likert, textbox, …). Ties break toward the first-seen annotation. Vote counts
and agreement fractions are recorded in metadata for transparency.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple


def aggregate_instance_annotations(
    instance_id: str,
    usernames: List[str],
    get_user_annotations: Callable[[str, str], Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Aggregate annotations for one instance.

    Args:
        instance_id: the instance to aggregate.
        usernames: all candidate annotator ids.
        get_user_annotations: ``(username, instance_id) -> {scheme: {label: value}}``
            (e.g. ``flask_server.get_annotations_for_user_on``).

    Returns:
        ``(reference_outputs, meta)``. ``reference_outputs`` is
        ``{scheme: {label: value}}`` (the majority annotation per scheme) or
        ``None`` if nobody annotated this instance. ``meta`` carries
        ``num_annotators`` and per-scheme ``votes``.
    """
    raw_by_scheme: Dict[str, List[Tuple[str, Dict[str, Any]]]] = defaultdict(list)
    annotators_with_any = 0

    for user in usernames:
        try:
            ann = get_user_annotations(user, instance_id) or {}
        except Exception:
            ann = {}
        if ann:
            annotators_with_any += 1
        for scheme, value_map in ann.items():
            if not isinstance(value_map, dict):
                value_map = {"_value": value_map}
            canonical = json.dumps(value_map, sort_keys=True, ensure_ascii=False)
            raw_by_scheme[scheme].append((canonical, value_map))

    if not raw_by_scheme:
        return None, {"num_annotators": 0, "votes": {}}

    reference: Dict[str, Any] = {}
    votes_meta: Dict[str, Any] = {}
    for scheme, pairs in raw_by_scheme.items():
        counter = Counter(c for c, _ in pairs)
        winner_canonical, count = counter.most_common(1)[0]
        winner_dict = next(d for c, d in pairs if c == winner_canonical)
        reference[scheme] = winner_dict
        votes_meta[scheme] = {
            "winner_votes": count,
            "total": len(pairs),
            "agreement": round(count / len(pairs), 4),
        }

    return reference, {"num_annotators": annotators_with_any, "votes": votes_meta}


def consensus_reference_outputs(
    instance_ids: List[str],
    usernames: List[str],
    get_user_annotations: Callable[[str, str], Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """Batch **Dawid-Skene** consensus across all instances/annotators.

    Unlike per-instance majority vote, this jointly estimates each annotator's
    reliability and weights their votes accordingly — so a careful annotator
    sways the consensus more than a careless one. Returns
    ``(references_by_instance, meta)`` where ``references_by_instance[iid]`` is
    ``{scheme: value_map}`` and ``meta`` carries per-scheme annotator
    ``reliability`` and per-instance ``confidence``.
    """
    from potato.server_utils.consensus import dawid_skene

    # Per scheme: observations + a canonical->value_map lookup to map the
    # consensus label back to the original annotation dict.
    obs_by_scheme: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    canon_to_value: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)

    for user in usernames:
        for iid in instance_ids:
            try:
                ann = get_user_annotations(user, str(iid)) or {}
            except Exception:
                ann = {}
            for scheme, value_map in ann.items():
                if not isinstance(value_map, dict):
                    value_map = {"_value": value_map}
                canonical = json.dumps(value_map, sort_keys=True, ensure_ascii=False)
                obs_by_scheme[scheme].append((user, str(iid), canonical))
                canon_to_value[scheme][canonical] = value_map

    references: Dict[str, Dict[str, Any]] = defaultdict(dict)
    reliability_meta: Dict[str, Any] = {}
    confidence_meta: Dict[str, Dict[str, float]] = defaultdict(dict)

    for scheme, observations in obs_by_scheme.items():
        result = dawid_skene(observations)
        reliability_meta[scheme] = {w: round(r, 4) for w, r in result.reliability.items()}
        for iid, canonical in result.labels.items():
            references[iid][scheme] = canon_to_value[scheme].get(canonical, {})
            confidence_meta[iid][scheme] = round(result.confidence.get(iid, 0.0), 4)

    meta = {
        "method": "dawid_skene",
        "reliability": reliability_meta,
        "confidence": dict(confidence_meta),
    }
    return dict(references), meta
