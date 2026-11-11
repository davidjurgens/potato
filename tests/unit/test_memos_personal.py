"""Personal and team-scoped memos.

A personal memo is a note to oneself: only its author reads it, adjudicators
included in "everyone else". A team memo shared within a live session reaches
the members of that team and nobody else on the project.
"""

import sqlite3

import pytest

from potato.memos import (
    MemoError,
    MemoNotFound,
    create_memo,
    delete_memo,
    list_issues,
    list_visible,
    reply_to,
    update_memo,
)
from potato.memos import service
from potato.memos.store import _MEMOS_MIGRATION, _SCOPE_MIGRATION, _THREADS_MIGRATION
from potato.persistence import clear_db_cache, clear_migrations, register_migration
from tests.helpers.test_utils import create_test_directory


@pytest.fixture(autouse=True)
def _isolated_db():
    clear_db_cache()
    clear_migrations()
    for migration in (_MEMOS_MIGRATION, _THREADS_MIGRATION, _SCOPE_MIGRATION):
        register_migration(migration)
    yield
    service.team_membership_resolver = None
    clear_db_cache()
    clear_migrations()


_counter = [0]


@pytest.fixture
def td():
    _counter[0] += 1
    return create_test_directory(f"memos_personal_{_counter[0]}")


def _mk(td, **kw):
    base = dict(project="p", instance_id="i1", body="note", created_by="alice")
    base.update(kw)
    return create_memo(td, **base)


def _visible_ids(td, requester, privileged=False):
    return {m["id"] for m in list_visible(td, project="p", instance_id="i1",
                                          requester=requester, is_privileged=privileged)}


class TestPersonal:
    def test_author_reads_it_and_nobody_else_does(self, td):
        memo = _mk(td, visibility="personal")
        assert memo["visibility"] == "personal"
        assert _visible_ids(td, "alice") == {memo["id"]}
        assert _visible_ids(td, "bob") == set()
        # The adjudicator tier reads private memos, but not personal ones.
        assert _visible_ids(td, "judge", privileged=True) == set()

    def test_private_memos_still_reach_adjudicators(self, td):
        memo = _mk(td, visibility="private")
        assert _visible_ids(td, "judge", privileged=True) == {memo["id"]}

    def test_survives_a_fresh_connection(self, td):
        memo = _mk(td, visibility="personal")
        clear_db_cache()
        assert _visible_ids(td, "alice") == {memo["id"]}
        assert _visible_ids(td, "judge", privileged=True) == set()

    def test_row_keeps_the_column_constraint(self, td):
        # Stored as a private row plus a scope row, so the CHECK on
        # memos.visibility holds for databases created before 'personal'.
        memo = _mk(td, visibility="personal")
        conn = sqlite3.connect(f"{td}/project.sqlite")
        try:
            (stored,) = conn.execute("SELECT visibility FROM memos WHERE id = ?",
                                     (memo["id"],)).fetchone()
        finally:
            conn.close()
        assert stored == "private"

    def test_adjudicator_cannot_delete_or_reply(self, td):
        memo = _mk(td, visibility="personal")
        with pytest.raises(MemoNotFound):
            delete_memo(td, memo["id"], requester="judge", is_privileged=True)
        with pytest.raises(MemoNotFound):
            reply_to(td, memo["id"], requester="judge", body="hi", is_privileged=True)

    def test_author_reply_stays_personal(self, td):
        memo = _mk(td, visibility="personal")
        reply = reply_to(td, memo["id"], requester="alice", body="later thought")
        assert reply["visibility"] == "personal"
        assert _visible_ids(td, "judge", privileged=True) == set()

    def test_switching_to_shared_and_back(self, td):
        memo = _mk(td, visibility="personal")
        shared = update_memo(td, memo["id"], requester="alice", visibility="shared")
        assert shared["visibility"] == "shared"
        assert _visible_ids(td, "bob") == {memo["id"]}
        back = update_memo(td, memo["id"], requester="alice", visibility="personal")
        assert back["visibility"] == "personal"
        assert _visible_ids(td, "bob") == set()

    def test_cannot_be_an_issue(self, td):
        with pytest.raises(MemoError):
            _mk(td, visibility="personal", issue=True)
        issue = _mk(td, visibility="private", issue=True)
        with pytest.raises(MemoError):
            update_memo(td, issue["id"], requester="alice", visibility="personal")

    def test_personal_memos_never_appear_in_issue_lists(self, td):
        _mk(td, visibility="personal")
        assert list_issues(td, project="p", requester="judge", is_privileged=True) == []

    def test_delete_removes_scope_row(self, td):
        memo = _mk(td, visibility="personal")
        delete_memo(td, memo["id"], requester="alice")
        conn = sqlite3.connect(f"{td}/project.sqlite")
        try:
            assert conn.execute("SELECT COUNT(*) FROM memo_scope").fetchone()[0] == 0
        finally:
            conn.close()


class TestTeamScope:
    def test_shared_team_memo_reaches_team_members_only(self, td):
        service.team_membership_resolver = lambda u: {"team-red"} if u in ("alice", "bob") else set()
        memo = _mk(td, visibility="shared", team_id="team-red")
        assert memo["team_id"] == "team-red"
        assert _visible_ids(td, "bob") == {memo["id"]}
        assert _visible_ids(td, "carol") == set()
        assert _visible_ids(td, "judge", privileged=True) == {memo["id"]}

    def test_reply_inherits_the_team(self, td):
        service.team_membership_resolver = lambda u: {"team-red"} if u in ("alice", "bob") else set()
        memo = _mk(td, visibility="shared", team_id="team-red")
        reply = reply_to(td, memo["id"], requester="bob", body="agreed")
        assert reply["team_id"] == "team-red"

    def test_no_resolver_keeps_team_memos_closed(self, td):
        memo = _mk(td, visibility="shared", team_id="team-red")
        assert _visible_ids(td, "bob") == set()
        assert _visible_ids(td, "alice") == {memo["id"]}

    def test_failing_resolver_keeps_team_memos_closed(self, td):
        def broken(_user):
            raise RuntimeError("boom")
        service.team_membership_resolver = broken
        _mk(td, visibility="shared", team_id="team-red")
        assert _visible_ids(td, "bob") == set()
