"""
Best-Worst Scaling Tuple Generator

Generates tuples of K items from a pool for Best-Worst Scaling annotation.
Each tuple is a synthetic instance containing references to K original pool items.
Annotators select the "best" and "worst" item from each tuple.

Key features:
- Reproducible via random seed
- Configurable tuple size and number of tuples
- Auto-calculates num_tuples based on Louviere's guideline (2 * tuple_size appearances per item)
- Each item appears in multiple tuples; no item repeats within a single tuple
"""

import logging
import math
import random
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Position labels: A, B, C, ... Z
POSITION_LABELS = [chr(ord('A') + i) for i in range(26)]


class BwsTupleGenerator:
    """Generate BWS tuples from a pool of items."""

    def __init__(
        self,
        pool_items: List[Dict[str, Any]],
        id_key: str,
        text_key: str,
        tuple_size: int = 4,
        num_tuples: Optional[int] = None,
        seed: int = 42,
        min_item_appearances: Optional[int] = None,
    ):
        self.pool_items = pool_items
        self.id_key = id_key
        self.text_key = text_key
        self.tuple_size = tuple_size
        self.seed = seed
        self.min_item_appearances = min_item_appearances
        self._num_tuples = num_tuples

    def validate(self):
        """Validate configuration before generation."""
        if self.tuple_size < 2:
            raise ValueError(f"tuple_size must be >= 2, got {self.tuple_size}")
        if self.tuple_size > len(self.pool_items):
            raise ValueError(
                f"tuple_size ({self.tuple_size}) exceeds pool size ({len(self.pool_items)})"
            )
        if self._num_tuples is not None and self._num_tuples < 1:
            raise ValueError(f"num_tuples must be >= 1, got {self._num_tuples}")

    def _calculate_num_tuples(self) -> int:
        """Auto-calculate number of tuples.

        Uses Louviere's guideline: each item should appear at least
        2 * tuple_size times across all tuples.
        """
        min_appearances = self.min_item_appearances
        if min_appearances is None:
            min_appearances = 2 * self.tuple_size

        pool_size = len(self.pool_items)
        # Each tuple uses tuple_size items, so on average each item appears
        # (num_tuples * tuple_size) / pool_size times.
        # We need: (num_tuples * tuple_size) / pool_size >= min_appearances
        num_tuples = math.ceil(pool_size * min_appearances / self.tuple_size)
        return max(num_tuples, 1)

    def generate(self) -> List[Dict[str, Any]]:
        """Generate tuple instances from pool items.

        Returns list of synthetic item dicts, each with:
        - id_key: "bws_tuple_001"
        - "_bws_items": list of {source_id, text, position} dicts
        - "_bws_tuple_size": int
        - text_key: "" (empty — BWS JS handles display)
        """
        self.validate()

        num_tuples = self._num_tuples if self._num_tuples else self._calculate_num_tuples()
        rng = random.Random(self.seed)

        logger.info(
            f"Generating {num_tuples} BWS tuples of size {self.tuple_size} "
            f"from pool of {len(self.pool_items)} items (seed={self.seed})"
        )

        tuples = []
        for i in range(num_tuples):
            sampled = rng.sample(self.pool_items, self.tuple_size)

            bws_items = []
            for pos_idx, item in enumerate(sampled):
                bws_items.append({
                    "source_id": str(item[self.id_key]),
                    "text": str(item.get(self.text_key, "")),
                    "position": POSITION_LABELS[pos_idx],
                })

            tuple_id = f"bws_tuple_{i + 1:04d}"
            tuple_instance = {
                self.id_key: tuple_id,
                self.text_key: "",
                "_bws_items": bws_items,
                "_bws_tuple_size": self.tuple_size,
            }
            tuples.append(tuple_instance)

        # Log coverage statistics
        item_counts = {}
        for t in tuples:
            for bws_item in t["_bws_items"]:
                sid = bws_item["source_id"]
                item_counts[sid] = item_counts.get(sid, 0) + 1

        min_count = min(item_counts.values()) if item_counts else 0
        max_count = max(item_counts.values()) if item_counts else 0
        avg_count = sum(item_counts.values()) / len(item_counts) if item_counts else 0
        logger.info(
            f"BWS tuple coverage: min={min_count}, max={max_count}, avg={avg_count:.1f} "
            f"appearances per item"
        )

        return tuples
