"""Phase D: guideline corpus — canonical store, content-hash invalidation
(separate from the codebook changelog), retrieval, and the default-off
labeler injection flag."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from potato.rag import store, indexer, retriever
from potato.rag.guidelines import (
    set_guidelines, append_guidelines, get_guidelines, chunk_guidelines,
)
from potato.rag.store import _RAG_MIGRATION, _RAG_GUIDELINE_MIGRATION, SOURCE_GUIDELINE
from potato.codebook import create_code, update_code_fields, clear_change_listeners
from potato.codebook.store import _CODEBOOK_MIGRATION
from potato.persistence import clear_db_cache, clear_migrations, register_migration
from .fake_embedder import FakeEmbeddingEndpoint


@pytest.fixture(autouse=True)
def _isolated():
    clear_db_cache()
    clear_migrations()
    register_migration(_CODEBOOK_MIGRATION)
    register_migration(_RAG_MIGRATION)
    register_migration(_RAG_GUIDELINE_MIGRATION)
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


GUIDE = (
    "When the text describes property destruction, prefer riot.\n\n"
    "- A sports celebration that turns rowdy is not a riot\n"
    "- Peaceful marches are demonstrations even if large"
)


class TestChunking:
    def test_paragraphs_and_bullets(self):
        chunks = chunk_guidelines(GUIDE)
        assert "When the text describes property destruction, prefer riot." in chunks
        assert "A sports celebration that turns rowdy is not a riot" in chunks
        assert "Peaceful marches are demonstrations even if large" in chunks
        assert len(chunks) == 3


class TestCanonicalStoreAndRetrieval:
    def test_set_then_retrieve_ranks_relevant_chunk(self, td, ep):
        set_guidelines(td, "P", GUIDE)
        hits = retriever.retrieve_guidelines(
            td, "P", "peaceful marches are demonstrations downtown",
            k=1, endpoint=ep)
        assert hits
        assert "demonstration" in hits[0]["text"].lower()
        assert get_guidelines(td, "P") == GUIDE.strip()

    def test_unchanged_set_is_noop_no_churn(self, td, ep):
        assert set_guidelines(td, "P", GUIDE) is True
        retriever.retrieve_guidelines(td, "P", "seed", k=1, endpoint=ep)
        before = {c["id"]: c["updated_at"]
                  for c in store.get_chunks(td, "P", source_type=SOURCE_GUIDELINE)}
        assert set_guidelines(td, "P", GUIDE) is False     # identical -> no-op
        after = {c["id"]: c["updated_at"]
                 for c in store.get_chunks(td, "P", source_type=SOURCE_GUIDELINE)}
        assert before == after                              # no re-chunk churn

    def test_changed_text_reembeds_and_serves_new(self, td, ep):
        set_guidelines(td, "P", GUIDE)
        retriever.retrieve_guidelines(td, "P", "seed", k=1, endpoint=ep)
        set_guidelines(td, "P", GUIDE + "\n\n- Looting is theft during unrest")
        # the new bullet is stale until catch-up
        assert any(c["stale"] and "Looting" in c["text"]
                   for c in store.get_chunks(td, "P", source_type=SOURCE_GUIDELINE))
        hits = retriever.retrieve_guidelines(
            td, "P", "people stealing during unrest", k=1, endpoint=ep)
        assert "looting" in hits[0]["text"].lower()
        assert all(not c["stale"]
                   for c in store.get_chunks(td, "P", source_type=SOURCE_GUIDELINE))

    def test_append_is_idempotent(self, td):
        set_guidelines(td, "P", "rule one")
        assert append_guidelines(td, "P", "rule two") is True
        assert append_guidelines(td, "P", "rule two") is False  # already present
        assert "rule one" in get_guidelines(td, "P")
        assert "rule two" in get_guidelines(td, "P")


class TestInvalidationIndependence:
    """Guideline staleness is a SEPARATE trigger from the codebook
    changelog (Amendment 2)."""

    def test_code_edit_does_not_stale_guidelines(self, td, ep):
        code = create_code(td, project="P", name="riot", created_by="u",
                           details={"definition": "violent crowd"})
        indexer.install_rag_codebook_sync()
        set_guidelines(td, "P", GUIDE)
        # Embed both corpora.
        retriever.retrieve_codebook_units(td, "P", "seed", k=1, endpoint=ep)
        retriever.retrieve_guidelines(td, "P", "seed", k=1, endpoint=ep)

        # A codebook edit fires the codebook listener only.
        update_code_fields(td, code["id"], project="P",
                           details={"definition": "an aggressive violent riot"})
        g_stale = [c for c in store.get_chunks(td, "P", source_type=SOURCE_GUIDELINE)
                   if c["stale"]]
        assert g_stale == []                       # guidelines untouched

    def test_guideline_rewrite_does_not_stale_codes(self, td, ep):
        create_code(td, project="P", name="riot", created_by="u",
                    details={"definition": "violent crowd"})
        indexer.install_rag_codebook_sync()
        set_guidelines(td, "P", GUIDE)
        retriever.retrieve_codebook_units(td, "P", "seed", k=1, endpoint=ep)
        retriever.retrieve_guidelines(td, "P", "seed", k=1, endpoint=ep)

        set_guidelines(td, "P", "completely different guidance about something")
        code_stale = [c for c in store.get_chunks(td, "P", source_type="code")
                      if c["stale"]]
        assert code_stale == []                    # codebook untouched


class TestLabelerInjectionFlag:
    def _thread(self, td, rag_cfg):
        from potato.solo_mode.llm_labeler import LLMLabelingThread
        cfg = {"task_dir": td, "annotation_task_name": "P"}
        if rag_cfg is not None:
            cfg["rag"] = rag_cfg
        return LLMLabelingThread(
            config=cfg, solo_config=SimpleNamespace(embedding=None),
            prompt_getter=lambda: "p", result_callback=lambda r: None)

    def test_default_off_returns_empty(self, td):
        thread = self._thread(td, rag_cfg=None)
        with patch("potato.rag.retriever.retrieve_guidelines") as m:
            assert thread._guideline_section("some text") == ""
            m.assert_not_called()           # default: not even attempted

    def test_flag_on_injects_relevant_guidelines_block(self, td):
        thread = self._thread(td, rag_cfg={"inject_guidelines": True,
                                           "guideline_top_k": 2})
        with patch("potato.rag.retriever.retrieve_guidelines",
                   return_value=[{"text": "prefer riot for destruction",
                                  "score": 0.9},
                                 {"text": "marches are demonstrations",
                                  "score": 0.7}]):
            out = thread._guideline_section("a violent riot")
        assert out.startswith("## Relevant Guidelines")
        assert "- prefer riot for destruction" in out
        assert "- marches are demonstrations" in out
        assert out.endswith("\n\n")

    def test_flag_on_but_no_hits_is_empty(self, td):
        thread = self._thread(td, rag_cfg={"inject_guidelines": True})
        with patch("potato.rag.retriever.retrieve_guidelines", return_value=[]):
            assert thread._guideline_section("x") == ""
