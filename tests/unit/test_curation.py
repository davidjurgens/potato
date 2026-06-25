"""Unit tests for semantic curation: index, embedder, slices (no ML stack)."""

import pytest

from potato.curation.embeddings import Embedder
from potato.curation.index import EmbeddingIndex, cosine
from potato.curation.slices import Slice, SliceStore, resolve_slice


# A tiny 2-D "embedding" space so tests are hermetic (no sentence-transformers).
VOCAB = {"cat": [1.0, 0.0], "feline": [0.92, 0.08], "dog": [0.0, 1.0],
         "puppy": [0.08, 0.92]}
EMBED = lambda s: VOCAB.get(s.strip(), [0.0, 0.0])


# ---- index ----

def test_cosine():
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([1, 0], [0, 0]) == 0.0  # zero vector guard


def test_index_search_ranking_and_threshold():
    idx = EmbeddingIndex()
    for name in VOCAB:
        idx.add(name, VOCAB[name])
    assert len(idx) == 4
    hits = idx.search(EMBED("cat"), top_k=10, threshold=0.5)
    ids = [i for i, _ in hits]
    assert ids[0] == "cat"            # exact match ranks first
    assert "feline" in ids            # close neighbour above threshold
    assert "dog" not in ids and "puppy" not in ids   # below threshold


def test_index_exclude_and_topk():
    idx = EmbeddingIndex()
    for name in VOCAB:
        idx.add(name, VOCAB[name])
    hits = idx.search(EMBED("cat"), top_k=1, threshold=0.0, exclude={"cat"})
    assert hits[0][0] == "feline"     # cat excluded -> nearest is feline


def test_index_remove():
    idx = EmbeddingIndex()
    idx.add("a", [1, 0])
    idx.remove("a")
    assert "a" not in idx and len(idx) == 0


# ---- embedder ----

def test_embedder_injected_fn():
    emb = Embedder(embed_fn=EMBED)
    assert emb.embed("cat") == [1.0, 0.0]
    assert emb.embed_batch(["cat", "dog"]) == [[1.0, 0.0], [0.0, 1.0]]


# ---- slices ----

def _index():
    idx = EmbeddingIndex()
    for name in VOCAB:
        idx.add(name, VOCAB[name])
    return idx


def test_resolve_slice_semantic_query():
    idx = _index()
    emb = Embedder(embed_fn=EMBED)
    slc = Slice(name="cats", query="cat", threshold=0.5)
    ids = resolve_slice(slc, idx, emb, metadata_for=lambda i: {})
    assert set(ids) == {"cat", "feline"}


def test_resolve_slice_anchor():
    idx = _index()
    emb = Embedder(embed_fn=EMBED)
    slc = Slice(name="like-cat", anchor_id="cat", threshold=0.5)
    ids = resolve_slice(slc, idx, emb, metadata_for=lambda i: {})
    assert "feline" in ids and "cat" not in ids   # anchor excluded


def test_resolve_slice_metadata_filter():
    idx = _index()
    emb = Embedder(embed_fn=EMBED)
    meta = {"cat": {"lang": "en"}, "feline": {"lang": "fr"}}
    slc = Slice(name="en-cats", query="cat", threshold=0.5,
                metadata_filter=[{"field": "lang", "equals": "en"}])
    ids = resolve_slice(slc, idx, emb, metadata_for=lambda i: meta.get(i, {}))
    assert ids == ["cat"]             # feline filtered out by lang


def test_resolve_slice_no_query_returns_all_then_filters():
    idx = _index()
    emb = Embedder(embed_fn=EMBED)
    slc = Slice(name="all", metadata_filter=[])
    ids = resolve_slice(slc, idx, emb, metadata_for=lambda i: {})
    assert set(ids) == set(VOCAB)


# ---- slice store persistence ----

def test_slice_store_persistence(tmp_path):
    store = SliceStore(str(tmp_path))
    store.save(Slice(name="s1", query="cat", threshold=0.4))
    assert store.get("s1").query == "cat"
    assert [s.name for s in store.list()] == ["s1"]
    # reload from disk
    store2 = SliceStore(str(tmp_path))
    assert store2.get("s1").threshold == 0.4
    assert store2.delete("s1") is True
    assert SliceStore(str(tmp_path)).get("s1") is None
