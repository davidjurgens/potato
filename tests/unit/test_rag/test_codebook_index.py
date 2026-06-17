"""Phase C: codebook corpus indexing, scoped changelog invalidation, and the
retrieve_codebook_units side feature."""

import pytest

from potato.rag import indexer, store, retriever
from potato.rag.store import _RAG_MIGRATION, SOURCE_CODE
from potato.codebook import (
    create_code, update_code_fields, delete_code, clear_change_listeners,
)
from potato.codebook.store import _CODEBOOK_MIGRATION
from potato.persistence import clear_db_cache, clear_migrations, register_migration
from .fake_embedder import FakeEmbeddingEndpoint


@pytest.fixture(autouse=True)
def _isolated():
    clear_db_cache()
    clear_migrations()
    register_migration(_CODEBOOK_MIGRATION)
    register_migration(_RAG_MIGRATION)
    clear_change_listeners()
    yield
    clear_db_cache()
    clear_migrations()
    clear_change_listeners()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


@pytest.fixture
def ep():
    return FakeEmbeddingEndpoint(dim=64)


def _seed_codebook(td):
    riot = create_code(td, project="P", name="riot", created_by="u", details={
        "definition": "a violent public disturbance by a crowd",
        "exclusion_rules": ["the text only mentions a sports celebration"]})
    demo = create_code(td, project="P", name="demonstration", created_by="u",
                       details={"definition": "a peaceful organized march"})
    return riot, demo


class TestChunking:
    def test_code_units_cover_fields(self):
        units = dict(indexer.code_units({
            "name": "riot",
            "definition": "violent crowd",
            "clarification": "includes property destruction",
            "negative_clarification": "not a peaceful protest",
            "exclusion_rules": ["only the word riot appears", "a sports riot"],
            "positive_examples": [{"text": "smashed windows", "why": "violence"}],
            "negative_examples": [],
        }))
        assert units["summary"] == "riot: violent crowd"
        assert "include" in units["clarification"]
        assert "exclusion_rule:0" in units and "exclusion_rule:1" in units
        assert "positive_example:0" in units
        # name is folded into every chunk for grounding
        assert all("riot" in t for t in units.values())


class TestFullIndexAndRetrieval:
    def test_first_retrieval_builds_pins_and_ranks(self, td, ep):
        _seed_codebook(td)
        # No pin yet -> retrieval triggers the full build + pin + bookmark.
        out = retriever.retrieve_codebook_units(
            td, "P", "a violent mob smashed shop windows", k=2, endpoint=ep)
        assert out[0]["name"] == "riot"
        assert out[0]["score"] >= out[-1]["score"]
        # grouped output: matching fields highlighted
        assert any(f["field"] == "summary" for f in out[0]["fields"])
        # pinned + bookmark set
        assert store.get_pin(td, "P")["model"] == ep.key
        from potato.codebook import current_revision
        assert store.get_index_revision(td, "P") == current_revision(td, "P")

    def test_retrieval_does_not_filter_label_set(self, td, ep):
        # Both codes remain retrievable/representable; retrieval only ranks.
        _seed_codebook(td)
        out = retriever.retrieve_codebook_units(
            td, "P", "a peaceful organized march downtown", k=5, endpoint=ep)
        names = {e["name"] for e in out}
        assert names == {"riot", "demonstration"}  # nothing dropped
        assert out[0]["name"] == "demonstration"   # but ranked by relevance


class TestScopedInvalidation:
    def test_edit_reembeds_only_that_code(self, td, ep):
        riot, demo = _seed_codebook(td)
        indexer.install_rag_codebook_sync()
        # Build the index once.
        retriever.retrieve_codebook_units(td, "P", "seed", k=1, endpoint=ep)
        demo_chunks_before = store.get_chunks(td, "P", source_ref=demo["id"])
        demo_updated_before = {c["updated_at"] for c in demo_chunks_before}

        # Edit ONLY riot's definition -> listener marks only riot stale.
        update_code_fields(td, riot["id"], project="P",
                           details={"definition": "an aggressive violent riot"})
        riot_stale = [c for c in store.get_chunks(td, "P", source_ref=riot["id"])
                      if c["stale"]]
        demo_stale = [c for c in store.get_chunks(td, "P", source_ref=demo["id"])
                      if c["stale"]]
        assert riot_stale and not demo_stale   # scoped, not flush-everything

        # Retrieval catches up: new text reflected, no stale fragment served.
        out = retriever.retrieve_codebook_units(
            td, "P", "an aggressive violent riot", k=1, endpoint=ep)
        assert out[0]["name"] == "riot"
        riot_summary = next(
            c for c in store.get_chunks(td, "P", source_ref=riot["id"])
            if c["field"] == "summary")
        assert "aggressive violent riot" in riot_summary["text"]
        assert riot_summary["stale"] == 0
        # demo chunks untouched (same rows, not re-embedded)
        demo_chunks_after = store.get_chunks(td, "P", source_ref=demo["id"])
        assert {c["updated_at"] for c in demo_chunks_after} == demo_updated_before

    def test_delete_removes_chunks(self, td, ep):
        riot, demo = _seed_codebook(td)
        indexer.install_rag_codebook_sync()
        retriever.retrieve_codebook_units(td, "P", "seed", k=1, endpoint=ep)
        delete_code(td, demo["id"], project="P")
        retriever.retrieve_codebook_units(td, "P", "seed", k=5, endpoint=ep)
        assert store.get_chunks(td, "P", source_ref=demo["id"]) == []

    def test_new_code_is_indexed(self, td, ep):
        _seed_codebook(td)
        indexer.install_rag_codebook_sync()
        retriever.retrieve_codebook_units(td, "P", "seed", k=1, endpoint=ep)
        riot2 = create_code(td, project="P", name="looting", created_by="u",
                            details={"definition": "stealing during unrest"})
        out = retriever.retrieve_codebook_units(
            td, "P", "people stealing during unrest", k=1, endpoint=ep)
        assert out[0]["name"] == "looting"


class TestModelSwitchReindex:
    def test_query_with_different_model_raises_then_reindex_fixes(self, td):
        epA = FakeEmbeddingEndpoint(model="A", provider="fake", dim=64, salt="A")
        _seed_codebook(td)
        retriever.retrieve_codebook_units(td, "P", "violent riot", k=1, endpoint=epA)

        epB = FakeEmbeddingEndpoint(model="B", provider="fake", dim=64, salt="B")
        from potato.rag.store import RagModelMismatch
        with pytest.raises(RagModelMismatch):
            retriever.retrieve_codebook_units(td, "P", "violent riot", k=1,
                                              endpoint=epB)
        # The sanctioned model switch: explicit whole-project reindex.
        indexer.reindex_project(td, "P", endpoint=epB)
        out = retriever.retrieve_codebook_units(td, "P", "violent riot", k=1,
                                                endpoint=epB)
        assert out[0]["name"] == "riot"
        assert store.get_pin(td, "P")["model"] == epB.key
