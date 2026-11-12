"""
Admin-supplied embedders.

Two ways in, because labs have both: a Python callable already in the
environment, or a model served over HTTP (vLLM, TEI, a colleague's Flask app).
Either way Potato only needs "list of references in, list of vectors out", so a
site can plug in a domain model — a pathology encoder, a bird-song classifier,
a fine-tuned CLIP — without touching Potato.

    embeddings:
      backend: custom
      modality: image              # what the UI should call it
      source_field: slide_url
      entrypoint: "mylab.encoders:embed_batch"

    embeddings:
      backend: custom
      endpoint: "http://localhost:8900/embed"
      headers: {Authorization: "Bearer ..."}
      batch_size: 32
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, Callable, List, Optional, Sequence, Tuple

from potato.embedders.base import EmbeddingBackend, require

logger = logging.getLogger(__name__)


class CustomEmbeddingBackend(EmbeddingBackend):
    name = "custom"
    modality = "custom"
    default_model = "custom"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.modality = str(self.options.get("modality") or "custom")
        self.entrypoint = self.options.get("entrypoint")
        self.endpoint = self.options.get("endpoint")
        self.headers = self.options.get("headers") or {}
        self.timeout = float(self.options.get("timeout", 60))
        self.batch_size = int(self.options.get("batch_size", 32))
        self._callable: Optional[Callable[[List[str]], Any]] = None

    def available(self) -> Tuple[bool, Optional[str]]:
        if not self.entrypoint and not self.endpoint:
            return False, ("embeddings.backend is 'custom' but neither "
                           "'entrypoint' nor 'endpoint' was set")
        if self.entrypoint and ":" not in str(self.entrypoint):
            return False, (f"embeddings.entrypoint must be "
                           f"'module.path:callable', got '{self.entrypoint}'")
        return True, None

    # -- python callable -------------------------------------------------

    def _resolve_callable(self) -> Callable[[List[str]], Any]:
        if self._callable is not None:
            return self._callable
        module_path, _, attribute = str(self.entrypoint).partition(":")
        try:
            module = importlib.import_module(module_path)
        except ImportError as exc:
            raise RuntimeError(
                f"embeddings.entrypoint: cannot import '{module_path}': {exc}"
            ) from exc
        function = getattr(module, attribute, None)
        if not callable(function):
            raise RuntimeError(
                f"embeddings.entrypoint: '{attribute}' in '{module_path}' "
                f"is not callable")
        self._callable = function
        return function

    # -- http ------------------------------------------------------------

    def _post(self, batch: List[str]) -> List[List[float]]:
        requests = require("requests", "requests", "Custom HTTP embeddings")
        payload = {"inputs": batch}
        if self.model and self.model != self.default_model:
            payload["model"] = self.model
        response = requests.post(self.endpoint, json=payload,
                                 headers=self.headers, timeout=self.timeout)
        response.raise_for_status()
        body = response.json()
        vectors = (body.get("embeddings") if isinstance(body, dict) else body)
        if vectors is None and isinstance(body, dict):
            # OpenAI-shaped response
            data = body.get("data") or []
            vectors = [row.get("embedding") for row in data]
        if not isinstance(vectors, list) or len(vectors) != len(batch):
            raise RuntimeError(
                f"embeddings.endpoint returned {type(vectors).__name__} for a "
                f"batch of {len(batch)}; expected a list of that many vectors")
        return vectors

    # -- work ------------------------------------------------------------

    def embed(self, references: Sequence[str]):
        numpy = require("numpy", "numpy", "Custom embeddings")
        items = list(references)
        if not items:
            return numpy.zeros((0, 1))

        if self.entrypoint:
            vectors = self._resolve_callable()(items)
            array = numpy.asarray(vectors, dtype=float)
            if array.ndim != 2 or array.shape[0] != len(items):
                raise RuntimeError(
                    f"embeddings.entrypoint returned shape "
                    f"{getattr(array, 'shape', None)} for {len(items)} inputs; "
                    f"expected ({len(items)}, dim)")
            return array

        rows: List[List[float]] = []
        for start in range(0, len(items), self.batch_size):
            rows.extend(self._post(items[start:start + self.batch_size]))
        return numpy.asarray(rows, dtype=float)
