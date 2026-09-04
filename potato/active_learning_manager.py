"""
Enhanced Active Learning Manager with Database Persistence

An active learning system with optional
database persistence, model saving, LLM integration, and multiple query
strategies including uncertainty sampling, diversity sampling, BADGE, BALD,
and hybrid combinations.

References:
    [1] Ash et al. (2020) "Deep Batch Active Learning by Diverse, Uncertain
        Gradient Lower Bounds" (BADGE). ICLR 2020.
    [2] Houlsby et al. (2011) "Bayesian Active Learning for Classification
        and Preference Learning" (BALD).
    [3] Bayer et al. (2024) "ActiveLLM: Large Language Model-Based Active
        Learning for Textual Few-Shot Scenarios". TACL.
    [4] Yuan et al. (2024) "Hide and Seek in Noise Labels: Noise-Robust
        Collaborative Active Learning" (NoiseAL). ACL 2024.
    [5] Mavromatis et al. (2024) "CoverICL: Selective Annotation for
        In-Context Learning via Active Graph Coverage". EMNLP 2024.
"""

import threading
import logging
import time
import os
import pickle
import json
from typing import Dict, List, Optional, Tuple, Any, Union
from collections import defaultdict, Counter
import dataclasses
from dataclasses import dataclass, field, asdict
from enum import Enum
import random
import queue
from datetime import datetime
from abc import ABC, abstractmethod

from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import SVC
from sklearn.metrics import accuracy_score, classification_report
import numpy as np

from potato.item_state_management import ItemStateManager, get_item_state_manager
from potato.user_state_management import get_user_state_manager


logger = logging.getLogger(__name__)


class ResolutionStrategy(Enum):
    """Strategies for resolving multiple annotations per instance."""
    MAJORITY_VOTE = "majority_vote"
    RANDOM = "random"
    CONSENSUS = "consensus"
    WEIGHTED_AVERAGE = "weighted_average"


# ---------------------------------------------------------------------------
# SentenceTransformerVectorizer
# ---------------------------------------------------------------------------

class SentenceTransformerVectorizer:
    """sklearn-compatible wrapper for sentence-transformers.

    Uses dense embeddings from pre-trained transformer models instead of
    bag-of-words features. Produces 384-dim vectors (for default model)
    that capture semantic meaning, enabling better classification with
    fewer training examples.

    The ``sentence-transformers`` package is an **optional** dependency and
    is only imported when this vectorizer is actually used.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None

    def fit(self, X, y=None):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(self.model_name)
        return self

    def transform(self, X):
        if self._model is None:
            raise RuntimeError("SentenceTransformerVectorizer has not been fitted yet")
        return self._model.encode(list(X), show_progress_bar=False)

    def fit_transform(self, X, y=None):
        self.fit(X, y)
        return self.transform(X)


def make_image_vectorizer(model_name: str = None, cache_dir: str = None,
                          image_root: str = None):
    """
    The image counterpart of SentenceTransformerVectorizer.

    Lives in ``potato.vision_features`` and is imported lazily here, so a text
    project never loads CLIP. Because it exposes the same fit/transform
    surface, every QueryStrategy below works on images WITHOUT modification --
    uncertainty, diversity, BADGE, BALD and hybrid are all unchanged code.
    """
    from potato.vision_features import (DEFAULT_IMAGE_MODEL,
                                        ImageEmbeddingVectorizer)

    return ImageEmbeddingVectorizer(
        model_name=model_name or DEFAULT_IMAGE_MODEL,
        cache_dir=cache_dir,
        image_root=image_root,
    )


#: Schema types whose items are images rather than text. Active learning ranks
#: these by visual similarity; ranking them by `get_text()` would sort on the
#: filename, which is worse than random because it is systematically wrong.
VISUAL_SCHEMA_TYPES = {"image_annotation", "video_annotation"}


def feature_for_item(item, schema_type: str, source_field: str = None) -> str:
    """
    What the vectorizer should see for one item.

    Text for a text schema; the image reference for a visual one. This single
    branch is the whole of what made active learning text-only: every strategy
    already worked on whatever features it was handed.
    """
    if schema_type in VISUAL_SCHEMA_TYPES:
        data = getattr(item, "data", None) or {}
        if source_field and data.get(source_field):
            return str(data[source_field])
        for key in ("image_url", "image", "image_path", "file_name",
                    "video_url", "url"):
            if data.get(key):
                return str(data[key])
    return item.get_text()


# ---------------------------------------------------------------------------
# Query Strategies
# ---------------------------------------------------------------------------

class QueryStrategy(ABC):
    """Base class for active learning query strategies."""

    @abstractmethod
    def rank(self, texts: List[str], model, vectorizer,
             annotated_texts: Optional[List[str]] = None) -> List[Tuple[int, float]]:
        """Return list of (index, score) sorted by selection priority (highest first)."""


class UncertaintySampling(QueryStrategy):
    """Select instances where classifier is least confident.

    Selects x* = argmax_x (1 - max_y P(y|x)), i.e., instances where the
    model's best guess has lowest confidence.
    """

    def rank(self, texts, model, vectorizer, annotated_texts=None):
        try:
            features = vectorizer.transform(texts)
            probas = model.predict_proba(features)
            # Score = 1 - max_prob (higher = more uncertain = higher priority)
            scores = 1.0 - np.max(probas, axis=1)
            ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
            return ranked
        except Exception as e:
            logger.warning(f"UncertaintySampling failed: {e}")
            return [(i, 0.5) for i in range(len(texts))]


class DiversitySampling(QueryStrategy):
    """Select instances that maximize feature-space coverage.

    Uses cosine distance from already-annotated instances in the vectorized
    feature space. Ensures the training set covers the full data distribution
    rather than over-sampling one region.
    """

    def rank(self, texts, model, vectorizer, annotated_texts=None):
        from sklearn.metrics.pairwise import cosine_distances

        try:
            features = vectorizer.transform(texts)
            if hasattr(features, 'toarray'):
                features = features.toarray()

            if annotated_texts:
                annotated_features = vectorizer.transform(annotated_texts)
                if hasattr(annotated_features, 'toarray'):
                    annotated_features = annotated_features.toarray()
                # Score = min cosine distance to any annotated instance
                distances = cosine_distances(features, annotated_features)
                scores = np.min(distances, axis=1)
            else:
                # No annotated texts yet: use distance from centroid
                centroid = np.mean(features, axis=0, keepdims=True)
                scores = cosine_distances(features, centroid).ravel()

            ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
            return ranked
        except Exception as e:
            logger.warning(f"DiversitySampling failed: {e}")
            return [(i, 0.5) for i in range(len(texts))]


class BadgeStrategy(QueryStrategy):
    """BADGE approximation: uncertainty-weighted diversity.

    Inspired by Ash et al. (2020) [Ref 1]. Full BADGE uses gradient embeddings
    from neural networks. Our approximation:
      1. Weight feature vectors by (1 - max_prob) as uncertainty proxy
      2. Run k-means++ initialization on weighted vectors to select
         diverse-uncertain instances.
    """

    def rank(self, texts, model, vectorizer, annotated_texts=None):
        try:
            features = vectorizer.transform(texts)
            if hasattr(features, 'toarray'):
                features = features.toarray()

            probas = model.predict_proba(features)
            uncertainty = 1.0 - np.max(probas, axis=1)

            # Weight features by uncertainty
            weighted = features * uncertainty[:, np.newaxis]

            # Use k-means++ initialization to select diverse-uncertain points
            from sklearn.cluster import kmeans_plusplus
            n_clusters = min(len(texts), max(1, len(texts) // 2))
            _, indices = kmeans_plusplus(weighted, n_clusters=n_clusters,
                                        random_state=42)

            # Build score: selected centroids get highest scores
            scores = np.zeros(len(texts))
            for rank_pos, idx in enumerate(indices):
                scores[idx] = len(indices) - rank_pos  # highest for first-selected

            # For non-selected, use uncertainty as tiebreaker
            for i in range(len(texts)):
                if scores[i] == 0:
                    scores[i] = uncertainty[i] * 0.01

            ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
            return ranked
        except Exception as e:
            logger.warning(f"BadgeStrategy failed, falling back to uncertainty: {e}")
            return UncertaintySampling().rank(texts, model, vectorizer, annotated_texts)


class BaldStrategy(QueryStrategy):
    """BALD: Bayesian Active Learning by Disagreement.

    Based on Houlsby et al. (2011) [Ref 2]. Trains an ensemble of classifiers
    with different random seeds/bootstrap samples. Selects instances with
    highest mutual information: H[y|x] - E_theta[H[y|x,theta]], i.e.,
    where the ensemble disagrees most.
    """

    def __init__(self, n_estimators: int = 5, bootstrap_fraction: float = 0.8):
        self.n_estimators = n_estimators
        self.bootstrap_fraction = bootstrap_fraction

    def rank(self, texts, model, vectorizer, annotated_texts=None):
        try:
            features = vectorizer.transform(texts)
            if hasattr(features, 'toarray'):
                features = features.toarray()

            probas = model.predict_proba(features)
            # Average entropy
            avg_proba = probas
            entropy_avg = -np.sum(avg_proba * np.log(avg_proba + 1e-10), axis=1)

            # For a single model, we approximate BALD by using dropout-like noise
            # or by comparing with uniform. Since we store the ensemble models
            # on the manager, we just use the single model's entropy here and
            # the ensemble version is handled in ActiveLearningManager._train_bald_ensemble
            scores = entropy_avg
            ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
            return ranked
        except Exception as e:
            logger.warning(f"BaldStrategy failed: {e}")
            return [(i, 0.5) for i in range(len(texts))]

    def rank_with_ensemble(self, texts, ensemble_models, vectorizer):
        """Rank using actual ensemble disagreement (mutual information)."""
        try:
            features = vectorizer.transform(texts)
            if hasattr(features, 'toarray'):
                features = features.toarray()

            all_probas = []
            for m in ensemble_models:
                all_probas.append(m.predict_proba(features))

            all_probas = np.array(all_probas)  # (n_estimators, n_samples, n_classes)

            # Mean prediction across ensemble
            mean_proba = np.mean(all_probas, axis=0)  # (n_samples, n_classes)

            # H[y|x] - entropy of mean prediction
            entropy_mean = -np.sum(mean_proba * np.log(mean_proba + 1e-10), axis=1)

            # E_theta[H[y|x,theta]] - mean of individual entropies
            individual_entropies = -np.sum(all_probas * np.log(all_probas + 1e-10), axis=2)
            mean_entropy = np.mean(individual_entropies, axis=0)

            # Mutual information = H[y|x] - E[H[y|x,theta]]
            mutual_info = entropy_mean - mean_entropy

            ranked = sorted(enumerate(mutual_info), key=lambda x: x[1], reverse=True)
            return ranked
        except Exception as e:
            logger.warning(f"BaldStrategy ensemble ranking failed: {e}")
            return [(i, 0.5) for i in range(len(texts))]


class HybridStrategy(QueryStrategy):
    """Weighted combination of uncertainty and diversity scores.

    Combines strategies with configurable weights. Default: 0.7 uncertainty +
    0.3 diversity.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or {"uncertainty": 0.7, "diversity": 0.3}

    def rank(self, texts, model, vectorizer, annotated_texts=None):
        try:
            strategies = {}
            if self.weights.get("uncertainty", 0) > 0:
                strategies["uncertainty"] = UncertaintySampling()
            if self.weights.get("diversity", 0) > 0:
                strategies["diversity"] = DiversitySampling()

            # Collect raw scores from each strategy
            all_scores = {}
            for name, strategy in strategies.items():
                rankings = strategy.rank(texts, model, vectorizer, annotated_texts)
                score_map = {idx: score for idx, score in rankings}
                all_scores[name] = score_map

            # Normalize each strategy's scores to [0, 1]
            for name in all_scores:
                vals = list(all_scores[name].values())
                min_val, max_val = min(vals), max(vals)
                rng = max_val - min_val if max_val > min_val else 1.0
                all_scores[name] = {
                    idx: (s - min_val) / rng for idx, s in all_scores[name].items()
                }

            # Weighted combination
            combined = {}
            for i in range(len(texts)):
                combined[i] = sum(
                    self.weights.get(name, 0) * all_scores.get(name, {}).get(i, 0)
                    for name in self.weights
                )

            ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)
            return ranked
        except Exception as e:
            logger.warning(f"HybridStrategy failed: {e}")
            return UncertaintySampling().rank(texts, model, vectorizer, annotated_texts)


# Strategy registry
STRATEGY_REGISTRY = {
    "uncertainty": UncertaintySampling,
    "diversity": DiversitySampling,
    "badge": BadgeStrategy,
    "bald": BaldStrategy,
    "hybrid": HybridStrategy,
}


def create_query_strategy(config: 'ActiveLearningConfig') -> QueryStrategy:
    """Create a query strategy from config."""
    strategy_name = config.query_strategy
    if strategy_name == "hybrid":
        return HybridStrategy(weights=config.hybrid_weights)
    elif strategy_name == "bald":
        params = config.bald_params
        return BaldStrategy(
            n_estimators=params.get("n_estimators", 5),
            bootstrap_fraction=params.get("bootstrap_fraction", 0.8),
        )
    elif strategy_name in STRATEGY_REGISTRY:
        return STRATEGY_REGISTRY[strategy_name]()
    else:
        logger.warning(f"Unknown strategy '{strategy_name}', falling back to uncertainty")
        return UncertaintySampling()


# ---------------------------------------------------------------------------
# ICLClassifier wrapper (Phase 5A)
# ---------------------------------------------------------------------------

class ICLClassifier:
    """Wraps ICLLabeler as an sklearn-compatible classifier for ensemble use.

    Enables combining LLM-based ICL predictions with traditional classifier
    predictions in a hybrid ensemble for active learning scoring.
    """

    def __init__(self, icl_labeler, schema_name: str, label_names: List[str]):
        self.icl_labeler = icl_labeler
        self.schema_name = schema_name
        self.label_names = label_names
        self.classes_ = np.array(label_names)

    def predict_proba(self, texts: List[str]) -> np.ndarray:
        """Get label probabilities from LLM via ICL."""
        n_classes = len(self.label_names)
        probas = np.full((len(texts), n_classes), 1.0 / n_classes)

        for i, text in enumerate(texts):
            try:
                prediction = self.icl_labeler.label_instance(
                    instance_id=f"_al_query_{i}",
                    schema_name=self.schema_name,
                    instance_text=text,
                )
                if prediction and prediction.predicted_label in self.label_names:
                    idx = self.label_names.index(prediction.predicted_label)
                    conf = prediction.confidence_score
                    # Distribute: conf to predicted label, (1-conf)/(n-1) to others
                    remaining = (1.0 - conf) / max(1, n_classes - 1)
                    probas[i] = remaining
                    probas[i, idx] = conf
            except Exception:
                pass  # Keep uniform distribution

        return probas


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ActiveLearningConfig:
    """Enhanced configuration for active learning."""
    enabled: bool = False
    classifier_name: str = "sklearn.linear_model.LogisticRegression"
    classifier_kwargs: Dict[str, Any] = None
    vectorizer_name: str = "sklearn.feature_extraction.text.TfidfVectorizer"
    vectorizer_kwargs: Dict[str, Any] = None
    min_annotations_per_instance: int = 1
    min_instances_for_training: int = 10
    max_instances_to_reorder: Optional[int] = None
    resolution_strategy: ResolutionStrategy = ResolutionStrategy.MAJORITY_VOTE
    random_sample_percent: float = 0.2
    update_frequency: int = 5
    schema_names: List[str] = None

    # Classifier/vectorizer passthrough params (Phase 1C)
    classifier_params: Dict[str, Any] = field(default_factory=dict)
    vectorizer_params: Dict[str, Any] = field(default_factory=dict)

    # Probability calibration (Phase 1D)
    calibrate_probabilities: bool = True

    # Query strategy (Phase 2)
    query_strategy: str = "uncertainty"
    hybrid_weights: Dict[str, float] = field(
        default_factory=lambda: {"uncertainty": 0.7, "diversity": 0.3}
    )
    bald_params: Dict[str, Any] = field(
        default_factory=lambda: {"n_estimators": 5, "bootstrap_fraction": 0.8}
    )

    # Cold-start (Phase 3)
    cold_start_strategy: str = "random"
    cold_start_batch_size: int = 20

    # ICL ensemble (Phase 5)
    use_icl_ensemble: bool = False
    icl_ensemble_params: Dict[str, Any] = field(default_factory=lambda: {
        "initial_icl_weight": 0.7,
        "final_icl_weight": 0.2,
        "transition_instances": 100,
    })

    # Annotation routing (Phase 5D)
    annotation_routing: bool = False
    routing_thresholds: Dict[str, float] = field(default_factory=lambda: {
        "auto_label_min_confidence": 0.9,
        "show_suggestion_below": 0.5,
    })
    verification_sample_rate: float = 0.2

    # `database_enabled` / `database_config` were removed. They gated a
    # persistence layer whose every method was a stub, so setting them changed
    # nothing except a log line claiming success. Run history is now always
    # recorded, through the same SQLite layer as the rest of the project, and
    # needs no configuration. Both keys are ignored if still present in a
    # config file.

    # Model persistence
    model_persistence_enabled: bool = False
    model_save_directory: Optional[str] = None
    model_retention_count: int = 2

    # LLM integration
    llm_enabled: bool = False
    llm_config: Dict[str, Any] = None

    #: The project config dict, carried so the run ledger can find `task_dir`
    #: and `annotation_task_name`. Empty means "record nothing", which is what
    #: unit tests that construct this dataclass directly want.
    project_config: Dict[str, Any] = field(default_factory=dict)

    #: ``{schema_name: annotation_type}`` and ``{schema_name: source_field}``,
    #: so ``feature_for_item`` can hand a visual schema its image reference
    #: instead of the item's text.
    schema_types: Dict[str, str] = field(default_factory=dict)
    schema_source_fields: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if self.classifier_kwargs is None:
            self.classifier_kwargs = {}
        if self.vectorizer_kwargs is None:
            self.vectorizer_kwargs = {}
        if self.schema_names is None:
            self.schema_names = []
        if self.llm_config is None:
            self.llm_config = {}
        # Merge classifier_params into classifier_kwargs
        if self.classifier_params:
            self.classifier_kwargs.update(self.classifier_params)
        # Merge vectorizer_params into vectorizer_kwargs
        if self.vectorizer_params:
            self.vectorizer_kwargs.update(self.vectorizer_params)


@dataclass
class TrainingMetrics:
    """Metrics for a training run."""
    schema_name: str
    training_time: float
    accuracy: float
    instance_count: int
    timestamp: datetime
    model_file_path: Optional[str] = None
    confidence_distribution: Dict[str, float] = None
    error_message: Optional[str] = None


class ModelPersistence:
    """Handles model saving and loading with metadata."""

    def __init__(self, save_directory: str, retention_count: int = 2):
        self.save_directory = save_directory
        self.retention_count = retention_count
        self.logger = logging.getLogger(__name__)

        # Ensure directory exists
        os.makedirs(save_directory, exist_ok=True)

    def save_model(self, model: Pipeline, schema_name: str, instance_count: int) -> str:
        """Save a trained model with metadata."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{schema_name}_{instance_count}_{timestamp}.pkl"
        filepath = os.path.join(self.save_directory, filename)

        try:
            # Save the complete model (including vectorizer)
            with open(filepath, 'wb') as f:
                pickle.dump(model, f)

            self.logger.info(f"Saved model to {filepath}")

            # Clean up old models
            self._cleanup_old_models(schema_name)

            return filepath
        except Exception as e:
            self.logger.error(f"Failed to save model: {e}")
            raise

    def load_model(self, filepath: str) -> Optional[Pipeline]:
        """Load a saved model."""
        try:
            with open(filepath, 'rb') as f:
                model = pickle.load(f)

            # TODO: Add schema validation here in the future
            # This is a placeholder for future schema validation enhancement

            self.logger.info(f"Loaded model from {filepath}")
            return model
        except Exception as e:
            self.logger.error(f"Failed to load model from {filepath}: {e}")
            return None

    def _cleanup_old_models(self, schema_name: str):
        """Clean up old models based on retention policy."""
        try:
            # Find all model files for this schema
            model_files = []

            for filename in os.listdir(self.save_directory):
                if filename.startswith(f"{schema_name}_") and filename.endswith(".pkl"):
                    filepath = os.path.join(self.save_directory, filename)
                    model_files.append((filepath, os.path.getmtime(filepath)))

            # Sort by modification time (newest first)
            model_files.sort(key=lambda x: x[1], reverse=True)

            # Remove old models beyond retention count
            for filepath, _ in model_files[self.retention_count:]:
                try:
                    os.remove(filepath)
                    self.logger.info(f"Removed old model: {filepath}")
                except Exception as e:
                    self.logger.warning(f"Failed to remove old model {filepath}: {e}")

        except Exception as e:
            self.logger.error(f"Error during model cleanup: {e}")


# `DatabaseStateManager` used to live here: a stub that logged "Active
# learning database initialized successfully" while creating no tables, saving
# no metrics, and returning an empty training history forever. Its replacement
# is `potato.training.store`, which is backed by the same SQLite layer as the
# rest of the project.


class SchemaCycler:
    """Manages cycling through multiple annotation schemes."""

    def __init__(self, schema_names: List[str], state_path: Optional[str] = None):
        self.schema_names = self._validate_schemas(schema_names)
        #: Where the cursor is remembered across restarts. A JSON file rather
        #: than a table because nothing ever queries this -- it is read once at
        #: startup and written once per advance.
        self.state_path = state_path
        self.current_index = 0
        self.logger = logging.getLogger(__name__)
        self._lock = threading.Lock()

        if self.state_path:
            self._load_state()

    def _validate_schemas(self, schema_names: List[str]) -> List[str]:
        """Validate and filter schema names."""
        valid_schemas = []

        for schema in schema_names:
            # Exclude text and span annotation schemes
            if schema in ['text', 'span']:
                raise ValueError(f"Text and span annotation schemes are not supported for active learning: {schema}")
            valid_schemas.append(schema)

        return valid_schemas

    def _load_state(self):
        """Restore the cursor from disk, if there is one."""
        try:
            if not os.path.isfile(self.state_path):
                return
            with open(self.state_path) as fh:
                state = json.load(fh)
            current_schema = state.get("current_schema")
            with self._lock:
                if current_schema in self.schema_names:
                    self.current_index = self.schema_names.index(current_schema)
        except Exception as e:
            self.logger.warning(f"Failed to load schema cycling state: {e}")

    def _save_state(self, current_schema: str):
        """Persist the cursor. Best effort -- losing it only restarts the cycle."""
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            with open(self.state_path, "w") as fh:
                json.dump({"current_schema": current_schema,
                           "schema_order": self.schema_names}, fh)
        except Exception as e:
            self.logger.warning(f"Failed to save schema cycling state: {e}")

    def get_current_schema(self) -> Optional[str]:
        """Get the current schema for training."""
        if not self.schema_names:
            return None
        with self._lock:
            return self.schema_names[self.current_index]

    def advance_schema(self):
        """Advance to the next schema in the cycle."""
        if not self.schema_names:
            return

        with self._lock:
            self.current_index = (self.current_index + 1) % len(self.schema_names)
            current_schema = self.schema_names[self.current_index]

        if self.state_path:
            self._save_state(current_schema)

    def get_schema_order(self) -> List[str]:
        """Get the current schema cycling order."""
        return self.schema_names.copy()


class ActiveLearningManager:
    """
    Manages active learning operations including classifier training and instance reordering.

    This class provides thread-safe operations for:
    - Training classifiers on annotated data
    - Predicting confidence scores for unlabeled instances
    - Reordering instances based on configurable query strategies
    - Cold-start LLM-based instance selection
    - ICL/classifier ensemble for improved ranking
    - Noise-aware annotation routing
    - Managing training state and progress
    - Database persistence and model saving
    """

    def __init__(self, config: ActiveLearningConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Thread safety. Two locks on purpose: `_lock` guards the fitted
        # models and is held by the training worker, while `_counter_lock`
        # guards only the annotation counter and is taken on the request
        # thread. Sharing one lock made every annotator wait out every fit.
        self._lock = threading.RLock()
        self._counter_lock = threading.Lock()
        self._training_queue = queue.Queue()
        self._training_thread = None
        self._stop_training = threading.Event()

        # State tracking
        self._last_training_time = 0
        self._training_count = 0
        self._models = {}  # schema_name -> trained_model
        self._vectorizers = {}  # schema_name -> fitted vectorizer
        self._bald_ensembles = {}  # schema_name -> list of classifiers
        self._last_annotation_count = 0
        self._training_metrics = []  # List of TrainingMetrics
        self._annotated_texts = {}  # schema_name -> list of annotated texts

        # Query strategy
        self._query_strategy = create_query_strategy(config)

        # Database and persistence
        self.database_manager = None
        self.model_persistence = None
        self.schema_cycler = None

        # Initialize components
        self._initialize_components()

        # Start training thread if enabled
        if self.config.enabled:
            self._start_training_thread()

    def _initialize_components(self):
        """Initialize model persistence and the schema cycler."""
        # Initialize model persistence if enabled
        if self.config.model_persistence_enabled and self.config.model_save_directory:
            try:
                self.model_persistence = ModelPersistence(
                    self.config.model_save_directory,
                    self.config.model_retention_count
                )
            except Exception as e:
                self.logger.error(f"Failed to initialize model persistence: {e}")
                # Continue without model persistence

        # Initialize schema cycler
        try:
            self.schema_cycler = SchemaCycler(
                self.config.schema_names, self._cycler_state_path())
        except Exception as e:
            self.logger.error(f"Failed to initialize schema cycler: {e}")
            raise  # Schema cycler is critical

    def _cycler_state_path(self) -> Optional[str]:
        """Where the schema cursor lives, or ``None`` with no output dir."""
        cfg = self.config.project_config or {}
        output_dir = cfg.get("output_annotation_dir")
        if not output_dir:
            return None
        return os.path.join(cfg.get("task_dir", "."), output_dir,
                            "training", "cycler.json")

    def _start_training_thread(self):
        """Start the background training thread."""
        if self._training_thread is None or not self._training_thread.is_alive():
            self._training_thread = threading.Thread(target=self._training_worker, daemon=True)
            self._training_thread.start()
            self.logger.info("Active learning training thread started")

    def _training_worker(self):
        """Background worker for training classifiers."""
        while not self._stop_training.is_set():
            try:
                # Wait for training request
                training_request = self._training_queue.get(timeout=1.0)
                if training_request is None:  # Shutdown signal
                    break

                self._perform_training()
                self._training_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"Error in training worker: {e}")

    def _perform_training(self):
        """Perform the actual classifier training.

        Deliberately does **not** hold ``self._lock`` across the fit. The lock
        is also taken by ``check_and_trigger_training`` from the Flask request
        thread on every annotation save, so holding it through data collection,
        vectorization, calibration and pickling stalls every annotator for the
        duration of the fit. Only the state mutations at the end are guarded.
        """
        try:
            self.logger.info("Starting active learning classifier training")
            start_time = time.time()

            # Reading the cycler is cheap and the worker is the only writer.
            current_schema = self.schema_cycler.get_current_schema()
            if not current_schema:
                self.logger.warning("No schema available for training")
                return

            item_manager = get_item_state_manager()
            user_manager = get_user_state_manager()

            run = self._begin_run(current_schema)

            # --- everything below is unlocked -----------------------------
            training_data = self._collect_training_data(
                item_manager, user_manager, current_schema)

            if not training_data:
                self.logger.warning(
                    f"No training data available for schema {current_schema}")
                self._finish_run(run, status="error",
                                 error="no training data",
                                 error_code="no_data")
                if self.config.cold_start_strategy == "llm" and self.config.llm_enabled:
                    self._cold_start_reorder(item_manager)
                return

            model, metrics = self._train_classifier(training_data, current_schema)

            if not model:
                self.logger.warning(
                    f"Failed to train model for schema {current_schema}")
                self._finish_run(
                    run, status="error",
                    error=metrics.error_message if metrics else "fit failed",
                    error_code="fit_failed",
                    n_train=len(training_data.get("texts", [])))
                if (self.config.cold_start_strategy == "llm"
                        and self.config.llm_enabled
                        and len(training_data.get("texts", [])) < self.config.min_instances_for_training):
                    self._cold_start_reorder(item_manager)
                return

            model_path = ""
            if self.model_persistence:
                try:
                    model_path = self.model_persistence.save_model(
                        model, current_schema, len(training_data["texts"]))
                    metrics.model_file_path = model_path
                except Exception as e:
                    self.logger.error(f"Failed to save model: {e}")

            # --- state mutation only ---------------------------------------
            with self._lock:
                self._models[current_schema] = model
                self._annotated_texts[current_schema] = training_data["texts"]
                self._training_metrics.append(metrics)
                # Bounded: this list is a debugging aid, the durable record is
                # the training_runs table.
                if len(self._training_metrics) > 100:
                    del self._training_metrics[:-100]
                self._training_count += 1
                self._last_training_time = time.time()

            self._finish_run(
                run, status="success", model_version=model_path,
                n_train=len(training_data["texts"]),
                metrics={"accuracy": metrics.accuracy,
                         "training_time": metrics.training_time,
                         "instance_count": metrics.instance_count})

            # Reordering reads the model we just installed and writes the
            # item manager's own queue; it does not need our lock.
            self._reorder_instances(item_manager, current_schema)
            self.schema_cycler.advance_schema()

            self.logger.info(
                f"Active learning training completed for schema {current_schema} "
                f"(run #{self._training_count}, "
                f"duration: {time.time() - start_time:.2f}s)")

        except Exception as e:
            self.logger.error(f"Error during training: {e}", exc_info=True)
            # Continue without failing the entire system

    def _begin_run(self, schema_name: str):
        """Open a ``training_runs`` row, or ``None`` if the store is unusable.

        Returning ``None`` rather than raising keeps a broken ledger from
        stopping the training it is only supposed to be recording.
        """
        if not self.config.project_config:
            return None
        try:
            from potato.training.store import TrainingRun, new_run_id, record_run
            run = TrainingRun(
                run_id=new_run_id(), trainer="active-learning-sklearn",
                schema_names=[schema_name], status="running", trigger="auto",
                started_at=time.time(),
                params={"classifier": self.config.classifier_name,
                        "vectorizer": self.config.vectorizer_name,
                        "query_strategy": self.config.query_strategy})
            record_run(self.config.project_config, run)
            return run
        except Exception:
            self.logger.debug("Could not open a training run record",
                              exc_info=True)
            return None

    def _finish_run(self, run, status: str, **fields) -> None:
        """Close a run record. A no-op when the ledger is unavailable."""
        if run is None:
            return
        try:
            from potato.training.store import record_run
            run.status = status
            run.finished_at = time.time()
            for key, value in fields.items():
                setattr(run, key, value)
            record_run(self.config.project_config, run)
        except Exception:
            self.logger.debug("Could not close training run record",
                              exc_info=True)

    def _collect_training_data(self, item_manager: ItemStateManager, user_manager, schema_name: str) -> Dict:
        """Collect training data for a specific schema."""
        training_data = {"texts": [], "labels": [], "instance_ids": []}

        # Get all user states
        user_states = user_manager.get_all_users()
        self.logger.debug(f"Found {len(user_states)} user states")

        # Collect annotations per instance
        instance_annotations = defaultdict(list)

        for user_state in user_states:
            user_annotations = user_state.get_all_annotations()
            self.logger.debug(f"User {user_state.user_id} has {len(user_annotations)} annotations")
            for instance_id, annotations in user_annotations.items():
                # Check if the schema exists in the labels section
                if 'labels' in annotations:
                    labels_dict = annotations['labels']
                    # Handle Label objects as keys
                    for label_obj, value in labels_dict.items():
                        if hasattr(label_obj, 'get_schema') and label_obj.get_schema() == schema_name:
                            instance_annotations[instance_id].append({
                                "label": label_obj.get_name(),
                                "value": value,
                                "user": user_state.user_id
                            })

        self.logger.debug(f"Collected annotations for {len(instance_annotations)} instances")

        # Filter instances with sufficient annotations
        for instance_id, annotations in instance_annotations.items():
            if len(annotations) >= self.config.min_annotations_per_instance:
                # Resolve multiple annotations
                resolved_label = self._resolve_annotations(annotations)
                if resolved_label:
                    item = item_manager.get_item(instance_id)
                    if item:
                        text = feature_for_item(
                            item,
                            self.config.schema_types.get(schema_name, ""),
                            self.config.schema_source_fields.get(schema_name))
                        training_data["texts"].append(text)
                        training_data["labels"].append(resolved_label)
                        training_data["instance_ids"].append(instance_id)

        self.logger.debug(f"Training data collected: {len(training_data['texts'])} texts, {len(training_data['labels'])} labels")
        return training_data

    def _resolve_annotations(self, annotations: List[Dict]) -> Optional[str]:
        """Resolve multiple annotations using the configured strategy."""
        if not annotations:
            return None

        if self.config.resolution_strategy == ResolutionStrategy.MAJORITY_VOTE:
            return self._majority_vote(annotations)
        elif self.config.resolution_strategy == ResolutionStrategy.RANDOM:
            return self._random_selection(annotations)
        elif self.config.resolution_strategy == ResolutionStrategy.CONSENSUS:
            return self._consensus_resolution(annotations)
        else:
            return self._majority_vote(annotations)  # Default fallback

    def _majority_vote(self, annotations: List[Dict]) -> str:
        """Resolve annotations using majority vote with random tie-breaking."""
        label_counts = Counter(ann["label"] for ann in annotations)
        max_count = max(label_counts.values())
        # Find all labels with the maximum count (handles ties)
        tied_labels = [label for label, count in label_counts.items() if count == max_count]
        # Break ties randomly
        return random.choice(tied_labels)

    def _random_selection(self, annotations: List[Dict]) -> str:
        """Resolve annotations by random selection."""
        return random.choice(annotations)["label"]

    def _consensus_resolution(self, annotations: List[Dict]) -> Optional[str]:
        """Resolve annotations by consensus (all must agree)."""
        labels = [ann["label"] for ann in annotations]
        if len(set(labels)) == 1:
            return labels[0]
        return None

    def _train_classifier(self, training_data: Dict, schema_name: str) -> Tuple[Optional[Pipeline], TrainingMetrics]:
        """Train a classifier for a specific schema."""
        start_time = time.time()

        if len(training_data["texts"]) < self.config.min_instances_for_training:
            error_msg = f"Insufficient training data for schema {schema_name}: {len(training_data['texts'])} < {self.config.min_instances_for_training}"
            self.logger.warning(error_msg)
            return None, TrainingMetrics(
                schema_name=schema_name,
                training_time=time.time() - start_time,
                accuracy=0.0,
                instance_count=len(training_data["texts"]),
                timestamp=datetime.now(),
                error_message=error_msg
            )

        # Check for sufficient label diversity
        unique_labels = set(training_data["labels"])
        if len(unique_labels) < 2:
            error_msg = f"Insufficient label diversity for schema {schema_name}: {len(unique_labels)} unique labels"
            self.logger.warning(error_msg)
            return None, TrainingMetrics(
                schema_name=schema_name,
                training_time=time.time() - start_time,
                accuracy=0.0,
                instance_count=len(training_data["texts"]),
                timestamp=datetime.now(),
                error_message=error_msg
            )

        try:
            # Create and train classifier
            classifier = self._create_classifier()
            vectorizer = self._create_vectorizer()

            pipeline = Pipeline([
                ("vectorizer", vectorizer),
                ("classifier", classifier)
            ])

            pipeline.fit(training_data["texts"], training_data["labels"])

            # Apply probability calibration, and keep it only if it helped.
            #
            # This used to fit `CalibratedClassifierCV(cv=min(3, n // 2),
            # method='isotonic')` on anything with five or more samples. On a
            # small training set that does not calibrate the model, it
            # destroys it: isotonic regression fitted over three folds of a
            # dozen examples collapses every prediction to an identical
            # probability. Because active learning trains from
            # `min_instances_for_training` (10 by default), the shipped
            # default path went straight into that regime -- and a model whose
            # confidence is constant makes uncertainty sampling rank every
            # instance equally, so the queue ordering became arbitrary while
            # the logs reported a successful fit.
            from potato.training.calibration import calibrate_if_it_helps

            calibration = calibrate_if_it_helps(
                pipeline, training_data["texts"], training_data["labels"],
                enabled=self.config.calibrate_probabilities,
                log=lambda level, msg: getattr(self.logger, level,
                                               self.logger.info)(msg))
            pipeline = calibration.model

            # Store vectorizer separately for strategy use
            self._vectorizers[schema_name] = pipeline.named_steps.get("vectorizer", vectorizer) if hasattr(pipeline, 'named_steps') else vectorizer

            # Train BALD ensemble if needed
            if self.config.query_strategy == "bald":
                self._train_bald_ensemble(training_data, schema_name)

            # Calculate accuracy
            predictions = pipeline.predict(training_data["texts"])
            accuracy = accuracy_score(training_data["labels"], predictions)

            # Calculate confidence distribution
            confidence_distribution = self._calculate_confidence_distribution(pipeline, training_data["texts"])

            training_time = time.time() - start_time

            metrics = TrainingMetrics(
                schema_name=schema_name,
                training_time=training_time,
                accuracy=accuracy,
                instance_count=len(training_data["texts"]),
                timestamp=datetime.now(),
                confidence_distribution=confidence_distribution
            )

            self.logger.info(f"Trained classifier for schema {schema_name} with {len(training_data['texts'])} instances, "
                           f"accuracy: {accuracy:.3f}, time: {training_time:.2f}s")

            return pipeline, metrics

        except Exception as e:
            error_msg = f"Error training classifier for schema {schema_name}: {e}"
            self.logger.error(error_msg)
            return None, TrainingMetrics(
                schema_name=schema_name,
                training_time=time.time() - start_time,
                accuracy=0.0,
                instance_count=len(training_data["texts"]),
                timestamp=datetime.now(),
                error_message=error_msg
            )

    def _train_bald_ensemble(self, training_data: Dict, schema_name: str):
        """Train an ensemble of classifiers for BALD strategy."""
        params = self.config.bald_params
        n_estimators = params.get("n_estimators", 5)
        bootstrap_fraction = params.get("bootstrap_fraction", 0.8)

        texts = training_data["texts"]
        labels = training_data["labels"]
        n_samples = len(texts)
        bootstrap_size = max(2, int(n_samples * bootstrap_fraction))

        ensemble = []
        for i in range(n_estimators):
            indices = np.random.choice(n_samples, size=bootstrap_size, replace=True)
            boot_texts = [texts[j] for j in indices]
            boot_labels = [labels[j] for j in indices]

            # Need at least 2 classes
            if len(set(boot_labels)) < 2:
                continue

            clf = self._create_classifier()
            vec = self._create_vectorizer()
            pipe = Pipeline([("vectorizer", vec), ("classifier", clf)])
            pipe.fit(boot_texts, boot_labels)
            ensemble.append(pipe)

        if ensemble:
            self._bald_ensembles[schema_name] = ensemble
            self.logger.info(f"Trained BALD ensemble with {len(ensemble)} models for {schema_name}")

    def _calculate_confidence_distribution(self, pipeline, texts: List[str]) -> Dict[str, float]:
        """Calculate confidence score distribution."""
        try:
            probas = pipeline.predict_proba(texts)
            max_confidences = np.max(probas, axis=1)

            # Create histogram bins
            bins = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
            hist, _ = np.histogram(max_confidences, bins=bins)

            # Convert to percentages
            total = len(max_confidences)
            distribution = {}
            for i, count in enumerate(hist):
                bin_label = f"{bins[i]:.1f}-{bins[i+1]:.1f}"
                distribution[bin_label] = (count / total) * 100 if total > 0 else 0

            return distribution
        except Exception as e:
            self.logger.warning(f"Failed to calculate confidence distribution: {e}")
            return {}

    def _create_classifier(self):
        """Create classifier instance based on configuration."""
        kwargs = dict(self.config.classifier_kwargs)

        if self.config.classifier_name == "sklearn.linear_model.LogisticRegression":
            return LogisticRegression(**kwargs)
        elif self.config.classifier_name == "sklearn.ensemble.RandomForestClassifier":
            return RandomForestClassifier(**kwargs)
        elif self.config.classifier_name == "sklearn.svm.SVC":
            kwargs.setdefault("probability", True)
            return SVC(**kwargs)
        else:
            # Try to import dynamically
            try:
                module_name, class_name = self.config.classifier_name.rsplit('.', 1)
                module = __import__(module_name, fromlist=[class_name])
                classifier_class = getattr(module, class_name)
                return classifier_class(**kwargs)
            except Exception as e:
                self.logger.error(f"Failed to create classifier {self.config.classifier_name}: {e}")
                return LogisticRegression()  # Fallback

    def _create_vectorizer(self):
        """Create vectorizer instance based on configuration."""
        kwargs = dict(self.config.vectorizer_kwargs)

        if self.config.vectorizer_name == "sklearn.feature_extraction.text.CountVectorizer":
            return CountVectorizer(**kwargs)
        elif self.config.vectorizer_name == "sklearn.feature_extraction.text.TfidfVectorizer":
            return TfidfVectorizer(**kwargs)
        elif self.config.vectorizer_name == "sentence-transformers":
            model_name = kwargs.pop("model_name", "all-MiniLM-L6-v2")
            return SentenceTransformerVectorizer(model_name=model_name)
        else:
            # Try to import dynamically
            try:
                module_name, class_name = self.config.vectorizer_name.rsplit('.', 1)
                module = __import__(module_name, fromlist=[class_name])
                vectorizer_class = getattr(module, class_name)
                return vectorizer_class(**kwargs)
            except Exception as e:
                self.logger.error(f"Failed to create vectorizer {self.config.vectorizer_name}: {e}")
                return TfidfVectorizer()  # Fallback

    def _reorder_instances(self, item_manager: ItemStateManager, schema_name: str):
        """Reorder instances based on the configured query strategy."""
        if schema_name not in self._models:
            self.logger.warning(f"No trained model available for schema {schema_name}")
            return

        # Rank over exactly the pool the ACTIVE_LEARNING assignment strategy
        # serves. Ranking "items with no annotator at all" instead silently
        # excludes every partially-annotated item whenever
        # max_annotations_per_item > 1, so the ordering never covers the queue
        # it is meant to be ordering.
        schema_type = self.config.schema_types.get(schema_name, "")
        source_field = self.config.schema_source_fields.get(schema_name)

        candidates = list(item_manager.get_remaining_instance_ids())
        if not candidates:
            self.logger.info("No unlabeled instances to reorder")
            return

        # Cap by sampling, not by slicing. Slicing takes the head of the file
        # in store order, so with a cap set the model only ever ranks the first
        # N items and the tail can never surface however uncertain it is.
        limit = self.config.max_instances_to_reorder
        if limit and len(candidates) > limit:
            candidates = random.sample(candidates, limit)

        unlabeled_instances = []
        unlabeled_texts = []
        for instance_id in candidates:
            item = item_manager.get_item(instance_id)
            if item:
                unlabeled_instances.append(instance_id)
                unlabeled_texts.append(
                    feature_for_item(item, schema_type, source_field))

        if not unlabeled_texts:
            self.logger.info("No unlabeled instances to reorder")
            return

        model = self._models[schema_name]
        annotated = self._annotated_texts.get(schema_name, [])

        # Get rankings from strategy
        if (self.config.query_strategy == "bald"
                and schema_name in self._bald_ensembles
                and isinstance(self._query_strategy, BaldStrategy)):
            vectorizer = self._vectorizers.get(schema_name)
            if vectorizer:
                rankings = self._query_strategy.rank_with_ensemble(
                    unlabeled_texts, self._bald_ensembles[schema_name], vectorizer
                )
            else:
                rankings = self._query_strategy.rank(unlabeled_texts, model, model, annotated)
        else:
            # Extract vectorizer and classifier from pipeline for strategy use
            vectorizer = self._vectorizers.get(schema_name)
            classifier = model
            if vectorizer:
                rankings = self._query_strategy.rank(
                    unlabeled_texts, classifier, vectorizer, annotated
                )
            else:
                # Fallback: use confidence scores directly
                instance_scores = self._calculate_confidence_scores(
                    unlabeled_instances, item_manager, schema_name
                )
                sorted_instances = sorted(instance_scores, key=lambda x: x[1])
                self._apply_reordering(sorted_instances, item_manager)
                return

        # ICL ensemble blending (Phase 5B)
        if self.config.use_icl_ensemble:
            rankings = self._blend_icl_scores(
                rankings, unlabeled_texts, schema_name
            )

        # Map rankings back to instance IDs
        sorted_instances = [
            (unlabeled_instances[idx], score) for idx, score in rankings
            if idx < len(unlabeled_instances)
        ]

        # Apply reordering with random sampling
        self._apply_reordering(sorted_instances, item_manager)

    def _blend_icl_scores(self, rankings: List[Tuple[int, float]],
                          texts: List[str], schema_name: str) -> List[Tuple[int, float]]:
        """Blend query strategy scores with ICL predictions."""
        try:
            from potato.ai.icl_labeler import get_icl_labeler
            icl_labeler = get_icl_labeler()
            if icl_labeler is None or not icl_labeler.has_enough_examples(schema_name):
                return rankings

            # Determine interpolation weight based on annotation count
            params = self.config.icl_ensemble_params
            initial_w = params.get("initial_icl_weight", 0.7)
            final_w = params.get("final_icl_weight", 0.2)
            transition = params.get("transition_instances", 100)

            annotated_count = len(self._annotated_texts.get(schema_name, []))
            progress = min(1.0, annotated_count / max(1, transition))
            icl_weight = initial_w + (final_w - initial_w) * progress
            strategy_weight = 1.0 - icl_weight

            # Get ICL confidence for each text
            icl_scores = {}
            for idx, text in enumerate(texts):
                try:
                    pred = icl_labeler.label_instance(
                        instance_id=f"_al_blend_{idx}",
                        schema_name=schema_name,
                        instance_text=text,
                    )
                    if pred:
                        # Lower confidence = higher priority (more uncertain)
                        icl_scores[idx] = 1.0 - pred.confidence_score
                    else:
                        icl_scores[idx] = 0.5
                except Exception:
                    icl_scores[idx] = 0.5

            # Normalize strategy scores
            strategy_map = {idx: score for idx, score in rankings}
            s_vals = list(strategy_map.values())
            s_min, s_max = min(s_vals), max(s_vals)
            s_rng = s_max - s_min if s_max > s_min else 1.0

            # Normalize ICL scores
            i_vals = list(icl_scores.values())
            i_min, i_max = min(i_vals), max(i_vals)
            i_rng = i_max - i_min if i_max > i_min else 1.0

            blended = []
            for idx, score in rankings:
                norm_s = (score - s_min) / s_rng
                norm_i = (icl_scores.get(idx, 0.5) - i_min) / i_rng
                combined = strategy_weight * norm_s + icl_weight * norm_i
                blended.append((idx, combined))

            blended.sort(key=lambda x: x[1], reverse=True)
            return blended

        except ImportError:
            return rankings
        except Exception as e:
            self.logger.warning(f"ICL blending failed: {e}")
            return rankings

    def _cold_start_reorder(self, item_manager: ItemStateManager):
        """LLM-based cold-start instance selection (Phase 3A).

        Based on Bayer et al. (2024) ActiveLLM approach. Before enough
        annotations exist for classifier training, use LLM to estimate
        which instances are most informative by finding those where LLM
        confidence is moderate (on the decision boundary).
        """
        try:
            from potato.ai.llm_active_learning import create_llm_active_learning

            llm = create_llm_active_learning(self.config.llm_config)

            # Sample candidate instances
            all_ids = list(item_manager.get_instance_ids())
            unannotated = [
                iid for iid in all_ids
                if not item_manager.get_annotators_for_item(iid)
            ]

            if not unannotated:
                return

            batch_size = min(self.config.cold_start_batch_size, len(unannotated))
            candidates = random.sample(unannotated, batch_size)

            instances = []
            for iid in candidates:
                item = item_manager.get_item(iid)
                if item:
                    instances.append({"id": iid, "text": item.get_text()})

            if not instances:
                return

            # Get LLM predictions
            schema_name = self.schema_cycler.get_current_schema() if self.schema_cycler else None
            predictions = llm.predict_instances(
                instances=instances,
                annotation_instructions="Rate your confidence in labeling this text.",
                schema_name=schema_name or "default",
                label_options=["positive", "negative", "neutral"],
            )

            # Select instances with moderate confidence (decision boundary)
            moderate = []
            other = []
            for pred in predictions:
                if 0.4 <= pred.confidence_score <= 0.7:
                    moderate.append((pred.instance_id, pred.confidence_score))
                else:
                    other.append((pred.instance_id, pred.confidence_score))

            # Moderate-confidence first, then others, interleaved with random
            reordered = [iid for iid, _ in moderate] + [iid for iid, _ in other]

            # Add remaining unannotated instances not in the sample
            sampled_set = set(candidates)
            remaining = [iid for iid in unannotated if iid not in sampled_set]
            random.shuffle(remaining)
            reordered.extend(remaining)

            item_manager.reorder_instances(reordered)
            self.logger.info(f"Cold-start LLM reordering: {len(moderate)} moderate-confidence, "
                           f"{len(other)} other, {len(remaining)} remaining")

        except Exception as e:
            self.logger.warning(f"Cold-start LLM reordering failed: {e}")

    def _calculate_confidence_scores(
            self, instance_ids: List[str], item_manager: ItemStateManager,
            schema_name: str) -> List[Tuple[str, float]]:
        """Confidence per instance, for the no-vectorizer fallback path."""
        instance_scores = []
        model = self._models[schema_name]

        for instance_id in instance_ids:
            item = item_manager.get_item(instance_id)
            if not item:
                continue

            text = feature_for_item(
                item, self.config.schema_types.get(schema_name, ""),
                self.config.schema_source_fields.get(schema_name))

            try:
                probas = model.predict_proba([text])[0]
                confidence = np.max(probas)
                instance_scores.append((instance_id, confidence))
            except Exception as e:
                self.logger.warning(
                    f"Error predicting for instance {instance_id}: {e}")
                # Default to low confidence for failed predictions
                instance_scores.append((instance_id, 0.1))

        return instance_scores

    # `_route_annotation` used to sit here. It read LLM confidence from
    # `icl_labeler`, never the trained classifier's `predict_proba`, and had no
    # caller anywhere in the tree -- so "auto-label" was a contract nothing
    # implemented and nothing invoked. `routing_thresholds` and
    # `verification_sample_rate` survive as config keys and are re-earned by
    # the training subsystem, where an auto-label means "write a prediction and
    # let model review adjudicate it" rather than "silently invent an
    # annotation".

        """Calculate confidence scores for instances."""
        instance_scores = []
        model = self._models[schema_name]

        for instance_id in instance_ids:
            item = item_manager.get_item(instance_id)
            if not item:
                continue

            text = feature_for_item(
                item, self.config.schema_types.get(schema_name, ""),
                self.config.schema_source_fields.get(schema_name))

            try:
                # Get prediction probabilities
                probas = model.predict_proba([text])[0]
                confidence = np.max(probas)
                instance_scores.append((instance_id, confidence))
            except Exception as e:
                self.logger.warning(f"Error predicting for instance {instance_id}: {e}")
                # Default to low confidence for failed predictions
                instance_scores.append((instance_id, 0.1))

        return instance_scores

    def _apply_reordering(self, sorted_instances: List[Tuple[str, float]], item_manager: ItemStateManager):
        """Apply the new ordering to the item manager."""
        # Extract instance IDs in new order
        new_order = [instance_id for instance_id, _ in sorted_instances]

        if not new_order:
            return

        # Split the ranking into an exploitation head and an exploration tail,
        # then interleave. Sampling from `new_order` as a whole and
        # interleaving that back in put every sampled id into the result
        # twice -- roughly random_sample_percent of the queue duplicated on
        # each reorder. Partitioning instead means each id appears exactly
        # once, and exploration still surfaces items the model ranked low.
        random_count = int(len(new_order) * self.config.random_sample_percent)
        random_count = max(0, min(random_count, len(new_order)))

        if random_count:
            head = new_order[:-random_count] if random_count < len(new_order) else []
            tail = new_order[len(head):]
            random.shuffle(tail)
        else:
            head, tail = new_order, []

        # Interleave active learning and random instances
        final_order = []
        al_idx = 0
        rand_idx = 0

        while al_idx < len(head) or rand_idx < len(tail):
            if al_idx < len(head):
                final_order.append(head[al_idx])
                al_idx += 1
            if rand_idx < len(tail):
                final_order.append(tail[rand_idx])
                rand_idx += 1

        # Update item manager ordering
        item_manager.reorder_instances(final_order)
        self.logger.info(
            f"Reordered {len(final_order)} instances "
            f"({len(head)} ranked, {len(tail)} exploration)")

    def check_and_trigger_training(self):
        """Check if training should be triggered and queue it if needed.

        Runs on the Flask request thread after every annotation save, so it
        must return promptly. It takes ``_counter_lock`` -- which is only ever
        held for the length of a comparison -- and never ``_lock``, which the
        training worker holds while installing a fitted model.
        """
        if not self.config.enabled:
            self.logger.debug("Active learning is disabled")
            return

        # Count current annotations
        user_manager = get_user_state_manager()
        current_annotation_count = sum(
            len(user_state.get_all_annotations())
            for user_state in user_manager.get_all_users()
        )

        with self._counter_lock:
            delta = current_annotation_count - self._last_annotation_count
            self.logger.debug(
                f"Current annotation count: {current_annotation_count}, "
                f"last count: {self._last_annotation_count}, "
                f"update_frequency: {self.config.update_frequency}")

            if delta < self.config.update_frequency:
                self.logger.debug("Not enough new annotations to trigger training")
                return

            # Claim the delta inside the lock so two concurrent saves cannot
            # both queue a run for the same annotations.
            self._last_annotation_count = current_annotation_count

        self._training_queue.put("train")
        self.logger.info(
            f"Queued active learning training "
            f"(annotations: {current_annotation_count})")

    def force_training(self):
        """Force immediate training (for testing purposes)."""
        if not self.config.enabled:
            self.logger.debug("Active learning is disabled")
            return

        self.logger.info("Forcing immediate active learning training")
        self._training_queue.put("train")

    def get_stats(self) -> Dict[str, Any]:
        """Get active learning statistics."""
        with self._lock:
            stats = {
                "enabled": self.config.enabled,
                "training_count": self._training_count,
                "last_training_time": self._last_training_time,
                "models_trained": list(self._models.keys()),
                "current_schema": self.schema_cycler.get_current_schema() if self.schema_cycler else None,
                "schema_order": self.schema_cycler.get_schema_order() if self.schema_cycler else [],
                "model_persistence_enabled": self.config.model_persistence_enabled,
                "llm_enabled": self.config.llm_enabled,
                "query_strategy": self.config.query_strategy,
                "calibrate_probabilities": self.config.calibrate_probabilities,
                "cold_start_strategy": self.config.cold_start_strategy,
                "use_icl_ensemble": self.config.use_icl_ensemble,
                "annotation_routing": self.config.annotation_routing,
            }

            # In-process metrics, newest last. The durable history lives in
            # `training_runs` and is read below.
            stats["recent_metrics"] = [asdict(m) for m in self._training_metrics[-20:]]

        # Outside the lock: this touches SQLite, and no caller of get_stats()
        # should be able to block a fit.
        stats["training_history"] = []
        if self.config.project_config:
            try:
                from potato.training.store import list_runs
                stats["training_history"] = [
                    run.to_dict() for run in
                    list_runs(self.config.project_config, limit=20)]
            except Exception as e:
                self.logger.warning(f"Failed to get training history: {e}")

        return stats

    def shutdown(self):
        """Shutdown the active learning manager."""
        self._stop_training.set()
        if self._training_thread and self._training_thread.is_alive():
            self._training_queue.put(None)  # Shutdown signal
            self._training_thread.join(timeout=5.0)
        self.logger.info("Active learning manager shutdown complete")


# Global singleton instance
ACTIVE_LEARNING_MANAGER = None


def parse_active_learning_config(config_data: Dict[str, Any]) -> Optional[ActiveLearningConfig]:
    """Build an ``ActiveLearningConfig`` from a Potato project config dict.

    Returns None when active learning is not enabled. Maps the keys under the
    ``active_learning:`` section onto the dataclass fields (unknown keys are
    ignored), and defaults ``schema_names`` to the project's labelable
    annotation schemes when not given.
    """
    al_dict = (config_data or {}).get("active_learning", {}) or {}
    if not al_dict.get("enabled"):
        return None

    valid_fields = {f.name for f in dataclasses.fields(ActiveLearningConfig)}
    kwargs = {k: v for k, v in al_dict.items() if k in valid_fields}

    # Accept the nested blocks the guide documents alongside the flat keys.
    # There used to be a second parser that understood only the nested form,
    # and it was the one the docs described and the tests exercised while
    # production ran this one -- so a config written from the documentation
    # silently fell back to defaults.
    for block, mapping in (
        ("classifier", {"name": "classifier_name",
                        "hyperparameters": "classifier_kwargs"}),
        ("vectorizer", {"name": "vectorizer_name",
                        "hyperparameters": "vectorizer_kwargs"}),
        ("model_persistence", {"enabled": "model_persistence_enabled",
                               "save_directory": "model_save_directory",
                               "retention_count": "model_retention_count"}),
    ):
        nested = al_dict.get(block)
        if isinstance(nested, dict):
            for src, dest in mapping.items():
                if src in nested:
                    kwargs.setdefault(dest, nested[src])

    # Honor the nested `active_learning.llm:` block (LLM cold-start / ICL).
    # The dataclass uses flat fields (llm_enabled / llm_config), so translate.
    llm_block = al_dict.get("llm")
    if isinstance(llm_block, dict):
        kwargs.setdefault("llm_enabled", bool(llm_block.get("enabled", False)))
        kwargs.setdefault("llm_config", llm_block)

    # YAML parses sequences as lists, but sklearn's vectorizers require a tuple
    # for ngram_range (e.g. (1, 2)). Coerce it so training doesn't fail.
    vec_params = kwargs.get("vectorizer_params")
    if isinstance(vec_params, dict) and isinstance(vec_params.get("ngram_range"), list):
        vec_params = dict(vec_params)
        vec_params["ngram_range"] = tuple(vec_params["ngram_range"])
        kwargs["vectorizer_params"] = vec_params

    # resolution_strategy may arrive as a string; coerce to the enum.
    rs = kwargs.get("resolution_strategy")
    if isinstance(rs, str):
        try:
            kwargs["resolution_strategy"] = ResolutionStrategy(rs)
        except ValueError:
            kwargs.pop("resolution_strategy", None)

    schemes = config_data.get("annotation_schemes", []) or []

    # Default schema_names to every scheme that has something learnable to
    # predict. Hard-coding four nominal types excluded ordinal, continuous,
    # multilabel and geometry schemes that the strategies handle perfectly
    # well; SchemaKind already classifies all 60-odd types and is tested.
    if not kwargs.get("schema_names"):
        try:
            from potato.server_utils.iaa.dispatcher import (SchemaKind,
                                                            classify_schema)
            kwargs["schema_names"] = [
                s["name"] for s in schemes
                if s.get("name")
                and classify_schema(s) not in (SchemaKind.TEXT,
                                               SchemaKind.UNSUPPORTED)]
        except Exception:
            logger.debug("Could not classify schemes; falling back to the "
                         "nominal types", exc_info=True)
            kwargs["schema_names"] = [
                s.get("name") for s in schemes
                if s.get("name") and s.get("annotation_type") in (
                    "radio", "multiselect", "likert", "select")]

    # Carry enough of the project config for the run ledger and for
    # feature_for_item to tell an image schema from a text one.
    kwargs["project_config"] = config_data or {}
    kwargs["schema_types"] = {
        s["name"]: s.get("annotation_type", "")
        for s in schemes if s.get("name")}
    kwargs["schema_source_fields"] = {
        s["name"]: s["source_field"]
        for s in schemes if s.get("name") and s.get("source_field")}

    return ActiveLearningConfig(**kwargs)


def init_active_learning_manager(config: ActiveLearningConfig) -> ActiveLearningManager:
    """Initialize the global active learning manager."""
    global ACTIVE_LEARNING_MANAGER

    if ACTIVE_LEARNING_MANAGER is None:
        ACTIVE_LEARNING_MANAGER = ActiveLearningManager(config)

    return ACTIVE_LEARNING_MANAGER


def get_active_learning_manager() -> Optional[ActiveLearningManager]:
    """Get the global active learning manager."""
    return ACTIVE_LEARNING_MANAGER


def clear_active_learning_manager():
    """Clear the global active learning manager (for testing)."""
    global ACTIVE_LEARNING_MANAGER
    if ACTIVE_LEARNING_MANAGER:
        ACTIVE_LEARNING_MANAGER.shutdown()
    ACTIVE_LEARNING_MANAGER = None
