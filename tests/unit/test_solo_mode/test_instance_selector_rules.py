"""
Tests for the edge_case_rule pool, cartography pool, and predictions cache
in InstanceSelector.
"""

import pytest
from unittest.mock import patch

from potato.solo_mode.instance_selector import InstanceSelector, SelectionWeights


class TestEdgeCaseRulePool:
    """Tests for edge case rule selection pool."""

    def test_weight_defaults(self):
        weights = SelectionWeights()
        assert weights.edge_case_rule == 0.0

    def test_weight_with_edge_case_rule(self):
        weights = SelectionWeights(
            low_confidence=0.35,
            diverse=0.25,
            random=0.15,
            disagreement=0.10,
            edge_case_rule=0.15,
        )
        weights.validate()
        total = (
            weights.low_confidence +
            weights.diverse +
            weights.random +
            weights.disagreement +
            weights.edge_case_rule
        )
        assert abs(total - 1.0) < 0.001

    def test_weight_normalization(self):
        weights = SelectionWeights(
            low_confidence=0.4,
            diverse=0.3,
            random=0.2,
            disagreement=0.1,
            edge_case_rule=0.2,  # Sum = 1.2
        )
        weights.validate()
        total = (
            weights.low_confidence +
            weights.diverse +
            weights.random +
            weights.disagreement +
            weights.edge_case_rule
        )
        assert abs(total - 1.0) < 0.001

    def test_refresh_pools_with_edge_case_rule_ids(self):
        selector = InstanceSelector()
        available = {'a', 'b', 'c', 'd', 'e'}
        edge_case_ids = {'b', 'c'}

        with patch.object(selector, '_build_diverse_pool', return_value=[]):
            selector.refresh_pools(
                available_ids=available,
                edge_case_rule_ids=edge_case_ids,
            )

        assert set(selector._edge_case_rule_pool) == {'b', 'c'}
        assert len(selector._random_pool) == 5

    def test_refresh_pools_no_edge_case_rule_ids(self):
        selector = InstanceSelector()
        available = {'a', 'b', 'c'}

        with patch.object(selector, '_build_diverse_pool', return_value=[]):
            selector.refresh_pools(available_ids=available)

        assert selector._edge_case_rule_pool == []

    def test_selection_from_edge_case_rule_pool(self):
        """When edge_case_rule weight is high, instances from that pool should be selected."""
        weights = SelectionWeights(
            low_confidence=0.0,
            diverse=0.0,
            random=0.0,
            disagreement=0.0,
            edge_case_rule=1.0,  # Only select from edge case rules
        )
        selector = InstanceSelector(weights=weights)
        available = {'a', 'b', 'c', 'd'}

        with patch.object(selector, '_build_diverse_pool', return_value=[]):
            selector.refresh_pools(
                available_ids=available,
                edge_case_rule_ids={'b', 'c'},
            )

        # Should select from edge_case_rule pool
        selected = selector.select_next(available)
        assert selected in {'b', 'c'}

    def test_selection_fallback_when_pool_empty(self):
        """When edge_case_rule pool is empty, should fall back to other pools."""
        weights = SelectionWeights(
            low_confidence=0.0,
            diverse=0.0,
            random=0.0,
            disagreement=0.0,
            edge_case_rule=1.0,
        )
        selector = InstanceSelector(weights=weights)
        available = {'a', 'b', 'c'}

        with patch.object(selector, '_build_diverse_pool', return_value=[]):
            selector.refresh_pools(
                available_ids=available,
                edge_case_rule_ids=set(),  # Empty
            )

        # Should fallback to any available
        selected = selector.select_next(available)
        assert selected in available

    def test_configure_with_edge_case_rule_weight(self):
        selector = InstanceSelector()
        selector.configure(
            low_confidence_weight=0.3,
            diversity_weight=0.2,
            random_weight=0.15,
            disagreement_weight=0.1,
            edge_case_rule_weight=0.25,
        )
        assert selector.weights.edge_case_rule == 0.25

    def test_get_selection_stats_includes_edge_case_rule(self):
        selector = InstanceSelector()
        stats = selector.get_selection_stats()
        assert 'edge_case_rule' in stats['pool_sizes']
        assert 'edge_case_rule' in stats['weights']

    def test_batch_selection_with_edge_case_pool(self):
        """Batch selection should work with edge case rule pool."""
        weights = SelectionWeights(
            low_confidence=0.0,
            diverse=0.0,
            random=0.5,
            disagreement=0.0,
            edge_case_rule=0.5,
        )
        selector = InstanceSelector(weights=weights)
        available = {'a', 'b', 'c', 'd', 'e'}

        with patch.object(selector, '_build_diverse_pool', return_value=[]):
            selector.refresh_pools(
                available_ids=available,
                edge_case_rule_ids={'a', 'b'},
            )

        batch = selector.select_batch(available, batch_size=3)
        assert len(batch) == 3
        # All selected should be from available
        assert all(s in available for s in batch)
        # No duplicates
        assert len(set(batch)) == 3


class TestConfigEdgeCaseRuleWeight:
    """Test config parsing for edge_case_rule_weight."""

    def test_parse_from_yaml(self):
        from potato.solo_mode.config import parse_solo_mode_config

        config_data = {
            'solo_mode': {
                'enabled': True,
                'labeling_models': [
                    {'endpoint_type': 'ollama', 'model': 'test'}
                ],
                'instance_selection': {
                    'low_confidence_weight': 0.35,
                    'diversity_weight': 0.25,
                    'random_weight': 0.15,
                    'disagreement_weight': 0.10,
                    'edge_case_rule_weight': 0.15,
                },
            },
        }
        config = parse_solo_mode_config(config_data)
        assert config.instance_selection.edge_case_rule_weight == 0.15

    def test_default_zero(self):
        from potato.solo_mode.config import parse_solo_mode_config

        config_data = {
            'solo_mode': {
                'enabled': True,
                'labeling_models': [
                    {'endpoint_type': 'ollama', 'model': 'test'}
                ],
            },
        }
        config = parse_solo_mode_config(config_data)
        assert config.instance_selection.edge_case_rule_weight == 0.0


class TestPredictionsCache:
    """Tests for _predictions_cache used by _select_lowest_confidence."""

    def test_predictions_cache_populated_on_refresh(self):
        selector = InstanceSelector()
        preds = {
            'a': {'s1': {'confidence_score': 0.3}},
            'b': {'s1': {'confidence_score': 0.8}},
        }
        with patch.object(selector, '_build_diverse_pool', return_value=[]):
            selector.refresh_pools(
                available_ids={'a', 'b'},
                llm_predictions=preds,
            )
        assert selector._predictions_cache == preds

    def test_predictions_cache_empty_when_none(self):
        selector = InstanceSelector()
        with patch.object(selector, '_build_diverse_pool', return_value=[]):
            selector.refresh_pools(available_ids={'a'})
        assert selector._predictions_cache == {}

    def test_select_lowest_confidence_uses_cache(self):
        selector = InstanceSelector()
        preds = {
            'a': {'s1': {'confidence_score': 0.9}},
            'b': {'s1': {'confidence_score': 0.2}},
            'c': {'s1': {'confidence_score': 0.5}},
        }
        with patch.object(selector, '_build_diverse_pool', return_value=[]):
            selector.refresh_pools(
                available_ids={'a', 'b', 'c'},
                llm_predictions=preds,
                confidence_threshold=1.0,  # Put all in low-confidence pool
            )

        result = selector._select_lowest_confidence(['a', 'b', 'c'])
        assert result == 'b'  # Lowest confidence

    def test_select_lowest_confidence_fallback_no_predictions(self):
        selector = InstanceSelector()
        with patch.object(selector, '_build_diverse_pool', return_value=[]):
            selector.refresh_pools(available_ids={'a', 'b'})

        # No predictions cached, should return first element
        result = selector._select_lowest_confidence(['a', 'b'])
        assert result == 'a'

    def test_select_lowest_confidence_multiple_schemas(self):
        """When instance has multiple schema predictions, pick min across all."""
        selector = InstanceSelector()
        preds = {
            'a': {
                's1': {'confidence_score': 0.8},
                's2': {'confidence_score': 0.3},
            },
            'b': {
                's1': {'confidence_score': 0.5},
            },
        }
        with patch.object(selector, '_build_diverse_pool', return_value=[]):
            selector.refresh_pools(
                available_ids={'a', 'b'},
                llm_predictions=preds,
            )

        result = selector._select_lowest_confidence(['a', 'b'])
        assert result == 'a'  # 0.3 < 0.5


class TestCartographyPool:
    """Tests for the cartography selection pool."""

    def test_cartography_weight_default(self):
        weights = SelectionWeights()
        assert weights.cartography == 0.0

    def test_cartography_weight_normalization(self):
        weights = SelectionWeights(
            low_confidence=0.3,
            diverse=0.2,
            random=0.1,
            disagreement=0.1,
            edge_case_rule=0.1,
            cartography=0.2,
        )
        weights.validate()
        total = (
            weights.low_confidence +
            weights.diverse +
            weights.random +
            weights.disagreement +
            weights.edge_case_rule +
            weights.cartography
        )
        assert abs(total - 1.0) < 0.001

    def test_refresh_pools_with_cartography_scores(self):
        selector = InstanceSelector()
        scores = {'a': 0.5, 'b': 0.1, 'c': 0.8}

        with patch.object(selector, '_build_diverse_pool', return_value=[]):
            selector.refresh_pools(
                available_ids={'a', 'b', 'c', 'd'},
                cartography_scores=scores,
            )

        # Pool should be sorted by variability descending
        assert selector._cartography_pool == ['c', 'a', 'b']

    def test_refresh_pools_cartography_excludes_zero_variability(self):
        selector = InstanceSelector()
        scores = {'a': 0.5, 'b': 0.0, 'c': 0.3}

        with patch.object(selector, '_build_diverse_pool', return_value=[]):
            selector.refresh_pools(
                available_ids={'a', 'b', 'c'},
                cartography_scores=scores,
            )

        assert 'b' not in selector._cartography_pool
        assert selector._cartography_pool == ['a', 'c']

    def test_refresh_pools_cartography_filters_available(self):
        selector = InstanceSelector()
        scores = {'a': 0.5, 'b': 0.3, 'x': 0.9}  # 'x' not in available

        with patch.object(selector, '_build_diverse_pool', return_value=[]):
            selector.refresh_pools(
                available_ids={'a', 'b'},
                cartography_scores=scores,
            )

        assert 'x' not in selector._cartography_pool

    def test_selection_from_cartography_pool(self):
        """When cartography weight is 1.0, should select from that pool."""
        weights = SelectionWeights(
            low_confidence=0.0,
            diverse=0.0,
            random=0.0,
            disagreement=0.0,
            edge_case_rule=0.0,
            cartography=1.0,
        )
        selector = InstanceSelector(weights=weights)
        scores = {'a': 0.1, 'b': 0.9, 'c': 0.5}

        with patch.object(selector, '_build_diverse_pool', return_value=[]):
            selector.refresh_pools(
                available_ids={'a', 'b', 'c'},
                cartography_scores=scores,
            )

        selected = selector.select_next({'a', 'b', 'c'})
        # Should pick highest variability first
        assert selected == 'b'

    def test_cartography_pool_empty_fallback(self):
        weights = SelectionWeights(
            low_confidence=0.0,
            diverse=0.0,
            random=0.0,
            disagreement=0.0,
            edge_case_rule=0.0,
            cartography=1.0,
        )
        selector = InstanceSelector(weights=weights)

        with patch.object(selector, '_build_diverse_pool', return_value=[]):
            selector.refresh_pools(available_ids={'a', 'b'})

        # No cartography scores → empty pool → fallback
        selected = selector.select_next({'a', 'b'})
        assert selected in {'a', 'b'}

    def test_get_selection_stats_includes_cartography(self):
        selector = InstanceSelector()
        stats = selector.get_selection_stats()
        assert 'cartography' in stats['pool_sizes']
        assert 'cartography' in stats['weights']

    def test_configure_with_cartography_weight(self):
        selector = InstanceSelector()
        selector.configure(
            low_confidence_weight=0.3,
            diversity_weight=0.2,
            random_weight=0.1,
            disagreement_weight=0.1,
            edge_case_rule_weight=0.1,
            cartography_weight=0.2,
        )
        assert selector.weights.cartography == 0.2


class TestCartographyConfigParsing:
    """Test config parsing for cartography_weight."""

    def test_parse_cartography_weight_from_yaml(self):
        from potato.solo_mode.config import parse_solo_mode_config

        config_data = {
            'solo_mode': {
                'enabled': True,
                'labeling_models': [
                    {'endpoint_type': 'ollama', 'model': 'test'}
                ],
                'instance_selection': {
                    'low_confidence_weight': 0.3,
                    'diversity_weight': 0.2,
                    'random_weight': 0.15,
                    'disagreement_weight': 0.1,
                    'cartography_weight': 0.25,
                },
            },
        }
        config = parse_solo_mode_config(config_data)
        assert config.instance_selection.cartography_weight == 0.25

    def test_cartography_weight_default_zero(self):
        from potato.solo_mode.config import parse_solo_mode_config

        config_data = {
            'solo_mode': {
                'enabled': True,
                'labeling_models': [
                    {'endpoint_type': 'ollama', 'model': 'test'}
                ],
            },
        }
        config = parse_solo_mode_config(config_data)
        assert config.instance_selection.cartography_weight == 0.0
