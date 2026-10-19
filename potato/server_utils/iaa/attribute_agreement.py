"""
Agreement over per-object attributes.

Two annotators who both drew the same car can still disagree about whether it
is partly occluded, and that disagreement is often where a driving or
detection dataset is least reliable. Every CV tool stores such attributes;
none reports whether the people filling them in agree.

For each attribute, the units are the objects two or more annotators drew in
the same place (matched by `geometry_agreement._matched_clusters`, the same
matching the classification alpha uses), and the values are what each of them
set. Krippendorff's alpha is computed at the level the attribute's type
implies, with raw percent agreement beside it, because a reader who has never
met chance correction needs to see what it corrected.

    select, bool   nominal
    number         interval
    multi          MASI distance over the chosen sets
    text           not scored (free text has no shared value space)

An object whose label the attribute does not apply to, or whose annotator left
the attribute blank, contributes no value for it.
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Any, Dict, List

from potato.server_utils.iaa.alpha import krippendorff_alpha

LEVELS = {"select": "nominal", "bool": "nominal", "number": "interval", "multi": "masi"}


def _value(definition: Dict[str, Any], raw: Any):
    """A hashable value at the right level, or None when there is none."""
    if raw is None or raw == "" or raw == []:
        return None
    kind = definition["type"]
    if kind == "multi":
        values = raw if isinstance(raw, list) else [raw]
        return frozenset(str(v) for v in values) or None
    if kind == "number":
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    if kind == "bool":
        if isinstance(raw, str):
            return raw.strip().lower() in ("true", "1", "yes")
        return bool(raw)
    return str(raw)


def _applies(definition: Dict[str, Any], label: Any) -> bool:
    labels = definition.get("labels")
    return labels is None or label in labels


def attribute_agreement(rows: Dict[str, Dict[str, List[dict]]],
                        definitions: List[Dict[str, Any]],
                        threshold: float = 0.5) -> Dict[str, Dict[str, Any]]:
    """Per-attribute agreement over the objects annotators matched.

    Args:
        rows: ``{instance_id: {annotator: [client-shaped objects]}}``, the
            shape `_gather_blobs` produces for an image scheme.
        definitions: normalized attribute definitions
            (`schemas.object_attributes.normalize_attributes`).
        threshold: geometric similarity two shapes need to count as the same
            object.

    Returns:
        ``{attribute name: {"level", "alpha", "percent_agreement",
        "n_objects", "n_annotators", ["note"]}}``. ``note`` says why alpha is
        undefined when it is, which the /admin/iaa table prints in its place.
    """
    from potato.server_utils.iaa import geometry_agreement as ga

    scored = [d for d in definitions if d.get("type") in LEVELS]
    long_format: Dict[str, List[tuple]] = {d["name"]: [] for d in scored}

    for instance_id, per_user in rows.items():
        canonical: Dict[str, List[dict]] = {}
        for annotator, objects in (per_user or {}).items():
            converted = []
            for obj in objects or []:
                shape = ga.canonical_object(obj) if isinstance(obj, dict) else None
                if shape is None:
                    continue
                shape = dict(shape)
                # Carried on the canonical copy so a matched cluster still
                # knows what each annotator set; geometry ignores both keys.
                shape["_attributes"] = obj.get("attributes") or {}
                shape["_label"] = obj.get("label")
                converted.append(shape)
            canonical[annotator] = converted

        for index, cluster in enumerate(ga._matched_clusters(canonical, threshold)):
            if len(cluster) < 2:
                continue
            unit = f"{instance_id}#{index}"
            for definition in scored:
                values = []
                for annotator, shape in cluster.items():
                    if not _applies(definition, shape["_label"]):
                        continue
                    value = _value(definition, shape["_attributes"].get(definition["name"]))
                    if value is not None:
                        values.append((annotator, unit, value))
                if len(values) >= 2:
                    long_format[definition["name"]].extend(values)

    report: Dict[str, Dict[str, Any]] = {}
    for definition in definitions:
        name = definition["name"]
        if definition.get("type") not in LEVELS:
            report[name] = {"level": "not scored",
                            "note": "free-text attributes are not scored"}
            continue
        rows_for = long_format[name]
        level = LEVELS[definition["type"]]
        units: Dict[str, List[Any]] = {}
        for _annotator, unit, value in rows_for:
            units.setdefault(unit, []).append(value)
        pairs = [(a, b) for values in units.values() for a, b in combinations(values, 2)]
        # alpha first: the /admin/iaa table captions the first measure with the
        # group's counts, and alpha is the number the row is for.
        entry: Dict[str, Any] = {
            "alpha": krippendorff_alpha(rows_for, level) if rows_for else float("nan"),
            "percent_agreement": (sum(1 for a, b in pairs if a == b) / len(pairs)
                                  if pairs else float("nan")),
            "n_objects": len(units),
            "n_annotators": len({a for a, _u, _v in rows_for}),
            "level": level,
        }
        if math.isnan(entry["alpha"]):
            if not rows_for:
                entry["note"] = (
                    "no object was matched across annotators with this attribute set "
                    "by two or more of them")
            elif len({v for _a, _u, v in rows_for}) < 2:
                entry["note"] = (
                    "every annotator gave the same value on every matched object, so "
                    "there is no variation for alpha to correct against. Perfect "
                    "agreement, not a failed computation.")
            else:
                entry["note"] = "too few matched objects for alpha to be defined"
        report[name] = entry
    return report
