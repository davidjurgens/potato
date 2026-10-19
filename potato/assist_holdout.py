"""
A randomized no-assistance comparison group for AI-assisted studies.

Every assistance surface Potato has -- hints, option highlights,
pre-annotations, visual AI, the inline judge, critique, chat -- shows the
annotator a model's view before they answer, and an answer given after a
suggestion is pulled toward it. Whether it was pulled, and how far, can only be
measured against answers given without one, by the same kind of annotator on
the same kind of item.

`ai_support.holdout.fraction` withholds every surface from a random share of
(annotator, item) pairs. The draw is a salted hash, so it is the same on every
request and after a restart, and it is per pair rather than per item: each
item gets some assisted and some unassisted annotators, so the two groups can
be compared item by item. The comparison is by assignment, not by whether an
annotator chose to open a hint, which would confound the suggestion with the
people who ask for one.

The labeling engine already does this for its own calibration requests;
`assist_withheld` is the union of the two, and it is what the assistance
routes and the page renderer consult.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional, Tuple


def holdout_settings(config: Dict[str, Any]) -> Tuple[float, str]:
    """(fraction, salt) from ``ai_support.holdout``; fraction 0 when unset."""
    block = ((config or {}).get("ai_support") or {}).get("holdout") or {}
    try:
        fraction = float(block.get("fraction", 0) or 0)
    except (TypeError, ValueError):
        fraction = 0.0
    return max(0.0, min(1.0, fraction)), str(block.get("salt", "") or "")


def holdout_draw(salt: str, user_id: str, instance_id: str) -> float:
    """A deterministic number in [0, 1) for this annotator and item."""
    digest = hashlib.blake2b(f"{salt}:{user_id}:{instance_id}".encode("utf-8"),
                             digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2 ** 64


def is_held_out(config: Dict[str, Any], user_id: Optional[str],
                instance_id: Optional[str]) -> bool:
    """Whether this annotator gets no AI assistance on this item."""
    if not user_id or instance_id is None:
        return False
    fraction, salt = holdout_settings(config)
    if fraction <= 0:
        return False
    return holdout_draw(salt, str(user_id), str(instance_id)) < fraction


def assist_withheld(config: Dict[str, Any], user_id: Optional[str],
                    instance_id: Optional[str]) -> bool:
    """Held out by the study's comparison group, or blind for the engine."""
    if is_held_out(config, user_id, instance_id):
        return True
    if (config or {}).get("labeling_engine", {}).get("enabled"):
        from potato.labeling_engine.integration.hooks import is_blind
        return bool(is_blind(user_id, instance_id))
    return False


def strip_holdout_fields(config: Dict[str, Any], record: Any, user_id: Optional[str],
                         instance_id: Optional[str]) -> Any:
    """``record`` without its pre-annotation field for a held-out pair.

    The page renders pre-annotations server-side, but the item record also
    reaches the browser (the instance-data routes, the page's item JSON), and a
    prediction left in it could be read off the page source.
    """
    if not isinstance(record, dict) or not is_held_out(config, user_id, instance_id):
        return record
    block = (config or {}).get("pre_annotation") or {}
    field = str(block.get("field") or "predictions") if isinstance(block, dict) else "predictions"
    if field not in record:
        return record
    return {k: v for k, v in record.items() if k != field}
