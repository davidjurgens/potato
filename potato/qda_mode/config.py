"""
QDA Mode Configuration

Parses and validates the `qda_mode:` block in a Potato YAML config. Features
populated in later phases (codebook, queries, cases) live under sub-blocks
here; Phase 0 ships memos + search.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MemosConfig:
    """QDA Mode memo defaults. Memo storage itself is universal
    (`potato/memos/`); this block only controls QDA-Mode-specific defaults
    such as whether the sidebar is visible by default."""
    enabled: bool = True
    show_sidebar_by_default: bool = True


@dataclass
class CodebookConfig:
    """Codebook is the QDA-Mode-only mutable runtime label set. Lands in
    Phase 1; this scaffolding is here so configs can already declare it."""
    enabled: bool = True
    mode: str = "open"  # 'open' | 'extensible' | 'fixed'


@dataclass
class QDAModeConfig:
    """Top-level QDA Mode config.

    Sub-blocks for codebook, cases, queries, etc. land in subsequent phases;
    they're declared here as Optional so configs can write forward-compatible
    YAML now without breaking when those features ship.
    """
    enabled: bool = False
    memos: MemosConfig = field(default_factory=MemosConfig)
    codebook: Optional[CodebookConfig] = None
    # Sub-blocks added in later phases (typed as Any to keep this stable):
    # cases, queries, smart_codes, network, media_sync

    # Free-form passthrough for forward compatibility — anything we haven't
    # explicitly modeled gets preserved here for later phases to consume.
    extras: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> List[str]:
        """Return a list of validation errors; empty means valid."""
        errors: List[str] = []
        if self.codebook and self.codebook.mode not in {"open", "extensible", "fixed"}:
            errors.append(
                f"qda_mode.codebook.mode must be one of "
                f"'open' | 'extensible' | 'fixed' (got {self.codebook.mode!r})"
            )
        return errors


_KNOWN_TOP_LEVEL_KEYS = {"enabled", "memos", "codebook"}


def parse_qda_mode_config(config_data: Dict[str, Any]) -> QDAModeConfig:
    """Parse the `qda_mode:` block out of a full Potato config dict.

    Returns an empty (disabled) QDAModeConfig if the block is missing.
    Unknown keys are preserved in `extras` so forward-compatible YAML
    (e.g. a `queries:` block written before Phase 3 ships) doesn't error.
    """
    raw = config_data.get("qda_mode") or {}
    if not isinstance(raw, dict):
        logger.warning(
            "qda_mode block must be a mapping; got %r — treating as disabled",
            type(raw).__name__,
        )
        return QDAModeConfig()

    memos_raw = raw.get("memos") or {}
    memos = MemosConfig(
        enabled=bool(memos_raw.get("enabled", True)),
        show_sidebar_by_default=bool(memos_raw.get("show_sidebar_by_default", True)),
    ) if isinstance(memos_raw, dict) else MemosConfig()

    codebook = None
    codebook_raw = raw.get("codebook")
    if isinstance(codebook_raw, dict):
        codebook = CodebookConfig(
            enabled=bool(codebook_raw.get("enabled", True)),
            mode=str(codebook_raw.get("mode", "open")),
        )

    extras = {k: v for k, v in raw.items() if k not in _KNOWN_TOP_LEVEL_KEYS}

    return QDAModeConfig(
        enabled=bool(raw.get("enabled", False)),
        memos=memos,
        codebook=codebook,
        extras=extras,
    )
