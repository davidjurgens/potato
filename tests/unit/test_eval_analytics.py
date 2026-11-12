"""Unit tests for cost/latency analytics + regression alerts (D9)."""

import pytest

from potato.server_utils import eval_analytics as an


class TestExtractMetrics:
    def test_nested_usage_and_latency(self):
        m = an.extract_metrics({"model": "gpt-4o", "latency_ms": 1200,
                                "usage": {"prompt_tokens": 100, "completion_tokens": 50}})
        assert m.model == "gpt-4o"
        assert m.prompt_tokens == 100 and m.completion_tokens == 50
        assert m.total_tokens == 150  # derived when total absent
        assert m.latency_ms == 1200

    def test_metadata_table_fallback(self):
        m = an.extract_metrics({"metadata_table": [
            {"Property": "Total Tokens", "Value": "320"},
            {"Property": "Model", "Value": "claude"}]})
        assert m.total_tokens == 320 and m.model == "claude"

    def test_cost_from_pricing(self):
        m = an.extract_metrics(
            {"model": "gpt-4o", "usage": {"prompt_tokens": 1000, "completion_tokens": 1000}},
            pricing={"gpt-4o": {"in": 2.5, "out": 10.0}})
        assert m.cost == pytest.approx(2.5 + 10.0)  # 1k in @2.5 + 1k out @10

    def test_explicit_cost_wins(self):
        m = an.extract_metrics({"model": "x", "cost": 0.42,
                                "usage": {"prompt_tokens": 100}},
                               pricing={"x": {"in": 99, "out": 99}})
        assert m.cost == 0.42

    def test_error_status(self):
        assert an.extract_metrics({"status": "error"}).is_error is True
        assert an.extract_metrics({"status": "success"}).is_error is False
        assert an.extract_metrics({"outcome": "failed"}).is_error is True


class TestComputeAnalytics:
    def _items(self):
        return [
            {"model": "a", "latency_ms": 100, "usage": {"total_tokens": 10}, "status": "ok"},
            {"model": "a", "latency_ms": 300, "usage": {"total_tokens": 20}, "status": "error"},
            {"model": "b", "latency_ms": 200, "usage": {"total_tokens": 30}, "status": "ok"},
        ]

    def test_totals_and_error_rate(self):
        a = an.compute_analytics(self._items())
        assert a["count"] == 3
        assert a["total_tokens"] == 60
        assert a["error_rate"] == pytest.approx(1 / 3, abs=1e-4)
        assert a["errors"] == 1

    def test_latency_percentiles(self):
        a = an.compute_analytics(self._items())
        assert a["avg_latency_ms"] == 200.0
        assert a["p50_latency_ms"] == 200.0
        assert a["p95_latency_ms"] is not None

    def test_per_model_breakdown(self):
        a = an.compute_analytics(self._items())
        assert a["per_model"]["a"]["count"] == 2
        assert a["per_model"]["a"]["errors"] == 1
        assert a["per_model"]["b"]["total_tokens"] == 30

    def test_empty(self):
        a = an.compute_analytics([])
        assert a["count"] == 0 and a["error_rate"] == 0.0


class TestRegressions:
    def test_cost_spike_flagged(self):
        base = {"count": 100, "total_cost": 10.0, "avg_latency_ms": 500, "error_rate": 0.0}
        recent = {"count": 100, "total_cost": 20.0, "avg_latency_ms": 500, "error_rate": 0.0}
        alerts = an.detect_regressions(recent, base)
        assert any(a["metric"] == "cost_per_trace" for a in alerts)
        assert alerts[0]["severity"] == "high"  # +100%

    def test_latency_regression_flagged(self):
        base = {"count": 50, "total_cost": 1.0, "avg_latency_ms": 400, "error_rate": 0.0}
        recent = {"count": 50, "total_cost": 1.0, "avg_latency_ms": 600, "error_rate": 0.0}
        alerts = an.detect_regressions(recent, base)
        assert any(a["metric"] == "avg_latency_ms" for a in alerts)

    def test_error_rate_regression_flagged(self):
        base = {"count": 100, "total_cost": 1.0, "avg_latency_ms": 100, "error_rate": 0.01}
        recent = {"count": 100, "total_cost": 1.0, "avg_latency_ms": 100, "error_rate": 0.20}
        alerts = an.detect_regressions(recent, base)
        assert any(a["metric"] == "error_rate" and a["severity"] == "high" for a in alerts)

    def test_no_regression_when_stable(self):
        base = {"count": 100, "total_cost": 10.0, "avg_latency_ms": 500, "error_rate": 0.02}
        recent = {"count": 100, "total_cost": 10.5, "avg_latency_ms": 520, "error_rate": 0.02}
        assert an.detect_regressions(recent, base) == []
