"""Phase E: ICL per-instance selection (blend + coverage floor + MMR) and
the shared single instance embedding."""

import numpy as np
import pytest

from potato.rag import indexer, store, retriever
from potato.rag.icl_select import select
from potato.rag.store import _RAG_MIGRATION, _RAG_META_MIGRATION, SOURCE_ICL
from potato.persistence import clear_db_cache, clear_migrations, register_migration
from .fake_embedder import FakeEmbeddingEndpoint


@pytest.fixture(autouse=True)
def _isolated():
    clear_db_cache()
    clear_migrations()
    register_migration(_RAG_MIGRATION)
    register_migration(_RAG_META_MIGRATION)
    yield
    clear_db_cache()
    clear_migrations()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


class TestSelectBlendCoverageMMR:
    def test_gain_weight_blends_not_replaces(self):
        cands = [
            {"label": "a", "similarity": 0.9, "gain": 0.02, "vector": [1, 0]},
            {"label": "b", "similarity": 0.5, "gain": 0.30, "vector": [0, 1]},
        ]
        # similarity-only -> the high-sim one wins
        top_sim = select([dict(c) for c in cands], max_total=1,
                         min_per_label=0, gain_weight=0.0)[0]
        assert top_sim["label"] == "a"
        # gain-only -> the high-gain one wins (signal preserved, Req 1)
        top_gain = select([dict(c) for c in cands], max_total=1,
                          min_per_label=0, gain_weight=1.0)[0]
        assert top_gain["label"] == "b"

    def test_per_label_coverage_floor(self):
        # Three 'a' examples all out-score the lone 'b'; the floor still
        # guarantees 'b' representation (Req 2).
        cands = [
            {"label": "a", "similarity": 0.99, "gain": 0.1, "vector": [1, 0]},
            {"label": "a", "similarity": 0.98, "gain": 0.1, "vector": [1, 0]},
            {"label": "a", "similarity": 0.97, "gain": 0.1, "vector": [1, 0]},
            {"label": "b", "similarity": 0.40, "gain": 0.1, "vector": [0, 1]},
        ]
        chosen = select(cands, max_total=2, min_per_label=1, gain_weight=0.5)
        assert {c["label"] for c in chosen} == {"a", "b"}

    def test_mmr_prefers_diverse_over_near_duplicate(self):
        # Two near-identical vectors + one distinct; with no coverage floor
        # MMR should avoid picking both duplicates.
        cands = [
            {"label": "a", "similarity": 0.99, "gain": 0.0, "vector": [1, 0]},
            {"label": "a", "similarity": 0.98, "gain": 0.0, "vector": [1, 0.01]},
            {"label": "a", "similarity": 0.80, "gain": 0.0, "vector": [0, 1]},
        ]
        chosen = select(cands, max_total=2, min_per_label=0,
                        gain_weight=0.0, mmr_lambda=0.5)
        vecs = [tuple(np.round(c["vector"], 2)) for c in chosen]
        assert (0.0, 1.0) in vecs    # the distinct one made the cut


def _entries():
    return [
        {"instance_id": "p1", "text": "a violent riot smashed windows",
         "label": "riot", "gain": 0.20},
        {"instance_id": "p2", "text": "an aggressive mob set fires",
         "label": "riot", "gain": 0.05},
        {"instance_id": "n1", "text": "a peaceful march of thousands",
         "label": "demonstration", "gain": 0.18},
        {"instance_id": "n2", "text": "a calm candlelight vigil",
         "label": "demonstration", "gain": 0.04},
    ]


class TestRetrieveICL:
    def test_sync_then_retrieve_ranks_and_covers(self, td):
        ep = FakeEmbeddingEndpoint(dim=64)
        indexer.sync_icl_entries(td, "P", _entries(), endpoint=ep)
        out = retriever.retrieve_icl_examples(
            td, "P", "a violent riot broke windows downtown", k=2,
            endpoint=ep, min_per_label=1, gain_weight=0.3)
        # top hit is the most similar riot example; coverage floor keeps a
        # demonstration contrast example in the set.
        assert out[0]["label"] == "riot"
        assert {e["label"] for e in out} == {"riot", "demonstration"}

    def test_embeds_source_text_not_label(self, td):
        # The stored chunk text is the SOURCE text, never the label (minor).
        ep = FakeEmbeddingEndpoint(dim=64)
        indexer.sync_icl_entries(td, "P", _entries(), endpoint=ep)
        texts = {c["text"] for c in
                 store.get_chunks(td, "P", source_type=SOURCE_ICL)}
        assert "a violent riot smashed windows" in texts
        assert "riot" not in texts  # the bare label is not a chunk

    def test_sync_is_incremental(self, td):
        ep = FakeEmbeddingEndpoint(dim=64)
        n1 = indexer.sync_icl_entries(td, "P", _entries(), endpoint=ep)
        assert n1 == 4
        n2 = indexer.sync_icl_entries(td, "P", _entries(), endpoint=ep)
        assert n2 == 0                      # unchanged -> nothing re-embedded
        # dropping an entry removes its chunk
        indexer.sync_icl_entries(td, "P", _entries()[:3], endpoint=ep)
        assert len(store.get_chunks(td, "P", source_type=SOURCE_ICL)) == 3


class _CountingFake(FakeEmbeddingEndpoint):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.calls = 0

    def _embed(self, texts):
        self.calls += 1
        return super()._embed(texts)


class TestSharedEmbedding:
    def test_query_embedded_once_across_retrievers(self, td):
        from potato.rag.guidelines import set_guidelines
        ep = _CountingFake(dim=64)
        # Warm the corpora so nothing is stale.
        set_guidelines(td, "P", "- prefer riot when there is destruction")
        indexer.sync_icl_entries(td, "P", _entries(), endpoint=ep)
        retriever.retrieve_guidelines(td, "P", "warm", k=1, endpoint=ep)

        ep.calls = 0
        _, qv = retriever.prepare_instance(td, "P", "a violent riot", endpoint=ep)
        assert qv is not None
        assert ep.calls == 1                 # the single shared query embed
        retriever.retrieve_guidelines(td, "P", "a violent riot", k=1,
                                      endpoint=ep, query_vec=qv)
        retriever.retrieve_icl_examples(td, "P", "a violent riot", k=2,
                                        endpoint=ep, query_vec=qv)
        assert ep.calls == 1                 # reused, not re-embedded (Req 5)
