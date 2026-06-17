"""Phase E: the measured ICL toggle in SoloModeManager.get_icl_examples —
default static behavior, the per-instance retrieval path, and the two
distinct fallbacks (sparse corpus vs. no embedder)."""

import pytest

from potato.solo_mode.manager import SoloModeManager, clear_solo_mode_manager
from potato.solo_mode.config import parse_solo_mode_config
from potato.solo_mode.refinement.icl_library import ICLEntry
from potato.rag import indexer
from potato.rag.embedding_endpoint import EmbeddingError
from potato.rag.store import _RAG_MIGRATION, _RAG_META_MIGRATION
from potato.codebook.store import _CODEBOOK_MIGRATION
from potato.persistence import clear_db_cache, clear_migrations, register_migration
from .test_icl_retrieval import _CountingFake
from .fake_embedder import FakeEmbeddingEndpoint


SCHEMES = [{"name": "sentiment", "annotation_type": "radio",
            "labels": ["riot", "demonstration", "looting"]}]


@pytest.fixture(autouse=True)
def _isolated():
    clear_db_cache()
    clear_migrations()
    register_migration(_CODEBOOK_MIGRATION)
    register_migration(_RAG_MIGRATION)
    register_migration(_RAG_META_MIGRATION)
    clear_solo_mode_manager()
    yield
    clear_db_cache()
    clear_migrations()
    clear_solo_mode_manager()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


def _manager(td, *, strategy="static_gain", min_corpus=2, state_dir=None):
    sm = {"enabled": True, "labeling_models": [],
          "icl": {"selection_strategy": strategy, "min_corpus": min_corpus,
                  "min_per_label": 1}}
    if state_dir:
        sm["state_dir"] = state_dir
    cfg = parse_solo_mode_config({"solo_mode": sm, "annotation_schemes": SCHEMES})
    app = {"task_dir": td, "annotation_task_name": "P",
           "annotation_schemes": SCHEMES}
    return SoloModeManager(cfg, app)


def _fill_library(mgr, n_per_label=2):
    lib = mgr._get_icl_library()
    rows = [
        ("p1", "a violent riot smashed windows", "riot", 0.20),
        ("p2", "an aggressive mob set fires", "riot", 0.05),
        ("d1", "a peaceful march of thousands", "demonstration", 0.18),
        ("d2", "a calm candlelight vigil", "demonstration", 0.04),
    ]
    for iid, text, label, gain in rows:
        lib.add(ICLEntry(instance_id=iid, text=text, label=label,
                         val_accuracy_gain=gain))
    return lib


class TestDefaultStaticUnchanged:
    def test_default_strategy_ignores_instance_text(self, td):
        mgr = _manager(td, strategy="static_gain")
        _fill_library(mgr)
        fake = _CountingFake(dim=64)
        out = mgr.get_icl_examples(max_per_label=1, max_total=2,
                                   instance_text="a violent riot", endpoint=fake)
        # Static path: highest-gain per label, no embedding at all.
        assert fake.calls == 0
        assert {e["label"] for e in out} <= {"riot", "demonstration"}
        # 'p1' (gain .20) and 'd1' (gain .18) are the per-label gain leaders
        assert {e["text"] for e in out} == {
            "a violent riot smashed windows", "a peaceful march of thousands"}


class TestPerInstanceRetrieval:
    def test_ranks_by_instance_with_coverage(self, td):
        mgr = _manager(td, strategy="per_instance_retrieval", min_corpus=2)
        _fill_library(mgr)
        fake = FakeEmbeddingEndpoint(dim=64)
        out = mgr.get_icl_examples(
            max_total=2, instance_text="a violent riot broke windows",
            endpoint=fake)
        assert out[0]["label"] == "riot"                  # most similar
        assert {e["label"] for e in out} == {"riot", "demonstration"}  # floor


class TestFallbacks:
    def test_sparse_corpus_falls_back_to_static(self, td):
        # per-instance requested, but corpus below min_corpus -> static path,
        # and crucially NO embedding is attempted (distinct from no-embedder).
        mgr = _manager(td, strategy="per_instance_retrieval", min_corpus=10)
        _fill_library(mgr)
        fake = _CountingFake(dim=64)
        out = mgr.get_icl_examples(
            max_total=2, instance_text="a violent riot", endpoint=fake)
        assert fake.calls == 0                            # sparse: no embed
        assert {e["label"] for e in out} == {"riot", "demonstration"}

    def test_no_embedder_falls_back_to_static(self, td, monkeypatch):
        # Corpus is rich enough, but the embedder is unavailable -> static.
        mgr = _manager(td, strategy="per_instance_retrieval", min_corpus=2)
        _fill_library(mgr)

        def _boom(*a, **k):
            raise EmbeddingError("no backend")

        monkeypatch.setattr(indexer, "_endpoint_for", _boom)
        out = mgr.get_icl_examples(max_total=2, instance_text="a violent riot")
        assert out                                        # still returns static
        assert {e["label"] for e in out} <= {"riot", "demonstration", "looting"}
