"""
QDA Mode — Qualitative Data Analysis workflow for Potato.

QDA Mode is a distinct mode of Potato, parallel to `potato/solo_mode/`. When
enabled, it composes a set of universal features (memos, search, cases,
queries, label-explorer) with QDA-Mode-only additions (codebook, smart codes,
optional network editor) and tunes their defaults for qualitative-coding
workflows.

Activation:
    yaml
    qda_mode:
      enabled: true

The standard annotation surface is unaffected when `qda_mode.enabled` is false
or the block is absent.

Architecture:
    See `internal/qda-implementation-plan.md` and
    `internal/qda-redesign-design.md` for the full design rationale and the
    phased rollout plan. The role of `qda_mode/` is composition and defaults;
    universal features live in their own top-level packages
    (`potato/memos/`, `potato/search/`, `potato/cases/`, `potato/queries/`,
    `potato/analytics/`, `potato/media_sync/`).
"""

from .config import QDAModeConfig, parse_qda_mode_config
from .manager import (
    QDAModeManager,
    init_qda_mode_manager,
    get_qda_mode_manager,
    clear_qda_mode_manager,
)
from .routes import qda_mode_bp

__all__ = [
    "QDAModeConfig",
    "parse_qda_mode_config",
    "QDAModeManager",
    "init_qda_mode_manager",
    "get_qda_mode_manager",
    "clear_qda_mode_manager",
    "qda_mode_bp",
]
