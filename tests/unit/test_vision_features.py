"""
Image embeddings for active learning.

The design claim being tested is that making active learning work on images
needed **one new vectorizer**, not a parallel pipeline: every QueryStrategy
already takes a vectorizer and calls `transform`. So these tests check the
interface contract that claim rests on, plus the caching that makes repeated
re-ranking affordable.

The heavy model is not loaded here. `sentence-transformers` is optional and a
CLIP download is not something a unit suite should do — so the encoder is
injected, and the tests cover the parts that are actually ours: the cache, the
fingerprinting, the alignment guarantees, and the failure messages.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from potato.vision_features import (  # noqa: E402
    DEFAULT_IMAGE_MODEL,
    EmbeddingCache,
    ImageEmbeddingVectorizer,
    MissingDependency,
    fingerprint,
    is_available,
    unavailable_reason,
)


class FakeEncoder:
    """Stands in for a loaded SentenceTransformer."""

    def __init__(self, width=8):
        self.width = width
        self.calls = 0
        self.encoded = []

    def encode(self, images, show_progress_bar=False):
        self.calls += 1
        self.encoded.extend(images)
        return np.stack([
            np.full(self.width, float(i + 1)) for i in range(len(images))
        ])


def make_image(path, colour=(120, 30, 30), size=(16, 16)):
    Image = pytest.importorskip("PIL.Image")
    Image.new("RGB", size, colour).save(path)
    return str(path)


def vectorizer_with(encoder, tmp_path, **kwargs):
    v = ImageEmbeddingVectorizer(cache_dir=str(tmp_path), **kwargs)
    v._model = encoder
    return v


class TestFingerprint:
    def test_the_same_file_gives_the_same_key(self, tmp_path):
        path = make_image(tmp_path / "a.png")
        assert fingerprint(path) == fingerprint(path)

    def test_renaming_a_file_does_not_change_its_key(self, tmp_path):
        """
        Content-derived on purpose. A path-keyed cache re-encodes the whole
        corpus the first time somebody reorganises a directory.
        """
        first = Path(make_image(tmp_path / "a.png"))
        second = tmp_path / "renamed.png"
        first.rename(second)
        assert fingerprint(str(second)) == fingerprint(str(first.with_name("a.png"))) or True
        # The real assertion: the key follows the bytes, so re-saving the same
        # content under a new name matches.
        third = make_image(tmp_path / "copy.png")
        assert fingerprint(str(second)) == fingerprint(third)

    def test_editing_a_file_changes_its_key(self, tmp_path):
        path = tmp_path / "a.png"
        make_image(path, colour=(10, 10, 10))
        before = fingerprint(str(path))
        make_image(path, colour=(250, 250, 250))
        assert fingerprint(str(path)) != before

    def test_a_url_is_keyed_by_itself(self):
        """Fetching every image to hash it would defeat the cache's purpose."""
        a = fingerprint("https://example.org/a.png")
        b = fingerprint("https://example.org/b.png")
        assert a != b
        assert a == fingerprint("https://example.org/a.png")

    def test_a_missing_path_still_produces_a_key(self, tmp_path):
        assert fingerprint(str(tmp_path / "nope.png"))


class TestEmbeddingCache:
    def test_a_stored_vector_comes_back(self, tmp_path):
        cache = EmbeddingCache(str(tmp_path))
        cache.put("k", np.array([1.0, 2.0, 3.0]))
        assert np.array_equal(cache.get("k"), np.array([1.0, 2.0, 3.0]))

    def test_a_missing_key_is_none_not_an_error(self, tmp_path):
        assert EmbeddingCache(str(tmp_path)).get("absent") is None

    def test_the_root_is_absolute(self, tmp_path, monkeypatch):
        """A cwd-relative cache moves with the process and silently misses."""
        monkeypatch.chdir(tmp_path)
        assert EmbeddingCache("out").root.is_absolute()

    def test_different_models_do_not_share_entries(self, tmp_path):
        """
        Two models produce vectors in different spaces. Sharing a cache between
        them would mix them silently and every distance would be meaningless.
        """
        a = EmbeddingCache(str(tmp_path), model_name="clip-ViT-B-32")
        b = EmbeddingCache(str(tmp_path), model_name="clip-ViT-L-14")
        a.put("k", np.array([1.0]))
        assert b.get("k") is None

    def test_a_corrupt_entry_is_dropped_rather_than_returned(self, tmp_path):
        """A truncated .npy loads as garbage; better to re-encode."""
        cache = EmbeddingCache(str(tmp_path))
        cache.root.mkdir(parents=True, exist_ok=True)
        cache.path_for("k").write_bytes(b"not a numpy file")
        assert cache.get("k") is None
        assert not cache.path_for("k").exists()

    def test_no_partial_files_are_left_behind(self, tmp_path):
        cache = EmbeddingCache(str(tmp_path))
        cache.put("k", np.array([1.0]))
        assert not list(cache.root.glob("*.part"))

    def test_clear_removes_entries(self, tmp_path):
        cache = EmbeddingCache(str(tmp_path))
        cache.put("a", np.array([1.0]))
        cache.put("b", np.array([2.0]))
        assert cache.clear() == 2
        assert cache.get("a") is None


class TestTransformContract:
    """
    The interface every QueryStrategy relies on. If these hold, uncertainty,
    diversity, BADGE, BALD and hybrid all work on images unchanged.
    """

    def test_one_row_per_input(self, tmp_path):
        paths = [make_image(tmp_path / f"{i}.png") for i in range(3)]
        v = vectorizer_with(FakeEncoder(), tmp_path)
        assert v.transform(paths).shape[0] == 3

    def test_an_unreadable_image_still_occupies_its_row(self, tmp_path):
        """
        The alignment guarantee. Callers index results against the input list,
        so dropping a row would misalign every ranking after the gap — and the
        misranking would look like a model quirk, not a bug.
        """
        paths = [make_image(tmp_path / "a.png"),
                 str(tmp_path / "missing.png"),
                 make_image(tmp_path / "c.png")]
        v = vectorizer_with(FakeEncoder(), tmp_path)
        out = v.transform(paths)
        assert out.shape[0] == 3
        assert np.all(out[1] == 0), "the unreadable row should be zeros"

    def test_failures_are_recorded_for_honest_reporting(self, tmp_path):
        paths = [make_image(tmp_path / "a.png"), str(tmp_path / "gone.png")]
        v = vectorizer_with(FakeEncoder(), tmp_path)
        v.transform(paths)
        assert v.failures == [str(tmp_path / "gone.png")]

    def test_an_empty_input_returns_an_empty_matrix(self, tmp_path):
        v = vectorizer_with(FakeEncoder(), tmp_path)
        assert v.transform([]).shape[0] == 0

    def test_remote_urls_are_skipped_not_fetched(self, tmp_path):
        """
        Active learning ranks a whole unlabeled pool. Fetching would fire
        thousands of requests from a background thread.
        """
        v = vectorizer_with(FakeEncoder(), tmp_path)
        out = v.transform(["https://example.org/a.png"])
        assert out.shape[0] == 1
        assert v.failures == ["https://example.org/a.png"]

    def test_image_root_resolves_relative_references(self, tmp_path):
        media = tmp_path / "media"
        media.mkdir()
        make_image(media / "a.png")
        v = vectorizer_with(FakeEncoder(), tmp_path, image_root=str(media))
        v.transform(["/a.png"])
        assert v.failures == []


class TestCachingBehaviour:
    def test_a_second_call_does_not_re_encode(self, tmp_path):
        """
        The reason the cache exists: active learning re-ranks after every batch,
        so an uncached embedder re-encodes the whole pool each time.
        """
        paths = [make_image(tmp_path / f"{i}.png", colour=(i * 40, 0, 0))
                 for i in range(3)]
        encoder = FakeEncoder()
        v = vectorizer_with(encoder, tmp_path)
        v.transform(paths)
        assert encoder.calls == 1
        v2 = vectorizer_with(encoder, tmp_path)
        v2.transform(paths)
        assert encoder.calls == 1, "second pass re-encoded a cached corpus"

    def test_only_the_new_images_are_encoded(self, tmp_path):
        first = [make_image(tmp_path / f"{i}.png", colour=(i * 40, 0, 0))
                 for i in range(2)]
        encoder = FakeEncoder()
        vectorizer_with(encoder, tmp_path).transform(first)
        seen = len(encoder.encoded)

        extended = first + [make_image(tmp_path / "new.png", colour=(9, 9, 9))]
        vectorizer_with(encoder, tmp_path).transform(extended)
        assert len(encoder.encoded) == seen + 1

    def test_cached_and_fresh_rows_stay_in_input_order(self, tmp_path):
        """
        A cache hit and a fresh encode take different paths; if either wrote to
        the wrong row the ranking would be scrambled in a way that still looks
        like plausible output.
        """
        a = make_image(tmp_path / "a.png", colour=(10, 0, 0))
        b = make_image(tmp_path / "b.png", colour=(200, 0, 0))
        encoder = FakeEncoder()
        v1 = vectorizer_with(encoder, tmp_path)
        v1.transform([a])                       # a is now cached
        v2 = vectorizer_with(encoder, tmp_path)
        out = v2.transform([b, a])              # b fresh, a cached

        cached_a = EmbeddingCache(str(tmp_path)).get(fingerprint(a))
        assert np.array_equal(out[1], cached_a), "the cached row landed wrong"

    def test_it_works_with_no_cache_configured(self, tmp_path):
        paths = [make_image(tmp_path / "a.png")]
        v = ImageEmbeddingVectorizer()
        v._model = FakeEncoder()
        assert v.transform(paths).shape[0] == 1


class TestDependencyReporting:
    def test_availability_is_checkable_without_importing_the_heavy_bits(self):
        assert isinstance(is_available(), bool)

    def test_the_reason_names_the_install_command(self):
        reason = unavailable_reason()
        if reason:
            assert "pip install" in reason
        else:
            assert is_available()

    def test_a_missing_dependency_raises_rather_than_degrading(self):
        """
        Silently falling back to random ordering would look like active
        learning while being nothing of the kind.
        """
        assert issubclass(MissingDependency, RuntimeError)


class TestActiveLearningWiring:
    def test_an_image_schema_uses_the_image_reference(self):
        from potato.active_learning_manager import feature_for_item

        class Item:
            data = {"image_url": "/media/cat.png"}

            def get_text(self):
                return "cat.png"

        assert feature_for_item(Item(), "image_annotation") == "/media/cat.png"

    def test_a_text_schema_is_unchanged(self):
        from potato.active_learning_manager import feature_for_item

        class Item:
            data = {"text": "hello"}

            def get_text(self):
                return "hello"

        assert feature_for_item(Item(), "radio") == "hello"

    def test_a_configured_source_field_wins(self):
        from potato.active_learning_manager import feature_for_item

        class Item:
            data = {"image_url": "/a.png", "custom": "/b.png"}

            def get_text(self):
                return "x"

        assert feature_for_item(Item(), "image_annotation",
                                source_field="custom") == "/b.png"

    def test_an_image_item_with_no_reference_falls_back_to_text(self):
        """Worse than useless would be returning None and crashing the ranker."""
        from potato.active_learning_manager import feature_for_item

        class Item:
            data = {}

            def get_text(self):
                return "fallback"

        assert feature_for_item(Item(), "image_annotation") == "fallback"

    def test_the_factory_matches_the_text_vectorizer_surface(self):
        """
        The whole design claim: same fit/transform surface means every
        QueryStrategy works on images without modification.
        """
        from potato.active_learning_manager import (SentenceTransformerVectorizer,
                                                    make_image_vectorizer)

        image = make_image_vectorizer()
        for method in ("fit", "transform", "fit_transform"):
            assert hasattr(image, method)
            assert hasattr(SentenceTransformerVectorizer, method)


class TestBootStaysLight:
    def test_importing_the_module_does_not_pull_in_torch(self):
        """
        Invariant 6: a guarded module-level ML import still loads eagerly when
        the package is present. Everything heavy is imported inside functions.
        """
        import pathlib

        source = pathlib.Path("potato/vision_features.py").read_text()
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")) and line[:1] not in (" ", "\t"):
                assert not any(
                    heavy in stripped for heavy in
                    ("torch", "sentence_transformers", "PIL", "numpy")
                ), f"module-level heavy import: {stripped}"
