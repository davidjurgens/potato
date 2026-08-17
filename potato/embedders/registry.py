"""
Backend registration, modality detection, and resolution.

Registration is lazy by module path (the ``AIEndpointFactory`` pattern): naming
a backend must not import torch, sentence-transformers or transformers, because
this module is reachable from the boot path and a guarded module-level import
still loads eagerly when the package happens to be installed.

Detection answers "what kind of corpus is this?" from the items themselves.
The rule is deliberately dull — field-name hints and file extensions — because
the failure it replaces was subtle: everything embedded fine, and what got
embedded was the instance id.
"""

from __future__ import annotations

import importlib
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from potato.embedders.base import EmbeddingBackend, EmbeddingSpec

logger = logging.getLogger(__name__)

#: name -> (module, class, install hint)
_LAZY: Dict[str, Tuple[str, str, str]] = {}
_CLASSES: Dict[str, type] = {}


def register_lazy(name: str, module: str, cls: str, hint: str = "") -> None:
    _LAZY[name] = (module, cls, hint)


def register(cls: type) -> type:
    """Register an already-imported backend class (used by tests)."""
    _CLASSES[cls.name] = cls
    return cls


def unregister(name: str) -> None:
    _CLASSES.pop(name, None)
    _LAZY.pop(name, None)


def backend_names() -> List[str]:
    return sorted(set(_LAZY) | set(_CLASSES))


def get_backend_class(name: str) -> type:
    if name in _CLASSES:
        return _CLASSES[name]
    if name not in _LAZY:
        raise KeyError(
            f"Unknown embedding backend '{name}'. "
            f"Known backends: {', '.join(backend_names()) or '(none)'}")
    module_path, class_name, _hint = _LAZY[name]
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    _CLASSES[name] = cls
    return cls


def _register_builtins() -> None:
    register_lazy("text", "potato.embedders.text", "TextEmbeddingBackend",
                  "sentence-transformers")
    register_lazy("image", "potato.embedders.image", "ImageEmbeddingBackend",
                  "sentence-transformers, pillow")
    register_lazy("audio", "potato.embedders.audio", "AudioEmbeddingBackend",
                  "transformers, soundfile")
    register_lazy("video", "potato.embedders.video", "VideoEmbeddingBackend",
                  "sentence-transformers, pillow (+ ffmpeg on PATH)")
    register_lazy("custom", "potato.embedders.custom", "CustomEmbeddingBackend",
                  "")


_register_builtins()


# ---------------------------------------------------------------- config --

@dataclass
class EmbeddingsConfig:
    """The ``embeddings:`` block. Every field is optional."""

    backend: str = "auto"
    model: Optional[str] = None
    source_field: Optional[str] = None
    cache_dir: Optional[str] = None
    media_root: Optional[str] = None
    options: Dict[str, Any] = None          # backend-specific extras

    def __post_init__(self):
        if self.options is None:
            self.options = {}


def parse_config(config: Dict[str, Any]) -> EmbeddingsConfig:
    block = config.get("embeddings") or {}
    if not isinstance(block, dict):
        logger.warning("embeddings: expected a mapping, got %s; ignoring",
                       type(block).__name__)
        block = {}
    options = {k: v for k, v in block.items()
               if k not in {"backend", "model", "source_field",
                            "cache_dir", "media_root"}}
    return EmbeddingsConfig(
        backend=str(block.get("backend") or "auto"),
        model=block.get("model"),
        source_field=block.get("source_field"),
        cache_dir=block.get("cache_dir"),
        media_root=block.get("media_root"),
        options=options,
    )


# ------------------------------------------------------------- detection --

#: Backend name -> (field-name hints, extensions). Kept here rather than read
#: off the classes so detection never has to import a backend to ask.
_SIGNATURES: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    "image": (
        ("image_url", "image", "image_path", "img", "img_url", "picture",
         "photo", "frame", "thumbnail"),
        (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff",
         ".avif", ".heic", ".heif"),
    ),
    "audio": (
        ("audio_url", "audio", "audio_path", "sound", "clip_url", "speech"),
        (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".wma"),
    ),
    "video": (
        ("video_url", "video", "video_path", "movie", "clip"),
        (".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"),
    ),
}


def _extension_of(value: str) -> str:
    """Lowercase extension of a path or URL, query string stripped."""
    without_query = str(value).split("?", 1)[0].split("#", 1)[0]
    return os.path.splitext(without_query)[1].lower()


def _text_key(config: Dict[str, Any]) -> str:
    return (config.get("item_properties") or {}).get("text_key", "text")


def detect(samples: Sequence[Dict[str, Any]],
           config: Dict[str, Any]) -> Tuple[str, Optional[str], str, List[str]]:
    """Pick a backend and a field from sample item dicts.

    Returns ``(backend, source_field, reason, alternatives)``.

    Media wins over text when both are present. In a media task the text field
    is usually a prompt shared by every item, and a projection of one repeated
    sentence is a single blob that tells you nothing — whereas the media is what
    the annotator is actually looking at. ``embeddings.source_field`` overrides.
    """
    alternatives: List[str] = []
    if not samples:
        return "text", _text_key(config), "no items to inspect", alternatives

    # Score each candidate field by how many sampled items carry a value that
    # looks like a given modality.
    hits: Dict[Tuple[str, str], int] = {}
    for item in samples:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if not isinstance(value, str) or not value.strip():
                continue
            extension = _extension_of(value)
            for backend, (names, extensions) in _SIGNATURES.items():
                by_extension = extension in extensions
                by_name = key.lower() in names
                if by_extension or (by_name and _looks_like_reference(value)):
                    hits[(backend, key)] = hits.get((backend, key), 0) + 1

    if hits:
        # Most-populated field wins; ties break by the modality order above,
        # which puts image first — the common case by a wide margin.
        order = list(_SIGNATURES)
        (backend, field), count = max(
            hits.items(), key=lambda kv: (kv[1], -order.index(kv[0][0])))
        alternatives = sorted({f"{b}:{f}" for (b, f) in hits
                               if (b, f) != (backend, field)})
        reason = (f"detected {backend} from '{field}' "
                  f"({count}/{len(samples)} sampled items)")
        return backend, field, reason, alternatives

    text_key = _text_key(config)
    present = sum(1 for item in samples
                  if isinstance(item, dict)
                  and isinstance(item.get(text_key), str)
                  and item[text_key].strip())
    if present:
        return "text", text_key, f"text from '{text_key}'", alternatives

    return "text", None, (
        f"no media field found and no usable '{text_key}' — nothing to embed "
        f"(set embeddings.source_field to name the field)"), alternatives


def _looks_like_reference(value: str) -> bool:
    """A media field's value should be a path or URL, not a sentence."""
    if len(value) > 512:
        return False
    if value.startswith(("http://", "https://", "data:", "/", "./", "../")):
        return True
    return "/" in value or _extension_of(value) != ""


# ------------------------------------------------------------ resolution --

@dataclass
class ResolvedEmbedder:
    """A backend plus the field it reads, ready to embed items."""

    backend: Optional[EmbeddingBackend]
    spec: EmbeddingSpec

    @property
    def available(self) -> bool:
        return self.backend is not None and self.spec.available

    def reference_for(self, item_data: Dict[str, Any]) -> Optional[str]:
        field = self.spec.source_field
        if not field:
            return None
        value = item_data.get(field)
        return value if isinstance(value, str) and value.strip() else None

    def embed_items(self, items: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """{instance_id: vector} for the items that have a usable reference."""
        if not self.available:
            return {}
        ids, references = [], []
        for instance_id, data in items.items():
            reference = self.reference_for(data)
            if reference is None:
                continue
            ids.append(instance_id)
            references.append(reference)
        if not ids:
            return {}
        vectors = self.backend.embed(references)
        return {instance_id: vectors[i] for i, instance_id in enumerate(ids)}


def resolve(config: Dict[str, Any],
            samples: Optional[Sequence[Dict[str, Any]]] = None,
            cache_dir: Optional[str] = None) -> ResolvedEmbedder:
    """Choose the project's embedder from config, falling back to detection."""
    settings = parse_config(config)
    samples = list(samples or [])

    if settings.backend and settings.backend != "auto":
        name = settings.backend
        field = settings.source_field
        because = f"configured (embeddings.backend: {name})"
        alternatives: List[str] = []
        if not field:
            detected, detected_field, reason, alternatives = detect(samples, config)
            # Honour the configured backend, but borrow detection's field so an
            # admin who names a backend need not also name the field.
            field = (detected_field if detected == name
                     else _first_field_for(name, samples))
            if field:
                because += f", field '{field}'"
    else:
        name, field, because, alternatives = detect(samples, config)

    cache_dir = settings.cache_dir or cache_dir
    try:
        cls = get_backend_class(name)
    except KeyError as exc:
        spec = EmbeddingSpec(backend=name, modality="unknown", model="",
                             source_field=field, unavailable_reason=str(exc),
                             chosen_because=because, alternatives=alternatives)
        return ResolvedEmbedder(None, spec)

    backend = cls(model=settings.model, cache_dir=cache_dir,
                  media_root=settings.media_root, options=settings.options)
    spec = backend.spec(source_field=field, chosen_because=because)
    spec.alternatives = alternatives
    if field is None and spec.available:
        # Detection's reason names the field it looked for and the text_key it
        # fell back to; a generic "no field to embed" would throw that away.
        spec.unavailable_reason = (
            because if "nothing to embed" in because
            else "no field to embed — set embeddings.source_field")
    return ResolvedEmbedder(backend if spec.available else None, spec)


def _first_field_for(name: str, samples: Sequence[Dict[str, Any]]) -> Optional[str]:
    """Best field for an explicitly configured backend."""
    names, extensions = _SIGNATURES.get(name, ((), ()))
    for item in samples:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if not isinstance(value, str):
                continue
            if key.lower() in names or _extension_of(value) in extensions:
                return key
    return None
