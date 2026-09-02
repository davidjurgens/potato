"""
Database module for Potato annotation platform.

Database connectivity and management for user state persistence, over either
MySQL or file-based storage.
"""

from .connection import DatabaseManager
from .mysql_user_state import MysqlUserState

__all__ = ['DatabaseManager', 'MysqlUserState']