"""
Unit tests for the SimilarityEngine module.

Tests cover:
- SimilarityEngine disabled when sentence-transformers not available
- SimilarityEngine disabled when similarity_enabled=False in config
- get_stats() returns correct structure
- precompute_embeddings() skips already-cached items
- find_similar() returns sorted results
- update_embedding() stores new embedding
- _cosine_similarity() math correctness
- Singleton management (init, get, clear)
"""

import pytest
import numpy as np
from dataclasses import dataclass, field
from unittest.mock import patch, MagicMock


@dataclass
class MockAdjudicationConfig:
    """Mock AdjudicationConfig for testing without importing the real one."""
    similarity_enabled: bool = False
    similarity_model: str = "all-MiniLM-L6-v2"
    similarity_top_k: int = 5
    similarity_precompute: bool = True
    output_subdir: str = "adjudication"


@pytest.fixture(autouse=True)
def cleanup_singleton():
    """Clear singleton between tests."""
    from potato.similarity import clear_similarity_engine
    clear_similarity_engine()
    yield
    clear_similarity_engine()


@pytest.fixture
def mock_adj_config_enabled():
    """AdjudicationConfig with similarity enabled."""
    return MockAdjudicationConfig(similarity_enabled=True)


@pytest.fixture
def mock_adj_config_disabled():
    """AdjudicationConfig with similarity disabled."""
    return MockAdjudicationConfig(similarity_enabled=False)


@pytest.fixture
def base_config():
    """Minimal app config dict."""
    return {
        "output_annotation_dir": "/tmp/test_annotation_output",
    }


class TestSimilarityDisabledNoLibrary:
    """Tests for behavior when sentence-transformers is not installed."""

    @patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", False)
    def test_engine_disabled_when_library_unavailable(self, base_config, mock_adj_config_enabled):
        from potato.similarity import SimilarityEngine
        engine = SimilarityEngine(base_config, mock_adj_config_enabled)
        assert engine.enabled is False
        assert engine.model is None

    @patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", False)
    def test_find_similar_returns_empty_when_disabled(self, base_config, mock_adj_config_enabled):
        from potato.similarity import SimilarityEngine
        engine = SimilarityEngine(base_config, mock_adj_config_enabled)
        result = engine.find_similar("some_id")
        assert result == []

    @patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", False)
    def test_precompute_returns_zero_when_disabled(self, base_config, mock_adj_config_enabled):
        from potato.similarity import SimilarityEngine
        engine = SimilarityEngine(base_config, mock_adj_config_enabled)
        result = engine.precompute_embeddings({"id1": "some text"})
        assert result == 0

    @patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", False)
    def test_update_embedding_returns_false_when_disabled(self, base_config, mock_adj_config_enabled):
        from potato.similarity import SimilarityEngine
        engine = SimilarityEngine(base_config, mock_adj_config_enabled)
        result = engine.update_embedding("id1", "some text")
        assert result is False


class TestSimilarityDisabledByConfig:
    """Tests for behavior when similarity_enabled=False in config."""

    @patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", True)
    def test_engine_disabled_when_config_off(self, base_config, mock_adj_config_disabled):
        from potato.similarity import SimilarityEngine
        engine = SimilarityEngine(base_config, mock_adj_config_disabled)
        assert engine.enabled is False
        assert engine.model is None

    @patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", True)
    def test_precompute_returns_zero_when_config_off(self, base_config, mock_adj_config_disabled):
        from potato.similarity import SimilarityEngine
        engine = SimilarityEngine(base_config, mock_adj_config_disabled)
        result = engine.precompute_embeddings({"id1": "text"})
        assert result == 0


class TestSimilarityEnabled:
    """Tests for fully enabled SimilarityEngine with mocked model."""

    @pytest.fixture
    def enabled_engine(self, base_config, mock_adj_config_enabled):
        """Create an enabled SimilarityEngine with a mocked SentenceTransformer."""
        with patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", True), \
             patch("potato.similarity.SentenceTransformer") as MockST, \
             patch("potato.similarity.SimilarityEngine._load_cache"):
            mock_model = MagicMock()
            MockST.return_value = mock_model

            from potato.similarity import SimilarityEngine
            engine = SimilarityEngine(base_config, mock_adj_config_enabled)
            assert engine.enabled is True
            assert engine.model is mock_model
            yield engine

    def test_engine_is_enabled(self, enabled_engine):
        assert enabled_engine.enabled is True

    def test_precompute_embeddings_new_items(self, enabled_engine):
        """precompute_embeddings encodes new items and stores them."""
        mock_vecs = np.array([
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ])
        enabled_engine.model.encode.return_value = mock_vecs

        with patch.object(enabled_engine, "_save_cache"):
            count = enabled_engine.precompute_embeddings({
                "id1": "first text",
                "id2": "second text",
            })

        assert count == 2
        assert "id1" in enabled_engine.embeddings
        assert "id2" in enabled_engine.embeddings
        np.testing.assert_array_equal(enabled_engine.embeddings["id1"], [1.0, 0.0, 0.0])
        np.testing.assert_array_equal(enabled_engine.embeddings["id2"], [0.0, 1.0, 0.0])

    def test_precompute_embeddings_skips_cached(self, enabled_engine):
        """precompute_embeddings skips items already in cache."""
        enabled_engine.embeddings["id1"] = np.array([1.0, 0.0, 0.0])
        enabled_engine.text_cache["id1"] = "already cached"

        mock_vecs = np.array([[0.0, 1.0, 0.0]])
        enabled_engine.model.encode.return_value = mock_vecs

        with patch.object(enabled_engine, "_save_cache"):
            count = enabled_engine.precompute_embeddings({
                "id1": "first text",
                "id2": "second text",
            })

        assert count == 1
        # id1 should remain unchanged
        np.testing.assert_array_equal(enabled_engine.embeddings["id1"], [1.0, 0.0, 0.0])
        # id2 should be the new encoding
        assert "id2" in enabled_engine.embeddings

    def test_precompute_embeddings_all_cached(self, enabled_engine):
        """precompute_embeddings returns 0 when all items already cached."""
        enabled_engine.embeddings["id1"] = np.array([1.0, 0.0])
        enabled_engine.embeddings["id2"] = np.array([0.0, 1.0])

        count = enabled_engine.precompute_embeddings({
            "id1": "text one",
            "id2": "text two",
        })

        assert count == 0
        enabled_engine.model.encode.assert_not_called()

    def test_precompute_embeddings_stores_text_preview(self, enabled_engine):
        """precompute_embeddings truncates text cache to 200 chars."""
        long_text = "x" * 500
        mock_vecs = np.array([[1.0, 0.0]])
        enabled_engine.model.encode.return_value = mock_vecs

        with patch.object(enabled_engine, "_save_cache"):
            enabled_engine.precompute_embeddings({"id1": long_text})

        assert len(enabled_engine.text_cache["id1"]) == 200

    def test_precompute_embeddings_encode_error(self, enabled_engine):
        """precompute_embeddings returns 0 on encode exception."""
        enabled_engine.model.encode.side_effect = RuntimeError("encode failed")

        with patch.object(enabled_engine, "_save_cache"):
            count = enabled_engine.precompute_embeddings({"id1": "text"})

        assert count == 0

    def test_find_similar_returns_sorted_results(self, enabled_engine):
        """find_similar returns results sorted by similarity, highest first."""
        # Reference vector
        enabled_engine.embeddings["ref"] = np.array([1.0, 0.0, 0.0])
        # Very similar (same direction)
        enabled_engine.embeddings["similar"] = np.array([0.9, 0.1, 0.0])
        # Orthogonal
        enabled_engine.embeddings["orthogonal"] = np.array([0.0, 1.0, 0.0])
        # Moderately similar
        enabled_engine.embeddings["moderate"] = np.array([0.5, 0.5, 0.0])

        results = enabled_engine.find_similar("ref")

        assert len(results) == 3
        # Results should be sorted highest similarity first
        assert results[0][0] == "similar"
        assert results[1][0] == "moderate"
        assert results[2][0] == "orthogonal"
        # Scores should be in descending order
        assert results[0][1] > results[1][1] > results[2][1]

    def test_find_similar_excludes_self(self, enabled_engine):
        """find_similar does not include the reference item itself."""
        enabled_engine.embeddings["ref"] = np.array([1.0, 0.0])
        enabled_engine.embeddings["other"] = np.array([0.5, 0.5])

        results = enabled_engine.find_similar("ref")

        ids = [r[0] for r in results]
        assert "ref" not in ids
        assert "other" in ids

    def test_find_similar_respects_top_k(self, enabled_engine):
        """find_similar limits results to top_k."""
        enabled_engine.embeddings["ref"] = np.array([1.0, 0.0])
        for i in range(10):
            enabled_engine.embeddings[f"item_{i}"] = np.array([1.0 - i * 0.1, i * 0.1])

        results = enabled_engine.find_similar("ref", top_k=3)
        assert len(results) == 3

    def test_find_similar_uses_config_top_k(self, enabled_engine):
        """find_similar defaults to adj_config.similarity_top_k."""
        enabled_engine.adj_config.similarity_top_k = 2
        enabled_engine.embeddings["ref"] = np.array([1.0, 0.0])
        for i in range(10):
            enabled_engine.embeddings[f"item_{i}"] = np.array([1.0 - i * 0.1, i * 0.1])

        results = enabled_engine.find_similar("ref")
        assert len(results) == 2

    def test_find_similar_unknown_id_returns_empty(self, enabled_engine):
        """find_similar returns empty for unknown instance_id."""
        enabled_engine.embeddings["known"] = np.array([1.0, 0.0])

        results = enabled_engine.find_similar("unknown_id")
        assert results == []

    def test_find_similar_disabled_returns_empty(self, base_config, mock_adj_config_disabled):
        """find_similar returns [] when engine is disabled."""
        with patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", True):
            from potato.similarity import SimilarityEngine
            engine = SimilarityEngine(base_config, mock_adj_config_disabled)
            engine.embeddings["id1"] = np.array([1.0, 0.0])
            result = engine.find_similar("id1")
            assert result == []

    def test_update_embedding_stores_new(self, enabled_engine):
        """update_embedding computes and stores a single embedding."""
        mock_vec = np.array([0.3, 0.7, 0.1])
        enabled_engine.model.encode.return_value = np.array([mock_vec])

        with patch.object(enabled_engine, "_save_cache"):
            result = enabled_engine.update_embedding("new_id", "new text content")

        assert result is True
        assert "new_id" in enabled_engine.embeddings
        np.testing.assert_array_equal(enabled_engine.embeddings["new_id"], mock_vec)
        assert enabled_engine.text_cache["new_id"] == "new text content"

    def test_update_embedding_truncates_text_cache(self, enabled_engine):
        """update_embedding truncates text_cache to 200 chars."""
        long_text = "a" * 300
        mock_vec = np.array([1.0])
        enabled_engine.model.encode.return_value = np.array([mock_vec])

        with patch.object(enabled_engine, "_save_cache"):
            enabled_engine.update_embedding("id1", long_text)

        assert len(enabled_engine.text_cache["id1"]) == 200

    def test_update_embedding_error_returns_false(self, enabled_engine):
        """update_embedding returns False on encode exception."""
        enabled_engine.model.encode.side_effect = RuntimeError("encode failed")

        with patch.object(enabled_engine, "_save_cache"):
            result = enabled_engine.update_embedding("id1", "text")

        assert result is False

    def test_update_embedding_disabled_returns_false(self, base_config, mock_adj_config_disabled):
        """update_embedding returns False when engine is disabled."""
        with patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", True):
            from potato.similarity import SimilarityEngine
            engine = SimilarityEngine(base_config, mock_adj_config_disabled)
            result = engine.update_embedding("id1", "text")
            assert result is False


class TestGetStats:
    """Tests for get_stats() method."""

    @patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", True)
    def test_stats_enabled_engine(self, base_config, mock_adj_config_enabled):
        with patch("potato.similarity.SentenceTransformer") as MockST, \
             patch("potato.similarity.SimilarityEngine._load_cache"):
            MockST.return_value = MagicMock()
            from potato.similarity import SimilarityEngine
            engine = SimilarityEngine(base_config, mock_adj_config_enabled)
            engine.embeddings = {"id1": np.array([1.0]), "id2": np.array([2.0])}

            stats = engine.get_stats()

        assert stats["available"] is True
        assert stats["enabled"] is True
        assert stats["model"] == "all-MiniLM-L6-v2"
        assert stats["embedding_count"] == 2
        assert stats["top_k"] == 5

    @patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", False)
    def test_stats_disabled_engine(self, base_config, mock_adj_config_enabled):
        from potato.similarity import SimilarityEngine
        engine = SimilarityEngine(base_config, mock_adj_config_enabled)

        stats = engine.get_stats()

        assert stats["available"] is False
        assert stats["enabled"] is False
        assert stats["model"] == "all-MiniLM-L6-v2"
        assert stats["embedding_count"] == 0
        assert stats["top_k"] == 5

    @patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", True)
    def test_stats_config_disabled(self, base_config, mock_adj_config_disabled):
        from potato.similarity import SimilarityEngine
        engine = SimilarityEngine(base_config, mock_adj_config_disabled)

        stats = engine.get_stats()

        assert stats["available"] is True
        assert stats["enabled"] is False
        assert stats["embedding_count"] == 0


class TestCosineSimilarity:
    """Tests for _cosine_similarity() math."""

    @pytest.fixture
    def engine(self, base_config, mock_adj_config_disabled):
        """Create a minimal engine (disabled) to test cosine similarity."""
        with patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", False):
            from potato.similarity import SimilarityEngine
            engine = SimilarityEngine(base_config, mock_adj_config_disabled)
        # Monkey-patch np into the module for cosine similarity to work
        import potato.similarity as sim_module
        sim_module.np = np
        return engine

    def test_identical_vectors(self, engine):
        a = np.array([1.0, 2.0, 3.0])
        b = np.array([1.0, 2.0, 3.0])
        result = engine._cosine_similarity(a, b)
        assert abs(result - 1.0) < 1e-6

    def test_orthogonal_vectors(self, engine):
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        result = engine._cosine_similarity(a, b)
        assert abs(result - 0.0) < 1e-6

    def test_opposite_vectors(self, engine):
        a = np.array([1.0, 0.0])
        b = np.array([-1.0, 0.0])
        result = engine._cosine_similarity(a, b)
        assert abs(result - (-1.0)) < 1e-6

    def test_zero_vector_a(self, engine):
        a = np.array([0.0, 0.0, 0.0])
        b = np.array([1.0, 2.0, 3.0])
        result = engine._cosine_similarity(a, b)
        assert result == 0.0

    def test_zero_vector_b(self, engine):
        a = np.array([1.0, 2.0, 3.0])
        b = np.array([0.0, 0.0, 0.0])
        result = engine._cosine_similarity(a, b)
        assert result == 0.0

    def test_known_value(self, engine):
        """Test with a known cosine similarity value."""
        a = np.array([1.0, 0.0])
        b = np.array([1.0, 1.0])
        # cos(45 degrees) = 1/sqrt(2) ~ 0.7071
        expected = 1.0 / np.sqrt(2.0)
        result = engine._cosine_similarity(a, b)
        assert abs(result - expected) < 1e-6

    def test_returns_float(self, engine):
        a = np.array([1.0, 2.0])
        b = np.array([3.0, 4.0])
        result = engine._cosine_similarity(a, b)
        assert isinstance(result, float)


class TestSingletonManagement:
    """Tests for init/get/clear singleton pattern."""

    @patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", False)
    def test_init_creates_singleton(self, base_config, mock_adj_config_disabled):
        from potato.similarity import (
            init_similarity_engine,
            get_similarity_engine,
        )
        engine = init_similarity_engine(base_config, mock_adj_config_disabled)
        assert engine is not None
        assert get_similarity_engine() is engine

    @patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", False)
    def test_get_before_init_returns_none(self):
        from potato.similarity import get_similarity_engine
        assert get_similarity_engine() is None

    @patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", False)
    def test_clear_removes_singleton(self, base_config, mock_adj_config_disabled):
        from potato.similarity import (
            init_similarity_engine,
            get_similarity_engine,
            clear_similarity_engine,
        )
        init_similarity_engine(base_config, mock_adj_config_disabled)
        assert get_similarity_engine() is not None
        clear_similarity_engine()
        assert get_similarity_engine() is None

    @patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", False)
    def test_init_does_not_overwrite_existing(self, base_config, mock_adj_config_disabled):
        """Second init call does not replace existing singleton."""
        from potato.similarity import (
            init_similarity_engine,
            get_similarity_engine,
        )
        engine1 = init_similarity_engine(base_config, mock_adj_config_disabled)
        engine2 = init_similarity_engine(base_config, mock_adj_config_disabled)
        assert engine1 is engine2
        assert get_similarity_engine() is engine1


class TestModelLoadFailure:
    """Tests for graceful handling of model loading errors."""

    @patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", True)
    def test_model_load_exception_disables_engine(self, base_config, mock_adj_config_enabled):
        with patch("potato.similarity.SentenceTransformer") as MockST:
            MockST.side_effect = RuntimeError("Failed to download model")

            from potato.similarity import SimilarityEngine
            engine = SimilarityEngine(base_config, mock_adj_config_enabled)

        assert engine.enabled is False
        assert engine.model is None


class TestCacheOperations:
    """Tests for cache directory and file operations."""

    @patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", True)
    def test_get_cache_dir_creates_directory(self, base_config, mock_adj_config_enabled):
        with patch("potato.similarity.SentenceTransformer") as MockST, \
             patch("potato.similarity.SimilarityEngine._load_cache"), \
             patch("os.makedirs") as mock_makedirs:
            MockST.return_value = MagicMock()
            from potato.similarity import SimilarityEngine
            engine = SimilarityEngine(base_config, mock_adj_config_enabled)

        # Now test _get_cache_dir
        with patch("os.makedirs") as mock_makedirs:
            cache_dir = engine._get_cache_dir()

        expected_dir = "/tmp/test_annotation_output/adjudication/.similarity_cache"
        assert cache_dir == expected_dir
        mock_makedirs.assert_called_once_with(expected_dir, exist_ok=True)

    @patch("potato.similarity._SENTENCE_TRANSFORMERS_AVAILABLE", True)
    def test_get_cache_dir_uses_config_values(self, mock_adj_config_enabled):
        config = {"output_annotation_dir": "/custom/output"}
        mock_adj_config_enabled.output_subdir = "custom_adj"

        with patch("potato.similarity.SentenceTransformer") as MockST, \
             patch("potato.similarity.SimilarityEngine._load_cache"):
            MockST.return_value = MagicMock()
            from potato.similarity import SimilarityEngine
            engine = SimilarityEngine(config, mock_adj_config_enabled)

        with patch("os.makedirs"):
            cache_dir = engine._get_cache_dir()

        assert cache_dir == "/custom/output/custom_adj/.similarity_cache"
