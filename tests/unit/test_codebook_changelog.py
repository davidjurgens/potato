"""Phase 2 (C) change-provenance overlay: migration shape + the
change-log / proposal data layer. Append-only / merge / split / restamp
behaviours are exercised in the service-level tests once those ops land.
"""

import pytest

from potato.codebook import changelog
from potato.codebook.changelog import _CHANGE_MIGRATION
from potato.codebook.store import _CODEBOOK_MIGRATION
from potato.codebook.revision import (
    _CODES_REV_MIGRATION,
    _REVISION_MIGRATION,
)
from potato.codebook import clear_change_listeners
from potato.persistence import (
    clear_db_cache,
    clear_migrations,
    get_db,
    register_migration,
)


@pytest.fixture(autouse=True)
def _isolated_db():
    clear_db_cache()
    clear_migrations()
    # Strict registration order: 0001 CREATE -> 0002 ALTERs ->
    # 0003 ALTER+CREATE. 0003 ALTERs annotation_codes/codes so it MUST
    # come last.
    register_migration(_CODEBOOK_MIGRATION)
    register_migration(_REVISION_MIGRATION)
    register_migration(_CODES_REV_MIGRATION)
    register_migration(_CHANGE_MIGRATION)
    clear_change_listeners()
    yield
    clear_db_cache()
    clear_migrations()
    clear_change_listeners()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


def _cols(conn, table):
    return {r["name"] for r in conn.execute(
        "PRAGMA table_info(%s)" % table).fetchall()}


def _tables(conn):
    return {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


class TestMigrationShape:
    def test_validity_columns_added(self, td):
        conn = get_db(td)
        ac = _cols(conn, "annotation_codes")
        assert {"invalidated_at", "invalidated_by_change"} <= ac
        # existing trace-timing columns must be untouched
        assert {"started_at", "ended_at"} <= ac
        assert "archived_at" in _cols(conn, "codes")

    def test_overlay_tables_created(self, td):
        conn = get_db(td)
        t = _tables(conn)
        assert {"codebook_change", "codebook_proposal"} <= t

    def test_change_table_has_actor_kind(self, td):
        conn = get_db(td)
        assert {"actor", "actor_kind", "op", "old_value", "new_value"} \
            <= _cols(conn, "codebook_change")


class TestChangeLog:
    def test_log_and_changes_since(self, td):
        c1 = changelog.log_change(
            td, project="P", op="rename", actor="alice",
            code_id="x", old_value="cost", new_value="cost concerns",
            revision=5)
        assert isinstance(c1, str) and c1
        # recorded after revision 4, not after revision 5
        assert len(changelog.changes_since(td, "P", 4)) == 1
        assert changelog.changes_since(td, "P", 5) == []
        row = changelog.changes_since(td, "P", 0)[0]
        assert row["op"] == "rename"
        assert row["actor_kind"] == "human"
        assert row["new_value"] == "cost concerns"

    def test_all_changes_orders_by_time(self, td):
        changelog.log_change(td, project="P", op="merge", actor="a",
                             revision=1)
        changelog.log_change(td, project="P", op="split", actor="b",
                             actor_kind="model", revision=2)
        ops = [r["op"] for r in changelog.all_changes(td, "P")]
        assert ops == ["merge", "split"]


class TestProposals:
    def test_lifecycle(self, td):
        p = changelog.record_proposal(
            td, project="P", op="merge",
            payload={"src_id": "s", "dst_id": "d"}, actor="gpt-x")
        assert p["status"] == "pending"
        assert p["actor_kind"] == "model"
        assert p["payload"] == {"src_id": "s", "dst_id": "d"}
        assert [x["id"] for x in
                changelog.list_proposals(td, "P")] == [p["id"]]
        ok = changelog.set_proposal_status(
            td, p["id"], status="confirmed", decided_by="admin",
            change_id="chg1")
        assert ok
        assert changelog.list_proposals(td, "P") == []          # no pending
        done = changelog.get_proposal(td, p["id"])
        assert done["status"] == "confirmed"
        assert done["decided_by"] == "admin"
        assert done["change_id"] == "chg1"

    def test_double_decide_is_noop(self, td):
        p = changelog.record_proposal(
            td, project="P", op="rename", payload={}, actor="m")
        assert changelog.set_proposal_status(
            td, p["id"], status="confirmed", decided_by="admin")
        # already decided -> second transition refused
        assert not changelog.set_proposal_status(
            td, p["id"], status="rejected", decided_by="admin2")

    def test_propose_change_helper(self, td):
        p = changelog.propose_change(
            td, project="P", op="split",
            payload={"src_id": "s", "annotator": "bob"}, actor="llm")
        assert p["status"] == "pending" and p["op"] == "split"


def _link_count(td):
    from potato.persistence import get_db
    return get_db(td).execute(
        "SELECT COUNT(*) c FROM annotation_codes").fetchone()["c"]


class TestRetroactiveMerge:
    def _setup(self, td):
        from potato.codebook import create_code, apply_code
        a = create_code(td, project="P", name="cost", created_by="u")
        b = create_code(td, project="P", name="cost concerns",
                         created_by="u")
        # i1 already has BOTH a and b (the merge PK-collision case)
        apply_code(td, project="P", annotation_id="i1",
                   code_id=a["id"], created_by="alice")
        apply_code(td, project="P", annotation_id="i1",
                   code_id=b["id"], created_by="alice")
        apply_code(td, project="P", annotation_id="i2",
                   code_id=a["id"], created_by="bob")
        return a, b

    def test_merge_is_idempotent_and_append_only(self, td):
        from potato.codebook import merge_codes, codes_on, Codebook
        a, b = self._setup(td)
        before = _link_count(td)
        res = merge_codes(td, project="P", src_id=a["id"],
                          dst_id=b["id"], actor="admin")
        assert res["merged"] == 2
        # append-only: no annotation_codes row was deleted
        assert _link_count(td) >= before
        # i1: single live b, no a (idempotent vs pre-existing b)
        on1 = [c["code_id"] for c in codes_on(td, "i1")]
        assert on1 == [b["id"]]
        # i2: a's link re-pointed to b
        assert [c["code_id"] for c in codes_on(td, "i2")] == [b["id"]]
        # src archived -> gone from the label list / ICL prompt
        labels = Codebook.load(td, "P").labels()
        assert "cost" not in labels and "cost concerns" in labels

    def test_merge_logs_change_and_restamps(self, td):
        from potato.codebook import (merge_codes, record_annotation,
                                     stale_instances, current_revision)
        a, b = self._setup(td)
        # alice annotated i1 at the current revision
        record_annotation(td, "P", "i1", "alice")
        merge_codes(td, project="P", src_id=a["id"], dst_id=b["id"],
                    actor="admin")
        chs = changelog.changes_since(td, "P", 0)
        assert any(c["op"] == "merge" for c in chs)
        # i1 resurfaces in alice's review worklist (soft flag)
        stale = [s["instance_id"]
                 for s in stale_instances(td, "P", "alice")]
        assert "i1" in stale

    def test_merge_into_self_rejected(self, td):
        from potato.codebook import merge_codes, CodebookError
        a, _ = self._setup(td)
        with pytest.raises(CodebookError):
            merge_codes(td, project="P", src_id=a["id"],
                        dst_id=a["id"], actor="admin")


class TestRetroactiveSplitByAnnotator:
    def test_split_moves_only_that_annotator(self, td):
        from potato.codebook import (create_code, apply_code,
                                     split_code, codes_on, Codebook)
        s = create_code(td, project="P", name="trust", created_by="u")
        apply_code(td, project="P", annotation_id="i1",
                   code_id=s["id"], created_by="alice")
        apply_code(td, project="P", annotation_id="i2",
                   code_id=s["id"], created_by="bob")
        apply_code(td, project="P", annotation_id="i3",
                   code_id=s["id"], created_by="alice")
        res = split_code(td, project="P", src_id=s["id"],
                         annotator="alice", new_name="trust (alice)",
                         actor="admin")
        assert res["moved"] == 2
        tid = res["target_id"]
        # alice's instances now on the new code
        assert [c["code_id"] for c in codes_on(td, "i1")] == [tid]
        assert [c["code_id"] for c in codes_on(td, "i3")] == [tid]
        # bob's instance still on the original
        assert [c["code_id"] for c in codes_on(td, "i2")] == [s["id"]]
        # src still live (bob uses it) -> not archived
        assert "trust" in Codebook.load(td, "P").labels()


class TestICLIsolation:
    def test_labels_unaffected_by_overlay_tables(self, td):
        """The ICL prompt is built from Codebook.labels(); change-log /
        proposal / provenance rows must never leak into it."""
        from potato.codebook import create_code, Codebook
        create_code(td, project="P", name="alpha", created_by="u")
        changelog.log_change(td, project="P", op="rename",
                             actor="admin", old_value="x",
                             new_value="y", revision=9)
        changelog.record_proposal(td, project="P", op="merge",
                                  payload={"a": 1}, actor="m")
        assert Codebook.load(td, "P").labels() == ["alpha"]

