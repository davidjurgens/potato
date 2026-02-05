"""
Similarity Engine Module

Provides semantic similarity search for adjudication items using
sentence-transformers embeddings. Uses a guarded import pattern so the
system degrades gracefully when sentence-transformers is not installed.

Key Components:
- SimilarityEngine: Manages embeddings, caching, and similarity search
- Singleton management: init/get/clear pattern matching other managers
"""

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Guarded import — same pattern as simpledorff in admin.py
try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    _SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    _SENTENCE_TRANSFORMERS_AVAILABLE = False

# Singleton
_SIMILARITY_ENGINE = None
_SIMILARITY_LOCK = threading.Lock()


class SimilarityEngine:
    """
    Manages sentence-transformer embeddings for finding semantically
    similar annotation items during adjudication.
    """

    def __init__(self, config: Dict[str, Any], adj_config):
        """
        Initialize the similarity engine.

        Args:
            config: Full application configuration
            adj_config: AdjudicationConfig dataclass instance
        """
        self.config = config
        self.adj_config = adj_config
        self.logger = logging.getLogger(__name__)
        self._lock = threading.Lock()

        self.enabled = False
        self.model = None
        self.embeddings = {}       # instance_id -> numpy array
        self.text_cache = {}       # instance_id -> text preview

        if not _SENTENCE_TRANSFORMERS_AVAILABLE:
            self.logger.warning(
                "sentence-transformers not installed. "
                "Similarity search disabled. Install with: "
                "pip install sentence-transformers"
            )
            return

        if not adj_config.similarity_enabled:
            return

        try:
            model_name = adj_config.similarity_model
            self.logger.info(f"Loading similarity model: {model_name}")
            self.model = SentenceTransformer(model_name)
            self.enabled = True
            self._load_cache()
            self.logger.info(
                f"Similarity engine ready: model={model_name}, "
                f"cached_embeddings={len(self.embeddings)}"
            )
        except Exception as e:
            self.logger.error(f"Failed to load similarity model: {e}")
            self.enabled = False

    def precompute_embeddings(self, item_texts: Dict[str, str]) -> int:
        """
        Batch-encode texts and store embeddings.

        Args:
            item_texts: Mapping of instance_id to text content

        Returns:
            Number of new embeddings computed
        """
        if not self.enabled or not self.model:
            return 0

        with self._lock:
            # Filter out items already cached
            new_items = {
                iid: text for iid, text in item_texts.items()
                if iid not in self.embeddings
            }

            if not new_items:
                return 0

            ids = list(new_items.keys())
            texts = list(new_items.values())

            try:
                vecs = self.model.encode(texts, show_progress_bar=False)
                for i, iid in enumerate(ids):
                    self.embeddings[iid] = vecs[i]
                    self.text_cache[iid] = texts[i][:200]  # preview

                self._save_cache()
                self.logger.info(f"Computed {len(ids)} new embeddings")
                return len(ids)
            except Exception as e:
                self.logger.error(f"Error computing embeddings: {e}")
                return 0

    def find_similar(
        self, instance_id: str, top_k: Optional[int] = None
    ) -> List[Tuple[str, float]]:
        """
        Find the most similar items to a given instance.

        Args:
            instance_id: The reference instance ID
            top_k: Number of results (defaults to config value)

        Returns:
            List of (instance_id, similarity_score) tuples, highest first
        """
        if not self.enabled or instance_id not in self.embeddings:
            return []

        if top_k is None:
            top_k = self.adj_config.similarity_top_k

        with self._lock:
            ref_vec = self.embeddings[instance_id]
            results = []

            for other_id, other_vec in self.embeddings.items():
                if other_id == instance_id:
                    continue
                score = self._cosine_similarity(ref_vec, other_vec)
                results.append((other_id, float(score)))

            results.sort(key=lambda x: x[1], reverse=True)
            return results[:top_k]

    def update_embedding(self, instance_id: str, text: str) -> bool:
        """
        Compute and store embedding for a single item.

        Args:
            instance_id: The instance ID
            text: The text content

        Returns:
            True if successful
        """
        if not self.enabled or not self.model:
            return False

        with self._lock:
            try:
                vec = self.model.encode([text], show_progress_bar=False)[0]
                self.embeddings[instance_id] = vec
                self.text_cache[instance_id] = text[:200]
                self._save_cache()
                return True
            except Exception as e:
                self.logger.error(f"Error updating embedding for {instance_id}: {e}")
                return False

    def get_stats(self) -> Dict[str, Any]:
        """Get similarity engine statistics."""
        return {
            "available": _SENTENCE_TRANSFORMERS_AVAILABLE,
            "enabled": self.enabled,
            "model": self.adj_config.similarity_model if self.adj_config else None,
            "embedding_count": len(self.embeddings),
            "top_k": self.adj_config.similarity_top_k if self.adj_config else None,
        }

    def _cosine_similarity(self, a, b) -> float:
        """Compute cosine similarity between two vectors."""
        dot = float(np.dot(a, b))
        norm_a = float(np.linalg.norm(a))
        norm_b = float(np.linalg.norm(b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _get_cache_dir(self) -> str:
        """Get the cache directory path."""
        output_dir = self.config.get("output_annotation_dir", "annotation_output")
        adj_subdir = self.adj_config.output_subdir if self.adj_config else "adjudication"
        cache_dir = os.path.join(output_dir, adj_subdir, ".similarity_cache")
        os.makedirs(cache_dir, exist_ok=True)
        return cache_dir

    def _save_cache(self) -> None:
        """Save embeddings and text cache to disk."""
        try:
            import pickle
            cache_dir = self._get_cache_dir()

            # Save embeddings as pickle (numpy arrays)
            emb_path = os.path.join(cache_dir, "embeddings.pkl")
            with open(emb_path, "wb") as f:
                pickle.dump(self.embeddings, f)

            # Save text cache as JSON
            text_path = os.path.join(cache_dir, "text_cache.json")
            with open(text_path, "w") as f:
                json.dump(self.text_cache, f)

        except Exception as e:
            self.logger.error(f"Failed to save similarity cache: {e}")

    def _load_cache(self) -> None:
        """Load cached embeddings and text previews from disk."""
        try:
            import pickle
            cache_dir = self._get_cache_dir()

            emb_path = os.path.join(cache_dir, "embeddings.pkl")
            if os.path.exists(emb_path):
                with open(emb_path, "rb") as f:
                    self.embeddings = pickle.load(f)

            text_path = os.path.join(cache_dir, "text_cache.json")
            if os.path.exists(text_path):
                with open(text_path, "r") as f:
                    self.text_cache = json.load(f)

            if self.embeddings:
                self.logger.info(
                    f"Loaded {len(self.embeddings)} cached embeddings"
                )
        except Exception as e:
            self.logger.warning(f"Failed to load similarity cache: {e}")
            self.embeddings = {}
            self.text_cache = {}


def init_similarity_engine(
    config: Dict[str, Any], adj_config
) -> Optional[SimilarityEngine]:
    """Initialize the singleton SimilarityEngine."""
    global _SIMILARITY_ENGINE

    with _SIMILARITY_LOCK:
        if _SIMILARITY_ENGINE is None:
            _SIMILARITY_ENGINE = SimilarityEngine(config, adj_config)

    return _SIMILARITY_ENGINE


def get_similarity_engine() -> Optional[SimilarityEngine]:
    """Get the singleton SimilarityEngine instance."""
    return _SIMILARITY_ENGINE


def clear_similarity_engine():
    """Clear the singleton (for testing)."""
    global _SIMILARITY_ENGINE
    with _SIMILARITY_LOCK:
        _SIMILARITY_ENGINE = None
