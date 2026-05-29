"""
Overlap sampling for heterogeneous annotator coverage.

Given the ``num_annotators_per_item.overlap_sample`` config block, selects a
deterministic fraction of items to receive a raised annotator cap. The cap
override is written onto each sampled item's metadata so the centralized
``ItemStateManager._get_annotator_cap_for_item`` helper picks it up.

This module is called once after all items have been loaded.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

import logging
import random as _random

logger = logging.getLogger(__name__)


_METADATA_KEY = "required_annotations"


def apply_overlap_sample(item_state_manager, config: dict) -> Dict[str, int]:
    """
    Stamp ``required_annotations`` on a deterministic sample of items.

    Returns a mapping of sampled instance_id -> assigned cap, for reporting.
    Items whose existing metadata already carries ``required_annotations``
    (e.g., from a previous load with persisted state) are not overwritten.
    """
    nap = config.get("num_annotators_per_item")
    if not isinstance(nap, dict):
        return {}
    overlap = nap.get("overlap_sample")
    if not overlap:
        return {}

    fraction = float(overlap["fraction"])
    count = int(overlap["count"])
    stratify_by = overlap.get("stratify_by")
    seed = int(overlap.get("seed", item_state_manager.random_seed))
    rng = _random.Random(seed)

    all_ids = list(item_state_manager.instance_id_to_instance.keys())
    if not all_ids:
        return {}

    # Build strata
    strata: Dict[Optional[str], List[str]] = defaultdict(list)
    if stratify_by:
        for iid in all_ids:
            item = item_state_manager.instance_id_to_instance[iid]
            data = item.get_data() if hasattr(item, "get_data") else {}
            key = data.get(stratify_by) if isinstance(data, dict) else None
            # Also accept the indexed category if it matches
            if key is None and hasattr(item_state_manager, "instance_id_to_categories"):
                cats = item_state_manager.instance_id_to_categories.get(iid)
                if cats:
                    key = sorted(cats)[0]
            strata[key if key is not None else "__uncategorized__"].append(iid)
    else:
        strata[None] = list(all_ids)

    sampled: Dict[str, int] = {}
    for key, ids in strata.items():
        if not ids:
            continue
        # Deterministic ordering across runs
        ids_sorted = sorted(ids)
        rng_local = _random.Random(f"{seed}:{key}" if key is not None else seed)
        rng_local.shuffle(ids_sorted)
        target = max(1, int(round(len(ids_sorted) * fraction)))
        for iid in ids_sorted[:target]:
            item = item_state_manager.instance_id_to_instance[iid]
            # Don't clobber an existing per-item override (operator may have
            # set one via item_data; respect that authority).
            if item.get_metadata(_METADATA_KEY) is not None:
                continue
            item.add_metadata(_METADATA_KEY, count)
            sampled[iid] = count

    if sampled:
        logger.info(
            "Overlap sample: %d / %d items raised to %d annotators (fraction=%s, stratify_by=%s, seed=%d)",
            len(sampled), len(all_ids), count, fraction, stratify_by, seed,
        )
    return sampled
