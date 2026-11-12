"""The runtime adapters Potato ships, by phase ``type``."""

from __future__ import annotations

from typing import Dict, Optional

from potato.runtimes.base import RuntimeAdapter

_ADAPTERS: Dict[str, RuntimeAdapter] = {}


def _load() -> Dict[str, RuntimeAdapter]:
    if not _ADAPTERS:
        from potato.runtimes.adapters import ALL
        for adapter in ALL:
            _ADAPTERS[adapter.kind] = adapter
    return _ADAPTERS


def runtime_kinds():
    return tuple(sorted(_load()))


def get_adapter(kind) -> Optional[RuntimeAdapter]:
    return _load().get(str(kind or "").lower())
