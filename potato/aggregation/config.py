"""
The ``consensus_aggregation`` config block.

::

    consensus_aggregation:
      agreement_threshold: 0.8   # top answer's share of classifiers to retire an item
      min_classifiers: 2         # fewer classifiers than this -> needs_review
      schemes: [T0, T1]          # optional; default every scheme that can be aggregated
      points:
        eps: 0.02                # neighbourhood radius
        eps_unit: fraction       # "fraction" of the image size, or "pixels"
        min_samples: 2           # points (the point itself included) to form a cluster
      boxes:
        iou_threshold: 0.5       # least IoU between any two boxes in a group

Every key is optional. The exporter's ``--option`` values override the block
(``agreement_threshold=0.9``, ``min_classifiers=3``, ``eps=10``,
``eps_unit=pixels``, ``min_samples=3``, ``iou_threshold=0.6``, ``schemes=T0,T2``).

Standard library only: config_module imports this at load time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

BLOCK = "consensus_aggregation"
EPS_UNITS = ("fraction", "pixels")

#: Defaults, also used by the docs table.
DEFAULTS = {
    "agreement_threshold": 0.8,
    "min_classifiers": 2,
    "points.eps": 0.02,
    "points.eps_unit": "fraction",
    "points.min_samples": 2,
    "boxes.iou_threshold": 0.5,
}

#: ``--option`` name -> dotted key in the block.
OPTION_KEYS = {
    "agreement_threshold": "agreement_threshold",
    "threshold": "agreement_threshold",
    "min_classifiers": "min_classifiers",
    "eps": "points.eps",
    "eps_unit": "points.eps_unit",
    "min_samples": "points.min_samples",
    "iou_threshold": "boxes.iou_threshold",
    "schemes": "schemes",
}

TOP_KEYS = {"agreement_threshold", "min_classifiers", "schemes", "points", "boxes"}
POINT_KEYS = {"eps", "eps_unit", "min_samples"}
BOX_KEYS = {"iou_threshold"}


class ConsensusConfigError(ValueError):
    """A ``consensus_aggregation`` value is unusable. The message names the key."""


@dataclass(frozen=True)
class ConsensusSettings:
    agreement_threshold: float = DEFAULTS["agreement_threshold"]
    min_classifiers: int = DEFAULTS["min_classifiers"]
    schemes: Optional[Tuple[str, ...]] = None
    eps: float = DEFAULTS["points.eps"]
    eps_unit: str = DEFAULTS["points.eps_unit"]
    min_samples: int = DEFAULTS["points.min_samples"]
    iou_threshold: float = DEFAULTS["boxes.iou_threshold"]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "agreement_threshold": self.agreement_threshold,
            "min_classifiers": self.min_classifiers,
            "schemes": list(self.schemes) if self.schemes is not None else None,
            "points": {"eps": self.eps, "eps_unit": self.eps_unit,
                       "min_samples": self.min_samples},
            "boxes": {"iou_threshold": self.iou_threshold},
        }


def _number(value: Any, key: str, *, integer: bool = False) -> float:
    if isinstance(value, bool):
        raise ConsensusConfigError(f"{BLOCK}.{key} must be a number, not {value!r}")
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            raise ConsensusConfigError(
                f"{BLOCK}.{key} must be a number, not {value!r}") from None
    if not isinstance(value, (int, float)):
        raise ConsensusConfigError(f"{BLOCK}.{key} must be a number, not {value!r}")
    if value != value:  # NaN
        raise ConsensusConfigError(f"{BLOCK}.{key} must be a number, not NaN")
    if integer:
        if float(value) != int(value):
            raise ConsensusConfigError(f"{BLOCK}.{key} must be a whole number, not {value!r}")
        return int(value)
    return float(value)


def _schemes(value: Any) -> Optional[Tuple[str, ...]]:
    if value is None:
        return None
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",") if part.strip()]
    if not isinstance(value, (list, tuple)) or not value:
        raise ConsensusConfigError(
            f"{BLOCK}.schemes must be a non-empty list of scheme names")
    names = []
    for name in value:
        if not isinstance(name, str) or not name.strip():
            raise ConsensusConfigError(
                f"{BLOCK}.schemes must list scheme names (strings), not {name!r}")
        names.append(name.strip())
    return tuple(names)


def _flatten(block: Mapping[str, Any]) -> Dict[str, Any]:
    """The block as dotted keys, refusing unknown keys and non-mapping groups."""
    if not isinstance(block, Mapping):
        raise ConsensusConfigError(f"{BLOCK} must be a mapping")
    unknown = sorted(set(block) - TOP_KEYS)
    if unknown:
        raise ConsensusConfigError(
            f"{BLOCK} has unknown key(s) {', '.join(unknown)}; "
            f"known keys are {', '.join(sorted(TOP_KEYS))}")
    flat: Dict[str, Any] = {}
    for key, value in block.items():
        if key in ("points", "boxes"):
            if value is None:
                continue
            if not isinstance(value, Mapping):
                raise ConsensusConfigError(f"{BLOCK}.{key} must be a mapping")
            allowed = POINT_KEYS if key == "points" else BOX_KEYS
            bad = sorted(set(value) - allowed)
            if bad:
                raise ConsensusConfigError(
                    f"{BLOCK}.{key} has unknown key(s) {', '.join(bad)}; "
                    f"known keys are {', '.join(sorted(allowed))}")
            for sub, sub_value in value.items():
                flat[f"{key}.{sub}"] = sub_value
        else:
            flat[key] = value
    return flat


def _build(flat: Mapping[str, Any]) -> ConsensusSettings:
    get = lambda k: flat[k] if flat.get(k) is not None else DEFAULTS.get(k)  # noqa: E731

    threshold = _number(get("agreement_threshold"), "agreement_threshold")
    if not 0.0 < threshold <= 1.0:
        raise ConsensusConfigError(
            f"{BLOCK}.agreement_threshold must be greater than 0 and at most 1, "
            f"not {threshold}")
    min_classifiers = _number(get("min_classifiers"), "min_classifiers", integer=True)
    if min_classifiers < 1:
        raise ConsensusConfigError(
            f"{BLOCK}.min_classifiers must be at least 1, not {min_classifiers}")
    eps = _number(get("points.eps"), "points.eps")
    unit = get("points.eps_unit")
    if not isinstance(unit, str) or unit.strip().lower() not in EPS_UNITS:
        raise ConsensusConfigError(
            f"{BLOCK}.points.eps_unit must be one of {', '.join(EPS_UNITS)}, not {unit!r}")
    unit = unit.strip().lower()
    if eps <= 0:
        raise ConsensusConfigError(f"{BLOCK}.points.eps must be greater than 0, not {eps}")
    if unit == "fraction" and eps > 1:
        raise ConsensusConfigError(
            f"{BLOCK}.points.eps is {eps} with eps_unit 'fraction', which is more than "
            "the whole image; give a fraction such as 0.02, or set eps_unit: pixels")
    min_samples = _number(get("points.min_samples"), "points.min_samples", integer=True)
    if min_samples < 1:
        raise ConsensusConfigError(
            f"{BLOCK}.points.min_samples must be at least 1, not {min_samples}")
    iou = _number(get("boxes.iou_threshold"), "boxes.iou_threshold")
    if not 0.0 < iou <= 1.0:
        raise ConsensusConfigError(
            f"{BLOCK}.boxes.iou_threshold must be greater than 0 and at most 1, not {iou}")
    return ConsensusSettings(
        agreement_threshold=threshold, min_classifiers=int(min_classifiers),
        schemes=_schemes(flat.get("schemes")), eps=eps, eps_unit=unit,
        min_samples=int(min_samples), iou_threshold=iou)


def parse_consensus_config(config: Optional[Mapping[str, Any]],
                           options: Optional[Mapping[str, Any]] = None) -> ConsensusSettings:
    """Settings from the config block, with exporter options laid over it.

    Raises:
        ConsensusConfigError: a value is out of range or of the wrong type, or
            an option or key is unknown.
    """
    block = (config or {}).get(BLOCK) if isinstance(config, Mapping) else None
    flat = _flatten(block) if block is not None else {}
    for name, value in (options or {}).items():
        key = OPTION_KEYS.get(str(name).strip())
        if key is None:
            raise ConsensusConfigError(
                f"unknown consensus option {name!r}; known options are "
                f"{', '.join(sorted(OPTION_KEYS))}")
        flat[key] = value
    return _build(flat)


def validate_consensus_aggregation_config(config_data: Mapping[str, Any],
                                          error_cls: type = ConsensusConfigError) -> None:
    """Config-load check. Raises ``error_cls`` naming the key on a bad value."""
    if not isinstance(config_data, Mapping) or config_data.get(BLOCK) is None:
        return
    try:
        settings = parse_consensus_config(config_data)
    except ConsensusConfigError as exc:
        raise error_cls(str(exc)) from None
    if settings.schemes:
        declared = {s.get("name") for s in config_data.get("annotation_schemes") or []
                    if isinstance(s, Mapping)}
        missing = [n for n in settings.schemes if n not in declared]
        if missing and declared:
            raise error_cls(
                f"{BLOCK}.schemes names scheme(s) the config does not declare: "
                f"{', '.join(missing)}")
