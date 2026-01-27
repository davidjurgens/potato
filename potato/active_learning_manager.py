"""
Enhanced Active Learning Manager with Database Persistence

This module provides a comprehensive active learning system with optional
database persistence, model saving, and LLM integration.
"""

import threading
import logging
import time
import os
import pickle
import json
from typing import Dict, List, Optional, Tuple, Any, Union
from collections import defaultdict, Counter
from dataclasses import dataclass, asdict
from enum import Enum
import random
import queue
from datetime import datetime

from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import SVC
from sklearn.metrics import accuracy_score, classification_report
import numpy as np

from potato.item_state_management import ItemStateManager, get_item_state_manager
from potato.user_state_management import get_user_state_manager


class ResolutionStrategy(Enum):
    """Strategies for resolving multiple annotations per instance."""
    MAJORITY_VOTE = "majority_vote"
    RANDOM = "random"
    CONSENSUS = "consensus"
    WEIGHTED_AVERAGE = "weighted_average"


@dataclass
class ActiveLearningConfig:
    """Enhanced configuration for active learning."""
    enabled: bool = False
    classifier_name: str = "sklearn.linear_model.LogisticRegression"
    classifier_kwargs: Dict[str, Any] = None
    vectorizer_name: str = "sklearn.feature_extraction.text.CountVectorizer"
    vectorizer_kwargs: Dict[str, Any] = None
    min_annotations_per_instance: int = 1
    min_instances_for_training: int = 10
    max_instances_to_reorder: Optional[int] = None
    resolution_strategy: ResolutionStrategy = ResolutionStrategy.MAJORITY_VOTE
    random_sample_percent: float = 0.2
    update_frequency: int = 5
    schema_names: List[str] = None

    # Database persistence
    database_enabled: bool = False
    database_config: Dict[str, Any] = None

    # Model persistence
    model_persistence_enabled: bool = False
    model_save_directory: Optional[str] = None
    model_retention_count: int = 2

    # LLM integration
    llm_enabled: bool = False
    llm_config: Dict[str, Any] = None

    def __post_init__(self):
        if self.classifier_kwargs is None:
            self.classifier_kwargs = {}
        if self.vectorizer_kwargs is None:
            self.vectorizer_kwargs = {}
        if self.schema_names is None:
            self.schema_names = []
        if self.database_config is None:
            self.database_config = {}
        if self.llm_config is None:
            self.llm_config = {}


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
            pattern = f"{schema_name}_*.pkl"
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


class DatabaseStateManager:
    """Manages database persistence for active learning state."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.connection = None
        self._initialize_database()

    def _initialize_database(self):
        """Initialize database connection and create tables."""
        try:
            # Use the same database system as main Potato application
            if self.config.get('type') == 'mysql':
                self._init_mysql_connection()
            else:
                self._init_file_based_connection()

            self._create_tables()
            self.logger.info("Active learning database initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}")
            raise

    def _init_mysql_connection(self):
        """Initialize MySQL connection."""
        # TODO: Implement MySQL connection
        # This will use similar connection logic as the main Potato database
        pass

    def _init_file_based_connection(self):
        """Initialize file-based database connection."""
        # TODO: Implement file-based database
        # This will use JSON files for state persistence
        pass

    def _create_tables(self):
        """Create database tables for active learning."""
        # TODO: Implement table creation
        # Tables: active_learning_state, training_history, model_metadata,
        # schema_cycling_state, confidence_distributions
        pass

    def save_training_metrics(self, metrics: TrainingMetrics):
        """Save training metrics to database."""
        # TODO: Implement metrics saving
        pass

    def get_training_history(self, schema_name: Optional[str] = None) -> List[TrainingMetrics]:
        """Get training history from database."""
        # TODO: Implement history retrieval
        return []

    def save_schema_cycling_state(self, current_schema: str, schema_order: List[str]):
        """Save current schema cycling state."""
        # TODO: Implement state saving
        pass

    def get_schema_cycling_state(self) -> Tuple[str, List[str]]:
        """Get current schema cycling state."""
        # TODO: Implement state retrieval
        return "", []


class SchemaCycler:
    """Manages cycling through multiple annotation schemes."""

    def __init__(self, schema_names: List[str], database_manager: Optional[DatabaseStateManager] = None):
        self.schema_names = self._validate_schemas(schema_names)
        self.database_manager = database_manager
        self.current_index = 0
        self.logger = logging.getLogger(__name__)
        self._lock = threading.Lock()

        # Load state from database if available
        if self.database_manager:
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
        """Load cycling state from database."""
        try:
            current_schema, schema_order = self.database_manager.get_schema_cycling_state()
            with self._lock:
                if current_schema in self.schema_names:
                    self.current_index = self.schema_names.index(current_schema)
        except Exception as e:
            self.logger.warning(f"Failed to load schema cycling state: {e}")

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

        # Save state to database if available
        if self.database_manager:
            try:
                self.database_manager.save_schema_cycling_state(
                    current_schema,
                    self.schema_names
                )
            except Exception as e:
                self.logger.warning(f"Failed to save schema cycling state: {e}")

    def get_schema_order(self) -> List[str]:
        """Get the current schema cycling order."""
        return self.schema_names.copy()


class ActiveLearningManager:
    """
    Manages active learning operations including classifier training and instance reordering.

    This class provides thread-safe operations for:
    - Training classifiers on annotated data
    - Predicting confidence scores for unlabeled instances
    - Reordering instances based on uncertainty
    - Managing training state and progress
    - Database persistence and model saving
    """

    def __init__(self, config: ActiveLearningConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Thread safety
        self._lock = threading.RLock()
        self._training_queue = queue.Queue()
        self._training_thread = None
        self._stop_training = threading.Event()

        # State tracking
        self._last_training_time = 0
        self._training_count = 0
        self._models = {}  # schema_name -> trained_model
        self._last_annotation_count = 0
        self._training_metrics = []  # List of TrainingMetrics

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
        """Initialize database, model persistence, and schema cycler."""
        # Initialize database manager if enabled
        if self.config.database_enabled:
            try:
                self.database_manager = DatabaseStateManager(self.config.database_config)
            except Exception as e:
                self.logger.error(f"Failed to initialize database manager: {e}")
                # Continue without database persistence

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
            self.schema_cycler = SchemaCycler(self.config.schema_names, self.database_manager)
        except Exception as e:
            self.logger.error(f"Failed to initialize schema cycler: {e}")
            raise  # Schema cycler is critical

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
        """Perform the actual classifier training."""
        with self._lock:
            try:
                self.logger.info("Starting active learning classifier training")
                start_time = time.time()

                # Get current schema for training
                current_schema = self.schema_cycler.get_current_schema()
                if not current_schema:
                    self.logger.warning("No schema available for training")
                    return

                # Get current annotation state
                item_manager = get_item_state_manager()
                user_manager = get_user_state_manager()

                # Collect training data
                training_data = self._collect_training_data(item_manager, user_manager, current_schema)

                if not training_data:
                    self.logger.warning(f"No training data available for schema {current_schema}")
                    return

                # Train classifier
                model, metrics = self._train_classifier(training_data, current_schema)

                if model:
                    self._models[current_schema] = model

                    # Save model if persistence is enabled
                    if self.model_persistence:
                        try:
                            model_path = self.model_persistence.save_model(
                                model, current_schema, len(training_data["texts"])
                            )
                            metrics.model_file_path = model_path
                        except Exception as e:
                            self.logger.error(f"Failed to save model: {e}")

                    # Save metrics to database if available
                    if self.database_manager:
                        try:
                            self.database_manager.save_training_metrics(metrics)
                        except Exception as e:
                            self.logger.error(f"Failed to save metrics: {e}")

                    # Reorder instances
                    self._reorder_instances(item_manager, current_schema)

                    # Advance to next schema
                    self.schema_cycler.advance_schema()

                    self._training_count += 1
                    self._last_training_time = time.time()

                    training_duration = time.time() - start_time
                    self.logger.info(f"Active learning training completed for schema {current_schema} "
                                   f"(run #{self._training_count}, duration: {training_duration:.2f}s)")
                else:
                    self.logger.warning(f"Failed to train model for schema {current_schema}")

            except Exception as e:
                self.logger.error(f"Error during training: {e}")
                # Continue without failing the entire system

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
                        text = item.get_text()
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

            # Calculate accuracy (simple approach - could be improved with cross-validation)
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

    def _calculate_confidence_distribution(self, pipeline: Pipeline, texts: List[str]) -> Dict[str, float]:
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
        if self.config.classifier_name == "sklearn.linear_model.LogisticRegression":
            return LogisticRegression(**self.config.classifier_kwargs)
        elif self.config.classifier_name == "sklearn.ensemble.RandomForestClassifier":
            return RandomForestClassifier(**self.config.classifier_kwargs)
        elif self.config.classifier_name == "sklearn.svm.SVC":
            return SVC(probability=True, **self.config.classifier_kwargs)
        else:
            # Try to import dynamically
            try:
                module_name, class_name = self.config.classifier_name.rsplit('.', 1)
                module = __import__(module_name, fromlist=[class_name])
                classifier_class = getattr(module, class_name)
                return classifier_class(**self.config.classifier_kwargs)
            except Exception as e:
                self.logger.error(f"Failed to create classifier {self.config.classifier_name}: {e}")
                return LogisticRegression()  # Fallback

    def _create_vectorizer(self):
        """Create vectorizer instance based on configuration."""
        if self.config.vectorizer_name == "sklearn.feature_extraction.text.CountVectorizer":
            return CountVectorizer(**self.config.vectorizer_kwargs)
        elif self.config.vectorizer_name == "sklearn.feature_extraction.text.TfidfVectorizer":
            return TfidfVectorizer(**self.config.vectorizer_kwargs)
        else:
            # Try to import dynamically
            try:
                module_name, class_name = self.config.vectorizer_name.rsplit('.', 1)
                module = __import__(module_name, fromlist=[class_name])
                vectorizer_class = getattr(module, class_name)
                return vectorizer_class(**self.config.vectorizer_kwargs)
            except Exception as e:
                self.logger.error(f"Failed to create vectorizer {self.config.vectorizer_name}: {e}")
                return CountVectorizer()  # Fallback

    def _reorder_instances(self, item_manager: ItemStateManager, schema_name: str):
        """Reorder instances based on model predictions."""
        if schema_name not in self._models:
            self.logger.warning(f"No trained model available for schema {schema_name}")
            return

        # Get unlabeled instances
        unlabeled_instances = []
        for instance_id in item_manager.get_instance_ids():
            if not item_manager.get_annotators_for_item(instance_id):
                unlabeled_instances.append(instance_id)

        if not unlabeled_instances:
            self.logger.info("No unlabeled instances to reorder")
            return

        # Limit number of instances to process
        if self.config.max_instances_to_reorder:
            unlabeled_instances = unlabeled_instances[:self.config.max_instances_to_reorder]

        # Calculate confidence scores
        instance_scores = self._calculate_confidence_scores(unlabeled_instances, item_manager, schema_name)

        # Sort by confidence (lowest first for active learning)
        sorted_instances = sorted(instance_scores, key=lambda x: x[1])

        # Apply reordering with random sampling
        self._apply_reordering(sorted_instances, item_manager)

    def _calculate_confidence_scores(self, instance_ids: List[str], item_manager: ItemStateManager, schema_name: str) -> List[Tuple[str, float]]:
        """Calculate confidence scores for instances."""
        instance_scores = []
        model = self._models[schema_name]

        for instance_id in instance_ids:
            item = item_manager.get_item(instance_id)
            if not item:
                continue

            text = item.get_text()

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

        # Apply random sampling
        random_count = int(len(new_order) * self.config.random_sample_percent)
        random_instances = random.sample(new_order, random_count)

        # Interleave active learning and random instances
        final_order = []
        al_idx = 0
        rand_idx = 0

        while al_idx < len(new_order) or rand_idx < len(random_instances):
            if al_idx < len(new_order):
                final_order.append(new_order[al_idx])
                al_idx += 1
            if rand_idx < len(random_instances):
                final_order.append(random_instances[rand_idx])
                rand_idx += 1

        # Update item manager ordering
        item_manager.reorder_instances(final_order)
        self.logger.info(f"Reordered {len(final_order)} instances")

    def check_and_trigger_training(self):
        """Check if training should be triggered and queue it if needed."""
        if not self.config.enabled:
            self.logger.debug("Active learning is disabled")
            return

        with self._lock:
            # Count current annotations
            user_manager = get_user_state_manager()
            current_annotation_count = sum(
                len(user_state.get_all_annotations())
                for user_state in user_manager.get_all_users()
            )

            self.logger.debug(f"Current annotation count: {current_annotation_count}, last count: {self._last_annotation_count}, update_frequency: {self.config.update_frequency}")

            # Check if we should trigger training
            if (current_annotation_count - self._last_annotation_count) >= self.config.update_frequency:
                self._training_queue.put("train")
                self._last_annotation_count = current_annotation_count
                self.logger.info(f"Queued active learning training (annotations: {current_annotation_count})")
            else:
                self.logger.debug("Not enough new annotations to trigger training")

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
                "database_enabled": self.config.database_enabled,
                "model_persistence_enabled": self.config.model_persistence_enabled,
                "llm_enabled": self.config.llm_enabled
            }

            # Add training metrics if available
            if self.database_manager:
                try:
                    stats["training_history"] = [
                        asdict(metrics) for metrics in self.database_manager.get_training_history()
                    ]
                except Exception as e:
                    self.logger.warning(f"Failed to get training history: {e}")
                    stats["training_history"] = []

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