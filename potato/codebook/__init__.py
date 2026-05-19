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

# Import order matters: .service -> .store registers the 0001_codebook
# migration (CREATE TABLE codes) which .revision's ALTER depends on.
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
    merge_codes,
    move_under,
    recolor_code,
    register_change_listener,
    remove_code,
    rename_code,
    split_code,
)
from .codebook import Codebook
from .similar import derive_code_name, similar_code_names
from . import revision
from . import changelog
from .changelog import propose_change
from .revision import (
    all_stale_instances,
    codes_added_since,
    current_revision,
    instance_revision,
    record_annotation,
    stale_instances,
    touch_instances,
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
    "merge_codes",
    "split_code",
    "touch_instances",
    "apply_code",
    "remove_code",
    "codes_on",
    "register_change_listener",
    "clear_change_listeners",
    "revision",
    "current_revision",
    "record_annotation",
    "instance_revision",
    "stale_instances",
    "all_stale_instances",
    "codes_added_since",
    "derive_code_name",
    "similar_code_names",
    "changelog",
    "propose_change",
]
