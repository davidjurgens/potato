"""
Database module for Potato annotation platform.

This module provides database connectivity and management for user state persistence.
It supports both MySQL and file-based storage backends.
"""

from .connection import DatabaseManager
from .mysql_user_state import MysqlUserState

__all__ = ['DatabaseManager', 'MysqlUserState']