"""Unit tests for the corpus map ingest pipeline (Phase 1).

Determinism is asserted on k-means CLUSTER ASSIGNMENTS (fixed seed), not on exact
UMAP coordinates (which vary across library/BLAS versions). Embeddings are
injected via a deterministic function so tests don't download a model.
"""

import re
import subprocess
import sys

import numpy as np
import pytest

from potato.corpus_map.manager import CorpusMapManager


def _hash_embed(texts):
    """Deterministic bag-of-words embedding (no model needed)."""
    dim = 48
    out = []
    for t in texts:
        v = np.zeros(dim)
        for w in re.findall(r"[a-z]{3,}", t.lower()):
            v[hash(w) % dim] += 1.0
        n = np.linalg.norm(v)
        out.append(v / n if n else v)
    return out


DOCS = {
    "d1": "flood flooding water river rising bangkok thailand",
    "d2": "flood flooding water damage thailand ayutthaya homes",
    "d3": "earthquake quake shaking tokyo japan collapse building",
    "d4": "earthquake quake damage japan tsunami seawall coast",
    "d5": "wildfire fire smoke california forest burning homes",
    "d6": "wildfire fire evacuation california flames spreading",
}


@pytest.fixture
def mgr(tmp_path):
    cfg = {
        "output_annotation_dir": str(tmp_path),
        "item_properties": {"text_key": "text"},
        "corpus_map": {
            "enabled": True,
            "clustering": {"num_clusters": 3, "items_per_cluster": 2},
            "knn": {"k": 3},
        },
        "_corpus_map_embed_fn": _hash_embed,
    }
    m = CorpusMapManager(cfg)
    m._collect_texts = lambda: dict(DOCS)
    return m


class TestBuild:
    def test_build_produces_all_points(self, mgr):
        st = mgr.build(force=True)
        assert st["state"] == "done"
        md = mgr.map_data()
        assert len(md["points"]) == len(DOCS)
        assert all("x" in p and "y" in p and "cluster" in p for p in md["points"])

    def test_cluster_assignments_deterministic(self, mgr):
        mgr.build(force=True)
        first = {p["doc_id"]: p["cluster"] for p in mgr.map_data()["points"]}
        mgr.build(force=True)
        second = {p["doc_id"]: p["cluster"] for p in mgr.map_data()["points"]}
        assert first == second

    def test_knn_excludes_self_and_respects_k(self, mgr):
        mgr.build(force=True)
        neigh = mgr.knn("d1")
        assert len(neigh) == 3  # k=3
        assert all(n["doc_id"] != "d1" for n in neigh)
        # scores are sorted descending
        scores = [n["score"] for n in neigh]
        assert scores == sorted(scores, reverse=True)

    def test_cache_roundtrip(self, mgr, tmp_path):
        mgr.build(force=True)
        pts = {p["doc_id"]: p["cluster"] for p in mgr.map_data()["points"]}
        # A fresh manager over the same output dir loads the cache.
        cfg = dict(mgr.config)
        m2 = CorpusMapManager(cfg)
        assert m2.is_built()
        pts2 = {p["doc_id"]: p["cluster"] for p in m2.map_data()["points"]}
        assert pts == pts2

    def test_clusters_have_labels(self, mgr):
        mgr.build(force=True)
        clusters = mgr.clusters()
        assert clusters
        assert all(c.get("label") for c in clusters)
        # Cluster docs partition the corpus.
        all_docs = sorted(d for c in clusters for d in c["doc_ids"])
        assert all_docs == sorted(DOCS)


class TestImportWeight:
    def test_corpus_map_import_is_light(self):
        """Importing the manager must NOT pull in the ML stack (fresh interpreter)."""
        code = (
            "import sys; import potato.corpus_map.manager as m; "
            "banned=[x for x in ('sentence_transformers','sklearn','umap') "
            "if x in sys.modules]; "
            "print('LOADED:'+','.join(banned)); "
            "sys.exit(1 if banned else 0)"
        )
        res = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True
        )
        assert res.returncode == 0, (
            f"corpus_map.manager eagerly imported ML stack: {res.stdout} {res.stderr}"
        )
