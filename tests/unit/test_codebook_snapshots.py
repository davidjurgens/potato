"""Unit tests for potato.codebook.snapshots (versioning + diff)."""

import pytest

from potato.codebook import snapshots
from potato.codebook.blocks import _BLOCKS_MIGRATION
from potato.codebook.store import _CODEBOOK_MIGRATION
from potato.persistence import (
    clear_db_cache,
    clear_migrations,
    register_migration,
)


@pytest.fixture(autouse=True)
def _isolated_db():
    clear_db_cache()
    clear_migrations()
    register_migration(_CODEBOOK_MIGRATION)
    register_migration(_BLOCKS_MIGRATION)
    yield
    clear_db_cache()
    clear_migrations()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


def _rec(td, scope_id, blocks, **kw):
    base = dict(
        project="p", scope_kind="code", scope_id=scope_id, blocks=blocks,
        semantic=False, revision=1, sem_revision=0, actor="alice")
    base.update(kw)
    return snapshots.record_snapshot(td, **base)


class TestRecordAndList:
    def test_record_then_get(self, td):
        sid = _rec(td, "c1", [
            {"block_type": "definition", "custom_label": None,
             "body_md": "hello"}])
        snap = snapshots.get_snapshot(td, sid)
        assert snap is not None
        assert snap["scope_id"] == "c1"
        assert snap["blocks"][0]["body_md"] == "hello"
        assert "hello" in snap["snapshot_md"]

    def test_list_is_newest_first(self, td):
        _rec(td, "c1", [{"block_type": "definition", "custom_label": None,
                         "body_md": "v1"}], revision=1)
        _rec(td, "c1", [{"block_type": "definition", "custom_label": None,
                         "body_md": "v2"}], revision=2)
        hist = snapshots.list_snapshots(td, "p", "code", "c1")
        assert len(hist) == 2
        assert hist[0]["revision"] == 2  # newest first

    def test_scopes_isolated(self, td):
        _rec(td, "c1", [{"block_type": "definition", "custom_label": None,
                         "body_md": "a"}])
        _rec(td, "c2", [{"block_type": "definition", "custom_label": None,
                         "body_md": "b"}])
        assert len(snapshots.list_snapshots(td, "p", "code", "c1")) == 1
        assert len(snapshots.list_snapshots(td, "p", "code", "c2")) == 1

    def test_semantic_flag_persisted(self, td):
        sid = _rec(td, "c1", [{"block_type": "use_when", "custom_label": None,
                               "body_md": "x"}], semantic=True)
        assert snapshots.get_snapshot(td, sid)["semantic"] == 1

    def test_classified_flag_not_persisted(self, td):
        # parse-time UI flags must not leak into the snapshot blocks
        sid = _rec(td, "c1", [{"block_type": "definition", "custom_label": None,
                               "body_md": "x", "classified": False}])
        snap = snapshots.get_snapshot(td, sid)
        assert "classified" not in snap["blocks"][0]


class TestDiff:
    def test_diff_detects_change(self, td):
        hunks = snapshots.diff_markdown("### Definition\nold\n",
                                        "### Definition\nnew\n")
        joined = "\n".join(hunks)
        assert "-old" in joined and "+new" in joined

    def test_diff_identical_is_empty(self, td):
        assert snapshots.diff_markdown("same\n", "same\n") == []
