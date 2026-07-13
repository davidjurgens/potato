"""Multiplayer Annotation Rooms — synchronized group annotation sessions.

Norming rooms (blind vote → reveal → discussion, with a live Krippendorff
alpha meter and conformity logging), adjudication huddles, and expert
shadowing. Event-sourced with per-room JSONL logs; clients sync via
cursor-based polling. See docs/advanced/multiplayer_rooms.md.
"""

from potato.rooms.config import RoomsConfig, parse_rooms_config
from potato.rooms.manager import (
    RoomsManager,
    clear_rooms_manager,
    get_rooms_manager,
    init_rooms_manager,
)
from potato.rooms.models import Room, RoomError

__all__ = [
    "Room",
    "RoomError",
    "RoomsConfig",
    "RoomsManager",
    "clear_rooms_manager",
    "get_rooms_manager",
    "init_rooms_manager",
    "parse_rooms_config",
]
