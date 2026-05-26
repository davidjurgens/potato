"""
Memos (universal annotation feature).

Free-text notes an annotator attaches to an instance or to a text
selection within an instance. Universal — available in standard
annotation, solo mode, and QDA mode; gated by `annotation_ui.memos`
(default off in standard mode; on for qda_mode/solo_mode).

Layers:
- `store`   — SQLite persistence over the universal `project.sqlite`.
- `service` — visibility + permission rules (private/shared; admins
  always read; author-only edit; author/admin delete).
"""

from .service import (
    MemoError,
    MemoNotFound,
    MemoPermissionError,
    create_memo,
    delete_memo,
    list_visible,
    update_memo,
)

__all__ = [
    "MemoError",
    "MemoNotFound",
    "MemoPermissionError",
    "create_memo",
    "list_visible",
    "update_memo",
    "delete_memo",
]
