"""
A machine source: something that produces predictions for one scheme.

Each source has a kind (llm, decision, detector, ...) and, per scheme, a
``SourceVersion`` that hashes everything that can change its answers: model,
parameters, prompt template, the scheme's labels and description, and a
``CODE_VERSION`` that is bumped whenever the source's own parsing or prompting
logic changes. Two runs with the same version are the same labeler, which is
what lets a certificate be checked later and a cached reply be reused.

Sources never call a model directly. They go through ``ctx.call``, which
redacts, caches, budgets and logs (see ``runtime/calls.py``).
"""

from __future__ import annotations

import os

from typing import Any, Dict, List, Optional, Sequence

from ..config.schema import SourceConfig
from ..items import ItemView
from ..model.records import Prediction, SourceVersion, content_hash
from ..schemes import SchemeSpec


class SourceError(RuntimeError):
    """A source could not be built or cannot label a scheme."""


class Source:
    kind: str = ""
    #: Bump when prompt construction or reply parsing changes, so predictions
    #: made by the old code get a different version.
    CODE_VERSION: str = "1"

    def __init__(self, cfg: SourceConfig, app_config: Optional[Dict[str, Any]] = None,
                 engine_cfg=None):
        self.cfg = cfg
        self.app_config = app_config or {}
        self.engine_cfg = engine_cfg

    @property
    def id(self) -> str:
        return self.cfg.id

    @property
    def concurrency(self) -> Optional[int]:
        return self.cfg.concurrency

    def supports(self, scheme: SchemeSpec) -> bool:
        raise NotImplementedError

    def unsupported_reason(self, scheme: SchemeSpec) -> str:
        return (f"source {self.id!r} ({self.kind}) cannot label "
                f"{scheme.annotation_type} scheme {scheme.name!r}")

    def prompt_template(self, scheme: SchemeSpec) -> str:
        """The instruction text this source sends, before item text is added."""
        return ""

    def version(self, scheme: SchemeSpec) -> SourceVersion:
        return SourceVersion(
            source_id=self.cfg.id, kind=self.kind, model=self.cfg.model,
            endpoint_type=self.cfg.endpoint_type or self.kind,
            revision=str(self.cfg.raw.get("revision") or ""),
            params=self.cfg.public_params(),
            prompt_template_hash=content_hash(
                [self.prompt_template(scheme), scheme.schema_hash()])[:32],
            code_version=f"{self.kind}/{self.CODE_VERSION}",
        )

    def predict_batch(self, items: Sequence[ItemView], scheme: SchemeSpec, ctx,
                      sv: SourceVersion) -> List[Prediction]:
        raise NotImplementedError


def endpoint_config(cfg: SourceConfig, temperature: Optional[float] = None,
                    max_tokens: Optional[int] = None) -> Dict[str, Any]:
    """The ``{"ai_support": ...}`` shape AIEndpointFactory takes."""
    ai_config: Dict[str, Any] = {
        "model": cfg.model,
        "temperature": cfg.temperature if temperature is None else temperature,
        "max_tokens": max_tokens or cfg.max_tokens,
    }
    for key in ("base_url", "api_key", "timeout"):
        value = getattr(cfg, key, None)
        if value is not None:
            ai_config[key] = value
    ai_config.update(cfg.options or {})
    return {"ai_support": {"enabled": True, "endpoint_type": cfg.endpoint_type,
                           "ai_config": ai_config}}


def local_media_path(app_config: Optional[Dict[str, Any]], ref: str) -> str:
    """An image reference as a file this process can open.

    ``/media/x.jpg`` is the URL the annotation page uses, served from
    ``<task_dir>/<media_directory>/``; read as a filesystem path it pointed at
    /media and every detector and vision call failed. Relative paths resolve
    against task_dir; URLs and absolute paths are returned as they are.
    """
    import os
    if not isinstance(ref, str) or ref.startswith(("http://", "https://", "data:")):
        return ref
    cfg = app_config or {}
    task_dir = cfg.get("task_dir", ".")
    if ref.startswith("/media/"):
        media_dir = cfg.get("media_directory", "media")
        base = media_dir if os.path.isabs(media_dir) else os.path.join(task_dir, media_dir)
        return os.path.join(base, ref[len("/media/"):])
    if os.path.isabs(ref):
        return ref
    return os.path.join(task_dir, ref)


#: File endings read as images when deciding a study's modality.
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".gif")


def image_reference(item, field: Optional[str] = None) -> str:
    """The image an item shows: ``item.data[field]``, or its text (an image
    study's text_key names the image)."""
    value = item.data.get(field) if field else item.text
    return str(value or "")


def looks_like_image(ref: str) -> bool:
    ref = (ref or "").strip().lower()
    return ref.startswith("data:image/") or ref.split("?")[0].endswith(IMAGE_SUFFIXES)


def local_image_file(app_config: Optional[Dict[str, Any]], ref: str) -> Optional[str]:
    """A file this process can open for an image reference, or None. Remote
    URLs are not downloaded: copy such images into the media directory."""
    if not ref or ref.startswith(("http://", "https://", "data:")):
        return None
    path = local_media_path(app_config, ref)
    return path if os.path.isfile(path) else None


def build_endpoint(cfg: SourceConfig, temperature: Optional[float] = None,
                   max_tokens: Optional[int] = None):
    from potato.ai.ai_endpoint import AIEndpointFactory
    try:
        endpoint = AIEndpointFactory.create_endpoint(
            endpoint_config(cfg, temperature, max_tokens))
    except Exception as e:
        raise SourceError(f"source {cfg.id!r}: could not build {cfg.endpoint_type} "
                          f"endpoint: {e}") from e
    if endpoint is None:
        raise SourceError(f"source {cfg.id!r}: no endpoint for {cfg.endpoint_type!r}")
    return endpoint
