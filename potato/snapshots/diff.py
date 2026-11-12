"""
What changed between two snapshots.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List


def _by_key(records: List[dict]) -> Dict[tuple, Any]:
    return {(r["annotator"], r["item"], r["schema"]): r["value"] for r in records}


def diff_snapshots(old: Dict[str, Any], new: Dict[str, Any], limit: int = 20) -> Dict[str, Any]:
    """Compare two loaded snapshots (``store.load_snapshot``).

    Annotations are compared per (annotator, item, scheme): added, removed, or
    changed value. Agreement is compared per scheme by alpha.
    """
    old_items, new_items = set(old["items"]), set(new["items"])
    a, b = _by_key(old["records"]), _by_key(new["records"])
    added = sorted(k for k in b if k not in a)
    removed = sorted(k for k in a if k not in b)
    changed = sorted(k for k in a if k in b and a[k] != b[k])

    def rows(keys):
        return [{"annotator": u, "item": i, "schema": s} for u, i, s in keys[:limit]]

    old_alpha = {s["name"]: s.get("alpha") for s in (old.get("agreement") or {}).get("schemes", [])}
    new_alpha = {s["name"]: s.get("alpha") for s in (new.get("agreement") or {}).get("schemes", [])}
    agreement = []
    for name in sorted(set(old_alpha) | set(new_alpha)):
        before, after = old_alpha.get(name), new_alpha.get(name)
        delta = (after - before) if isinstance(before, (int, float)) and isinstance(after, (int, float)) else None
        agreement.append({"scheme": name, "alpha_before": before, "alpha_after": after,
                          "change": delta})

    old_people = {u for u, _i, _s in a}
    new_people = {u for u, _i, _s in b}
    return {
        "from": old["id"], "to": new["id"],
        "same_content": old["content_hash"] == new["content_hash"],
        "items": {"added": sorted(new_items - old_items)[:limit],
                  "removed": sorted(old_items - new_items)[:limit],
                  "n_added": len(new_items - old_items),
                  "n_removed": len(old_items - new_items)},
        "annotators": {"added": sorted(new_people - old_people),
                       "removed": sorted(old_people - new_people)},
        "annotations": {"n_added": len(added), "n_removed": len(removed),
                        "n_changed": len(changed), "added": rows(added),
                        "removed": rows(removed), "changed": rows(changed)},
        "agreement": agreement,
        "config_changed": (old.get("config_sha256") != new.get("config_sha256")
                           if old.get("config_sha256") and new.get("config_sha256") else None),
    }


def format_diff(result: Dict[str, Any]) -> str:
    lines = [f"{result['from']} -> {result['to']}"]
    if result["same_content"]:
        lines.append("Same content.")
        return "\n".join(lines)
    items, people, ann = result["items"], result["annotators"], result["annotations"]
    if result.get("config_changed"):
        lines.append("Config: changed")
    lines.append(f"Items: +{items['n_added']} -{items['n_removed']}")
    if people["added"] or people["removed"]:
        lines.append(f"Annotators: +{len(people['added'])} {', '.join(people['added'])}".rstrip()
                     + (f"; -{len(people['removed'])} {', '.join(people['removed'])}" if people["removed"] else ""))
    lines.append(f"Annotations: +{ann['n_added']} -{ann['n_removed']} changed {ann['n_changed']}")
    for kind in ("changed", "added", "removed"):
        for row in ann[kind]:
            lines.append(f"  {kind:<8} {row['annotator']}  {row['item']}  {row['schema']}")
    for row in result["agreement"]:
        def fmt(v):
            return "n/a" if v is None else f"{v:.3f}"
        change = "" if row["change"] is None else f" ({row['change']:+.3f})"
        lines.append(f"Alpha {row['scheme']}: {fmt(row['alpha_before'])} -> {fmt(row['alpha_after'])}{change}")
    return "\n".join(lines)


def to_json(result: Dict[str, Any]) -> str:
    return json.dumps(result, indent=2, ensure_ascii=False)
