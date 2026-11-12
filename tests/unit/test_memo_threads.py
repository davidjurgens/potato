"""
Memo threads and issues: replies, open/resolved status, assignees, region
anchors, and the migration that adds them to an existing project database.
"""

import os
import sqlite3

import pytest

from potato.memos import (
    MemoError, MemoNotFound, MemoPermissionError, create_memo, delete_memo,
    list_issues, list_visible, reply_to, set_assignee, set_status, update_memo,
)
from potato.memos import store
from potato.persistence import clear_db_cache, clear_migrations, register_migration
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory


@pytest.fixture(autouse=True)
def _isolated_db():
    clear_db_cache()
    clear_migrations()
    register_migration(store._MEMOS_MIGRATION)
    register_migration(store._THREADS_MIGRATION)
    yield
    clear_db_cache()
    clear_migrations()


@pytest.fixture
def td():
    folder = create_test_directory("memo_threads")
    yield folder
    clear_db_cache()
    cleanup_test_directory(folder)


def note(td, by="alice", **kw):
    base = dict(project="p", instance_id="i1", body="needs a look", created_by=by)
    base.update(kw)
    return create_memo(td, **base)


def seen_by(td, user, privileged=False):
    return [m["body"] for m in list_visible(td, project="p", instance_id="i1",
                                            requester=user, is_privileged=privileged)]


class TestMigration:
    def test_an_existing_database_gains_threads_and_keeps_its_notes(self, td):
        """A project.sqlite written before threads existed: 0001 applied, one
        memo in it, no memo_threads table."""
        clear_db_cache()
        path = os.path.join(td, "project.sqlite")
        db = sqlite3.connect(path)
        db.executescript(store._MEMOS_MIGRATION.sql)
        db.execute("CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, "
                   "applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        db.execute("INSERT INTO schema_migrations (name) VALUES ('0001_memos')")
        db.execute("INSERT INTO memos VALUES ('old1', 'p', 'i1', NULL, 'from last year', "
                   "'alice', 1.0, 1.0, 'shared')")
        db.commit()
        db.close()

        [old] = list_visible(td, project="p", instance_id="i1", requester="bob")
        assert (old["body"], old["parent_id"], old["status"]) == ("from last year", None, None)
        reply = reply_to(td, "old1", requester="bob", body="still true")
        assert reply["parent_id"] == "old1"
        names = {r[0] for r in sqlite3.connect(path).execute("SELECT name FROM schema_migrations")}
        assert {"0001_memos", "0002_memo_threads"} <= names


class TestReplies:
    def test_a_reply_follows_its_thread(self, td):
        root = note(td, visibility="shared")
        reply = reply_to(td, root["id"], requester="bob", body="agreed")
        assert (reply["instance_id"], reply["visibility"], reply["parent_id"]) == (
            "i1", "shared", root["id"])
        nested = reply_to(td, reply["id"], requester="carol", body="me too")
        assert nested["parent_id"] == root["id"]  # one level: replies join the root

    def test_replies_are_visible_exactly_when_the_root_is(self, td):
        root = note(td, visibility="shared")
        reply_to(td, root["id"], requester="bob", body="agreed")
        assert seen_by(td, "carol") == ["needs a look", "agreed"]
        update_memo(td, root["id"], requester="alice", visibility="private")
        assert seen_by(td, "carol") == []
        assert seen_by(td, "bob") == []  # bob's own reply goes with the thread
        assert seen_by(td, "adj", privileged=True) == ["needs a look", "agreed"]

    def test_nobody_replies_to_a_thread_they_cannot_see(self, td):
        root = note(td)  # private
        with pytest.raises(MemoNotFound):
            reply_to(td, root["id"], requester="bob", body="hello")

    def test_a_reply_keeps_the_thread_visibility(self, td):
        root = note(td, visibility="shared")
        reply = reply_to(td, root["id"], requester="bob", body="x")
        with pytest.raises(MemoError, match="thread's visibility"):
            update_memo(td, reply["id"], requester="bob", visibility="private")

    def test_deleting_the_first_memo_deletes_the_thread(self, td):
        root = note(td, visibility="shared")
        reply_to(td, root["id"], requester="bob", body="x")
        delete_memo(td, root["id"], requester="alice")
        assert seen_by(td, "alice", privileged=True) == []
        assert store._db(td).execute("SELECT COUNT(*) FROM memo_threads").fetchone()[0] == 0


class TestIssues:
    def test_status_by_author_assignee_or_adjudicator_only(self, td):
        issue = note(td, issue=True, assignee="bob", visibility="shared")
        assert (issue["status"], issue["assignee"]) == ("open", "bob")
        with pytest.raises(MemoPermissionError):
            set_status(td, issue["id"], requester="carol", status="resolved")
        done = set_status(td, issue["id"], requester="bob", status="resolved")
        assert (done["status"], done["resolved_by"]) == ("resolved", "bob")
        assert done["resolved_at"] > 0
        again = set_status(td, issue["id"], requester="adj", status="open", is_privileged=True)
        assert (again["status"], again["resolved_by"], again["resolved_at"]) == ("open", None, None)

    def test_assignment_by_author_or_adjudicator_only(self, td):
        issue = note(td, issue=True, visibility="shared")
        with pytest.raises(MemoPermissionError):
            set_assignee(td, issue["id"], requester="bob", assignee="bob")
        assert set_assignee(td, issue["id"], requester="alice", assignee="dana")["assignee"] == "dana"
        assert set_assignee(td, issue["id"], requester="alice", assignee="  ")["assignee"] is None
        with pytest.raises(MemoError, match="Only an issue"):
            set_assignee(td, note(td)["id"], requester="alice", assignee="dana")

    def test_the_assignee_of_a_private_issue_can_read_and_work_it(self, td):
        """Found by the potato-skill agent: assigned a private issue, mallory
        could resolve it (and got its body back) but not see it."""
        issue = note(td, issue=True, body="alice private issue")
        set_assignee(td, issue["id"], requester="alice", assignee="mallory")
        assert seen_by(td, "mallory") == ["alice private issue"]
        assert [m["id"] for m in list_issues(td, project="p", requester="mallory",
                                             assignee="mallory")] == [issue["id"]]
        reply_to(td, issue["id"], requester="mallory", body="on it")
        assert set_status(td, issue["id"], requester="mallory", status="resolved")["status"] == "resolved"
        # Unassigned again, the thread is private to alice once more.
        set_assignee(td, issue["id"], requester="alice", assignee="")
        assert seen_by(td, "mallory") == []
        for action in (lambda: set_status(td, issue["id"], requester="mallory", status="open"),
                       lambda: reply_to(td, issue["id"], requester="mallory", body="x"),
                       lambda: update_memo(td, issue["id"], requester="mallory", body="x"),
                       lambda: delete_memo(td, issue["id"], requester="mallory")):
            with pytest.raises(MemoNotFound):  # one answer for every action
                action()

    def test_replies_have_no_status(self, td):
        root = note(td, issue=True, visibility="shared")
        reply = reply_to(td, root["id"], requester="bob", body="fixed it")
        with pytest.raises(MemoError, match="first memo"):
            set_status(td, reply["id"], requester="bob", status="resolved")

    def test_the_issue_list_filters_and_respects_visibility(self, td):
        mine = note(td, issue=True, assignee="bob", visibility="shared")
        note(td, by="carol", issue=True)  # private to carol
        note(td, body="just a note", visibility="shared")
        set_status(td, mine["id"], requester="alice", status="resolved")
        assert [m["id"] for m in list_issues(td, project="p", requester="bob")] == [mine["id"]]
        assert list_issues(td, project="p", requester="bob", status="open") == []
        assert len(list_issues(td, project="p", requester="adj", is_privileged=True)) == 2
        [assigned] = list_issues(td, project="p", requester="bob", assignee="bob")
        assert assigned["can_resolve"] and not assigned["can_assign"]

    def test_permission_flags_follow_the_rules(self, td):
        issue = note(td, issue=True, visibility="shared")
        [as_author] = list_visible(td, project="p", instance_id="i1", requester="alice")
        [as_peer] = list_visible(td, project="p", instance_id="i1", requester="bob")
        assert (as_author["can_resolve"], as_author["can_assign"], as_author["can_edit"]) == (True, True, True)
        assert (as_peer["can_resolve"], as_peer["can_assign"], as_peer["can_delete"]) == (False, False, False)
        assert issue["id"] == as_peer["id"]


class TestShapeAnchors:
    SHAPE = {"schema": "objects", "type": "bbox", "label": "car",
             "coordinates": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.2}}

    def test_an_issue_on_a_drawn_shape(self, td):
        issue = note(td, issue=True, anchor={"shape": self.SHAPE})
        assert issue["anchor"] == {"shape": self.SHAPE}

    def test_an_incomplete_shape_is_refused(self, td):
        with pytest.raises(MemoError, match="schema, type and coordinates"):
            note(td, anchor={"shape": {"schema": "objects", "type": "bbox"}})
        with pytest.raises(MemoError):
            note(td, anchor={"label": "car"})


class TestQuotationExport:
    def test_replies_and_issues_are_labelled_and_replies_follow_the_root(self, td):
        from potato.export.base import ExportContext
        from potato.export.quotation_report_exporter import QuotationReportExporter
        root = note(td, issue=True, visibility="shared", body="unclear span")
        reply_to(td, root["id"], requester="bob", body="agreed")
        update_memo(td, root["id"], requester="alice", visibility="private")
        context = ExportContext(config={"task_dir": td, "annotation_task_name": "p"},
                                annotations=[], items={"i1": {"text": "hello"}},
                                schemas=[], output_dir=td)
        rows = QuotationReportExporter()._memo_rows(context, "text")
        assert [(r["schema"], r["text"], r["code"]) for r in rows] == [
            ("(issue: open)", "unclear span", "private"),
            ("(memo reply)", "agreed", "private")]
