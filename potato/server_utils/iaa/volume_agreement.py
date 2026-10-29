"""
Agreement on volume_annotation masks: 3D Dice per label.

For each item two or more people labelled, every pair of annotators is
compared label by label over the whole volume: Dice = 2|A and B| / (|A|+|B|).
A pair where neither painted the label says nothing about that label and is
left out, rather than counted as perfect agreement. Boxes are not scored
here; a closed polygon is painted into the mask and is.

With three or more annotators on an item, STAPLE (Warfield et al. 2004) also
estimates each annotator's sensitivity and specificity per label against the
consensus. With two it cannot tell who is right, so it is not run. Large
volumes are cropped to the box around every annotator's voxels of the label
first, so specificity there is over that box, not the whole scan.
"""

from __future__ import annotations

import json
from itertools import combinations
from typing import Any, Dict, List, Optional

#: Voxels above which STAPLE runs on the labels' bounding box only. EM over a
#: whole CT (512 x 512 x 300 is 79M voxels) per label would hang the page.
STAPLE_FULL_VOLUME_LIMIT = 2_000_000


def _annotation(value: Any) -> Optional[Dict[str, Any]]:
    if isinstance(value, dict) and "_data" in value:
        value = value["_data"]
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) and "masks" in value else None


def volume_report(rows: Dict[str, Dict[str, Any]], scheme: Dict[str, Any]) -> Dict[str, Any]:
    from potato.media.volume_masks import dice, label_volume

    names: List[str] = []
    for item in scheme.get("labels") or []:
        name = item if isinstance(item, str) else (item or {}).get("name")
        if name:
            names.append(str(name))
    per_label: Dict[str, List[float]] = {name: [] for name in names}
    # label -> {"sensitivity"/"specificity": {uid: [values]}, "items": n}
    staple_rates: Dict[str, Dict[str, Any]] = {}
    items_scored = 0
    for _iid, per_user in rows.items():
        parsed = {uid: a for uid, a in ((u, _annotation(v)) for u, v in per_user.items()) if a}
        if len(parsed) < 2:
            continue
        shapes = {tuple(a.get("shape") or ()) for a in parsed.values()}
        if len(shapes) != 1 or len(next(iter(shapes))) != 3:
            continue                    # drawn on different versions of the file
        shape = next(iter(shapes))
        items_scored += 1
        volumes = {uid: {name: label_volume(a, shape, name) for name in names}
                   for uid, a in parsed.items()}
        for a, b in combinations(sorted(volumes), 2):
            for name in names:
                score = dice(volumes[a][name], volumes[b][name])
                if score is not None:
                    per_label[name].append(score)
        if len(volumes) >= 3:
            for name in names:
                _add_staple(staple_rates.setdefault(name, {}),
                            {uid: v[name] for uid, v in volumes.items()})
    by_label = {name: (round(sum(v) / len(v), 4) if v else None)
                for name, v in per_label.items()}
    scored = [v for v in by_label.values() if v is not None]
    report = {
        "mean_dice": round(sum(scored) / len(scored), 4) if scored else None,
        "dice_by_label": by_label,
        "n_pairs_by_label": {name: len(v) for name, v in per_label.items()},
        "n_items": items_scored,
    }
    staple_report = {
        name: {
            "sensitivity": {u: round(sum(v) / len(v), 4)
                            for u, v in sorted(rates["sensitivity"].items())},
            "specificity": {u: round(sum(v) / len(v), 4)
                            for u, v in sorted(rates["specificity"].items())},
            "n_items": rates["items"],
        }
        for name, rates in staple_rates.items() if rates.get("items")
    }
    if staple_report:
        report["staple"] = staple_report
    return report


def _add_staple(rates: Dict[str, Any], masks: Dict[str, Any]) -> None:
    """Run STAPLE on one item's masks for one label and accumulate the rates."""
    import numpy as np
    from potato.staple import staple

    stack = [np.asarray(m, dtype=bool) for m in masks.values()]
    union = np.logical_or.reduce(stack)
    if not union.any():
        return                          # nobody painted the label here
    if union.size > STAPLE_FULL_VOLUME_LIMIT:
        idx = np.nonzero(union)
        box = tuple(slice(int(a.min()), int(a.max()) + 1) for a in idx)
        masks = {uid: np.asarray(m, dtype=bool)[box] for uid, m in masks.items()}
    result = staple({uid: m.astype(np.uint8) for uid, m in masks.items()})
    rates.setdefault("sensitivity", {})
    rates.setdefault("specificity", {})
    for uid in masks:
        rates["sensitivity"].setdefault(uid, []).append(float(result.sensitivity[uid]))
        rates["specificity"].setdefault(uid, []).append(float(result.specificity[uid]))
    rates["items"] = rates.get("items", 0) + 1
