"""Phase B: project-scoped SQLite vector store + brute-force cosine + pin."""

import numpy as np
import pytest

from potato.rag import store
from potato.rag.store import RagModelMismatch, _RAG_MIGRATION
from potato.persistence import clear_db_cache, clear_migrations, register_migration
from .fake_embedder import FakeEmbeddingEndpoint


@pytest.fixture(autouse=True)
def _isolated():
    clear_db_cache()
    clear_migrations()
    register_migration(_RAG_MIGRATION)
    yield
    clear_db_cache()
    clear_migrations()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


def _embed(ep, text):
    return ep.embed_one(text)


class TestVectorIO:
    def test_pack_unpack_round_trip(self):
        v = np.array([1.0, -2.5, 3.0], dtype=np.float32)
        assert np.allclose(store.unpack_vector(store.pack_vector(v)), v)


class TestPin:
    def test_pin_set_on_first_then_enforced(self, td):
        store.ensure_pin(td, "p", "fake:A", 32)
        pin = store.get_pin(td, "p")
        assert pin["model"] == "fake:A" and pin["dim"] == 32
        # same model is fine
        store.ensure_pin(td, "p", "fake:A", 32)
        # different model -> refuse
        with pytest.raises(RagModelMismatch):
            store.ensure_pin(td, "p", "fake:B", 32)
        with pytest.raises(RagModelMismatch):
            store.ensure_pin(td, "p", "fake:A", 16)  # dim change

    def test_check_pin_noop_without_pin(self, td):
        store.check_pin(td, "p", "fake:A", 32)  # no raise

    def test_index_revision_round_trip(self, td):
        store.ensure_pin(td, "p", "fake:A", 32)
        assert store.get_index_revision(td, "p") == 0
        store.set_index_revision(td, "p", 7)
        assert store.get_index_revision(td, "p") == 7


class TestChunkCrudAndSearch:
    def _seed(self, td, ep):
        store.ensure_pin(td, "p", ep.key, ep.dim or 32)
        rows = [
            ("code", "c1", "definition", "a violent public disturbance riot"),
            ("code", "c2", "definition", "a peaceful demonstration march"),
            ("guideline", "g1", None, "quarterly revenue earnings finance"),
        ]
        for st, ref, fld, txt in rows:
            store.upsert_chunk(td, project="p", source_type=st, source_ref=ref,
                               field=fld, text=txt, vector=_embed(ep, txt),
                               model=ep.key, dim=ep.dim)

    def test_upsert_is_idempotent_by_stable_id(self, td):
        ep = FakeEmbeddingEndpoint()
        a = store.upsert_chunk(td, project="p", source_type="code",
                               source_ref="c1", field="definition", text="x",
                               vector=_embed(ep, "x"), model=ep.key, dim=ep.dim)
        b = store.upsert_chunk(td, project="p", source_type="code",
                               source_ref="c1", field="definition", text="y",
                               vector=_embed(ep, "y"), model=ep.key, dim=ep.dim)
        assert a == b
        assert len(store.get_chunks(td, "p", source_ref="c1")) == 1

    def test_search_ranks_by_cosine(self, td):
        ep = FakeEmbeddingEndpoint(dim=64)
        self._seed(td, ep)
        hits = store.search(td, "p", _embed(ep, "a violent riot broke out"),
                            source_type="code", k=2, model=ep.key)
        assert hits[0][0]["source_ref"] == "c1"   # the riot definition
        assert hits[0][1] >= hits[1][1]

    def test_search_scopes_by_source_type(self, td):
        ep = FakeEmbeddingEndpoint(dim=64)
        self._seed(td, ep)
        hits = store.search(td, "p", _embed(ep, "earnings report"),
                            source_type="guideline", k=5, model=ep.key)
        assert {h[0]["source_ref"] for h in hits} == {"g1"}

    def test_stale_rows_excluded_from_search(self, td):
        ep = FakeEmbeddingEndpoint(dim=64)
        self._seed(td, ep)
        store.mark_stale(td, "p", source_ref="c1")
        hits = store.search(td, "p", _embed(ep, "violent riot"),
                            source_type="code", k=5, model=ep.key)
        assert "c1" not in {h[0]["source_ref"] for h in hits}

    def test_set_vector_clears_stale(self, td):
        ep = FakeEmbeddingEndpoint(dim=64)
        cid = store.upsert_chunk(td, project="p", source_type="code",
                                 source_ref="c1", field="definition",
                                 text="riot", vector=None, model=None, dim=None)
        assert store.get_chunk(td, cid)["stale"] == 1
        store.set_chunk_vector(td, cid, vector=_embed(ep, "riot"),
                               model=ep.key, dim=ep.dim)
        assert store.get_chunk(td, cid)["stale"] == 0


class TestModelSwitchGuard:
    def test_query_under_different_model_returns_no_cross_model_scores(self, td):
        # Index under model A...
        epA = FakeEmbeddingEndpoint(model="A", provider="fake", dim=64, salt="A")
        store.ensure_pin(td, "p", epA.key, epA.dim or 64)
        store.upsert_chunk(td, project="p", source_type="code", source_ref="c1",
                           field="definition", text="violent riot",
                           vector=_embed(epA, "violent riot"),
                           model=epA.key, dim=epA.dim)
        # ...then a different model B shows up.
        epB = FakeEmbeddingEndpoint(model="B", provider="fake", dim=64, salt="B")
        with pytest.raises(RagModelMismatch):
            store.ensure_pin(td, "p", epB.key, epB.dim or 64)
        # Even a raw search filtered to model B yields nothing (no cross-model
        # cosine leaks through).
        hits = store.search(td, "p", _embed(epB, "violent riot"),
                            source_type="code", k=5, model=epB.key)
        assert hits == []
