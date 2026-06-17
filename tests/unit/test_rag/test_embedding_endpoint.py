"""Phase A: pluggable embedding-provider abstraction."""

import numpy as np
import pytest

from potato.rag.embedding_endpoint import (
    BaseEmbeddingEndpoint,
    EmbeddingEndpointFactory,
    EmbeddingError,
)
from potato.solo_mode.config import EmbeddingConfig
from .fake_embedder import FakeEmbeddingEndpoint


class TestBaseEndpoint:
    def test_embed_normalises_to_float32_and_sets_dim(self):
        ep = FakeEmbeddingEndpoint(dim=16)
        vecs = ep.embed(["hello world", "hello"])
        assert len(vecs) == 2
        assert all(v.dtype == np.float32 for v in vecs)
        assert ep.dim == 16

    def test_empty_batch(self):
        assert FakeEmbeddingEndpoint().embed([]) == []

    def test_key_is_provider_colon_model(self):
        ep = FakeEmbeddingEndpoint(model="fake-32", provider="fake")
        assert ep.key == "fake:fake-32"

    def test_shared_words_are_more_similar(self):
        ep = FakeEmbeddingEndpoint(dim=64)
        a, b, c = ep.embed(["protest march downtown",
                            "a downtown protest",
                            "quarterly revenue earnings"])

        def cos(x, y):
            return float(x @ y / (np.linalg.norm(x) * np.linalg.norm(y)))

        assert cos(a, b) > cos(a, c)


class TestFactory:
    def test_unknown_provider_raises(self):
        with pytest.raises(EmbeddingError):
            EmbeddingEndpointFactory.create("does-not-exist")

    def test_register_and_create(self):
        EmbeddingEndpointFactory.register("fake", FakeEmbeddingEndpoint)
        ep = EmbeddingEndpointFactory.create("fake")
        assert isinstance(ep, BaseEmbeddingEndpoint)
        assert ep.provider == "fake"

    def test_create_does_not_fall_back_to_a_different_model(self, monkeypatch):
        # An explicit provider that fails to construct must raise, never
        # silently swap in another backend (cross-model cosine guard).
        class Broken(BaseEmbeddingEndpoint):
            provider = "broken"

            def __init__(self, **opts):
                raise EmbeddingError("backend down")

            def _embed(self, texts):  # pragma: no cover
                return []

        EmbeddingEndpointFactory.register("broken", Broken)
        with pytest.raises(EmbeddingError):
            EmbeddingEndpointFactory.create("broken")

    def test_auto_falls_through_to_first_healthy_backend(self, monkeypatch):
        class Down(BaseEmbeddingEndpoint):
            provider = "down"

            def __init__(self, **opts):
                raise EmbeddingError("unreachable")

            def _embed(self, texts):  # pragma: no cover
                return []

        EmbeddingEndpointFactory.register("down", Down)
        EmbeddingEndpointFactory.register("fake", FakeEmbeddingEndpoint)
        monkeypatch.setattr(
            EmbeddingEndpointFactory, "_AUTO_ORDER", ["down", "fake"])
        cfg = EmbeddingConfig(provider="auto")
        ep = EmbeddingEndpointFactory.create_default(config=cfg)
        assert ep.provider == "fake"

    def test_auto_raises_when_nothing_available(self, monkeypatch):
        monkeypatch.setattr(EmbeddingEndpointFactory, "_AUTO_ORDER", [])
        with pytest.raises(EmbeddingError):
            EmbeddingEndpointFactory.create_default(
                config=EmbeddingConfig(provider="auto"))

    def test_explicit_provider_honoured(self):
        EmbeddingEndpointFactory.register("fake", FakeEmbeddingEndpoint)
        ep = EmbeddingEndpointFactory.create_default(
            config=EmbeddingConfig(provider="fake"))
        assert ep.provider == "fake"
