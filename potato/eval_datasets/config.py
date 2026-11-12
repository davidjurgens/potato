"""Config parsing for the datasets / experiments subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class DatasetsConfig:
    enabled: bool = False
    storage: str = "file"  # "file" | "sqlite"

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "DatasetsConfig":
        block = (config or {}).get("datasets", {}) or {}
        storage = str(block.get("storage", "file")).lower()
        if storage not in ("file", "sqlite"):
            storage = "file"
        return cls(
            enabled=bool(block.get("enabled", False)),
            storage=storage,
        )
