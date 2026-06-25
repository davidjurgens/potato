"""
Multi-model arena — fan one prompt out to N providers side by side, capture
human preferences, and track a win-rate leaderboard. Provider-agnostic via
``AIEndpointFactory`` (any of Potato's 11 LLM endpoints, not just one vendor).
"""

from potato.arena.config import ArenaConfig, ArenaModel
from potato.arena.arena import run_arena
from potato.arena.manager import (
    ArenaManager,
    init_arena_manager,
    get_arena_manager,
    clear_arena_manager,
)

__all__ = [
    "ArenaConfig",
    "ArenaModel",
    "run_arena",
    "ArenaManager",
    "init_arena_manager",
    "get_arena_manager",
    "clear_arena_manager",
]
