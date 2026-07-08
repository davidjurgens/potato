"""
Corpus Map Manager

Ingest-time pipeline for multi-document annotation: embed every document, cluster
the corpus, project to 2D, and precompute per-document k-nearest-neighbors. The
result is a small JSON payload the annotator-facing corpus map consumes.

Reuse, not reinvention:
  - Embeddings + k-means clustering: `DiversityManager` (lazy sentence-transformers
    + sklearn, with .npz caching). We own a private instance so enabling the map
    does not require diversity-ordering to be on.
  - 2D projection: UMAP when available (same idiom as EmbeddingVisualizationManager),
    falling back to a pure-numpy PCA so the map still renders without umap-learn.
  - Cluster labels: `curation.discovery` LLM naming when configured, else the most
    distinctive terms per cluster (offline, deterministic).

Import-light: this module imports numpy eagerly (cheap) but defers
sentence-transformers / sklearn / umap to `build()` so importing it at boot is
safe.
"""

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_CORPUS_MAP_MANAGER: Optional["CorpusMapManager"] = None
_CORPUS_MAP_LOCK = threading.Lock()


class CorpusMapManager:
    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        cm = self.config.get("corpus_map", {}) or {}
        self.enabled = bool(cm.get("enabled", False))
        self.build_on_start = bool(cm.get("build_on_start", True))
        self.embedding_model = cm.get("embedding_model", "all-MiniLM-L6-v2")
        self.clustering_cfg = cm.get("clustering", {}) or {}
        self.umap_cfg = cm.get("umap", {}) or {}
        self.knn_cfg = cm.get("knn", {}) or {}
        self.labeling_cfg = cm.get("cluster_labeling", {}) or {}
        self.k = int(self.knn_cfg.get("k", 10))

        self._lock = threading.RLock()
        # doc_id -> {"x","y","cluster","snippet"}
        self._points: Dict[str, Dict[str, Any]] = {}
        # cluster_id -> {"label","description","size"}
        self._clusters: Dict[int, Dict[str, Any]] = {}
        # doc_id -> [[neighbor_id, score], ...]
        self._knn: Dict[str, List[List[Any]]] = {}
        self._status = {"state": "idle", "built": False, "n_docs": 0, "error": None}

        self._load_cache()

    # ---- paths / cache -----------------------------------------------------
    def _cache_dir(self) -> str:
        output_dir = self.config.get("output_annotation_dir", "annotation_output")
        d = os.path.join(output_dir, ".corpus_map_cache")
        os.makedirs(d, exist_ok=True)
        return d

    def _map_path(self) -> str:
        return os.path.join(self._cache_dir(), "corpus_map.json")

    def _load_cache(self) -> None:
        path = self._map_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                self._points = data.get("points", {})
                self._clusters = {int(k): v for k, v in data.get("clusters", {}).items()}
                self._knn = data.get("knn", {})
                self._status = data.get("status", self._status)
                self._status["built"] = bool(self._points)
            logger.info("Loaded corpus map cache: %d docs", len(self._points))
        except Exception as e:  # pragma: no cover - defensive
            logger.error("Failed to load corpus map cache: %s", e)

    def _save_cache(self) -> None:
        path = self._map_path()
        payload = {
            "points": self._points,
            "clusters": {str(k): v for k, v in self._clusters.items()},
            "knn": self._knn,
            "status": self._status,
        }
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception as e:  # pragma: no cover - defensive
            logger.error("Failed to save corpus map cache: %s", e)

    # ---- ingest ------------------------------------------------------------
    def _collect_texts(self) -> Dict[str, str]:
        """Pull {doc_id: text} from the item state manager."""
        from potato.item_state_management import get_item_state_manager

        ism = get_item_state_manager()
        text_key = (self.config.get("item_properties", {}) or {}).get("text_key")
        texts: Dict[str, str] = {}
        for iid in ism.get_instance_ids():
            item = ism.get_item(iid)
            data = item.get_data()
            text = None
            if text_key and isinstance(data, dict):
                text = data.get(text_key)
            if not text:
                text = item.get_text()
            texts[str(iid)] = text if isinstance(text, str) else str(text)
        return texts

    def _embed_and_cluster(self, texts: Dict[str, str]):
        """Embed + cluster via a private DiversityManager. Returns (embeddings, labels)."""
        from potato.diversity_manager import DiversityManager, DiversityConfig

        dcfg = DiversityConfig(
            enabled=True,
            model_name=self.embedding_model,
            num_clusters=int(self.clustering_cfg.get("num_clusters", 10))
            if str(self.clustering_cfg.get("num_clusters", "auto")).isdigit()
            else 10,
            items_per_cluster=int(self.clustering_cfg.get("items_per_cluster", 20)),
            auto_clusters=str(self.clustering_cfg.get("num_clusters", "auto")) == "auto",
            batch_size=int(self.clustering_cfg.get("batch_size", 32)),
            cache_dir=os.path.join(self._cache_dir(), "diversity"),
            custom_embedding_function=self.config.get("_corpus_map_embed_fn"),
        )
        dm = DiversityManager(dcfg, self.config)
        if not dm.enabled:
            raise RuntimeError(
                "Corpus map needs sentence-transformers + scikit-learn. "
                "Install them or set corpus_map.enabled: false."
            )
        dm.compute_embeddings_batch(texts)
        dm.cluster_items(force=True)
        return dict(dm.embeddings), dict(dm.cluster_labels)

    @staticmethod
    def _project_2d(embeddings: Dict[str, Any], umap_cfg: Dict[str, Any]) -> Dict[str, Tuple[float, float]]:
        """UMAP 2D projection with a pure-numpy PCA fallback."""
        import numpy as np

        ids = list(embeddings.keys())
        if not ids:
            return {}
        vectors = np.array([embeddings[i] for i in ids], dtype=float)
        n = len(ids)

        # Try UMAP first (better structure); fall back to PCA if unavailable.
        try:
            import umap  # lazy

            n_neighbors = min(int(umap_cfg.get("n_neighbors", 15)), n - 1)
            if n_neighbors >= 2:
                reducer = umap.UMAP(
                    n_neighbors=n_neighbors,
                    min_dist=float(umap_cfg.get("min_dist", 0.1)),
                    metric=umap_cfg.get("metric", "cosine"),
                    n_components=2,
                    random_state=42,
                )
                proj = reducer.fit_transform(vectors)
                return {ids[i]: (float(proj[i, 0]), float(proj[i, 1])) for i in range(n)}
        except Exception as e:
            logger.warning("UMAP unavailable/failed (%s); using PCA fallback", e)

        # PCA via SVD (deterministic).
        centered = vectors - vectors.mean(axis=0, keepdims=True)
        try:
            _, _, vt = np.linalg.svd(centered, full_matrices=False)
            comps = vt[:2]
            proj = centered @ comps.T
            return {ids[i]: (float(proj[i, 0]), float(proj[i, 1])) for i in range(n)}
        except Exception as e:  # pragma: no cover - defensive
            logger.error("PCA projection failed: %s", e)
            return {ids[i]: (0.0, 0.0) for i in range(n)}

    def _compute_knn(self, embeddings: Dict[str, Any]) -> Dict[str, List[List[Any]]]:
        """Cosine top-k neighbors, computed directly from embeddings (no eager ST)."""
        import numpy as np

        ids = list(embeddings.keys())
        if len(ids) < 2:
            return {i: [] for i in ids}
        mat = np.array([embeddings[i] for i in ids], dtype=float)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        unit = mat / norms
        sims = unit @ unit.T
        k = min(self.k, len(ids) - 1)
        out: Dict[str, List[List[Any]]] = {}
        for idx, doc_id in enumerate(ids):
            row = sims[idx].copy()
            row[idx] = -np.inf  # exclude self
            top = np.argsort(-row)[:k]
            out[doc_id] = [[ids[j], float(row[j])] for j in top]
        return out

    def _label_clusters(
        self, texts: Dict[str, str], labels: Dict[str, int]
    ) -> Dict[int, Dict[str, Any]]:
        """Name each cluster. Offline default: most distinctive terms per cluster."""
        clusters: Dict[int, Dict[str, Any]] = {}
        members: Dict[int, List[str]] = {}
        for doc_id, cid in labels.items():
            members.setdefault(int(cid), []).append(doc_id)

        for cid, doc_ids in members.items():
            label = self._top_terms_label(texts, doc_ids)
            clusters[cid] = {
                "label": label,
                "description": "",
                "size": len(doc_ids),
            }
        return clusters

    @staticmethod
    def _top_terms_label(texts: Dict[str, str], doc_ids: List[str], n_terms: int = 3) -> str:
        """Deterministic offline label: top content terms in the cluster."""
        import re
        from collections import Counter

        stop = {
            "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for",
            "with", "as", "by", "from", "that", "this", "is", "are", "was", "were",
            "has", "have", "had", "said", "says", "after", "over", "more", "than",
            "into", "out", "up", "who", "which", "their", "they", "its", "it",
            "been", "will", "would", "could", "near", "several",
        }
        counts: "Counter" = Counter()
        for did in doc_ids:
            for w in re.findall(r"[A-Za-z]{3,}", texts.get(did, "").lower()):
                if w not in stop:
                    counts[w] += 1
        top = [w for w, _ in counts.most_common(n_terms)]
        return ", ".join(top) if top else "cluster"

    def build(self, force: bool = False) -> Dict[str, Any]:
        """Run the full ingest pipeline. Returns the status dict."""
        with self._lock:
            if self._status.get("state") == "building":
                return dict(self._status)
            self._status = {"state": "building", "built": False, "n_docs": 0, "error": None}

        try:
            texts = self._collect_texts()
            if not texts:
                raise RuntimeError("No documents to build a corpus map from")

            embeddings, labels = self._embed_and_cluster(texts)
            projection = self._project_2d(embeddings, self.umap_cfg)
            knn = self._compute_knn(embeddings)
            clusters = self._label_clusters(texts, labels)

            points: Dict[str, Dict[str, Any]] = {}
            for doc_id in texts:
                x, y = projection.get(doc_id, (0.0, 0.0))
                snippet = texts[doc_id]
                snippet = snippet[:160] + "…" if len(snippet) > 160 else snippet
                points[doc_id] = {
                    "x": x,
                    "y": y,
                    "cluster": int(labels.get(doc_id, -1)),
                    "snippet": snippet,
                }

            with self._lock:
                self._points = points
                self._clusters = clusters
                self._knn = knn
                self._status = {
                    "state": "done",
                    "built": True,
                    "n_docs": len(points),
                    "error": None,
                }
                self._save_cache()
            logger.info("Corpus map built: %d docs, %d clusters", len(points), len(clusters))
        except Exception as e:
            logger.error("Corpus map build failed: %s", e)
            with self._lock:
                self._status = {"state": "error", "built": False, "n_docs": 0, "error": str(e)}
        return dict(self._status)

    # ---- reads -------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def is_built(self) -> bool:
        with self._lock:
            return bool(self._points)

    def map_data(self) -> Dict[str, Any]:
        with self._lock:
            points = [
                {"doc_id": did, **pt} for did, pt in self._points.items()
            ]
            clusters = [
                {"id": cid, **info} for cid, info in sorted(self._clusters.items())
            ]
        return {"points": points, "clusters": clusters}

    def clusters(self) -> List[Dict[str, Any]]:
        with self._lock:
            out = []
            for cid, info in sorted(self._clusters.items()):
                doc_ids = [d for d, p in self._points.items() if p.get("cluster") == cid]
                out.append({"id": cid, "doc_ids": doc_ids, **info})
            return out

    def cluster_docs(self, cluster_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {"doc_id": did, "snippet": pt.get("snippet", "")}
                for did, pt in self._points.items()
                if pt.get("cluster") == cluster_id
            ]

    def knn(self, doc_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            neighbors = self._knn.get(str(doc_id), [])
            return [
                {
                    "doc_id": nid,
                    "score": score,
                    "snippet": self._points.get(nid, {}).get("snippet", ""),
                }
                for nid, score in neighbors
            ]


# ---- singleton helpers -----------------------------------------------------
def init_corpus_map_manager(config: Dict[str, Any]) -> "CorpusMapManager":
    global _CORPUS_MAP_MANAGER
    with _CORPUS_MAP_LOCK:
        if _CORPUS_MAP_MANAGER is None:
            _CORPUS_MAP_MANAGER = CorpusMapManager(config)
    return _CORPUS_MAP_MANAGER


def get_corpus_map_manager() -> Optional["CorpusMapManager"]:
    return _CORPUS_MAP_MANAGER


def clear_corpus_map_manager() -> None:
    global _CORPUS_MAP_MANAGER
    with _CORPUS_MAP_LOCK:
        _CORPUS_MAP_MANAGER = None
