"""
Tests for ConfidenceRouter.

Tests cascaded confidence escalation: tier acceptance, escalation,
human routing, error handling, and statistics tracking.
"""

import pytest
from unittest.mock import MagicMock, patch

from potato.solo_mode.confidence_router import (
    ConfidenceRouter,
    RoutingResult,
    TierStats,
)
from potato.solo_mode.config import (
    ConfidenceRoutingConfig,
    ConfidenceTierConfig,
    ModelConfig,
)
from potato.solo_mode.llm_labeler import LabelingResult


def _make_labeling_result(instance_id="i1", confidence=0.9, error=None, label="positive"):
    """Helper to create a LabelingResult."""
    return LabelingResult(
        instance_id=instance_id,
        schema_name="sentiment",
        label=label,
        confidence=confidence,
        uncertainty=1.0 - confidence,
        reasoning="test",
        prompt_version=1,
        model_name="test-model",
        error=error,
    )


def _make_routing_config(tiers=None):
    """Helper to create a ConfidenceRoutingConfig."""
    if tiers is None:
        tiers = [
            ConfidenceTierConfig(
                model=ModelConfig(endpoint_type='openai', model='gpt-4o-mini'),
                confidence_threshold=0.85,
                name='fast',
            ),
            ConfidenceTierConfig(
                model=ModelConfig(endpoint_type='anthropic', model='claude-sonnet'),
                confidence_threshold=0.65,
                name='strong',
            ),
        ]
    return ConfidenceRoutingConfig(enabled=True, tiers=tiers)


class TestTierStats:
    """Tests for TierStats dataclass."""

    def test_defaults(self):
        stats = TierStats(name="test")
        assert stats.instances_attempted == 0
        assert stats.avg_confidence == 0.0
        assert stats.acceptance_rate == 0.0
        assert stats.avg_latency_ms == 0.0

    def test_avg_confidence(self):
        stats = TierStats(
            name="test",
            instances_accepted=2,
            total_confidence=1.6,
        )
        assert abs(stats.avg_confidence - 0.8) < 0.001

    def test_acceptance_rate(self):
        stats = TierStats(
            name="test",
            instances_attempted=10,
            instances_accepted=7,
        )
        assert abs(stats.acceptance_rate - 0.7) < 0.001

    def test_avg_latency(self):
        stats = TierStats(
            name="test",
            instances_attempted=5,
            total_latency_ms=500.0,
        )
        assert abs(stats.avg_latency_ms - 100.0) < 0.001

    def test_to_dict(self):
        stats = TierStats(
            name="fast",
            instances_attempted=10,
            instances_accepted=8,
            instances_escalated=2,
            instances_errored=0,
            total_confidence=7.2,
            total_latency_ms=1000.0,
        )
        d = stats.to_dict()
        assert d['name'] == 'fast'
        assert d['instances_attempted'] == 10
        assert d['instances_accepted'] == 8
        assert d['instances_escalated'] == 2
        assert d['acceptance_rate'] == 0.8
        assert d['avg_confidence'] == 0.9


class TestRoutingResult:
    """Tests for RoutingResult dataclass."""

    def test_defaults(self):
        r = RoutingResult(instance_id="i1")
        assert r.accepted is False
        assert r.routed_to_human is False
        assert r.tier_index == -1
        assert r.labeling_result is None
        assert r.attempts == []


class TestConfidenceRouterAcceptance:
    """Tests for tier acceptance behavior."""

    def test_tier1_accepts_high_confidence(self):
        """Tier 1 accepts when confidence >= threshold."""
        config = _make_routing_config()
        mock_endpoint = MagicMock()

        def label_fn(iid, text, schema, endpoint):
            return _make_labeling_result(iid, confidence=0.92)

        router = ConfidenceRouter(
            routing_config=config,
            label_fn=label_fn,
            endpoint_factory=lambda mc: mock_endpoint,
        )

        result = router.route_instance("i1", "great product", "sentiment")
        assert result.accepted is True
        assert result.routed_to_human is False
        assert result.tier_index == 0
        assert result.tier_name == "fast"
        assert result.labeling_result.confidence == 0.92
        assert len(result.attempts) == 1
        assert result.attempts[0]['accepted'] is True

    def test_tier1_escalates_tier2_accepts(self):
        """Tier 1 escalates, Tier 2 accepts."""
        config = _make_routing_config()
        mock_endpoint = MagicMock()
        call_count = [0]

        def label_fn(iid, text, schema, endpoint):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_labeling_result(iid, confidence=0.70)  # Below 0.85
            else:
                return _make_labeling_result(iid, confidence=0.75)  # Above 0.65

        router = ConfidenceRouter(
            routing_config=config,
            label_fn=label_fn,
            endpoint_factory=lambda mc: mock_endpoint,
        )

        result = router.route_instance("i1", "mixed feelings", "sentiment")
        assert result.accepted is True
        assert result.routed_to_human is False
        assert result.tier_index == 1
        assert result.tier_name == "strong"
        assert len(result.attempts) == 2
        assert result.attempts[0]['accepted'] is False
        assert result.attempts[1]['accepted'] is True

    def test_all_tiers_fail_routes_to_human(self):
        """All tiers below threshold -> routed to human."""
        config = _make_routing_config()
        mock_endpoint = MagicMock()

        def label_fn(iid, text, schema, endpoint):
            return _make_labeling_result(iid, confidence=0.30)  # Below all thresholds

        router = ConfidenceRouter(
            routing_config=config,
            label_fn=label_fn,
            endpoint_factory=lambda mc: mock_endpoint,
        )

        result = router.route_instance("i1", "ambiguous text", "sentiment")
        assert result.accepted is False
        assert result.routed_to_human is True
        assert len(result.attempts) == 2
        # Best result is still stored
        assert result.labeling_result is not None
        assert result.labeling_result.confidence == 0.30


class TestConfidenceRouterErrorHandling:
    """Tests for error handling during routing."""

    def test_endpoint_creation_failure_skips_tier(self):
        """If endpoint creation fails, skip to next tier."""
        config = _make_routing_config()
        call_count = [0]

        def factory(mc):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("API key invalid")
            return MagicMock()

        def label_fn(iid, text, schema, endpoint):
            return _make_labeling_result(iid, confidence=0.80)

        router = ConfidenceRouter(
            routing_config=config,
            label_fn=label_fn,
            endpoint_factory=factory,
        )

        result = router.route_instance("i1", "text", "sentiment")
        assert result.accepted is True
        assert result.tier_index == 1
        assert len(result.attempts) == 2
        assert 'error' in result.attempts[0]

    def test_label_fn_returns_none_skips_tier(self):
        """If label_fn returns None, skip to next tier."""
        config = _make_routing_config()
        mock_endpoint = MagicMock()
        call_count = [0]

        def label_fn(iid, text, schema, endpoint):
            call_count[0] += 1
            if call_count[0] == 1:
                return None
            return _make_labeling_result(iid, confidence=0.80)

        router = ConfidenceRouter(
            routing_config=config,
            label_fn=label_fn,
            endpoint_factory=lambda mc: mock_endpoint,
        )

        result = router.route_instance("i1", "text", "sentiment")
        assert result.accepted is True
        assert result.tier_index == 1

    def test_label_fn_returns_error_skips_tier(self):
        """If label_fn returns a result with error, skip to next tier."""
        config = _make_routing_config()
        mock_endpoint = MagicMock()
        call_count = [0]

        def label_fn(iid, text, schema, endpoint):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_labeling_result(iid, error="Rate limited")
            return _make_labeling_result(iid, confidence=0.80)

        router = ConfidenceRouter(
            routing_config=config,
            label_fn=label_fn,
            endpoint_factory=lambda mc: mock_endpoint,
        )

        result = router.route_instance("i1", "text", "sentiment")
        assert result.accepted is True
        assert result.tier_index == 1

    def test_label_fn_raises_exception_skips_tier(self):
        """If label_fn raises an exception, skip to next tier."""
        config = _make_routing_config()
        mock_endpoint = MagicMock()
        call_count = [0]

        def label_fn(iid, text, schema, endpoint):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("Timeout")
            return _make_labeling_result(iid, confidence=0.80)

        router = ConfidenceRouter(
            routing_config=config,
            label_fn=label_fn,
            endpoint_factory=lambda mc: mock_endpoint,
        )

        result = router.route_instance("i1", "text", "sentiment")
        assert result.accepted is True
        assert result.tier_index == 1
        assert 'error' in result.attempts[0]

    def test_all_tiers_error_routes_to_human(self):
        """All tiers error -> routes to human."""
        config = _make_routing_config()
        mock_endpoint = MagicMock()

        def label_fn(iid, text, schema, endpoint):
            return None

        router = ConfidenceRouter(
            routing_config=config,
            label_fn=label_fn,
            endpoint_factory=lambda mc: mock_endpoint,
        )

        result = router.route_instance("i1", "text", "sentiment")
        assert result.accepted is False
        assert result.routed_to_human is True


class TestConfidenceRouterStats:
    """Tests for statistics tracking."""

    def test_stats_after_acceptance(self):
        """Stats update correctly after tier 1 acceptance."""
        config = _make_routing_config()
        mock_endpoint = MagicMock()

        def label_fn(iid, text, schema, endpoint):
            return _make_labeling_result(iid, confidence=0.90)

        router = ConfidenceRouter(
            routing_config=config,
            label_fn=label_fn,
            endpoint_factory=lambda mc: mock_endpoint,
        )

        router.route_instance("i1", "text", "sentiment")
        stats = router.get_stats()

        assert stats['enabled'] is True
        assert stats['num_tiers'] == 2
        assert stats['total_routed'] == 1
        assert stats['human_routed_count'] == 0

        tier0 = stats['tiers'][0]
        assert tier0['instances_attempted'] == 1
        assert tier0['instances_accepted'] == 1
        assert tier0['instances_escalated'] == 0

        tier1 = stats['tiers'][1]
        assert tier1['instances_attempted'] == 0

    def test_stats_after_escalation(self):
        """Stats update correctly after tier escalation."""
        config = _make_routing_config()
        mock_endpoint = MagicMock()
        call_count = [0]

        def label_fn(iid, text, schema, endpoint):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_labeling_result(iid, confidence=0.50)
            return _make_labeling_result(iid, confidence=0.70)

        router = ConfidenceRouter(
            routing_config=config,
            label_fn=label_fn,
            endpoint_factory=lambda mc: mock_endpoint,
        )

        router.route_instance("i1", "text", "sentiment")
        stats = router.get_stats()

        tier0 = stats['tiers'][0]
        assert tier0['instances_attempted'] == 1
        assert tier0['instances_escalated'] == 1
        assert tier0['instances_accepted'] == 0

        tier1 = stats['tiers'][1]
        assert tier1['instances_attempted'] == 1
        assert tier1['instances_accepted'] == 1

    def test_stats_after_human_routing(self):
        """Stats update correctly when routed to human."""
        config = _make_routing_config()
        mock_endpoint = MagicMock()

        def label_fn(iid, text, schema, endpoint):
            return _make_labeling_result(iid, confidence=0.20)

        router = ConfidenceRouter(
            routing_config=config,
            label_fn=label_fn,
            endpoint_factory=lambda mc: mock_endpoint,
        )

        router.route_instance("i1", "text", "sentiment")
        stats = router.get_stats()
        assert stats['human_routed_count'] == 1
        assert stats['total_routed'] == 1

    def test_stats_multiple_instances(self):
        """Stats accumulate across multiple instances."""
        config = _make_routing_config()
        mock_endpoint = MagicMock()
        confidences = iter([0.90, 0.50, 0.70, 0.20, 0.20])

        def label_fn(iid, text, schema, endpoint):
            return _make_labeling_result(iid, confidence=next(confidences))

        router = ConfidenceRouter(
            routing_config=config,
            label_fn=label_fn,
            endpoint_factory=lambda mc: mock_endpoint,
        )

        # i1: tier 0 accepts (0.90 >= 0.85)
        router.route_instance("i1", "text1", "sentiment")
        # i2: tier 0 escalates (0.50 < 0.85), tier 1 accepts (0.70 >= 0.65)
        router.route_instance("i2", "text2", "sentiment")
        # i3: tier 0 escalates (0.20 < 0.85), tier 1 escalates (0.20 < 0.65) -> human
        router.route_instance("i3", "text3", "sentiment")

        stats = router.get_stats()
        assert stats['total_routed'] == 3
        assert stats['human_routed_count'] == 1

        tier0 = stats['tiers'][0]
        assert tier0['instances_attempted'] == 3
        assert tier0['instances_accepted'] == 1
        assert tier0['instances_escalated'] == 2

        tier1 = stats['tiers'][1]
        assert tier1['instances_attempted'] == 2
        assert tier1['instances_accepted'] == 1
        assert tier1['instances_escalated'] == 1

    def test_stats_reset(self):
        """Stats reset clears all counters."""
        config = _make_routing_config()
        mock_endpoint = MagicMock()

        def label_fn(iid, text, schema, endpoint):
            return _make_labeling_result(iid, confidence=0.90)

        router = ConfidenceRouter(
            routing_config=config,
            label_fn=label_fn,
            endpoint_factory=lambda mc: mock_endpoint,
        )

        router.route_instance("i1", "text", "sentiment")
        router.reset_stats()

        stats = router.get_stats()
        assert stats['total_routed'] == 0
        assert stats['human_routed_count'] == 0
        for tier in stats['tiers']:
            assert tier['instances_attempted'] == 0
            assert tier['instances_accepted'] == 0


class TestConfidenceRouterEdgeCases:
    """Tests for edge cases and configuration validation."""

    def test_single_tier(self):
        """Router works with a single tier."""
        config = _make_routing_config(tiers=[
            ConfidenceTierConfig(
                model=ModelConfig(endpoint_type='openai', model='gpt-4o-mini'),
                confidence_threshold=0.80,
                name='only',
            ),
        ])
        mock_endpoint = MagicMock()

        def label_fn(iid, text, schema, endpoint):
            return _make_labeling_result(iid, confidence=0.85)

        router = ConfidenceRouter(
            routing_config=config,
            label_fn=label_fn,
            endpoint_factory=lambda mc: mock_endpoint,
        )

        result = router.route_instance("i1", "text", "sentiment")
        assert result.accepted is True
        assert result.tier_name == "only"

    def test_empty_tiers_routes_to_human(self):
        """Empty tiers list immediately routes to human."""
        config = _make_routing_config(tiers=[])
        router = ConfidenceRouter(
            routing_config=config,
            label_fn=lambda *a: None,
            endpoint_factory=lambda mc: MagicMock(),
        )

        result = router.route_instance("i1", "text", "sentiment")
        assert result.accepted is False
        assert result.routed_to_human is True

    def test_exact_threshold_accepts(self):
        """Confidence exactly equal to threshold is accepted."""
        config = _make_routing_config(tiers=[
            ConfidenceTierConfig(
                model=ModelConfig(endpoint_type='openai', model='test'),
                confidence_threshold=0.80,
                name='exact',
            ),
        ])
        mock_endpoint = MagicMock()

        def label_fn(iid, text, schema, endpoint):
            return _make_labeling_result(iid, confidence=0.80)

        router = ConfidenceRouter(
            routing_config=config,
            label_fn=label_fn,
            endpoint_factory=lambda mc: mock_endpoint,
        )

        result = router.route_instance("i1", "text", "sentiment")
        assert result.accepted is True

    def test_endpoint_caching(self):
        """Endpoints are cached per tier."""
        config = _make_routing_config()
        factory_calls = [0]

        def factory(mc):
            factory_calls[0] += 1
            return MagicMock()

        def label_fn(iid, text, schema, endpoint):
            return _make_labeling_result(iid, confidence=0.90)

        router = ConfidenceRouter(
            routing_config=config,
            label_fn=label_fn,
            endpoint_factory=factory,
        )

        router.route_instance("i1", "text1", "sentiment")
        router.route_instance("i2", "text2", "sentiment")

        # Factory should only be called once for tier 0 (both accepted at tier 0)
        assert factory_calls[0] == 1
