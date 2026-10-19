"""
Citable project snapshots.

A snapshot freezes a project's config, data and annotations under an id a
paper can cite, with a content hash a reader can check and the agreement report
as it stood. See docs/tools/snapshots.md.
"""

from potato.snapshots.build import create_snapshot, SnapshotUnchanged
from potato.snapshots.store import list_snapshots, load_snapshot, resolve, tag_snapshot, verify_snapshot
from potato.snapshots.diff import diff_snapshots

__all__ = [
    "create_snapshot", "SnapshotUnchanged", "list_snapshots", "load_snapshot",
    "resolve", "tag_snapshot", "verify_snapshot", "diff_snapshots",
]
