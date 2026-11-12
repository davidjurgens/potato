"""
Calibration-sample selection.

Given the LLM-labeled instance ids, pick the subset that human(s) will
*blind*-label for calibration. Mirrors the deterministic stratify+seed logic of
``server_utils/overlap_sampler.py`` but returns a plain id list (we don't want
the overlap mechanism's per-item annotator-cap stamping here).

Strategies:
- random     : uniform random sample of ``sample_size`` ids
- stratified : proportional allocation across strata defined by an item-data
               field (or, for the calibration use-case, the modal LLM label)
- all        : every labeled id (ignores sample_size)
"""

import logging
import random as _random
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def select_calibration_sample(
    instance_ids: List[str],
    sampling_cfg,                                   # SamplingConfig
    stratum_of: Optional[Callable[[str], Any]] = None,
) -> List[str]:
    """Return a deterministic subset of ``instance_ids`` to show humans.

    Args:
        instance_ids: candidate ids (the LLM-labeled items).
        sampling_cfg: a SamplingConfig (strategy / sample_size / seed / stratify_by).
        stratum_of: optional callable mapping an id -> a stratum key. Required
            for the 'stratified' strategy; ignored otherwise. (The manager
            wires this to either an item-data field or the modal LLM label.)
    """
    ids = sorted(set(instance_ids))
    if not ids:
        return []

    strategy = sampling_cfg.strategy
    if strategy == "all":
        return ids

    sample_size = min(sampling_cfg.sample_size, len(ids))
    seed = sampling_cfg.seed

    if strategy == "random" or stratum_of is None:
        if strategy == "stratified" and stratum_of is None:
            logger.warning("judge_calibration: stratified sampling requested but no "
                           "stratum mapping available; falling back to random")
        rng = _random.Random(seed)
        shuffled = list(ids)
        rng.shuffle(shuffled)
        return sorted(shuffled[:sample_size])

    # stratified: proportional allocation, deterministic per-stratum shuffle.
    strata: Dict[Any, List[str]] = defaultdict(list)
    for iid in ids:
        key = stratum_of(iid)
        strata[key if key is not None else "__none__"].append(iid)

    selected: List[str] = []
    total = len(ids)
    for key in sorted(strata.keys(), key=str):
        bucket = sorted(strata[key])
        rng_local = _random.Random(f"{seed}:{key}")
        rng_local.shuffle(bucket)
        # proportional quota (at least 1 per non-empty stratum)
        quota = max(1, round(sample_size * len(bucket) / total))
        selected.extend(bucket[:quota])

    # Trim/pad to exactly sample_size deterministically.
    selected = sorted(set(selected))
    if len(selected) > sample_size:
        rng = _random.Random(seed)
        rng.shuffle(selected)
        selected = sorted(selected[:sample_size])
    return selected
