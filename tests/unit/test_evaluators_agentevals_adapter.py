"""Tests for the lazy agentevals adapter (graceful when not installed)."""

import sys

import pytest

from potato.evaluators import agentevals_adapter as adapter


def test_importing_adapter_does_not_import_agentevals():
    # Merely importing the adapter module must not import the optional dep.
    assert "agentevals" not in sys.modules


def test_factories_raise_when_unavailable():
    if adapter.is_available():
        pytest.skip("agentevals is installed; degradation path not exercised")
    with pytest.raises(ImportError):
        adapter.graph_trajectory_strict_match()
    with pytest.raises(ImportError):
        adapter.graph_trajectory_llm_judge()


def test_wrapper_normalizes_agentevals_result():
    # Wrap a fake agentevals-style callable and confirm result mapping.
    fake = lambda outputs=None, reference_outputs=None, **kw: {
        "key": "graph_trajectory_strict_match", "score": True, "comment": "ok"}
    wrapped = adapter._AgentEvalsWrapper(fake, key="graph_trajectory_strict_match")
    r = wrapped.evaluate(outputs="x", reference_outputs="y")
    assert r.score == 1.0  # bool True -> 1.0
    assert r.metadata["source"] == "agentevals"
    assert r.comment == "ok"
