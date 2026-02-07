"""
Instance Selector for Solo Mode

This module implements weighted instance selection for human annotation.
It combines multiple signals (LLM confidence, diversity, disagreements, random)
to prioritize which instances the human annotator should see next.
"""

import logging
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple
import threading

logger = logging.getLogger(__name__)


@dataclass
class SelectionWeights:
    """Configuration for instance selection weights."""
    low_confidence: float = 0.4   # Low LLM confidence instances
    diverse: float = 0.3          # Diverse instances (embedding clusters)
    random: float = 0.2           # Random sample for calibration
    disagreement: float = 0.1    # Instances with prior disagreements

    def validate(self) -> None:
        """Validate that weights sum to 1.0."""
        total = (
            self.low_confidence +
            self.diverse +
            self.random +
            self.disagreement
        )
        if abs(total - 1.0) > 0.001:
            # Normalize
            self.low_confidence /= total
            self.diverse /= total
            self.random /= total
            self.disagreement /= total
            logger.warning(f"Normalized selection weights (original sum: {total})")


class InstanceSelector:
    """
    Weighted instance selector for Solo Mode.

    Combines multiple signals to select which instances the human
    should annotate, optimizing for efficient use of human labeling time.

    Selection pools:
    1. Low confidence: Instances where LLM is uncertain
    2. Diverse: Instances from different embedding clusters
    3. Random: Random sample for calibration
    4. Disagreement: Instances with prior human-LLM disagreement
    """

    def __init__(
        self,
        weights: Optional[SelectionWeights] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the instance selector.

        Args:
            weights: Selection weight configuration
            config: Full application configuration
        """
        self.weights = weights or SelectionWeights()
        self.weights.validate()
        self.config = config or {}
        self._lock = threading.RLock()

        # Random state
        self.random = random.Random()

        # Track selection history
        self.selection_history: List[Dict[str, Any]] = []

        # Pool state
        self._low_confidence_pool: List[str] = []
        self._diverse_pool: List[str] = []
        self._random_pool: List[str] = []
        self._disagreement_pool: List[str] = []

    def configure(
        self,
        low_confidence_weight: float = 0.4,
        diversity_weight: float = 0.3,
        random_weight: float = 0.2,
        disagreement_weight: float = 0.1
    ) -> None:
        """Configure selection weights."""
        self.weights = SelectionWeights(
            low_confidence=low_confidence_weight,
            diverse=diversity_weight,
            random=random_weight,
            disagreement=disagreement_weight,
        )
        self.weights.validate()

    def refresh_pools(
        self,
        available_ids: Set[str],
        llm_predictions: Optional[Dict[str, Dict[str, Any]]] = None,
        disagreement_ids: Optional[Set[str]] = None,
        confidence_threshold: float = 0.5
    ) -> None:
        """
        Refresh the selection pools based on current state.

        Args:
            available_ids: Set of instance IDs available for selection
            llm_predictions: Dict of instance_id -> schema -> prediction
            disagreement_ids: Set of instance IDs with disagreements
            confidence_threshold: Threshold for low confidence pool
        """
        with self._lock:
            available_list = list(available_ids)

            # Clear pools
            self._low_confidence_pool = []
            self._diverse_pool = []
            self._random_pool = []
            self._disagreement_pool = []

            # Build low confidence pool
            if llm_predictions:
                for instance_id in available_list:
                    if instance_id in llm_predictions:
                        preds = llm_predictions[instance_id]
                        # Check if any prediction is below threshold
                        for pred in preds.values():
                            confidence = pred.get('confidence_score', 1.0)
                            if confidence < confidence_threshold:
                                self._low_confidence_pool.append(instance_id)
                                break

            # Build disagreement pool
            if disagreement_ids:
                self._disagreement_pool = [
                    iid for iid in available_list
                    if iid in disagreement_ids
                ]

            # Diverse pool uses diversity manager if available
            self._diverse_pool = self._build_diverse_pool(available_list)

            # Random pool is just all available (sampling happens at selection time)
            self._random_pool = available_list.copy()

            logger.debug(
                f"Refreshed pools: low_conf={len(self._low_confidence_pool)}, "
                f"diverse={len(self._diverse_pool)}, "
                f"random={len(self._random_pool)}, "
                f"disagreement={len(self._disagreement_pool)}"
            )

    def _build_diverse_pool(self, available_ids: List[str]) -> List[str]:
        """
        Build the diverse instances pool using DiversityManager.

        Returns instances ordered by diversity (from different clusters).
        """
        try:
            from potato.diversity_manager import get_diversity_manager

            dm = get_diversity_manager()
            if dm is None or not dm.enabled:
                return []

            # Get diverse ordering from all clusters
            diverse = dm.generate_diverse_ordering(
                user_id='solo_mode',
                available_ids=available_ids,
                preserve_ids=set()
            )
            return diverse

        except Exception as e:
            logger.debug(f"Could not build diverse pool: {e}")
            return []

    def select_next(
        self,
        available_ids: Set[str],
        exclude_ids: Optional[Set[str]] = None
    ) -> Optional[str]:
        """
        Select the next instance for human annotation.

        Uses weighted random selection across the pools.

        Args:
            available_ids: Set of available instance IDs
            exclude_ids: Set of IDs to exclude from selection

        Returns:
            Selected instance ID, or None if no instances available
        """
        with self._lock:
            # Filter pools by available and exclude
            exclude = exclude_ids or set()

            pools = {
                'low_confidence': [
                    iid for iid in self._low_confidence_pool
                    if iid in available_ids and iid not in exclude
                ],
                'diverse': [
                    iid for iid in self._diverse_pool
                    if iid in available_ids and iid not in exclude
                ],
                'random': [
                    iid for iid in self._random_pool
                    if iid in available_ids and iid not in exclude
                ],
                'disagreement': [
                    iid for iid in self._disagreement_pool
                    if iid in available_ids and iid not in exclude
                ],
            }

            # Select pool based on weights
            selected_pool, pool_name = self._weighted_pool_selection(pools)

            if not selected_pool:
                # Fallback to any available instance
                remaining = [iid for iid in available_ids if iid not in exclude]
                if remaining:
                    instance_id = self.random.choice(remaining)
                    self._record_selection(instance_id, 'fallback')
                    return instance_id
                return None

            # Select from pool
            if pool_name == 'low_confidence':
                # Sort by confidence (lowest first) and take first
                instance_id = self._select_lowest_confidence(selected_pool)
            elif pool_name == 'diverse':
                # Take first (already ordered by diversity)
                instance_id = selected_pool[0]
            elif pool_name == 'disagreement':
                # Random from disagreements
                instance_id = self.random.choice(selected_pool)
            else:  # random
                instance_id = self.random.choice(selected_pool)

            self._record_selection(instance_id, pool_name)
            return instance_id

    def _weighted_pool_selection(
        self,
        pools: Dict[str, List[str]]
    ) -> Tuple[List[str], str]:
        """
        Select a pool based on configured weights.

        Returns empty list if all pools are empty.
        """
        # Build list of (pool, name, weight) for non-empty pools
        candidates = []
        weights = []

        pool_weights = {
            'low_confidence': self.weights.low_confidence,
            'diverse': self.weights.diverse,
            'random': self.weights.random,
            'disagreement': self.weights.disagreement,
        }

        for name, pool in pools.items():
            if pool:  # Only consider non-empty pools
                candidates.append((pool, name))
                weights.append(pool_weights[name])

        if not candidates:
            return [], ''

        # Normalize weights
        total = sum(weights)
        if total > 0:
            weights = [w / total for w in weights]

        # Weighted random selection
        r = self.random.random()
        cumsum = 0
        for (pool, name), weight in zip(candidates, weights):
            cumsum += weight
            if r <= cumsum:
                return pool, name

        # Fallback to last
        return candidates[-1]

    def _select_lowest_confidence(self, pool: List[str]) -> str:
        """Select the instance with lowest LLM confidence."""
        try:
            from potato.item_state_management import get_item_state_manager

            ism = get_item_state_manager()
            if ism is None:
                return self.random.choice(pool)

            min_conf = float('inf')
            best_id = pool[0]

            for instance_id in pool:
                predictions = ism.get_llm_predictions(instance_id)
                for pred in predictions.values():
                    conf = pred.get('confidence_score', 1.0)
                    if conf < min_conf:
                        min_conf = conf
                        best_id = instance_id

            return best_id

        except Exception:
            return self.random.choice(pool)

    def _record_selection(self, instance_id: str, pool_name: str) -> None:
        """Record a selection for analytics."""
        from datetime import datetime
        self.selection_history.append({
            'instance_id': instance_id,
            'pool': pool_name,
            'timestamp': datetime.now().isoformat(),
        })

    def select_batch(
        self,
        available_ids: Set[str],
        batch_size: int,
        exclude_ids: Optional[Set[str]] = None
    ) -> List[str]:
        """
        Select a batch of instances for annotation.

        Args:
            available_ids: Available instance IDs
            batch_size: Number of instances to select
            exclude_ids: IDs to exclude

        Returns:
            List of selected instance IDs
        """
        selected = []
        exclude = set(exclude_ids) if exclude_ids else set()

        for _ in range(batch_size):
            instance_id = self.select_next(available_ids, exclude)
            if instance_id is None:
                break
            selected.append(instance_id)
            exclude.add(instance_id)

        return selected

    def get_selection_stats(self) -> Dict[str, Any]:
        """Get statistics about selections made."""
        with self._lock:
            from collections import Counter
            pool_counts = Counter(s['pool'] for s in self.selection_history)

            return {
                'total_selections': len(self.selection_history),
                'by_pool': dict(pool_counts),
                'pool_sizes': {
                    'low_confidence': len(self._low_confidence_pool),
                    'diverse': len(self._diverse_pool),
                    'random': len(self._random_pool),
                    'disagreement': len(self._disagreement_pool),
                },
                'weights': {
                    'low_confidence': self.weights.low_confidence,
                    'diverse': self.weights.diverse,
                    'random': self.weights.random,
                    'disagreement': self.weights.disagreement,
                },
            }

    def clear_history(self) -> None:
        """Clear selection history."""
        with self._lock:
            self.selection_history.clear()
