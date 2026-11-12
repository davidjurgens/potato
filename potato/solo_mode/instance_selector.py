"""
Instance Selector for Solo Mode

Weighted instance selection for human annotation, combining LLM confidence,
diversity, disagreements and randomness to decide what the annotator sees next.
An optional curriculum (Annotation Curricula, CL 2022) overrides the pools for
the human's first labels so they start on the items the LLM found easiest.
"""

import logging
import random
from collections import Counter
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
    edge_case_rule: float = 0.0  # Instances matching edge case rule patterns
    cartography: float = 0.0     # Instances with high confidence variability
    llm_predicted: float = 0.0   # Instances with LLM predictions needing human comparison

    def validate(self) -> None:
        """Validate that weights sum to 1.0."""
        total = (
            self.low_confidence +
            self.diverse +
            self.random +
            self.disagreement +
            self.edge_case_rule +
            self.cartography +
            self.llm_predicted
        )
        if abs(total - 1.0) > 0.001:
            # Normalize
            self.low_confidence /= total
            self.diverse /= total
            self.random /= total
            self.disagreement /= total
            self.edge_case_rule /= total
            self.cartography /= total
            self.llm_predicted /= total
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
        self._edge_case_rule_pool: List[str] = []
        self._cartography_pool: List[str] = []
        self._llm_predicted_pool: List[str] = []

        # Cache predictions for use in _select_lowest_confidence
        self._predictions_cache: Dict[str, Dict[str, Any]] = {}

        # Curriculum state. ``curriculum`` is a CurriculumConfig (or None when
        # off); progress is the human label count the manager last reported.
        self.curriculum = None
        self._human_labeled_count = 0
        self._cartography_cache: Dict[str, float] = {}
        self._curriculum_label_counts: Counter = Counter()

    def configure_curriculum(self, curriculum) -> None:
        """Turn curriculum ordering on (a CurriculumConfig) or off (None)."""
        with self._lock:
            self.curriculum = (
                curriculum if curriculum is not None and curriculum.enabled
                else None)
            self._curriculum_label_counts.clear()

    def configure(
        self,
        low_confidence_weight: float = 0.4,
        diversity_weight: float = 0.3,
        random_weight: float = 0.2,
        disagreement_weight: float = 0.1,
        edge_case_rule_weight: float = 0.0,
        cartography_weight: float = 0.0,
        llm_predicted_weight: float = 0.0,
    ) -> None:
        """Configure selection weights.

        Every pool has to be named here. Omitting one does not leave it alone --
        it rebuilds ``SelectionWeights`` from scratch, so the missing pool drops
        to its dataclass default. ``llm_predicted`` was absent until 2026-08-27,
        which meant any call to this method silently switched the LLM-predicted
        pool off.
        """
        self.weights = SelectionWeights(
            low_confidence=low_confidence_weight,
            diverse=diversity_weight,
            random=random_weight,
            disagreement=disagreement_weight,
            edge_case_rule=edge_case_rule_weight,
            cartography=cartography_weight,
            llm_predicted=llm_predicted_weight,
        )
        self.weights.validate()

    def refresh_pools(
        self,
        available_ids: Set[str],
        llm_predictions: Optional[Dict[str, Dict[str, Any]]] = None,
        disagreement_ids: Optional[Set[str]] = None,
        confidence_threshold: float = 0.5,
        edge_case_rule_ids: Optional[Set[str]] = None,
        cartography_scores: Optional[Dict[str, float]] = None,
        revisit_ids: Optional[Set[str]] = None,
        human_labeled_count: Optional[int] = None,
    ) -> None:
        """
        Refresh the selection pools based on current state.

        Args:
            available_ids: Set of instance IDs available for selection
            llm_predictions: Dict of instance_id -> schema -> prediction
            disagreement_ids: Set of instance IDs with disagreements
            confidence_threshold: Threshold for low confidence pool
            edge_case_rule_ids: Set of instance IDs matching edge case rule patterns
            cartography_scores: Dict of instance_id -> variability score
            revisit_ids: Already-labelled disagreements to offer again for
                re-review. They are not in ``available_ids`` (which holds
                unlabelled items), so the disagreement pool is built from
                these directly.
            human_labeled_count: How many items the human has labelled so
                far. Drives the curriculum; omitted, the last value stands.
        """
        with self._lock:
            available_list = list(available_ids)

            # Cache predictions for use in _select_lowest_confidence
            self._predictions_cache = llm_predictions or {}
            self._cartography_cache = dict(cartography_scores or {})
            if human_labeled_count is not None:
                self._human_labeled_count = human_labeled_count

            # Clear pools
            self._low_confidence_pool = []
            self._diverse_pool = []
            self._random_pool = []
            self._disagreement_pool = []
            self._edge_case_rule_pool = []
            self._cartography_pool = []
            self._llm_predicted_pool = []

            # Build low confidence pool
            observed_confidences = []
            if llm_predictions:
                for instance_id in available_list:
                    if instance_id in llm_predictions:
                        preds = llm_predictions[instance_id]
                        # Check if any prediction is below threshold
                        for pred in preds.values():
                            confidence = pred.get('confidence_score', 1.0)
                            observed_confidences.append(confidence)
                            if confidence < confidence_threshold:
                                self._low_confidence_pool.append(instance_id)
                                break

            # An empty pool is dropped by _select_weighted_pool and its weight
            # is renormalised onto the others, so the largest of the five
            # weights can route nothing at all and never say so. The default
            # `direct_confidence` estimator self-reports in the 0.95-1.0 band,
            # well above the 0.5 default threshold, so on an unmodified config
            # this arm is inert rather than merely quiet. Say which way the
            # threshold missed -- the number to change depends on it.
            if observed_confidences and not self._low_confidence_pool:
                lowest = min(observed_confidences)
                logger.warning(
                    "low_confidence_weight is %.2f and the low-confidence pool "
                    "is empty: %d prediction(s) scored no lower than %.2f, and "
                    "the threshold is %.2f. That weight is being renormalised "
                    "onto the other pools. Raise solo_mode.confidence_threshold "
                    "above %.2f, or use an uncertainty estimator whose range "
                    "reaches it -- a self-reported confidence rarely goes low.",
                    self.weights.low_confidence, len(observed_confidences),
                    lowest, confidence_threshold, lowest)

            # Build LLM-predicted pool: instances with predictions that aren't
            # already in the low_confidence pool (those are more valuable there).
            # This pool steers human annotations toward instances where a comparison
            # with the LLM can happen immediately.
            if llm_predictions:
                low_conf_set = set(self._low_confidence_pool)
                self._llm_predicted_pool = [
                    iid for iid in available_list
                    if iid in llm_predictions and iid not in low_conf_set
                ]

            # Build disagreement pool
            if revisit_ids:
                self._disagreement_pool = sorted(revisit_ids)
            elif disagreement_ids:
                self._disagreement_pool = [
                    iid for iid in available_list
                    if iid in disagreement_ids
                ]

            # Build edge case rule pool
            if edge_case_rule_ids:
                self._edge_case_rule_pool = [
                    iid for iid in available_list
                    if iid in edge_case_rule_ids
                ]

            # Build cartography pool (high variability = ambiguous instances)
            if cartography_scores:
                scored = [
                    (iid, score) for iid, score in cartography_scores.items()
                    if iid in available_ids and score > 0
                ]
                scored.sort(key=lambda x: x[1], reverse=True)
                self._cartography_pool = [iid for iid, _ in scored]

            # Diverse pool uses diversity manager if available
            self._diverse_pool = self._build_diverse_pool(available_list)

            # Random pool is just all available (sampling happens at selection time)
            self._random_pool = available_list.copy()

            logger.debug(
                f"Refreshed pools: low_conf={len(self._low_confidence_pool)}, "
                f"llm_predicted={len(self._llm_predicted_pool)}, "
                f"diverse={len(self._diverse_pool)}, "
                f"random={len(self._random_pool)}, "
                f"disagreement={len(self._disagreement_pool)}, "
                f"edge_case_rule={len(self._edge_case_rule_pool)}, "
                f"cartography={len(self._cartography_pool)}"
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
                'edge_case_rule': [
                    iid for iid in self._edge_case_rule_pool
                    if iid in available_ids and iid not in exclude
                ],
                'cartography': [
                    iid for iid in self._cartography_pool
                    if iid in available_ids and iid not in exclude
                ],
                'llm_predicted': [
                    iid for iid in self._llm_predicted_pool
                    if iid in available_ids and iid not in exclude
                ],
            }

            # Select pool based on weights
            selected_pool, pool_name = self._weighted_pool_selection(pools)

            # The curriculum replaces the pick among fresh items. A revisit of
            # an earlier disagreement keeps its turn: deferring every re-review
            # until the curriculum ends would hide the human's first
            # disagreements for its whole length.
            if pool_name != 'disagreement':
                instance_id = self._select_by_curriculum(available_ids, exclude)
                if instance_id is not None:
                    self._record_selection(instance_id, 'curriculum')
                    return instance_id

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
            elif pool_name == 'edge_case_rule':
                # Random from edge case rule matches
                instance_id = self.random.choice(selected_pool)
            elif pool_name == 'cartography':
                # Take first (already sorted by variability, highest first)
                instance_id = selected_pool[0]
            elif pool_name == 'llm_predicted':
                # Random from LLM-predicted instances
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
            'edge_case_rule': self.weights.edge_case_rule,
            'cartography': self.weights.cartography,
            'llm_predicted': self.weights.llm_predicted,
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

    # === Curriculum ===

    def curriculum_target(
        self, human_labeled_count: Optional[int] = None,
    ) -> Optional[float]:
        """Target difficulty quantile for the next pick, or None when inactive.

        0.0 during warm-up (easiest first), rising linearly to 1.0 across the
        ramp, and None once the ramp is over or the curriculum is off.
        ``human_labeled_count`` defaults to the count from the last refresh.
        """
        c = self.curriculum
        if c is None:
            return None
        n = (self._human_labeled_count if human_labeled_count is None
             else human_labeled_count)
        if n < c.warmup_items:
            return 0.0
        if n < c.warmup_items + c.ramp_items:
            return (n - c.warmup_items) / c.ramp_items
        return None

    def _difficulty(self, instance_id: str) -> Optional[float]:
        """Estimated difficulty in [0, 1], or None when there is no signal.

        ``confidence`` is one minus the lowest LLM confidence across the item's
        schemas. Under confidence routing that includes the confidence of
        every tier the item passed through, so an item the first tier
        escalated is not ranked easy because the tier that accepted it was
        sure. ``cartography`` is the item's confidence variability across
        prompt versions, scaled by the largest variability seen. ``combined``
        averages whichever of the two the item has.
        """
        signal = self.curriculum.difficulty_signal
        parts = []
        if signal in ('confidence', 'combined'):
            preds = self._predictions_cache.get(instance_id)
            if preds:
                lowest = min(
                    min(float(p.get('confidence_score', 1.0)),
                        float(p.get('routing_min_confidence', 1.0)))
                    for p in preds.values())
                parts.append(1.0 - max(0.0, min(1.0, lowest)))
        if signal in ('cartography', 'combined'):
            score = self._cartography_cache.get(instance_id)
            if score is not None:
                top = max(self._cartography_cache.values())
                parts.append(score / top if top > 0 else 0.0)
        if not parts:
            return None
        return sum(parts) / len(parts)

    def _predicted_label_key(self, instance_id: str) -> str:
        preds = self._predictions_cache.get(instance_id) or {}
        return '|'.join(
            f"{schema}={preds[schema].get('predicted_label')}"
            for schema in sorted(preds))

    def _select_by_curriculum(
        self,
        available_ids: Set[str],
        exclude: Set[str],
    ) -> Optional[str]:
        """Pick the fresh item nearest the curriculum's target difficulty.

        Returns None when the curriculum is inactive or no fresh item has a
        difficulty signal yet (cold start), so the weighted pools decide.
        """
        target = self.curriculum_target()
        if target is None:
            return None

        # Fresh items only: _random_pool is every unlabelled item at refresh.
        scored = []
        for iid in self._random_pool:
            if iid not in available_ids or iid in exclude:
                continue
            difficulty = self._difficulty(iid)
            if difficulty is not None:
                scored.append((iid, difficulty))
        if not scored:
            return None

        # Shuffle before the stable sort so equal difficulties (common with
        # self-reported confidence, which bunches near 1.0) come out in a
        # random order rather than in data-file order.
        self.random.shuffle(scored)
        scored.sort(key=lambda pair: pair[1])

        centre = round(target * (len(scored) - 1))
        half = self.curriculum.window // 2
        lo = max(0, min(centre - half, len(scored) - self.curriculum.window))
        window = scored[lo:lo + self.curriculum.window]

        # Within the window, rotate the LLM's predicted label so a warm-up on
        # a skewed dataset is not twenty copies of the obvious class. Ties go
        # to the item closest to the target.
        def rank(indexed):
            offset, (iid, _) = indexed
            return (self._curriculum_label_counts[self._predicted_label_key(iid)],
                    abs(lo + offset - centre))
        _, (chosen, _) = min(enumerate(window), key=rank)
        self._curriculum_label_counts[self._predicted_label_key(chosen)] += 1
        return chosen

    def get_curriculum_status(
        self, human_labeled_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Curriculum stage and progress, for the dashboard and the API."""
        with self._lock:
            c = self.curriculum
            if c is None:
                return {'enabled': False}
            n = (self._human_labeled_count if human_labeled_count is None
                 else human_labeled_count)
            if n < c.warmup_items:
                stage = 'warmup'
            elif n < c.warmup_items + c.ramp_items:
                stage = 'ramp'
            else:
                stage = 'done'
            return {
                'enabled': True,
                'stage': stage,
                'human_labeled': n,
                'warmup_items': c.warmup_items,
                'ramp_items': c.ramp_items,
                'target_difficulty': self.curriculum_target(n),
                'difficulty_signal': c.difficulty_signal,
            }

    def _select_lowest_confidence(self, pool: List[str]) -> str:
        """Select the instance with lowest LLM confidence from cached predictions."""
        min_conf = float('inf')
        best_id = pool[0]

        for instance_id in pool:
            if instance_id in self._predictions_cache:
                for pred in self._predictions_cache[instance_id].values():
                    conf = pred.get('confidence_score', 1.0)
                    if conf < min_conf:
                        min_conf = conf
                        best_id = instance_id

        return best_id

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
                    'edge_case_rule': len(self._edge_case_rule_pool),
                    'cartography': len(self._cartography_pool),
                    'llm_predicted': len(self._llm_predicted_pool),
                },
                'weights': {
                    'low_confidence': self.weights.low_confidence,
                    'diverse': self.weights.diverse,
                    'random': self.weights.random,
                    'disagreement': self.weights.disagreement,
                    'edge_case_rule': self.weights.edge_case_rule,
                    'cartography': self.weights.cartography,
                    'llm_predicted': self.weights.llm_predicted,
                },
                'curriculum': self.get_curriculum_status(),
            }

    def clear_history(self) -> None:
        """Clear selection history."""
        with self._lock:
            self.selection_history.clear()
