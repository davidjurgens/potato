"""
Per-object attributes: typed fields an annotator fills in for each shape.

A box labelled `car` is often only half the answer. Autonomous-driving and
detection datasets record occlusion, truncation, whether the object is parked,
how many people are in a vehicle -- properties of that one object, not of the
image. Every other CV tool has them; Potato's shapes carried an `attributes`
dict only when an importer filled it.

This module validates the `attributes:` block of a scheme and normalizes it
into the shape the browser panel reads. The same definitions drive agreement
over attributes in :mod:`potato.server_utils.iaa.attribute_agreement`.

    attributes:
      - name: occluded
        type: select            # select | multi | text | number | bool
        options: [none, partial, heavy]
        labels: [car, pedestrian]   # omit = every label
        required: true
        default: none
        show_if: {attribute: truncated, equals: true}
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

TYPES = ("select", "multi", "text", "number", "bool")

#: Keys an attribute definition may carry. Anything else is a typo, and a
#: typo here (`option:` for `options:`) would otherwise render an empty select.
KEYS = {"name", "type", "options", "labels", "required", "default", "show_if",
        "description", "min", "max"}


class AttributeConfigError(ValueError):
    """An `attributes:` block that cannot be rendered as written."""


def normalize_attributes(raw: Any, label_names: List[str],
                         where: str) -> List[Dict[str, Any]]:
    """Validate an `attributes:` block and return the normalized definitions.

    Raises AttributeConfigError with a message naming the scheme and the
    attribute, so a config error points at the line to fix.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise AttributeConfigError(f"{where}.attributes must be a list of attribute definitions")

    defs: List[Dict[str, Any]] = []
    seen = set()
    for index, entry in enumerate(raw):
        at = f"{where}.attributes[{index}]"
        if not isinstance(entry, dict):
            raise AttributeConfigError(f"{at} must be a mapping with at least name and type")
        unknown = sorted(set(entry) - KEYS)
        if unknown:
            import difflib
            hints = [f"'{k}' -> '{m[0]}'" for k in unknown
                     for m in [difflib.get_close_matches(str(k), KEYS, n=1, cutoff=0.6)] if m]
            hint = f" Did you mean: {', '.join(hints)}?" if hints else ""
            raise AttributeConfigError(
                f"{at} has unknown key(s) {', '.join(unknown)}.{hint} "
                f"Accepted: {', '.join(sorted(KEYS))}")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise AttributeConfigError(f"{at} needs a name")
        if name in seen:
            raise AttributeConfigError(f"{at}: attribute '{name}' is defined twice")
        seen.add(name)
        at = f"{where}.attributes[{name}]"

        kind = entry.get("type", "select")
        if kind not in TYPES:
            raise AttributeConfigError(f"{at}.type must be one of {', '.join(TYPES)}, not '{kind}'")

        out: Dict[str, Any] = {"name": name, "type": kind,
                               "required": bool(entry.get("required", False))}
        if entry.get("description"):
            out["description"] = str(entry["description"])

        if kind in ("select", "multi"):
            options = entry.get("options")
            if not isinstance(options, list) or not options:
                raise AttributeConfigError(f"{at} is a {kind} and needs a non-empty options list")
            # YAML reads `[yes, no]` as booleans; store what the annotator sees.
            out["options"] = [_option_text(o) for o in options]
        elif entry.get("options") is not None:
            raise AttributeConfigError(f"{at}: options only apply to select and multi attributes")

        if kind == "number":
            for bound in ("min", "max"):
                if entry.get(bound) is not None:
                    if not isinstance(entry[bound], (int, float)) or isinstance(entry[bound], bool):
                        raise AttributeConfigError(f"{at}.{bound} must be a number")
                    out[bound] = entry[bound]

        labels = entry.get("labels")
        if labels is not None:
            if not isinstance(labels, list) or not labels:
                raise AttributeConfigError(f"{at}.labels must be a non-empty list of label names")
            labels = [str(label) for label in labels]
            missing = [label for label in labels if label not in label_names]
            if missing:
                raise AttributeConfigError(
                    f"{at}.labels names {', '.join(missing)}, which "
                    f"{'is' if len(missing) == 1 else 'are'} not among the scheme's labels "
                    f"({', '.join(label_names)})")
            out["labels"] = labels

        if "default" in entry and entry["default"] is not None:
            out["default"] = _check_value(entry["default"], out, f"{at}.default")

        out["_show_if"] = entry.get("show_if")
        defs.append(out)

    # show_if refers to another attribute, so it is checked once all are known.
    by_name = {d["name"]: d for d in defs}
    for d in defs:
        condition = d.pop("_show_if")
        if condition is None:
            continue
        at = f"{where}.attributes[{d['name']}].show_if"
        if not isinstance(condition, dict) or "attribute" not in condition or "equals" not in condition:
            raise AttributeConfigError(f"{at} must be {{attribute: <name>, equals: <value>}}")
        target = by_name.get(condition["attribute"])
        if target is None or target is d:
            raise AttributeConfigError(
                f"{at}.attribute must name another attribute of this scheme, "
                f"not '{condition['attribute']}'")
        d["show_if"] = {"attribute": target["name"],
                        "equals": _check_value(condition["equals"], target, f"{at}.equals")}
    return defs


def _option_text(option: Any) -> str:
    if option is True:
        return "yes"
    if option is False:
        return "no"
    return str(option)


def _check_value(value: Any, definition: Dict[str, Any], at: str) -> Any:
    kind = definition["type"]
    if kind == "bool":
        if not isinstance(value, bool):
            raise AttributeConfigError(f"{at} must be true or false for a bool attribute")
        return value
    if kind == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise AttributeConfigError(f"{at} must be a number")
        return value
    if kind == "select":
        text = _option_text(value)
        if text not in definition["options"]:
            raise AttributeConfigError(f"{at} '{text}' is not one of the options "
                                       f"({', '.join(definition['options'])})")
        return text
    if kind == "multi":
        values = value if isinstance(value, list) else [value]
        texts = [_option_text(v) for v in values]
        bad = [t for t in texts if t not in definition["options"]]
        if bad:
            raise AttributeConfigError(f"{at} names {', '.join(bad)}, not among the options")
        return texts
    return str(value)


def applies_to(definition: Dict[str, Any], label: Optional[str]) -> bool:
    labels = definition.get("labels")
    return labels is None or label in labels
