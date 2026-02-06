"""
Diversity Manager Module

Provides embedding-based clustering and round-robin sampling to maximize diversity
in annotation item ordering. Uses sentence-transformers for embeddings and k-means
clustering, then samples items from different clusters to ensure annotators see
diverse content rather than similar items in sequence.

Key Components:
- DiversityConfig: Configuration dataclass for diversity ordering
- ClusterState: Per-user cluster tracking for round-robin sampling
- DiversityManager: Main class for embeddings, clustering, and diverse ordering
- Singleton management: init/get/clear pattern matching other managers
"""

import json
import logging
import os
import pickle
import queue
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Guarded imports - same pattern as similarity.py
try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    from sklearn.cluster import KMeans
    _SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    _SENTENCE_TRANSFORMERS_AVAILABLE = False
    np = None
    KMeans = None

# Singleton
_DIVERSITY_MANAGER: Optional['DiversityManager'] = None
_DIVERSITY_LOCK = threading.Lock()


@dataclass
class DiversityConfig:
    """Configuration for diversity-based ordering."""
    enabled: bool = False
    model_name: str = "all-MiniLM-L6-v2"
    num_clusters: int = 10
    items_per_cluster: int = 20
    auto_clusters: bool = True
    prefill_count: int = 100
    batch_size: int = 32
    cache_dir: Optional[str] = None
    custom_embedding_function: Optional[Callable[[str], Any]] = None
    recluster_threshold: float = 1.0
    preserve_visited: bool = True
    trigger_ai_prefetch: bool = True


@dataclass
class ClusterState:
    """Per-user cluster tracking for round-robin sampling."""
    sampled_clusters: Set[int] = field(default_factory=set)
    cluster_sample_counts: Dict[int, int] = field(default_factory=dict)
    current_cluster_index: int = 0
    visited_instance_ids: Set[str] = field(default_factory=set)
    skipped_instance_ids: Set[str] = field(default_factory=set)
    last_recluster_time: Optional[datetime] = None


class DiversityManager:
    """
    Manages embedding-based clustering for diversity-aware item ordering.

    This class provides:
    - Sentence-transformer embeddings with configurable model
    - K-means clustering with auto-calculated cluster count
    - Round-robin cluster sampling for diverse ordering
    - Async embedding of new items after annotation
    - Re-clustering when user has sampled all clusters
    - Order preservation for annotated, visited, and skipped items
    - AI cache prefetch integration after reordering
    - Embedding persistence across server restarts
    """

    def __init__(self, config: DiversityConfig, app_config: Dict[str, Any]):
        """
        Initialize the diversity manager.

        Args:
            config: DiversityConfig instance with diversity settings
            app_config: Full application configuration dictionary
        """
        self.config = config
        self.app_config = app_config
        self.logger = logging.getLogger(__name__)
        self._lock = threading.RLock()

        # Core state
        self.enabled = False
        self.model = None
        self.embeddings: Dict[str, Any] = {}  # instance_id -> numpy array
        self.cluster_labels: Dict[str, int] = {}  # instance_id -> cluster_id
        self.cluster_members: Dict[int, List[str]] = {}  # cluster_id -> [instance_ids]
        self.user_cluster_states: Dict[str, ClusterState] = {}  # user_id -> state
        self.num_clusters: int = config.num_clusters

        # Threading for async operations
        self._embedding_executor = ThreadPoolExecutor(max_workers=4)
        self._pending_futures: Dict[str, Future] = {}

        # Check dependencies
        if not _SENTENCE_TRANSFORMERS_AVAILABLE:
            self.logger.warning(
                "sentence-transformers or scikit-learn not installed. "
                "Diversity ordering disabled. Install with: "
                "pip install sentence-transformers scikit-learn"
            )
            return

        if not config.enabled:
            self.logger.info("Diversity ordering disabled in config")
            return

        # Initialize model
        try:
            if config.custom_embedding_function:
                self.logger.info("Using custom embedding function")
                self._embed_function = config.custom_embedding_function
            else:
                self.logger.info(f"Loading sentence-transformer model: {config.model_name}")
                self.model = SentenceTransformer(config.model_name)
                self._embed_function = self._embed_with_model

            self.enabled = True
            self._load_cache()
            self.logger.info(
                f"Diversity manager ready: model={config.model_name}, "
                f"cached_embeddings={len(self.embeddings)}"
            )
        except Exception as e:
            self.logger.error(f"Failed to initialize diversity manager: {e}")
            self.enabled = False

    def _embed_with_model(self, texts: List[str]) -> Any:
        """Embed texts using the loaded sentence-transformer model."""
        return self.model.encode(texts, show_progress_bar=False)

    def _get_cache_dir(self) -> str:
        """Get the cache directory path."""
        if self.config.cache_dir:
            cache_dir = self.config.cache_dir
        else:
            output_dir = self.app_config.get("output_annotation_dir", "annotation_output")
            cache_dir = os.path.join(output_dir, ".diversity_cache")
        os.makedirs(cache_dir, exist_ok=True)
        return cache_dir

    def _save_cache(self) -> None:
        """Save embeddings and cluster labels to disk."""
        if not self.enabled:
            return

        try:
            cache_dir = self._get_cache_dir()

            # Save embeddings as pickle (numpy arrays)
            emb_path = os.path.join(cache_dir, "embeddings.pkl")
            with open(emb_path, "wb") as f:
                pickle.dump(self.embeddings, f)

            # Save cluster labels as JSON
            labels_path = os.path.join(cache_dir, "cluster_labels.json")
            with open(labels_path, "w") as f:
                json.dump(self.cluster_labels, f)

            self.logger.debug(f"Saved diversity cache: {len(self.embeddings)} embeddings")
        except Exception as e:
            self.logger.error(f"Failed to save diversity cache: {e}")

    def _load_cache(self) -> None:
        """Load cached embeddings and cluster labels from disk."""
        try:
            cache_dir = self._get_cache_dir()

            emb_path = os.path.join(cache_dir, "embeddings.pkl")
            if os.path.exists(emb_path):
                with open(emb_path, "rb") as f:
                    self.embeddings = pickle.load(f)

            labels_path = os.path.join(cache_dir, "cluster_labels.json")
            if os.path.exists(labels_path):
                with open(labels_path, "r") as f:
                    self.cluster_labels = json.load(f)
                # Rebuild cluster_members from labels
                self._rebuild_cluster_members()

            if self.embeddings:
                self.logger.info(f"Loaded {len(self.embeddings)} cached embeddings")
        except Exception as e:
            self.logger.warning(f"Failed to load diversity cache: {e}")
            self.embeddings = {}
            self.cluster_labels = {}

    def _rebuild_cluster_members(self) -> None:
        """Rebuild cluster_members dict from cluster_labels."""
        self.cluster_members = {}
        for instance_id, cluster_id in self.cluster_labels.items():
            if cluster_id not in self.cluster_members:
                self.cluster_members[cluster_id] = []
            self.cluster_members[cluster_id].append(instance_id)

    def compute_embedding(self, text: str) -> Optional[Any]:
        """
        Compute embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Numpy array embedding, or None if failed
        """
        if not self.enabled:
            return None

        try:
            embeddings = self._embed_function([text])
            return embeddings[0]
        except Exception as e:
            self.logger.error(f"Error computing embedding: {e}")
            return None

    def compute_embeddings_batch(
        self,
        texts: Dict[str, str],
        callback: Optional[Callable[[str, Any], None]] = None
    ) -> int:
        """
        Batch-encode texts and store embeddings.

        Args:
            texts: Mapping of instance_id to text content
            callback: Optional callback(instance_id, embedding) after each batch

        Returns:
            Number of new embeddings computed
        """
        if not self.enabled:
            return 0

        with self._lock:
            # Filter out already cached items
            new_items = {
                iid: text for iid, text in texts.items()
                if iid not in self.embeddings
            }

            if not new_items:
                return 0

            try:
                ids = list(new_items.keys())
                text_list = list(new_items.values())

                # Process in batches
                total_computed = 0
                batch_size = self.config.batch_size

                for i in range(0, len(text_list), batch_size):
                    batch_ids = ids[i:i + batch_size]
                    batch_texts = text_list[i:i + batch_size]

                    vecs = self._embed_function(batch_texts)

                    for j, iid in enumerate(batch_ids):
                        self.embeddings[iid] = vecs[j]
                        if callback:
                            callback(iid, vecs[j])

                    total_computed += len(batch_ids)

                self._save_cache()
                self.logger.info(f"Computed {total_computed} new embeddings")
                return total_computed

            except Exception as e:
                self.logger.error(f"Error computing embeddings batch: {e}")
                return 0

    def start_async_embedding(self, instance_id: str, text: str) -> Optional[Future]:
        """
        Start async embedding computation for a single item.

        Args:
            instance_id: The instance ID
            text: Text content to embed

        Returns:
            Future for the embedding computation
        """
        if not self.enabled:
            return None

        with self._lock:
            if instance_id in self.embeddings:
                return None  # Already computed

            if instance_id in self._pending_futures:
                return self._pending_futures[instance_id]

            def compute():
                emb = self.compute_embedding(text)
                if emb is not None:
                    with self._lock:
                        self.embeddings[instance_id] = emb
                        self._save_cache()
                return emb

            future = self._embedding_executor.submit(compute)
            self._pending_futures[instance_id] = future

            def cleanup(f):
                with self._lock:
                    self._pending_futures.pop(instance_id, None)

            future.add_done_callback(cleanup)
            return future

    def cluster_items(self, force: bool = False) -> bool:
        """
        Cluster items using k-means on embeddings.

        Args:
            force: Force re-clustering even if already clustered

        Returns:
            True if clustering was performed
        """
        if not self.enabled or not _SENTENCE_TRANSFORMERS_AVAILABLE:
            return False

        with self._lock:
            if not self.embeddings:
                self.logger.warning("No embeddings available for clustering")
                return False

            if self.cluster_labels and not force:
                self.logger.debug("Items already clustered, skipping")
                return False

            try:
                ids = list(self.embeddings.keys())
                vectors = np.array([self.embeddings[iid] for iid in ids])

                # Calculate number of clusters
                if self.config.auto_clusters:
                    n_items = len(ids)
                    target_size = self.config.items_per_cluster
                    self.num_clusters = max(2, min(n_items // target_size, n_items // 2))
                else:
                    self.num_clusters = min(self.config.num_clusters, len(ids))

                self.logger.info(f"Clustering {len(ids)} items into {self.num_clusters} clusters")

                kmeans = KMeans(n_clusters=self.num_clusters, random_state=42, n_init=10)
                labels = kmeans.fit_predict(vectors)

                # Store results
                self.cluster_labels = {}
                self.cluster_members = {}

                for i, iid in enumerate(ids):
                    cluster_id = int(labels[i])
                    self.cluster_labels[iid] = cluster_id
                    if cluster_id not in self.cluster_members:
                        self.cluster_members[cluster_id] = []
                    self.cluster_members[cluster_id].append(iid)

                self._save_cache()

                # Log cluster sizes
                sizes = [len(m) for m in self.cluster_members.values()]
                self.logger.info(
                    f"Clustering complete: {self.num_clusters} clusters, "
                    f"sizes range {min(sizes)}-{max(sizes)}, avg {sum(sizes)/len(sizes):.1f}"
                )
                return True

            except Exception as e:
                self.logger.error(f"Clustering failed: {e}")
                return False

    def get_user_cluster_state(self, user_id: str) -> ClusterState:
        """Get or create cluster state for a user."""
        with self._lock:
            if user_id not in self.user_cluster_states:
                self.user_cluster_states[user_id] = ClusterState()
            return self.user_cluster_states[user_id]

    def _get_next_cluster(self, user_id: str, available_clusters: Set[int]) -> Optional[int]:
        """
        Get the next cluster for round-robin sampling.

        Args:
            user_id: User identifier
            available_clusters: Set of clusters with available items

        Returns:
            Next cluster ID to sample from, or None if no clusters available
        """
        if not available_clusters:
            return None

        state = self.get_user_cluster_state(user_id)

        # Sort clusters for deterministic ordering
        sorted_clusters = sorted(available_clusters)

        # Find the next cluster that hasn't been fully sampled
        for _ in range(len(sorted_clusters)):
            # Cycle through clusters
            idx = state.current_cluster_index % len(sorted_clusters)
            cluster_id = sorted_clusters[idx]

            state.current_cluster_index = (state.current_cluster_index + 1) % len(sorted_clusters)

            if cluster_id in available_clusters:
                state.sampled_clusters.add(cluster_id)
                state.cluster_sample_counts[cluster_id] = state.cluster_sample_counts.get(cluster_id, 0) + 1
                return cluster_id

        return None

    def get_next_diverse_item(
        self,
        user_id: str,
        available_ids: Set[str]
    ) -> Optional[str]:
        """
        Get the next item for a user using round-robin cluster sampling.

        Args:
            user_id: User identifier
            available_ids: Set of available instance IDs

        Returns:
            Next instance ID to assign, or None if no items available
        """
        if not self.enabled or not self.cluster_labels:
            return None

        with self._lock:
            # Find clusters with available items
            available_by_cluster: Dict[int, List[str]] = {}
            for iid in available_ids:
                if iid in self.cluster_labels:
                    cluster_id = self.cluster_labels[iid]
                    if cluster_id not in available_by_cluster:
                        available_by_cluster[cluster_id] = []
                    available_by_cluster[cluster_id].append(iid)

            if not available_by_cluster:
                # No clustered items available
                return list(available_ids)[0] if available_ids else None

            # Get next cluster using round-robin
            next_cluster = self._get_next_cluster(user_id, set(available_by_cluster.keys()))

            if next_cluster is None:
                return None

            # Return first available item from the cluster
            return available_by_cluster[next_cluster][0]

    def generate_diverse_ordering(
        self,
        user_id: str,
        available_ids: List[str],
        preserve_ids: Set[str]
    ) -> List[str]:
        """
        Generate a diverse ordering of items with order preservation.

        Items in preserve_ids will maintain their original positions.
        Remaining items are reordered using round-robin cluster sampling.

        Args:
            user_id: User identifier
            available_ids: List of available instance IDs in current order
            preserve_ids: Set of instance IDs that should keep their positions

        Returns:
            New ordering of instance IDs
        """
        if not self.enabled or not self.cluster_labels:
            return available_ids

        with self._lock:
            state = self.get_user_cluster_state(user_id)

            # Combine all items to preserve
            all_preserve = preserve_ids | state.visited_instance_ids
            if self.config.preserve_visited:
                all_preserve |= state.skipped_instance_ids

            # Separate into preserved (keep position) and reorderable
            preserved_positions: List[Tuple[int, str]] = []
            reorderable: Set[str] = set()

            for i, iid in enumerate(available_ids):
                if iid in all_preserve:
                    preserved_positions.append((i, iid))
                else:
                    reorderable.add(iid)

            # Generate diverse order for reorderable items
            diverse_order: List[str] = []
            remaining = reorderable.copy()

            while remaining:
                next_item = self.get_next_diverse_item(user_id, remaining)
                if next_item:
                    diverse_order.append(next_item)
                    remaining.discard(next_item)
                else:
                    # Fallback: append remaining items
                    diverse_order.extend(sorted(remaining))
                    break

            # Merge preserved items back at their original positions
            result = diverse_order.copy()
            for orig_idx, iid in sorted(preserved_positions):
                insert_pos = min(orig_idx, len(result))
                result.insert(insert_pos, iid)

            return result

    def should_recluster(self, user_id: str) -> bool:
        """
        Check if reclustering should be triggered for a user.

        Returns True when user has sampled from all clusters (based on threshold).

        Args:
            user_id: User identifier

        Returns:
            True if reclustering is needed
        """
        if not self.enabled or not self.cluster_members:
            return False

        with self._lock:
            state = self.get_user_cluster_state(user_id)

            total_clusters = len(self.cluster_members)
            sampled_clusters = len(state.sampled_clusters)

            if total_clusters == 0:
                return False

            coverage = sampled_clusters / total_clusters
            return coverage >= self.config.recluster_threshold

    def trigger_recluster(self, user_id: str) -> bool:
        """
        Trigger reclustering and reset user's cluster state.

        Args:
            user_id: User identifier

        Returns:
            True if reclustering was performed
        """
        with self._lock:
            # Reset user's cluster sampling state
            state = self.get_user_cluster_state(user_id)
            state.sampled_clusters.clear()
            state.cluster_sample_counts.clear()
            state.current_cluster_index = 0
            state.last_recluster_time = datetime.now()

            # Force reclustering
            result = self.cluster_items(force=True)

            if result:
                self.logger.info(f"Reclustered items for user {user_id}")

            return result

    def mark_item_visited(self, user_id: str, instance_id: str) -> None:
        """Mark an item as visited by a user."""
        with self._lock:
            state = self.get_user_cluster_state(user_id)
            state.visited_instance_ids.add(instance_id)

    def mark_item_skipped(self, user_id: str, instance_id: str) -> None:
        """Mark an item as skipped by a user."""
        with self._lock:
            state = self.get_user_cluster_state(user_id)
            state.skipped_instance_ids.add(instance_id)

    def on_annotation_complete(
        self,
        user_id: str,
        instance_id: str,
        text: str
    ) -> None:
        """
        Handle annotation completion - compute embedding if needed.

        Args:
            user_id: User identifier
            instance_id: Instance that was annotated
            text: Text content of the instance
        """
        with self._lock:
            state = self.get_user_cluster_state(user_id)
            state.visited_instance_ids.add(instance_id)

        # Start async embedding if not already computed
        if instance_id not in self.embeddings:
            self.start_async_embedding(instance_id, text)

    def apply_to_user_ordering(
        self,
        user_id: str,
        available_ids: List[str],
        annotated_ids: Set[str]
    ) -> List[str]:
        """
        Apply diversity ordering to a user's available items.

        This is the main entry point for integrating with ItemStateManager.

        Args:
            user_id: User identifier
            available_ids: Available instance IDs in current order
            annotated_ids: Instance IDs the user has already annotated

        Returns:
            Diversely ordered list of instance IDs
        """
        if not self.enabled:
            return available_ids

        return self.generate_diverse_ordering(user_id, available_ids, annotated_ids)

    def get_stats(self) -> Dict[str, Any]:
        """Get diversity manager statistics."""
        with self._lock:
            cluster_sizes = {}
            if self.cluster_members:
                cluster_sizes = {
                    cid: len(members)
                    for cid, members in self.cluster_members.items()
                }

            return {
                "available": _SENTENCE_TRANSFORMERS_AVAILABLE,
                "enabled": self.enabled,
                "model": self.config.model_name,
                "embedding_count": len(self.embeddings),
                "cluster_count": len(self.cluster_members),
                "cluster_sizes": cluster_sizes,
                "num_users": len(self.user_cluster_states),
                "pending_embeddings": len(self._pending_futures),
            }

    def shutdown(self) -> None:
        """Shutdown the diversity manager."""
        self._embedding_executor.shutdown(wait=False)
        self.logger.info("Diversity manager shutdown complete")


def parse_diversity_config(config_data: Dict[str, Any]) -> DiversityConfig:
    """
    Parse diversity_ordering section from config into DiversityConfig.

    Args:
        config_data: Full application configuration

    Returns:
        DiversityConfig instance
    """
    dc = config_data.get("diversity_ordering", {})

    return DiversityConfig(
        enabled=dc.get("enabled", False),
        model_name=dc.get("model_name", "all-MiniLM-L6-v2"),
        num_clusters=dc.get("num_clusters", 10),
        items_per_cluster=dc.get("items_per_cluster", 20),
        auto_clusters=dc.get("auto_clusters", True),
        prefill_count=dc.get("prefill_count", 100),
        batch_size=dc.get("batch_size", 32),
        cache_dir=dc.get("cache_dir"),
        recluster_threshold=dc.get("recluster_threshold", 1.0),
        preserve_visited=dc.get("preserve_visited", True),
        trigger_ai_prefetch=dc.get("trigger_ai_prefetch", True),
    )


def init_diversity_manager(
    config_data: Dict[str, Any]
) -> Optional[DiversityManager]:
    """
    Initialize the singleton DiversityManager.

    Args:
        config_data: Full application configuration

    Returns:
        DiversityManager instance, or None if disabled
    """
    global _DIVERSITY_MANAGER

    with _DIVERSITY_LOCK:
        if _DIVERSITY_MANAGER is None:
            diversity_config = parse_diversity_config(config_data)

            # Check if diversity clustering is the assignment strategy
            assignment_strategy = config_data.get("assignment_strategy", "")
            if isinstance(assignment_strategy, dict):
                assignment_strategy = assignment_strategy.get("name", "")

            # Enable if strategy is diversity_clustering, even if diversity_ordering.enabled is false
            if assignment_strategy == "diversity_clustering" and not diversity_config.enabled:
                diversity_config.enabled = True

            _DIVERSITY_MANAGER = DiversityManager(diversity_config, config_data)

    return _DIVERSITY_MANAGER


def get_diversity_manager() -> Optional[DiversityManager]:
    """Get the singleton DiversityManager instance."""
    return _DIVERSITY_MANAGER


def clear_diversity_manager() -> None:
    """Clear the singleton (for testing)."""
    global _DIVERSITY_MANAGER
    with _DIVERSITY_LOCK:
        if _DIVERSITY_MANAGER is not None:
            _DIVERSITY_MANAGER.shutdown()
        _DIVERSITY_MANAGER = None
