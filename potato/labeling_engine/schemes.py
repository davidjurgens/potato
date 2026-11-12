"""
What the engine needs to know about an annotation scheme, and label matching.

``SchemeSpec`` is built once per scheme from the config and passed to sources
and families. ``normalize_label`` is the one label matcher: a model's reply
"Positive " or "POSITIVE" is the scheme's "positive", and anything that is not
one of the scheme's labels is not silently mapped to the nearest one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .model.records import content_hash

#: Annotation types whose answer is one label from a fixed list.
ONE_OF_N = ("radio", "select")
#: Ordinal one-of-N: the labels are scale points in order.
ORDINAL = ("likert",)


def label_names(scheme: Dict[str, Any]) -> List[str]:
    """The scheme's label names in order. Likert scales get "1".."size"."""
    out = []
    for label in scheme.get("labels") or []:
        if isinstance(label, str):
            out.append(label)
        elif isinstance(label, dict) and label.get("name") is not None:
            out.append(str(label["name"]))
        elif label is not None:
            out.append(str(label))
    if not out and scheme.get("annotation_type") == "likert":
        try:
            size = int(scheme.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        out = [str(i) for i in range(1, size + 1)]
    return out


def label_descriptions(scheme: Dict[str, Any]) -> Dict[str, str]:
    out = {}
    for label in scheme.get("labels") or []:
        if isinstance(label, dict) and label.get("name") is not None:
            desc = label.get("tooltip") or label.get("description")
            if desc:
                out[str(label["name"])] = str(desc)
    return out


def normalize_label(value: Any, valid: Sequence[str]) -> Optional[str]:
    """Return the label in ``valid`` that ``value`` names, or None.

    Matching ignores case, surrounding whitespace and quotes, and a trailing
    period. It never picks the nearest label for an answer that is not one:
    a model that answers "neutral" for a positive/negative scheme abstained,
    and counting it as either label would make its errors invisible.
    """
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip().strip("\"'`").strip()
    if text.endswith(".") and text[:-1] in valid:
        text = text[:-1]
    if text in valid:
        return text
    low = text.lower().rstrip(".")
    for v in valid:
        if str(v).lower().strip() == low:
            return v
    return None


@dataclass
class SchemeSpec:
    name: str
    annotation_type: str
    labels: List[str] = field(default_factory=list)
    descriptions: Dict[str, str] = field(default_factory=dict)
    description: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_scheme(cls, scheme: Dict[str, Any]) -> "SchemeSpec":
        return cls(
            name=str(scheme.get("name", "")),
            annotation_type=str(scheme.get("annotation_type", "")),
            labels=label_names(scheme),
            descriptions=label_descriptions(scheme),
            description=str(scheme.get("description") or ""),
            raw=dict(scheme),
        )

    @property
    def is_one_of_n(self) -> bool:
        return self.annotation_type in ONE_OF_N + ORDINAL or (
            self.annotation_type == "multiselect"
            and self.raw.get("max_selections") == 1)

    def schema_hash(self) -> str:
        """Hash of everything about the scheme a model sees.

        Part of every source version, so editing the labels or the
        description makes a new version and stales certificates on the old.
        """
        return content_hash({
            "name": self.name, "type": self.annotation_type, "labels": self.labels,
            "descriptions": self.descriptions, "description": self.description,
            "size": self.raw.get("size"), "min_label": self.raw.get("min_label"),
            "max_label": self.raw.get("max_label"),
        })[:16]


def scheme_specs(config: Dict[str, Any],
                 names: Optional[Sequence[str]] = None) -> List[SchemeSpec]:
    specs = [SchemeSpec.from_scheme(s) for s in config.get("annotation_schemes") or []
             if isinstance(s, dict)]
    if names is not None:
        wanted = set(names)
        specs = [s for s in specs if s.name in wanted]
    return specs
