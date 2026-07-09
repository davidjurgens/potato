"""
Unit tests for D2 Topics (persisted pattern groups over curation embeddings).

Covers: Topic/TopicStore persistence, centroid computation, nearest-centroid
auto-assignment (threshold + idempotence), discovered-vs-manual replacement
semantics, and topics_from_clusters naming.
"""

import pytest

from potato.curation.discovery import DiscoveredCluster
from potato.curation.topics import (
    DEFAULT_ASSIGN_THRESHOLD,
    Topic,
    TopicStore,
    assign_instance,
    centroid_of,
    topics_from_clusters,
)
from tests.helpers.test_utils import create_test_directory


VECS = {
    "a1": [1.0, 0.0, 0.0],
    "a2": [0.9, 0.1, 0.0],
    "b1": [0.0, 1.0, 0.0],
    "b2": [0.0, 0.95, 0.05],
}


def get_vec(iid):
    return VECS.get(iid)


class TestTopicStore:
    def test_round_trip_persistence(self):
        base = create_test_directory("topics_store")
        store = TopicStore(base)
        store.save(Topic(name="tool-failures", description="d",
                         centroid=[1.0, 0.0, 0.0], member_ids=["a1"]))
        # Fresh store re-reads from disk
        store2 = TopicStore(base)
        t = store2.get("tool-failures")
        assert t is not None and t.member_ids == ["a1"]
        assert t.centroid == [1.0, 0.0, 0.0]

    def test_list_sorted_by_size(self):
        store = TopicStore(None)
        store.save(Topic(name="small", member_ids=["x"]))
        store.save(Topic(name="big", member_ids=["a", "b", "c"]))
        assert [t.name for t in store.list()] == ["big", "small"]

    def test_replace_discovered_keeps_manual(self):
        store = TopicStore(None)
        store.save(Topic(name="hand-made", source="manual", member_ids=["m"]))
        store.save(Topic(name="old-discovered", source="discovered"))
        store.replace_discovered([Topic(name="new-discovered", source="discovered")])
        names = {t.name for t in store.list()}
        assert names == {"hand-made", "new-discovered"}

    def test_topic_of(self):
        store = TopicStore(None)
        store.save(Topic(name="t", member_ids=["a1", "a2"]))
        assert store.topic_of("a2") == "t"
        assert store.topic_of("zz") is None

    def test_summary_excludes_centroid(self):
        s = Topic(name="t", centroid=[0.1] * 128, member_ids=["a"]).summary()
        assert "centroid" not in s and s["size"] == 1


class TestCentroidAndAssignment:
    def test_centroid_is_normalized_mean(self):
        c = centroid_of(["a1", "a2"], get_vec)
        assert len(c) == 3
        assert abs(sum(x * x for x in c) - 1.0) < 1e-9
        assert c[0] > 0.9  # dominated by the x-axis

    def test_assign_to_nearest_topic(self):
        store = TopicStore(None)
        store.save(Topic(name="x-axis", centroid=centroid_of(["a1", "a2"], get_vec)))
        store.save(Topic(name="y-axis", centroid=centroid_of(["b1", "b2"], get_vec)))
        assert assign_instance("new1", [0.95, 0.05, 0.0], store) == "x-axis"
        assert "new1" in store.get("x-axis").member_ids

    def test_threshold_blocks_far_instances(self):
        store = TopicStore(None)
        store.save(Topic(name="x-axis", centroid=[1.0, 0.0, 0.0]))
        assert assign_instance("far", [0.0, 0.0, 1.0], store,
                               threshold=DEFAULT_ASSIGN_THRESHOLD) is None

    def test_assignment_idempotent(self):
        store = TopicStore(None)
        store.save(Topic(name="x-axis", centroid=[1.0, 0.0, 0.0], member_ids=["already"]))
        assert assign_instance("already", [1.0, 0.0, 0.0], store) == "x-axis"
        assert store.get("x-axis").member_ids.count("already") == 1

    def test_auto_assign_false_excluded(self):
        store = TopicStore(None)
        store.save(Topic(name="frozen", centroid=[1.0, 0.0, 0.0], auto_assign=False))
        assert assign_instance("n", [1.0, 0.0, 0.0], store) is None

    def test_empty_vector_ignored(self):
        store = TopicStore(None)
        store.save(Topic(name="t", centroid=[1.0, 0.0, 0.0]))
        assert assign_instance("n", [], store) is None


class TestTopicsFromClusters:
    def test_llm_labels_used(self):
        clusters = [DiscoveredCluster(cluster_id=0, member_ids=["a1", "a2"], size=2,
                                      suggested_label="Tool call failed",
                                      suggested_description="agent picked wrong tool")]
        topics = topics_from_clusters(clusters, get_vec, refreshed_at="2026-07-08T00:00:00")
        assert topics[0].name == "Tool call failed"
        assert topics[0].description == "agent picked wrong tool"
        assert topics[0].member_ids == ["a1", "a2"]
        assert topics[0].centroid  # computed from members
        assert topics[0].refreshed_at == "2026-07-08T00:00:00"

    def test_positional_fallback_names(self):
        clusters = [DiscoveredCluster(cluster_id=0, member_ids=["b1"], size=1)]
        topics = topics_from_clusters(clusters, get_vec)
        assert topics[0].name == "topic-1"


class TestAutomationAction:
    def test_refresh_topics_skips_without_curation(self):
        from potato.automation.actions import execute_action
        from potato.curation.manager import clear_curation_manager
        clear_curation_manager()
        out = execute_action({"type": "refresh_topics"}, {"item_id": "x", "item_data": {}})
        assert out["status"] == "skipped"

    def test_refresh_topics_registered_as_heavy(self):
        from potato.automation.actions import HEAVY_ACTIONS, _EXECUTORS
        assert "refresh_topics" in HEAVY_ACTIONS
        assert "refresh_topics" in _EXECUTORS
