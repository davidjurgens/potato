"""
Tests for the rule clustering and aggregation pipeline.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from potato.solo_mode.edge_case_rules import EdgeCaseRule, EdgeCaseCategory
from potato.solo_mode.rule_clusterer import RuleClusterer


def _make_rule(rule_id: str, text: str = "When X -> Y") -> EdgeCaseRule:
    """Helper to create a test rule."""
    return EdgeCaseRule(
        id=rule_id,
        instance_id=f"inst_{rule_id}",
        rule_text=text,
        condition="X",
        action="Y",
        source_confidence=0.4,
        source_label="test",
        prompt_version=1,
    )


def _make_mock_solo_config(
    target_cluster_size: int = 5,
    model_name: str = "all-MiniLM-L6-v2",
):
    """Create a mock SoloModeConfig."""
    config = MagicMock()
    config.edge_case_rules.target_cluster_size = target_cluster_size
    config.embedding.model_name = model_name
    config.revision_models = []
    config.labeling_models = []
    return config


class TestRuleClustererEmbedding:
    """Tests for rule embedding."""

    def test_tfidf_fallback(self):
        """Test that TF-IDF fallback works when sentence-transformers unavailable."""
        clusterer = RuleClusterer({}, _make_mock_solo_config())

        rules = [
            _make_rule("r1", "When sarcasm present -> label negative"),
            _make_rule("r2", "When irony used -> label negative"),
            _make_rule("r3", "When positive tone -> label positive"),
        ]

        with patch.object(clusterer, '_get_embedding_model', return_value=None):
            embeddings = clusterer.embed_rules(rules)

        # TF-IDF should produce embeddings
        assert embeddings is not None
        assert embeddings.shape[0] == 3

    def test_embed_empty_rules(self):
        """Embedding empty list should return None or empty."""
        clusterer = RuleClusterer({}, _make_mock_solo_config())
        with patch.object(clusterer, '_get_embedding_model', return_value=None):
            result = clusterer.embed_rules([])
        # TF-IDF on empty list may return None
        assert result is None or (hasattr(result, 'shape') and result.shape[0] == 0)


class TestRuleClustererClustering:
    """Tests for rule clustering."""

    def test_cluster_with_mock_embeddings(self):
        """Test clustering with mock numpy embeddings."""
        import numpy as np

        clusterer = RuleClusterer({}, _make_mock_solo_config(target_cluster_size=3))
        rules = [_make_rule(f"r{i}") for i in range(9)]

        # Create embeddings that naturally form 3 clusters
        embeddings = np.array([
            [1, 0], [1.1, 0], [0.9, 0],   # cluster 1
            [0, 1], [0, 1.1], [0, 0.9],   # cluster 2
            [1, 1], [1.1, 1], [0.9, 1.1], # cluster 3
        ], dtype=np.float32)

        clusters = clusterer.cluster_rules(rules, embeddings)

        # Should form approximately 3 clusters (9 rules / 3 target size + 1 = 4 max)
        assert 1 <= len(clusters) <= 4
        total_rules = sum(len(c) for c in clusters.values())
        assert total_rules == 9

    def test_cluster_single_rule(self):
        """Single rule should stay in one cluster."""
        import numpy as np

        clusterer = RuleClusterer({}, _make_mock_solo_config())
        rules = [_make_rule("r1")]
        embeddings = np.array([[1, 0]])

        clusters = clusterer.cluster_rules(rules, embeddings)
        assert len(clusters) == 1
        assert len(clusters[0]) == 1

    def test_cluster_none_embeddings(self):
        """None embeddings should put all rules in one cluster."""
        clusterer = RuleClusterer({}, _make_mock_solo_config())
        rules = [_make_rule(f"r{i}") for i in range(5)]

        clusters = clusterer.cluster_rules(rules, None)
        assert len(clusters) == 1
        assert len(clusters[0]) == 5

    def test_cluster_empty(self):
        """Empty rule list should return empty dict."""
        clusterer = RuleClusterer({}, _make_mock_solo_config())
        clusters = clusterer.cluster_rules([], None)
        assert clusters == {0: []}


class TestRebalanceClusters:
    """Tests for cluster rebalancing."""

    def test_rebalance_oversized(self):
        """Oversized clusters should be split."""
        clusterer = RuleClusterer({}, _make_mock_solo_config(target_cluster_size=3))
        rules = [_make_rule(f"r{i}") for i in range(8)]

        # One cluster with 8 items (max_size = 6)
        clusters = {0: rules}
        result = clusterer._rebalance_clusters(clusters, target_size=3)

        total = sum(len(c) for c in result.values())
        assert total == 8
        # No cluster should have more than 6 items
        for members in result.values():
            assert len(members) <= 6

    def test_rebalance_already_balanced(self):
        """Already balanced clusters should be unchanged."""
        clusterer = RuleClusterer({}, _make_mock_solo_config(target_cluster_size=5))
        rules1 = [_make_rule(f"r1_{i}") for i in range(5)]
        rules2 = [_make_rule(f"r2_{i}") for i in range(5)]

        clusters = {0: rules1, 1: rules2}
        result = clusterer._rebalance_clusters(clusters, target_size=5)

        assert len(result) == 2
        assert sum(len(c) for c in result.values()) == 10


class TestClusterAggregation:
    """Tests for cluster aggregation."""

    def test_single_rule_aggregation(self):
        """Single rule cluster should return the rule text directly."""
        clusterer = RuleClusterer({}, _make_mock_solo_config())
        rule = _make_rule("r1", "When sarcasm -> negative")

        summary = clusterer.aggregate_cluster([rule])
        assert summary == "When sarcasm -> negative"

    def test_aggregation_without_endpoint(self):
        """Without endpoint, should fallback to first rule."""
        clusterer = RuleClusterer({}, _make_mock_solo_config())
        rules = [
            _make_rule("r1", "When sarcasm -> negative"),
            _make_rule("r2", "When irony -> negative"),
        ]

        summary = clusterer.aggregate_cluster(rules)
        assert summary == "When sarcasm -> negative"

    def test_aggregation_with_mock_endpoint(self):
        """Test aggregation with a mocked LLM endpoint."""
        clusterer = RuleClusterer({}, _make_mock_solo_config())

        mock_endpoint = MagicMock()
        mock_endpoint.query.return_value = '{"summary_rule": "When figurative language -> prioritize intent over literal meaning"}'
        clusterer._endpoint = mock_endpoint

        rules = [
            _make_rule("r1", "When sarcasm used -> check tone"),
            _make_rule("r2", "When irony present -> consider context"),
        ]

        summary = clusterer.aggregate_cluster(rules)
        assert "figurative language" in summary

    def test_aggregation_empty(self):
        """Empty cluster should return None."""
        clusterer = RuleClusterer({}, _make_mock_solo_config())
        assert clusterer.aggregate_cluster([]) is None


class TestCategoryMerging:
    """Tests for redundant category merging."""

    def test_no_merge_single(self):
        """Single category should be returned as-is."""
        clusterer = RuleClusterer({}, _make_mock_solo_config())
        cat = EdgeCaseCategory(id="c1", summary_rule="Rule 1")
        result = clusterer.merge_categories([cat])
        assert len(result) == 1
        assert result[0].id == "c1"

    def test_no_merge_without_endpoint(self):
        """Without endpoint, categories should pass through unchanged."""
        clusterer = RuleClusterer({}, _make_mock_solo_config())
        cats = [
            EdgeCaseCategory(id="c1", summary_rule="Rule 1"),
            EdgeCaseCategory(id="c2", summary_rule="Rule 2"),
        ]
        result = clusterer.merge_categories(cats)
        assert len(result) == 2

    def test_merge_with_mock_endpoint(self):
        """Test merging with a mocked LLM endpoint."""
        clusterer = RuleClusterer({}, _make_mock_solo_config())

        mock_endpoint = MagicMock()
        mock_endpoint.query.return_value = json.dumps({
            "merge_groups": [{
                "merged_summary": "Combined rule",
                "category_ids": ["c1", "c2"]
            }]
        })
        clusterer._endpoint = mock_endpoint

        cats = [
            EdgeCaseCategory(id="c1", summary_rule="Rule A", member_rule_ids=["r1"]),
            EdgeCaseCategory(id="c2", summary_rule="Rule B", member_rule_ids=["r2"]),
            EdgeCaseCategory(id="c3", summary_rule="Rule C", member_rule_ids=["r3"]),
        ]

        result = clusterer.merge_categories(cats)
        # c1 and c2 merged, c3 kept
        assert len(result) == 2
        merged = [c for c in result if len(c.member_rule_ids) == 2]
        assert len(merged) == 1
        assert set(merged[0].member_rule_ids) == {"r1", "r2"}


class TestFullPipeline:
    """Tests for the complete clustering pipeline."""

    def test_pipeline_empty(self):
        """Empty rules should produce empty categories."""
        clusterer = RuleClusterer({}, _make_mock_solo_config())
        result = clusterer.run_full_pipeline([])
        assert result == []

    def test_pipeline_single_rule(self):
        """Single rule should produce one category."""
        clusterer = RuleClusterer({}, _make_mock_solo_config())
        rules = [_make_rule("r1", "When edge case -> handle specially")]

        with patch.object(clusterer, 'embed_rules', return_value=None):
            result = clusterer.run_full_pipeline(rules)

        assert len(result) == 1
        assert result[0].summary_rule == "When edge case -> handle specially"
        assert "r1" in result[0].member_rule_ids

    def test_pipeline_multiple_rules(self):
        """Multiple rules should be clustered and aggregated."""
        import numpy as np

        clusterer = RuleClusterer({}, _make_mock_solo_config(target_cluster_size=3))
        rules = [_make_rule(f"r{i}", f"When condition {i} -> action {i}") for i in range(6)]

        # Mock embeddings that form 2 clusters
        embeddings = np.array([
            [0, 0], [0.1, 0], [0, 0.1],
            [10, 10], [10.1, 10], [10, 10.1],
        ], dtype=np.float32)

        with patch.object(clusterer, 'embed_rules', return_value=embeddings):
            result = clusterer.run_full_pipeline(rules)

        # Should produce at least 1 category
        assert len(result) >= 1
        # All rules should be accounted for
        all_member_ids = set()
        for cat in result:
            all_member_ids.update(cat.member_rule_ids)
        assert len(all_member_ids) == 6


class TestJsonParsing:
    """Tests for JSON response parsing."""

    def test_parse_plain_json(self):
        clusterer = RuleClusterer({}, _make_mock_solo_config())
        result = clusterer._parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_markdown_json(self):
        clusterer = RuleClusterer({}, _make_mock_solo_config())
        result = clusterer._parse_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parse_dict(self):
        clusterer = RuleClusterer({}, _make_mock_solo_config())
        result = clusterer._parse_json({"key": "value"})
        assert result == {"key": "value"}

    def test_parse_invalid(self):
        clusterer = RuleClusterer({}, _make_mock_solo_config())
        result = clusterer._parse_json("not json at all")
        assert result == {}


# Need json import for merge test
import json


class TestProjectTo2D:
    """Tests for 2D projection of rule embeddings."""

    def test_empty_rules(self):
        clusterer = RuleClusterer({}, _make_mock_solo_config())
        result = clusterer.project_to_2d([])
        assert result == []

    def test_single_rule(self):
        clusterer = RuleClusterer({}, _make_mock_solo_config())
        rules = [_make_rule("r1", "When sarcasm -> negative")]

        with patch.object(clusterer, '_get_embedding_model', return_value=None):
            result = clusterer.project_to_2d(rules)

        assert len(result) == 1
        assert len(result[0]) == 2
        assert isinstance(result[0][0], float)

    def test_multiple_rules_tfidf(self):
        clusterer = RuleClusterer({}, _make_mock_solo_config())
        rules = [
            _make_rule("r1", "When sarcasm present -> label negative"),
            _make_rule("r2", "When irony used -> label negative"),
            _make_rule("r3", "When positive tone -> label positive"),
            _make_rule("r4", "When ambiguous text -> label neutral"),
        ]

        with patch.object(clusterer, '_get_embedding_model', return_value=None):
            result = clusterer.project_to_2d(rules)

        assert len(result) == 4
        for x, y in result:
            assert isinstance(x, float)
            assert isinstance(y, float)

        # Points should not all be identical
        unique_points = set(result)
        assert len(unique_points) > 1

    def test_returns_correct_count(self):
        clusterer = RuleClusterer({}, _make_mock_solo_config())
        rules = [_make_rule(f"r{i}", f"Rule {i}") for i in range(10)]

        with patch.object(clusterer, '_get_embedding_model', return_value=None):
            result = clusterer.project_to_2d(rules)

        assert len(result) == 10
