"""Trainer registration and capability matching.

Registration is lazy by module path, the same idiom as
``potato.embedders.registry`` and ``AIEndpointFactory``: naming a trainer must
not import torch or transformers. The admin UI lists every trainer, its
capabilities and its install hint without importing any of them, which is only
possible because that metadata lives in the registration call rather than on
the class.

Capability matching goes through ``iaa.dispatcher.classify_schema``. A trainer
says "I handle NOMINAL text"; the registry asks the dispatcher what kind a
scheme is and pairs them up. Reusing that classification means a new annotation
type becomes trainable the moment it is classified, without touching any
trainer.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "TrainerInfo",
    "register_lazy",
    "register",
    "unregister",
    "trainer_names",
    "get_trainer_class",
    "get_trainer",
    "trainer_info",
    "list_trainers",
    "trainers_for_schema",
    "kind_of_schema",
]


@dataclass(frozen=True)
class TrainerInfo:
    """Everything the UI needs about a trainer, without importing it."""

    name: str
    module: str
    cls: str
    description: str = ""
    kinds: Tuple[str, ...] = ()
    modalities: Tuple[str, ...] = ("text",)
    install_hint: str = ""
    licence: str = "unspecified"
    commercial_use: Optional[bool] = None
    licence_ack: bool = False
    licence_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "kinds": list(self.kinds), "modalities": list(self.modalities),
                "install_hint": self.install_hint, "licence": self.licence,
                "commercial_use": self.commercial_use,
                "licence_ack": self.licence_ack,
                "licence_url": self.licence_url}


_LAZY: Dict[str, TrainerInfo] = {}
_CLASSES: Dict[str, type] = {}


def register_lazy(name: str, module: str, cls: str, hint: str = "",
                  kinds: Tuple[str, ...] = (),
                  modalities: Tuple[str, ...] = ("text",),
                  description: str = "", licence: str = "unspecified",
                  commercial_use: Optional[bool] = None,
                  licence_ack: bool = False, licence_url: str = "") -> None:
    """Register a trainer by module path, without importing it."""
    _LAZY[name] = TrainerInfo(
        name=name, module=module, cls=cls, description=description,
        kinds=tuple(kinds), modalities=tuple(modalities), install_hint=hint,
        licence=licence, commercial_use=commercial_use,
        licence_ack=licence_ack, licence_url=licence_url)


def register(cls: type) -> type:
    """Register an already-imported trainer class. Used by tests."""
    _CLASSES[cls.name] = cls
    _LAZY[cls.name] = TrainerInfo(
        name=cls.name, module=cls.__module__, cls=cls.__name__,
        description=getattr(cls, "description", ""),
        kinds=tuple(getattr(cls, "kinds", ())),
        modalities=tuple(getattr(cls, "modalities", ("text",))),
        install_hint=getattr(cls, "install_hint", ""),
        licence=getattr(cls, "licence", "unspecified"),
        commercial_use=getattr(cls, "commercial_use", None),
        licence_ack=getattr(cls, "licence_ack", False),
        licence_url=getattr(cls, "licence_url", ""))
    return cls


def unregister(name: str) -> None:
    _CLASSES.pop(name, None)
    _LAZY.pop(name, None)


def trainer_names() -> List[str]:
    return sorted(set(_LAZY) | set(_CLASSES))


def trainer_info(name: str) -> Optional[TrainerInfo]:
    return _LAZY.get(name)


def list_trainers(include_unavailable: bool = True) -> List[Dict[str, Any]]:
    """Every registered trainer as a dict, with an availability flag.

    Availability is probed through ``Trainer.available()``, which is
    contractually forbidden from importing the training library -- so this
    stays cheap enough to call on every page render.
    """
    out = []
    for name in trainer_names():
        info = _LAZY.get(name)
        if info is None:
            continue
        entry = info.to_dict()
        try:
            usable, reason = get_trainer_class(name).available()
        except Exception as exc:  # noqa: BLE001 - a broken trainer is data
            usable, reason = False, str(exc)
        entry["available"] = bool(usable)
        entry["unavailable_reason"] = "" if usable else reason
        if usable or include_unavailable:
            out.append(entry)
    return out


def get_trainer_class(name: str) -> type:
    """Import and return a trainer class. This is where torch finally loads."""
    if name in _CLASSES:
        return _CLASSES[name]
    info = _LAZY.get(name)
    if info is None:
        raise KeyError(
            "Unknown trainer '%s'. Known trainers: %s"
            % (name, ", ".join(trainer_names()) or "(none)"))
    module = importlib.import_module(info.module)
    cls = getattr(module, info.cls)
    _CLASSES[name] = cls
    return cls


def get_trainer(name: str):
    """An instance of the named trainer."""
    return get_trainer_class(name)()


def kind_of_schema(scheme: Dict[str, Any]) -> str:
    """The ``SchemaKind`` value for one scheme, as a string.

    Falls back to ``"unsupported"`` rather than raising, so an unknown
    annotation type produces "no trainer handles this" instead of a 500.
    """
    try:
        from potato.server_utils.iaa.dispatcher import classify_schema
        return str(classify_schema(scheme).value)
    except Exception:
        logger.debug("Could not classify scheme %r", scheme.get("name"),
                     exc_info=True)
        return "unsupported"


def trainers_for_schema(scheme: Dict[str, Any],
                        modality: Optional[str] = None,
                        available_only: bool = False) -> List[TrainerInfo]:
    """Trainers that can handle this scheme.

    Matches on kind, and on modality when one is given. Imports nothing unless
    *available_only* is set, which is what lets the run form be rendered on a
    machine with no training extras installed.
    """
    kind = kind_of_schema(scheme)
    if kind in ("unsupported", "text"):
        # Free text has no automatic target and unsupported has no shape.
        return []

    matches = []
    for name in trainer_names():
        info = _LAZY.get(name)
        if info is None or kind not in info.kinds:
            continue
        if modality and modality not in info.modalities:
            continue
        if available_only:
            try:
                usable, _ = get_trainer_class(name).available()
            except Exception:
                usable = False
            if not usable:
                continue
        matches.append(info)
    return matches


def _register_builtins() -> None:
    # sklearn, scipy and numpy are core dependencies, so this one is always
    # usable and needs no extra.
    register_lazy(
        "sklearn-text", "potato.training.trainers.sklearn_text",
        "SklearnTextTrainer", hint="",
        kinds=("nominal", "ordinal", "multilabel"),
        modalities=("text", "image"),
        description="Linear and tree classifiers over bag-of-words, sentence "
                    "embeddings or CLIP image embeddings. No extra install.",
        licence="BSD-3-Clause", commercial_use=True)


_register_builtins()
