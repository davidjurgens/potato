"""
Registry of refinement strategies.

Strategies register themselves via the @register decorator. The manager
looks up the configured strategy name at refinement time.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Type

from .base import RefinementStrategy

logger = logging.getLogger(__name__)

_STRATEGIES: Dict[str, Type[RefinementStrategy]] = {}


def register_strategy(cls: Type[RefinementStrategy]) -> Type[RefinementStrategy]:
    """Decorator to register a refinement strategy class."""
    name = getattr(cls, "NAME", None)
    if not name or name == "abstract":
        raise ValueError(f"Strategy class {cls.__name__} must set a non-abstract NAME")
    if name in _STRATEGIES:
        logger.warning(f"Overwriting registered strategy: {name}")
    _STRATEGIES[name] = cls
    logger.debug(f"Registered refinement strategy: {name}")
    return cls


def get_strategy(name: str) -> Type[RefinementStrategy]:
    """Look up a strategy class by name.

    Raises KeyError with a helpful message if not found.
    """
    # Ensure builtin strategies are loaded
    _load_builtin_strategies()
    if name not in _STRATEGIES:
        available = ", ".join(sorted(_STRATEGIES.keys())) or "(none)"
        raise KeyError(
            f"Unknown refinement strategy: '{name}'. Available: {available}"
        )
    return _STRATEGIES[name]


def list_strategies() -> List[Dict[str, str]]:
    """List all registered strategies with their metadata."""
    _load_builtin_strategies()
    return [
        {
            "name": cls.NAME,
            "tier": cls.RECOMMENDED_OPTIMIZER_TIER,
            "best_for": ", ".join(cls.BEST_FOR),
            "description": cls.DESCRIPTION,
        }
        for cls in _STRATEGIES.values()
    ]


_BUILTINS_LOADED = False


def _load_builtin_strategies() -> None:
    """Import modules that register strategies."""
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    _BUILTINS_LOADED = True
    # Triggers @register_strategy side effects
    from . import strategies  # noqa: F401
