"""
Unit tests for the embedding visualization module.

Tests the EmbeddingVisualizationManager class, including:
- Optional feature behavior (graceful degradation)
- Configuration parsing
- UMAP projection computation
- Label retrieval (MACE and majority vote)
- Interleaving algorithm for multi-selection reordering
- Cache invalidation
- Error handling and edge cases

IMPORTANT: This is an optional feature. Tests verify that:
1. The feature gracefully handles missing dependencies
2. Admins are not forced to use embeddings
3. The admin dashboard works even when this feature is unavailable
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import sys


# =============================================================================
# Test Fixtures and Setup
# =============================================================================

@pytest.fixture
def mock_umap():
    """Mock the umap module."""
    mock = MagicMock()
    mock.UMAP.return_value.fit_transform.return_value = [[0.1, 0.2], [0.3, 0.4]]
    return mock


@pytest.fixture
def mock_numpy():
    """Mock numpy for testing without the dependency."""
    import numpy as np
    return np


@pytest.fixture(autouse=True)
def clear_singleton():
    """Clear the singleton manager before and after each test."""
    from potato.embedding_visualization import clear_embedding_viz_manager
    clear_embedding_viz_manager()
    yield
    clear_embedding_viz_manager()


# =============================================================================
# Optional Feature Tests - Graceful Degradation
# =============================================================================

class TestOptionalFeatureBehavior:
    """Test that the feature is truly optional and degrades gracefully."""

    def test_manager_disabled_when_config_disabled(self):
        """Test that manager is disabled when config sets enabled=False."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig(enabled=False)
        manager = EmbeddingVisualizationManager(config, {})

        assert manager.enabled is False

    def test_manager_reports_status_when_disabled(self):
        """Test that disabled manager reports status correctly."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig(enabled=False)
        manager = EmbeddingVisualizationManager(config, {})

        stats = manager.get_stats()
        assert stats["enabled"] is False

    def test_get_visualization_data_returns_error_when_disabled(self):
        """Test that get_visualization_data returns error info when disabled."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig(enabled=False)
        manager = EmbeddingVisualizationManager(config, {})

        result = manager.get_visualization_data()

        assert result.stats.get("error") is not None
        assert "not enabled" in result.stats["error"].lower()

    def test_compute_umap_returns_empty_when_disabled(self):
        """Test that UMAP computation returns empty dict when disabled."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig(enabled=False)
        manager = EmbeddingVisualizationManager(config, {})

        result = manager.compute_umap_projection({"id1": [1, 2, 3]})

        assert result == {}

    def test_reorder_returns_error_when_no_item_state_manager(self):
        """Test reordering returns error when ItemStateManager unavailable."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig(enabled=True)
        manager = EmbeddingVisualizationManager(config, {})

        # Mock _get_item_state_manager to return None
        with patch.object(manager, '_get_item_state_manager', return_value=None):
            result = manager.reorder_instances([
                {"instance_ids": ["id1"], "priority": 1}
            ])

        assert result["success"] is False
        assert "error" in result

    def test_get_labels_gracefully_handles_missing_mace(self):
        """Test that label retrieval works when MACE is unavailable."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig(enabled=True, label_source="mace")
        manager = EmbeddingVisualizationManager(config, {})

        # Mock the MACE import to fail
        with patch.dict('sys.modules', {'potato.mace_manager': None}):
            with patch.object(manager, '_get_majority_labels', return_value={"id1": None}):
                result = manager.get_labels_for_instances(["id1"], source="mace")

        # Should fall back gracefully (either to majority or return None labels)
        assert "id1" in result

    def test_get_labels_handles_empty_instance_list(self):
        """Test label retrieval with empty instance list."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig(enabled=True)
        manager = EmbeddingVisualizationManager(config, {})

        result = manager.get_labels_for_instances([], source="mace")

        assert result == {}

    def test_singleton_returns_none_when_not_initialized(self):
        """Test that get_embedding_viz_manager returns None when not initialized."""
        from potato.embedding_visualization import (
            get_embedding_viz_manager, clear_embedding_viz_manager
        )

        clear_embedding_viz_manager()
        assert get_embedding_viz_manager() is None


class TestMissingDependencies:
    """Test behavior when optional dependencies are missing."""

    def test_umap_unavailable_disables_manager(self):
        """Test that manager is disabled when UMAP is not installed."""
        # This tests the actual behavior - if umap-learn is not installed,
        # the manager should be disabled gracefully
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig,
            _UMAP_AVAILABLE
        )

        config = EmbeddingVizConfig(enabled=True)
        manager = EmbeddingVisualizationManager(config, {})

        # If UMAP is not available, manager should report it
        stats = manager.get_stats()
        assert "umap_available" in stats

    def test_manager_works_without_diversity_manager(self):
        """Test that manager handles missing DiversityManager gracefully."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig(enabled=True)
        manager = EmbeddingVisualizationManager(config, {})

        # Mock diversity manager to return None
        with patch.object(manager, '_get_diversity_manager', return_value=None):
            result = manager.get_visualization_data()

        # Should return error, not crash
        assert "error" in result.stats
        assert "diversity" in result.stats["error"].lower()


# =============================================================================
# Configuration Tests
# =============================================================================

class TestEmbeddingVizConfig:
    """Test configuration parsing for embedding visualization."""

    def test_parse_default_config(self):
        """Test parsing config with no embedding_visualization section."""
        from potato.embedding_visualization import parse_embedding_viz_config

        config_data = {}
        result = parse_embedding_viz_config(config_data)

        assert result.enabled is True
        assert result.sample_size == 1000
        assert result.include_all_annotated is True
        assert result.embedding_model == "all-MiniLM-L6-v2"
        assert result.label_source == "mace"
        assert result.umap_n_neighbors == 15
        assert result.umap_min_dist == 0.1
        assert result.umap_metric == "cosine"

    def test_parse_custom_config(self):
        """Test parsing config with custom values."""
        from potato.embedding_visualization import parse_embedding_viz_config

        config_data = {
            "embedding_visualization": {
                "enabled": True,
                "sample_size": 500,
                "include_all_annotated": False,
                "embedding_model": "custom-model",
                "label_source": "majority",
                "umap": {
                    "n_neighbors": 20,
                    "min_dist": 0.2,
                    "metric": "euclidean"
                }
            }
        }
        result = parse_embedding_viz_config(config_data)

        assert result.enabled is True
        assert result.sample_size == 500
        assert result.include_all_annotated is False
        assert result.embedding_model == "custom-model"
        assert result.label_source == "majority"
        assert result.umap_n_neighbors == 20
        assert result.umap_min_dist == 0.2
        assert result.umap_metric == "euclidean"

    def test_parse_disabled_config(self):
        """Test parsing config when visualization is disabled."""
        from potato.embedding_visualization import parse_embedding_viz_config

        config_data = {
            "embedding_visualization": {
                "enabled": False
            }
        }
        result = parse_embedding_viz_config(config_data)

        assert result.enabled is False

    def test_parse_partial_umap_config(self):
        """Test parsing config with partial UMAP settings."""
        from potato.embedding_visualization import parse_embedding_viz_config

        config_data = {
            "embedding_visualization": {
                "umap": {
                    "n_neighbors": 25
                    # min_dist and metric not specified
                }
            }
        }
        result = parse_embedding_viz_config(config_data)

        assert result.umap_n_neighbors == 25
        assert result.umap_min_dist == 0.1  # Default
        assert result.umap_metric == "cosine"  # Default

    def test_parse_empty_embedding_visualization_section(self):
        """Test parsing with empty embedding_visualization dict."""
        from potato.embedding_visualization import parse_embedding_viz_config

        config_data = {
            "embedding_visualization": {}
        }
        result = parse_embedding_viz_config(config_data)

        # Should use all defaults
        assert result.enabled is True
        assert result.sample_size == 1000


# =============================================================================
# Interleaving Algorithm Tests
# =============================================================================

class TestInterleavingAlgorithm:
    """Test the interleaving algorithm for multi-selection reordering."""

    def test_interleave_two_selections(self):
        """Test interleaving two selections."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        selections = [
            {"instance_ids": ["a", "b", "c"], "priority": 1},
            {"instance_ids": ["x", "y"], "priority": 2}
        ]

        result = manager._interleave_selections(selections)

        # Expected: a, x, b, y, c (round-robin by priority)
        assert result == ["a", "x", "b", "y", "c"]

    def test_interleave_three_selections(self):
        """Test interleaving three selections."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        selections = [
            {"instance_ids": ["a", "b"], "priority": 1},
            {"instance_ids": ["x", "y", "z"], "priority": 2},
            {"instance_ids": ["1", "2"], "priority": 3}
        ]

        result = manager._interleave_selections(selections)

        # Expected: a, x, 1, b, y, 2, z
        assert result == ["a", "x", "1", "b", "y", "2", "z"]

    def test_interleave_single_selection(self):
        """Test with only one selection."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        selections = [
            {"instance_ids": ["a", "b", "c"], "priority": 1}
        ]

        result = manager._interleave_selections(selections)

        assert result == ["a", "b", "c"]

    def test_interleave_empty_selections(self):
        """Test with empty selections list."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        result = manager._interleave_selections([])

        assert result == []

    def test_interleave_respects_priority_order(self):
        """Test that lower priority numbers come first in each round."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        # Priority 2 before priority 1 in the list, but 1 should come first
        selections = [
            {"instance_ids": ["late1", "late2"], "priority": 2},
            {"instance_ids": ["early1", "early2"], "priority": 1}
        ]

        result = manager._interleave_selections(selections)

        # early items should come first in each round
        assert result[0] == "early1"
        assert result[1] == "late1"
        assert result[2] == "early2"
        assert result[3] == "late2"

    def test_interleave_with_empty_selection_in_list(self):
        """Test interleaving when one selection is empty."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        selections = [
            {"instance_ids": ["a", "b"], "priority": 1},
            {"instance_ids": [], "priority": 2},  # Empty
            {"instance_ids": ["x"], "priority": 3}
        ]

        result = manager._interleave_selections(selections)

        # Should skip empty selection
        assert result == ["a", "x", "b"]

    def test_interleave_with_same_priority(self):
        """Test interleaving when selections have same priority."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        selections = [
            {"instance_ids": ["a", "b"], "priority": 1},
            {"instance_ids": ["x", "y"], "priority": 1}  # Same priority
        ]

        result = manager._interleave_selections(selections)

        # Both have priority 1, order within same priority is by list position
        assert len(result) == 4
        assert set(result) == {"a", "b", "x", "y"}

    def test_interleave_missing_priority_uses_default(self):
        """Test that missing priority field uses high default value."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        selections = [
            {"instance_ids": ["a"]},  # No priority - defaults to 999
            {"instance_ids": ["x"], "priority": 1}
        ]

        result = manager._interleave_selections(selections)

        # x should come first (priority 1 < default 999)
        assert result[0] == "x"
        assert result[1] == "a"


# =============================================================================
# Label Color Tests
# =============================================================================

class TestLabelColors:
    """Test label color assignment."""

    def test_assign_label_colors(self):
        """Test that colors are assigned consistently."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig, UNANNOTATED_COLOR
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        labels = ["Positive", "Negative", None]
        colors = manager._assign_label_colors(labels)

        assert "Positive" in colors
        assert "Negative" in colors
        assert None in colors
        assert colors[None] == UNANNOTATED_COLOR
        assert colors["Positive"] != colors["Negative"]

    def test_assign_colors_only_none(self):
        """Test color assignment when only unannotated items exist."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig, UNANNOTATED_COLOR
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        labels = [None]
        colors = manager._assign_label_colors(labels)

        assert colors[None] == UNANNOTATED_COLOR

    def test_assign_colors_many_labels(self):
        """Test color assignment with many labels cycles through palette."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig, DEFAULT_COLORS
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        # Create more labels than colors in palette
        labels = [f"Label_{i}" for i in range(15)]
        colors = manager._assign_label_colors(labels)

        # Should assign colors to all labels
        assert len(colors) == 15

        # Colors should cycle
        assert colors["Label_0"] == DEFAULT_COLORS[0]
        assert colors["Label_10"] == DEFAULT_COLORS[0]  # Cycles back

    def test_assign_colors_empty_list(self):
        """Test color assignment with empty label list."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        colors = manager._assign_label_colors([])

        assert colors == {}


# =============================================================================
# Sampling Tests
# =============================================================================

class TestSampling:
    """Test instance sampling for visualization."""

    def test_sample_within_limit(self):
        """Test sampling when all instances fit within limit."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig(sample_size=100)
        manager = EmbeddingVisualizationManager(config, {})

        all_ids = {"id1", "id2", "id3"}
        annotated_ids = {"id1"}

        result = manager._sample_instances(all_ids, annotated_ids, 100, True)

        assert result == all_ids

    def test_sample_exceeds_limit_includes_annotated(self):
        """Test that annotated items are always included when requested."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig(sample_size=5)
        manager = EmbeddingVisualizationManager(config, {})

        all_ids = {f"id{i}" for i in range(20)}
        annotated_ids = {"id0", "id1", "id2"}

        result = manager._sample_instances(all_ids, annotated_ids, 5, True)

        # All annotated should be included
        assert annotated_ids.issubset(result)
        # Total should not exceed sample_size
        assert len(result) <= 5

    def test_sample_without_including_all_annotated(self):
        """Test sampling when include_all_annotated is False."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig(sample_size=2)
        manager = EmbeddingVisualizationManager(config, {})

        all_ids = {f"id{i}" for i in range(10)}
        annotated_ids = {"id0", "id1", "id2", "id3", "id4"}

        result = manager._sample_instances(all_ids, annotated_ids, 2, False)

        # Not all annotated need to be included
        assert len(result) <= 2

    def test_sample_more_annotated_than_limit(self):
        """Test when annotated items exceed sample_size."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        all_ids = {f"id{i}" for i in range(100)}
        # More annotated than sample_size
        annotated_ids = {f"id{i}" for i in range(50)}

        result = manager._sample_instances(all_ids, annotated_ids, 30, True)

        # All annotated should still be included (even if > sample_size)
        # because include_all_annotated=True takes precedence
        assert annotated_ids.issubset(result)

    def test_sample_empty_all_ids(self):
        """Test sampling with empty all_ids."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        result = manager._sample_instances(set(), set(), 100, True)

        assert result == set()

    def test_sample_empty_annotated_ids(self):
        """Test sampling when no items are annotated."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        all_ids = {f"id{i}" for i in range(10)}

        result = manager._sample_instances(all_ids, set(), 5, True)

        # Should sample 5 random items
        assert len(result) == 5
        assert result.issubset(all_ids)


# =============================================================================
# Cache Tests
# =============================================================================

class TestCacheInvalidation:
    """Test cache invalidation functionality."""

    def test_invalidate_cache_clears_state(self):
        """Test that invalidate_cache clears all cache state."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        # Simulate cached state
        manager._projection_cache = {"id1": (0.5, 0.5)}
        manager._cache_hash = "abc123"
        manager._label_cache = {"id1": "Positive"}

        manager.invalidate_cache()

        assert manager._projection_cache is None
        assert manager._cache_hash is None
        assert manager._label_cache == {}


class TestEmbeddingHash:
    """Test embedding hash computation for cache."""

    def test_hash_consistency(self):
        """Test that same embeddings produce same hash."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        embeddings = {"id1": [1, 2, 3], "id2": [4, 5, 6]}

        hash1 = manager._compute_embedding_hash(embeddings)
        hash2 = manager._compute_embedding_hash(embeddings)

        assert hash1 == hash2

    def test_hash_changes_with_different_embeddings(self):
        """Test that different embeddings produce different hash."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        embeddings1 = {"id1": [1, 2, 3], "id2": [4, 5, 6]}
        embeddings2 = {"id1": [1, 2, 3], "id3": [7, 8, 9]}

        hash1 = manager._compute_embedding_hash(embeddings1)
        hash2 = manager._compute_embedding_hash(embeddings2)

        assert hash1 != hash2

    def test_hash_empty_embeddings(self):
        """Test hash computation with empty embeddings."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        hash1 = manager._compute_embedding_hash({})
        hash2 = manager._compute_embedding_hash({})

        assert hash1 == hash2

    def test_hash_order_independent(self):
        """Test that hash is independent of insertion order."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        embeddings1 = {"id1": [1], "id2": [2], "id3": [3]}
        embeddings2 = {"id3": [3], "id1": [1], "id2": [2]}

        hash1 = manager._compute_embedding_hash(embeddings1)
        hash2 = manager._compute_embedding_hash(embeddings2)

        # Hash should be the same regardless of dict order
        assert hash1 == hash2


# =============================================================================
# Data Classes Tests
# =============================================================================

class TestVisualizationData:
    """Test visualization data classes."""

    def test_visualization_point_creation(self):
        """Test creating a VisualizationPoint with all fields."""
        from potato.embedding_visualization import VisualizationPoint

        point = VisualizationPoint(
            instance_id="test_id",
            x=1.0,
            y=2.0,
            label="Positive",
            label_source="mace",
            preview="Test preview text",
            preview_type="text",
            annotated=True,
            annotation_count=3
        )

        assert point.instance_id == "test_id"
        assert point.x == 1.0
        assert point.y == 2.0
        assert point.label == "Positive"
        assert point.label_source == "mace"
        assert point.preview == "Test preview text"
        assert point.preview_type == "text"
        assert point.annotated is True
        assert point.annotation_count == 3

    def test_visualization_point_defaults(self):
        """Test VisualizationPoint default values."""
        from potato.embedding_visualization import VisualizationPoint

        point = VisualizationPoint(
            instance_id="test_id",
            x=0.0,
            y=0.0
        )

        assert point.label is None
        assert point.label_source is None
        assert point.preview == ""
        assert point.preview_type == "text"
        assert point.annotated is False
        assert point.annotation_count == 0

    def test_visualization_data_creation(self):
        """Test creating VisualizationData."""
        from potato.embedding_visualization import VisualizationData, VisualizationPoint

        point = VisualizationPoint(
            instance_id="test_id",
            x=1.0,
            y=2.0
        )

        data = VisualizationData(
            points=[point],
            labels=["Positive", None],
            label_colors={"Positive": "#22c55e", None: "#94a3b8"},
            stats={"total_instances": 100}
        )

        assert len(data.points) == 1
        assert len(data.labels) == 2
        assert data.stats["total_instances"] == 100

    def test_visualization_data_defaults(self):
        """Test VisualizationData default values."""
        from potato.embedding_visualization import VisualizationData

        data = VisualizationData()

        assert data.points == []
        assert data.labels == []
        assert data.label_colors == {}
        assert data.stats == {}


# =============================================================================
# Singleton Management Tests
# =============================================================================

class TestSingletonManagement:
    """Test singleton pattern for the manager."""

    def test_clear_manager(self):
        """Test clearing the singleton manager."""
        from potato.embedding_visualization import (
            clear_embedding_viz_manager,
            get_embedding_viz_manager
        )

        clear_embedding_viz_manager()
        assert get_embedding_viz_manager() is None

    def test_init_manager(self):
        """Test initializing the singleton manager."""
        from potato.embedding_visualization import (
            init_embedding_viz_manager,
            get_embedding_viz_manager,
            clear_embedding_viz_manager
        )

        clear_embedding_viz_manager()

        config_data = {
            "embedding_visualization": {
                "enabled": True
            }
        }

        manager = init_embedding_viz_manager(config_data)

        assert manager is not None
        assert get_embedding_viz_manager() is manager

    def test_init_manager_returns_existing(self):
        """Test that init_embedding_viz_manager returns existing instance."""
        from potato.embedding_visualization import (
            init_embedding_viz_manager,
            clear_embedding_viz_manager
        )

        clear_embedding_viz_manager()

        config_data = {"embedding_visualization": {"enabled": True}}

        manager1 = init_embedding_viz_manager(config_data)
        manager2 = init_embedding_viz_manager(config_data)

        assert manager1 is manager2


# =============================================================================
# Reorder Instances Tests
# =============================================================================

class TestReorderInstances:
    """Test the reorder_instances method."""

    def test_reorder_empty_selections(self):
        """Test reordering with empty selections list."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        result = manager.reorder_instances([])

        assert result["success"] is False
        assert "error" in result

    def test_reorder_without_interleave(self):
        """Test reordering without interleaving."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        # Mock ItemStateManager
        mock_ism = MagicMock()
        mock_ism.reorder_instances = MagicMock()

        with patch.object(manager, '_get_item_state_manager', return_value=mock_ism):
            result = manager.reorder_instances(
                [
                    {"instance_ids": ["a", "b"], "priority": 1},
                    {"instance_ids": ["x", "y"], "priority": 2}
                ],
                interleave=False
            )

        # Without interleave, should be concatenated by priority
        assert result["success"] is True
        mock_ism.reorder_instances.assert_called_once()
        call_args = mock_ism.reorder_instances.call_args[0][0]
        assert call_args == ["a", "b", "x", "y"]

    def test_reorder_with_interleave(self):
        """Test reordering with interleaving."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        mock_ism = MagicMock()
        mock_ism.reorder_instances = MagicMock()

        with patch.object(manager, '_get_item_state_manager', return_value=mock_ism):
            result = manager.reorder_instances(
                [
                    {"instance_ids": ["a", "b"], "priority": 1},
                    {"instance_ids": ["x", "y"], "priority": 2}
                ],
                interleave=True
            )

        assert result["success"] is True
        mock_ism.reorder_instances.assert_called_once()
        call_args = mock_ism.reorder_instances.call_args[0][0]
        # Should be interleaved
        assert call_args == ["a", "x", "b", "y"]

    def test_reorder_removes_duplicates(self):
        """Test that reordering removes duplicate instance IDs."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        mock_ism = MagicMock()

        with patch.object(manager, '_get_item_state_manager', return_value=mock_ism):
            result = manager.reorder_instances(
                [
                    {"instance_ids": ["a", "b", "c"], "priority": 1},
                    {"instance_ids": ["b", "c", "d"], "priority": 2}  # b, c are duplicates
                ],
                interleave=False
            )

        assert result["success"] is True
        call_args = mock_ism.reorder_instances.call_args[0][0]
        # Should have no duplicates
        assert len(call_args) == len(set(call_args))


# =============================================================================
# Stats Tests
# =============================================================================

class TestGetStats:
    """Test the get_stats method."""

    def test_get_stats_when_disabled(self):
        """Test stats when manager is disabled."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig(enabled=False)
        manager = EmbeddingVisualizationManager(config, {})

        stats = manager.get_stats()

        assert stats["enabled"] is False

    def test_get_stats_includes_config(self):
        """Test that stats includes configuration."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig(
            sample_size=500,
            include_all_annotated=False,
            label_source="majority"
        )
        manager = EmbeddingVisualizationManager(config, {})

        stats = manager.get_stats()

        assert "config" in stats
        assert stats["config"]["sample_size"] == 500
        assert stats["config"]["include_all_annotated"] is False
        assert stats["config"]["label_source"] == "majority"

    def test_get_stats_includes_cache_status(self):
        """Test that stats includes cache validity status."""
        from potato.embedding_visualization import (
            EmbeddingVisualizationManager, EmbeddingVizConfig
        )

        config = EmbeddingVizConfig()
        manager = EmbeddingVisualizationManager(config, {})

        # Initially no cache
        stats = manager.get_stats()
        assert stats["cache_valid"] is False

        # Simulate cache
        manager._projection_cache = {"id1": (0.5, 0.5)}
        stats = manager.get_stats()
        assert stats["cache_valid"] is True


# =============================================================================
# Config Validation Tests
# =============================================================================

class TestConfigValidation:
    """Test configuration validation."""

    def test_valid_config_passes_validation(self):
        """Test that valid config passes validation."""
        from potato.server_utils.config_module import validate_embedding_visualization_config

        config_data = {
            "embedding_visualization": {
                "enabled": True,
                "sample_size": 500,
                "include_all_annotated": True,
                "label_source": "mace",
                "umap": {
                    "n_neighbors": 15,
                    "min_dist": 0.1,
                    "metric": "cosine"
                }
            }
        }

        # Should not raise
        validate_embedding_visualization_config(config_data)

    def test_invalid_sample_size_fails_validation(self):
        """Test that invalid sample_size fails validation."""
        from potato.server_utils.config_module import (
            validate_embedding_visualization_config,
            ConfigValidationError
        )

        config_data = {
            "embedding_visualization": {
                "enabled": True,
                "sample_size": -1  # Invalid
            }
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_embedding_visualization_config(config_data)

        assert "sample_size" in str(exc_info.value)

    def test_invalid_sample_size_zero_fails_validation(self):
        """Test that sample_size of 0 fails validation."""
        from potato.server_utils.config_module import (
            validate_embedding_visualization_config,
            ConfigValidationError
        )

        config_data = {
            "embedding_visualization": {
                "enabled": True,
                "sample_size": 0  # Invalid - must be positive
            }
        }

        with pytest.raises(ConfigValidationError):
            validate_embedding_visualization_config(config_data)

    def test_invalid_label_source_fails_validation(self):
        """Test that invalid label_source fails validation."""
        from potato.server_utils.config_module import (
            validate_embedding_visualization_config,
            ConfigValidationError
        )

        config_data = {
            "embedding_visualization": {
                "enabled": True,
                "label_source": "invalid_source"  # Invalid
            }
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_embedding_visualization_config(config_data)

        assert "label_source" in str(exc_info.value)

    def test_invalid_umap_metric_fails_validation(self):
        """Test that invalid UMAP metric fails validation."""
        from potato.server_utils.config_module import (
            validate_embedding_visualization_config,
            ConfigValidationError
        )

        config_data = {
            "embedding_visualization": {
                "enabled": True,
                "umap": {
                    "metric": "invalid_metric"  # Invalid
                }
            }
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_embedding_visualization_config(config_data)

        assert "metric" in str(exc_info.value)

    def test_invalid_umap_n_neighbors_fails_validation(self):
        """Test that invalid n_neighbors fails validation."""
        from potato.server_utils.config_module import (
            validate_embedding_visualization_config,
            ConfigValidationError
        )

        config_data = {
            "embedding_visualization": {
                "enabled": True,
                "umap": {
                    "n_neighbors": 1  # Invalid - must be >= 2
                }
            }
        }

        with pytest.raises(ConfigValidationError):
            validate_embedding_visualization_config(config_data)

    def test_invalid_umap_min_dist_fails_validation(self):
        """Test that invalid min_dist fails validation."""
        from potato.server_utils.config_module import (
            validate_embedding_visualization_config,
            ConfigValidationError
        )

        config_data = {
            "embedding_visualization": {
                "enabled": True,
                "umap": {
                    "min_dist": 1.5  # Invalid - must be <= 1
                }
            }
        }

        with pytest.raises(ConfigValidationError):
            validate_embedding_visualization_config(config_data)

    def test_disabled_config_skips_validation(self):
        """Test that disabled config skips detailed validation."""
        from potato.server_utils.config_module import validate_embedding_visualization_config

        config_data = {
            "embedding_visualization": {
                "enabled": False,
                "sample_size": -999  # Would be invalid if enabled
            }
        }

        # Should not raise because enabled=False
        validate_embedding_visualization_config(config_data)

    def test_missing_section_passes_validation(self):
        """Test that missing embedding_visualization section passes."""
        from potato.server_utils.config_module import validate_embedding_visualization_config

        config_data = {}

        # Should not raise - section is optional
        validate_embedding_visualization_config(config_data)

    def test_non_dict_section_fails_validation(self):
        """Test that non-dict embedding_visualization section fails."""
        from potato.server_utils.config_module import (
            validate_embedding_visualization_config,
            ConfigValidationError
        )

        config_data = {
            "embedding_visualization": "invalid"  # Should be dict
        }

        with pytest.raises(ConfigValidationError):
            validate_embedding_visualization_config(config_data)
