"""Unit tests for potato.memos store + service (visibility/permissions)."""

import pytest

from potato.memos import (
    MemoError,
    MemoNotFound,
    MemoPermissionError,
    create_memo,
    delete_memo,
    list_visible,
    update_memo,
)
from potato.memos.store import _MEMOS_MIGRATION
from potato.persistence import (
    clear_db_cache,
    clear_migrations,
    register_migration,
)


@pytest.fixture(autouse=True)
def _isolated_db():
    clear_db_cache()
    clear_migrations()
    register_migration(_MEMOS_MIGRATION)  # re-register after wipe
    yield
    clear_db_cache()
    clear_migrations()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


def _mk(td, **kw):
    base = dict(project="p", instance_id="i1", body="note", created_by="alice")
    base.update(kw)
    return create_memo(td, **base)


class TestCreateAndGet:
    def test_create_instance_level(self, td):
        m = _mk(td)
        assert m["anchor"] is None
        assert m["visibility"] == "private"
        assert m["created_by"] == "alice"

    def test_create_span_anchored(self, td):
        m = _mk(td, anchor={"start": 3, "end": 9, "field": "text"})
        assert m["anchor"] == {"start": 3, "end": 9, "field": "text"}

    def test_empty_body_rejected(self, td):
        with pytest.raises(MemoError):
            _mk(td, body="   ")

    def test_bad_visibility_rejected(self, td):
        with pytest.raises(MemoError):
            _mk(td, visibility="public")

    def test_bad_anchor_rejected(self, td):
        with pytest.raises(MemoError):
            _mk(td, anchor={"start": 1})  # missing 'end'


class TestVisibility:
    def test_private_hidden_from_peer(self, td):
        _mk(td, created_by="alice", visibility="private")
        seen = list_visible(td, project="p", instance_id="i1",
                            requester="bob", is_privileged=False)
        assert seen == []

    def test_private_visible_to_author(self, td):
        _mk(td, created_by="alice", visibility="private")
        seen = list_visible(td, project="p", instance_id="i1",
                            requester="alice", is_privileged=False)
        assert len(seen) == 1

    def test_private_visible_to_admin(self, td):
        _mk(td, created_by="alice", visibility="private")
        seen = list_visible(td, project="p", instance_id="i1",
                            requester="bob", is_privileged=True)
        assert len(seen) == 1

    def test_shared_visible_to_peer(self, td):
        _mk(td, created_by="alice", visibility="shared")
        seen = list_visible(td, project="p", instance_id="i1",
                            requester="bob", is_privileged=False)
        assert len(seen) == 1

    def test_list_scoped_to_instance(self, td):
        _mk(td, instance_id="i1", visibility="shared")
        _mk(td, instance_id="i2", visibility="shared")
        seen = list_visible(td, project="p", instance_id="i1",
                            requester="bob")
        assert len(seen) == 1 and seen[0]["instance_id"] == "i1"


class TestUpdate:
    def test_author_can_edit(self, td):
        m = _mk(td, created_by="alice")
        upd = update_memo(td, m["id"], requester="alice",
                          body="edited", visibility="shared")
        assert upd["body"] == "edited" and upd["visibility"] == "shared"
        assert upd["updated_at"] >= m["updated_at"]

    def test_peer_cannot_edit(self, td):
        m = _mk(td, created_by="alice")
        with pytest.raises(MemoPermissionError):
            update_memo(td, m["id"], requester="bob", body="hax")

    def test_admin_cannot_edit_others(self, td):
        """Admins moderate (delete) but do not rewrite authored content."""
        m = _mk(td, created_by="alice")
        with pytest.raises(MemoPermissionError):
            update_memo(td, m["id"], requester="mod",
                        is_privileged=True, body="changed")

    def test_update_missing_raises(self, td):
        with pytest.raises(MemoNotFound):
            update_memo(td, "nope", requester="alice", body="x")


class TestDelete:
    def test_author_can_delete(self, td):
        m = _mk(td, created_by="alice")
        delete_memo(td, m["id"], requester="alice")
        assert list_visible(td, project="p", instance_id="i1",
                            requester="alice") == []

    def test_admin_can_delete_others(self, td):
        m = _mk(td, created_by="alice")
        delete_memo(td, m["id"], requester="mod", is_privileged=True)
        assert list_visible(td, project="p", instance_id="i1",
                            requester="alice") == []

    def test_peer_cannot_delete(self, td):
        m = _mk(td, created_by="alice")
        with pytest.raises(MemoPermissionError):
            delete_memo(td, m["id"], requester="bob")
