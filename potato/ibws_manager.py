"""
Iterative Best-Worst Scaling (IBWS) Manager

Implements the IBWS algorithm from "Baby Bear: Seeking a Just Right Rating Scale
for Scalar Annotations" (arxiv 2408.09765). IBWS extends standard BWS with a
Quicksort-like adaptive loop:

1. Round 1: Generate tuples from full pool, annotators select best/worst
2. Score items, partition into upper/middle/lower buckets
3. Round N: Generate tuples WITHIN each bucket, annotate, partition again
4. Stop when all buckets are terminal (< tuple_size items) or max_rounds reached

Output: Ordinal ranking from bucket positions + within-bucket scores.

Usage:
    from potato.ibws_manager import get_ibws_manager, init_ibws_manager

    mgr = init_ibws_manager(config, pool_items, id_key, text_key)
    round1_tuples = mgr.get_current_round_tuples()

    # After annotations are complete for current round:
    if mgr.check_round_complete(ism, bws_schema_name):
        new_tuples = mgr.advance_round(ism, bws_schema_name)
        # Add new_tuples to ISM
"""

import logging
import math
import threading
from typing import Any, Dict, List, Optional, Tuple

from potato.bws_scoring import BwsScorer
from potato.bws_tuple_generator import BwsTupleGenerator

logger = logging.getLogger(__name__)

# Singleton instance
_ibws_manager = None
_ibws_lock = threading.Lock()


def init_ibws_manager(config: dict, pool_items: List[Dict[str, Any]],
                      id_key: str, text_key: str) -> "IBWSManager":
    """Initialize the global IBWS manager singleton."""
    global _ibws_manager
    with _ibws_lock:
        _ibws_manager = IBWSManager(config, pool_items, id_key, text_key)
    return _ibws_manager


def get_ibws_manager() -> Optional["IBWSManager"]:
    """Get the global IBWS manager (None if not initialized)."""
    return _ibws_manager


def clear_ibws_manager():
    """Clear the global IBWS manager (for testing)."""
    global _ibws_manager
    with _ibws_lock:
        _ibws_manager = None


class IBWSManager:
    """Manages iterative BWS rounds, partitioning, and tuple generation."""

    def __init__(self, config: dict, pool_items: List[Dict[str, Any]],
                 id_key: str, text_key: str):
        self._lock = threading.RLock()

        self.id_key = id_key
        self.text_key = text_key

        ibws_config = config["ibws_config"]
        self.tuple_size = ibws_config.get("tuple_size", 4)
        self.max_rounds = ibws_config.get("max_rounds", None)  # None = auto
        self.seed = ibws_config.get("seed", 42)
        self.scoring_method = ibws_config.get("scoring_method", "counting")
        self.tuples_per_item_per_round = ibws_config.get("tuples_per_item_per_round", 2)

        # Store original pool items with their IDs
        self.pool_items = list(pool_items)
        self.pool_item_map = {str(item[id_key]): item for item in pool_items}

        # Partition state: list of buckets, each bucket is a list of item IDs
        # Start with one bucket containing all items
        self.current_round = 0  # 0 = not started, 1 = round 1 active, etc.
        self.buckets: List[List[str]] = [[str(item[id_key]) for item in pool_items]]
        self.terminal_buckets: List[List[str]] = []  # Buckets too small to partition further

        # Track tuples for each round: round_num -> list of tuple IDs
        self.round_tuples: Dict[int, List[str]] = {}

        # Track all generated tuples' data for scoring
        self.tuple_data: Dict[str, Dict[str, Any]] = {}

        # Completed flag
        self.completed = False

    def generate_round_tuples(self) -> List[Dict[str, Any]]:
        """Generate tuples for the next round from current active buckets.

        Returns list of tuple instance dicts ready for ISM.add_item().
        """
        with self._lock:
            self.current_round += 1
            round_num = self.current_round

            all_tuples = []
            tuple_ids = []

            new_buckets = []
            for bucket_idx, bucket_item_ids in enumerate(self.buckets):
                if len(bucket_item_ids) < self.tuple_size:
                    # Terminal bucket — too few items to form a tuple
                    self.terminal_buckets.append(bucket_item_ids)
                    continue

                new_buckets.append(bucket_item_ids)

                # Build pool items for this bucket
                bucket_pool = [self.pool_item_map[iid] for iid in bucket_item_ids
                               if iid in self.pool_item_map]

                if len(bucket_pool) < self.tuple_size:
                    self.terminal_buckets.append(bucket_item_ids)
                    continue

                # Calculate tuples needed for this bucket
                min_appearances = self.tuples_per_item_per_round * self.tuple_size
                num_tuples = max(1, math.ceil(
                    len(bucket_pool) * self.tuples_per_item_per_round / self.tuple_size
                ))

                prefix = f"ibws_r{round_num}_b{bucket_idx}"
                generator = BwsTupleGenerator(
                    pool_items=bucket_pool,
                    id_key=self.id_key,
                    text_key=self.text_key,
                    tuple_size=self.tuple_size,
                    num_tuples=num_tuples,
                    seed=self.seed + round_num * 1000 + bucket_idx,
                    min_item_appearances=min_appearances,
                )

                tuples = generator.generate()

                # Rename tuple IDs with our prefix
                for i, t in enumerate(tuples):
                    new_id = f"{prefix}_{i + 1:04d}"
                    t[self.id_key] = new_id
                    t["_ibws_round"] = round_num
                    t["_ibws_bucket"] = bucket_idx
                    self.tuple_data[new_id] = t
                    tuple_ids.append(new_id)

                all_tuples.extend(tuples)

            # Update active buckets (excluding those that became terminal)
            self.buckets = new_buckets
            self.round_tuples[round_num] = tuple_ids

            if not all_tuples:
                # All buckets are terminal
                self.completed = True

            logger.info(
                f"IBWS round {round_num}: Generated {len(all_tuples)} tuples "
                f"across {len(self.buckets)} active buckets "
                f"({len(self.terminal_buckets)} terminal)"
            )

            return all_tuples

    def check_round_complete(self, ism, bws_schema_name: str) -> bool:
        """Check if all tuples in the current round have been annotated.

        Uses ISM's instance_annotators tracking to see if each tuple
        has at least one annotator.

        Args:
            ism: ItemStateManager instance
            bws_schema_name: Name of the BWS annotation schema

        Returns:
            True if all current round tuples have at least one annotation
        """
        with self._lock:
            if self.completed or self.current_round == 0:
                return False

            round_tuple_ids = self.round_tuples.get(self.current_round, [])
            if not round_tuple_ids:
                return False

            # Check that every tuple in this round has at least one annotator
            for tuple_id in round_tuple_ids:
                annotators = ism.instance_annotators.get(tuple_id, set())
                if not annotators:
                    return False

            return True

    def advance_round(self, ism, usm, bws_schema_name: str) -> List[Dict[str, Any]]:
        """Score current round, partition buckets, generate next round tuples.

        Args:
            ism: ItemStateManager instance
            usm: UserStateManager instance
            bws_schema_name: Name of the BWS annotation schema

        Returns:
            List of new tuple instance dicts for the next round (empty if done)
        """
        with self._lock:
            if self.completed:
                return []

            if self.max_rounds and self.current_round >= self.max_rounds:
                self.completed = True
                logger.info(f"IBWS: Reached max_rounds ({self.max_rounds}), stopping")
                return []

            # Score current round and partition each active bucket
            new_buckets = []
            for bucket_idx, bucket_item_ids in enumerate(self.buckets):
                if len(bucket_item_ids) < self.tuple_size:
                    self.terminal_buckets.append(bucket_item_ids)
                    continue

                # Collect annotations for tuples that contain items from this bucket
                annotations = self._collect_bucket_annotations(
                    bucket_item_ids, ism, usm, bws_schema_name
                )

                if not annotations:
                    # No annotations — can't partition, keep bucket as-is
                    new_buckets.append(bucket_item_ids)
                    continue

                # Score items in this bucket
                bucket_pool = [self.pool_item_map[iid] for iid in bucket_item_ids
                               if iid in self.pool_item_map]
                scorer = BwsScorer(annotations, bucket_pool, self.id_key, self.text_key)
                scores = scorer.score(self.scoring_method)

                # Partition into upper/middle/lower thirds
                upper, middle, lower = self._partition_bucket(bucket_item_ids, scores)

                for sub_bucket in [upper, middle, lower]:
                    if sub_bucket:
                        new_buckets.append(sub_bucket)

            self.buckets = new_buckets

            # Check if all remaining buckets are terminal
            active_count = sum(1 for b in self.buckets if len(b) >= self.tuple_size)
            if active_count == 0:
                # Move remaining small buckets to terminal
                for b in self.buckets:
                    if len(b) < self.tuple_size:
                        self.terminal_buckets.append(b)
                self.buckets = []
                self.completed = True
                logger.info("IBWS: All buckets terminal, annotation complete")
                return []

            # Generate tuples for the next round
            return self.generate_round_tuples()

    def _collect_bucket_annotations(self, bucket_item_ids, ism, usm,
                                     bws_schema_name: str) -> List[Dict[str, Any]]:
        """Collect BWS annotations for tuples containing items from a bucket."""
        bucket_id_set = set(bucket_item_ids)
        annotations = []

        # Look at tuples from the current round
        round_tuple_ids = self.round_tuples.get(self.current_round, [])

        for tuple_id in round_tuple_ids:
            tuple_info = self.tuple_data.get(tuple_id)
            if not tuple_info:
                continue

            bws_items = tuple_info.get("_bws_items", [])
            # Check if this tuple's items overlap with our bucket
            tuple_source_ids = {item["source_id"] for item in bws_items}
            if not tuple_source_ids.intersection(bucket_id_set):
                continue

            # Collect annotations from all users for this tuple
            for user_state in usm.get_all_users():
                username = user_state.get_user_id()
                label_store = getattr(user_state, 'instance_id_to_label_to_value', {})

                if tuple_id not in label_store:
                    continue

                labels = label_store[tuple_id]
                best_val = None
                worst_val = None
                for label_obj, value in labels.items():
                    if label_obj.get_schema() == bws_schema_name:
                        if label_obj.get_name() == "best":
                            best_val = value
                        elif label_obj.get_name() == "worst":
                            worst_val = value

                if best_val and worst_val:
                    annotations.append({
                        "instance_id": tuple_id,
                        "bws_items": bws_items,
                        "best": best_val,
                        "worst": worst_val,
                        "annotator": username,
                    })

        return annotations

    def _partition_bucket(self, item_ids: List[str],
                          scores: Dict[str, Dict[str, Any]]) -> Tuple[List[str], List[str], List[str]]:
        """Partition a bucket into upper/middle/lower thirds by score.

        Uses equal-thirds of sorted list (not score thresholds) for balanced partitions.
        """
        # Sort by score descending
        sorted_ids = sorted(
            item_ids,
            key=lambda iid: scores.get(iid, {}).get("score", 0.0),
            reverse=True
        )

        n = len(sorted_ids)
        third = n // 3

        # Handle remainder: distribute extra items to middle
        upper = sorted_ids[:third]
        lower = sorted_ids[n - third:] if third > 0 else []
        middle = sorted_ids[third:n - third] if third > 0 else sorted_ids

        return upper, middle, lower

    def get_round_info(self) -> Dict[str, Any]:
        """Get current round information for UI display."""
        with self._lock:
            total_tuples_this_round = len(self.round_tuples.get(self.current_round, []))
            active_buckets = len([b for b in self.buckets if len(b) >= self.tuple_size])
            terminal_count = len(self.terminal_buckets)
            total_items = len(self.pool_items)

            # Items in terminal buckets (already ranked)
            terminal_items = sum(len(b) for b in self.terminal_buckets)

            return {
                "current_round": self.current_round,
                "max_rounds": self.max_rounds,
                "total_tuples_this_round": total_tuples_this_round,
                "active_buckets": active_buckets,
                "terminal_buckets": terminal_count,
                "total_items": total_items,
                "terminal_items": terminal_items,
                "completed": self.completed,
            }

    def get_final_ranking(self) -> List[Dict[str, Any]]:
        """Produce final ordinal ranking from bucket positions + within-bucket scores.

        Returns list of dicts sorted by rank:
            [{"item_id": str, "rank": int, "bucket_position": int, "text": str}, ...]
        """
        with self._lock:
            # Combine terminal buckets (ordered by when they became terminal = higher quality)
            # and any remaining active buckets
            all_buckets = list(self.terminal_buckets) + list(self.buckets)

            ranking = []
            rank = 1
            for bucket_position, bucket in enumerate(all_buckets):
                for item_id in bucket:
                    item = self.pool_item_map.get(item_id, {})
                    ranking.append({
                        "item_id": item_id,
                        "rank": rank,
                        "bucket_position": bucket_position,
                        "text": str(item.get(self.text_key, "")),
                    })
                    rank += 1

            return ranking

    def is_completed(self) -> bool:
        """Check if IBWS has completed all rounds."""
        with self._lock:
            return self.completed
