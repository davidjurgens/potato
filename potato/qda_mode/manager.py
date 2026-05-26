"""
QDA Mode Manager

Singleton orchestrator for QDA Mode. Currently minimal — owns the parsed
config and the task_dir reference; later phases attach codebook, smart-codes,
network, and other QDA-only state here.

The pattern mirrors potato/solo_mode/manager.py: a module-level singleton
guarded by a lock, with init/get/clear helpers used by flask_server.py.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

from .config import QDAModeConfig, parse_qda_mode_config

logger = logging.getLogger(__name__)


_QDA_MODE_MANAGER: Optional["QDAModeManager"] = None
_QDA_MODE_LOCK = threading.Lock()


class QDAModeManager:
    """Holds parsed QDA Mode state for the running server."""

    def __init__(self, qda_config: QDAModeConfig, full_config: Dict[str, Any]):
        self.config = qda_config
        self.task_dir: str = full_config.get("task_dir") or "."
        self._full_config = full_config

    def shutdown(self) -> None:
        """Release any held resources. No-op today; later phases close DBs etc."""
        logger.info("QDAModeManager shutdown")

    def __repr__(self) -> str:
        return (
            f"QDAModeManager(enabled={self.config.enabled}, "
            f"task_dir={self.task_dir!r}, "
            f"memos={self.config.memos.enabled}, "
            f"codebook={self.config.codebook is not None})"
        )


def init_qda_mode_manager(config_data: Dict[str, Any]) -> Optional[QDAModeManager]:
    """Initialize the singleton QDAModeManager from a full Potato config.

    Returns None (and leaves the singleton unset) when QDA Mode is disabled.
    Calling twice is a no-op — the second call returns the existing singleton.
    """
    global _QDA_MODE_MANAGER

    with _QDA_MODE_LOCK:
        if _QDA_MODE_MANAGER is not None:
            return _QDA_MODE_MANAGER

        qda_config = parse_qda_mode_config(config_data)
        if not qda_config.enabled:
            logger.info("QDA Mode disabled in config")
            return None

        errors = qda_config.validate()
        if errors:
            for err in errors:
                logger.error(f"QDA Mode config error: {err}")
            # Fail loud: an explicitly-enabled but misconfigured qda_mode
            # block must abort startup, not silently boot with QDA off
            # (the same silent-failure class as the legacy phase-type bug).
            from potato.server_utils.config_module import ConfigValidationError
            raise ConfigValidationError(
                "Invalid qda_mode configuration: " + "; ".join(errors)
            )

        _QDA_MODE_MANAGER = QDAModeManager(qda_config, config_data)
        logger.info(f"QDA Mode initialized: {_QDA_MODE_MANAGER!r}")
        return _QDA_MODE_MANAGER


def get_qda_mode_manager() -> Optional[QDAModeManager]:
    """Get the singleton QDAModeManager, or None if QDA Mode is disabled."""
    return _QDA_MODE_MANAGER


def clear_qda_mode_manager() -> None:
    """Clear the singleton. Primarily for tests."""
    global _QDA_MODE_MANAGER
    with _QDA_MODE_LOCK:
        if _QDA_MODE_MANAGER is not None:
            _QDA_MODE_MANAGER.shutdown()
        _QDA_MODE_MANAGER = None
