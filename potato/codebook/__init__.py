"""
Codebook (universal annotation feature).

A mutable, optionally nested set of codes (labels) backed by the
universal `project.sqlite`. Opt-in per scheme via
`annotation_schemes[].codebook: true`; `codebook_mode`
(fixed|extensible|open) governs whether annotators may add codes on the
fly. Universal — usable in standard annotation, solo mode (human + LLM
co-edit), and QDA mode.

Layers:
- `store`    — SQLite persistence (codes + annotation_codes).
- `codebook` — read-model: tree + flat label list for the schema bridge.
- `service`  — the single audited mutation path (create/rename/recolor/
  move_under/delete + annotation links); fires change listeners (ICL
  prompt-cache invalidation).
"""

from .codebook import Codebook
from .service import (
    CodebookCycleError,
    CodebookError,
    CodeNotFound,
    DuplicateCodeError,
    apply_code,
    clear_change_listeners,
    codes_on,
    create_code,
    delete_code,
    move_under,
    recolor_code,
    register_change_listener,
    remove_code,
    rename_code,
)

__all__ = [
    "Codebook",
    "CodebookError",
    "CodeNotFound",
    "DuplicateCodeError",
    "CodebookCycleError",
    "create_code",
    "rename_code",
    "recolor_code",
    "move_under",
    "delete_code",
    "apply_code",
    "remove_code",
    "codes_on",
    "register_change_listener",
    "clear_change_listeners",
]
