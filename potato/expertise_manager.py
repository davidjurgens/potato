"""
Dynamic Category Expertise Manager

Dynamic category-based assignment where annotator expertise
is determined by agreement with other annotators, rather than gold labels.

Key features:
- Tracks per-user, per-category expertise scores based on agreement
- Background worker periodically recalculates expertise from annotation agreement
- Probabilistic routing: all categories possible, weighted by expertise
- Expertise increases when annotator agrees with consensus, decreases otherwise
"""

import json
import logging
import os
import threading
import time
from collections import defaultdict, Counter
from potato.server_utils.annotation_keys import answer_from_entries
from dataclasses import dataclass, field
from typing import Dict, Set, List, Optional, Any, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


def _schema_answer(instance_annotations: dict, schema_name: str):
    """One annotator's answer for one schema, as a comparable value.

    This read used to take the stored VALUE, which for a radio is the DOM
    marker "on". Consensus was then "on", every annotator's answer was "on",
    and `agreed = (user_annotation == consensus_value)` was True by
    construction. Measured: 36 agreements and no disagreement in a run where
    one annotator dissented from both colleagues on every item of a category,
    with every expertise score climbing to 1.0 and probabilistic routing
    staying uniform -- random assignment reporting success.

    The label NAME is the answer. `annotation_keys.answer_from_entries` is the
    single definition of that rule.
    """
    labels = (instance_annotations or {}).get('labels')
    if not labels:
        return None
    entries = [(label.get_name(), value) for label, value in labels.items()
               if label.get_schema() == schema_name]
    if not entries:
        return None
    return answer_from_entries(entries)



class AgreementMethod(Enum):
    """Methods for calculating agreement/consensus."""
    MAJORITY_VOTE = "majority_vote"  # Simple majority
    SUPER_MAJORITY = "super_majority"  # 2/3 or more agree
    UNANIMOUS = "unanimous"  # All must agree


@dataclass
class CategoryExpertise:
    """Tracks expertise metrics for a single category."""
    category: str
    agreements: int = 0  # Times user agreed with consensus
    disagreements: int = 0  # Times user disagreed with consensus
    total_evaluated: int = 0  # Total instances evaluated for this category
    expertise_score: float = 0.5  # 0.0 to 1.0, starts neutral

    def update_score(self, agreed: bool, learning_rate: float = 0.1) -> None:
        """
        Update expertise score based on agreement.

        Uses exponential moving average to smooth updates.
        """
        self.total_evaluated += 1
        if agreed:
            self.agreements += 1
            # Increase score, but cap at 1.0
            self.expertise_score = min(1.0,
                self.expertise_score + learning_rate * (1.0 - self.expertise_score))
        else:
            self.disagreements += 1
            # Decrease score, but floor at 0.0
            self.expertise_score = max(0.0,
                self.expertise_score - learning_rate * self.expertise_score)

    def get_accuracy(self) -> float:
        """Get raw agreement accuracy."""
        if self.total_evaluated == 0:
            return 0.5  # Neutral if no data
        return self.agreements / self.total_evaluated

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'category': self.category,
            'agreements': self.agreements,
            'disagreements': self.disagreements,
            'total_evaluated': self.total_evaluated,
            'expertise_score': self.expertise_score
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CategoryExpertise':
        """Deserialize from dictionary."""
        return cls(
            category=data['category'],
            agreements=data.get('agreements', 0),
            disagreements=data.get('disagreements', 0),
            total_evaluated=data.get('total_evaluated', 0),
            expertise_score=data.get('expertise_score', 0.5)
        )


@dataclass
class UserExpertiseProfile:
    """Complete expertise profile for a user."""
    user_id: str
    category_expertise: Dict[str, CategoryExpertise] = field(default_factory=dict)
    evaluated_instances: Set[str] = field(default_factory=set)  # Instances already evaluated
    last_updated: float = 0.0  # Timestamp of last update

    def get_expertise(self, category: str) -> CategoryExpertise:
        """Get or create expertise for a category."""
        if category not in self.category_expertise:
            self.category_expertise[category] = CategoryExpertise(category=category)
        return self.category_expertise[category]

    def get_expertise_score(self, category: str) -> float:
        """Get expertise score for a category (0.5 if unknown)."""
        if category in self.category_expertise:
            return self.category_expertise[category].expertise_score
        return 0.5  # Neutral for unknown categories

    def get_all_expertise_scores(self) -> Dict[str, float]:
        """Get all category expertise scores."""
        return {cat: exp.expertise_score for cat, exp in self.category_expertise.items()}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'user_id': self.user_id,
            'category_expertise': {
                cat: exp.to_dict() for cat, exp in self.category_expertise.items()
            },
            'evaluated_instances': list(self.evaluated_instances),
            'last_updated': self.last_updated
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UserExpertiseProfile':
        """Deserialize from dictionary."""
        profile = cls(user_id=data['user_id'])
        profile.category_expertise = {
            cat: CategoryExpertise.from_dict(exp_data)
            for cat, exp_data in data.get('category_expertise', {}).items()
        }
        profile.evaluated_instances = set(data.get('evaluated_instances', []))
        profile.last_updated = data.get('last_updated', 0.0)
        return profile


class ExpertiseManager:
    """
    Manages dynamic category expertise for all users.

    This class:
    - Tracks expertise scores per user per category
    - Calculates agreement with consensus for completed instances
    - Updates expertise scores based on agreement
    - Provides weighted probabilities for category assignment
    """

    _instance = None
    _lock = threading.RLock()

    def __new__(cls, *args, **kwargs):
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the ExpertiseManager.

        Args:
            config: Configuration dictionary with settings
        """
        if self._initialized:
            return

        self.config = config or {}
        self.user_profiles: Dict[str, UserExpertiseProfile] = {}

        # Configuration options
        dynamic_config = self.config.get('category_assignment', {}).get('dynamic', {})
        self.min_annotations_for_consensus = dynamic_config.get('min_annotations_for_consensus', 2)
        self.agreement_method = AgreementMethod(
            dynamic_config.get('agreement_method', 'majority_vote')
        )
        self.learning_rate = dynamic_config.get('learning_rate', 0.1)
        self.update_interval_seconds = dynamic_config.get('update_interval_seconds', 60)
        self.base_probability = dynamic_config.get('base_probability', 0.1)  # Min probability for any category

        # Background worker
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_worker = threading.Event()

        #: Annotations actually scored since boot. The worker's log line used
        #: to report the size of the pool it walked, which never changes.
        self.total_scored = 0

        # Scores were held in memory only. `to_dict`/`from_dict` existed and
        # had no caller anywhere, so a study restarted on day two relearned
        # every score from the neutral 0.5 and nothing said so -- and since
        # there is no route reporting expertise either, the only way to observe
        # the router at all was to run with -v and read DEBUG lines.
        self._store_path = self._resolve_store_path()
        self._load_scores()

        self._initialized = True
        logger.info(
            "ExpertiseManager initialized: agreement=%s, learning_rate=%s, "
            "update_interval=%ss, min_annotations_for_consensus=%s, "
            "base_probability=%s, scores at %s",
            self.agreement_method.value, self.learning_rate,
            self.update_interval_seconds, self.min_annotations_for_consensus,
            self.base_probability, self._store_path or "(memory only)")

    def _resolve_store_path(self) -> Optional[str]:
        """Where expertise scores live between runs, or None if nowhere."""
        task_dir = (self.config.get("output_annotation_dir")
                    or self.config.get("task_dir"))
        if not task_dir:
            return None
        return os.path.join(task_dir, "expertise_scores.json")

    def _load_scores(self) -> None:
        """Restore scores from the previous run, saying so either way."""
        if not self._store_path or not os.path.exists(self._store_path):
            if self._store_path:
                logger.info(
                    "No expertise scores found at %s; every annotator starts "
                    "at the neutral 0.5", self._store_path)
            return
        try:
            with open(self._store_path, "r", encoding="utf-8") as fh:
                self.from_dict(json.load(fh))
            logger.info("Restored expertise scores for %d annotators from %s",
                        len(self.user_profiles), self._store_path)
        except (OSError, ValueError) as exc:
            logger.warning(
                "Could not read expertise scores from %s (%s); every annotator "
                "starts at the neutral 0.5", self._store_path, exc)

    def _save_scores(self) -> None:
        """Persist scores. Failure is logged, never raised into the worker."""
        if not self._store_path:
            return
        try:
            os.makedirs(os.path.dirname(self._store_path), exist_ok=True)
            with open(self._store_path, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, indent=2)
        except (OSError, TypeError) as exc:
            logger.warning("Could not write expertise scores to %s: %s",
                           self._store_path, exc)

    def get_user_profile(self, user_id: str) -> UserExpertiseProfile:
        """Get or create expertise profile for a user."""
        with self._lock:
            if user_id not in self.user_profiles:
                self.user_profiles[user_id] = UserExpertiseProfile(user_id=user_id)
            return self.user_profiles[user_id]

    def calculate_consensus(
        self,
        instance_id: str,
        category: str,
        schema_name: str
    ) -> Optional[Tuple[Any, int]]:
        """
        Calculate the consensus annotation for an instance.

        Args:
            instance_id: The instance ID
            category: The category of the instance
            schema_name: The annotation schema to check

        Returns:
            Tuple of (consensus_value, num_annotators) or None if not enough annotations
        """
        # Import here to avoid circular imports
        from potato.flask_server import get_users, get_user_state

        annotations = []
        for username in get_users():
            user_state = get_user_state(username)
            if user_state:
                all_annotations = user_state.get_all_annotations()
                if instance_id in all_annotations:
                    answer = _schema_answer(
                        all_annotations[instance_id], schema_name)
                    if answer is not None:
                        annotations.append((username, answer))

        if len(annotations) < self.min_annotations_for_consensus:
            return None

        # Extract just the values
        values = [v for _, v in annotations]
        counter = Counter(values)
        most_common_value, most_common_count = counter.most_common(1)[0]

        # Check agreement method
        if self.agreement_method == AgreementMethod.MAJORITY_VOTE:
            if most_common_count > len(values) / 2:
                return (most_common_value, len(annotations))
        elif self.agreement_method == AgreementMethod.SUPER_MAJORITY:
            if most_common_count >= len(values) * 2 / 3:
                return (most_common_value, len(annotations))
        elif self.agreement_method == AgreementMethod.UNANIMOUS:
            if most_common_count == len(values):
                return (most_common_value, len(annotations))

        return None  # No clear consensus

    def update_user_expertise(
        self,
        user_id: str,
        instance_id: str,
        category: str,
        user_annotation: Any,
        consensus_value: Any
    ) -> Optional[bool]:
        """
        Update a user's expertise based on agreement with consensus.

        Args:
            user_id: The user ID
            instance_id: The instance ID
            category: The category of the instance
            user_annotation: The user's annotation value
            consensus_value: The consensus annotation value

        Returns:
            True if the user agreed, False if they disagreed, None if this
            instance was already scored. The skip used to return False, which
            is indistinguishable from a disagreement -- and the caller counted
            it as work done either way.
        """
        with self._lock:
            profile = self.get_user_profile(user_id)

            # Skip if already evaluated
            eval_key = f"{instance_id}:{category}"
            if eval_key in profile.evaluated_instances:
                return None

            # Determine agreement
            agreed = (user_annotation == consensus_value)

            # Update expertise
            expertise = profile.get_expertise(category)
            expertise.update_score(agreed, self.learning_rate)

            # Mark as evaluated
            profile.evaluated_instances.add(eval_key)
            profile.last_updated = time.time()

            logger.debug(
                f"Updated expertise for {user_id} in {category}: "
                f"agreed={agreed}, new_score={expertise.expertise_score:.3f}"
            )

            return agreed

    def evaluate_all_instances(self) -> Dict[str, int]:
        """
        Evaluate all completed instances and update expertise scores.

        This is called by the background worker periodically.

        Returns:
            Dictionary mapping user_id to number of new evaluations
        """
        # Import here to avoid circular imports
        from potato.flask_server import get_users, get_user_state, get_item_state_manager

        updates_per_user: Dict[str, int] = defaultdict(int)

        try:
            ism = get_item_state_manager()
            if ism is None:
                return updates_per_user

            # Get all annotation schemes from config
            annotation_schemes = self.config.get('annotation_schemes', [])
            schema_names = [s.get('name') for s in annotation_schemes if s.get('name')]

            if not schema_names:
                return updates_per_user

            # Use first schema for agreement calculation
            primary_schema = schema_names[0]

            # Get all instances with categories
            for instance_id in ism.instance_id_ordering:
                categories = ism.get_categories_for_instance(instance_id)
                if not categories:
                    continue

                for category in categories:
                    # Try to get consensus
                    consensus_result = self.calculate_consensus(
                        instance_id, category, primary_schema
                    )

                    if consensus_result is None:
                        continue  # Not enough annotations yet

                    consensus_value, num_annotators = consensus_result

                    # Update each user who annotated this instance
                    for username in get_users():
                        user_state = get_user_state(username)
                        if not user_state:
                            continue

                        all_annotations = user_state.get_all_annotations()
                        if instance_id not in all_annotations:
                            continue

                        instance_annotations = all_annotations[instance_id]
                        if 'labels' not in instance_annotations:
                            continue

                        # Find user's annotation for this schema
                        user_value = _schema_answer(
                            instance_annotations, primary_schema)

                        if user_value is not None:
                            # Count what was SCORED, not what was offered. The
                            # counter incremented unconditionally while the
                            # update returned early on the already-scored
                            # guard, so "Background worker: 36 expertise
                            # updates" was logged on every tick forever after
                            # 36 real updates happened once. It was a constant
                            # dressed as throughput, and it read the same
                            # whether the router was learning or had been idle
                            # for eight hours.
                            scored = self.update_user_expertise(
                                username, instance_id, category,
                                user_value, consensus_value
                            )
                            if scored is not None:
                                updates_per_user[username] += 1
                                self.total_scored += 1

        except Exception as e:
            logger.error(f"Error evaluating instances: {e}")

        return updates_per_user

    def get_category_probabilities(
        self,
        user_id: str,
        available_categories: Set[str]
    ) -> Dict[str, float]:
        """
        Calculate assignment probabilities for each category.

        Uses expertise scores to weight categories, but ensures all categories
        have at least base_probability chance.

        Args:
            user_id: The user ID
            available_categories: Set of categories with available instances

        Returns:
            Dictionary mapping category to probability (sums to 1.0)
        """
        if not available_categories:
            return {}

        profile = self.get_user_profile(user_id)

        # Get raw scores for each category
        raw_scores = {}
        for category in available_categories:
            score = profile.get_expertise_score(category)
            # Ensure minimum probability
            raw_scores[category] = max(self.base_probability, score)

        # Normalize to probabilities
        total = sum(raw_scores.values())
        if total == 0:
            # Equal probability if no scores
            prob = 1.0 / len(available_categories)
            return {cat: prob for cat in available_categories}

        return {cat: score / total for cat, score in raw_scores.items()}

    def select_category_probabilistically(
        self,
        user_id: str,
        available_categories: Set[str],
        random_instance=None
    ) -> Optional[str]:
        """
        Select a category using weighted random selection.

        Args:
            user_id: The user ID
            available_categories: Set of categories with available instances
            random_instance: Optional random.Random instance for reproducibility

        Returns:
            Selected category name, or None if no categories available
        """
        import random as random_module

        if not available_categories:
            return None

        probs = self.get_category_probabilities(user_id, available_categories)
        if not probs:
            return None

        rng = random_instance or random_module
        categories = list(probs.keys())
        weights = [probs[cat] for cat in categories]

        # Use random.choices for weighted selection
        selected = rng.choices(categories, weights=weights, k=1)[0]
        return selected

    def start_background_worker(self) -> None:
        """Start the background worker thread for periodic expertise updates."""
        if self._worker_thread is not None and self._worker_thread.is_alive():
            logger.warning("Background worker already running")
            return

        self._stop_worker.clear()
        self._worker_thread = threading.Thread(
            target=self._background_worker_loop,
            name="ExpertiseWorker",
            daemon=True
        )
        self._worker_thread.start()
        logger.info("Started expertise background worker")

    def stop_background_worker(self) -> None:
        """Stop the background worker thread."""
        if self._worker_thread is None:
            return

        self._stop_worker.set()
        self._worker_thread.join(timeout=5.0)
        self._worker_thread = None
        self._save_scores()
        logger.info("Stopped expertise background worker; scores saved to %s",
                    self._store_path or "(memory only)")

    def _background_worker_loop(self) -> None:
        """Main loop for the background worker."""
        logger.info(f"Background worker started, interval={self.update_interval_seconds}s")

        while not self._stop_worker.is_set():
            try:
                updates = self.evaluate_all_instances()
                total_updates = sum(updates.values()) if updates else 0
                if total_updates:
                    logger.info(
                        "Expertise: scored %d new annotations across %d "
                        "annotators (%d scored in total so far)",
                        total_updates, len(updates), self.total_scored)
                    self._save_scores()
            except Exception as e:
                logger.error(f"Background worker error: {e}")

            # Wait for next interval or stop signal
            self._stop_worker.wait(self.update_interval_seconds)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize all expertise data."""
        with self._lock:
            return {
                'user_profiles': {
                    user_id: profile.to_dict()
                    for user_id, profile in self.user_profiles.items()
                }
            }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load expertise data from dictionary."""
        with self._lock:
            self.user_profiles = {
                user_id: UserExpertiseProfile.from_dict(profile_data)
                for user_id, profile_data in data.get('user_profiles', {}).items()
            }


# Module-level singleton access
_expertise_manager: Optional[ExpertiseManager] = None


def init_expertise_manager(config: Dict[str, Any]) -> ExpertiseManager:
    """Initialize the global expertise manager."""
    global _expertise_manager
    _expertise_manager = ExpertiseManager(config)
    return _expertise_manager


def get_expertise_manager() -> Optional[ExpertiseManager]:
    """Get the global expertise manager instance."""
    return _expertise_manager


def clear_expertise_manager() -> None:
    """Clear the global expertise manager (for testing)."""
    global _expertise_manager
    if _expertise_manager:
        _expertise_manager.stop_background_worker()
    _expertise_manager = None
    ExpertiseManager._instance = None
