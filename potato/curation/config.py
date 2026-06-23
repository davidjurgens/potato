"""Config parsing for the semantic-curation subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class CurationConfig:
    enabled: bool = False
    model_name: str = "all-MiniLM-L6-v2"
    embed_on_ingest: bool = False   # opt-in; off by default (boot/memory weight)
    text_key: str = ""              # which field to embed (defaults to item text)

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "CurationConfig":
        block = (config or {}).get("curation", {}) or {}
        return cls(
            enabled=bool(block.get("enabled", False)),
            model_name=str(block.get("model_name", "all-MiniLM-L6-v2")),
            embed_on_ingest=bool(block.get("embed_on_ingest", False)),
            text_key=str(block.get("text_key", "")),
        )
