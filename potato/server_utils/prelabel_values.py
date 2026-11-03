"""Model predictions for hidden-input and slider schemes, as input values.

The annotation page restores a returning annotator's answer by walking the
DOM and filling inputs named ``<scheme>:::<label>``. A prelabel takes the
same path: ``render_page_with_annotations`` puts ``{label: value}`` under the
scheme and the walk fills the input and marks it server-set, which is what
each widget's restore code reads.

This module turns a trained model's payload into those values for the types
whose answer is one or a few hidden inputs: a ranking's order, a BWS best
and worst, a soft label's sliders, an interlinear gloss and a conversation
tree. Pairwise scale needs the annotator's presentation order, so the page
handles it itself.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["PRELABEL_TYPES", "prelabel_values"]

PRELABEL_TYPES = ("ranking", "bws", "soft_label", "interlinear_gloss",
                  "tree_annotation")


def _label_names(scheme: Dict[str, Any]) -> List[str]:
    return [str(l.get("name") if isinstance(l, dict) else l)
            for l in scheme.get("labels") or []]


def _order(payload: Any) -> List[str]:
    if isinstance(payload, dict):
        payload = payload.get("order", payload.get("rank_order"))
    if isinstance(payload, str):
        payload = payload.split(",")
    return [str(p) for p in payload] if isinstance(payload, list) else []


def _integer_masses(shares: Dict[str, float], labels: List[str],
                    total: int) -> Dict[str, int]:
    """Shares as whole slider values summing to *total*, by largest
    remainder, so the sliders read as the model's distribution and the
    widget's sum check passes."""
    weights = {label: max(0.0, float(shares.get(label, 0.0) or 0.0))
               for label in labels}
    whole = sum(weights.values())
    if whole <= 0:
        return {}
    exact = {label: total * w / whole for label, w in weights.items()}
    masses = {label: int(v) for label, v in exact.items()}
    short = total - sum(masses.values())
    for label in sorted(labels, key=lambda l: exact[l] - masses[l],
                        reverse=True)[:short]:
        masses[label] += 1
    return masses


def prelabel_values(scheme: Dict[str, Any], payload: Any) -> Optional[Dict[str, str]]:
    """``{label_name: input value}`` for one scheme's prediction, or None
    when the payload does not fit the scheme (logged)."""
    atype = scheme.get("annotation_type")
    name = str(scheme.get("name") or "")
    if atype == "ranking":
        known = _label_names(scheme)
        order = [o for o in _order(payload) if o in known]
        # The widget shows every option; a partial order would drop some.
        if sorted(order) != sorted(known):
            logger.warning("Ranking prediction for %r does not order every "
                           "option; not shown", name)
            return None
        return {"rank_order": ",".join(order)}
    if atype == "bws":
        if not isinstance(payload, dict):
            return None
        best, worst = str(payload.get("best") or ""), str(payload.get("worst") or "")
        if not best or not worst or best == worst:
            return None
        return {"best": best, "worst": worst}
    if atype == "soft_label":
        shares = payload.get("distribution", payload) if isinstance(payload, dict) else None
        if not isinstance(shares, dict):
            return None
        try:
            total = int(scheme.get("total", 100) or 100)
        except (TypeError, ValueError):
            total = 100
        masses = _integer_masses(shares, _label_names(scheme), total)
        return {label: str(v) for label, v in masses.items()} or None
    if atype == "interlinear_gloss":
        if not isinstance(payload, dict) or not isinstance(payload.get("words"), list):
            return None
        return {name: json.dumps({"words": payload["words"],
                                  "translation": str(payload.get("translation") or "")},
                                 ensure_ascii=False)}
    if atype == "tree_annotation":
        if not isinstance(payload, dict):
            return None
        values = {}
        if isinstance(payload.get("path"), list) and payload["path"]:
            values["selected_path"] = json.dumps([str(p) for p in payload["path"]])
        if isinstance(payload.get("nodes"), dict) and payload["nodes"]:
            values["node_annotations"] = json.dumps(payload["nodes"])
        return values or None
    return None
