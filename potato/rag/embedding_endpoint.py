"""
Pluggable embedding-provider abstraction for the RAG substrate.

Mirrors ``potato.ai.ai_endpoint`` (text generation) but for embeddings.
Backends are guarded imports so the substrate degrades gracefully when an
optional dependency or a local server is unavailable. No provider is
hardcoded into callers — everything goes through ``EmbeddingEndpointFactory``.

Returned vectors are numpy ``float32`` arrays. Cross-model vectors are NOT
comparable, so:

- ``create()`` builds ONE specific (provider, model) endpoint and raises
  ``EmbeddingError`` if it is unreachable — it never silently substitutes a
  different model.
- ``create_default()`` resolves ``provider="auto"`` (Ollama -> sentence-
  transformers) and is used ONLY at first index creation to *pick* the
  model. The rag store then pins ``endpoint.key`` for the project and uses
  ``create()`` thereafter (see potato/rag/store.py + Amendment 1).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """An embedding backend is unavailable or a request to it failed."""


class BaseEmbeddingEndpoint(ABC):
    """Abstract embedding backend. Subclasses implement ``_embed``."""

    provider: str = ""

    def __init__(self, model: str, **opts: Any):
        self.model = model
        self._opts = opts
        self._dim: Optional[int] = None

    @property
    def key(self) -> str:
        """Stable pin identity for a project: ``'provider:model'``."""
        return f"{self.provider}:{self.model}"

    @property
    def dim(self) -> Optional[int]:
        """Vector dimensionality, known after the first ``embed`` call."""
        return self._dim

    @abstractmethod
    def _embed(self, texts: List[str]) -> List[Any]:
        """Return one raw vector (list/ndarray) per input text."""

    def embed(self, texts: List[str]) -> List[np.ndarray]:
        """Embed a batch, normalising to float32 ndarrays. [] -> []."""
        if not texts:
            return []
        raw = self._embed(list(texts))
        arr = [np.asarray(v, dtype=np.float32).ravel() for v in raw]
        if arr:
            self._dim = int(arr[0].shape[0])
        return arr

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    def health_check(self) -> bool:
        """True if a tiny embed succeeds (used by auto-provider selection)."""
        try:
            return len(self.embed(["ok"])) == 1
        except Exception:
            return False


class OllamaEmbeddingEndpoint(BaseEmbeddingEndpoint):
    """Local Ollama embeddings (default open-weight backend)."""

    provider = "ollama"

    def __init__(self, model: str = "nomic-embed-text",
                 base_url: str = "http://localhost:11434", **opts: Any):
        super().__init__(model, base_url=base_url, **opts)
        try:
            import ollama
        except Exception as e:  # pragma: no cover - import guard
            raise EmbeddingError(f"ollama package not available: {e}")
        self._client = ollama.Client(host=base_url)

    def _embed(self, texts: List[str]) -> List[Any]:
        try:
            resp = self._client.embed(model=self.model, input=texts)
        except Exception as e:
            raise EmbeddingError(f"ollama embed failed: {e}")
        # Newer clients return {"embeddings": [[...], ...]}.
        embeddings = resp["embeddings"] if isinstance(resp, dict) \
            else getattr(resp, "embeddings", None)
        if not embeddings:
            raise EmbeddingError("ollama returned no embeddings")
        return list(embeddings)


class SentenceTransformerEmbeddingEndpoint(BaseEmbeddingEndpoint):
    """In-process sentence-transformers (zero-server local fallback)."""

    provider = "sentence_transformers"

    def __init__(self, model: str = "all-MiniLM-L6-v2", **opts: Any):
        super().__init__(model, **opts)
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as e:  # pragma: no cover - import guard
            raise EmbeddingError(f"sentence-transformers not available: {e}")
        try:
            self._model_obj = SentenceTransformer(model)
        except Exception as e:  # pragma: no cover - model load
            raise EmbeddingError(f"could not load model {model!r}: {e}")

    def _embed(self, texts: List[str]) -> List[Any]:
        return list(self._model_obj.encode(texts, show_progress_bar=False))


class OpenAIEmbeddingEndpoint(BaseEmbeddingEndpoint):
    """OpenAI-compatible embeddings (opt-in; also serves vLLM/LM Studio
    via a custom base_url)."""

    provider = "openai"

    def __init__(self, model: str = "text-embedding-3-small",
                 api_key: str = "", base_url: Optional[str] = None, **opts: Any):
        super().__init__(model, **opts)
        try:
            from openai import OpenAI
        except Exception as e:  # pragma: no cover - import guard
            raise EmbeddingError(f"openai package not available: {e}")
        kwargs: Dict[str, Any] = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)

    def _embed(self, texts: List[str]) -> List[Any]:
        try:
            resp = self._client.embeddings.create(model=self.model, input=texts)
        except Exception as e:
            raise EmbeddingError(f"openai embed failed: {e}")
        return [d.embedding for d in resp.data]


class EmbeddingEndpointFactory:
    """Builds embedding endpoints by provider name (registry + auto)."""

    _registry: Dict[str, type] = {
        "ollama": OllamaEmbeddingEndpoint,
        "sentence_transformers": SentenceTransformerEmbeddingEndpoint,
        "openai": OpenAIEmbeddingEndpoint,
    }
    # provider="auto" tries these in order (local / open-weight first).
    _AUTO_ORDER: List[str] = ["ollama", "sentence_transformers"]

    @classmethod
    def register(cls, name: str, klass: type) -> None:
        cls._registry[name] = klass

    @classmethod
    def _opts_for(cls, provider: str, model: Optional[str],
                  config: Any, opts: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(opts)
        if model:
            out["model"] = model
        if config is not None:
            if provider == "ollama":
                out.setdefault("model", getattr(config, "ollama_model", None)
                               or "nomic-embed-text")
                if getattr(config, "base_url", None):
                    out.setdefault("base_url", config.base_url)
            elif provider == "sentence_transformers":
                out.setdefault("model", getattr(config, "model_name", None)
                               or "all-MiniLM-L6-v2")
            elif provider == "openai":
                out.setdefault("model", getattr(config, "openai_model", None)
                               or "text-embedding-3-small")
                if getattr(config, "api_key", None):
                    out.setdefault("api_key", config.api_key)
        return out

    @classmethod
    def create(cls, provider: str, model: Optional[str] = None, *,
               config: Any = None, **opts: Any) -> BaseEmbeddingEndpoint:
        """Build a SPECIFIC endpoint. Raises EmbeddingError if unreachable —
        never falls back to a different model."""
        if provider not in cls._registry:
            raise EmbeddingError(f"unknown embedding provider: {provider!r}")
        kwargs = cls._opts_for(provider, model, config, opts)
        return cls._registry[provider](**kwargs)

    @classmethod
    def create_default(cls, config: Any = None,
                       **opts: Any) -> BaseEmbeddingEndpoint:
        """Resolve the configured provider, expanding "auto" by trying the
        local backends in order. Used ONLY at first index creation to pick
        the model; the resolved endpoint.key is then pinned by the caller."""
        provider = (getattr(config, "provider", None) or "auto") \
            if config is not None else "auto"
        if provider != "auto":
            return cls.create(provider, config=config, **opts)
        last: Optional[Exception] = None
        for cand in cls._AUTO_ORDER:
            try:
                ep = cls.create(cand, config=config, **opts)
            except EmbeddingError as e:
                last = e
                continue
            if ep.health_check():
                logger.info("RAG embedding provider (auto) -> %s", ep.key)
                return ep
            last = EmbeddingError(f"{cand} unreachable (health check failed)")
        raise EmbeddingError(
            f"no embedding backend available for provider=auto: {last}")
