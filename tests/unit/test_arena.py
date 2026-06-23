"""Unit tests for the multi-model arena (hermetic — stub endpoints, no LLMs)."""

import pytest

from potato.arena.config import ArenaConfig, ArenaModel
from potato.arena.arena import run_arena
from potato.arena.manager import ArenaManager


MODELS = [
    ArenaModel(label="A", endpoint_type="stub", model="m-a"),
    ArenaModel(label="B", endpoint_type="stub", model="m-b"),
    ArenaModel(label="C", endpoint_type="stub", model="m-c"),
]


class _StubEndpoint:
    def __init__(self, label):
        self.label = label
    def query(self, prompt, output_format=None):
        return f"{self.label} says: {prompt}"


def _builder(m):
    return _StubEndpoint(m.label)


# ---- config ----

def test_config_parsing():
    cfg = ArenaConfig.from_config({"arena": {"enabled": True, "models": [
        {"label": "GPT", "endpoint_type": "openai", "model": "gpt-4o", "temperature": 0.2},
        {"endpoint_type": "ollama", "model": "qwen"},  # label defaults to model
    ]}})
    assert cfg.enabled
    assert cfg.models[0].label == "GPT" and cfg.models[0].temperature == 0.2
    assert cfg.models[1].label == "qwen"


# ---- fan-out ----

def test_run_arena_ordered_results():
    results = run_arena("hello", MODELS, endpoint_builder=_builder)
    assert [r["label"] for r in results] == ["A", "B", "C"]   # input order preserved
    assert results[0]["response"] == "A says: hello"
    assert all(r["error"] is None for r in results)
    assert all(isinstance(r["latency_ms"], int) for r in results)


def test_run_arena_one_model_fails_others_ok():
    def flaky_builder(m):
        if m.label == "B":
            raise RuntimeError("provider down")
        return _StubEndpoint(m.label)
    results = run_arena("hi", MODELS, endpoint_builder=flaky_builder)
    by = {r["label"]: r for r in results}
    assert by["B"]["error"] == "provider down" and by["B"]["response"] == ""
    assert by["A"]["error"] is None and by["A"]["response"] == "A says: hi"


def test_run_arena_empty_models():
    assert run_arena("x", []) == []


# ---- manager + leaderboard ----

@pytest.fixture
def manager():
    mgr = ArenaManager({"arena": {"enabled": True, "models": [
        {"label": "A", "endpoint_type": "stub"}, {"label": "B", "endpoint_type": "stub"},
        {"label": "C", "endpoint_type": "stub"}]}})
    mgr.endpoint_builder = _builder
    return mgr


def test_manager_run_and_history(manager):
    results = manager.run("q1")
    assert len(results) == 3
    assert len(manager.history) == 1


def test_manager_preferences_and_leaderboard(manager):
    manager.run("q1")
    manager.record_preference("q1", winner="A")   # A vs B vs C, A wins
    manager.record_preference("q2", winner="A")
    manager.record_preference("q3", winner="B")
    lb = {r["label"]: r for r in manager.leaderboard()}
    assert lb["A"]["wins"] == 2 and lb["A"]["comparisons"] == 3
    assert lb["A"]["win_rate"] == pytest.approx(2 / 3, abs=1e-3)  # stored rounded to 3dp
    assert lb["B"]["wins"] == 1
    # leaderboard sorted by win_rate desc -> A first
    assert manager.leaderboard()[0]["label"] == "A"
