"""
Agreement on volume_annotation masks: 3D Dice per label.

For each item two or more people labelled, every pair of annotators is
compared label by label over the whole volume: Dice = 2|A and B| / (|A|+|B|).
A pair where neither painted the label says nothing about that label and is
left out, rather than counted as perfect agreement. Boxes and polygons are
not scored here.
"""

from __future__ import annotations

import json
from itertools import combinations
from typing import Any, Dict, List, Optional


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
    by_label = {name: (round(sum(v) / len(v), 4) if v else None)
                for name, v in per_label.items()}
    scored = [v for v in by_label.values() if v is not None]
    return {
        "mean_dice": round(sum(scored) / len(scored), 4) if scored else None,
        "dice_by_label": by_label,
        "n_pairs_by_label": {name: len(v) for name, v in per_label.items()},
        "n_items": items_scored,
    }
