"""
Centralized Logging Configuration for Potato

This module provides a unified logging configuration for the entire Potato
annotation platform. It ensures consistent log formatting, appropriate log
levels, and optional file logging across all modules.

Usage:
    from potato.logging_config import setup_logging, get_logger

    # At application startup (in flask_server.py):
    setup_logging(verbose=config.get('verbose'), debug=config.get('debug'))

    # In any module:
    logger = get_logger(__name__)
    logger.info("Something happened")

Debug Log Modes:
    --debug-log=all     Enable debug logging for both UI and server
    --debug-log=ui      Enable debug logging for UI/frontend only
    --debug-log=server  Enable debug logging for server/backend only
    --debug-log=none    Disable all debug logging
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional


# Default log format
DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Verbose format includes more details
VERBOSE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"

# Module loggers that should be configured
POTATO_LOGGERS = [
    "potato",
    "potato.flask_server",
    "potato.routes",
    "potato.admin",
    "potato.authentication",
    "potato.user_state_management",
    "potato.item_state_management",
    "potato.active_learning_manager",
    "potato.directory_watcher",
    "potato.agreement",
    "potato.ai",
    "potato.ai.ai_endpoint",
    "potato.ai.icl_labeler",
    "potato.server_utils",
    "potato.server_utils.config_module",
    "potato.server_utils.front_end",
    "potato.database",
]

# Track if logging has been set up
_logging_initialized = False

# Track debug log settings for UI
_ui_debug_enabled = False
_server_debug_enabled = False


def setup_logging(
    verbose: bool = False,
    debug: bool = False,
    debug_log: Optional[str] = None,
    log_file: Optional[str] = None,
    log_dir: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
) -> None:
    """
    Set up logging for the entire Potato application.

    This function configures the root logger and all Potato module loggers
    with consistent formatting and appropriate log levels.

    Args:
        verbose: If True, set log level to DEBUG and use verbose format
        debug: If True, set log level to DEBUG (same as verbose)
        debug_log: Selective debug logging mode:
                   - 'all': Enable debug for both UI and server
                   - 'ui': Enable debug for UI/frontend only
                   - 'server': Enable debug for server/backend only
                   - 'none': Disable all debug logging
                   - None: Use verbose/debug flags as before
        log_file: Optional path to a log file. If provided, logs will be
                  written to this file in addition to console.
        log_dir: Optional directory for log files. If log_file is not provided
                 but log_dir is, a default log file will be created there.
        max_bytes: Maximum size of each log file before rotation (default 10MB)
        backup_count: Number of backup log files to keep (default 5)
    """
    global _logging_initialized, _ui_debug_enabled, _server_debug_enabled

    # Handle selective debug logging
    if debug_log:
        if debug_log == 'all':
            _ui_debug_enabled = True
            _server_debug_enabled = True
        elif debug_log == 'ui':
            _ui_debug_enabled = True
            _server_debug_enabled = False
        elif debug_log == 'server':
            _ui_debug_enabled = False
            _server_debug_enabled = True
        elif debug_log == 'none':
            _ui_debug_enabled = False
            _server_debug_enabled = False
    else:
        # Default behavior based on debug/verbose flags
        _ui_debug_enabled = debug or verbose
        _server_debug_enabled = debug or verbose

    # Determine server log level
    if _server_debug_enabled:
        log_level = logging.DEBUG
        log_format = VERBOSE_FORMAT
    elif verbose or debug:
        # If debug_log explicitly disabled server but debug flag is on,
        # still use INFO level for server
        log_level = logging.INFO
        log_format = DEFAULT_FORMAT
    else:
        log_level = logging.INFO
        log_format = DEFAULT_FORMAT

    # Create formatter
    formatter = logging.Formatter(log_format, datefmt=DEFAULT_DATE_FORMAT)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers to avoid duplicates on reinitialization
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Add file handler if requested
    if log_file or log_dir:
        if not log_file and log_dir:
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, "potato.log")

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Configure all Potato loggers
    for logger_name in POTATO_LOGGERS:
        module_logger = logging.getLogger(logger_name)
        module_logger.setLevel(log_level)
        # Don't add handlers - they inherit from root
        module_logger.propagate = True

    # Reduce noise from third-party libraries
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    _logging_initialized = True

    # Log that logging has been configured
    logger = logging.getLogger("potato")
    logger.debug(f"Logging initialized with level={logging.getLevelName(log_level)}")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for the specified module.

    This is a convenience function that ensures the logger is properly
    configured even if setup_logging() hasn't been called yet.

    Args:
        name: The name of the logger, typically __name__

    Returns:
        A configured Logger instance
    """
    if not _logging_initialized:
        # Set up basic logging if not initialized
        # This ensures logging works even before setup_logging() is called
        logging.basicConfig(
            format=DEFAULT_FORMAT,
            datefmt=DEFAULT_DATE_FORMAT,
            level=logging.INFO,
        )

    return logging.getLogger(name)


def set_log_level(level: int) -> None:
    """
    Change the log level for all Potato loggers at runtime.

    Args:
        level: The logging level (e.g., logging.DEBUG, logging.INFO)
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in root_logger.handlers:
        handler.setLevel(level)

    for logger_name in POTATO_LOGGERS:
        logging.getLogger(logger_name).setLevel(level)


def get_log_level() -> int:
    """
    Get the current log level.

    Returns:
        The current logging level
    """
    return logging.getLogger("potato").level


def is_ui_debug_enabled() -> bool:
    """
    Check if UI/frontend debug logging is enabled.

    Returns:
        True if UI debug logging is enabled
    """
    return _ui_debug_enabled


def is_server_debug_enabled() -> bool:
    """
    Check if server/backend debug logging is enabled.

    Returns:
        True if server debug logging is enabled
    """
    return _server_debug_enabled


def get_debug_log_settings() -> dict:
    """
    Get the current debug log settings for passing to frontend.

    Returns:
        Dict with 'ui_debug' and 'server_debug' boolean flags
    """
    return {
        'ui_debug': _ui_debug_enabled,
        'server_debug': _server_debug_enabled,
    }
