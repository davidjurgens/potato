"""Config parsing for the automation-rules engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AutomationConfig:
    enabled: bool = False
    rules: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "AutomationConfig":
        block = (config or {}).get("automation", {}) or {}
        return cls(
            enabled=bool(block.get("enabled", False)),
            rules=list(block.get("rules", []) or []),
        )
