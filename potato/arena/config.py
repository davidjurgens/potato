"""Config parsing for the multi-model arena."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ArenaModel:
    label: str
    endpoint_type: str
    model: str = ""
    base_url: str = ""
    temperature: float = 0.7
    ai_config: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ArenaModel":
        return cls(
            label=d.get("label") or d.get("model") or d.get("endpoint_type", "model"),
            endpoint_type=d.get("endpoint_type", ""),
            model=d.get("model", ""),
            base_url=d.get("base_url", ""),
            temperature=float(d.get("temperature", 0.7)),
            ai_config=d.get("ai_config", {}) or {},
        )


@dataclass
class ArenaConfig:
    enabled: bool = False
    models: List[ArenaModel] = field(default_factory=list)

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "ArenaConfig":
        block = (config or {}).get("arena", {}) or {}
        return cls(
            enabled=bool(block.get("enabled", False)),
            models=[ArenaModel.from_dict(m) for m in (block.get("models", []) or [])],
        )
