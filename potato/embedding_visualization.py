"""
Embedding Visualization Module

Provides 2D visualization of text/image embeddings for the admin dashboard,
enabling interactive exploration and prioritization of annotation items.

Key Components:
- EmbeddingVisualizationManager: Main class for embedding visualization
- UMAP dimensionality reduction for 2D projection
- Label coloring via MACE or majority vote
- Interactive selection and queue reordering

The visualization allows admins to:
- See clustering patterns in the data
- Identify annotated vs unannotated items
- Select regions to prioritize for annotation
- Interleave multiple selections for diverse sampling
"""

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
import hashlib
import json

logger = logging.getLogger(__name__)

# Guarded imports for optional dependencies
try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False
    np = None

try:
    import umap
    _UMAP_AVAILABLE = True
except ImportError:
    _UMAP_AVAILABLE = False
    umap = None

# Singleton
_EMBEDDING_VIZ_MANAGER: Optional['EmbeddingVisualizationManager'] = None
_EMBEDDING_VIZ_LOCK = threading.Lock()


@dataclass
class EmbeddingVizConfig:
    """Configuration for embedding visualization."""
    enabled: bool = True
    sample_size: int = 1000
    include_all_annotated: bool = True
    embedding_model: str = "all-MiniLM-L6-v2"
    image_embedding_model: str = "clip-ViT-B-32"
    umap_n_neighbors: int = 15
    umap_min_dist: float = 0.1
    umap_metric: str = "cosine"
    label_source: str = "mace"  # "mace" or "majority"


@dataclass
class VisualizationPoint:
    """A single point in the visualization."""
    instance_id: str
    x: float
    y: float
    label: Optional[str] = None
    label_source: Optional[str] = None
    preview: str = ""
    preview_type: str = "text"  # "text" or "image"
    annotated: bool = False
    annotation_count: int = 0


@dataclass
class VisualizationData:
    """Complete visualization data for the scatter plot."""
    points: List[VisualizationPoint] = field(default_factory=list)
    labels: List[Optional[str]] = field(default_factory=list)
    label_colors: Dict[Optional[str], str] = field(default_factory=dict)
    stats: Dict[str, Any] = field(default_factory=dict)


# Default color palette for labels
DEFAULT_COLORS = [
    "#22c55e",  # green
    "#ef4444",  # red
    "#3b82f6",  # blue
    "#eab308",  # yellow
    "#8b5cf6",  # purple
    "#f97316",  # orange
    "#06b6d4",  # cyan
    "#ec4899",  # pink
    "#14b8a6",  # teal
    "#f59e0b",  # amber
]

UNANNOTATED_COLOR = "#94a3b8"  # slate gray


class EmbeddingVisualizationManager:
    """
    Manages embedding visualization for the admin dashboard.

    This class provides:
    - 2D UMAP projections of text/image embeddings
    - Label coloring via MACE or majority vote
    - Interactive selection and queue reordering
    - Caching with invalidation on new annotations
    """

    def __init__(self, config: EmbeddingVizConfig, app_config: Dict[str, Any]):
        """
        Initialize the embedding visualization manager.

        Args:
            config: EmbeddingVizConfig instance
            app_config: Full application configuration dictionary
        """
        self.config = config
        self.app_config = app_config
        self.logger = logging.getLogger(__name__)
        self._lock = threading.RLock()

        # State
        self.enabled = False
        self._projection_cache: Optional[Dict[str, Tuple[float, float]]] = None
        self._cache_hash: Optional[str] = None
        self._label_cache: Dict[str, Optional[str]] = {}

        # Check dependencies
        if not _NUMPY_AVAILABLE:
            self.logger.warning(
                "numpy not available. Embedding visualization disabled."
            )
            return

        if not _UMAP_AVAILABLE:
            self.logger.warning(
                "umap-learn not installed. Embedding visualization disabled. "
                "Install with: pip install umap-learn"
            )
            return

        if not config.enabled:
            self.logger.info("Embedding visualization disabled in config")
            return

        self.enabled = True
        self.logger.info("Embedding visualization manager initialized")

    def _get_diversity_manager(self):
        """Get the DiversityManager singleton."""
        from potato.diversity_manager import get_diversity_manager
        return get_diversity_manager()

    def _get_item_state_manager(self):
        """Get the ItemStateManager singleton."""
        from potato.item_state_management import get_item_state_manager
        return get_item_state_manager()

    def _get_user_state_manager(self):
        """Get the UserStateManager singleton."""
        from potato.user_state_management import get_user_state_manager
        return get_user_state_manager()

    def _compute_embedding_hash(self, embeddings: Dict[str, Any]) -> str:
        """Compute a hash of embedding IDs for cache invalidation."""
        sorted_ids = sorted(embeddings.keys())
        return hashlib.md5(",".join(sorted_ids).encode()).hexdigest()

    def compute_umap_projection(
        self,
        embeddings: Dict[str, Any],
        force: bool = False
    ) -> Dict[str, Tuple[float, float]]:
        """
        Compute UMAP 2D projection of embeddings.

        Args:
            embeddings: Dict mapping instance_id to embedding vector
            force: Force recomputation even if cached

        Returns:
            Dict mapping instance_id to (x, y) coordinates
        """
        if not self.enabled or not embeddings:
            return {}

        with self._lock:
            # Check cache
            current_hash = self._compute_embedding_hash(embeddings)
            if not force and self._projection_cache and self._cache_hash == current_hash:
                self.logger.debug("Using cached UMAP projection")
                return self._projection_cache

            try:
                self.logger.info(f"Computing UMAP projection for {len(embeddings)} embeddings")

                # Convert to numpy array
                instance_ids = list(embeddings.keys())
                vectors = np.array([embeddings[iid] for iid in instance_ids])

                # Ensure we have enough samples for UMAP
                n_samples = len(vectors)
                n_neighbors = min(self.config.umap_n_neighbors, n_samples - 1)
                if n_neighbors < 2:
                    self.logger.warning(f"Not enough samples ({n_samples}) for UMAP")
                    return {}

                # Run UMAP
                reducer = umap.UMAP(
                    n_neighbors=n_neighbors,
                    min_dist=self.config.umap_min_dist,
                    metric=self.config.umap_metric,
                    n_components=2,
                    random_state=42
                )
                projection = reducer.fit_transform(vectors)

                # Build result dict
                result = {}
                for i, instance_id in enumerate(instance_ids):
                    result[instance_id] = (float(projection[i, 0]), float(projection[i, 1]))

                # Cache result
                self._projection_cache = result
                self._cache_hash = current_hash

                self.logger.info(f"UMAP projection complete: {len(result)} points")
                return result

            except Exception as e:
                self.logger.error(f"UMAP projection failed: {e}")
                return {}

    def get_labels_for_instances(
        self,
        instance_ids: List[str],
        source: str = "mace"
    ) -> Dict[str, Optional[str]]:
        """
        Get predicted labels for instances.

        Args:
            instance_ids: List of instance IDs
            source: Label source - "mace" or "majority"

        Returns:
            Dict mapping instance_id to label (or None if unannotated)
        """
        result = {}

        if source == "mace":
            result = self._get_mace_labels(instance_ids)
        else:
            result = self._get_majority_labels(instance_ids)

        return result

    def _get_mace_labels(self, instance_ids: List[str]) -> Dict[str, Optional[str]]:
        """Get MACE predicted labels for instances."""
        result = {iid: None for iid in instance_ids}

        try:
            from potato.mace_manager import get_mace_manager

            mace_mgr = get_mace_manager()
            if not mace_mgr or not mace_mgr.mace_config.enabled:
                self.logger.debug("MACE not available, falling back to majority")
                return self._get_majority_labels(instance_ids)

            # Get predictions from all schemas
            summary = mace_mgr.get_results_summary()
            if "error" in summary or not summary.get("enabled"):
                return self._get_majority_labels(instance_ids)

            # Use first schema's predictions (most common case)
            schemas = summary.get("schemas", {})
            if not schemas:
                return self._get_majority_labels(instance_ids)

            # Get first schema with predictions
            for schema_name, schema_data in schemas.items():
                predictions = schema_data.get("predictions", {})
                label_names = schema_data.get("label_names", [])

                for instance_id in instance_ids:
                    if instance_id in predictions:
                        pred_idx = predictions[instance_id]
                        if isinstance(pred_idx, int) and pred_idx < len(label_names):
                            result[instance_id] = label_names[pred_idx]
                break  # Use first schema only

        except ImportError:
            self.logger.debug("MACE manager not available")
        except Exception as e:
            self.logger.error(f"Error getting MACE labels: {e}")

        return result

    def _get_majority_labels(self, instance_ids: List[str]) -> Dict[str, Optional[str]]:
        """Get majority vote labels for instances."""
        from collections import Counter

        result = {iid: None for iid in instance_ids}

        try:
            usm = self._get_user_state_manager()
            if not usm:
                return result

            # Get annotation schemes
            annotation_schemes = self.app_config.get("annotation_schemes", [])
            if not annotation_schemes:
                return result

            # Use first categorical schema
            target_schema = None
            for scheme in annotation_schemes:
                if scheme.get("annotation_type") in ["radio", "select", "multiselect"]:
                    target_schema = scheme.get("name")
                    break

            if not target_schema:
                return result

            # Count labels per instance
            from potato.flask_server import get_users
            users = get_users()

            for instance_id in instance_ids:
                labels = []
                for username in users:
                    user_state = usm.get_user_state(username)
                    if not user_state:
                        continue

                    annotations = user_state.get_all_annotations()
                    if instance_id not in annotations:
                        continue

                    instance_annot = annotations[instance_id]
                    label_annotations = instance_annot.get("labels", {})

                    for label, value in label_annotations.items():
                        label_schema = None
                        label_name = None

                        if hasattr(label, 'schema'):
                            label_schema = label.schema
                            label_name = getattr(label, 'name', None)
                        elif hasattr(label, 'get_schema'):
                            label_schema = label.get_schema()
                            label_name = label.get_name() if hasattr(label, 'get_name') else None

                        if label_schema == target_schema and label_name:
                            labels.append(label_name)

                if labels:
                    counter = Counter(labels)
                    result[instance_id] = counter.most_common(1)[0][0]

        except Exception as e:
            self.logger.error(f"Error getting majority labels: {e}")

        return result

    def _assign_label_colors(self, unique_labels: List[Optional[str]]) -> Dict[Optional[str], str]:
        """Assign consistent colors to labels."""
        colors = {}
        color_idx = 0

        for label in unique_labels:
            if label is None:
                colors[None] = UNANNOTATED_COLOR
            else:
                colors[label] = DEFAULT_COLORS[color_idx % len(DEFAULT_COLORS)]
                color_idx += 1

        return colors

    def get_visualization_data(self, force_refresh: bool = False) -> VisualizationData:
        """
        Get complete visualization data for the scatter plot.

        Args:
            force_refresh: Force recomputation of projections

        Returns:
            VisualizationData with points, labels, and colors
        """
        if not self.enabled:
            return VisualizationData(
                stats={"error": "Embedding visualization not enabled"}
            )

        with self._lock:
            dm = self._get_diversity_manager()
            ism = self._get_item_state_manager()

            if not dm or not dm.enabled:
                return VisualizationData(
                    stats={"error": "Diversity manager not available. Enable diversity_ordering in config."}
                )

            if not dm.embeddings:
                return VisualizationData(
                    stats={"error": "No embeddings available. Ensure items have been loaded."}
                )

            # Get embeddings (possibly sampled)
            all_embedding_ids = set(dm.embeddings.keys())
            annotated_ids = set()

            # Find annotated instances
            if ism:
                for instance_id in all_embedding_ids:
                    annotators = ism.get_annotators_for_item(instance_id)
                    if annotators:
                        annotated_ids.add(instance_id)

            # Sample if needed
            sample_ids = self._sample_instances(
                all_embedding_ids,
                annotated_ids,
                self.config.sample_size,
                self.config.include_all_annotated
            )

            # Get embeddings for sampled instances
            sampled_embeddings = {
                iid: dm.embeddings[iid]
                for iid in sample_ids
                if iid in dm.embeddings
            }

            # Compute UMAP projection
            projection = self.compute_umap_projection(sampled_embeddings, force=force_refresh)
            if not projection:
                return VisualizationData(
                    stats={"error": "UMAP projection failed"}
                )

            # Get labels
            labels = self.get_labels_for_instances(
                list(projection.keys()),
                source=self.config.label_source
            )

            # Build points
            points = []
            unique_labels = set()

            for instance_id, (x, y) in projection.items():
                label = labels.get(instance_id)
                unique_labels.add(label)

                # Get preview text
                preview = ""
                preview_type = "text"
                if ism:
                    item = ism.get_instance_by_id(instance_id)
                    if item:
                        text = item.get_text()
                        if text:
                            preview = text[:200] + "..." if len(text) > 200 else text
                        # Check for image
                        if hasattr(item, 'get_image_path'):
                            img_path = item.get_image_path()
                            if img_path:
                                preview = img_path
                                preview_type = "image"

                annotation_count = 0
                if ism:
                    annotators = ism.get_annotators_for_item(instance_id)
                    annotation_count = len(annotators) if annotators else 0

                points.append(VisualizationPoint(
                    instance_id=instance_id,
                    x=x,
                    y=y,
                    label=label,
                    label_source=self.config.label_source if label else None,
                    preview=preview,
                    preview_type=preview_type,
                    annotated=instance_id in annotated_ids,
                    annotation_count=annotation_count
                ))

            # Assign colors
            label_colors = self._assign_label_colors(list(unique_labels))

            # Build stats
            stats = {
                "total_instances": len(all_embedding_ids),
                "visualized_instances": len(points),
                "annotated_instances": len(annotated_ids),
                "unannotated_instances": len(all_embedding_ids) - len(annotated_ids),
                "label_source": self.config.label_source,
                "unique_labels": len([l for l in unique_labels if l is not None])
            }

            return VisualizationData(
                points=points,
                labels=sorted([l for l in unique_labels if l is not None]) + [None],
                label_colors=label_colors,
                stats=stats
            )

    def _sample_instances(
        self,
        all_ids: Set[str],
        annotated_ids: Set[str],
        sample_size: int,
        include_all_annotated: bool
    ) -> Set[str]:
        """
        Sample instances for visualization.

        Args:
            all_ids: All available instance IDs
            annotated_ids: IDs that have been annotated
            sample_size: Maximum number of instances to include
            include_all_annotated: Always include all annotated instances

        Returns:
            Set of instance IDs to visualize
        """
        if len(all_ids) <= sample_size:
            return all_ids

        result = set()

        if include_all_annotated:
            result.update(annotated_ids)

        # Sample remaining from unannotated
        remaining_needed = sample_size - len(result)
        if remaining_needed > 0:
            unannotated = all_ids - annotated_ids
            if len(unannotated) <= remaining_needed:
                result.update(unannotated)
            else:
                # Random sample
                import random
                sampled = random.sample(list(unannotated), remaining_needed)
                result.update(sampled)

        return result

    def reorder_instances(
        self,
        selections: List[Dict[str, Any]],
        interleave: bool = True
    ) -> Dict[str, Any]:
        """
        Reorder the annotation queue based on selections.

        Args:
            selections: List of selection groups, each with:
                - instance_ids: List of selected instance IDs
                - priority: Priority number (lower = higher priority)
            interleave: Whether to interleave selections (default True)

        Returns:
            Dict with success status and reordering info
        """
        if not selections:
            return {"success": False, "error": "No selections provided"}

        ism = self._get_item_state_manager()
        if not ism:
            return {"success": False, "error": "ItemStateManager not available"}

        try:
            # Build new order
            if interleave:
                new_order = self._interleave_selections(selections)
            else:
                # Concatenate by priority
                sorted_selections = sorted(selections, key=lambda s: s.get("priority", 999))
                new_order = []
                for sel in sorted_selections:
                    new_order.extend(sel.get("instance_ids", []))

            # Deduplicate while preserving order
            seen = set()
            deduped_order = []
            for iid in new_order:
                if iid not in seen:
                    seen.add(iid)
                    deduped_order.append(iid)

            # Apply reordering
            ism.reorder_instances(deduped_order)

            # Build preview of new order (first 10)
            preview = deduped_order[:10]

            return {
                "success": True,
                "reordered_count": len(deduped_order),
                "new_order_preview": preview
            }

        except Exception as e:
            self.logger.error(f"Error reordering instances: {e}")
            return {"success": False, "error": str(e)}

    def _interleave_selections(self, selections: List[Dict[str, Any]]) -> List[str]:
        """
        Interleave instances from multiple selections by priority.

        Example:
            selections = [
                {"instance_ids": ["a", "b", "c"], "priority": 1},
                {"instance_ids": ["x", "y"], "priority": 2}
            ]
            Result: ["a", "x", "b", "y", "c"]

        Lower priority number = higher priority (comes first in each round)

        Args:
            selections: List of selection dicts with instance_ids and priority

        Returns:
            List of interleaved instance IDs
        """
        # Sort by priority
        sorted_selections = sorted(selections, key=lambda s: s.get("priority", 999))

        # Create iterators
        iterators = [iter(s.get("instance_ids", [])) for s in sorted_selections]

        result = []
        while iterators:
            exhausted = []
            for i, it in enumerate(iterators):
                try:
                    result.append(next(it))
                except StopIteration:
                    exhausted.append(i)

            # Remove exhausted iterators (in reverse to maintain indices)
            for i in reversed(exhausted):
                iterators.pop(i)

        return result

    def invalidate_cache(self) -> None:
        """Invalidate the projection cache."""
        with self._lock:
            self._projection_cache = None
            self._cache_hash = None
            self._label_cache = {}
            self.logger.info("Embedding visualization cache invalidated")

    def get_stats(self) -> Dict[str, Any]:
        """Get visualization manager statistics."""
        dm = self._get_diversity_manager()

        return {
            "enabled": self.enabled,
            "umap_available": _UMAP_AVAILABLE,
            "numpy_available": _NUMPY_AVAILABLE,
            "embeddings_available": dm.enabled if dm else False,
            "embedding_count": len(dm.embeddings) if dm and dm.embeddings else 0,
            "cache_valid": self._projection_cache is not None,
            "config": {
                "sample_size": self.config.sample_size,
                "include_all_annotated": self.config.include_all_annotated,
                "label_source": self.config.label_source,
                "umap_n_neighbors": self.config.umap_n_neighbors,
                "umap_min_dist": self.config.umap_min_dist,
            }
        }

    def to_json(self) -> Dict[str, Any]:
        """Convert visualization data to JSON-serializable format."""
        data = self.get_visualization_data()

        points_json = []
        for p in data.points:
            points_json.append({
                "instance_id": p.instance_id,
                "x": p.x,
                "y": p.y,
                "label": p.label,
                "label_source": p.label_source,
                "preview": p.preview,
                "preview_type": p.preview_type,
                "annotated": p.annotated,
                "annotation_count": p.annotation_count
            })

        return {
            "points": points_json,
            "labels": data.labels,
            "label_colors": data.label_colors,
            "stats": data.stats
        }


def parse_embedding_viz_config(config_data: Dict[str, Any]) -> EmbeddingVizConfig:
    """
    Parse embedding_visualization section from config.

    Args:
        config_data: Full application configuration

    Returns:
        EmbeddingVizConfig instance
    """
    ev = config_data.get("embedding_visualization", {})

    return EmbeddingVizConfig(
        enabled=ev.get("enabled", True),
        sample_size=ev.get("sample_size", 1000),
        include_all_annotated=ev.get("include_all_annotated", True),
        embedding_model=ev.get("embedding_model", "all-MiniLM-L6-v2"),
        image_embedding_model=ev.get("image_embedding_model", "clip-ViT-B-32"),
        umap_n_neighbors=ev.get("umap", {}).get("n_neighbors", 15),
        umap_min_dist=ev.get("umap", {}).get("min_dist", 0.1),
        umap_metric=ev.get("umap", {}).get("metric", "cosine"),
        label_source=ev.get("label_source", "mace"),
    )


def init_embedding_viz_manager(
    config_data: Dict[str, Any]
) -> Optional[EmbeddingVisualizationManager]:
    """
    Initialize the singleton EmbeddingVisualizationManager.

    Args:
        config_data: Full application configuration

    Returns:
        EmbeddingVisualizationManager instance, or None if disabled
    """
    global _EMBEDDING_VIZ_MANAGER

    with _EMBEDDING_VIZ_LOCK:
        if _EMBEDDING_VIZ_MANAGER is None:
            viz_config = parse_embedding_viz_config(config_data)
            _EMBEDDING_VIZ_MANAGER = EmbeddingVisualizationManager(viz_config, config_data)

    return _EMBEDDING_VIZ_MANAGER


def get_embedding_viz_manager() -> Optional[EmbeddingVisualizationManager]:
    """Get the singleton EmbeddingVisualizationManager instance."""
    return _EMBEDDING_VIZ_MANAGER


def clear_embedding_viz_manager() -> None:
    """Clear the singleton (for testing)."""
    global _EMBEDDING_VIZ_MANAGER
    with _EMBEDDING_VIZ_LOCK:
        _EMBEDDING_VIZ_MANAGER = None
