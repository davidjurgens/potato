"""
Unit tests for the DiversityManager module.

Tests the embedding-based clustering and round-robin sampling for
diverse item ordering without requiring a running Flask server.
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import tempfile
import os
import json


class TestDiversityConfig:
    """Tests for DiversityConfig dataclass."""

    def test_default_values(self):
        """Test that DiversityConfig has sensible defaults."""
        from potato.diversity_manager import DiversityConfig

        config = DiversityConfig()

        assert config.enabled is False
        assert config.model_name == "all-MiniLM-L6-v2"
        assert config.num_clusters == 10
        assert config.items_per_cluster == 20
        assert config.auto_clusters is True
        assert config.prefill_count == 100
        assert config.batch_size == 32
        assert config.cache_dir is None
        assert config.recluster_threshold == 1.0
        assert config.preserve_visited is True
        assert config.trigger_ai_prefetch is True

    def test_custom_values(self):
        """Test DiversityConfig with custom values."""
        from potato.diversity_manager import DiversityConfig

        config = DiversityConfig(
            enabled=True,
            model_name="custom-model",
            num_clusters=5,
            items_per_cluster=10,
            auto_clusters=False,
            prefill_count=50,
        )

        assert config.enabled is True
        assert config.model_name == "custom-model"
        assert config.num_clusters == 5
        assert config.items_per_cluster == 10
        assert config.auto_clusters is False
        assert config.prefill_count == 50


class TestClusterState:
    """Tests for ClusterState dataclass."""

    def test_default_values(self):
        """Test that ClusterState has correct defaults."""
        from potato.diversity_manager import ClusterState

        state = ClusterState()

        assert state.sampled_clusters == set()
        assert state.cluster_sample_counts == {}
        assert state.current_cluster_index == 0
        assert state.visited_instance_ids == set()
        assert state.skipped_instance_ids == set()
        assert state.last_recluster_time is None

    def test_mutable_fields(self):
        """Test that ClusterState mutable fields work correctly."""
        from potato.diversity_manager import ClusterState

        state = ClusterState()

        # Modify sets
        state.sampled_clusters.add(1)
        state.visited_instance_ids.add("item1")
        state.skipped_instance_ids.add("item2")

        assert 1 in state.sampled_clusters
        assert "item1" in state.visited_instance_ids
        assert "item2" in state.skipped_instance_ids

        # Modify dict
        state.cluster_sample_counts[1] = 5
        assert state.cluster_sample_counts[1] == 5


class TestParseDiversityConfig:
    """Tests for parse_diversity_config function."""

    def test_empty_config(self):
        """Test parsing empty config returns defaults."""
        from potato.diversity_manager import parse_diversity_config

        config = parse_diversity_config({})

        assert config.enabled is False
        assert config.model_name == "all-MiniLM-L6-v2"

    def test_full_config(self):
        """Test parsing full diversity_ordering config."""
        from potato.diversity_manager import parse_diversity_config

        app_config = {
            "diversity_ordering": {
                "enabled": True,
                "model_name": "paraphrase-MiniLM-L6-v2",
                "num_clusters": 8,
                "items_per_cluster": 15,
                "auto_clusters": False,
                "prefill_count": 200,
                "batch_size": 64,
                "recluster_threshold": 0.8,
                "preserve_visited": False,
                "trigger_ai_prefetch": False,
            }
        }

        config = parse_diversity_config(app_config)

        assert config.enabled is True
        assert config.model_name == "paraphrase-MiniLM-L6-v2"
        assert config.num_clusters == 8
        assert config.items_per_cluster == 15
        assert config.auto_clusters is False
        assert config.prefill_count == 200
        assert config.batch_size == 64
        assert config.recluster_threshold == 0.8
        assert config.preserve_visited is False
        assert config.trigger_ai_prefetch is False


class TestSingletonManagement:
    """Tests for singleton init/get/clear functions."""

    def teardown_method(self):
        """Clear singleton after each test."""
        from potato.diversity_manager import clear_diversity_manager
        clear_diversity_manager()

    def test_get_before_init_returns_none(self):
        """Test get_diversity_manager returns None before init."""
        from potato.diversity_manager import get_diversity_manager, clear_diversity_manager

        clear_diversity_manager()
        dm = get_diversity_manager()
        assert dm is None

    @patch('potato.diversity_manager._SENTENCE_TRANSFORMERS_AVAILABLE', False)
    def test_disabled_when_no_sentence_transformers(self):
        """Test graceful fallback when sentence_transformers not installed."""
        from potato.diversity_manager import init_diversity_manager, get_diversity_manager, clear_diversity_manager

        clear_diversity_manager()
        app_config = {
            "assignment_strategy": "diversity_clustering",
            "diversity_ordering": {"enabled": True},
            "output_annotation_dir": "/tmp/test"
        }

        dm = init_diversity_manager(app_config)
        assert dm is not None
        assert dm.enabled is False

    def test_disabled_when_config_off(self):
        """Test manager respects enabled: false."""
        from potato.diversity_manager import init_diversity_manager, get_diversity_manager, clear_diversity_manager

        clear_diversity_manager()
        app_config = {
            "diversity_ordering": {"enabled": False},
            "output_annotation_dir": "/tmp/test"
        }

        dm = init_diversity_manager(app_config)
        # Manager exists but not enabled
        assert dm.enabled is False

    def test_clear_sets_to_none(self):
        """Test clear_diversity_manager sets singleton to None."""
        from potato.diversity_manager import init_diversity_manager, get_diversity_manager, clear_diversity_manager

        app_config = {
            "diversity_ordering": {"enabled": False},
            "output_annotation_dir": "/tmp/test"
        }

        init_diversity_manager(app_config)
        assert get_diversity_manager() is not None

        clear_diversity_manager()
        assert get_diversity_manager() is None


class TestDiversityManagerWithMocks:
    """Tests for DiversityManager using mocks for sentence-transformers."""

    def setup_method(self):
        """Set up test fixtures."""
        from potato.diversity_manager import clear_diversity_manager
        clear_diversity_manager()
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        """Clean up after tests."""
        from potato.diversity_manager import clear_diversity_manager
        clear_diversity_manager()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_manager_with_mock(self, enabled=True, custom_embed_fn=None):
        """Create a DiversityManager with mocked sentence-transformers."""
        import numpy as np
        from potato.diversity_manager import DiversityConfig, DiversityManager

        # Create custom embedding function that doesn't require sentence-transformers
        if custom_embed_fn is None:
            def custom_embed_fn(texts):
                # Return random-ish embeddings based on text length
                return np.array([[len(t) % 10, len(t) // 10, hash(t) % 100 / 100]
                                for t in texts])

        config = DiversityConfig(
            enabled=enabled,
            custom_embedding_function=custom_embed_fn,
            cache_dir=self.temp_dir,
            num_clusters=3,
            auto_clusters=False,
            batch_size=2,
        )

        app_config = {
            "output_annotation_dir": self.temp_dir,
        }

        return DiversityManager(config, app_config)

    def test_compute_embedding_single(self):
        """Test computing embedding for single text."""
        dm = self._create_manager_with_mock()

        emb = dm.compute_embedding("Hello world")
        assert emb is not None
        assert len(emb) == 3  # Our mock returns 3-dim vectors

    def test_compute_embeddings_batch(self):
        """Test batch embedding computation."""
        dm = self._create_manager_with_mock()

        texts = {
            "item1": "Short text",
            "item2": "A longer piece of text here",
            "item3": "Another example text",
        }

        count = dm.compute_embeddings_batch(texts)
        assert count == 3
        assert "item1" in dm.embeddings
        assert "item2" in dm.embeddings
        assert "item3" in dm.embeddings

    def test_compute_embeddings_batch_with_callback(self):
        """Test batch embedding with callback."""
        dm = self._create_manager_with_mock()
        callbacks = []

        def callback(iid, emb):
            callbacks.append(iid)

        texts = {
            "item1": "Text one",
            "item2": "Text two",
        }

        dm.compute_embeddings_batch(texts, callback=callback)
        assert len(callbacks) == 2

    def test_compute_embeddings_batch_skips_cached(self):
        """Test that batch embedding skips already cached items."""
        dm = self._create_manager_with_mock()

        texts1 = {"item1": "First text"}
        dm.compute_embeddings_batch(texts1)

        texts2 = {
            "item1": "First text",
            "item2": "Second text",
        }
        count = dm.compute_embeddings_batch(texts2)
        # Only item2 should be computed
        assert count == 1

    def test_cluster_items_basic(self):
        """Test k-means clustering."""
        import numpy as np
        from potato.diversity_manager import DiversityConfig, DiversityManager

        # Create embeddings that will clearly cluster
        def cluster_embed(texts):
            embeddings = []
            for t in texts:
                if "cluster1" in t:
                    embeddings.append([1.0, 0.0, 0.0])
                elif "cluster2" in t:
                    embeddings.append([0.0, 1.0, 0.0])
                else:
                    embeddings.append([0.0, 0.0, 1.0])
            return np.array(embeddings)

        config = DiversityConfig(
            enabled=True,
            custom_embedding_function=cluster_embed,
            cache_dir=self.temp_dir,
            num_clusters=3,
            auto_clusters=False,
        )

        dm = DiversityManager(config, {"output_annotation_dir": self.temp_dir})

        texts = {
            "a1": "cluster1 text a",
            "a2": "cluster1 text b",
            "b1": "cluster2 text a",
            "b2": "cluster2 text b",
            "c1": "cluster3 text a",
            "c2": "cluster3 text b",
        }
        dm.compute_embeddings_batch(texts)

        result = dm.cluster_items()
        assert result is True
        assert len(dm.cluster_labels) == 6
        assert len(dm.cluster_members) == 3

    def test_cluster_items_auto_clusters(self):
        """Test auto cluster count calculation."""
        import numpy as np
        from potato.diversity_manager import DiversityConfig, DiversityManager

        def simple_embed(texts):
            return np.random.rand(len(texts), 10)

        config = DiversityConfig(
            enabled=True,
            custom_embedding_function=simple_embed,
            cache_dir=self.temp_dir,
            items_per_cluster=5,
            auto_clusters=True,
        )

        dm = DiversityManager(config, {"output_annotation_dir": self.temp_dir})

        # Add 20 items, should get ~4 clusters with items_per_cluster=5
        texts = {f"item{i}": f"Text number {i}" for i in range(20)}
        dm.compute_embeddings_batch(texts)
        dm.cluster_items()

        # Should have at least 2 clusters and not more than 10
        assert 2 <= len(dm.cluster_members) <= 10

    def test_round_robin_sampling(self):
        """Test round-robin sampling from clusters."""
        import numpy as np
        from potato.diversity_manager import DiversityConfig, DiversityManager

        # Create embeddings that cluster into 3 groups
        def cluster_embed(texts):
            embeddings = []
            for t in texts:
                idx = int(t[-1]) % 3
                vec = [0.0, 0.0, 0.0]
                vec[idx] = 1.0
                embeddings.append(vec)
            return np.array(embeddings)

        config = DiversityConfig(
            enabled=True,
            custom_embedding_function=cluster_embed,
            cache_dir=self.temp_dir,
            num_clusters=3,
            auto_clusters=False,
        )

        dm = DiversityManager(config, {"output_annotation_dir": self.temp_dir})

        texts = {f"item{i}": f"Text {i}" for i in range(9)}  # 3 items per cluster
        dm.compute_embeddings_batch(texts)
        dm.cluster_items()

        # Sample items for user1
        available = set(texts.keys())
        sampled = []
        for _ in range(6):
            item = dm.get_next_diverse_item("user1", available)
            if item:
                sampled.append(item)
                available.discard(item)

        assert len(sampled) == 6
        # Should have sampled from different clusters
        cluster_ids = [dm.cluster_labels[iid] for iid in sampled]
        # First 3 should be from different clusters
        assert len(set(cluster_ids[:3])) == 3

    def test_order_preservation_annotated(self):
        """Test that annotated items stay in place."""
        dm = self._create_manager_with_mock()

        texts = {f"item{i}": f"Text {i}" for i in range(6)}
        dm.compute_embeddings_batch(texts)
        dm.cluster_items()

        available = ["item0", "item1", "item2", "item3", "item4", "item5"]
        preserve = {"item0", "item2"}  # Annotated items

        result = dm.generate_diverse_ordering("user1", available, preserve)

        # Preserved items should be at or near their original positions
        assert "item0" in result[:2]  # Should be near position 0
        assert "item2" in result[:4]  # Should be near position 2

    def test_order_preservation_skipped(self):
        """Test that skipped items stay in place when preserve_visited is True."""
        dm = self._create_manager_with_mock()
        dm.config.preserve_visited = True

        texts = {f"item{i}": f"Text {i}" for i in range(6)}
        dm.compute_embeddings_batch(texts)
        dm.cluster_items()

        # Mark item1 as skipped
        dm.mark_item_skipped("user1", "item1")

        available = ["item0", "item1", "item2", "item3", "item4", "item5"]
        preserve = set()  # No annotated items

        result = dm.generate_diverse_ordering("user1", available, preserve)

        # item1 should be preserved (skipped)
        assert "item1" in result

    def test_recluster_trigger(self):
        """Test recluster when threshold is reached."""
        dm = self._create_manager_with_mock()
        dm.config.recluster_threshold = 1.0

        texts = {f"item{i}": f"Text {i}" for i in range(6)}
        dm.compute_embeddings_batch(texts)
        dm.cluster_items()

        # Sample from all clusters
        user_id = "user1"
        available = set(texts.keys())

        for _ in range(6):
            dm.get_next_diverse_item(user_id, available)

        # Now should trigger recluster
        assert dm.should_recluster(user_id) is True

    def test_cache_save_load(self):
        """Test embedding persistence."""
        dm1 = self._create_manager_with_mock()

        texts = {"item1": "Text one", "item2": "Text two"}
        dm1.compute_embeddings_batch(texts)
        dm1.cluster_items()

        # Create new manager with same cache dir
        dm2 = self._create_manager_with_mock()
        dm2._load_cache()

        assert len(dm2.embeddings) == 2
        assert "item1" in dm2.embeddings
        assert "item2" in dm2.embeddings

    def test_get_stats(self):
        """Test statistics reporting."""
        dm = self._create_manager_with_mock()

        texts = {f"item{i}": f"Text {i}" for i in range(6)}
        dm.compute_embeddings_batch(texts)
        dm.cluster_items()

        stats = dm.get_stats()

        assert stats["enabled"] is True
        assert stats["embedding_count"] == 6
        assert stats["cluster_count"] > 0
        assert "cluster_sizes" in stats

    def test_mark_item_visited(self):
        """Test marking items as visited."""
        dm = self._create_manager_with_mock()

        dm.mark_item_visited("user1", "item1")
        dm.mark_item_visited("user1", "item2")

        state = dm.get_user_cluster_state("user1")
        assert "item1" in state.visited_instance_ids
        assert "item2" in state.visited_instance_ids

    def test_on_annotation_complete(self):
        """Test annotation completion handler."""
        dm = self._create_manager_with_mock()

        # Should trigger async embedding
        dm.on_annotation_complete("user1", "new_item", "New item text")

        state = dm.get_user_cluster_state("user1")
        assert "new_item" in state.visited_instance_ids

    def test_apply_to_user_ordering(self):
        """Test main integration method."""
        dm = self._create_manager_with_mock()

        texts = {f"item{i}": f"Text {i}" for i in range(6)}
        dm.compute_embeddings_batch(texts)
        dm.cluster_items()

        available = [f"item{i}" for i in range(6)]
        annotated = {"item0"}  # Already annotated

        result = dm.apply_to_user_ordering("user1", available, annotated)

        assert len(result) == 6
        assert set(result) == set(available)

    def test_disabled_manager_returns_original_order(self):
        """Test that disabled manager returns original ordering."""
        from potato.diversity_manager import DiversityConfig, DiversityManager

        config = DiversityConfig(enabled=False)
        dm = DiversityManager(config, {"output_annotation_dir": self.temp_dir})

        available = ["item0", "item1", "item2"]
        result = dm.apply_to_user_ordering("user1", available, set())

        assert result == available


class TestDiversityManagerThreadSafety:
    """Tests for thread-safety of DiversityManager."""

    def setup_method(self):
        """Set up test fixtures."""
        from potato.diversity_manager import clear_diversity_manager
        clear_diversity_manager()
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        """Clean up after tests."""
        from potato.diversity_manager import clear_diversity_manager
        clear_diversity_manager()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_concurrent_embedding_requests(self):
        """Test concurrent embedding computations."""
        import numpy as np
        import threading
        import time
        from potato.diversity_manager import DiversityConfig, DiversityManager

        def slow_embed(texts):
            time.sleep(0.01)  # Simulate slow embedding
            return np.random.rand(len(texts), 10)

        config = DiversityConfig(
            enabled=True,
            custom_embedding_function=slow_embed,
            cache_dir=self.temp_dir,
        )

        dm = DiversityManager(config, {"output_annotation_dir": self.temp_dir})

        results = []
        errors = []

        def worker(worker_id):
            try:
                texts = {f"item_{worker_id}_{i}": f"Text {i}" for i in range(5)}
                count = dm.compute_embeddings_batch(texts)
                results.append(count)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert sum(results) == 20  # 4 workers * 5 items each

    def test_concurrent_user_ordering(self):
        """Test concurrent user ordering requests."""
        import numpy as np
        import threading
        from potato.diversity_manager import DiversityConfig, DiversityManager

        def simple_embed(texts):
            return np.random.rand(len(texts), 10)

        config = DiversityConfig(
            enabled=True,
            custom_embedding_function=simple_embed,
            cache_dir=self.temp_dir,
            num_clusters=3,
            auto_clusters=False,
        )

        dm = DiversityManager(config, {"output_annotation_dir": self.temp_dir})

        # Pre-compute embeddings
        texts = {f"item{i}": f"Text {i}" for i in range(12)}
        dm.compute_embeddings_batch(texts)
        dm.cluster_items()

        results = {}
        errors = []

        def worker(user_id):
            try:
                available = list(texts.keys())
                order = dm.apply_to_user_ordering(user_id, available, set())
                results[user_id] = order
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"user{i}",)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 10

        # Each user should get all items
        for user_id, order in results.items():
            assert len(order) == 12
            assert set(order) == set(texts.keys())
