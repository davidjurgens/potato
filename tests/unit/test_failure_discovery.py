"""Unit tests for failure-mode discovery via clustering + axial coding (E1)."""

import json
import pytest

from potato.curation.index import EmbeddingIndex
from potato.curation.discovery import (
    kmeans_cosine, discover_failure_modes, DiscoveredCluster,
)


def _two_blobs():
    """Two well-separated blobs in 3-D (cluster A near x-axis, B near y-axis)."""
    items = []
    for i in range(5):
        items.append((f"a{i}", [1.0, 0.05 * i, 0.0]))
    for i in range(5):
        items.append((f"b{i}", [0.0, 0.05 * i, 1.0]))
    return items


class TestKMeansCosine:
    def test_separates_two_blobs(self):
        labels = kmeans_cosine(_two_blobs(), k=2)
        a_labels = {labels[f"a{i}"] for i in range(5)}
        b_labels = {labels[f"b{i}"] for i in range(5)}
        assert len(a_labels) == 1 and len(b_labels) == 1
        assert a_labels != b_labels  # the two blobs land in different clusters

    def test_deterministic(self):
        items = _two_blobs()
        assert kmeans_cosine(items, k=2) == kmeans_cosine(items, k=2)

    def test_k_clamped_to_n(self):
        labels = kmeans_cosine([("x", [1.0, 0.0])], k=5)
        assert set(labels.values()) == {0}

    def test_empty(self):
        assert kmeans_cosine([], k=3) == {}


class _StubJudge:
    """Names a cluster from its examples (echoes a fixed label)."""
    def __init__(self, label="tool error", desc="the agent calls the wrong tool"):
        self.label, self.desc = label, desc
        self.calls = 0
    def query(self, prompt, model=None):
        self.calls += 1
        return json.dumps({"label": self.label, "description": self.desc})


class TestDiscoverFailureModes:
    def _index(self):
        idx = EmbeddingIndex()
        for iid, vec in _two_blobs():
            idx.add(iid, vec)
        return idx

    def test_clusters_sorted_by_size(self):
        idx = self._index()
        idx.add("a5", [1.0, 0.3, 0.0])  # make cluster A bigger
        texts = {**{f"a{i}": "tool failed" for i in range(6)},
                 **{f"b{i}": "gave up early" for i in range(5)}}
        clusters = discover_failure_modes(idx, lambda i: texts.get(i, ""), k=2, llm=None)
        assert len(clusters) == 2
        assert clusters[0].size >= clusters[1].size  # largest first
        assert all(isinstance(c, DiscoveredCluster) for c in clusters)

    def test_examples_are_populated(self):
        idx = self._index()
        clusters = discover_failure_modes(idx, lambda i: f"text-{i}", k=2, llm=None)
        assert all(c.examples for c in clusters)
        assert all(c.suggested_label == "" for c in clusters)  # no LLM -> no axial code

    def test_llm_axial_labeling(self):
        idx = self._index()
        judge = _StubJudge(label="premature termination")
        clusters = discover_failure_modes(idx, lambda i: f"trace {i}", k=2, llm=judge)
        assert judge.calls == 2  # one axial-coding call per cluster
        assert all(c.suggested_label == "premature termination" for c in clusters)

    def test_restrict_to_instance_ids(self):
        idx = self._index()
        only = [f"a{i}" for i in range(5)]
        clusters = discover_failure_modes(idx, lambda i: "x", k=2, llm=None, instance_ids=only)
        members = {m for c in clusters for m in c.member_ids}
        assert members == set(only)

    def test_empty_index(self):
        assert discover_failure_modes(EmbeddingIndex(), lambda i: "", k=3) == []
